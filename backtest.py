"""
backtest.py — Module 4: the backtester.

Runs the EXACT SAME strategy logic as the live system (imported from
strategy.py) over years of historical data for all 4 symbols, then reports
performance per symbol and combined, with a buy-and-hold comparison.

Run it:
    python backtest.py

Metrics reported per symbol and combined:
    * Net profit ($ and %)
    * Win rate (% of trades that made money)
    * Profit factor (gross wins / gross losses)
    * Max drawdown (worst peak-to-trough equity drop)
    * Number of trades
    * Buy-and-hold comparison (what if you just held the asset?)

Trading realism applied on every fill:
    * 0.1% fee per side
    * 0.05% slippage
Position sizing: 95% of current equity, one position at a time per symbol.
"""

from dataclasses import dataclass, field

import pandas as pd

import config
import data_feed
import strategy


# ---------------------------------------------------------------------------
# A single completed trade (for the log and stats)
# ---------------------------------------------------------------------------
@dataclass
class Trade:
    symbol: str
    entry_time: object
    exit_time: object
    entry_price: float       # the raw candle price at entry
    exit_price: float        # the raw candle price at exit
    fill_entry: float        # price after slippage (what we actually paid)
    fill_exit: float         # price after slippage (what we actually got)
    qty: float
    pnl: float               # net profit/loss in $ (after fees & slippage)
    return_pct: float        # net return on the cash committed to this trade
    exit_reason: str


# ---------------------------------------------------------------------------
# Apply slippage + fees to a fill
# ---------------------------------------------------------------------------
def apply_slippage(price: float, side: str) -> float:
    """When you BUY you pay a bit MORE; when you SELL you get a bit LESS.

    `side` is "buy" or "sell".
    """
    if side == "buy":
        return price * (1 + config.SLIPPAGE_PCT)
    else:  # sell
        return price * (1 - config.SLIPPAGE_PCT)


# ---------------------------------------------------------------------------
# Backtest a single symbol
# ---------------------------------------------------------------------------
def backtest_symbol(symbol: str, df: pd.DataFrame,
                    starting_equity: float) -> tuple[list[Trade], float]:
    """Walk bar-by-bar through `df`, opening/closing one position at a time.

    Returns (list_of_trades, final_equity).

    Beginner note on how a single trade's money works here:
      * We commit 95% of current equity in cash to the trade.
      * We buy `qty` units at the slipped entry price and pay the entry fee.
      * On exit we sell `qty` at the slipped exit price and pay the exit fee.
      * The net P&L is added back to equity.
    """
    df = strategy.add_indicators(df)
    df = df.reset_index()  # make the datetime a normal column we can read

    # Find the datetime column name (yfinance calls it 'Datetime' or 'Date').
    time_col = "Datetime" if "Datetime" in df.columns else "Date"
    if time_col not in df.columns:
        time_col = df.columns[0]  # fallback: first column is the index

    equity = starting_equity
    trades: list[Trade] = []

    in_position = False
    entry_price = 0.0
    fill_entry = 0.0
    qty = 0.0
    cash_committed = 0.0
    entry_time = None

    for i in range(len(df)):
        price = df.iloc[i]["Close"]
        if pd.isna(price):
            continue

        if not in_position:
            # Look for an entry signal.
            if strategy.entry_signal(df, i):
                entry_price = float(price)
                fill_entry = apply_slippage(entry_price, "buy")

                # Commit 95% of equity as cash to this trade.
                cash_committed = equity * config.POSITION_SIZE_PCT
                # Entry fee is charged on the cash we deploy.
                entry_fee = cash_committed * config.FEE_PCT
                # Buy as many units as the remaining cash allows.
                qty = (cash_committed - entry_fee) / fill_entry

                entry_time = df.iloc[i][time_col]
                in_position = True

        else:
            # We hold a position — check whether to exit.
            reason = strategy.check_exit(entry_price, float(price), df, i)
            if reason is not None:
                fill_exit = apply_slippage(float(price), "sell")

                # Proceeds from selling qty units, minus the exit fee.
                gross_proceeds = qty * fill_exit
                exit_fee = gross_proceeds * config.FEE_PCT
                net_proceeds = gross_proceeds - exit_fee

                # P&L = what we got back minus the cash we committed.
                pnl = net_proceeds - cash_committed
                return_pct = pnl / cash_committed if cash_committed else 0.0

                equity += pnl

                trades.append(Trade(
                    symbol=symbol,
                    entry_time=entry_time,
                    exit_time=df.iloc[i][time_col],
                    entry_price=entry_price,
                    exit_price=float(price),
                    fill_entry=fill_entry,
                    fill_exit=fill_exit,
                    qty=qty,
                    pnl=pnl,
                    return_pct=return_pct,
                    exit_reason=reason,
                ))

                in_position = False

    return trades, equity


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def compute_stats(trades: list[Trade], starting_equity: float,
                  final_equity: float) -> dict:
    """Turn a list of trades into the headline performance numbers."""
    n = len(trades)
    if n == 0:
        return {
            "trades": 0,
            "net_profit": final_equity - starting_equity,
            "net_profit_pct": (final_equity / starting_equity - 1) * 100,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
        }

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]

    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))

    # Profit factor = total winnings / total losses. Higher is better; >1 means
    # the strategy made money overall. If there were no losses, it's infinite.
    if gross_loss > 0:
        profit_factor = gross_win / gross_loss
    else:
        profit_factor = float("inf") if gross_win > 0 else 0.0

    win_rate = len(wins) / n * 100

    # Max drawdown: rebuild the equity curve trade-by-trade and find the worst
    # drop from a peak.
    equity = starting_equity
    peak = starting_equity
    max_dd = 0.0
    for t in trades:
        equity += t.pnl
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, drawdown)

    return {
        "trades": n,
        "net_profit": final_equity - starting_equity,
        "net_profit_pct": (final_equity / starting_equity - 1) * 100,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_dd * 100,
    }


