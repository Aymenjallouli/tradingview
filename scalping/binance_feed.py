"""
binance_feed.py — Fetches 1-minute candles from Binance's public API.

No API key is needed for market data. Shared by the scalping backtester
(Module A) and the live scalper (Module B).

Two functions:
  * get_klines()        — one raw request (up to 1000 candles).
  * get_history()       — pages backwards to pull many days of 1m candles.
  * get_latest_closed() — the most recent CLOSED candles (for live polling).
"""

import time

import pandas as pd
import requests

import scalp_config as cfg


# Binance kline columns, in the order the API returns them.
_KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def _request(params: dict) -> list:
    """GET /api/v3/klines, trying each host until one works.

    Returns the raw list of klines, or raises the last error if all hosts fail.
    """
    last_err = None
    for host in cfg.BINANCE_HOSTS:
        url = host + "/api/v3/klines"
        try:
            resp = requests.get(url, params=params, timeout=20)
            if resp.status_code == 200:
                return resp.json()
            last_err = RuntimeError(f"{host} -> HTTP {resp.status_code}: "
                                    f"{resp.text[:150]}")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise last_err if last_err else RuntimeError("No Binance host reachable")


def _to_dataframe(raw: list) -> pd.DataFrame:
    """Turn raw klines into a clean DataFrame indexed by candle open time.

    Only the OHLCV columns are kept, converted to floats. The index is a UTC
    timestamp of when the candle OPENED.
    """
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw, columns=_KLINE_COLS)
    # Convert the numeric columns.
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    return df[["open", "high", "low", "close", "volume"]]


def get_klines(symbol: str, interval: str = "1m", limit: int = 1000,
               start_time: int = None, end_time: int = None) -> pd.DataFrame:
    """Fetch up to `limit` candles (max 1000 per Binance rules)."""
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_time is not None:
        params["startTime"] = start_time
    if end_time is not None:
        params["endTime"] = end_time
    return _to_dataframe(_request(params))


def get_history(symbol: str, days: int, interval: str = "1m") -> pd.DataFrame:
    """Pull `days` worth of 1m candles by paging forward from the start.

    Binance returns at most 1000 candles per call, so for 30 days (~43,200
    one-minute candles) we make ~44 sequential requests, walking forward in
    time. A tiny sleep between calls stays polite to the public API.

    Returns a DataFrame sorted by time with duplicates removed.
    """
    ms_per_min = 60_000
    total_minutes = days * 24 * 60
    # Start `days` ago. We compute the start from the newest candle's time so we
    # don't depend on the local clock being correct.
    newest = get_klines(symbol, interval=interval, limit=1)
    if newest.empty:
        return pd.DataFrame()
    newest_ms = int(newest.index[-1].timestamp() * 1000)
    start_ms = newest_ms - total_minutes * ms_per_min

    frames = []
    cursor = start_ms
    calls = 0
    while cursor < newest_ms:
        batch = get_klines(symbol, interval=interval, limit=1000,
                           start_time=cursor)
        if batch.empty:
            break
        frames.append(batch)
        # Advance the cursor to just past the last candle we received.
        last_ms = int(batch.index[-1].timestamp() * 1000)
        if last_ms <= cursor:
            break  # no progress; avoid an infinite loop
        cursor = last_ms + ms_per_min
        calls += 1
        # Be polite to the free public API.
        time.sleep(0.15)
        # Safety cap so a bug can't hammer the API forever.
        if calls > total_minutes // 1000 + 5:
            break

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df


def get_latest_closed(symbol: str, interval: str = "1m",
                      limit: int = 100) -> pd.DataFrame:
    """Return the most recent CLOSED candles for live polling.

    Binance's last returned candle is the currently-forming one, so we drop it
    and return only closed candles. `limit` should comfortably exceed the
    indicator warm-up (Bollinger 20 + a little), so 100 is plenty.
    """
    df = get_klines(symbol, interval=interval, limit=limit)
    if len(df) < 2:
        return df
    # Drop the last (still-forming) candle.
    return df.iloc[:-1]
