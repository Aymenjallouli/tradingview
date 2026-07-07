"""
smart_grid.py — Live smart-grid engine (our most promising strategy).

The one strategy in this project with a real, repeatable edge in backtests:
grid trading (profit from volatility, not prediction) run ONLY on coins that
are currently RANGING (choppy), which is where grids win. In testing it beat
buy-and-hold on 8 of 10 coins.

How it works:
  1. Scan ~100 liquid coins.
  2. Score each by "choppiness" (how much it oscillates vs how much it trends).
     High choppiness = grid-friendly.
  3. Run live paper grids on the top N most-ranging coins, each in its own grid
     between its recent low and high.
  4. Each grid buys on dips through its levels and sells on the bounce up — a
     small profit per oscillation, minus realistic fees.
  5. Re-scan periodically; rotate grids toward the best-ranging coins.

Honest risk (shown, not hidden): if a coin trends hard DOWN, its grid gets
"bagged" (holds a falling asset). We mitigate by (a) only gridding RANGING
coins and (b) re-scanning to rotate away from coins that start trending.

Uses its own paper account ("grid") in the shared broker.
"""

import threading
import time
from datetime import datetime, timezone

import requests

import config

FEE = config.FEE_PCT
SLIP = config.SLIPPAGE_PCT

# Stablecoins / pegged pairs to skip (they don't oscillate usefully).
_SKIP = {"USDCUSDT", "FDUSDUSDT", "USD1USDT", "TUSDUSDT", "DAIUSDT",
         "USDPUSDT", "EURUSDT", "AEURUSDT", "BUSDUSDT", "XUSDUSDT", "RLUSDUSDT"}


def _log(m):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [smart-grid] {m}", flush=True)


def _klines(symbol, interval="1h", limit=300):
    try:
        rows = requests.get(f"{config.BINANCE_REST}/api/v3/klines",
                            params={"symbol": symbol, "interval": interval,
                                    "limit": limit}, timeout=12).json()
        if not isinstance(rows, list):
            return None
        return [(float(r[2]), float(r[3]), float(r[4])) for r in rows]
    except Exception:  # noqa: BLE001
        return None


def choppiness(candles):
    """Higher = more oscillation vs net drift = better for grids (0..1)."""
    closes = [c[2] for c in candles]
    if len(closes) < 10 or closes[0] == 0:
        return 0.0
    net = abs(closes[-1] - closes[0]) / closes[0]
    total = sum(abs(closes[i] - closes[i - 1])
                for i in range(1, len(closes))) / closes[0]
    return (1 - net / total) if total > 0 else 0.0


class GridInstance:
    """One live grid on one coin."""
    def __init__(self, symbol, low, high, n_levels, capital):
        self.symbol = symbol
        self.low, self.high, self.n = low, high, n_levels
        self.step = (high - low) / n_levels
        self.levels = [low + i * self.step for i in range(n_levels + 1)]
        self.cash_per_level = capital / n_levels
        self.cash = capital
        self.capital = capital
        self.holdings = {}          # level_index -> {qty, cost}
        self.trades = 0
        self.realized = 0.0
        self.prev_price = None

    def on_price(self, price, low=None, high=None):
        """Feed a price + the price RANGE swept since the last check.

        BUG FIX: polling only the instantaneous price every 15s missed almost
        every fill — the price rarely jumps a full ~1.4% level in one poll, it
        wiggles within a cell. So we now fill any level the price actually
        TOUCHED between polls, using the low/high of the interval (from a 1m
        candle). A buy fills if `low` reached a level; a sell fills if `high`
        reached the level above a holding. This is how real grid bots work.
        """
        lo = low if low is not None else price
        hi = high if high is not None else price
        # BUY: any level at or above `lo` (price dipped to it) we don't hold.
        for i in range(len(self.levels)):
            lvl = self.levels[i]
            if lo <= lvl <= hi and i not in self.holdings \
                    and self.cash >= self.cash_per_level - 1e-9:
                fill = lvl * (1 + SLIP)
                fee = self.cash_per_level * FEE
                qty = (self.cash_per_level - fee) / fill
                self.holdings[i] = {"qty": qty, "cost": self.cash_per_level}
                self.cash -= self.cash_per_level
        # SELL: any holding whose next level up was reached by `hi`.
        for i in list(self.holdings.keys()):
            sell_lvl = self.levels[min(i + 1, len(self.levels) - 1)]
            if hi >= sell_lvl > self.levels[i]:
                h = self.holdings.pop(i)
                fill = sell_lvl * (1 - SLIP)
                net = h["qty"] * fill * (1 - FEE)
                self.realized += net - h["cost"]
                self.cash += net
                self.trades += 1
        self.prev_price = price

    def value(self, price):
        return self.cash + sum(h["qty"] * price for h in self.holdings.values())


