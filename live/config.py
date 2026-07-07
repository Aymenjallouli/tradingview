"""
config.py — Settings for the real-time multi-strategy engine.

Runs THREE paper accounts side by side, each its own strategy + data feed:

  TREND  — crypto, 4h candles, Binance WebSocket (real-time). Proven (PF ~1.37).
           Trades a few times a WEEK.
  SCALP  — crypto, 1m candles, Binance WebSocket (real-time). Fast, trades often.
           LOST money in backtest (costs) — real-time action to watch.
  FOREX  — USD/JPY etc, 5m candles, yfinance (~60s refresh). Best economics
           (tight spreads); swing on USD/JPY was the most promising (PF 1.34).

All paper money. No broker, no keys, no real funds.
"""

import os

# Load a local .env file (if present) so you can keep tokens/settings out of
# the code. Copy .env.example to .env and fill it in. Safe if python-dotenv
# isn't installed or there's no .env — it just does nothing.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:  # noqa: BLE001
    pass

STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", "50"))
POSITION_SIZE_PCT = 0.95        # trend/forex sizing
SCALP_POSITION_PCT = 0.30       # scalp sizing (smaller, more frequent)

# Which strategies to run (comma-separated: trend,scalp,forex).
ENABLED = os.getenv("ENABLED", "trend,scalp,forex").split(",")

# Shared realistic costs.
FEE_PCT = 0.001                 # 0.1% per side
SLIPPAGE_PCT = 0.0005           # 0.05% per fill

# ---------------------------------------------------------------------------
# Data feeds
# ---------------------------------------------------------------------------
# Crypto (Binance, real-time WebSocket + REST warmup).
CRYPTO_SYMBOLS = os.getenv("CRYPTO_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
BINANCE_REST = os.getenv("BINANCE_REST", "https://data-api.binance.vision")
BINANCE_WS = os.getenv("BINANCE_WS", "wss://stream.binance.com:9443")

# Forex (yfinance, ~60s refresh — no free tick feed exists for forex).
FOREX_SYMBOLS = os.getenv("FOREX_SYMBOLS", "USDJPY=X,EURUSD=X").split(",")
FOREX_POLL_SECONDS = 60
# Realistic forex spread cost per pair, in pips (yfinance gives mid prices).
FOREX_SPREADS = {                # pip_size, spread_pips
    "USDJPY=X": {"pip": 0.01, "spread": 0.7},
    "EURUSD=X": {"pip": 0.0001, "spread": 0.5},
    "GBPUSD=X": {"pip": 0.0001, "spread": 0.8},
}
FOREX_SLIPPAGE_PIPS = 0.2

# ---------------------------------------------------------------------------
# TREND strategy params (proven 4h config)
# ---------------------------------------------------------------------------
TREND_TIMEFRAME = os.getenv("TREND_TIMEFRAME", "4h")
TREND_EMA_FAST = 20
TREND_EMA_SLOW = 100
TREND_EMA_TREND = 200
TREND_RSI_PERIOD = 14
TREND_RSI_MAX = 70
TREND_STOP = 0.08
TREND_TARGET = 0.15

# ---------------------------------------------------------------------------
# SCALP strategy params (crypto 1m mean-reversion)
# ---------------------------------------------------------------------------
SCALP_TIMEFRAME = os.getenv("SCALP_TIMEFRAME", "1m")
SCALP_BB_PERIOD = 20
SCALP_BB_STD = 2.0
SCALP_RSI_PERIOD = 7
# RSI < 25 almost never fires in a calm market (you'd wait days to see a trade).
# Loosened to 40 so the scalper actually trades and you can WATCH it work.
# Honest note: trading more often means paying more costs — this makes the
# "costs eat scalping" lesson show up faster, not slower.
SCALP_RSI_ENTRY = int(os.getenv("SCALP_RSI_ENTRY", "45"))
# How close to the lower band counts as "at the band" (0.001 = 0.1% above it).
# Bigger = trades more often. This is the main knob for scalp activity.
SCALP_BAND_TOL = float(os.getenv("SCALP_BAND_TOL", "0.0015"))
SCALP_STOP = 0.006              # -0.6%
SCALP_MAX_HOLD_MIN = 30

# ---------------------------------------------------------------------------
# FOREX strategy params (5m swing — best backtest result)
# ---------------------------------------------------------------------------
FOREX_TIMEFRAME = os.getenv("FOREX_TIMEFRAME", "5m")
FOREX_EMA_FAST = 20
FOREX_EMA_SLOW = 50
FOREX_EMA_TREND = 200
FOREX_RSI_PERIOD = 14
FOREX_RSI_MAX = 70
FOREX_STOP = 0.006             # -0.6%
FOREX_TARGET = 0.012           # +1.2%

# ---------------------------------------------------------------------------
# Files & networking
# ---------------------------------------------------------------------------
WARMUP_CANDLES = 400
DATABASE_PATH = os.getenv("DATABASE_PATH", "live_trades.db")
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8000"))
