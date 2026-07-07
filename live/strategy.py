"""
strategy.py — Pluggable strategies (single source of truth).

Three strategies, each self-describing (its own timeframe, market, params). The
engine runs any subset, each with its own paper account.

  TREND  — crypto 4h EMA-cross trend. Passed backtest (PF ~1.37). Slow (a few
           trades/week). The proven one.
  SCALP  — crypto 1m Bollinger + RSI mean-reversion. Fast, trades often. Lost
           money in backtest (costs). Real-time action to watch.
  FOREX  — forex 5m trend pullback (swing). Best economics; USD/JPY was the most
           promising (PF 1.34). Updates ~every 60s (no free forex tick feed).

Each strategy exposes the same interface so the engine treats them identically:
    key, label, market, timeframe, warmup
    add_indicators(df) -> df
    entry_signal(df, i) -> bool
    check_exit(entry_price, price, df, i, bars_held) -> reason|None
"""

import pandas as pd

import config


def _ema(s, p):
    return s.ewm(span=p, adjust=False).mean()


def _rsi(s, p):
    d = s.diff()
    gain = d.clip(lower=0.0).ewm(alpha=1 / p, adjust=False).mean()
    loss = (-d.clip(upper=0.0)).ewm(alpha=1 / p, adjust=False).mean()
    return (100 - (100 / (1 + gain / loss))).fillna(100)


def _bollinger(s, p, mult):
    mid = s.rolling(p).mean()
    sd = s.rolling(p).std(ddof=0)
    return mid, mid + mult * sd, mid - mult * sd


# ---------------------------------------------------------------------------
# TREND (crypto 4h) — proven
# ---------------------------------------------------------------------------
class TrendStrategy:
    key = "trend"
    label = "Trend 4h (proven)"
    market = "crypto"
    timeframe = config.TREND_TIMEFRAME
    warmup = 400
    size_pct = config.POSITION_SIZE_PCT

    def add_indicators(self, df):
        df = df.copy()
        df["ema_fast"] = _ema(df["close"], config.TREND_EMA_FAST)
        df["ema_slow"] = _ema(df["close"], config.TREND_EMA_SLOW)
        df["ema_trend"] = _ema(df["close"], config.TREND_EMA_TREND)
        df["rsi"] = _rsi(df["close"], config.TREND_RSI_PERIOD)
        return df

    def entry_signal(self, df, i):
        if i < 1:
            return False
        row, prev = df.iloc[i], df.iloc[i - 1]
        c = ["ema_fast", "ema_slow", "ema_trend", "rsi"]
        if any(pd.isna(row[x]) for x in c) or pd.isna(prev["ema_fast"]) \
                or pd.isna(prev["ema_slow"]):
            return False
        crossed = (prev["ema_fast"] <= prev["ema_slow"]) and \
                  (row["ema_fast"] > row["ema_slow"])
        return bool(crossed and row["close"] > row["ema_trend"]
                    and row["rsi"] < config.TREND_RSI_MAX)

    def check_exit(self, entry_price, price, df, i, bars_held):
        if price <= entry_price * (1 - config.TREND_STOP):
            return "stop_loss"
        if price >= entry_price * (1 + config.TREND_TARGET):
            return "take_profit"
        if i >= 1:
            row, prev = df.iloc[i], df.iloc[i - 1]
            if not pd.isna(row["ema_fast"]) and not pd.isna(prev["ema_fast"]) \
                    and prev["ema_fast"] >= prev["ema_slow"] \
                    and row["ema_fast"] < row["ema_slow"]:
                return "ema_cross"
        return None


# ---------------------------------------------------------------------------
# SCALP (crypto 1m) — fast, experimental
# ---------------------------------------------------------------------------
class ScalpStrategy:
    key = "scalp"
    label = "Scalp 1m (fast)"
    market = "crypto"
    timeframe = config.SCALP_TIMEFRAME
    warmup = 60
    size_pct = config.SCALP_POSITION_PCT

    def add_indicators(self, df):
        df = df.copy()
        mid, up, low = _bollinger(df["close"], config.SCALP_BB_PERIOD,
                                  config.SCALP_BB_STD)
        df["bb_mid"] = mid
        df["bb_lower"] = low
        df["rsi"] = _rsi(df["close"], config.SCALP_RSI_PERIOD)
        return df

    def entry_signal(self, df, i):
        row = df.iloc[i]
        if pd.isna(row["bb_lower"]) or pd.isna(row["rsi"]):
            return False
        # Enter on an oversold dip toward the lower band. We allow "near or
        # below" the band (within a small tolerance) so the strategy actually
        # trades in normal markets instead of only on rare sharp crashes.
        near_band = row["close"] < row["bb_lower"] * (1 + config.SCALP_BAND_TOL)
        oversold = row["rsi"] < config.SCALP_RSI_ENTRY
        return bool(near_band and oversold)

    def check_exit(self, entry_price, price, df, i, bars_held):
        if price <= entry_price * (1 - config.SCALP_STOP):
            return "stop_loss"
        row = df.iloc[i]
        if not pd.isna(row["bb_mid"]) and price >= row["bb_mid"]:
            return "take_profit"
        if bars_held >= config.SCALP_MAX_HOLD_MIN:
            return "time_stop"
        return None


# ---------------------------------------------------------------------------
# FOREX (5m swing) — best economics
# ---------------------------------------------------------------------------
class ForexStrategy:
    key = "forex"
    label = "Forex 5m swing (best economics)"
    market = "forex"
    timeframe = config.FOREX_TIMEFRAME
    warmup = 260
    size_pct = config.POSITION_SIZE_PCT

    def add_indicators(self, df):
        df = df.copy()
        df["ema_fast"] = _ema(df["close"], config.FOREX_EMA_FAST)
        df["ema_slow"] = _ema(df["close"], config.FOREX_EMA_SLOW)
        df["ema_trend"] = _ema(df["close"], config.FOREX_EMA_TREND)
        df["rsi"] = _rsi(df["close"], config.FOREX_RSI_PERIOD)
        return df

    def entry_signal(self, df, i):
        if i < 1:
            return False
        row, prev = df.iloc[i], df.iloc[i - 1]
        c = ["ema_fast", "ema_slow", "ema_trend", "rsi"]
        if any(pd.isna(row[x]) for x in c):
            return False
        uptrend = row["ema_fast"] > row["ema_slow"] \
            and row["close"] > row["ema_trend"]
        pullback = row["close"] <= row["ema_fast"] \
            and prev["close"] > prev["ema_fast"]
        return bool(uptrend and pullback and row["rsi"] < config.FOREX_RSI_MAX)

    def check_exit(self, entry_price, price, df, i, bars_held):
        if price <= entry_price * (1 - config.FOREX_STOP):
            return "stop_loss"
        if price >= entry_price * (1 + config.FOREX_TARGET):
            return "take_profit"
        row = df.iloc[i]
        if not pd.isna(row["ema_fast"]) and not pd.isna(row["ema_slow"]) \
                and row["ema_fast"] < row["ema_slow"]:
            return "trend_break"
        return None


ALL = {"trend": TrendStrategy, "scalp": ScalpStrategy, "forex": ForexStrategy}


def build(keys):
    return [ALL[k]() for k in keys if k in ALL]
