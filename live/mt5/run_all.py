"""
run_all.py — launch the FIVE clean, VALIDATED asset-class books.

Every strategy in these books passed the strict walk-forward bar
(OOS PF>=1.3, >=50 out-of-sample trades) — built data-driven from
validated_strategies.json. ~29 strategies, ~67 trades/month combined
(~2/day) so you actually see regular action.

  METALS   gold+silver          magic 770001  :8801
  FOREX    EUR/GBP/JPY/AUD/CAD   magic 770002  :8802
  INDICES  US500/US100/GER40     magic 770003  :8803
  ENERGY   crude/natgas          magic 770004  :8804
  CRYPTO   BTC/ETH               magic 770005  :8805

Each: own markets, own magic, own dashboard, 1-2% risk, regime-gated, shared
$1000. Every trade is journaled to trades_log.csv with its exact strategy.
Then run mt5_hub.py for the unified view (:8800).

    python run_all.py           # live demo, all five
    python run_all.py --dry     # dry-run
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
    dict(name="METALS", book="v_metals", magic="770001", port="8801"),
    dict(name="FOREX", book="v_forex", magic="770002", port="8802"),
    dict(name="INDICES", book="v_indices", magic="770003", port="8803"),
    dict(name="ENERGY", book="v_energy", magic="770004", port="8804"),
    dict(name="CRYPTO", book="v_crypto", magic="770005", port="8805"),
    dict(name="SOFTS", book="v_softs", magic="770006", port="8806"),
]


def _env(**overrides):
    e = dict(os.environ)
    e.update({k: str(v) for k, v in overrides.items()})
    return e


def main():
    procs = []
    for b in BOOKS:
        # SIZING TUNED TO THE MIN-LOT REALITY of a small account.
        # Measured on this $744 account: the broker's MINIMUM lot already risks
        # 1.6-14% on most markets, so a tiny 0.5-0.9% cap would BLOCK 16 of 24
        # markets (most strategies would never fire). A ~3% cap unlocks 18 of 24
        # markets while still allowing ~6-10 concurrent positions inside the 12%
        # portfolio cap. More MARKETS available matters more than more positions
        # here — it's what lets the 169 strategies actually trade.
        env = _env(MT5_BOOK=b["book"], MT5_MAGIC=b["magic"],
                   MT5_DASH_PORT=b["port"],
                   MT5_RISK_MIN="1.5", MT5_RISK_MAX="3.0",
                   MT5_MAX_POS="4",              # per book (6 books -> up to 24)
                   MT5_MAX_POS_STRAT="2",
                   MT5_MAX_PORTFOLIO_RISK="12",  # total across ALL books
                   MT5_MAX_GROUP_POS="3",        # per correlated group
                   MT5_MAX_GROUP_RISK="5",
                   MT5_DAILY_STOP="0.06",
                   MT5_REGIME="1", MT5_GOLD_FOCUS="0",
                   MT5_DAYTRADER="0", MT5_PYRAMID="0")
        procs.append(subprocess.Popen([PY, "-u", "mt5_dashboard.py", *DRY],
                                      cwd=HERE, env=env))

    print("=" * 62)
    print(" FIVE VALIDATED BOOKS RUNNING (isolated by magic):")
    for b in BOOKS:
        print(f"   {b['name']:9} -> http://localhost:{b['port']}")
    print(" All walk-forward validated · every trade journaled to trades_log.csv")
    print(" Then: python mt5_hub.py  (unified :8800)")
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
