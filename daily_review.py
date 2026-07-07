"""
daily_review.py — Module 5: daily AI review using your Claude subscription.

This gathers the last 7 days of trades, your current open positions, and your
equity curve into a plain-text summary, then asks Claude (via the `claude` CLI
that ships with your Claude Code subscription) to analyse:
    * what's working
    * what's failing
    * ONE suggested adjustment

The response is saved to reports/YYYY-MM-DD.md.

SAFETY: This script is READ-ONLY with respect to your strategy. It NEVER edits
config.py or any strategy code. Claude's suggestions are for YOU to read and
decide on — nothing is applied automatically.

Run it:
    python daily_review.py

Requirements:
    * The `claude` command must be on your PATH (it is, if you use Claude Code).
    * You must be logged in to Claude Code (run `claude` once interactively if
      you've never signed in).
"""

import os
import subprocess
from datetime import datetime, timedelta, timezone

import config
import data_feed
from paper_broker import PaperBroker


def build_summary(broker: PaperBroker) -> str:
    """Assemble the text summary we hand to Claude."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    since_iso = since.isoformat()

    lines = []
    lines.append("PAPER TRADING — 7-DAY PERFORMANCE SUMMARY")
    lines.append(f"Generated (UTC): {now.isoformat()}")
    lines.append(f"Starting capital: ${config.STARTING_CAPITAL:.2f}")
    lines.append("")

    # --- Account snapshot ---------------------------------------------------
    # Value open positions at current market prices for an honest equity number.
    prices = {}
    for pos in broker.open_positions():
        df = data_feed.get_candles(pos["symbol"], interval=config.TIMEFRAME,
                                   period="5d")
        if not df.empty:
            prices[pos["symbol"]] = float(df["Close"].dropna().iloc[-1])

    cash = broker.get_cash()
    equity = broker.get_equity(prices)
    lines.append("ACCOUNT SNAPSHOT")
    lines.append(f"  Cash: ${cash:.2f}")
    lines.append(f"  Equity (cash + open positions): ${equity:.2f}")
    lines.append(f"  Total return: "
                 f"{(equity / config.STARTING_CAPITAL - 1) * 100:+.2f}%")
    lines.append("")

    # --- Open positions -----------------------------------------------------
    lines.append("OPEN POSITIONS")
    open_positions = broker.open_positions()
    if not open_positions:
        lines.append("  (none)")
    else:
        for pos in open_positions:
            symbol = pos["symbol"]
            cur_price = prices.get(symbol, pos["fill_price"])
            unreal = (cur_price - pos["fill_price"]) * pos["qty"]
            lines.append(
                f"  {symbol}: qty={pos['qty']:.6f} "
                f"entry={pos['entry_price']:.4f} "
                f"now={cur_price:.4f} "
                f"unrealized=${unreal:+.4f} "
                f"(opened {pos['entry_time']})"
            )
    lines.append("")

    # --- Trades in the last 7 days -----------------------------------------
    recent = broker.recent_trades(since_iso)
    lines.append(f"TRADES IN LAST 7 DAYS ({len(recent)})")
    if not recent:
        lines.append("  (no closed trades in this window)")
    else:
        for t in recent:
            lines.append(
                f"  {t['symbol']}: {t['exit_reason']:<11} "
                f"P&L=${t['pnl']:+.4f} ({t['return_pct']*100:+.2f}%) "
                f"entry={t['entry_price']:.4f} exit={t['exit_price']:.4f} "
                f"[{t['entry_time']} -> {t['exit_time']}]"
            )
    lines.append("")

    # --- All-time stats + equity curve -------------------------------------
    all_trades = broker.all_trades()
    lines.append(f"ALL-TIME STATS ({len(all_trades)} closed trades)")
    if all_trades:
        wins = [t for t in all_trades if t["pnl"] > 0]
        gross_win = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in all_trades if t["pnl"] <= 0))
        pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
        win_rate = len(wins) / len(all_trades) * 100
        lines.append(f"  Win rate: {win_rate:.1f}%")
        lines.append(f"  Profit factor: "
                     f"{'inf' if pf == float('inf') else f'{pf:.2f}'}")

        # Equity curve = starting capital + cumulative realized P&L per trade.
        lines.append("  Equity curve (realized, per closed trade):")
        running = config.STARTING_CAPITAL
        curve_points = [f"{running:.2f}"]
        for t in all_trades:
            running += t["pnl"]
            curve_points.append(f"{running:.2f}")
        lines.append("    " + " -> ".join(curve_points))
    else:
        lines.append("  (no closed trades yet)")
    lines.append("")

    # --- The strategy description (context for Claude) ---------------------
    lines.append("STRATEGY IN USE")
    lines.append("  Long-only trend following on 4h candles.")
    lines.append(f"  Entry: {config.EMA_FAST} EMA crosses above "
                 f"{config.EMA_SLOW} EMA, price above {config.EMA_TREND} EMA, "
                 f"RSI({config.RSI_PERIOD}) < {config.RSI_MAX_ENTRY}.")
    lines.append(f"  Exit: {config.EMA_FAST}/{config.EMA_SLOW} EMA cross down, "
                 f"OR -{config.STOP_LOSS_PCT*100:.0f}% stop, "
                 f"OR +{config.TAKE_PROFIT_PCT*100:.0f}% target.")
    lines.append(f"  Costs modeled: {config.FEE_PCT*100:.1f}% fee/side, "
                 f"{config.SLIPPAGE_PCT*100:.2f}% slippage.")

    return "\n".join(lines)


def build_prompt(summary: str) -> str:
    """Wrap the summary in a clear ask for Claude."""
    return (
        "You are reviewing the performance of a beginner's paper-trading "
        "system. Below is a summary of the last 7 days of trades, current "
        "open positions, and the equity curve.\n\n"
        "Please give a concise review with exactly these three sections:\n"
        "1. WHAT'S WORKING — patterns in the winning trades.\n"
        "2. WHAT'S FAILING — patterns in the losing trades or weak spots.\n"
        "3. ONE SUGGESTED ADJUSTMENT — a single, specific change to consider "
        "(do NOT suggest multiple changes; pick the one with the best "
        "risk/reward). Explain the reasoning in 2-3 sentences.\n\n"
        "Keep it practical and beginner-friendly. Do not rewrite the whole "
        "strategy.\n\n"
        "=== PERFORMANCE SUMMARY ===\n"
        f"{summary}\n"
    )


def call_claude(prompt: str) -> str:
    """Call the `claude` CLI in one-shot mode and return its text response.

    Uses `claude -p "<prompt>"`. Requires you to be logged in to Claude Code.
    """
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=180,
            shell=False,
        )
    except FileNotFoundError:
        return ("ERROR: the `claude` command was not found on your PATH.\n"
                "Install Claude Code and sign in, then re-run this script.")
    except subprocess.TimeoutExpired:
        return "ERROR: the `claude` command timed out after 180 seconds."

    if result.returncode != 0:
        return (f"ERROR: `claude` exited with code {result.returncode}.\n"
                f"stderr:\n{result.stderr}")

    return result.stdout.strip()


def main():
    broker = PaperBroker()

    print("Gathering the last 7 days of activity ...")
    summary = build_summary(broker)
    broker.close()

    print("Asking Claude for a review ...")
    prompt = build_prompt(summary)
    review = call_claude(prompt)

    # Make sure the reports directory exists.
    os.makedirs(config.REPORTS_DIR, exist_ok=True)

    # File name uses today's date. new datetime() with tz is allowed.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = os.path.join(config.REPORTS_DIR, f"{today}.md")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Daily AI Review — {today}\n\n")
        f.write("> Suggestions below are for YOUR review only. Nothing was "
                "applied automatically to the strategy.\n\n")
        f.write("## Claude's analysis\n\n")
        f.write(review + "\n\n")
        f.write("---\n\n")
        f.write("## Raw data given to Claude\n\n")
        f.write("```\n" + summary + "\n```\n")

    print(f"\nSaved review to {out_path}")
    print("\n" + "=" * 60)
    print(review)
    print("=" * 60)


if __name__ == "__main__":
    main()