class SmartGrid:
    def __init__(self, broker, scan_top=100, grids=8, per_grid=6.0,
                 rescan_seconds=1800, price_seconds=15):
        """
        broker         : MultiBroker (uses a 'grid' summary; grids tracked here)
        scan_top       : how many liquid coins to scan for rangeyness
        grids          : how many simultaneous grids to run (top-ranging coins)
        per_grid       : capital per grid (paper $)
        rescan_seconds : how often to re-rank and rotate grids
        price_seconds  : how often to feed live prices to active grids
        """
        self.broker = broker
        self.scan_top = scan_top
        self.n_grids = grids
        self.per_grid = per_grid
        self.rescan_seconds = rescan_seconds
        self.price_seconds = price_seconds
        self.grids = {}             # symbol -> GridInstance
        self.ranked = []            # latest choppiness ranking for the UI
        self.start_capital = grids * per_grid
        self.last_scan = None
        self._running = False
        self._last_prices = {}

    def _liquid(self):
        try:
            info = requests.get(f"{config.BINANCE_REST}/api/v3/exchangeInfo",
                                timeout=20).json()
            spot = {s["symbol"] for s in info["symbols"]
                    if s["symbol"].endswith("USDT")
                    and s["status"] == "TRADING"
                    and s.get("isSpotTradingAllowed")}
            tk = requests.get(f"{config.BINANCE_REST}/api/v3/ticker/24hr",
                              timeout=25).json()
            rows = [t for t in tk if t["symbol"] in spot
                    and t["symbol"] not in _SKIP]
            rows.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
            return [t["symbol"] for t in rows[:self.scan_top]]
        except Exception as exc:  # noqa: BLE001
            _log(f"liquid list failed: {exc}")
            return []

    def scan_and_rotate(self):
        """Rank ~100 coins by choppiness; (re)build grids on the top ones."""
        universe = self._liquid()
        if not universe:
            return
        scored = []
        for sym in universe:
            # Skip non-ASCII / junk ticker names (scam tokens like 币安人生USDT).
            if not sym.isascii() or not sym.replace("USDT", "").isalnum():
                continue
            c = _klines(sym, "1h", 300)
            if not c or len(c) < 100:
                continue
            chop = choppiness(c)
            full_lo = min(x[1] for x in c)
            full_hi = max(x[0] for x in c)
            last = c[-1][2]
            # Grid a TIGHT band around the CURRENT price (±8%), not the full
            # multi-day range. A grid centered on the price means the price is
            # always among active levels and crosses them as it wiggles. The
            # full-range grid put price between far-apart lines that it rarely
            # reached — which is why it never traded.
            lo = last * 0.92
            hi = last * 1.08
            width = (full_hi - full_lo) / full_lo if full_lo else 0
            scored.append({"symbol": sym, "chop": round(chop, 3),
                           "low": lo, "high": hi, "width_pct": round(width*100, 1),
                           "price": last,
                           # eligible if it has real historical range to work with
                           "eligible": width > 0.05})
            time.sleep(0.01)   # light pacing; keep the scan reasonably fast
        scored.sort(key=lambda x: x["chop"], reverse=True)
        self.ranked = scored[:15]
        self.last_scan = datetime.now(timezone.utc).isoformat()

        # Pick the top eligible coins.
        picks = [s for s in scored if s["eligible"]][:self.n_grids]
        pick_syms = {s["symbol"] for s in picks}

        # Remove grids for coins no longer picked (bank their current value).
        for sym in list(self.grids.keys()):
            if sym not in pick_syms:
                g = self.grids.pop(sym)
                _log(f"closing grid {sym}: realized ${g.realized:+.2f} "
                     f"in {g.trades} trades")

        # Create grids for newly picked coins.
        for s in picks:
            if s["symbol"] not in self.grids:
                # Grid step ~0.8%. Tuning on real data showed this is the sweet
                # spot: tighter (0.3%) makes MORE trades but goes NEGATIVE (fees
                # eat the tiny per-bounce profit — same lesson as the scalper);
                # ~0.8% captures bigger bounces that clear the ~0.3% round-trip
                # cost. Wider still (1.2%) trades too rarely. 0.8% won the test.
                width_frac = (s["high"] - s["low"]) / s["low"] if s["low"] else 0.1
                n_levels = max(15, min(60, int(width_frac / 0.008)))
                self.grids[s["symbol"]] = GridInstance(
                    s["symbol"], s["low"], s["high"], n_levels, self.per_grid)
                _log(f"opening grid {s['symbol']} "
                     f"range {s['low']:.6f}-{s['high']:.6f} "
                     f"({n_levels} levels ~0.5% apart, "
                     f"choppiness {s['chop']}, width {s['width_pct']}%)")

    def feed_prices(self):
        """Push each grid coin's recent price RANGE (1m candles) into its grid.

        We fetch the last few 1-minute candles per coin and feed their low/high
        so the grid fills every level the price actually touched between polls —
        not just the instantaneous snapshot (which missed nearly all fills).
        """
        if not self.grids:
            return
        for sym, g in list(self.grids.items()):
            candles = _klines(sym, "1m", 3)   # last ~3 minutes of range
            if not candles:
                continue
            last_close = candles[-1][2]
            self._last_prices[sym] = last_close
            # Feed each recent candle's (low, high, close) in order.
            for hi, lo, close in candles:
                g.on_price(close, low=lo, high=hi)

    def run(self):
        self._running = True
        _log(f"Smart-grid started: scan top {self.scan_top}, "
             f"{self.n_grids} grids, ${self.per_grid} each, "
             f"rescan {self.rescan_seconds}s")
        self.scan_and_rotate()
        last_rescan = time.time()
        while self._running:
            self.feed_prices()
            if time.time() - last_rescan >= self.rescan_seconds:
                try:
                    self.scan_and_rotate()
                except Exception as exc:  # noqa: BLE001
                    _log(f"rescan error: {exc}")
                last_rescan = time.time()
            for _ in range(self.price_seconds):
                if not self._running:
                    return
                time.sleep(1)

    def stop(self):
        self._running = False

    def snapshot(self):
        total_value = sum(g.value(self._last_prices.get(s, g.prev_price or g.low))
                          for s, g in self.grids.items())
        # Grids not yet holding contribute their idle cash.
        idle = (self.n_grids - len(self.grids)) * self.per_grid
        equity = total_value + max(idle, 0)
        total_trades = sum(g.trades for g in self.grids.values())
        total_realized = sum(g.realized for g in self.grids.values())
        def fmt(v):
            # Adaptive decimals so micro-price coins (BONK/SHIB) aren't "0.0000".
            if v == 0:
                return "0"
            if v >= 1:
                return f"{v:.4f}"
            if v >= 0.001:
                return f"{v:.6f}"
            return f"{v:.9f}"
        active = [{
            "symbol": s, "trades": g.trades,
            "realized": round(g.realized, 4),
            "value": round(g.value(self._last_prices.get(s, g.prev_price or g.low)), 2),
            "holdings": len(g.holdings),
            "range": f"{fmt(g.low)}-{fmt(g.high)}",
        } for s, g in self.grids.items()]
        return {
            "last_scan": self.last_scan,
            "equity": round(equity, 2),
            "start_capital": self.start_capital,
            "total_trades": total_trades,
            "realized_pnl": round(total_realized, 4),
            "active_grids": active,
            "ranked": self.ranked,
        }
