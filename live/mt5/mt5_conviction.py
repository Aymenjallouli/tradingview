"""
mt5_conviction.py — size by MEASURED EDGE, not by how loud the signal is.

WHAT THIS USED TO DO, AND WHY IT WAS WRONG
------------------------------------------
The old score was 40% "strategy agreement" (several strategies firing the same
symbol+direction at once), 30% a hardcoded table of profit factors from the
backtests we later proved were overfit, and 20% trend alignment. We then bet up
to 2x more on a high score.

Agreement was tested over 19,399 replayed trades:

    strategies agreeing     trades   win rate   expectancy
    1 (alone)               13,291        70%     +0.033R
    2                        4,188        68%     +0.033R
    3                        1,472        63%     +0.007R
    4+                         448        71%     +0.056R

    lift from agreement: -0.005R   t = -0.89   ->  NOISE

Agreement predicts NOTHING. Worse, agreement means several strategies piling into
the SAME symbol and direction — so sizing up on it concentrated risk into
correlated bets for zero extra return. We were paying risk and buying nothing.

WHAT ACTUALLY PREDICTS
----------------------
A strategy's own past edge forecasts its future edge. Split every strategy-market
70% past / 30% unseen future:

    correlation(past expectancy, future expectancy) = +0.425
    ranked on the PAST, what they earned NEXT:
        top quartile      +0.066R
        flat (all)        +0.036R
        bottom quartile   +0.030R
    top quartile beats flat by +0.030R, t = +2.18  ->  REAL

So we size on measured expectancy (strategy_quality.json), not on noise.

THE CAP IS NOT TIMIDITY, IT IS ARITHMETIC
-----------------------------------------
The Kelly criterion — the mathematically optimal bet size for a given edge — puts
the maximum safe bet for our measured edge at ~2% of equity. Bet more than Kelly
and long-run growth turns NEGATIVE even while you win most of your trades. We
size in 0.5-1.5% and hard-cap at KELLY_CAP_PCT, i.e. at or under half-Kelly,
because Kelly assumes you know your win rate exactly and we only ESTIMATE ours.
An 8-point error in that estimate — well inside our own confidence interval —
is the difference between compounding and going to zero.

Untested strategies (the trend methods, which this replay cannot score) get
NEUTRAL risk. Unmeasured is not the same as good.
"""

import json
import os

RISK_MIN_PCT = float(os.getenv("MT5_RISK_MIN", "0.5"))
RISK_MAX_PCT = float(os.getenv("MT5_RISK_MAX", "1.5"))
# Hard ceiling. Kelly for our measured edge is ~2%; never exceed it, whatever
# the score says. This is the line between compounding and ruin.
KELLY_CAP_PCT = float(os.getenv("MT5_KELLY_CAP", "2.0"))

_PATH = os.path.join(os.path.dirname(__file__), "strategy_quality.json")
try:
    with open(_PATH) as f:
        _QUALITY = json.load(f)          # "SYMBOL|Method|tf" -> expectancy in R
except Exception:  # noqa: BLE001
    _QUALITY = {}

# Live strategy.key -> the method name used in the study.
KEY_TO_METHOD = {
    "zscore": "ZScoreMR", "s_zscore": "ShortZScore",
    "keltner": "Keltner", "shortkelt": "ShortKeltner",
    "stoch": "Stochastic", "s_stoch": "ShortStoch",
    "williams": "WilliamsR", "shortwill": "ShortWilliams",
    "rangersi": "RangeRSI",
    "cci": "CCI", "s_cci": "ShortCCI",
    "rsidiv": "RSIdiverg", "s_rsidiv": "ShortRSIdiv",
}

_vals = sorted(_QUALITY.values())


def _percentile_of(exp_r):
    """Where this strategy's edge ranks among all measured strategies (0-1)."""
    if not _vals:
        return 0.5
    below = sum(1 for v in _vals if v < exp_r)
    return below / len(_vals)


def expectancy(strategy_key, our_symbol, timeframe):
    """Measured edge in R for this strategy-market, or None if never measured."""
    method = KEY_TO_METHOD.get(strategy_key)
    if not method:
        return None
    return _QUALITY.get(f"{our_symbol}|{method}|{timeframe}")


def confidence(strategy_key, our_symbol, timeframe):
    """0-100: how strong this strategy's MEASURED edge is, vs all the others.

    Not a probability of winning, and not a promise. It is a ranking of edge.
    An unmeasured strategy scores 50 — neutral, because we do not know.
    """
    exp_r = expectancy(strategy_key, our_symbol, timeframe)
    if exp_r is None:
        return 50.0
    return round(100.0 * _percentile_of(exp_r), 1)


def risk_pct_for(conf):
    """Map the 0-100 edge ranking to a risk %, hard-capped at Kelly."""
    r = RISK_MIN_PCT + (RISK_MAX_PCT - RISK_MIN_PCT) * (conf / 100.0)
    return round(min(KELLY_CAP_PCT, max(RISK_MIN_PCT, r)), 3)


def label(conf):
    if conf >= 75:
        return "TOP EDGE"
    if conf >= 55:
        return "STRONG"
    if conf >= 35:
        return "AVERAGE"
    return "WEAK"


def loaded():
    return len(_QUALITY)
