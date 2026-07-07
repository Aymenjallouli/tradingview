"""
check_signals.py — Module 1: the live signal engine (FREE mode, the default).

Run this every 4 hours (manually, or via cron / Windows Task Scheduler). It:
  1. Downloads fresh 4h candles for every symbol from yfinance.
  2. Computes indicators using the SHARED strategy module (strategy.py) — the
     exact same logic the backtester uses.
  3. Checks the most recent CLOSED candle for entry/exit signals.
  4. Sends any signals to the paper broker (paper_broker.py).

Run it:
    python check_signals.py

Why the "most recent CLOSED candle"? The last row yfinance returns is often a
still-forming candle. Acting on a candle that hasn't closed yet is a classic
beginner mistake (the signal can vanish before the candle finishes). So we act
on the second-to-last row, which is fully closed.
"""

import config
import data_feed
import strategy
from paper_broker import PaperBroker


def latest_closed_index(df) -> int:
    """Return the index of the most recent CLOSED candle.

    yfinance's final row is usually the current, still-forming candle, so we
    step back one bar to be safe. Returns -1 if there isn't enough data.
    """
    if len(df) < 2:
        return -1
    return len(df) - 2  # second to last = last fully closed candle


def check_symbol(symbol: str, broker: PaperBroker):
    """Check one symbol for an entry or exit signal and act on it."""
    print(f"\nChecking {symbol} ...")

    # Pull a long window so the 200 EMA has enough history to warm up for
    # every symbol (stocks included). data_feed defaults to ~730 days of
    # candles at config.TIMEFRAME, which is far more than 200 bars.
    df = data_feed.get_candles(symbol)
    if df.empty or len(df) < config.EMA_TREND:
        print(f"  Not enough data for {symbol}; skipping.")
        return

    df = strategy.add_indicators(df)
    i = latest_closed_index(df)
    if i < 1:
        print(f"  Not enough closed candles for {symbol}; skipping.")
        return

    price = float(df.iloc[i]["Close"])
    time_label = df.index[i]
    print(f"  Latest closed candle: {time_label}  close={price:.4f}")

    holding = broker.has_position(symbol)

    if holding:
        # We're in a trade — check the exit rules (stop / target / EMA cross).
        pos = broker.get_position(symbol)
        entry_price = pos["entry_price"]
        reason = strategy.check_exit(entry_price, price, df, i)
        if reason is not None:
            print(f"  EXIT signal ({reason}).")
            broker.sell(symbol, price, reason=reason)
        else:
            print("  Holding — no exit signal.")
    else:
        # Flat — check for an entry signal.
        if strategy.entry_signal(df, i):
            print("  ENTRY signal (20/50 cross, above 200 EMA, RSI<70).")
            broker.buy(symbol, price)
        else:
            print("  No entry signal.")


def main():
    print("=" * 60)
    print("SIGNAL CHECK — free mode (yfinance)")
    print("Run this every 4 hours.")
    print("=" * 60)

    broker = PaperBroker()
    print(f"Starting cash: ${broker.get_cash():.2f} | "
          f"Open positions: {len(broker.open_positions())} | "
          f"Equity: ${broker.get_equity():.2f}")

    for symbol in config.SYMBOLS:
        try:
            check_symbol(symbol, broker)
        except Exception as exc:  # noqa: BLE001 - keep going if one symbol fails
            print(f"  Error checking {symbol}: {exc}")

    print(f"\nDone. Cash: ${broker.get_cash():.2f} | "
          f"Open positions: {len(broker.open_positions())} | "
          f"Equity: ${broker.get_equity():.2f}")
    broker.close()


if __name__ == "__main__":
    main()
