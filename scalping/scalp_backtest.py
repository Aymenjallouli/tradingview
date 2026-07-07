"""
scalp_backtest.py — Module A: the scalping backtester.

Runs the mean-reversion scalp (from scalp_strategy.py — the SAME logic the live
scalper uses) over 1-minute Binance history, and reports results TWO ways side
by side:
    (1) WITH fees + slippage   (realistic)
    (2) WITHOUT fees + slippage (frictionless fantasy)
so you can see exactly how much trading costs destroy.

Also compares against buy-and-hold over the same window.

Run it:
    python scalp_backtest.py

Execution realism enforced here:
  * A signal is detected on a CLOSED candle (bar i).
  * The entry FILLS at bar i+1's OPEN (next candle) — never bar i's close.
  * Exits fill at the candle close on which the exit condition is met.
"""

from dataclasses import dataclass

import pandas as pd

import scalp_config as cfg
import scalp_strategy as strat
import binance_feed


@dataclass
class ScalpTrade:
    symbol: str
    entry_time: object
    exit_time: object
    entry_fill: float          # price actually paid (incl. slippage if costs on)
    exit_fill: float           # price actually received
    qty: float
    pnl: float                 # net $ after (optional) fees
    return_pct: float
    fees_paid: float           # total $ fees on this trade (0 if costs off)
    exit_reason: str
    bars_held: int


def _apply_slippage(price: float, side: str, costs_on: bool) -> float:
    if not costs_on:
        return price
    if side == "buy":
        return price * (1 + cfg.SLIPPAGE_PCT)
    return price * (1 - cfg.SLIPPAGE_PCT)


def backtest_symbol(symbol: str, df: pd.DataFrame,
                    costs_on: bool) -> tuple[list[ScalpTrade], float]:
    """Run the scalp over one symbol's 1m candles.

    `costs_on` toggles fees + slippage. Returns (trades, final_equity).
    """
    df = strat.add_indicators(df).reset_index()
    time_col = df.columns[0]  # 'open_time' after reset_index

    equity = cfg.STARTING_CAPITAL
    trades: list[ScalpTrade] = []

    in_position = False
    entry_fill = 0.0
    qty = 0.0
    cash_committed = 0.0
    entry_bar = 0
    entry_time = None
    entry_fee = 0.0

    n = len(df)
    for i in range(n):
        row = df.iloc[i]
        price = row["close"]
        if pd.isna(price):
            continue

        if not in_position:
            # Detect a signal on the CLOSED bar i; fill at bar i+1's OPEN.
            if strat.entry_signal(df, i) and i + 1 < n:
                raw_fill = df.iloc[i + 1]["open"]  # NEXT candle open
                entry_fill = _apply_slippage(raw_fill, "buy", costs_on)

                cash_committed = equity * cfg.POSITION_SIZE_PCT
                entry_fee = cash_committed * cfg.FEE_PCT if costs_on else 0.0
                qty = (cash_committed - entry_fee) / entry_fill

                entry_bar = i + 1
                entry_time = df.iloc[i + 1][time_col]
                in_position = True

        else:
            bars_held = i - entry_bar
            reason = strat.check_exit(entry_fill, df, i, bars_held)
            if reason is not None:
                exit_fill = _apply_slippage(price, "sell", costs_on)
                gross = qty * exit_fill
                exit_fee = gross * cfg.FEE_PCT if costs_on else 0.0
                net_proceeds = gross - exit_fee
                pnl = net_proceeds - cash_committed
                ret = pnl / cash_committed if cash_committed else 0.0
                equity += pnl

                trades.append(ScalpTrade(
                    symbol=symbol,
                    entry_time=entry_time,
                    exit_time=df.iloc[i][time_col],
                    entry_fill=entry_fill,
                    exit_fill=exit_fill,
                    qty=qty,
                    pnl=pnl,
                    return_pct=ret,
                    fees_paid=entry_fee + exit_fee,
                    exit_reason=reason,
                    bars_held=bars_held,
                ))
                in_position = False

    return trades, equity


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def compute_stats(trades: list[ScalpTrade], start: float,
                  final: float) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "net": final - start, "net_pct": 0.0,
                "win_rate": 0.0, "profit_factor": 0.0, "max_dd": 0.0,
                "fees": 0.0, "gross_profit": 0.0, "avg_pnl": 0.0}

    wins = [t for t in trades if t.pnl > 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl <= 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    equity = start
    peak = start
    max_dd = 0.0
    for t in trades:
        equity += t.pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0.0)

    fees = sum(t.fees_paid for t in trades)
    # "Gross profit" = sum of winning trades' P&L BEFORE we net losses; but for
    # the fees-as-%-of-gross metric we want gross profit = total positive P&L
    # produced by the strategy (the winners), which is gross_win.
    return {
        "trades": n,
        "net": final - start,
        "net_pct": (final / start - 1) * 100,
        "win_rate": len(wins) / n * 100,
        "profit_factor": pf,
        "max_dd": max_dd * 100,
        "fees": fees,
        "gross_profit": gross_win,
        "avg_pnl": sum(t.pnl for t in trades) / n,
    }


def buy_and_hold_pct(df: pd.DataFrame) -> float:
    closes = df["close"].dropna()
    if len(closes) < 2:
        return 0.0
    return (float(closes.iloc[-1]) / float(closes.iloc[0]) - 1) * 100


