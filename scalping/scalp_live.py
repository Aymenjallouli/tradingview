"""
scalp_live.py — Module B: the live paper scalper.

Polls Binance 1-minute klines every 60 seconds, applies the SAME strategy
module the backtester uses (scalp_strategy.py), and records simulated fills to
the scalp SQLite ledger (scalp_ledger.py — separate scalp_* tables).

Console output shows every signal, fill, and the running equity.

AUTO-STOP: if virtual equity drops 25% below the $50 start, it halts and prints
a summary. (The Module A backtest suggests this WILL happen — that's the whole
point of the experiment.)

Run it:
    python scalp_live.py

Stop it any time with Ctrl+C. Progress is saved in the ledger, so you can
resume by running it again, and the verdict report reads the same ledger.

Execution realism: a signal detected on the latest CLOSED candle is filled at
the CURRENT (forming) candle's price on the next poll — the nearest live
equivalent of "next candle open", never the signal candle's close.
"""

import time
from datetime import datetime, timezone

import pandas as pd

import scalp_config as cfg
import scalp_strategy as strat
import binance_feed
from scalp_ledger import ScalpLedger


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def poll_once(ledger: ScalpLedger) -> bool:
    """Run one polling cycle across all symbols.

    Returns True to keep running, False if the auto-halt fired.
    """
    # Value open positions at the latest price for an honest equity read.
    prices = {}

    for symbol in cfg.SYMBOLS:
        try:
            df = binance_feed.get_latest_closed(symbol, interval=cfg.INTERVAL,
                                                limit=100)
        except Exception as exc:  # noqa: BLE001
            log(f"{symbol}: fetch error: {exc}")
            continue
        if df.empty or len(df) < cfg.BB_PERIOD + 2:
            continue

        df = strat.add_indicators(df)
        last = len(df) - 1               # latest CLOSED candle index
        price = float(df.iloc[last]["close"])
        prices[symbol] = price

        if ledger.has_position(symbol):
            # Work out how long we've held (in minutes = candles).
            pos = ledger.get_position(symbol)
            entry_ms = pos["entry_bar_ms"]
            now_ms = int(df.index[last].timestamp() * 1000)
            minutes_held = max(0, int((now_ms - entry_ms) / 60_000))

            reason = strat.check_exit(pos["entry_fill"], df, last, minutes_held)
            if reason is not None:
                result = ledger.sell(symbol, price, reason, minutes_held)
                log(f"{symbol}: EXIT {reason} @ {price:.4f} "
                    f"P&L ${result['pnl']:+.4f} ({result['return_pct']*100:+.2f}%) "
                    f"held {minutes_held}m")
        else:
            if strat.entry_signal(df, last):
                entry_ms = int(df.index[last].timestamp() * 1000)
                # Fill at the current price on this poll (nearest live analogue
                # of the next-candle-open rule the backtester uses).
                opened = ledger.buy(symbol, price, entry_ms)
                if opened:
                    log(f"{symbol}: ENTRY signal (close<lowerBB, RSI<25) "
                        f"filled ~{price:.4f}")

    # Equity + auto-halt check.
    equity = ledger.get_equity(prices)
    start = cfg.STARTING_CAPITAL
    dd = (start - equity) / start
    log(f"Equity ${equity:.2f}  (start ${start:.2f}, "
        f"drawdown {dd*100:.1f}%)  open positions: "
        f"{len(ledger.open_positions())}")

    if dd >= cfg.HALT_DRAWDOWN_PCT:
        log(f"AUTO-HALT: drawdown {dd*100:.1f}% >= "
            f"{cfg.HALT_DRAWDOWN_PCT*100:.0f}%. Experiment over.")
        return False
    return True


def print_summary(ledger: ScalpLedger):
    trades = ledger.all_trades()
    print("\n" + "=" * 55)
    print("SCALP LIVE SESSION SUMMARY")
    print("=" * 55)
    print(f"  Closed trades: {len(trades)}")
    if trades:
        wins = [t for t in trades if t["pnl"] > 0]
        total_pnl = sum(t["pnl"] for t in trades)
        total_fees = sum(t["fees_paid"] for t in trades)
        print(f"  Win rate: {len(wins)/len(trades)*100:.1f}%")
        print(f"  Net P&L: ${total_pnl:+.2f}")
        print(f"  Total fees paid: ${total_fees:.2f}")
    print(f"  Final cash: ${ledger.get_cash():.2f}")
    print(f"  Final equity: ${ledger.get_equity():.2f}")
    print("\nRun `python scalp_report.py` for the full verdict + equity PNG.")


def main():
    print("=" * 55)
    print("LIVE PAPER SCALPER (Module B)")
    print(f"Polling {', '.join(cfg.SYMBOLS)} every {cfg.POLL_SECONDS}s")
    print(f"Auto-halt at -{cfg.HALT_DRAWDOWN_PCT*100:.0f}% drawdown")
    print("Press Ctrl+C to stop. Progress is saved in the ledger.")
    print("=" * 55)

    ledger = ScalpLedger()
    log(f"Starting equity: ${ledger.get_equity():.2f}")

    try:
        running = True
        while running:
            running = poll_once(ledger)
            if running:
                time.sleep(cfg.POLL_SECONDS)
    except KeyboardInterrupt:
        log("Stopped by user (Ctrl+C).")
    finally:
        print_summary(ledger)
        ledger.close()


if __name__ == "__main__":
    main()
