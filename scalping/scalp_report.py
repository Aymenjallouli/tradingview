"""
scalp_report.py — Module C: the verdict report.

Reads the scalp ledger (from either the live scalper or a recorded run) and
prints the metrics that decide whether scalping survived costs:
    * trades count, win rate, profit factor
    * total fees paid vs gross profit
    * fees as % of gross profit   <-- the number that usually kills scalping
    * average profit per trade in dollars
    * net P&L and equity
and saves the equity curve as a PNG.

Run it (after a live run, or it will note the ledger is empty):
    python scalp_report.py

It also evaluates the four success criteria and prints a plain-English verdict.
"""

import matplotlib
matplotlib.use("Agg")  # no GUI needed; we save straight to a file
import matplotlib.pyplot as plt

import scalp_config as cfg
from scalp_ledger import ScalpLedger


def _fmt_pf(pf):
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def build_equity_curve(trades) -> list[float]:
    """Equity after each closed trade, starting from the initial capital."""
    equity = cfg.STARTING_CAPITAL
    curve = [equity]
    for t in trades:
        equity += t["pnl"]
        curve.append(equity)
    return curve


def save_png(curve: list[float], path: str):
    plt.figure(figsize=(10, 5))
    plt.plot(range(len(curve)), curve, linewidth=1.5)
    plt.axhline(cfg.STARTING_CAPITAL, linestyle="--", linewidth=1,
                color="gray", label=f"start ${cfg.STARTING_CAPITAL:.0f}")
    halt_line = cfg.STARTING_CAPITAL * (1 - cfg.HALT_DRAWDOWN_PCT)
    plt.axhline(halt_line, linestyle=":", linewidth=1, color="red",
                label=f"-{cfg.HALT_DRAWDOWN_PCT*100:.0f}% halt")
    plt.title("Scalping experiment — equity curve (with realistic costs)")
    plt.xlabel("Closed trade #")
    plt.ylabel("Equity ($)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def main():
    ledger = ScalpLedger()
    trades = ledger.all_trades()

    print("=" * 58)
    print("SCALP VERDICT REPORT (Module C)")
    print("=" * 58)

    if not trades:
        print("\nThe scalp ledger has no closed trades yet.")
        print("Run the backtester (scalp_backtest.py) to see cost impact, or")
        print("run the live scalper (scalp_live.py) to record paper trades.")
        ledger.close()
        return

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_profit = sum(t["pnl"] for t in wins)          # winners' total P&L
    gross_loss = abs(sum(t["pnl"] for t in losses))
    net = sum(t["pnl"] for t in trades)
    total_fees = sum(t["fees_paid"] for t in trades)
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    win_rate = len(wins) / len(trades) * 100
    avg_pnl = net / len(trades)
    fees_pct_gross = (total_fees / gross_profit * 100) if gross_profit > 0 \
        else float("inf")

    final_equity = ledger.get_equity()

    print(f"\n  Trades:                    {len(trades)}")
    print(f"  Win rate:                  {win_rate:.1f}%")
    print(f"  Profit factor:             {_fmt_pf(pf)}")
    print(f"  Net P&L:                   ${net:+.2f}")
    print(f"  Final equity:              ${final_equity:.2f} "
          f"({(final_equity/cfg.STARTING_CAPITAL-1)*100:+.1f}%)")
    print(f"  Avg P&L per trade:         ${avg_pnl:+.4f}")
    print(f"\n  Gross profit (winners):    ${gross_profit:.2f}")
    print(f"  Total fees paid:           ${total_fees:.2f}")
    if gross_profit > 0:
        print(f"  >> Fees as % of gross:     {fees_pct_gross:.0f}%   "
              f"(this is what kills scalping)")
    else:
        print("  >> Fees as % of gross:     N/A (no gross profit at all)")

    # Equity curve PNG.
    curve = build_equity_curve(trades)
    save_png(curve, cfg.EQUITY_CURVE_PNG)
    print(f"\n  Equity curve saved to:     {cfg.EQUITY_CURVE_PNG}")

    # ------------------------------------------------------------------
    # Success criteria verdict.
    # ------------------------------------------------------------------
    print("\n" + "-" * 58)
    print("SUCCESS CRITERIA (judged WITH full costs):")
    _check("Profit factor > 1.3", pf > 1.3, _fmt_pf(pf))
    _check("Fees < 30% of gross profit",
           gross_profit > 0 and fees_pct_gross < 30,
           f"{fees_pct_gross:.0f}%" if gross_profit > 0 else "N/A")
    _check("Survived 200+ trades without -25% halt",
           len(trades) >= 200 and final_equity >
           cfg.STARTING_CAPITAL * (1 - cfg.HALT_DRAWDOWN_PCT),
           f"{len(trades)} trades, equity ${final_equity:.2f}")
    print("-" * 58)

    all_pass = (pf > 1.3 and gross_profit > 0 and fees_pct_gross < 30
                and len(trades) >= 200
                and final_equity > cfg.STARTING_CAPITAL *
                (1 - cfg.HALT_DRAWDOWN_PCT))
    print("\nVERDICT:", "SCALPING SURVIVED (on paper)" if all_pass
          else "SCALPING FAILED — costs won. It fails harder with real money.")

    ledger.close()


def _check(label: str, passed: bool, detail: str):
    print(f"  [{'PASS' if passed else 'FAIL'}] {label}  ({detail})")


if __name__ == "__main__":
    main()
