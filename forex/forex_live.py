"""
forex_live.py — Live paper trader for the forex experiment.

Polls yfinance forex candles every 60 seconds, applies the SAME strategy module
the backtester uses (forex_strategy.py), and records simulated fills to the
forex ledger (fx_* tables) with the realistic spread cost model.

You pick which strategy to run:
    python forex_live.py scalp     # 1-minute mean-reversion
    python forex_live.py swing     # 5-minute trend pullback  (default)

Why forward-testing matters here: yfinance only serves ~5 days of 1m history,
so the backtest sample is tiny and was a flat week. Running this live for days/
weeks accumulates YOUR OWN out-of-sample data — the honest way to find out if
the edge is real. It's paper money, so there's no risk in letting it run.

Console shows each signal, fill, and running equity. Auto-halts at -25%.
Stop any time with Ctrl+C — progress is saved. Ctrl+C then rerun to resume.
"""

import sys
import time
from datetime import datetime, timezone

import pandas as pd

import forex_config as cfg
import forex_feed as feed
import forex_strategy as fx
from forex_ledger import ForexLedger


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def poll_once(ledger, strat, params):
    prices = {}
    for pair in cfg.PAIRS:
        try:
            df = feed.get_candles(pair, params["interval"], params["period"])
        except Exception as exc:  # noqa: BLE001
            log(f"{pair}: fetch error: {exc}")
            continue
        if df.empty or len(df) < 210:
            continue
        # Drop the still-forming last candle; act on the last CLOSED one.
        df = df.iloc[:-1]
        df = strat.add_indicators(df)
        last = len(df) - 1
        price = float(df.iloc[last]["close"])
        prices[pair] = price

        if ledger.has_position(pair):
            pos = ledger.get_position(pair)
            entry_ms = pos["entry_bar_ms"]
            now_ms = int(df.index[last].timestamp() * 1000)
            # minutes per bar depends on the interval (1m or 5m).
            per_bar = 1 if params["interval"] == "1m" else 5
            minutes_held = max(0, int((now_ms - entry_ms) / 60_000))
            bars_held = minutes_held // per_bar
            reason = strat.check_exit(pos["entry_fill"], df, last, bars_held)
            if reason:
                r = ledger.sell(pair, price, reason, minutes_held)
                log(f"{pair}: EXIT {reason} @ {price:.5f} "
                    f"P&L ${r['pnl']:+.4f} ({r['return_pct']*100:+.3f}%) "
                    f"held {minutes_held}m")
        else:
            if strat.entry_signal(df, last):
                entry_ms = int(df.index[last].timestamp() * 1000)
                if ledger.buy(pair, price, strat.name, entry_ms):
                    log(f"{pair}: ENTRY ({strat.name}) filled ~{price:.5f}")

    equity = ledger.get_equity(prices)
    dd = (cfg.STARTING_CAPITAL - equity) / cfg.STARTING_CAPITAL
    log(f"Equity ${equity:.2f}  drawdown {dd*100:.1f}%  "
        f"open {len(ledger.open_positions())}")
    if dd >= cfg.HALT_DRAWDOWN_PCT:
        log(f"AUTO-HALT: drawdown {dd*100:.1f}% >= "
            f"{cfg.HALT_DRAWDOWN_PCT*100:.0f}%. Stopping.")
        return False
    return True


def summary(ledger):
    trades = ledger.all_trades()
    print("\n" + "=" * 50)
    print("FOREX LIVE SESSION SUMMARY")
    print("=" * 50)
    print(f"  Closed trades: {len(trades)}")
    if trades:
        wins = [t for t in trades if t["pnl"] > 0]
        print(f"  Win rate: {len(wins)/len(trades)*100:.1f}%")
        print(f"  Net P&L: ${sum(t['pnl'] for t in trades):+.2f}")
        print(f"  Total cost paid: ${sum(t['cost_paid'] for t in trades):.4f}")
    print(f"  Final equity: ${ledger.get_equity():.2f}")
    print("\nRun `python forex_report.py` for the full verdict + PNG.")


def main():
    name = sys.argv[1].lower() if len(sys.argv) > 1 else "swing"
    if name not in fx.STRATEGIES:
        print(f"Unknown strategy '{name}'. Use: scalp | swing")
        return
    params = cfg.SCALP if name == "scalp" else cfg.SWING
    strat = fx.get_strategy(name)

    print("=" * 50)
    print(f"FOREX LIVE PAPER TRADER — {name.upper()}")
    print(f"Pairs: {', '.join(cfg.PAIRS)}  ({params['interval']} candles)")
    print(f"Poll every {cfg.POLL_SECONDS}s, auto-halt at "
          f"-{cfg.HALT_DRAWDOWN_PCT*100:.0f}%. Ctrl+C to stop.")
    print("=" * 50)

    ledger = ForexLedger()
    log(f"Starting equity: ${ledger.get_equity():.2f}")
    try:
        while poll_once(ledger, strat, params):
            time.sleep(cfg.POLL_SECONDS)
    except KeyboardInterrupt:
        log("Stopped by user (Ctrl+C).")
    finally:
        summary(ledger)
        ledger.close()


if __name__ == "__main__":
    main()
