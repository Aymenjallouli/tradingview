"""
mt5_runner.py — the always-on MT5 trading loop.

Runs the orchestrator continuously on THIS machine (where the MT5 terminal is).
Polls on a schedule, lets strategies fire on new candle closes, manages trailing
stops, enforces the risk governor + daily circuit breaker, and exposes a
snapshot for the dashboard.

This CANNOT run on the Linux VPS — MT5's Python API only talks to a local
Windows terminal. Run it here alongside the terminal.

    python mt5_runner.py                # live demo trading
    python mt5_runner.py --dry          # dry-run (compute, send nothing)
"""

import sys
import threading
import time
from datetime import datetime, timezone

from mt5_bridge import MT5Bridge
from mt5_orchestrator import Orchestrator
import mt5_orders as orders

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None

POLL_SECONDS = 60          # check for new candles / manage stops every minute
TRAIL_AFTER = 0.04         # start trailing after +4% in favor
TRAIL_DISTANCE = 0.03      # trail 3% behind the best price


def _log(m):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [runner] {m}", flush=True)


class MT5Runner:
    def __init__(self, dry_run=False):
        self.bridge = MT5Bridge()
        self.orch = None
        self.dry_run = dry_run
        self._running = False
        self.connected = False

    def _manage_trailing(self):
        """Move stops up on winning positions (trailing stop)."""
        if self.dry_run or mt5 is None:
            return
        for p in orders.open_positions():
            tick = mt5.symbol_info_tick(p.symbol)
            if not tick:
                continue
            if p.type == mt5.ORDER_TYPE_BUY:
                gain = tick.bid / p.price_open - 1
                if gain >= TRAIL_AFTER:
                    new_sl = tick.bid * (1 - TRAIL_DISTANCE)
                    if new_sl > p.sl:        # only ratchet up
                        orders.modify_stop(p, new_sl)
            else:  # short
                gain = p.price_open / tick.ask - 1
                if gain >= TRAIL_AFTER:
                    new_sl = tick.ask * (1 + TRAIL_DISTANCE)
                    if new_sl < p.sl or p.sl == 0:
                        orders.modify_stop(p, new_sl)

    def run(self):
        if not self.bridge.connect():
            _log("Could not connect to a DEMO MT5 terminal. Exiting.")
            return
        self.connected = True
        self.orch = Orchestrator(self.bridge, dry_run=self.dry_run)
        _log(f"MT5 runner started ({'DRY-RUN' if self.dry_run else 'LIVE DEMO'}). "
             f"Strategies: {[s.key for s in self.orch.strategies]}. "
             f"Poll every {POLL_SECONDS}s.")
        self._running = True
        while self._running:
            try:
                if not self.bridge.connected:
                    self.bridge.reconnect()
                self.orch.poll_once()
                self._manage_trailing()
            except Exception as exc:  # noqa: BLE001
                _log(f"loop error: {exc}")
                self.connected = self.bridge.connected
            for _ in range(POLL_SECONDS):
                if not self._running:
                    break
                time.sleep(1)

    def stop(self):
        self._running = False

    def snapshot(self):
        if self.orch is None:
            return {"connected": False, "status": "starting"}
        st = self.orch.status()
        st["connected"] = self.bridge.connected
        return st


# Shared instance for the dashboard to import.
RUNNER = MT5Runner(dry_run="--dry" in sys.argv)


if __name__ == "__main__":
    try:
        RUNNER.run()
    except KeyboardInterrupt:
        RUNNER.stop()
        _log("stopped by user.")