def _fmt_pf(pf):
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def print_side_by_side(symbol: str, with_costs: dict, no_costs: dict,
                       bh: float):
    print(f"\n=== {symbol} ===")
    print(f"  {'metric':<22}{'WITH costs':>16}{'WITHOUT costs':>16}")
    print(f"  {'-'*54}")
    rows = [
        ("Trades", f"{with_costs['trades']}", f"{no_costs['trades']}"),
        ("Net P&L $",
         f"${with_costs['net']:+.2f}", f"${no_costs['net']:+.2f}"),
        ("Net P&L %",
         f"{with_costs['net_pct']:+.1f}%", f"{no_costs['net_pct']:+.1f}%"),
        ("Win rate",
         f"{with_costs['win_rate']:.1f}%", f"{no_costs['win_rate']:.1f}%"),
        ("Profit factor",
         _fmt_pf(with_costs['profit_factor']),
         _fmt_pf(no_costs['profit_factor'])),
        ("Max drawdown",
         f"{with_costs['max_dd']:.1f}%", f"{no_costs['max_dd']:.1f}%"),
        ("Total fees paid",
         f"${with_costs['fees']:.2f}", f"${no_costs['fees']:.2f}"),
    ]
    for label, a, b in rows:
        print(f"  {label:<22}{a:>16}{b:>16}")
    print(f"  {'Buy & hold':<22}{bh:>+15.1f}%")


def main():
    print("=" * 60)
    print("SCALP BACKTEST (Module A) — mean-reversion, 1m candles")
    print(f"Symbols: {', '.join(cfg.SYMBOLS)}   Window: {cfg.BACKTEST_DAYS}d")
    print("Entry: close < lower BB(20,2) AND RSI(7) < 25")
    print("Exit: middle BB / -0.6% stop / 30m max hold")
    print(f"Costs: {cfg.FEE_PCT*100:.1f}% fee/side + "
          f"{cfg.SLIPPAGE_PCT*100:.2f}% slippage; entry fills NEXT candle open")
    print("=" * 60)

    combined_with = {"net": 0.0, "trades": 0, "fees": 0.0, "gross_profit": 0.0}
    all_with_trades: list[ScalpTrade] = []
    all_no_trades: list[ScalpTrade] = []
    bh_list = []

    for symbol in cfg.SYMBOLS:
        print(f"\nDownloading {cfg.BACKTEST_DAYS}d of 1m {symbol} ...")
        df = binance_feed.get_history(symbol, cfg.BACKTEST_DAYS)
        if df.empty or len(df) < cfg.BB_PERIOD + 5:
            print(f"  Not enough data for {symbol}; skipping.")
            continue
        print(f"  Got {len(df)} candles "
              f"({df.index[0].date()} to {df.index[-1].date()})")

        start = cfg.STARTING_CAPITAL
        wt, wf_equity = backtest_symbol(symbol, df, costs_on=True)
        nt, nf_equity = backtest_symbol(symbol, df, costs_on=False)

        w_stats = compute_stats(wt, start, wf_equity)
        n_stats = compute_stats(nt, start, nf_equity)
        bh = buy_and_hold_pct(df)
        bh_list.append(bh)

        print_side_by_side(symbol, w_stats, n_stats, bh)

        all_with_trades.extend(wt)
        all_no_trades.extend(nt)

    # ------------------------------------------------------------------
    # Combined view + the metric that usually kills scalping.
    # ------------------------------------------------------------------
    if all_with_trades:
        n_symbols = len({t.symbol for t in all_with_trades})
        start_total = cfg.STARTING_CAPITAL * max(n_symbols, 1)
        final_with = start_total + sum(t.pnl for t in all_with_trades)
        final_no = start_total + sum(t.pnl for t in all_no_trades)

        w = compute_stats(all_with_trades, start_total, final_with)
        nn = compute_stats(all_no_trades, start_total, final_no)
        avg_bh = sum(bh_list) / len(bh_list) if bh_list else 0.0

        print("\n" + "=" * 60)
        print("COMBINED (all symbols)")
        print("=" * 60)
        print_side_by_side("ALL SYMBOLS", w, nn, avg_bh)

        # The headline number.
        gross = w["gross_profit"]
        fees = w["fees"]
        fees_pct_of_gross = (fees / gross * 100) if gross > 0 else float("inf")

        print("\n" + "-" * 60)
        print("THE NUMBER THAT USUALLY KILLS SCALPING:")
        print(f"  Total fees paid (with costs):     ${fees:.2f}")
        print(f"  Gross profit from winners:        ${gross:.2f}")
        if gross > 0:
            print(f"  Fees as % of gross profit:        {fees_pct_of_gross:.0f}%")
        else:
            print("  Fees as % of gross profit:        N/A (no gross profit)")
        print(f"  Avg P&L per trade (with costs):   ${w['avg_pnl']:+.4f}")
        print("-" * 60)

        # Verdict against the success criteria.
        print("\nSUCCESS CRITERIA (judged WITH full costs):")
        pf = w["profit_factor"]
        _check("Profit factor > 1.3", pf > 1.3, _fmt_pf(pf))
        _check("Fees < 30% of gross profit",
               gross > 0 and fees_pct_of_gross < 30,
               f"{fees_pct_of_gross:.0f}%" if gross > 0 else "N/A")
        _check("Beats buy-and-hold", w["net_pct"] > avg_bh,
               f"{w['net_pct']:+.1f}% vs {avg_bh:+.1f}%")
        _check(f"At least 200 trades", w["trades"] >= 200,
               f"{w['trades']} trades")
    else:
        print("\nNo trades generated. Try a longer BACKTEST_DAYS window.")

    print("\nDone. This is Module A. Review BEFORE running the live scalper.")


def _check(label: str, passed: bool, detail: str):
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {label}  ({detail})")


if __name__ == "__main__":
    main()
