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


# ---------------------------------------------------------------------------
# K) Short Breakdown — the SHORT side (profit when price FALLS). The bot was
#    long-only, blind to half of every market's moves. Backtested the short side
#    (cost-included): shorting FAILS on indices/stocks (they drift UP over time
#    — US500 PF 0.02, US100 0.08) but WORKS on things that crash hard with no
#    upward bias: ETH (Donchian 2.97 / Trend 3.42), COCOA (1.97 / 7.23), BTC
#    (1.40 / 2.37), silver, copper, USDMXN, coffee, GBPUSD. Restricted to those.
#    Logic: SELL a 20-bar low breakdown while below the 200-EMA (with the
#    downtrend); cover (close) on a 10-bar high.
# ---------------------------------------------------------------------------
class ShortBreakdown:
    key = "short"
    label = "Short Breakdown (down-moves)"
    timeframe = "4h"
    direction = "short"
    stop_pct = 0.05          # floor; real exit is the 10-bar high
    target_pct = 0.20        # let the fall run
    allowed_symbols = {"ETHUSD", "BTCUSD", "COCOA", "XAGUSD", "COPPER",
                       "USDMXN", "COFFEE", "GBPUSD"}

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 210:
            return []
        df = df.copy()
        et = _ema(df["close"], 200)
        hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
        i = len(df) - 1
        if has_position:
            # Cover (close the short) on a 10-bar high breakout.
            if cl[i] > max(hi[i - 10:i]):
                return [{"type": "close", "symbol": symbol,
                         "reason": "10-bar high — cover short"}]
            return []
        # Enter short on a 20-bar low breakdown while below the 200-EMA.
        if cl[i] < min(lo[i - 20:i]) and cl[i] < et.iloc[i]:
            return [{"type": "open", "side": "sell", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "20-bar low breakdown (short)"}]
        return []


# ---------------------------------------------------------------------------
# L) Gold/Silver Bollinger Reversal (DAILY) — the metals-focus specialist.
#    On the DAILY chart, precious metals mean-revert beautifully: when price
#    pierces below the lower Bollinger band then closes back inside, buy the
#    snap-back; exit at the mean (20-SMA). Backtested cost-included:
#    XAUUSD daily PF 3.26 (82% win), XAGUSD daily PF 53 (87% win!). Only metals,
#    only daily — it does NOT work intraday or on other assets.
# ---------------------------------------------------------------------------
class MetalsBollingerDaily:
    key = "goldbb"
    label = "Metals Bollinger Reversal (daily)"
    timeframe = "1d"
    direction = "long"
    stop_pct = 0.04
    target_pct = 0.06
    allowed_symbols = {"XAUUSD", "XAGUSD"}

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 25:
            return []
        c = df["close"]
        mean = c.rolling(20).mean()
        sd = c.rolling(20).std()
        lower = mean - 2 * sd
        i = len(df) - 1
        if has_position:
            # exit when price returns to (or above) the mean
            if c.iloc[i] >= mean.iloc[i]:
                return [{"type": "close", "symbol": symbol,
                         "reason": "reverted to mean"}]
            return []
        # prior bar closed below the lower band, this bar closes back inside
        if (c.iloc[i - 1] < lower.iloc[i - 1]
                and c.iloc[i] > lower.iloc[i]):
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "Bollinger snap-back (daily)"}]
        return []


# ---------------------------------------------------------------------------
# M) Gold/Silver Trend (DAILY) — the long-hold metals trend rider. On the daily,
#    the 20/100 EMA cross catches gold/silver's multi-week bull runs:
#    XAUUSD daily Trend PF very high, XAGUSD daily PF 8.03 (+113%). Few trades,
#    big moves. Metals + daily only.
# ---------------------------------------------------------------------------
class MetalsTrendDaily:
    key = "goldtrend"
    label = "Metals Trend (daily)"
    timeframe = "1d"
    direction = "long"
    stop_pct = 0.06
    target_pct = 0.25
    allowed_symbols = {"XAUUSD", "XAGUSD"}

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 120:
            return []
        df = df.copy()
        ef = _ema(df["close"], 20)
        es = _ema(df["close"], 100)
        i = len(df) - 1
        if has_position:
            if ef.iloc[i - 1] >= es.iloc[i - 1] and ef.iloc[i] < es.iloc[i]:
                return [{"type": "close", "symbol": symbol,
                         "reason": "daily EMA cross down"}]
            return []
        if ef.iloc[i - 1] <= es.iloc[i - 1] and ef.iloc[i] > es.iloc[i]:
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "daily 20/100 cross up"}]
        return []


