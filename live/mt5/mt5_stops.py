"""
mt5_stops.py — data-derived stop-losses.

THE BUG THIS FIXES: every one of the 169 strategies was walk-forward validated
exiting on a SIGNAL (RSI recovers, z-score crosses zero, price returns to the
mid-band) with NO stop-loss at all. Live, we bolted a flat 2% stop onto all of
them. But a mean-reversion trade is *supposed* to go against you before it
reverts — you buy 2 std-devs below the mean precisely because it's falling. A
flat 2% stop fires during exactly that dip and converts winners into losses.

Measured across 114 strategy-markets (see the MAE study):
    avg PF with our flat 2% stop  : 1.32
    avg PF with no stop (backtest): 1.53
    avg PF with the best stop     : 1.55
    the 2% stop killed 16% of trades on average — up to 58%

It was turning winners into losers outright:
    NAS100 Keltner  PF 0.91 -> 1.70    US500 Keltner  0.95 -> 1.51
    WHEAT ZScoreMR  PF 0.95 -> 1.69    US30 Keltner   0.81 -> 1.25

THE FIX: size each strategy's stop from its OWN measured adverse excursion
(90th-percentile MAE, or the empirically best stop), not a constant. Volatile 4h
index mean-reversion needs 5-10%; tight FX pairs are fine at 4-6%. Stops stay
capped at 10% so a genuine failure is still bounded — this widens the stop, it
does not remove it.

strategy_stops.json maps "SYMBOL|Method|tf" -> stop fraction. Unknown pairs fall
back to the strategy's own stop_pct, so nothing breaks if the file is missing.
"""

import json
import os

_PATH = os.path.join(os.path.dirname(__file__), "strategy_stops.json")

try:
    with open(_PATH) as f:
        _STOPS = json.load(f)
except Exception:  # noqa: BLE001
    _STOPS = {}

# Live method names (strategy.key) -> the method name used in the study.
KEY_TO_METHOD = {
    "zscore": "ZScoreMR", "s_zscore": "ShortZScore",
    "keltner": "Keltner", "shortkelt": "ShortKeltner",
    "stoch": "Stochastic", "s_stoch": "ShortStoch",
    "williams": "WilliamsR", "shortwill": "ShortWilliams",
    "rangersi": "RangeRSI",
    "cci": "CCI", "s_cci": "ShortCCI",
    "rsidiv": "RSIdiverg", "s_rsidiv": "ShortRSIdiv",
}

# Trend strategies exit on a trailing stop, so their stop is part of the design
# and was validated as such — leave those alone.
TRAILING = {"donchtrend", "s_donch", "supertrend", "s_super"}


def stop_for(strategy_key, symbol, timeframe, default):
    """The measured stop for this strategy-market, or `default` if unknown.

    timeframe=None means "we don't know which timeframe opened this position"
    (an open position doesn't record it). Fall back to the TIGHTEST stop mapped
    for the symbol+method across timeframes — never widen a live stop by more
    than the data actually supports.
    """
    if strategy_key in TRAILING:
        return default
    method = KEY_TO_METHOD.get(strategy_key)
    if not method:
        return default
    if timeframe is None:
        vals = [v for k, v in _STOPS.items()
                if k.startswith(f"{symbol}|{method}|")]
        return min(vals) if vals else default
    return _STOPS.get(f"{symbol}|{method}|{timeframe}", default)


def loaded():
    return len(_STOPS)
