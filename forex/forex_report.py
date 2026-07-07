"""
forex_report.py — Verdict report for the forex paper experiment.

Reads the fx_* ledger (from your live runs) and prints the metrics that decide
whether the strategy is working, broken down by strategy (scalp/swing), plus
the cost-as-%-of-gross number and an equity-curve PNG.

Run it (after some live runs):
    python forex_report.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import forex_config as cfg
from forex_ledger import ForexLedger


def _pf(v):
    return "inf" if v == float("inf") else f"{v:.2f}"


def analyze(trades):
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    net = sum(t["pnl"] for t in trades)
    cost = sum(t["cost_paid"] for t in trades)
    pf = gp / gl if gl > 0 else (float("inf") if gp > 0 else 0.0)
    return {"n": n, "win_rate": len(wins)/n*100 if n else 0.0, "pf": pf,
            "net": net, "cost": cost, "gross_profit": gp,
            "avg": net/n if n else 0.0}


def save_png(curve, path):
    plt.figure(figsize=(10, 5))
    plt.plot(range(len(curve)), curve, linewidth=1.5)
    plt.axhline(cfg.STARTING_CAPITAL, ls="--", c="gray", lw=1,
                label=f"start ${cfg.STARTING_CAPITAL:.0f}")
    plt.axhline(cfg.STARTING_CAPITAL*(1-cfg.HALT_DRAWDOWN_PCT), ls=":",
                c="red", lw=1, label=f"-{cfg.HALT_DRAWDOWN_PCT*100:.0f}% halt")
    plt.title("Forex paper experiment — equity curve (with realistic costs)")
    plt.xlabel("Closed trade #")
    plt.ylabel("Equity ($)")
    plt.legend(); plt.grid(True, alpha=0.3); plt.tight_layout()
    plt.savefig(path, dpi=120); plt.close()


def main():
    ledger = ForexLedger()
    trades = ledger.all_trades()

    print("=" * 56)
    print("FOREX VERDICT REPORT")
    print("=" * 56)

    if not trades:
        print("\nNo forex trades recorded yet.")
        print("Run the backtester (forex_backtest.py) to see cost impact, or")
        print("run the live trader (forex_live.py scalp|swing) to record trades.")
        ledger.close()
        return

    # Break down by strategy.
    for strat_name in ("scalp", "swing"):
        subset = [t for t in trades if t["strategy"] == strat_name]
        if not subset:
            continue
        a = analyze(subset)
        cpg = (a["cost"]/a["gross_profit"]*100) if a["gross_profit"] > 0 \
            else float("inf")
        print(f"\n--- {strat_name.upper()} ({a['n']} trades) ---")
        print(f"  Win rate:            {a['win_rate']:.1f}%")
        print(f"  Profit factor:       {_pf(a['pf'])}")
        print(f"  Net P&L:             ${a['net']:+.2f}")
        print(f"  Total cost paid:     ${a['cost']:.4f}")
        print(f"  Cost as % of gross:  "
              f"{cpg:.0f}%" if a["gross_profit"] > 0 else
              "  Cost as % of gross:  N/A")
        print(f"  Avg P&L per trade:   ${a['avg']:+.4f}")

    # Overall + PNG.
    overall = analyze(trades)
    print(f"\n=== OVERALL ({overall['n']} trades) ===")
    print(f"  Net P&L: ${overall['net']:+.2f}  "
          f"Final equity: ${ledger.get_equity():.2f}  "
          f"PF: {_pf(overall['pf'])}")

    equity = cfg.STARTING_CAPITAL
    curve = [equity]
    for t in trades:
        equity += t["pnl"]
        curve.append(equity)
    save_png(curve, cfg.EQUITY_CURVE_PNG)
    print(f"  Equity curve saved to: {cfg.EQUITY_CURVE_PNG}")

    print("\n" + "-" * 56)
    print("SUCCESS CRITERIA (with full costs):")
    cpg = (overall["cost"]/overall["gross_profit"]*100) \
        if overall["gross_profit"] > 0 else float("inf")
    _chk("Profit factor > 1.3", overall["pf"] > 1.3, _pf(overall["pf"]))
    _chk("Cost < 30% of gross", overall["gross_profit"] > 0 and cpg < 30,
         f"{cpg:.0f}%" if overall["gross_profit"] > 0 else "N/A")
    _chk("200+ trades", overall["n"] >= 200, f"{overall['n']}")
    ledger.close()


def _chk(label, ok, detail):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  ({detail})")


if __name__ == "__main__":
    main()