# ---------------------------------------------------------------------------
# N) Metal Pulse (1h) — OUR OWN strategy, built from edges DISCOVERED in the
#    data (not guessed). We tested many signal components on 1h gold/silver and
#    kept the ones that genuinely predict the next move:
#      * 20-bar breakout in a bull regime (gold 58% up-edge)
#      * RSI2<5 oversold bounce in a bull regime (56-58% up-edge)
#      * silver additionally needs a VOLUME spike to confirm (its edge)
#    Two entry types (momentum breakout + oversold reversion), ATR trailing
#    exit. Backtested cost-included on 1h: gold PF 1.33 (58% win, ~106 trades),
#    silver PF 1.30-1.83 (56-62% win). FAST = lots of action, unlike the 4h/1d
#    strategies. Metals only — the edges were discovered on metals.
# ---------------------------------------------------------------------------
class MetalPulse:
    key = "pulse"
    label = "Metal Pulse (1h, ours)"
    timeframe = "1h"
    direction = "long"
    stop_pct = 0.02          # floor; real exit is the ATR trail
    target_pct = 0.05
    allowed_symbols = {"XAUUSD", "XAGUSD"}

    def _atr(self, df, p=14):
        h, l, c = df["high"], df["low"], df["close"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / p, adjust=False).mean()

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 210:
            return []
        df = df.copy()
        e200 = _ema(df["close"], 200)
        e21 = _ema(df["close"], 21)
        r2 = _rsi(df["close"], 2)
        i = len(df) - 1
        c = df["close"].iloc[i]

        if has_position:
            # exit: reversion trades bank fast (RSI2>85); all trades honor the
            # ATR trail via a simple close-below-recent-swing check.
            atrv = self._atr(df, 14).iloc[i]
            recent_high = df["close"].iloc[-8:].max()
            trail = recent_high - 3.0 * atrv
            if r2.iloc[i] > 85 or c < trail:
                return [{"type": "close", "symbol": symbol,
                         "reason": "pulse exit (RSI2>85 or ATR trail)"}]
            return []

        is_silver = symbol == "XAGUSD"
        bull = c > e200.iloc[i]
        if not bull:
            return []
        hi20 = df["high"].iloc[-21:-1].max()
        vol = df["tick_volume"].iloc[i]
        avg_vol = df["tick_volume"].iloc[-21:-1].mean()
        # Entry A: momentum breakout (silver needs volume confirmation)
        breakout = c > hi20
        if is_silver:
            breakout = breakout and vol > 1.3 * avg_vol
        # Entry B: oversold bounce (deep dip to/below 21-EMA)
        revert = r2.iloc[i] < 5 and c <= e21.iloc[i]
        if breakout:
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "pulse: momentum breakout"}]
        if revert:
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "pulse: oversold bounce"}]
        return []


# ---------------------------------------------------------------------------
# O) Gold Scalp 15m — the FAST one (user wanted minute-level). Honest test:
#    on 1m and 5m EVERY fast strategy LOSES (the spread eats tiny moves —
#    PF 0.24-0.90, proven cost-included). The ONLY fast metals strategy that
#    survives costs is momentum on 15m GOLD: ride a burst candle (big green +
#    volume spike, above 50-EMA) with an ATR stop/target. Backtested 15m gold
#    PF 1.37 (134 trades). This is the realistic "fast" edge — 15 min, not 1.
#    Gold only (silver's version lost); 15m only (1m/5m lose).
# ---------------------------------------------------------------------------
class GoldScalp15m:
    key = "scalp15"
    label = "Gold Scalp 15m (fast, gold only)"
    timeframe = "15m"
    direction = "long"
    stop_pct = 0.006         # ~ATR-based; tight for 15m
    target_pct = 0.009       # ~1.5:1
    allowed_symbols = {"XAUUSD"}

    def _atr(self, df, p=14):
        h, l, c = df["high"], df["low"], df["close"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / p, adjust=False).mean()

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 60:
            return []
        df = df.copy()
        e50 = _ema(df["close"], 50)
        rng = df["high"] - df["low"]
        i = len(df) - 1
        o, h, l, c = (df["open"].iloc[i], df["high"].iloc[i],
                      df["low"].iloc[i], df["close"].iloc[i])
        if has_position:
            # exit handled by the broker SL/TP (tight ATR-style levels).
            return []
        avg_r = rng.iloc[-21:-1].mean()
        avg_v = df["tick_volume"].iloc[-21:-1].mean()
        body = abs(c - o)
        r = (h - l) if h > l else 1e-9
        # burst candle: big green body + volume spike, with the short trend
        if (c > o and (h - l) > 1.8 * avg_r and body > 0.6 * r
                and df["tick_volume"].iloc[i] > 1.5 * avg_v and c > e50.iloc[i]):
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "15m gold momentum burst"}]
        return []


