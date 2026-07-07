"""
forex_feed.py — Fetches forex candles from yfinance and models the spread cost.

Two responsibilities:
  1. get_candles()  — download OHLCV forex candles (mid prices) for a pair.
  2. cost helpers   — turn the per-pair spread (in pips) into a price you'd
                      actually fill at, so the backtester/live trader can apply
                      REALISTIC forex costs.

Why this file exists separately from the crypto feed: forex costs are quoted in
PIPS and depend on the pair, not a flat percentage. We centralize that here so
the strategy and backtester never have to think about pips.
"""

import pandas as pd
import yfinance as yf

import forex_config as cfg


def get_candles(pair: str, interval: str, period: str) -> pd.DataFrame:
    """Download forex candles for `pair` (e.g. 'EURUSD=X').

    Returns a DataFrame indexed by datetime with lowercase OHLCV columns
    (open, high, low, close, volume) so it matches the scalping module's shape.
    Empty DataFrame on failure.
    """
    try:
        df = yf.download(pair, interval=interval, period=period,
                         auto_adjust=True, progress=False)
    except Exception as exc:  # noqa: BLE001
        print(f"  [forex_feed] download failed for {pair}: {exc}")
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    # Flatten possible MultiIndex columns (yfinance quirk).
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Normalize to lowercase OHLCV.
    rename = {c: c.lower() for c in df.columns}
    df = df.rename(columns=rename)
    keep = [c for c in ["open", "high", "low", "close", "volume"]
            if c in df.columns]
    return df[keep]


# ---------------------------------------------------------------------------
# Spread / slippage cost, expressed as a price adjustment.
# ---------------------------------------------------------------------------
def half_spread_price(pair: str) -> float:
    """Half the spread (in PRICE terms) for `pair`.

    The spread is the gap between the buy (ask) and sell (bid) price. yfinance
    gives us the MID, so a buy fills at mid + half-spread and a sell at
    mid - half-spread. We also add the slippage pips here (per side).
    """
    info = cfg.PAIRS[pair]
    pip = info["pip_size"]
    total_pips_per_side = info["spread_pips"] / 2.0 + cfg.SLIPPAGE_PIPS
    return total_pips_per_side * pip


def apply_cost(pair: str, mid_price: float, side: str) -> float:
    """Return the realistic FILL price for `side` ('buy'/'sell') at `mid_price`.

    Buy  -> pay more (mid + half-spread + slippage)
    Sell -> get less (mid - half-spread - slippage)
    """
    adj = half_spread_price(pair)
    if side == "buy":
        return mid_price + adj
    return mid_price - adj


def spread_cost_pct(pair: str, price: float) -> float:
    """The full round-trip spread+slippage cost as a % of price (for reporting).

    This is the number to compare against the crypto scalper's ~0.3%.
    """
    round_trip_price = 2 * half_spread_price(pair)  # both sides
    return round_trip_price / price * 100 if price else 0.0
