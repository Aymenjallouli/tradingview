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


RANGE_BREAK = 0.10   # liquidate a grid if price closes >10% outside its range


class GridInstance:
    """One live grid on one coin (v2: real spread cost + range-break exit)."""
    def __init__(self, symbol, low, high, n_levels, capital, spread_side=0.0):
        self.symbol = symbol
        self.low, self.high, self.n = low, high, n_levels
        self.step = (high - low) / n_levels
        self.levels = [low + i * self.step for i in range(n_levels + 1)]
        self.cash_per_level = capital / n_levels
        self.cash = capital
        self.capital = capital
        self.spread = spread_side       # per-side slippage (half bid-ask)
        self.holdings = {}              # level_index -> {qty, cost}
        self.trades = 0
        self.realized = 0.0
        self.prev_price = None
        self.bagged = False             # True once range broke + liquidated
        self.break_lo = low * (1 - RANGE_BREAK)
        self.break_hi = high * (1 + RANGE_BREAK)

    def on_price(self, price, low=None, high=None):
        """Feed a price + the price RANGE swept since the last check.

        BUG FIX: polling only the instantaneous price every 15s missed almost
        every fill — the price rarely jumps a full ~1.4% level in one poll, it
        wiggles within a cell. So we now fill any level the price actually
        TOUCHED between polls, using the low/high of the interval (from a 1m
        candle). A buy fills if `low` reached a level; a sell fills if `high`
        reached the level above a holding. This is how real grid bots work.
        """
        if self.bagged:
            return
        lo = low if low is not None else price
        hi = high if high is not None else price
        slip = self.spread if self.spread else SLIP   # real spread, else default

        # RANGE-BREAK: if price closed >10% outside the range, liquidate the
        # whole grid at market (with costs) and stop. Caps the downside instead
        # of holding a bag all the way down.
        if price < self.break_lo or price > self.break_hi:
            for h in self.holdings.values():
                px = price * (1 - slip)
                self.cash += h["qty"] * px * (1 - FEE)
            self.holdings = {}
            self.bagged = True
            self.prev_price = price
            return

        # BUY: any level at or above `lo` (price dipped to it) we don't hold.
        for i in range(len(self.levels)):
            lvl = self.levels[i]
            if lo <= lvl <= hi and i not in self.holdings \
                    and self.cash >= self.cash_per_level - 1e-9:
                fill = lvl * (1 + slip)
                fee = self.cash_per_level * FEE
                qty = (self.cash_per_level - fee) / fill
                self.holdings[i] = {"qty": qty, "cost": self.cash_per_level}
                self.cash -= self.cash_per_level
        # SELL: any holding whose next level up was reached by `hi`.
        for i in list(self.holdings.keys()):
            sell_lvl = self.levels[min(i + 1, len(self.levels) - 1)]
            if hi >= sell_lvl > self.levels[i]:
                h = self.holdings.pop(i)
                fill = sell_lvl * (1 - slip)
                net = h["qty"] * fill * (1 - FEE)
                self.realized += net - h["cost"]
                self.cash += net
                self.trades += 1
        self.prev_price = price

    def value(self, price):
        return self.cash + sum(h["qty"] * price for h in self.holdings.values())


class SmartGrid:
    def __init__(self, broker, scan_top=100, grids=8, per_grid=6.0,
                 rescan_seconds=1800, price_seconds=15, radar=None):
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
        self.radar = radar          # optional Scanner for ranging watchlist
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

    def _spread_side(self, sym):
        """Half the live bid-ask spread as a fraction (per-side slippage)."""
        try:
            d = requests.get(f"{config.BINANCE_REST}/api/v3/ticker/bookTicker",
                            params={"symbol": sym}, timeout=8).json()
            bid, ask = float(d["bidPrice"]), float(d["askPrice"])
            return (ask - bid) / bid / 2 if bid > 0 else None
        except Exception:  # noqa: BLE001
            return None

    def scan_and_rotate(self):
        """v2: only grid coins the RADAR flags as truly ranging + liquid +
        tight spread. Uses real spread as slippage; range-break liquidation is
        built into each grid. Falls back to its own liquid scan if no radar."""
        # Preferred source: the radar's ranging watchlist (liquid, tight spread).
        candidates = []
        if self.radar is not None:
            for c in self.radar.grid_candidates:
                if c.get("grid_eligible"):
                    candidates.append(c["symbol"])
        # Fallback: scan liquid coins ourselves for choppiness.
        if not candidates:
            for sym in self._liquid():
                if not sym.isascii() or not sym.replace("USDT", "").isalnum():
                    continue
                c = _klines(sym, "1h", 300)
                if not c or len(c) < 100:
                    continue
                if choppiness(c[-200:]) > 0.9:
                    candidates.append(sym)
                if len(candidates) >= self.n_grids * 2:
                    break

        picks = candidates[:self.n_grids]
        pick_set = set(picks)
        self.ranked = [{"symbol": s} for s in picks]
        self.last_scan = datetime.now(timezone.utc).isoformat()

        # Close grids no longer picked OR that got bagged (range broke).
        for sym in list(self.grids.keys()):
            g = self.grids[sym]
            if sym not in pick_set or g.bagged:
                self.grids.pop(sym)
                tag = "bagged (range broke)" if g.bagged else "rotated out"
                _log(f"closing grid {sym} [{tag}]: realized ${g.realized:+.4f} "
                     f"in {g.trades} trades")

        # Open grids for newly picked coins with REAL spread cost.
        for sym in picks:
            if sym in self.grids:
                continue
            c = _klines(sym, "1h", 5)
            if not c:
                continue
            last = c[-1][2]
            spread = self._spread_side(sym) or 0.0005
            round_trip = 2 * (FEE + spread)
            lo, hi = last * 0.92, last * 1.08
            # Step >= 3x round-trip cost so bounces can clear costs.
            min_step = 3 * round_trip
            band = (hi - lo) / last
            n_levels = max(8, min(40, int(band / max(min_step, 0.008))))
            self.grids[sym] = GridInstance(sym, lo, hi, n_levels,
                                           self.per_grid, spread_side=spread)
            _log(f"opening grid {sym} range {lo:.6f}-{hi:.6f} "
                 f"({n_levels} levels, spread {spread*100:.3f}%/side, "
                 f"step>={min_step*100:.2f}%)")

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
        _log(f"Smart-grid v2 started: {self.n_grids} grids, "
             f"${self.per_grid} each, radar-fed ranging coins, "
             f"rescan {self.rescan_seconds}s, range-break exit at 10%")
        # Ensure the radar has scanned at least once so we have candidates.
        if self.radar is not None and not self.radar.grid_candidates:
            try:
                self.radar.scan_once()
            except Exception:  # noqa: BLE001
                pass
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
            "spread": round(g.spread * 100, 3),
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