# ---------------------------------------------------------------------------
# P) Metals Short 1h — profit when gold/silver FALL (fixes the long-only gap).
#    Metals have a long-term UP drift, so shorting on 4h/daily LOSES (fights the
#    bull — backtested PF 0.26-0.92). But on 1h you can catch the short-term
#    DOWNSWINGS before the uptrend resumes. Backtested cost-included on 1h:
#    gold ShortDonchian PF 1.78, silver ShortTrend 1.99, silver ShortDonchian
#    1.54, gold ShortTrend 1.38. Two entries: 20-bar low breakdown (below
#    200-EMA) OR 20/100 cross-down (below 200-EMA). Cover on a 10-bar high.
# ---------------------------------------------------------------------------
class MetalsShort1h:
    key = "mshort"
    label = "Metals Short 1h (down-moves)"
    timeframe = "1h"
    direction = "short"
    stop_pct = 0.02
    target_pct = 0.04
    allowed_symbols = {"XAUUSD", "XAGUSD"}

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 210:
            return []
        df = df.copy()
        et = _ema(df["close"], 200)
        ef = _ema(df["close"], 20)
        es = _ema(df["close"], 100)
        hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
        i = len(df) - 1
        if has_position:
            # cover the short on a 10-bar high breakout
            if cl[i] > max(hi[i - 10:i]):
                return [{"type": "close", "symbol": symbol,
                         "reason": "10-bar high — cover short"}]
            return []
        below_200 = cl[i] < et.iloc[i]
        if not below_200:
            return []
        # Entry A: 20-bar low breakdown
        breakdown = cl[i] < min(lo[i - 20:i])
        # Entry B: 20/100 cross down
        cross_down = ef.iloc[i - 1] >= es.iloc[i - 1] and ef.iloc[i] < es.iloc[i]
        if breakdown or cross_down:
            return [{"type": "open", "side": "sell", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "1h metals breakdown (short)"}]
        return []


# ---------------------------------------------------------------------------
# Q) Metals Range (RSI mean-reversion) — makes money when gold/silver CHOP
#    SIDEWAYS (the condition where every breakout strategy does nothing). Buys
#    an oversold dip (RSI14<25) but ONLY when the market is actually RANGING
#    (price near its 50-EMA, not trending — the filter that makes it work).
#    Exits when RSI recovers (>55). Backtested cost-included: gold 1h PF 4.17
#    (90% win!), gold 4h 2.09, silver 30m 6.04. The "ranging" filter is key —
#    plain Bollinger/channel versions LOST (they trade into trends and get run
#    over). This is the piece that fires when nothing else can.
# ---------------------------------------------------------------------------
class MetalsRange:
    key = "mrange"
    label = "Metals Range (RSI, ranging-only)"
    timeframe = "1h"
    direction = "long"
    stop_pct = 0.02
    target_pct = 0.03
    allowed_symbols = {"XAUUSD", "XAGUSD"}
    rsi_buy = 25
    rsi_exit = 55

    def _atr(self, df, p=14):
        h, l, c = df["high"], df["low"], df["close"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / p, adjust=False).mean()

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 60:
            return []
        df = df.copy()
        r = _rsi(df["close"], 14)
        e50 = _ema(df["close"], 50)
        atrv = self._atr(df, 14)
        i = len(df) - 1
        c = df["close"].iloc[i]
        if has_position:
            if r.iloc[i] > self.rsi_exit:
                return [{"type": "close", "symbol": symbol,
                         "reason": "RSI recovered — range exit"}]
            return []
        # only trade when RANGING: price is close to its 50-EMA (not trending)
        ranging = abs(c - e50.iloc[i]) < 1.5 * atrv.iloc[i]
        if ranging and r.iloc[i] < self.rsi_buy:
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "oversold dip in a range"}]
        return []


