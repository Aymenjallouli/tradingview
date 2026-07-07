"""
forex_backtest.py — Backtests BOTH forex strategies with realistic costs.

Runs the SCALP and SWING strategies (from forex_strategy.py — the same logic
the live trader uses) over yfinance forex candles, and reports each strategy:
    * WITH realistic forex costs (spread + slippage, per pair)
    * WITHOUT costs (frictionless)
side by side, plus buy-and-hold, plus the four success criteria.

This directly answers your question: does forex's much tighter spread let a
scalp survive, and does the slower swing do better?

Run it:
    python forex_backtest.py            # both strategies
    python forex_backtest.py scalp      # just the scalp
    python forex_backtest.py swing      # just the swing

Execution realism: entries fill at the NEXT candle's open after the signal;
costs (spread half + slippage) are applied to every fill via forex_feed.
"""

import sys
from dataclasses import dataclass

import pandas as pd

import forex_config as cfg
import forex_feed as feed
import forex_strategy as fx


@dataclass
class FxTrade:
    pair: str
    pnl: float
    return_pct: float
    cost_paid: float           # $ spread+slippage cost for this trade
    exit_reason: str
    bars_held: int


def backtest(pair: str, df: pd.DataFrame, strat, costs_on: bool):
    """Run one strategy over one pair. Returns (trades, final_equity)."""
    df = strat.add_indicators(df).reset_index()
    time_col = df.columns[0]

    equity = cfg.STARTING_CAPITAL
    trades: list[FxTrade] = []

    in_pos = False
    entry_fill = qty = cash_committed = 0.0
    entry_bar = 0
    entry_cost = 0.0

    n = len(df)
    for i in range(n):
        price = df.iloc[i]["close"]
        if pd.isna(price):
            continue

        if not in_pos:
            if strat.entry_signal(df, i) and i + 1 < n:
                raw = df.iloc[i + 1]["open"]      # next-candle-open fill
                entry_fill = feed.apply_cost(pair, raw, "buy") if costs_on \
                    else raw
                cash_committed = equity * cfg.POSITION_SIZE_PCT
                # Commission (usually 0 for forex) on the deployed cash.
                entry_comm = cash_committed * cfg.COMMISSION_PCT if costs_on \
                    else 0.0
                qty = (cash_committed - entry_comm) / entry_fill
                # Cost captured as the gap between mid and our fill (spread/slip)
                entry_cost = (qty * (entry_fill - raw)) + entry_comm
                entry_bar = i + 1
                in_pos = True

        else:
            bars_held = i - entry_bar
            reason = strat.check_exit(entry_fill, df, i, bars_held)
            if reason is not None:
                raw = price
                exit_fill = feed.apply_cost(pair, raw, "sell") if costs_on \
                    else raw
                gross = qty * exit_fill
                exit_comm = gross * cfg.COMMISSION_PCT if costs_on else 0.0
                net_proceeds = gross - exit_comm
                pnl = net_proceeds - cash_committed
                exit_cost = (qty * (raw - exit_fill)) + exit_comm
                ret = pnl / cash_committed if cash_committed else 0.0
                equity += pnl
                trades.append(FxTrade(
                    pair=pair, pnl=pnl, return_pct=ret,
                    cost_paid=entry_cost + exit_cost,
                    exit_reason=reason, bars_held=bars_held,
                ))
                in_pos = False

    return trades, equity


def stats(trades, start, final):
    n = len(trades)
    if n == 0:
        return {"trades": 0, "net": final - start, "net_pct": 0.0,
                "win_rate": 0.0, "pf": 0.0, "max_dd": 0.0,
                "cost": 0.0, "gross_profit": 0.0, "avg": 0.0}
    wins = [t for t in trades if t.pnl > 0]
    gp = sum(t.pnl for t in wins)
    gl = abs(sum(t.pnl for t in trades if t.pnl <= 0))
    pf = gp / gl if gl > 0 else float("inf")
    eq = peak = start
    mdd = 0.0
    for t in trades:
        eq += t.pnl
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak if peak > 0 else 0.0)
    return {"trades": n, "net": final - start, "net_pct": (final/start-1)*100,
            "win_rate": len(wins)/n*100, "pf": pf, "max_dd": mdd*100,
            "cost": sum(t.cost_paid for t in trades), "gross_profit": gp,
            "avg": sum(t.pnl for t in trades)/n}


def bh_pct(df):
    c = df["close"].dropna()
    return (float(c.iloc[-1])/float(c.iloc[0]) - 1)*100 if len(c) > 1 else 0.0


def _pf(v):
    return "inf" if v == float("inf") else f"{v:.2f}"


