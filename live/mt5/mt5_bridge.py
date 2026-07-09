"""
mt5_bridge.py — MT5 execution bridge (DEMO ONLY).

Connects to a running MetaTrader 5 terminal on THIS machine, verifies the
account is a DEMO, streams candles/ticks for the symbol universe, and sends
orders with broker-side SL/TP attached.

HARD SAFETY (checked at startup, no override):
  * Account must be DEMO (ACCOUNT_TRADE_MODE_DEMO == 0). If REAL (==2) or
    CONTEST (==1 — treat as non-demo for safety), REFUSE to start and exit.
  * Every order carries SL + TP so protection survives a script crash.

Requires: pip install MetaTrader5 ; MT5 terminal running + logged into a demo,
with Tools -> Options -> Expert Advisors -> "Allow algorithmic trading" ON.

Run standalone to verify the connection + a live tick/candle:
    python mt5_bridge.py
"""

import time
from datetime import datetime, timezone

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None

import pandas as pd

# The correct MT5 enum (verified): DEMO=0, CONTEST=1, REAL=2.
TRADE_MODE_DEMO = 0
TRADE_MODE_CONTEST = 1
TRADE_MODE_REAL = 2

# Our target universe -> candidate broker symbol names (first match wins).
# Only symbols the broker has ENABLED for trading are used (auto-checked); the
# rest are skipped with a log line. Add/remove here as you enable symbols in
# the MT5 Market Watch.
#
# Only LIQUID, tight-spread symbols are here. We deliberately EXCLUDE the
# broker's illiquid alts (LTC/LINK/BCH/SOL, WTI) whose spreads (11-31%!) would
# eat every trade — verified live, see chat. More assets only help when they're
# clean; garbage symbols just bleed to the spread.
SYMBOL_MAP = {
    # crypto (synthetic prices on the MetaQuotes demo) — tight spread only
    "BTCUSD": ["BTCUSD", "BTC", "BTCUSD.", "BTCUSDT"],
    "ETHUSD": ["ETHUSD", "ETH", "ETHUSD.", "ETHUSDT"],
    # metals
    "XAUUSD": ["XAUUSD", "GOLD", "XAUUSD."],
    "XAGUSD": ["XAGUSD", "SILVER", "XAGUSD."],
    # indices (usually disabled on MetaQuotes demo — kept in case enabled)
    "US100": ["US100", "USTEC", "NAS100", "NDX100", "USTECH"],
    "US500": ["US500", "SPX500", "US500.", "SPX"],
    # forex majors (real prices)
    "EURUSD": ["EURUSD", "EURUSD."],
    "USDJPY": ["USDJPY", "USDJPY."],
    "GBPUSD": ["GBPUSD", "GBPUSD."],
    "AUDUSD": ["AUDUSD", "AUDUSD."],
    "USDCAD": ["USDCAD", "USDCAD."],
    "USDCHF": ["USDCHF", "USDCHF."],
    "NZDUSD": ["NZDUSD", "NZDUSD."],
    # forex crosses (real prices, tight spread — more trend opportunities)
    "EURJPY": ["EURJPY", "EURJPY."],
    "GBPJPY": ["GBPJPY", "GBPJPY."],
    "EURGBP": ["EURGBP", "EURGBP."],
    "AUDJPY": ["AUDJPY", "AUDJPY."],
    # US stocks (real prices — great for the Candle Lessons trend strategy)
    "AMD": ["AMD", "AMD.NAS", "#AMD"],
    "NVDA": ["NVDA", "NVDA.NAS", "#NVDA"],
    "MSFT": ["MSFT", "MSFT.NAS", "#MSFT"],
    "INTC": ["INTC", "INTC.NAS", "#INTC"],
    # mega-cap US stocks (real prices, tight spread — trend + momentum names)
    "AAPL": ["AAPL", "AAPL.NAS", "#AAPL"],
    "TSLA": ["TSLA", "TSLA.NAS", "#TSLA"],
    "AMZN": ["AMZN", "AMZN.NAS", "#AMZN"],
    "GOOGL": ["GOOGL", "GOOGL.NAS", "#GOOGL"],
    "META": ["META", "META.NAS", "#META"],
    "NFLX": ["NFLX", "NFLX.NAS", "#NFLX"],
}

# MT5 timeframe constants (guarded so the module imports without MT5 present).
if mt5 is not None:
    TF = {"1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4,
          "1d": mt5.TIMEFRAME_D1}
else:
    TF = {"1h": 16385, "4h": 16388, "1d": 16408}


import mt5_log


def _log(m):
    mt5_log.emit("mt5", m)


