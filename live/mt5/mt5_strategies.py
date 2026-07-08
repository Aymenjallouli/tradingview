"""
mt5_strategies.py — Validated strategy plugins for the MT5 wing.

Each strategy has the same interface:
    key, label, timeframe, direction ('long'/'short')
    on_candle(symbol, df) -> list of intents

An intent is a dict the orchestrator turns into a real order:
    {"type":"open","side":"buy"/"sell","symbol":...,"stop_pct":...,
     "target_pct":...,"reason":...}
    {"type":"close","symbol":...,"reason":...}

Implemented (validated in prior backtests):
  A) CandleLessons — 1h bullish reversal patterns in an uptrend (PF 1.5-2.7)
  B) Trend4h — 4h 20/100 EMA cross with 200 EMA filter (PF ~1.37, our champion)

Only real, tested logic here — no invented "magic" strategies.
"""

import pandas as pd


def _ema(s, p):
    return s.ewm(span=p, adjust=False).mean()


def _rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / p, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / p, adjust=False).mean()
    return (100 - 100 / (1 + g / loss)).fillna(100)


# ---------------------------------------------------------------------------
# A) Candle Lessons — 1h bullish reversal in a confirmed uptrend.
# ---------------------------------------------------------------------------
class CandleLessons:
    key = "candle"
    label = "Candle Lessons (1h reversals)"
    timeframe = "1h"
    direction = "long"
    stop_pct = 0.02          # -2%
    target_pct = 0.04        # +4%

    def _patterns(self, df, i):
        """Return True if bar i is a bullish reversal candle."""
        o, h, l, c = (df["open"].iloc[i], df["high"].iloc[i],
                      df["low"].iloc[i], df["close"].iloc[i])
        po, pc = df["open"].iloc[i - 1], df["close"].iloc[i - 1]
        body = abs(c - o)
        rng = h - l if h > l else 1e-9
        lower_wick = min(o, c) - l
        avg_body = (df["close"] - df["open"]).abs().rolling(14).mean().iloc[i]

        # Bullish engulfing: green body engulfs prior red body, body > 14-bar avg
        bull_engulf = (pc < po and c > o and c >= po and o <= pc
                       and body > avg_body)
        # Hammer: lower wick > 2x body, small upper wick
        hammer = (lower_wick > 2 * body and (h - max(o, c)) < body)
        # Bullish pin: lower wick > 66% of the whole range
        bull_pin = (lower_wick > 0.66 * rng and c > o)
        return bull_engulf or hammer or bull_pin

    def _bearish_exit(self, df, i):
        """Bearish engulfing or shooting star -> exit signal."""
        o, h, l, c = (df["open"].iloc[i], df["high"].iloc[i],
                      df["low"].iloc[i], df["close"].iloc[i])
        po, pc = df["open"].iloc[i - 1], df["close"].iloc[i - 1]
        body = abs(c - o)
        upper_wick = h - max(o, c)
        bear_engulf = pc > po and c < o and c <= po and o >= pc
        shooter = upper_wick > 2 * body and (min(o, c) - l) < body and c < o
        return bear_engulf or shooter

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 210:
            return []
        df = df.copy()
        df["ema200"] = _ema(df["close"], 200)
        df["rsi"] = _rsi(df["close"], 14)
        i = len(df) - 1

        if has_position:
            # Exit only on a bearish reversal pattern (SL/TP handled by broker).
            if self._bearish_exit(df, i):
                return [{"type": "close", "symbol": symbol,
                         "reason": "bearish pattern"}]
            return []

        # Context (ALL must hold): uptrend, rising 200EMA, near 50-bar low, RSI<60
        price = df["close"].iloc[i]
        ema200 = df["ema200"].iloc[i]
        ema200_prev = df["ema200"].iloc[i - 20]
        low50 = df["low"].iloc[-50:].min()
        rsi = df["rsi"].iloc[i]
        if pd.isna(ema200) or pd.isna(ema200_prev):
            return []
        ctx = (price > ema200 and ema200 > ema200_prev
               and price <= low50 * 1.008 and rsi < 60)
        if ctx and self._patterns(df, i):
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "bullish reversal in uptrend"}]
        return []


