"""
config.py — Central configuration for the whole paper-trading system.

Everything that you might reasonably want to tweak lives here so you never
have to hunt through the code. All other modules import from this file.

Beginner note: think of this as the "settings" file. Changing a number here
changes the behaviour of the backtester AND the live modules at the same time,
because they all read from this one place.
"""

# ---------------------------------------------------------------------------
# Capital & sizing
# ---------------------------------------------------------------------------
STARTING_CAPITAL = 50.0        # Virtual starting cash, in USD
POSITION_SIZE_PCT = 0.95       # Use 95% of current equity per trade

# ---------------------------------------------------------------------------
# Symbols & timeframe
# ---------------------------------------------------------------------------
# NOTE: yfinance uses "BTC-USD" / "ETH-USD" for crypto, and plain tickers
# ("SPY", "AAPL") for stocks. These strings are what we pass to yfinance.
SYMBOLS = ["BTC-USD", "ETH-USD", "SPY", "AAPL"]

# 4-hour candles. Chosen by optimize.py: 4h was far more robust than 1h
# (1h combined profit factor was 0.90 — a loser; 4h reaches ~1.88).
# For "4h", data_feed builds candles by resampling 1h data automatically.
TIMEFRAME = "4h"

# ---------------------------------------------------------------------------
# Strategy parameters (trend following)
# ---------------------------------------------------------------------------
# These values were selected by the parameter sweep in optimize.py, then
# sanity-checked with a walk-forward split. See README "Optimization results".
# EMA_SLOW=100 (instead of 50) cut whipsaw trades; the wider 15% target and
# 8% stop let winners run and stopped the -3% stop from being knifed by noise.
EMA_FAST = 20                  # Fast EMA
EMA_SLOW = 100                 # Slow EMA (was 50 — 100 reduced whipsaws)
EMA_TREND = 200                # Long-term trend filter EMA
RSI_PERIOD = 14                # RSI look-back
RSI_MAX_ENTRY = 70             # Don't enter if RSI is at/above this (overbought)

# ---------------------------------------------------------------------------
# Risk management (exits)
# ---------------------------------------------------------------------------
STOP_LOSS_PCT = 0.08           # -8% stop loss (wider = fewer noise stop-outs)
TAKE_PROFIT_PCT = 0.15         # +15% take profit (let winners run)

# ---------------------------------------------------------------------------
# Trading costs (make the simulation realistic)
# ---------------------------------------------------------------------------
FEE_PCT = 0.001                # 0.1% fee per trade SIDE (buy and sell each)
SLIPPAGE_PCT = 0.0005          # 0.05% slippage per fill

# ---------------------------------------------------------------------------
# Files & paths
# ---------------------------------------------------------------------------
DATABASE_PATH = "trades.db"    # SQLite database for the paper broker
REPORTS_DIR = "reports"        # Where daily AI reviews are saved
TRADE_LOG_CSV = "trade_log.csv"  # CSV export destination

# ---------------------------------------------------------------------------
# Webhook security (Module 2)
# ---------------------------------------------------------------------------
# CHANGE THIS to your own random secret before exposing the webhook server.
# TradingView must send this exact value in the alert payload.
WEBHOOK_SECRET = "change-me-to-a-long-random-string"

# ---------------------------------------------------------------------------
# Backtest settings (Module 4)
# ---------------------------------------------------------------------------
BACKTEST_YEARS = 3             # How many years of history to test
