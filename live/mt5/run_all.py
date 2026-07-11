"""
run_all.py — launch ALL books: the validated long-term metals book PLUS the
4 experimental short-term asset-class bots. Each isolated by magic + port.

  METALS-LT   (validated)   gold+silver   magic 770001  :8801
  METALS-ST   (short-term)  gold+silver   magic 770002  :8802
  FOREX-ST    (short-term)  JPY/AUD/EUR/GBP magic 770003 :8803
  INDICES-ST  (short-term)  US500/US100/oil/gas magic 770004 :8804
  CRYPTO-ST   (short-term)  BTC/ETH        magic 770005  :8805

NOTE (honest): only METALS-LT passed walk-forward. The 4 ST books did NOT —
they're here to FORWARD-TEST on demo (real fills), which is the only test
backtest can't fake. Watch their live results before trusting them.

    python run_all.py           # live demo, all five
    python run_all.py --dry     # dry-run
Then: python mt5_hub.py   (unified view on :8800)
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
    dict(name="METALS-LT (validated)", book="metals", magic="770001", port="8801"),
    dict(name="METALS-ST", book="st_metals", magic="770002", port="8802"),
    dict(name="FOREX-ST", book="st_forex", magic="770003", port="8803"),
    dict(name="INDICES-ST", book="st_indices", magic="770004", port="8804"),
    dict(name="CRYPTO-ST", book="st_crypto", magic="770005", port="8805"),
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

    print("=" * 66)
    print(" FIVE BOOKS RUNNING (isolated by magic):")
    for b in BOOKS:
        print(f"   {b['name']:24} -> http://localhost:{b['port']}")
    print(" Only METALS-LT is validated; the 4 ST books are forward-tests.")
    print(" Then: python mt5_hub.py  (unified :8800)")
    print("=" * 66)

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