def run_strategy(name: str):
    strat = fx.get_strategy(name)
    params = cfg.SCALP if name == "scalp" else cfg.SWING
    interval, period = params["interval"], params["period"]

    print("\n" + "=" * 64)
    print(f"STRATEGY: {name.upper()}  ({interval} candles, {period} history)")
    print("=" * 64)

    all_with, all_no = [], []
    bh_list = []
    n_pairs = 0

    for pair in cfg.PAIRS:
        print(f"\nDownloading {pair} {interval} ...")
        df = feed.get_candles(pair, interval, period)
        if df.empty or len(df) < 210:
            print(f"  Not enough data for {pair}; skipping.")
            continue
        n_pairs += 1
        print(f"  {len(df)} candles ({df.index[0].date()}..{df.index[-1].date()})"
              f"  round-trip cost ~{feed.spread_cost_pct(pair, float(df['close'].iloc[-1])):.4f}%")

        wt, we = backtest(pair, df, strat, costs_on=True)
        nt, ne = backtest(pair, df, strat, costs_on=False)
        ws, ns = stats(wt, cfg.STARTING_CAPITAL, we), stats(nt, cfg.STARTING_CAPITAL, ne)
        bh = bh_pct(df); bh_list.append(bh)

        print(f"  {'':16}{'WITH costs':>14}{'WITHOUT costs':>16}")
        print(f"  {'trades':16}{ws['trades']:>14}{ns['trades']:>16}")
        print(f"  {'net %':16}{ws['net_pct']:>+13.1f}%{ns['net_pct']:>+15.1f}%")
        print(f"  {'win rate':16}{ws['win_rate']:>13.1f}%{ns['win_rate']:>15.1f}%")
        print(f"  {'profit factor':16}{_pf(ws['pf']):>14}{_pf(ns['pf']):>16}")
        print(f"  {'buy & hold':16}{bh:>+13.1f}%")

        all_with.extend(wt); all_no.extend(nt)

    if not all_with:
        print("\nNo trades. Try a different period/pair.")
        return None

    start_total = cfg.STARTING_CAPITAL * max(n_pairs, 1)
    fw = start_total + sum(t.pnl for t in all_with)
    fn = start_total + sum(t.pnl for t in all_no)
    w = stats(all_with, start_total, fw)
    nn = stats(all_no, start_total, fn)
    avg_bh = sum(bh_list)/len(bh_list) if bh_list else 0.0

    print("\n" + "-" * 64)
    print(f"COMBINED — {name.upper()}")
    print(f"  {'':18}{'WITH costs':>14}{'WITHOUT costs':>16}")
    print(f"  {'trades':18}{w['trades']:>14}{nn['trades']:>16}")
    print(f"  {'net P&L $':18}{w['net']:>+13.2f}{nn['net']:>+16.2f}")
    print(f"  {'net %':18}{w['net_pct']:>+13.1f}%{nn['net_pct']:>+15.1f}%")
    print(f"  {'win rate':18}{w['win_rate']:>13.1f}%{nn['win_rate']:>15.1f}%")
    print(f"  {'profit factor':18}{_pf(w['pf']):>14}{_pf(nn['pf']):>16}")
    print(f"  {'max drawdown':18}{w['max_dd']:>13.1f}%{nn['max_dd']:>15.1f}%")
    print(f"  {'total cost paid':18}{w['cost']:>13.2f}{nn['cost']:>16.2f}")
    print(f"  {'buy & hold (avg)':18}{avg_bh:>+13.1f}%")

    gp, cost = w["gross_profit"], w["cost"]
    cost_pct_gross = (cost/gp*100) if gp > 0 else float("inf")
    print(f"\n  Cost as % of gross profit: "
          f"{cost_pct_gross:.0f}%" if gp > 0 else
          "\n  Cost as % of gross profit: N/A (no gross profit)")
    print(f"  Avg P&L per trade: ${w['avg']:+.4f}")

    print("\n  SUCCESS CRITERIA (with full costs):")
    _chk("Profit factor > 1.3", w["pf"] > 1.3, _pf(w["pf"]))
    _chk("Cost < 30% of gross profit", gp > 0 and cost_pct_gross < 30,
         f"{cost_pct_gross:.0f}%" if gp > 0 else "N/A")
    _chk("Beats buy-and-hold", w["net_pct"] > avg_bh,
         f"{w['net_pct']:+.1f}% vs {avg_bh:+.1f}%")
    _chk("200+ trades", w["trades"] >= 200, f"{w['trades']}")

    return {"name": name, "pf": w["pf"], "net_pct": w["net_pct"],
            "trades": w["trades"], "cost_pct_gross": cost_pct_gross}


def _chk(label, ok, detail):
    print(f"    [{'PASS' if ok else 'FAIL'}] {label}  ({detail})")


def main():
    which = sys.argv[1].lower() if len(sys.argv) > 1 else "both"
    print("=" * 64)
    print("FOREX BACKTEST — scalp vs swing, honest costs")
    print(f"Pairs: {', '.join(cfg.PAIRS)}")
    print("Cost model: real per-pair SPREAD (pips) + slippage, applied on fills")
    print("=" * 64)

    results = []
    if which in ("scalp", "both"):
        r = run_strategy("scalp")
        if r:
            results.append(r)
    if which in ("swing", "both"):
        r = run_strategy("swing")
        if r:
            results.append(r)

    if len(results) == 2:
        print("\n" + "=" * 64)
        print("HEAD-TO-HEAD (with full costs)")
        print("=" * 64)
        for r in results:
            print(f"  {r['name'].upper():6}  PF={_pf(r['pf'])}  "
                  f"net={r['net_pct']:+.1f}%  trades={r['trades']}  "
                  f"cost/gross={r['cost_pct_gross']:.0f}%"
                  if r['cost_pct_gross'] != float('inf')
                  else f"  {r['name'].upper():6}  PF={_pf(r['pf'])}  "
                       f"net={r['net_pct']:+.1f}%  trades={r['trades']}")
        winner = max(results, key=lambda r: (r["pf"] if r["pf"] != float("inf")
                                             else 999))
        print(f"\n  Winner on profit factor: {winner['name'].upper()}")

    print("\nDone. Review BEFORE running the live paper trader.")


if __name__ == "__main__":
    main()
