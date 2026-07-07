"""
process_manager.py — Runs and tracks the trading scripts as subprocesses.

The dashboard uses this to:
  * run one-shot jobs (backtests, optimizers) and capture their output, and
  * start/stop long-running LIVE traders and know whether they're alive.

Everything is launched with the SAME Python interpreter running this server,
using each script's own working directory, so imports resolve exactly as they
do when you run the scripts by hand.

Output is streamed to log files under dashboard/logs/ so the front-end can tail
them. We never run more than one live trader per system at a time.
"""

import os
import subprocess
import sys
import threading
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

PY = sys.executable  # the interpreter running the dashboard


# ---------------------------------------------------------------------------
# Registry of everything the dashboard can launch.
#   cwd      : working directory (matters for relative imports/paths)
#   argv     : command after the python executable
#   kind     : "job" (runs and finishes) or "live" (long-running)
# ---------------------------------------------------------------------------
TASKS = {
    # One-shot jobs -------------------------------------------------------
    "trend_backtest":  {"cwd": ROOT, "argv": ["backtest.py"], "kind": "job"},
    "trend_optimize":  {"cwd": ROOT, "argv": ["optimize.py"], "kind": "job"},
    "scalp_backtest":  {"cwd": os.path.join(ROOT, "scalping"),
                        "argv": ["scalp_backtest.py"], "kind": "job"},
    "forex_backtest_both": {"cwd": os.path.join(ROOT, "forex"),
                            "argv": ["forex_backtest.py"], "kind": "job"},
    "forex_backtest_scalp": {"cwd": os.path.join(ROOT, "forex"),
                             "argv": ["forex_backtest.py", "scalp"], "kind": "job"},
    "forex_backtest_swing": {"cwd": os.path.join(ROOT, "forex"),
                             "argv": ["forex_backtest.py", "swing"], "kind": "job"},
    "forex_optimize":  {"cwd": os.path.join(ROOT, "forex"),
                        "argv": ["forex_optimize.py"], "kind": "job"},
    # Long-running live traders ------------------------------------------
    "trend_signals":   {"cwd": ROOT, "argv": ["check_signals.py"], "kind": "job"},
    "scalp_live":      {"cwd": os.path.join(ROOT, "scalping"),
                        "argv": ["scalp_live.py"], "kind": "live"},
    "forex_live_swing": {"cwd": os.path.join(ROOT, "forex"),
                         "argv": ["forex_live.py", "swing"], "kind": "live"},
    "forex_live_scalp": {"cwd": os.path.join(ROOT, "forex"),
                         "argv": ["forex_live.py", "scalp"], "kind": "live"},
}


class ManagedProcess:
    def __init__(self, key):
        self.key = key
        self.proc = None
        self.log_path = os.path.join(LOG_DIR, f"{key}.log")
        self.started_at = None
        self.kind = TASKS[key]["kind"]

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.is_running():
            return False, "already running"
        task = TASKS[self.key]
        # Fresh log each start. Line-buffered so the tail is live.
        logf = open(self.log_path, "w", encoding="utf-8", buffering=1)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        logf.write(f"=== started {self.key} at {stamp} ===\n")
        logf.flush()

        # PYTHONUNBUFFERED so child output reaches the log promptly.
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen(
            [PY, *task["argv"]],
            cwd=task["cwd"],
            stdout=logf,
            stderr=subprocess.STDOUT,
            env=env,
        )
        self.started_at = stamp
        return True, "started"

    def stop(self):
        if not self.is_running():
            return False, "not running"
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        return True, "stopped"

    def status(self):
        return {
            "key": self.key,
            "kind": self.kind,
            "running": self.is_running(),
            "started_at": self.started_at,
            "returncode": (self.proc.poll() if self.proc else None),
        }

    def tail(self, lines=200):
        if not os.path.exists(self.log_path):
            return ""
        with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
            data = f.readlines()
        return "".join(data[-lines:])


# One manager instance per task key, created lazily.
_MANAGERS = {}
_LOCK = threading.Lock()


def get(key):
    if key not in TASKS:
        raise KeyError(f"Unknown task: {key}")
    with _LOCK:
        if key not in _MANAGERS:
            _MANAGERS[key] = ManagedProcess(key)
        return _MANAGERS[key]


def all_status():
    out = {}
    for key in TASKS:
        out[key] = get(key).status()
    return out
