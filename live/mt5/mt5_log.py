"""
mt5_log.py — one shared, in-memory log buffer for the whole MT5 wing.

Every module's _log() writes here AND prints to the terminal, so the dashboard
can show the SAME full stream you'd see in the console: every order request,
response, signal, close, trailing-stop modify, heartbeat, and error.

Thread-safe (the runner loops in a background thread while FastAPI serves).
"""

import threading
from collections import deque
from datetime import datetime, timezone

_LOCK = threading.Lock()
_BUF = deque(maxlen=500)          # keep the last 500 events


def emit(source, message):
    """Record one event (and print it to the terminal too)."""
    ts = datetime.now(timezone.utc)
    line = f"[{ts.strftime('%Y-%m-%d %H:%M:%S')}] [{source}] {message}"
    print(line, flush=True)
    with _LOCK:
        _BUF.append({"time": ts.isoformat(), "source": source,
                     "msg": message})


def recent(n=200):
    """Most-recent-first list of the last n events (for the dashboard)."""
    with _LOCK:
        items = list(_BUF)
    return items[-n:][::-1]
