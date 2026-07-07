"""
forex_config.py — All settings for the FOREX experiment in one place.

This experiment answers the question the crypto scalper raised:
    "Scalping died because cost (~0.3%/round-trip) was bigger than the edge.
     Forex has much TIGHTER spreads. Does the edge now survive the (smaller)
     cost? And does a slower 'swing' version do even better?"

We test TWO strategies on the SAME data with the SAME honest cost model:
    * SCALP  — fast mean-reversion on 1-minute candles (like the crypto one)
    * SWING  — slower trend-pullback on higher timeframe, bigger targets

REALISTIC COST MODEL — THE KEY DIFFERENCE FROM CRYPTO
-----------------------------------------------------
yfinance forex candles are MID prices (they do NOT include the spread). In real
forex trading, the spread IS your main cost. So we model it explicitly, per
pair, in PIPS — this is the honest, realistic cost we're testing against.

A "pip" is the standard forex price increment:
    * For most pairs (EUR/USD, GBP/USD): 1 pip = 0.0001
    * For JPY pairs (USD/JPY):           1 pip = 0.01
"""

# ---------------------------------------------------------------------------
# Capital & sizing
# ---------------------------------------------------------------------------
STARTING_CAPITAL = 50.0
POSITION_SIZE_PCT = 0.30       # 30% of equity per trade (matches the crypto test)

# ---------------------------------------------------------------------------
# Pairs. yfinance uses the '=X' suffix for forex.
# pip_size = the price value of 1 pip for that pair.
# spread_pips = a realistic RETAIL spread (what a typical broker charges).
#   These are deliberately on the honest/conservative side — real spreads widen
#   during news and off-hours, so this is the optimistic-but-fair case.
# ---------------------------------------------------------------------------
PAIRS = {
    "EURUSD=X": {"pip_size": 0.0001, "spread_pips": 0.5},
    "GBPUSD=X": {"pip_size": 0.0001, "spread_pips": 0.8},
    "USDJPY=X": {"pip_size": 0.01,   "spread_pips": 0.7},
}

# ---------------------------------------------------------------------------
# SCALP strategy (fast mean-reversion, 1-minute) — mirrors the crypto scalper
# ---------------------------------------------------------------------------
SCALP = {
    "interval": "1m",
    "period": "5d",            # yfinance serves ~5-7 days of 1m forex
    "bb_period": 20,
    "bb_std": 2.0,
    "rsi_period": 7,
    "rsi_entry_max": 25,       # oversold entry
    "stop_loss_pct": 0.0015,   # -0.15% (tight, scalp-sized)
    "take_profit_mode": "bb_mid",  # exit at middle Bollinger Band
    "max_hold_minutes": 30,
}

# ---------------------------------------------------------------------------
# SWING strategy (trend pullback, 5-minute) — fewer, BIGGER trades so the
# fixed cost is a small fraction of each trade's target.
# ---------------------------------------------------------------------------
SWING = {
    "interval": "5m",
    "period": "30d",           # ~30 days of 5m candles
    "ema_fast": 20,
    "ema_slow": 50,
    "ema_trend": 200,
    "rsi_period": 14,
    "rsi_entry_max": 70,
    "stop_loss_pct": 0.006,    # -0.6%
    "take_profit_pct": 0.012,  # +1.2% (2:1 reward:risk; cost is tiny vs this)
}

# ---------------------------------------------------------------------------
# Non-spread costs. Most retail forex brokers are "commission-free" and bake
# the cost into the spread, so we set commission to 0 and let the spread be the
# cost. Slippage is a small extra to stay honest about real fills.
# ---------------------------------------------------------------------------
COMMISSION_PCT = 0.0           # per side; 0 for typical spread-only brokers
SLIPPAGE_PIPS = 0.2            # extra pips of slippage per side (realistic)

# ---------------------------------------------------------------------------
# Live trader
# ---------------------------------------------------------------------------
POLL_SECONDS = 60
HALT_DRAWDOWN_PCT = 0.25

# ---------------------------------------------------------------------------
# Files. Shares the project DB but uses its OWN fx_* tables.
# ---------------------------------------------------------------------------
DATABASE_PATH = "../trades.db"
EQUITY_CURVE_PNG = "forex_equity_curve.png"
