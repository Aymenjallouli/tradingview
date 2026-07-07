"""
scalp_config.py — All settings for the SCALPING experiment in one place.

This is a SEPARATE experiment from the trend system in the parent folder. It
tests a mean-reversion scalp on 1-minute crypto candles to answer one question:
    "Can scalping survive realistic trading costs?"

Nothing here is softened. Fees and slippage are set to realistic Binance spot
values on purpose — the whole point is to measure how much they hurt.
"""

# ---------------------------------------------------------------------------
# Capital & sizing
# ---------------------------------------------------------------------------
STARTING_CAPITAL = 50.0        # Virtual starting cash, USD
POSITION_SIZE_PCT = 0.30       # Use 30% of current equity per trade

# ---------------------------------------------------------------------------
# Symbols & timeframe (Binance spot market data, no API key needed)
# ---------------------------------------------------------------------------
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
INTERVAL = "1m"                # 1-minute candles

# ---------------------------------------------------------------------------
# Strategy parameters — mean-reversion scalp
# ---------------------------------------------------------------------------
BB_PERIOD = 20                 # Bollinger Band moving-average length
BB_STD = 2.0                   # Bollinger Band standard-deviation multiplier
RSI_PERIOD = 7                 # RSI look-back (short, for scalping)
RSI_ENTRY_MAX = 25             # Enter only when RSI is BELOW this (oversold)

# ---------------------------------------------------------------------------
# Exits
# ---------------------------------------------------------------------------
STOP_LOSS_PCT = 0.006          # -0.6% hard stop
MAX_HOLD_MINUTES = 30          # Force-exit after 30 minutes (candles) max hold
# Take-profit is "price touches the middle Bollinger Band" — computed live.

# ---------------------------------------------------------------------------
# Realistic cost model — DO NOT SOFTEN. This is the experiment.
# ---------------------------------------------------------------------------
FEE_PCT = 0.001                # 0.1% per side (Binance spot taker)
SLIPPAGE_PCT = 0.0005          # 0.05% per side
# Execution realism: entries fill at the NEXT candle's OPEN after the signal,
# never the signal candle's close. (Handled in the backtester/live logic.)

# ---------------------------------------------------------------------------
# Live scalper (Module B)
# ---------------------------------------------------------------------------
POLL_SECONDS = 60              # Poll Binance every 60 seconds
HALT_DRAWDOWN_PCT = 0.25       # Auto-halt if equity drops 25% from start

# ---------------------------------------------------------------------------
# Backtest window
# ---------------------------------------------------------------------------
BACKTEST_DAYS = 30             # How many days of 1m history to pull & test

# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
# The SQLite database is SHARED with the trend system (parent folder), but the
# scalping module writes to its OWN tables (prefixed scalp_*), so the two
# experiments never mix. Path is relative to the project root.
DATABASE_PATH = "../trades.db"
EQUITY_CURVE_PNG = "scalp_equity_curve.png"

# Binance public market-data hosts. data-api.binance.vision is the recommended
# no-key, no-geo-block host; api.binance.com is the fallback.
BINANCE_HOSTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
]
