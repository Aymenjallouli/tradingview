"""
mt5_tradelog.py — persistent trade journal. Every OPEN and CLOSE is appended to
a CSV with the exact strategy, symbol, prices, size, and P&L — so you have a
permanent record of what each strategy actually did (the real track record).

File: live/mt5/trades_log.csv  (one row per event, human- and Excel-readable).
"""

import os
import csv
import threading
from datetime import datetime, timezone

_LOG_PATH = os.path.join(os.path.dirname(__file__), "trades_log.csv")
_LOCK = threading.Lock()
_HEADER = ["time_utc", "event", "book", "strategy", "symbol", "side",
           "lots", "price", "sl", "tp", "confidence", "profit_usd", "reason"]


def _ensure_header():
    if not os.path.exists(_LOG_PATH):
        with open(_LOG_PATH, "w", newline="") as f:
            csv.writer(f).writerow(_HEADER)


def log_open(book, strategy, symbol, side, lots, price, sl, tp,
             confidence="", reason=""):
    _write("OPEN", book, strategy, symbol, side, lots, price, sl, tp,
           confidence, "", reason)


def log_close(book, strategy, symbol, profit, reason=""):
    _write("CLOSE", book, strategy, symbol, "", "", "", "", "",
           "", profit, reason)


def _write(event, book, strategy, symbol, side, lots, price, sl, tp,
           confidence, profit, reason):
    row = [datetime.now(timezone.utc).isoformat(), event, book, strategy,
           symbol, side, lots, price, sl, tp, confidence, profit, reason]
    with _LOCK:
        _ensure_header()
        with open(_LOG_PATH, "a", newline="") as f:
            csv.writer(f).writerow(row)


def summary():
    """Read the log back and return per-strategy performance (for a report)."""
    if not os.path.exists(_LOG_PATH):
        return {}
    stats = {}
    with open(_LOG_PATH, newline="") as f:
        for row in csv.DictReader(f):
            if row["event"] != "CLOSE":
                continue
            key = f"{row['book']}/{row['strategy']}"
            s = stats.setdefault(key, {"trades": 0, "wins": 0, "pnl": 0.0})
            try:
                p = float(row["profit_usd"])
            except (ValueError, TypeError):
                continue
            s["trades"] += 1
            s["pnl"] += p
            if p > 0:
                s["wins"] += 1
    return stats
