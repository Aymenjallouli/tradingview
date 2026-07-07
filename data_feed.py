"""
data_feed.py — Fetches price candles from yfinance.

Shared by the backtester (Module 4) and the live signal engine (Module 1) so
both get their data the same way. The candle timeframe is whatever
`config.TIMEFRAME` says (currently "1h").

yfinance quirks this module smooths over:
  * Intraday intervals (1h, 4h, etc.) are only served for a limited history
    window (~730 days for 1h). That's plenty for both a ~2-year backtest and
    for warming up the 200 EMA in live mode.
  * If ever a coarser timeframe is requested than yfinance serves natively, we
    fetch 1h and resample up. For native intervals (like 1h) no resampling
    happens — you get the real candles.
  * yfinance sometimes returns columns as a MultiIndex (when you download a
    single ticker it can still nest under the ticker name). We flatten it.
"""

import pandas as pd
import yfinance as yf

import config


# Intervals yfinance serves natively. Anything not in here we build by
# resampling 1h data (see _timeframe_to_pandas_rule).
_NATIVE_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"}


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance sometimes returns MultiIndex columns like ('Close','BTC-USD').

    Flatten to plain 'Close', 'Open', etc. so the rest of the code is simple.
    """
    if isinstance(df.columns, pd.MultiIndex):
        # Keep the first level (the OHLCV field name).
        df.columns = df.columns.get_level_values(0)
    return df


def _timeframe_to_pandas_rule(timeframe: str) -> str:
    """Translate a yfinance-style timeframe (e.g. '4h') to a pandas resample
    rule (e.g. '4h'). They mostly match; this keeps one place to adjust.
    """
    # yfinance uses '1h'/'4h'/'1d'; pandas resample accepts the same lowercase
    # 'h'/'d' offsets, so we can pass most through unchanged.
    return timeframe


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample intraday candles up to a coarser timeframe.

    Standard OHLCV aggregation:
        Open = first, High = max, Low = min, Close = last, Volume = sum
    """
    agg = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }
    agg = {k: v for k, v in agg.items() if k in df.columns}
    out = df.resample(rule).agg(agg)
    # Drop periods with no trades (e.g. weekend gaps for stocks).
    out = out.dropna(subset=["Close"])
    return out


def _download(symbol: str, interval: str, period: str) -> pd.DataFrame:
    """Thin wrapper around yf.download with error handling + column flatten."""
    try:
        df = yf.download(
            symbol,
            interval=interval,
            period=period,
            auto_adjust=True,     # adjust for splits/dividends
            progress=False,
        )
    except Exception as exc:  # noqa: BLE001 - be robust for a beginner
        print(f"  [data_feed] Failed to download {symbol}: {exc}")
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()
    return _flatten_columns(df)


def _get_timeframe_candles(symbol: str, period: str) -> pd.DataFrame:
    """Fetch candles for `symbol` at config.TIMEFRAME over `period`.

    If the timeframe is a native yfinance interval (e.g. '1h'), download it
    directly. Otherwise download 1h and resample up to the timeframe.
    """
    timeframe = config.TIMEFRAME

    if timeframe in _NATIVE_INTERVALS:
        return _download(symbol, interval=timeframe, period=period)

    # Non-native timeframe (e.g. '4h'): build it from 1h candles.
    one_h = _download(symbol, interval="1h", period=period)
    if one_h.empty:
        return pd.DataFrame()
    return _resample(one_h, _timeframe_to_pandas_rule(timeframe))


def get_candles(symbol: str, interval: str = None,
                period: str = "730d") -> pd.DataFrame:
    """Fetch recent candles for one symbol (used by the LIVE signal engine).

    We deliberately pull a LONG window (default ~730 days of 1h data) so the
    200 EMA has enough history to warm up for every symbol — including stocks,
    where a short window would give too few bars. The candles are built at
    config.TIMEFRAME so live and backtest see identically-constructed candles.

    Args:
        symbol:   e.g. "BTC-USD", "AAPL"
        interval: usually leave as None to use config.TIMEFRAME. If you pass an
                  explicit yfinance interval it is downloaded directly.
        period:   yfinance period string; default "730d" (Yahoo's 1h cap).

    Returns a DataFrame indexed by datetime (Open/High/Low/Close/Volume), or an
    empty DataFrame if the download fails.
    """
    if interval is not None and interval != config.TIMEFRAME:
        # Caller explicitly wants a specific raw interval.
        return _download(symbol, interval=interval, period=period)
    return _get_timeframe_candles(symbol, period=period)


def get_backtest_candles(symbol: str, years: int = 3) -> pd.DataFrame:
    """Fetch candles for the backtest at config.TIMEFRAME.

    For 1h candles, Yahoo caps history at ~730 days (~2 years). We request the
    full allowed window so the backtest is as long as the data permits. The
    exact number of years available is reported by the backtester from the data
    it actually receives.
    """
    return _get_timeframe_candles(symbol, period="730d")
