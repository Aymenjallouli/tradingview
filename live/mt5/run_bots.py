"""
run_bots.py — launch the FOUR short-term asset-class bots on one account.

Each bot trades ONLY its asset class, with the best short-term strategy per
asset (cross-asset backtest sweep, cost-included). All short-term, all range/
burst — the proven short-term edges. Isolated by magic number.

  BOOK  METALS   gold+silver          magic 770001  :8801  (gold range PF 4.86)
  BOOK  FOREX    JPY/AUD/EUR/GBP      magic 770002  :8802  (USDJPY range 5.37!)
  BOOK  INDICES  US500/US100/oil/gas  magic 770003  :8803  (US500 range 2.50)
  BOOK  CRYPTO   BTC/ETH (weekend)    magic 770004  :8804  (BTC range 1.23)

Each: own markets, own magic, own dashboard, 1-2% risk, regime-gated, all share
the $1000 balance. Then run mt5_hub.py for the unified view.

    python run_bots.py           # live demo, all four
    python run_bots.py --dry     # dry-run
Stop: Ctrl+C.
"""

import os
import sys
import subprocess
import signal

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
DRY = ["--dry"] if "--dry" in sys.argv else []

BOOKS = [
    dict(name="METALS · short-term", book="st_metals", magic="770001", port="8801"),
    dict(name="FOREX · short-term", book="st_forex", magic="770002", port="8802"),
    dict(name="INDICES+ENERGY · short-term", book="st_indices", magic="770003", port="8803"),
    dict(name="CRYPTO · short-term (weekend)", book="st_crypto", magic="770004", port="8804"),
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
                   MT5_REGIME="1", MT5_GOLD_FOCUS="0",
                   MT5_DAYTRADER="0", MT5_PYRAMID="0")
        procs.append(subprocess.Popen([PY, "-u", "mt5_dashboard.py", *DRY],
                                      cwd=HERE, env=env))

    print("=" * 64)
    print(" FOUR SHORT-TERM BOOKS RUNNING (isolated by magic):")
    for b in BOOKS:
        print(f"   {b['name']:30} -> http://localhost:{b['port']}")
    print(" All short-term · regime-gated · 1-2% risk · shared $1000")
    print(" Then: python mt5_hub.py  for the unified view (:8800)")
    print("=" * 64)

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
