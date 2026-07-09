"""
mt5_conviction.py — confidence-based position sizing.

NOT "guaranteed trades" (those do not exist — anyone promising them is lying).
This is what real traders actually do: size UP on higher-confidence setups and
DOWN on weak ones. Confidence is a 0-100 score built from honest, measurable
factors — never a promise of a win.

Confidence factors (add up, capped at 100):
  * base .................................. 10   every signal starts here
  * strategy agreement ................. 0-40   +20 per extra strategy signalling
                                                the SAME symbol this poll (2 strats
                                                agreeing = strong; 3+ = very strong)
  * backtested edge of the market ...... 0-30   scaled by the market's Donchian/Trend
                                                profit factor (Brent PF 2.88 -> high;
                                                marginal PF ~1.1 -> low)
  * trend alignment ....................... 20   price above its 200-EMA (with-trend)

Sizing maps confidence -> risk %:
  * conf   0 .............. RISK_MIN_PCT (default 1.0%)
  * conf 100 .............. RISK_MAX_PCT (default 2.5%)
  * linear in between, then HARD-capped by RISK_MAX_PCT.

So the strongest setups (multiple strategies agree, strong market, with-trend)
risk ~2.5% and the weakest lone signals risk ~1.0% — more behind the best odds,
less behind the marginal ones. Still every trade has a broker SL/TP.
"""

import os

# AGGRESSIVE sizing (user choice): weak setups risk 2%, strongest 5%.
# On $1000 that's ~$20 (low conf) to ~$50 (very high conf) per trade — and a
# high-conf 2:1 winner is ~$100. The flip side: a few high-conf losers in a row
# can draw the account down 15-20%. Tune via env MT5_RISK_MIN / MT5_RISK_MAX.
RISK_MIN_PCT = float(os.getenv("MT5_RISK_MIN", "2.0"))
RISK_MAX_PCT = float(os.getenv("MT5_RISK_MAX", "5.0"))

# Backtested profit factors (cost-included, from the chat's backtests). Used to
# score how strong the EDGE is on each market. Best available PF across the
# strategies we ran. Unknown markets get a neutral 1.2.
MARKET_EDGE = {
    # energy — the standouts
    "GASOLINE": 7.05, "BRENT": 2.88, "NATGAS": 2.60, "CRUDE": 2.10,
    # indices / metals / softs
    "JPN225": 3.41, "UK100": 2.70, "COPPER": 1.68, "XPTUSD": 1.34,
    "COFFEE": 1.82, "SOYBEANS": 1.38, "WHEAT": 3.23,
    # equities
    "GOOGL": 10.77, "NFLX": 2.95, "AAPL": 2.62, "AMZN": 1.63, "META": 1.23,
    "NVDA": 3.50, "AMD": 2.69, "INTC": 2.40, "MSFT": 1.36,
    # metals / crypto
    "XAGUSD": 3.11, "XAUUSD": 2.23, "BTCUSD": 3.00, "ETHUSD": 1.50,
}
NEUTRAL_EDGE = 1.2


def edge_score(our_symbol):
    """0-30 based on the market's backtested profit factor."""
    pf = MARKET_EDGE.get(our_symbol, NEUTRAL_EDGE)
    # PF 1.0 -> 0 pts, PF 3.0+ -> full 30 pts (clamped)
    frac = max(0.0, min(1.0, (pf - 1.0) / 2.0))
    return 30.0 * frac


def confidence(our_symbol, agree_count, trend_aligned):
    """Compute a 0-100 confidence score for a signal.

    agree_count   = how many strategies signalled this symbol THIS poll (>=1)
    trend_aligned = bool, price above its 200-EMA (with the long trend)
    """
    score = 10.0                                   # base
    score += min(40.0, 20.0 * max(0, agree_count - 1))   # agreement
    score += edge_score(our_symbol)                # backtested edge
    if trend_aligned:
        score += 20.0                              # with-trend
    return round(min(100.0, score), 1)


def risk_pct_for(conf):
    """Map a 0-100 confidence score to a risk %, hard-capped at RISK_MAX_PCT."""
    r = RISK_MIN_PCT + (RISK_MAX_PCT - RISK_MIN_PCT) * (conf / 100.0)
    return round(min(RISK_MAX_PCT, max(RISK_MIN_PCT, r)), 3)


def label(conf):
    if conf >= 75:
        return "VERY HIGH"
    if conf >= 55:
        return "HIGH"
    if conf >= 35:
        return "MEDIUM"
    return "LOW"
