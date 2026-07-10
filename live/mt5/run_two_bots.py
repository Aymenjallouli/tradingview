"""
run_two_bots.py — launch TWO independent bots on the same account.

  Bot A "MAIN"       : the full metals book (slow 4h/daily + fast), magic 770001,
                       dashboard on :8800
  Bot B "DAY-TRADER" : fast metals only (15m/1h), max 5 trades/day, stop after
                       3 losses, magic 770002, dashboard on :8801

They are fully ISOLATED — each tags its trades with its own magic number and
only sees/manages its own positions, so they never collide.

    python run_two_bots.py           # live demo, both bots
    python run_two_bots.py --dry     # dry-run both

Open http://localhost:8800 (main) and http://localhost:8801 (day-trader).
Stop: Ctrl+C (kills both).
"""

import os
import sys
import subprocess
import signal

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
DRY = ["--dry"] if "--dry" in sys.argv else []


def _env(**overrides):
    e = dict(os.environ)
    e.update({k: str(v) for k, v in overrides.items()})
    return e


def main():
    procs = []
    # Risk lowered 2-5% -> 1-2% after two bots double-lost ~$49 on one gold move.
    # Different markets so they NEVER double-bet the same thing:
    #   Bot A (MAIN)  = GOLD only
    #   Bot B (DAY)   = SILVER only
    procs.append(subprocess.Popen(
        [PY, "-u", "mt5_dashboard.py", *DRY], cwd=HERE,
        env=_env(MT5_GOLD_FOCUS="1", MT5_PYRAMID="0",
                 MT5_MAGIC="770001", MT5_DASH_PORT="8800",
                 MT5_DAYTRADER="0", MT5_ONLY_SYMBOLS="XAUUSD",
                 MT5_RISK_MIN="1.0", MT5_RISK_MAX="2.0")))
    procs.append(subprocess.Popen(
        [PY, "-u", "mt5_dashboard.py", *DRY], cwd=HERE,
        env=_env(MT5_DAYTRADER="1", MT5_MAGIC="770002",
                 MT5_DASH_PORT="8801", MT5_GOLD_FOCUS="0",
                 MT5_ONLY_SYMBOLS="XAGUSD",
                 MT5_MAX_TRADES_DAY="5", MT5_MAX_LOSSES_DAY="3",
                 MT5_RISK_MIN="1.0", MT5_RISK_MAX="2.0")))

    print("=" * 60)
    print(" TWO BOTS RUNNING (isolated: different markets + magic):")
    print("   MAIN (GOLD)      -> http://localhost:8800  (magic 770001)")
    print("   DAY-TRADER (SILVER) -> http://localhost:8801  (magic 770002)")
    print("   Risk lowered to 1-2%/trade. No double-betting.")
    print("=" * 60)
    print(" Ctrl+C to stop both.")

    def _stop(*_):
        for p in procs:
            try:
                p.terminate()
            except Exception:  # noqa: BLE001
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    for p in procs:
        p.wait()


if __name__ == "__main__":
    main()
