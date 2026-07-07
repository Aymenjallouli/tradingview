"""
forex_strategy.py — Single source of truth for BOTH forex strategies.

The backtester and the live trader import their logic from here — no duplicated
strategy code. Two strategies share this module:

  SCALP (fast mean-reversion, 1m):
    ENTRY: close < lower Bollinger Band(20,2) AND RSI(7) < 25
    EXIT:  price >= middle Bollinger Band (take profit)
           OR -0.15% stop OR 30-minute max hold

  SWING (trend pullback, 5m):
    ENTRY: 20 EMA > 50 EMA (uptrend) AND price above 200 EMA
           AND price dips to/below the 20 EMA (a pullback) AND RSI(14) < 70
    EXIT:  +1.2% take profit OR -0.6% stop OR trend break (20 EMA < 50 EMA)

Each strategy is a small class with the same interface:
    add_indicators(df) -> df
    entry_signal(df, i) -> bool
    check_exit(entry_price, df, i, bars_held) -> reason|None
so the backtester and live loop can treat them identically.
"""

import pandas as pd

import forex_config as cfg


# ---------------------------------------------------------------------------
# Shared indicator helpers (pure pandas)
# ---------------------------------------------------------------------------
def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return (100 - (100 / (1 + rs))).fillna(100)


def _bollinger(close: pd.Series, period: int, std_mult: float):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    return mid, mid + std_mult * std, mid - std_mult * std


# ---------------------------------------------------------------------------
# SCALP strategy
# ---------------------------------------------------------------------------
class ScalpStrategy:
    name = "scalp"

    def __init__(self):
        self.p = cfg.SCALP

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        mid, upper, lower = _bollinger(df["close"], self.p["bb_period"],
                                       self.p["bb_std"])
        df["bb_mid"] = mid
        df["bb_lower"] = lower
        df["rsi"] = _rsi(df["close"], self.p["rsi_period"])
        return df

    def entry_signal(self, df: pd.DataFrame, i: int) -> bool:
        row = df.iloc[i]
        if pd.isna(row["bb_lower"]) or pd.isna(row["rsi"]):
            return False
        return bool(row["close"] < row["bb_lower"]
                    and row["rsi"] < self.p["rsi_entry_max"])

    def check_exit(self, entry_price, df, i, bars_held):
        row = df.iloc[i]
        price = row["close"]
        if price <= entry_price * (1 - self.p["stop_loss_pct"]):
            return "stop_loss"
        if not pd.isna(row["bb_mid"]) and price >= row["bb_mid"]:
            return "take_profit"
        if bars_held >= self.p["max_hold_minutes"]:
            return "time_stop"
        return None


# ---------------------------------------------------------------------------
# SWING strategy
# ---------------------------------------------------------------------------
class SwingStrategy:
    name = "swing"

    def __init__(self):
        self.p = cfg.SWING

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ema_fast"] = _ema(df["close"], self.p["ema_fast"])
        df["ema_slow"] = _ema(df["close"], self.p["ema_slow"])
        df["ema_trend"] = _ema(df["close"], self.p["ema_trend"])
        df["rsi"] = _rsi(df["close"], self.p["rsi_period"])
        return df

    def entry_signal(self, df: pd.DataFrame, i: int) -> bool:
        if i < 1:
            return False
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        cols = ["ema_fast", "ema_slow", "ema_trend", "rsi"]
        if any(pd.isna(row[c]) for c in cols):
            return False

        # Established uptrend: fast above slow, price above the long trend line.
        uptrend = (row["ema_fast"] > row["ema_slow"]
                   and row["close"] > row["ema_trend"])
        # Pullback: price dipped to/below the fast EMA on this bar but was above
        # it on the previous bar (a buy-the-dip entry, not chasing).
        pullback = (row["close"] <= row["ema_fast"]
                    and prev["close"] > prev["ema_fast"])
        rsi_ok = row["rsi"] < self.p["rsi_entry_max"]
        return bool(uptrend and pullback and rsi_ok)

    def check_exit(self, entry_price, df, i, bars_held):
        row = df.iloc[i]
        price = row["close"]
        if price <= entry_price * (1 - self.p["stop_loss_pct"]):
            return "stop_loss"
        if price >= entry_price * (1 + self.p["take_profit_pct"]):
            return "take_profit"
        # Trend break: fast EMA falls below slow EMA.
        if not pd.isna(row["ema_fast"]) and not pd.isna(row["ema_slow"]) \
                and row["ema_fast"] < row["ema_slow"]:
            return "trend_break"
        return None


# Registry so callers can pick a strategy by name.
STRATEGIES = {
    "scalp": ScalpStrategy,
    "swing": SwingStrategy,
}


def get_strategy(name: str):
    return STRATEGIES[name]()
