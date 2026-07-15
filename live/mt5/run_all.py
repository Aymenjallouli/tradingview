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
import time
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


def _book_env(b):
    """The environment for one book. Sizing for the $6.7k account.

    The min-lot constraint that strangled the $743 account is gone: the broker's
    minimum lot now risks ~0.4% (was ~2%), so all markets are tradeable and we
    size by choice, not by the broker's floor. Risk 0.5-1.5% (edge-weighted:
    proven strategies get more, marginal ones less) inside a 12% portfolio cap
    and hard-capped at 2% (Kelly for our measured edge). Survives the 16-trade
    losing streak the walk-forward found (worst case ~-16%, not account death).
    """
    return _env(MT5_BOOK=b["book"], MT5_MAGIC=b["magic"],
                MT5_DASH_PORT=b["port"],
                # Simulate a fresh $2,000 account on the existing demo. Every
                # book sizes and risk-checks against $2k, so together they trade
                # exactly as one $2k account would -- including skipping markets
                # whose min-lot is too big for $2k. The extra demo cash is
                # ignored. Set to 0 to trade the real balance instead.
                MT5_VIRTUAL_EQUITY="2000",
                MT5_RISK_MIN="0.5", MT5_RISK_MAX="1.5",
                MT5_KELLY_CAP="2.0",          # hard ceiling, whatever the score
                MT5_OVERSIZE_CAP="2.0",       # min-lot must fit under 2%
                MT5_MAX_POS="5",              # per book (6 books -> up to 30)
                MT5_MAX_POS_STRAT="2",
                MT5_MAX_PORTFOLIO_RISK="12",  # total across ALL books
                MT5_MAX_GROUP_POS="4",        # per correlated group
                MT5_MAX_GROUP_RISK="4",
                MT5_DAILY_STOP="0.05",
                MT5_REGIME="1", MT5_GOLD_FOCUS="0",
                MT5_DAYTRADER="0", MT5_PYRAMID="0")


def _launch(b):
    return subprocess.Popen([PY, "-u", "mt5_dashboard.py", *DRY],
                            cwd=HERE, env=_book_env(b))


def main():
    # book name -> live process. Supervised: if one dies, it is relaunched.
    procs = {b["name"]: _launch(b) for b in BOOKS}

    print("=" * 62)
    print(" SIX VALIDATED BOOKS RUNNING (isolated by magic, SUPERVISED):")
    for b in BOOKS:
        print(f"   {b['name']:9} -> http://localhost:{b['port']}")
    print(" All walk-forward validated · every trade journaled to trades_log.csv")
    print(" A book that crashes is auto-restarted. Then: python mt5_hub.py (:8800)")
    print("=" * 62)

    running = {"on": True}

    def _stop(*_):
        running["on"] = False
        for p in procs.values():
            try:
                p.terminate()
            except Exception:  # noqa: BLE001
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    # WATCHDOG: the whole point of "keep it running." A book can die from a
    # transient MT5 disconnect, a candle-feed hiccup, or an unhandled edge case.
    # Without this it stays dead and silently stops trading. Poll every 15s and
    # relaunch anything that exited, so the system self-heals unattended.
    fails = {b["name"]: 0 for b in BOOKS}
    while running["on"]:
        time.sleep(15)
        for b in BOOKS:
            p = procs[b["name"]]
            if p.poll() is None:
                fails[b["name"]] = 0            # healthy this cycle
                continue
            fails[b["name"]] += 1
            print(f"[watchdog] {b['name']} exited (code {p.returncode}); "
                  f"restart #{fails[b['name']]}", flush=True)
            procs[b["name"]] = _launch(b)


if __name__ == "__main__":
    main()