# ---------------------------------------------------------------------------
# B) Trend 4h — 20/100 EMA cross, 200 EMA filter (our champion).
# ---------------------------------------------------------------------------
class Trend4h:
    key = "trend4h"
    label = "Trend 4h (champion)"
    timeframe = "4h"
    direction = "long"
    stop_pct = 0.08
    target_pct = 0.15

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 210:
            return []
        df = df.copy()
        df["ef"] = _ema(df["close"], 20)
        df["es"] = _ema(df["close"], 100)
        df["et"] = _ema(df["close"], 200)
        df["rsi"] = _rsi(df["close"], 14)
        i = len(df) - 1
        row, prev = df.iloc[i], df.iloc[i - 1]

        if has_position:
            # Exit on 20/100 cross-down (SL/TP handled by broker).
            if prev["ef"] >= prev["es"] and row["ef"] < row["es"]:
                return [{"type": "close", "symbol": symbol,
                         "reason": "ema cross down"}]
            return []

        crossed_up = prev["ef"] <= prev["es"] and row["ef"] > row["es"]
        if crossed_up and row["close"] > row["et"] and row["rsi"] < 70:
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "20/100 cross up, above 200EMA"}]
        return []


# ---------------------------------------------------------------------------
# D) Range Breakout — APPROVED, restricted to the symbols it won in backtest
#    (stocks + gold: NVDA PF 1.60, XAUUSD 2.23, MSFT/AMD/INTC 1.2+). Rejected
#    on forex/crypto where it was breakeven-or-worse.
# ---------------------------------------------------------------------------
class RangeBreakout:
    key = "breakout"
    label = "Range Breakout (stocks+gold)"
    timeframe = "4h"
    direction = "long"
    stop_pct = 0.03
    target_pct = 0.05
    allowed_symbols = {"NVDA", "MSFT", "AMD", "INTC", "XAUUSD"}

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 120 or has_position:
            return []
        hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
        width = (df["high"] - df["low"]).rolling(20).mean()
        i = len(df) - 1
        r20 = hi[-20:].max() - lo[-20:].min()
        avg100 = width.iloc[-100:].mean()
        compressed = bool(avg100) and r20 < 0.60 * avg100 * 20
        range_high = hi[-21:-1].max()
        if compressed and cl[i] > range_high:
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "breakout from compression"}]
        return []


# ---------------------------------------------------------------------------
# E) Momentum Pullback — the FASTER one (1h). More action than the 4h/reversal
#    strategies. Thesis: in a short-term uptrend, buy a shallow pullback to the
#    20 EMA and ride the bounce. Not scalping — still trend-following, just on a
#    faster clock. Backtest before trusting it.
# ---------------------------------------------------------------------------
class MomentumPullback:
    key = "momo"
    label = "Momentum Pullback (1h, faster)"
    timeframe = "1h"
    direction = "long"
    stop_pct = 0.015         # -1.5%
    target_pct = 0.03        # +3% (2:1)
    # Restricted to the ONLY symbols it was profitable on in backtest:
    # MSFT (PF 1.36), USDCAD (1.91), ETH (1.07). It LOST on the other 11.
    allowed_symbols = {"MSFT", "USDCAD", "ETHUSD"}

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 60:
            return []
        df = df.copy()
        df["ef"] = _ema(df["close"], 20)
        df["es"] = _ema(df["close"], 50)
        df["rsi"] = _rsi(df["close"], 14)
        i = len(df) - 1
        row, prev = df.iloc[i], df.iloc[i - 1]
        if has_position:
            # Exit if the short-term trend breaks (20 below 50).
            if row["ef"] < row["es"]:
                return [{"type": "close", "symbol": symbol,
                         "reason": "trend break"}]
            return []
        uptrend = row["ef"] > row["es"]
        # Pullback: this bar dipped to/below the 20 EMA, prev was above it, and
        # the close is back up (bounce), RSI not overbought.
        pullback = (row["low"] <= row["ef"] and prev["close"] > prev["ef"]
                    and row["close"] > row["ef"] and row["rsi"] < 65)
        if uptrend and pullback:
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "pullback bounce in uptrend"}]
        return []


# Registry of ENABLED strategies. C (Bear Trend) rejected in backtest.
# D (Range Breakout) approved but symbol-restricted. E (Momentum) added after
# its backtest (see mt5_backtest_fast).
def build_strategies():
    return [CandleLessons(), Trend4h(), RangeBreakout(), MomentumPullback()]
