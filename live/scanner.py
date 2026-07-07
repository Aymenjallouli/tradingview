"""
scanner.py — Multi-market scanner (tests the "scan many markets" theory).

What it does:
  1. Pulls the most LIQUID crypto markets from Binance (top N by 24h volume,
     skipping stablecoins that don't move).
  2. For each, fetches recent candles and scores it with the SAME strategy
     signals the focused strategies use (a trend/pullback score).
  3. Ranks markets by signal strength and PAPER-TRADES the strongest ones into
     the scanner's own account.

Why this is built as an experiment, not a money machine:
  Scanning hundreds of markets and acting on whatever "looks best right now" is
  the classic data-snooping trap — with enough markets, something ALWAYS looks
  great by pure chance. So this doesn't assume it works; it MEASURES it with
  paper money. If scanning across many markets beats trading a few, the
  scanner's equity will show it. If it's just noise (likely), that shows too.

Runs on a slow cadence (every few minutes) — it's a scan, not a tick engine.
"""

import time
from datetime import datetime, timezone

import pandas as pd
import requests

import config


def _log(m):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [scanner] {m}", flush=True)


# Stablecoins / wrapped pairs that barely move — exclude from scanning.
_SKIP = {"USDCUSDT", "USD1USDT", "RLUSDUSDT", "TUSDUSDT", "FDUSDUSDT",
         "BUSDUSDT", "DAIUSDT", "USDPUSDT", "EURUSDT", "AEURUSDT"}


def _ema(s, p):
    return s.ewm(span=p, adjust=False).mean()


def _rsi(s, p):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / p, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / p, adjust=False).mean()
    return (100 - 100 / (1 + g / loss)).fillna(100)