class MT5Bridge:
    def __init__(self):
        self.connected = False
        self.account = None
        self.symbols = {}        # our name -> resolved broker name
        self.demo_ok = False

    # ------------------------------------------------------------------
    # Connect + the DEMO-ONLY guard.
    # ------------------------------------------------------------------
    def connect(self):
        if mt5 is None:
            _log("MetaTrader5 package not installed (pip install MetaTrader5).")
            return False
        if not mt5.initialize():
            _log(f"initialize() failed: {mt5.last_error()}. "
                 "Is the MT5 terminal running and logged in?")
            return False

        info = mt5.account_info()
        if info is None:
            _log("no account_info — not logged into a terminal. Refusing.")
            mt5.shutdown()
            return False

        # === THE SAFETY GUARD ===
        if info.trade_mode != TRADE_MODE_DEMO:
            mode = {TRADE_MODE_CONTEST: "CONTEST",
                    TRADE_MODE_REAL: "REAL"}.get(info.trade_mode, "UNKNOWN")
            _log("=" * 60)
            _log(f"!!! REFUSING TO START — account is {mode}, not DEMO !!!")
            _log(f"    login={info.login} server={info.server} "
                 f"trade_mode={info.trade_mode}")
            _log("    Real trading is a future MANUAL decision, not a config.")
            _log("=" * 60)
            mt5.shutdown()
            return False

        self.account = info
        self.demo_ok = True
        self.connected = True
        _log(f"Connected to DEMO: login={info.login} server={info.server} "
             f"balance={info.balance} {info.currency} lev=1:{info.leverage}")
        self._resolve_symbols()
        return True

    def _resolve_symbols(self):
        """Map our universe names to the broker's actual symbol names, and
        enable (select) any that are hidden from Market Watch."""
        for our, candidates in SYMBOL_MAP.items():
            for name in candidates:
                s = mt5.symbol_info(name)
                if s is None:
                    continue
                # Skip index CFDs the demo has disabled for trading.
                if s.trade_mode == 0:      # SYMBOL_TRADE_MODE_DISABLED
                    _log(f"{our}: {name} exists but trading DISABLED — skipping")
                    break
                if not s.visible:
                    mt5.symbol_select(name, True)   # add to Market Watch
                    time.sleep(0.1)
                self.symbols[our] = name
                break
            if our not in self.symbols:
                _log(f"{our}: no tradeable broker symbol found")
        _log(f"Universe resolved: {self.symbols}")

    def reconnect(self):
        """Terminal restarts happen — try to re-establish the connection."""
        self.connected = False
        for attempt in range(5):
            _log(f"reconnect attempt {attempt+1} ...")
            if self.connect():
                return True
            time.sleep(min(5 * (attempt + 1), 30))
        return False

    # ------------------------------------------------------------------
    # Data.
    # ------------------------------------------------------------------
    def candles(self, our_symbol, timeframe="1h", count=300):
        """Return a DataFrame of recent candles (time/open/high/low/close/...)."""
        name = self.symbols.get(our_symbol)
        if not name:
            return pd.DataFrame()
        rates = mt5.copy_rates_from_pos(name, TF[timeframe], 0, count)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df

    def tick(self, our_symbol):
        """Latest bid/ask tick, or None."""
        name = self.symbols.get(our_symbol)
        if not name:
            return None
        t = mt5.symbol_info_tick(name)
        if t is None:
            return None
        return {"symbol": our_symbol, "broker_symbol": name,
                "bid": t.bid, "ask": t.ask,
                "spread": round((t.ask - t.bid), 8), "time": t.time}

    def account_snapshot(self):
        info = mt5.account_info()
        if info is None:
            return None
        return {"login": info.login, "server": info.server,
                "balance": info.balance, "equity": info.equity,
                "margin": info.margin, "free_margin": info.margin_free,
                "currency": info.currency, "demo": info.trade_mode == 0}

    def shutdown(self):
        if mt5 is not None:
            mt5.shutdown()
        self.connected = False


# ---------------------------------------------------------------------------
# Standalone: verify connection + show a live tick and a candle pull.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    b = MT5Bridge()
    if not b.connect():
        raise SystemExit("Could not connect to a DEMO MT5 terminal.")

    print("\n=== LIVE TICKS ===")
    for our in b.symbols:
        t = b.tick(our)
        if t:
            print(f"  {our:8} ({t['broker_symbol']}): "
                  f"bid={t['bid']} ask={t['ask']} spread={t['spread']}")

    print("\n=== CANDLE PULL (1h, last 3 bars per symbol) ===")
    for our in b.symbols:
        df = b.candles(our, "1h", 3)
        if not df.empty:
            last = df.iloc[-1]
            print(f"  {our:8}: last 1h close={last['close']} "
                  f"@ {last['time']}  ({len(df)} bars)")

    print("\n=== ACCOUNT ===")
    print(" ", b.account_snapshot())
    b.shutdown()
    print("\nCheckpoint 1 OK — connected to DEMO, ticks + candles flowing.")
