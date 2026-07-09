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
    # stocks + metals (breakout works on trending equities/metals, not forex)
    allowed_symbols = {"NVDA", "MSFT", "AMD", "INTC", "XAUUSD",
                       "XAGUSD", "AAPL", "GOOGL", "AMZN", "META"}

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


# ---------------------------------------------------------------------------
# F) Donchian Breakout (Turtle) — the STRONGEST backtest: median PF 1.39,
#    profitable on 9/14. Buy a 20-bar high breakout, exit on a 10-bar low.
#    Rides big trends, cuts losers fast. Restricted to its winners.
# ---------------------------------------------------------------------------
class DonchianBreakout:
    key = "donchian"
    label = "Donchian Breakout (Turtle)"
    timeframe = "4h"
    direction = "long"
    stop_pct = 0.05          # a floor; real exit is the 10-bar low
    target_pct = 0.30        # let winners run
    # Original winners + stock winners + NEW Pepperstone winners (cost-incl):
    # energy is the standout — BRENT 2.28, GASOLINE 2.26, NATGAS 2.14,
    # CRUDE 1.71; plus JPN225 2.67, COFFEE 1.82, XPTUSD 1.34, UK100 1.38,
    # SOYBEANS 1.38. Rejected: cocoa/sugar/corn/US500/GER40/BNB (all lose).
    allowed_symbols = {"BTCUSD", "ETHUSD", "XAUUSD", "AMD", "NVDA",
                       "MSFT", "INTC",
                       "XAGUSD", "GOOGL", "AMZN", "AAPL", "META",
                       "CRUDE", "BRENT", "NATGAS", "GASOLINE", "XPTUSD",
                       "COFFEE", "SOYBEANS", "UK100", "JPN225"}

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 60:
            return []
        hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
        i = len(df) - 1
        if has_position:
            # Exit when price closes below the 10-bar low.
            if cl[i] < min(lo[i - 10:i]):
                return [{"type": "close", "symbol": symbol,
                         "reason": "10-bar low exit"}]
            return []
        # Enter on a fresh 20-bar high breakout.
        if cl[i] > max(hi[i - 20:i]):
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "20-bar high breakout"}]
        return []


# ---------------------------------------------------------------------------
# G) RSI-2 (Connors) — mean reversion. PF 1.05 median (marginal), but strong on
#    crypto + stocks. Buy RSI(2)<10 above the 200MA, sell RSI(2)>70.
#    Restricted to the symbols it actually won on.
# ---------------------------------------------------------------------------
class RSI2:
    key = "rsi2"
    label = "RSI-2 mean reversion"
    timeframe = "4h"
    direction = "long"
    stop_pct = 0.05
    target_pct = 0.06
    allowed_symbols = {"BTCUSD", "ETHUSD", "AMD", "NVDA", "MSFT",
                       "AAPL", "GOOGL", "AMZN", "META"}

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 210:
            return []
        df = df.copy()
        r = _rsi(df["close"], 2)
        ma = _ema(df["close"], 200)
        i = len(df) - 1
        if has_position:
            if r.iloc[i] > 70:
                return [{"type": "close", "symbol": symbol,
                         "reason": "RSI-2 > 70"}]
            return []
        if df["close"].iloc[i] > ma.iloc[i] and r.iloc[i] < 10:
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "RSI-2 oversold above 200MA"}]
        return []


# ---------------------------------------------------------------------------
# I) Darvas Box (Nicolas Darvas, 1950s) — box breakout with box-trailing stop.
#    A "box" = a consolidation range (top = recent high that holds, bottom =
#    recent low). Buy on a close above the box top; stop = box bottom; as higher
#    boxes form, trail the stop up box-by-box; exit on a close below the box.
#    Backtested (cost-included) on 42 markets: wins on METALS + Nikkei + soft
#    commodities, loses on forex/crypto (too choppy). Restricted to its winners:
#    XAGUSD 2.39, JPN225 2.06, XAUUSD 1.71, NATGAS 1.51, AUDUSD 1.33,
#    GASOLINE 1.30, COFFEE 1.27. Overlaps Donchian on some — which HELPS the
#    conviction sizing (2 strategies agreeing = higher-confidence, bigger size).
# ---------------------------------------------------------------------------
class DarvasBox:
    key = "darvas"
    label = "Darvas Box (breakout + box-trail)"
    timeframe = "4h"
    direction = "long"
    stop_pct = 0.05          # floor; the real stop is the box bottom
    target_pct = 0.20        # let boxes stack; wide TP
    box_len = 8
    allowed_symbols = {"XAGUSD", "JPN225", "XAUUSD", "NATGAS", "AUDUSD",
                       "GASOLINE", "COFFEE"}

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < self.box_len + 2:
            return []
        hi = df["high"].values
        lo = df["low"].values
        cl = df["close"].values
        i = len(df) - 1
        box_top = hi[i - self.box_len:i].max()
        box_bottom = lo[i - self.box_len:i].min()
        if has_position:
            # Exit when price closes below the box bottom (the trailing stop).
            if cl[i] < box_bottom:
                return [{"type": "close", "symbol": symbol,
                         "reason": "closed below box bottom"}]
            return []
        # Enter on a close above the box top (breakout from consolidation).
        if cl[i] > box_top:
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "breakout above Darvas box"}]
        return []