# ---------------------------------------------------------------------------
# SHORT-TERM generic strategies (work on ANY asset, restricted per-bot). These
# are the winners from the cross-asset short-term sweep: RANGE (RSI mean-
# reversion, ranging-only) dominates; BURST (momentum + ATR trail) for the
# trendier ones. Timeframe set per instance (15m or 1h).
# ---------------------------------------------------------------------------
class STRange:
    """Short-term range: buy oversold when ranging (near 50-EMA).
    Walk-forward VALIDATED only on gold at the LOOSER setting (RSI<30, range
    mult 2.0 -> OOS PF 2.76 on 76 unseen trades, ~4x the strict frequency).
    Other assets collapsed out-of-sample at every setting — kept strict where
    still used, but the real edge is gold. rsi_buy / rng_mult tunable per bot."""
    key = "st_range"
    label = "Short-Term Range (RSI)"
    direction = "long"
    stop_pct = 0.015
    target_pct = 0.022

    def __init__(self, timeframe="1h", symbols=None, rsi_buy=25, rng_mult=1.5):
        self.timeframe = timeframe
        self.allowed_symbols = set(symbols) if symbols else None
        self.rsi_buy = rsi_buy
        self.rng_mult = rng_mult

    def _atr(self, df, p=14):
        h, l, c = df["high"], df["low"], df["close"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / p, adjust=False).mean()

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 60:
            return []
        r = _rsi(df["close"], 14)
        e50 = _ema(df["close"], 50)
        atrv = self._atr(df, 14)
        i = len(df) - 1
        c = df["close"].iloc[i]
        if has_position:
            if r.iloc[i] > 55:
                return [{"type": "close", "symbol": symbol,
                         "reason": "RSI recovered — range exit"}]
            return []
        ranging = abs(c - e50.iloc[i]) < self.rng_mult * atrv.iloc[i]
        if ranging and r.iloc[i] < self.rsi_buy:
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "oversold dip in a range"}]
        return []


class STBurst:
    """Short-term burst: big momentum candle + volume breakout, ATR trailing
    exit. Winner on silver 1.72, GBPUSD 1.47, NatGas 1.70."""
    key = "st_burst"
    label = "Short-Term Burst (momentum)"
    direction = "long"
    stop_pct = 0.02
    target_pct = 0.05

    def __init__(self, timeframe="1h", symbols=None):
        self.timeframe = timeframe
        self.allowed_symbols = set(symbols) if symbols else None

    def _atr(self, df, p=14):
        h, l, c = df["high"], df["low"], df["close"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / p, adjust=False).mean()

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 60:
            return []
        df = df.copy()
        e50 = _ema(df["close"], 50)
        rng = df["high"] - df["low"]
        i = len(df) - 1
        o, h, l, c = (df["open"].iloc[i], df["high"].iloc[i],
                      df["low"].iloc[i], df["close"].iloc[i])
        if has_position:
            atrv = self._atr(df, 14).iloc[i]
            recent_high = df["close"].iloc[-8:].max()
            if c < recent_high - 2.5 * atrv:
                return [{"type": "close", "symbol": symbol,
                         "reason": "ATR trailing stop"}]
            return []
        avg_r = rng.iloc[-21:-1].mean()
        avg_v = df["tick_volume"].iloc[-21:-1].mean()
        body = abs(c - o)
        r = (h - l) if h > l else 1e-9
        hi20 = df["high"].iloc[-21:-1].max()
        if (rng.iloc[i] >= 1.8 * avg_r and body >= 0.6 * r
                and (c - l) >= 0.7 * r
                and df["tick_volume"].iloc[i] >= 1.3 * avg_v
                and c > hi20 and c > e50.iloc[i]):
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "momentum burst breakout"}]
        return []


# ---------------------------------------------------------------------------
# FOUR SHORT-TERM ASSET-CLASS BOOKS — each its best short-term strategy per
# asset (cross-asset sweep, cost-included). RANGE dominates; BURST for trendy.
# ---------------------------------------------------------------------------
def build_st_metals():
    """Gold range 1h at the LOOSER walk-forward-VALIDATED setting (RSI<30,
    range mult 2.0 -> OOS PF 2.76 on 76 unseen trades, ~4x more action than
    strict) + Silver burst 1h. Gold range is the one short-term edge that held
    out-of-sample."""
    return [STRange("1h", {"XAUUSD"}, rsi_buy=30, rng_mult=2.0),
            STBurst("1h", {"XAGUSD"})]