def buy_and_hold_return(df: pd.DataFrame) -> float:
    """% return if you simply bought at the first bar and held to the last."""
    closes = df["Close"].dropna()
    if len(closes) < 2:
        return 0.0
    first = float(closes.iloc[0])
    last = float(closes.iloc[-1])
    if first == 0:
        return 0.0
    return (last / first - 1) * 100


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------
def _fmt_pf(pf: float) -> str:
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def print_report(symbol: str, stats: dict, bh_pct: float, resolution: str):
    print(f"\n=== {symbol}  ({resolution}) ===")
    print(f"  Trades:          {stats['trades']}")
    print(f"  Net profit:      ${stats['net_profit']:.2f} "
          f"({stats['net_profit_pct']:+.1f}%)")
    print(f"  Win rate:        {stats['win_rate']:.1f}%")
    print(f"  Profit factor:   {_fmt_pf(stats['profit_factor'])}")
    print(f"  Max drawdown:    {stats['max_drawdown_pct']:.1f}%")
    print(f"  Buy & hold:      {bh_pct:+.1f}%")
    verdict = "BEAT" if stats["net_profit_pct"] > bh_pct else "LOST TO"
    print(f"  Strategy {verdict} buy & hold")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print(f"BACKTEST — timeframe {config.TIMEFRAME}, "
          f"starting capital ${config.STARTING_CAPITAL:.2f}")
    print(f"Strategy: {config.EMA_FAST}/{config.EMA_SLOW} EMA cross, "
          f"{config.EMA_TREND} EMA trend filter, RSI<{config.RSI_MAX_ENTRY}")
    print(f"Exits: -{config.STOP_LOSS_PCT*100:.0f}% stop / "
          f"+{config.TAKE_PROFIT_PCT*100:.0f}% target / EMA cross-down")
    print(f"Costs: {config.FEE_PCT*100:.1f}% fee/side, "
          f"{config.SLIPPAGE_PCT*100:.2f}% slippage")
    print("Note: intraday history from Yahoo is capped (~2y for 1h-based).")
    print("=" * 60)

    all_trades: list[Trade] = []
    combined_net = 0.0
    combined_start = 0.0
    # For an apples-to-apples combined view, each symbol runs its own $50
    # sleeve (they trade independently, one position per symbol).
    per_symbol_start = config.STARTING_CAPITAL

    bh_returns = []

    for symbol in config.SYMBOLS:
        print(f"\nDownloading data for {symbol} ...")
        df = data_feed.get_backtest_candles(symbol, config.BACKTEST_YEARS)

        if df.empty or len(df) < config.EMA_TREND:
            print(f"  Not enough data for {symbol}, skipping.")
            continue

        # Report the actual timeframe and date span we received, so you always
        # know exactly what was tested.
        idx = df.index
        if len(idx) > 2:
            span_days = (idx[-1] - idx[0]).days
            resolution = (f"{config.TIMEFRAME} candles, {len(df)} bars, "
                          f"~{span_days/365:.1f}y "
                          f"({idx[0].date()} to {idx[-1].date()})")
        else:
            resolution = "unknown"

        trades, final_equity = backtest_symbol(symbol, df, per_symbol_start)
        stats = compute_stats(trades, per_symbol_start, final_equity)
        bh = buy_and_hold_return(df)
        bh_returns.append(bh)

        print_report(symbol, stats, bh, resolution)

        all_trades.extend(trades)
        combined_net += stats["net_profit"]
        combined_start += per_symbol_start

    # ------------------------------------------------------------------
    # Combined report across all symbols
    # ------------------------------------------------------------------
    if all_trades:
        combined_final = combined_start + combined_net
        combined_stats = compute_stats(all_trades, combined_start,
                                       combined_final)
        avg_bh = sum(bh_returns) / len(bh_returns) if bh_returns else 0.0
        print("\n" + "=" * 60)
        print("COMBINED (all symbols, each with its own $50 sleeve)")
        print("=" * 60)
        print_report("ALL SYMBOLS", combined_stats, avg_bh,
                     "mixed")
        print(f"\n  Total starting capital: ${combined_start:.2f}")
        print(f"  Total ending capital:   ${combined_final:.2f}")
    else:
        print("\nNo trades were generated across any symbol.")

    print("\nDone. Review these numbers BEFORE going live.")
    print("Rule of thumb: profit factor >= 1.3 and beating buy-and-hold.")


if __name__ == "__main__":
    main()