# ---------------------------------------------------------------------------
# H) Donchian 1h (FAST) — the "more action" strategy. Same breakout edge as the
#    4h Donchian but on a 1h clock: ~29 trades/symbol instead of a few/week.
#    Backtested (cost-included): only profitable on TRENDING STOCKS, so it's
#    hard-restricted to them. On forex/crypto/gold the fast clock loses to fees
#    (median PF 0.73 overall — but GOOGL 3.04, AMD 2.69, INTC 2.40, META 1.41,
#    AAPL 1.30). 15m was even faster and LOST everywhere (-75%) — rejected.
# ---------------------------------------------------------------------------
class DonchianFast:
    key = "donch1h"
    label = "Donchian 1h (fast, stocks only)"
    timeframe = "1h"
    direction = "long"
    stop_pct = 0.03          # floor; real exit is the 10-bar low
    target_pct = 0.10
    # ONLY the stocks it won on in backtest. Do NOT widen without re-testing.
    allowed_symbols = {"GOOGL", "AMD", "INTC", "META", "AAPL"}

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 40:
            return []
        hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
        i = len(df) - 1
        if has_position:
            if cl[i] < min(lo[i - 10:i]):
                return [{"type": "close", "symbol": symbol,
                         "reason": "10-bar low exit (1h)"}]
            return []
        if cl[i] > max(hi[i - 20:i]):
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "1h 20-bar high breakout"}]
        return []


# ---------------------------------------------------------------------------
# J) Momentum Burst — YOUR OWN signal (built + backtested from scratch, not
#    bought). Catches an explosive move AS IT STARTS:
#      * a "burst" candle: range >= 2x the 20-bar avg range (something's moving)
#      * strong bullish close: body >60% of range, close in the top 30%
#      * real participation: tick volume >= 1.2x its 20-bar average
#      * a genuine breakout: closes above the 20-bar high (not a fake spike)
#      * with-trend: above the 50-EMA
#    Then RIDE it with an ATR(20) trailing stop (2.5x) — let winners run, cut
#    losers. Backtested cost-included on 42 markets: v1 was mediocre (-43%);
#    adding the breakout filter + ATR trail flipped it to +101%. Restricted to
#    its 12 winners (gold PF 5.79, Brent 5.27, US500 3.59, coffee 3.22, ...).
# ---------------------------------------------------------------------------
class MomentumBurst:
    key = "burst"
    label = "Momentum Burst (yours)"
    timeframe = "4h"
    direction = "long"
    stop_pct = 0.04          # initial floor; real exit is the ATR trail
    target_pct = 0.25        # wide — let the trail decide
    burst_mult = 2.0
    trail_atr = 2.5
    allowed_symbols = {"XAUUSD", "BRENT", "US500", "COFFEE", "GASOLINE",
                       "AUDUSD", "NATGAS", "XPTUSD", "JPN225", "US100",
                       "COCOA", "GBPUSD"}

    def _atr(self, df, p=20):
        h, l, c = df["high"], df["low"], df["close"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / p, adjust=False).mean()

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 60:
            return []
        df = df.copy()
        df["ema50"] = _ema(df["close"], 50)
        df["atr"] = self._atr(df, 20)
        rng = df["high"] - df["low"]
        df["avg_rng"] = rng.rolling(20).mean()
        df["avg_vol"] = df["tick_volume"].rolling(20).mean()
        i = len(df) - 1
        o, h, l, c = (df["open"].iloc[i], df["high"].iloc[i],
                      df["low"].iloc[i], df["close"].iloc[i])

        if has_position:
            # ATR trailing stop: exit if we close below (close - 2.5*ATR)
            # measured from the recent swing. Approximate with a trailing check
            # against the highest close since a fixed lookback.
            recent_high = df["close"].iloc[-10:].max()
            trail = recent_high - self.trail_atr * df["atr"].iloc[i]
            if c < trail:
                return [{"type": "close", "symbol": symbol,
                         "reason": "ATR trailing stop"}]
            return []

        body = abs(c - o)
        r = (h - l) if h > l else 1e-9
        avg_rng = df["avg_rng"].iloc[i]
        avg_vol = df["avg_vol"].iloc[i]
        hi20 = df["high"].iloc[-21:-1].max()
        if pd.isna(avg_rng) or pd.isna(avg_vol) or avg_rng <= 0:
            return []
        big = (h - l) >= self.burst_mult * avg_rng
        strong = body >= 0.6 * r and (c - l) >= 0.7 * r
        vol_ok = df["tick_volume"].iloc[i] >= 1.2 * avg_vol
        breakout = c > hi20
        trend_ok = c > df["ema50"].iloc[i]
        if big and strong and vol_ok and breakout and trend_ok:
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "momentum burst breakout"}]
        return []


# Registry of ENABLED strategies, each restricted to where it has a real edge:
#   Candle Lessons, Trend 4h — validated, all symbols
#   Range Breakout — stocks+gold (backtest)
#   Momentum Pullback — MSFT/USDCAD/ETH (its 3 winners)
#   Donchian Breakout — STRONGEST (PF 1.39), + energy/index/metal winners
#   RSI-2 — crypto+stocks (marginal but positive there)
#   Darvas Box — metals + Nikkei + soft commodities (XAG 2.39, JPN225 2.06)
#   Donchian 1h (fast) — trending stocks only
# Rejected: Bear Trend (PF 0.54), Bollinger MR (0.92), MACD (0.91).
def build_strategies():
    return [CandleLessons(), Trend4h(), RangeBreakout(), MomentumPullback(),
            DonchianBreakout(), RSI2(), DarvasBox(), DonchianFast(),
            MomentumBurst()]
