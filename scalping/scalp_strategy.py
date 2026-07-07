"""
scalp_strategy.py — THE single source of truth for the scalping strategy.

Both the scalping backtester (Module A) and the live paper scalper (Module B)
import their logic from here. Zero duplicated strategy code.

The strategy — mean-reversion scalp (long only):
  ENTRY: the candle CLOSES below the lower Bollinger Band (20, 2.0)
         AND RSI(7) < 25   (deeply oversold)
  EXIT:  price touches the MIDDLE Bollinger Band (take profit)   -> "take_profit"
         OR  price falls -0.6% from entry (stop loss)            -> "stop_loss"
         OR  30 minutes (candles) elapsed since entry            -> "time_stop"
         whichever comes first.

Execution realism: the SIGNAL is detected on a closed candle, but the ENTRY
FILLS at the NEXT candle's OPEN — never the signal candle's close. The
backtester and live loop both honour this.
"""

import pandas as pd

import scalp_config as cfg


# ---------------------------------------------------------------------------
# Indicators (pure pandas — no TA library)
# ---------------------------------------------------------------------------
def bollinger_bands(close: pd.Series, period: int, std_mult: float):
    """Return (middle, upper, lower) Bollinger Bands.

    Middle = simple moving average. Upper/lower = middle +/- std_mult * rolling
    standard deviation. We use population std (ddof=0), the common BB choice.
    """
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std(ddof=0)
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    return middle, upper, lower


def rsi(close: pd.Series, period: int) -> pd.Series:
    """RSI using Wilder's smoothing (same definition as the trend system)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    out = 100 - (100 / (1 + rs))
    return out.fillna(100)


# ---------------------------------------------------------------------------
# Attach indicators
# ---------------------------------------------------------------------------
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a COPY of df with bb_mid, bb_upper, bb_lower, rsi columns.

    Expects a 'close' column (lowercase — that's what our Binance fetcher
    produces).
    """
    df = df.copy()
    mid, upper, lower = bollinger_bands(df["close"], cfg.BB_PERIOD, cfg.BB_STD)
    df["bb_mid"] = mid
    df["bb_upper"] = upper
    df["bb_lower"] = lower
    df["rsi"] = rsi(df["close"], cfg.RSI_PERIOD)
    return df


# ---------------------------------------------------------------------------
# Entry signal
# ---------------------------------------------------------------------------
def entry_signal(df: pd.DataFrame, i: int) -> bool:
    """True if bar `i` (a CLOSED candle) triggers a long entry.

    Rules:
      * close < lower Bollinger Band, AND
      * RSI(7) < 25
    The actual fill happens at bar i+1's OPEN (the caller handles that).
    """
    row = df.iloc[i]
    if pd.isna(row["bb_lower"]) or pd.isna(row["rsi"]):
        return False
    below_band = row["close"] < row["bb_lower"]
    oversold = row["rsi"] < cfg.RSI_ENTRY_MAX
    return bool(below_band and oversold)


# ---------------------------------------------------------------------------
# Exit decision
# ---------------------------------------------------------------------------
def check_exit(entry_price: float, df: pd.DataFrame, i: int,
               bars_held: int) -> str | None:
    """Decide whether an OPEN position exits on bar `i`.

    Returns "take_profit" | "stop_loss" | "time_stop" | None.

    Priority: stop loss first (protective), then take profit at the middle
    band, then the time stop. `bars_held` is how many 1-minute candles we've
    held (each bar = 1 minute), used for the 30-minute max-hold rule.
    """
    row = df.iloc[i]
    price = row["close"]

    # 1. Stop loss: -0.6% from entry.
    stop_price = entry_price * (1 - cfg.STOP_LOSS_PCT)
    if price <= stop_price:
        return "stop_loss"

    # 2. Take profit: price touches/exceeds the middle band.
    if not pd.isna(row["bb_mid"]) and price >= row["bb_mid"]:
        return "take_profit"

    # 3. Time stop: held for the maximum number of minutes.
    if bars_held >= cfg.MAX_HOLD_MINUTES:
        return "time_stop"

    return None