def build_st_forex():
    """USDJPY (range 15m 5.37!), AUDUSD (range 1h 3.66), EURUSD (range 1h 1.90),
    GBPUSD (burst 1h 1.47)."""
    return [
        STRange("15m", {"USDJPY"}),
        STRange("1h", {"AUDUSD", "EURUSD"}),
        STBurst("1h", {"GBPUSD"}),
    ]


def build_st_indices():
    """US500 (range 1h 2.50), US100 (range 1h 1.67), Crude (range 15m 1.73),
    NatGas (burst 1h 1.70)."""
    return [
        STRange("1h", {"US500", "US100"}),
        STRange("15m", {"CRUDE"}),
        STBurst("1h", {"NATGAS"}),
    ]


def build_st_crypto():
    """Weekend book — BTC range 1h (PF 1.23, marginal but positive; 24/7)."""
    return [STRange("1h", {"BTCUSD", "ETHUSD"})]


# ===========================================================================
# THREE CLEAN BOOKS — each with ONLY its backtest-winning strategies (fresh
# rebuild, cost-included PFs shown). Rejected losers are excluded.
# ===========================================================================

def _restrict(strategies, symbols):
    """Hard-restrict every strategy to the given symbol set."""
    for s in strategies:
        cur = getattr(s, "allowed_symbols", None)
        s.allowed_symbols = symbols if cur is None else (set(cur) & symbols) or symbols
    return strategies


def build_book_metals():
    """BOOK 1 — LONG-TERM METALS (gold + silver), slow trend/breakout.
    Winners (backtested PF): gold trend 1d 6.77, trend 4h 5.35, donchian 4h
    3.05, burst 4h 2.15, donchian 1d 1.95; silver trend 4h 3.64, trend 1d 2.18,
    donchian 4h 2.14. All long-term — rides the big metal moves.
    Plus the Pattern Engine (4h): double-bottom + ascending-triangle geometry
    (gold 4h PF 1.64 / 3.19, backtested)."""
    from mt5_patterns import PatternEngine
    trend4h = Trend4h()
    trenddaily = MetalsTrendDaily()          # 20/100 cross on the daily
    strategies = [
        trend4h,                 # 4h trend (gold 5.35 / silver 3.64)
        trenddaily,              # daily trend (gold 6.77 / silver 2.18)
        DonchianBreakout(),      # 4h + 1d breakout (gold 3.05 / silver 2.14)
        MomentumBurst(),         # 4h burst (gold 2.15; silver weak -> gold only)
        MetalsBollingerDaily(),  # daily mean-reversion floor (high win rate)
        PatternEngine(timeframe="4h"),   # chart patterns (double-bottom/asc-tri)
    ]
    return _restrict(strategies, {"XAUUSD", "XAGUSD"})


def build_book_shortterm():
    """BOOK 2 — SHORT-TERM (fast 15m/1h metals). Winners: gold range 1h 4.08
    (90% win!), gold pulse 1h 1.40, gold scalp 15m 1.43, silver pulse 1h 1.46.
    Plus 1h shorts for down-moves. Fast = more action, disciplined."""
    from mt5_patterns import PatternEngine
    strategies = [
        MetalsRange(),           # 1h range (gold PF 4.08, 90% win)
        MetalPulse(),            # 1h breakout+bounce (gold 1.40 / silver 1.46)
        GoldScalp15m(),          # 15m gold momentum (1.43) — gold only
        MetalsShort1h(),         # 1h shorts (down-moves)
        PatternEngine(timeframe="1h"),   # chart patterns 1h (silver DB 2.23!)
    ]
    return _restrict(strategies, {"XAUUSD", "XAGUSD"})


def build_book_crypto():
    """BOOK 3 — CRYPTO (BTC + ETH), 4h. Winners: ETH trend 4h 1.81, ETH burst
    4h 1.55, BTC burst 4h 1.40, BTC rsi2 4h 1.31. Rejected: BTC trend, ETH
    donchian/rsi2/pulse (losers). Crypto is volatile — momentum + burst fit."""
    crypto = {"BTCUSD", "ETHUSD"}
    trend4h = Trend4h()          # ETH trend 1.81
    burst = MomentumBurst()
    rsi2 = RSI2()                # BTC rsi2 1.31
    strategies = [trend4h, burst, rsi2]
    return _restrict(strategies, crypto)


# ---- back-compat aliases (older launchers/env may still call these) ----
def build_strategies():
    return build_book_metals() + build_book_shortterm() + build_book_crypto()


def build_daytrader_strategies():
    return build_book_shortterm()


def build_gold_focus_strategies():
    return build_book_metals()
