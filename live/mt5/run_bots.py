"""
run_bots.py — launch the THREE clean books, each isolated, on one account.

  BOOK 1  METALS (long-term)  gold+silver  magic 770001  dashboard :8801
  BOOK 2  SHORT-TERM (fast)   gold+silver  magic 770002  dashboard :8802
  BOOK 3  CRYPTO              BTC+ETH      magic 770003  dashboard :8803

Each book:
  * trades ONLY its own markets (books 1 & 2 share gold/silver but are separated
    by magic number so they manage their own positions; book 3 is BTC/ETH)
  * tags trades with its own magic number (no cross-management)
  * has its own dashboard/radar
  * sizes risk at 1-2% per trade (all 3 share the $1000 balance)

    python run_bots.py           # live demo, all three books
    python run_bots.py --dry     # dry-run

Stop: Ctrl+C (kills all three).
"""

import os
import sys
import subprocess
import signal

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
DRY = ["--dry"] if "--dry" in sys.argv else []

BOOKS = [
    dict(name="BOOK 1 · METALS (long-term)", book="metals",
         magic="770001", port="8801"),
    dict(name="BOOK 2 · SHORT-TERM (fast)", book="shortterm",
         magic="770002", port="8802", daytrader="1"),
    dict(name="BOOK 3 · CRYPTO", book="crypto",
         magic="770003", port="8803"),
]


def _env(**overrides):
    e = dict(os.environ)
    e.update({k: str(v) for k, v in overrides.items()})
    return e


def main():
    procs = []
    for b in BOOKS:
        env = _env(MT5_BOOK=b["book"], MT5_MAGIC=b["magic"],
                   MT5_DASH_PORT=b["port"],
                   MT5_RISK_MIN="1.0", MT5_RISK_MAX="2.0",
                   MT5_DAYTRADER=b.get("daytrader", "0"),
                   MT5_GOLD_FOCUS="0", MT5_PYRAMID="0")
        procs.append(subprocess.Popen([PY, "-u", "mt5_dashboard.py", *DRY],
                                      cwd=HERE, env=env))

    print("=" * 62)
    print(" THREE BOOKS RUNNING (isolated by magic number):")
    for b in BOOKS:
        print(f"   {b['name']:28} -> http://localhost:{b['port']}")
    print(" Risk 1-2%/trade · shared $1000 balance · Ctrl+C stops all.")
    print("=" * 62)

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