class Scanner:
    def __init__(self, broker, top_n=40, hold_slots=5, timeframe="15m",
                 scan_seconds=300):
        """
        broker      : the MultiBroker (uses account key 'scanner')
        top_n       : how many liquid markets to scan
        hold_slots  : max simultaneous paper positions
        timeframe   : candle interval to score on
        scan_seconds: seconds between scans
        """
        self.broker = broker
        self.top_n = top_n
        self.hold_slots = hold_slots
        self.timeframe = timeframe
        self.scan_seconds = scan_seconds
        self.broker.ensure_account("scanner")
        self.universe = []          # current scanned symbols
        self.ranked = []            # latest ranked results (for the dashboard)
        self.last_scan = None
        self._running = False
        self._last_prices = {}

    # ------------------------------------------------------------------
    def _liquid_markets(self):
        """Top N USDT spot pairs by 24h quote volume (minus stablecoins)."""
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
            return [t["symbol"] for t in rows[:self.top_n]]
        except Exception as exc:  # noqa: BLE001
            _log(f"market list failed: {exc}")
            return []

    def _score(self, sym):
        """Fetch candles and return a signal dict, or None.

        Score = a simple trend-pullback read (same family as the live
        strategies): price above its long EMA (uptrend), pulling back toward the
        fast EMA, RSI not overbought. Higher score = stronger setup.
        """
        try:
            rows = requests.get(
                f"{config.BINANCE_REST}/api/v3/klines",
                params={"symbol": sym, "interval": self.timeframe,
                        "limit": 250}, timeout=15).json()
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(rows, list) or len(rows) < 210:
            return None
        close = pd.Series([float(r[4]) for r in rows])
        ema_fast = _ema(close, 20)
        ema_slow = _ema(close, 50)
        ema_trend = _ema(close, 200)
        rsi = _rsi(close, 14)
        price = float(close.iloc[-1])
        self._last_prices[sym] = price

        ef, es, et, r = (float(ema_fast.iloc[-1]), float(ema_slow.iloc[-1]),
                         float(ema_trend.iloc[-1]), float(rsi.iloc[-1]))
        uptrend = ef > es and price > et
        if not uptrend:
            return {"symbol": sym, "price": price, "score": 0.0,
                    "rsi": round(r, 1), "reason": "no uptrend"}
        # Distance of price below the fast EMA = pullback depth (a dip in an
        # uptrend). Reward moderate pullbacks with healthy RSI.
        pullback = max(0.0, (ef - price) / ef)          # 0 if above fast EMA
        rsi_ok = 40 <= r <= 65
        score = (pullback * 100) + (10 if rsi_ok else 0) + \
                ((et and (price - et) / et) * 5)         # trend strength bonus
        return {"symbol": sym, "price": price, "score": round(score, 2),
                "rsi": round(r, 1),
                "reason": "uptrend pullback" if pullback > 0 else "uptrend"}

    # ------------------------------------------------------------------
    def scan_once(self):
        """One full scan: rank markets, then paper-trade the top signals."""
        universe = self._liquid_markets()
        if not universe:
            return
        self.universe = universe
        results = []
        for sym in universe:
            s = self._score(sym)
            if s:
                results.append(s)
            time.sleep(0.05)   # be polite to the API
        results.sort(key=lambda x: x["score"], reverse=True)
        self.ranked = results[:15]
        self.last_scan = datetime.now(timezone.utc).isoformat()

        # --- Exit any held positions that no longer rank / hit stop/target ---
        from engine import crypto_cost  # reuse the same cost model
        held = {p["symbol"]: p for p in self.broker.open_positions("scanner")}
        strong = {r["symbol"] for r in results if r["score"] > 5}
        for sym, pos in held.items():
            price = self._last_prices.get(sym, pos["entry_price"])
            entry = pos["entry_price"]
            reason = None
            if price <= entry * 0.97:
                reason = "stop_loss"        # -3%
            elif price >= entry * 1.05:
                reason = "take_profit"      # +5%
            elif sym not in strong:
                reason = "signal_gone"      # no longer a strong setup
            if reason:
                self.broker.sell("scanner", sym, price, reason, crypto_cost)
                _log(f"SELL {sym} @ {price:.6f} ({reason})")

        # --- Open new positions in the strongest fresh signals ---------------
        open_now = {p["symbol"] for p in self.broker.open_positions("scanner")}
        slots = self.hold_slots - len(open_now)
        for r in results:
            if slots <= 0:
                break
            if r["score"] <= 5 or r["symbol"] in open_now:
                continue
            price = r["price"]
            res = self.broker.buy("scanner", r["symbol"], price,
                                  size_pct=0.18, cost_fn=crypto_cost)
            if res:
                _log(f"BUY {r['symbol']} @ {price:.6f} (score {r['score']})")
                slots -= 1

    def _realtime_exit_check(self):
        """Near-realtime exit guard for HELD positions (runs every 2s).

        Scanning 40 markets is periodic, but EXITS must be fast — a late stop
        loss is what loses money if you ever go to real funds. So this checks
        live prices on just the positions we hold every 2 seconds and fires the
        stop/target immediately, synchronized with the real market price.
        """
        from engine import crypto_cost
        while self._running:
            try:
                held = self.broker.open_positions("scanner")
                if held:
                    syms = [p["symbol"] for p in held]
                    # One lightweight call for all held symbols' live prices.
                    import json as _json
                    resp = requests.get(
                        f"{config.BINANCE_REST}/api/v3/ticker/price",
                        params={"symbols": _json.dumps(syms)}, timeout=10)
                    prices = {d["symbol"]: float(d["price"])
                              for d in resp.json()}
                    for pos in held:
                        sym = pos["symbol"]
                        price = prices.get(sym)
                        if price is None:
                            continue
                        self._last_prices[sym] = price
                        entry = pos["entry_price"]
                        reason = None
                        if price <= entry * 0.97:
                            reason = "stop_loss"
                        elif price >= entry * 1.05:
                            reason = "take_profit"
                        if reason:
                            self.broker.sell("scanner", sym, price, reason,
                                             crypto_cost)
                            _log(f"REALTIME-EXIT {sym} @ {price:.6f} ({reason})")
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2)

    def run(self):
        self._running = True
        _log(f"Scanner started: top {self.top_n} markets, {self.timeframe}, "
             f"{self.hold_slots} slots, scan every {self.scan_seconds}s, "
             f"exits checked every 2s (near-realtime)")
        # Start the fast exit-guard in its own thread.
        import threading
        threading.Thread(target=self._realtime_exit_check, daemon=True).start()
        while self._running:
            try:
                self.scan_once()
            except Exception as exc:  # noqa: BLE001
                _log(f"scan error: {exc}")
            for _ in range(self.scan_seconds):
                if not self._running:
                    return
                time.sleep(1)

    def stop(self):
        self._running = False

    def snapshot(self):
        return {
            "last_scan": self.last_scan,
            "universe_size": len(self.universe),
            "ranked": self.ranked,
        }
