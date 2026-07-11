"""
mt5_patterns.py — Pattern Detection Engine (geometry from real OHLC, not pixels).

Computes chart-pattern GEOMETRY from MT5 candle numbers — swing highs/lows,
necklines, trendlines, symmetry — and when a pattern's rules are met, produces a
full trade card (entry / stop / target sized from the pattern's own structure).

DETECTION is unlimited (it sees every pattern forming, on every allowed
symbol/timeframe). EXECUTION is earned: only pattern+timeframe combos that
PASSED their backtest with a real edge are allowed to open a position. The rest
are logged as "detected but not traded" — a radar, not a trigger.

Backtested (cost-included, gold/silver, 1h+4h):
  * Double Bottom  — PAYS: silver 1h 2.23 (76% win), gold 4h 1.64, gold 1h 1.43
  * Asc Triangle   — PAYS: gold 4h 3.19 (79% win!), silver 1h 2.96
  * Double Top     — REJECTED (gold 4h PF 0.67; metals drift up, shorts lose)

Each detected pattern that clears its whitelist emits a standard OPEN intent
(entry at breakout, stop from the structure, target = pattern height projected),
so it flows through the same risk governor + conviction sizing as every other
strategy.
"""

import numpy as np
import pandas as pd


def _swings(h, l, k=3):
    hi, lo = [], []
    n = len(h)
    for i in range(k, n - k):
        if h[i] == max(h[i - k:i + k + 1]):
            hi.append(i)
        if l[i] == min(l[i - k:i + k + 1]):
            lo.append(i)
    return hi, lo


class PatternEngine:
    """One strategy object that detects several patterns and only TRADES the
    whitelisted (backtest-proven) pattern+timeframe combos."""
    key = "pattern"
    label = "Pattern Engine (geometry)"
    timeframe = "4h"                 # default; run instances per timeframe
    direction = "long"
    allowed_symbols = {"XAUUSD", "XAGUSD"}

    # Which pattern+timeframe combos passed the backtest (only these TRADE).
    # (pattern, timeframe) -> True.  Detection happens for all; trade only these.
    TRADE_WHITELIST = {
        ("double_bottom", "1h"), ("double_bottom", "4h"),
        ("asc_triangle", "1h"), ("asc_triangle", "4h"),
        # double_top intentionally absent — it lost in backtest.
    }

    def __init__(self, timeframe="4h"):
        self.timeframe = timeframe
        self.last_detections = []     # for the dashboard "radar" (all, incl. non-traded)

    # ---- pattern detectors: return (found, entry, stop, target, name) ----
    def _double_bottom(self, h, l, c, tol=0.01, look=60):
        _, lo = _swings(h, l, 3)
        i = len(c) - 1
        recent = [x for x in lo if i - look <= x < i - 1]
        if len(recent) < 2:
            return None
        ib = recent[-1]
        for ia in recent[:-1][::-1]:
            if ib - ia < 5:
                continue
            la, lb = l[ia], l[ib]
            if abs(la - lb) / la > tol:
                continue
            peak = h[ia:ib].max()
            base = min(la, lb)
            height = peak - base
            if height <= 0:
                continue
            # breakout: current close just crossed above the neckline
            if c[i] > peak and c[i - 1] <= peak:
                entry = c[i]
                return ("double_bottom", "buy", entry, base * (1 - 0.003),
                        entry + height)
        return None

    def _asc_triangle(self, h, l, c, look=40):
        hi, lo = _swings(h, l, 3)
        i = len(c) - 1
        wh = [x for x in hi if i - look <= x < i]
        wl = [x for x in lo if i - look <= x < i]
        if len(wh) < 2 or len(wl) < 2:
            return None
        highs = [h[x] for x in wh]
        res = float(np.mean(highs))
        if np.std(highs) / res > 0.004:
            return None
        lows = [l[x] for x in wl]
        if lows[-1] <= lows[0]:
            return None
        height = res - min(lows)
        if height <= 0:
            return None
        if c[i] > res and c[i - 1] <= res:
            entry = c[i]
            return ("asc_triangle", "buy", entry, min(lows) * (1 - 0.003),
                    entry + height)
        return None

    def _double_top(self, h, l, c, tol=0.01, look=60):
        # Detected for the radar but NOT whitelisted to trade (backtest loser).
        hi, _ = _swings(h, l, 3)
        i = len(c) - 1
        recent = [x for x in hi if i - look <= x < i - 1]
        if len(recent) < 2:
            return None
        ib = recent[-1]
        for ia in recent[:-1][::-1]:
            if ib - ia < 5:
                continue
            ha, hb = h[ia], h[ib]
            if abs(ha - hb) / ha > tol:
                continue
            trough = l[ia:ib].min()
            top = max(ha, hb)
            height = top - trough
            if height <= 0:
                continue
            if c[i] < trough and c[i - 1] >= trough:
                entry = c[i]
                return ("double_top", "sell", entry, top * (1 + 0.003),
                        entry - height)
        return None

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 80:
            return []
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values
        if has_position:
            return []                # exits handled by broker SL/TP

        detected = []
        for det in (self._double_bottom, self._asc_triangle, self._double_top):
            res = det(h, l, c)
            if res:
                detected.append(res)

        self.last_detections = [{"pattern": d[0], "side": d[1]} for d in detected]

        # Trade only the whitelisted (backtest-proven) pattern+timeframe combos.
        for name, side, entry, stop, target in detected:
            if (name, self.timeframe) not in self.TRADE_WHITELIST:
                continue                  # detected but not traded (no proven edge)
            if entry <= 0 or stop <= 0 or target <= 0:
                continue
            stop_pct = abs(entry - stop) / entry
            target_pct = abs(target - entry) / entry
            # sanity: skip absurd geometry
            if stop_pct > 0.15 or target_pct > 0.5 or stop_pct <= 0:
                continue
            return [{"type": "open", "side": side, "symbol": symbol,
                     "stop_pct": stop_pct, "target_pct": target_pct,
                     "reason": f"pattern: {name} ({self.timeframe})"}]
        return []
