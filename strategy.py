"""
strategy.py — THE single source of truth for the trading strategy.

Both the backtester (Module 4) and the live signal engine (Module 1) import
their strategy logic from this file. This guarantees that what you test is
EXACTLY what you trade — there is no duplicated strategy code anywhere.

What's in here:
  1. Indicator calculations (EMA, RSI) using pure pandas — no TA library.
  2. `add_indicators()` — attaches all indicator columns to a price DataFrame.
  3. `entry_signal()` / `exit_signal()` — the exact rules from the spec.

The strategy (long only, trend following):
  ENTRY:  20 EMA crosses ABOVE 50 EMA
          AND price is ABOVE the 200 EMA
          AND RSI(14) < 70
  EXIT:   20 EMA crosses BELOW 50 EMA
          OR  stop loss hit at -3%
          OR  take profit hit at +6%
"""

import pandas as pd

import config


# ---------------------------------------------------------------------------
# Indicator calculations (pure pandas, no external TA library)
# ---------------------------------------------------------------------------
def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average.

    `adjust=False` gives the standard "recursive" EMA that trading platforms
    (like TradingView) use, so our numbers line up with what you'd see there.
    """
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing method).

    RSI oscillates between 0 and 100. Above 70 is often called "overbought".
    We use Wilder's smoothing (an EMA with alpha = 1/period), which is the
    classic RSI definition.
    """
    delta = series.diff()

    # Separate gains (up moves) from losses (down moves).
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    # Wilder's smoothing = exponential moving average with alpha = 1/period.
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    # Relative Strength = average gain / average loss.
    # If avg_loss is 0, RS is infinite and RSI should be 100.
    rs = avg_gain / avg_loss
    rsi_values = 100 - (100 / (1 + rs))

    # When there are no losses at all, RSI = 100 (avoid divide-by-zero NaN).
    rsi_values = rsi_values.fillna(100)
    return rsi_values


# ---------------------------------------------------------------------------
# Attach all indicators to a price DataFrame
# ---------------------------------------------------------------------------
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a COPY of `df` with indicator columns added.

    Expects `df` to have at least a 'Close' column (case-sensitive), which is
    what yfinance gives us. Adds:
        ema_fast, ema_slow, ema_trend, rsi
    """
    df = df.copy()

    df["ema_fast"] = ema(df["Close"], config.EMA_FAST)
    df["ema_slow"] = ema(df["Close"], config.EMA_SLOW)
    df["ema_trend"] = ema(df["Close"], config.EMA_TREND)
    df["rsi"] = rsi(df["Close"], config.RSI_PERIOD)

    return df


# ---------------------------------------------------------------------------
# Signal logic — the exact rules from the spec
# ---------------------------------------------------------------------------
def entry_signal(df: pd.DataFrame, i: int) -> bool:
    """True if we should OPEN a long position at bar index `i`.

    Rules (all must be true):
      1. 20 EMA crosses ABOVE 50 EMA on this bar
         (fast was <= slow on the previous bar, and is > slow now)
      2. Price (Close) is ABOVE the 200 EMA
      3. RSI(14) < 70

    We need a previous bar to detect a "cross", so index 0 can never be an
    entry. We also require the 200 EMA to be valid (not NaN).
    """
    if i < 1:
        return False

    row = df.iloc[i]
    prev = df.iloc[i - 1]

    # If any indicator is still NaN (not enough history yet), no signal.
    if pd.isna(row["ema_fast"]) or pd.isna(row["ema_slow"]) \
            or pd.isna(row["ema_trend"]) or pd.isna(row["rsi"]):
        return False
    if pd.isna(prev["ema_fast"]) or pd.isna(prev["ema_slow"]):
        return False

    # 1. Fresh bullish crossover: fast was at/below slow, now it's above.
    crossed_up = (prev["ema_fast"] <= prev["ema_slow"]) and \
                 (row["ema_fast"] > row["ema_slow"])

    # 2. Price above the long-term trend line.
    above_trend = row["Close"] > row["ema_trend"]

    # 3. Not overbought.
    rsi_ok = row["rsi"] < config.RSI_MAX_ENTRY

    return bool(crossed_up and above_trend and rsi_ok)


def ema_exit_signal(df: pd.DataFrame, i: int) -> bool:
    """True if the 20 EMA crosses BELOW the 50 EMA at bar index `i`.

    This is the trend-reversal exit. Stop-loss and take-profit are handled
    separately (they depend on the entry price, which this function doesn't
    know about). See `check_exit()` for the full exit decision.
    """
    if i < 1:
        return False

    row = df.iloc[i]
    prev = df.iloc[i - 1]

    if pd.isna(row["ema_fast"]) or pd.isna(row["ema_slow"]) \
            or pd.isna(prev["ema_fast"]) or pd.isna(prev["ema_slow"]):
        return False

    crossed_down = (prev["ema_fast"] >= prev["ema_slow"]) and \
                   (row["ema_fast"] < row["ema_slow"])
    return bool(crossed_down)


def check_exit(entry_price: float, current_price: float,
               df: pd.DataFrame, i: int) -> str | None:
    """Decide whether an OPEN position should exit at bar index `i`.

    Returns the REASON for exit as a string, or None if we should hold:
        "stop_loss"    -> price fell to/below the -3% stop
        "take_profit"  -> price rose to/above the +6% target
        "ema_cross"    -> 20 EMA crossed below 50 EMA
        None           -> keep holding

    Priority order matters: we check stop loss and take profit first because
    those are protective/locking exits based on the entry price.
    """
    # Stop loss: current price at or below entry * (1 - 3%).
    stop_price = entry_price * (1 - config.STOP_LOSS_PCT)
    if current_price <= stop_price:
        return "stop_loss"

    # Take profit: current price at or above entry * (1 + 6%).
    target_price = entry_price * (1 + config.TAKE_PROFIT_PCT)
    if current_price >= target_price:
        return "take_profit"

    # Trend reversal: fast EMA crosses below slow EMA.
    if ema_exit_signal(df, i):
        return "ema_cross"

    return None
