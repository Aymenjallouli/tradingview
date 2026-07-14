"""
mt5_audit.py — the honest scorecard. One question: ARE WE MAKING MONEY?

Everything else in this project (169 strategies, 22 methods, 6 books, the guards)
only matters if the equity curve goes up. This audit measures that, and nothing
else, from the ONLY source of truth: the broker's own closed-deal history.

    python mt5_audit.py            # full audit
    python mt5_audit.py --strats   # per-strategy breakdown (who earns, who bleeds)

It reports, per period:
  * net P&L, win rate, profit factor, expectancy per trade
  * max drawdown and the worst losing streak actually experienced
  * per-strategy and per-market P&L, so losers can be cut
  * VERDICT: is the live edge holding up against what the backtest promised?

Deliberately blunt. A strategy that loses money live is cut, whatever its
backtest said. Backtests are a hypothesis; this file is the evidence.
"""

import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None

# The books, by magic number.
BOOK = {770001: "METALS", 770002: "FOREX", 770003: "INDICES",
        770004: "ENERGY", 770005: "CRYPTO", 770006: "SOFTS"}

# What the walk-forward promised, so we can compare live vs backtest.
BACKTEST_PF = 1.73          # average OOS profit factor across the 169 strategies
BACKTEST_WIN = 0.68         # average OOS win rate

# A strategy is a candidate for the chopping block once it has enough live
# trades to judge AND it's losing money.
MIN_TRADES_TO_JUDGE = int(os.getenv("MT5_AUDIT_MIN_TRADES", "15"))


def _stats(pnls):
    """Core stats from a list of trade P&Ls."""
    if not pnls:
        return None
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (99.0 if wins else 0.0)
    # worst losing streak actually experienced
    streak = worst = 0
    for p in pnls:
        if p <= 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    # max drawdown of the realised equity curve
    eq = peak = 0.0
    maxdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)
    return {
        "n": len(pnls),
        "net": sum(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(pnls),
        "pf": pf,
        "expectancy": sum(pnls) / len(pnls),
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (gross_loss / len(losses)) if losses else 0.0,
        "max_dd": maxdd,
        "worst_streak": worst,
    }


def _fetch_closed(days):
    """Closed trades from the broker, newest last. The only source of truth.

    NOTE: MT5 OVERWRITES the position comment on exit ('close', '[sl 4100.49]'),
    destroying the strategy name at exactly the moment we need it. The ENTRY deal
    still carries it, and position_id links the two — so join on that. Without
    this, every per-strategy number is garbage ("cut METALS/close" means nothing).
    """
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=days), now) or []
    # position_id -> strategy name, from the ENTRY deal
    strat_of = {d.position_id: (d.comment or "?")
                for d in deals if d.entry == 0 and d.magic in BOOK}
    out = []
    for d in deals:
        if d.entry != 1 or d.magic not in BOOK:   # exits from OUR books only
            continue
        exit_comment = d.comment or ""
        out.append({
            "time": datetime.fromtimestamp(d.time, timezone.utc),
            "symbol": d.symbol,
            "profit": d.profit,
            "book": BOOK[d.magic],
            "strategy": strat_of.get(d.position_id, "?"),
            "hit_stop": exit_comment.startswith("[sl"),
            "hit_target": exit_comment.startswith("[tp"),
        })
    out.sort(key=lambda x: x["time"])
    return out


def _bar(v, lo, hi, width=20):
    """A crude progress bar for the scorecard."""
    frac = 0.0 if hi == lo else max(0.0, min(1.0, (v - lo) / (hi - lo)))
    filled = int(frac * width)
    return "█" * filled + "·" * (width - filled)


def audit(days=30, show_strategies=False):
    if mt5 is None or not mt5.initialize():
        print("Cannot reach MT5.")
        return
    acc = mt5.account_info()
    trades = _fetch_closed(days)
    open_pos = [p for p in (mt5.positions_get() or []) if p.magic in BOOK]
    floating = sum(p.profit for p in open_pos)

    print("=" * 68)
    print(f" AUDIT — ARE WE MAKING MONEY?   (last {days} days)")
    print("=" * 68)
    print(f" balance ${acc.balance:,.2f}   equity ${acc.equity:,.2f}   "
          f"floating ${floating:+,.2f} on {len(open_pos)} open")
    print()

    if not trades:
        print(" No closed trades yet. Nothing to judge.")
        print(" >>> The bot must RUN to produce evidence. That is the bottleneck.")
        mt5.shutdown()
        return

    s = _stats([t["profit"] for t in trades])

    # ---- the headline: are we up or down? ----
    verdict = "MAKING MONEY" if s["net"] > 0 else "LOSING MONEY"
    print(f" VERDICT: {verdict}   net ${s['net']:+,.2f} over {s['n']} closed trades")
    print()
    print(f"   win rate   {s['win_rate']*100:5.1f}%   {_bar(s['win_rate'], 0, 1)}"
          f"   (backtest said {BACKTEST_WIN*100:.0f}%)")
    print(f"   profit factor {s['pf']:5.2f}   {_bar(s['pf'], 0, 3)}"
          f"   (backtest said {BACKTEST_PF:.2f})")
    print(f"   expectancy  ${s['expectancy']:+.2f}/trade")
    print(f"   avg win  ${s['avg_win']:.2f}   avg loss ${s['avg_loss']:.2f}")
    print(f"   max drawdown ${s['max_dd']:,.2f}   worst losing streak {s['worst_streak']}")
    print()

    # ---- is the live edge holding vs the backtest? ----
    print(" IS THE BACKTEST EDGE HOLDING UP LIVE?")
    if s["n"] < 30:
        print(f"   UNKNOWN — {s['n']} trades is too few to judge. Need 100+.")
        print("   Do NOT conclude anything yet, in either direction.")
    else:
        decay = (s["pf"] / BACKTEST_PF) if BACKTEST_PF else 0
        if s["pf"] >= 1.3:
            print(f"   HOLDING — live PF {s['pf']:.2f} vs backtest {BACKTEST_PF:.2f} "
                  f"({decay*100:.0f}% retained). Normal decay is 50-70%.")
        elif s["pf"] >= 1.0:
            print(f"   MARGINAL — live PF {s['pf']:.2f}. Breakeven-ish. Watch closely.")
        else:
            print(f"   NOT HOLDING — live PF {s['pf']:.2f} (< 1.0 = losing). "
                  f"The backtest edge is not surviving contact with the market.")
    print()

    # ---- per book ----
    bybook = defaultdict(list)
    for t in trades:
        bybook[t["book"]].append(t["profit"])
    print(" BY BOOK")
    print(f"   {'book':9} {'trades':>7} {'net':>10} {'win%':>6} {'PF':>6}")
    print("   " + "-" * 42)
    for b, pnls in sorted(bybook.items(), key=lambda x: -sum(x[1])):
        st = _stats(pnls)
        print(f"   {b:9} {st['n']:7} ${st['net']:+9.2f} {st['win_rate']*100:5.0f}% "
              f"{st['pf']:6.2f}")
    print()

    # ---- per market: where is the money actually coming from / going? ----
    bysym = defaultdict(list)
    for t in trades:
        bysym[t["symbol"]].append(t["profit"])
    ranked = sorted(bysym.items(), key=lambda x: -sum(x[1]))
    print(" BEST / WORST MARKETS")
    for sym, pnls in ranked[:3]:
        print(f"   + {sym:10} {len(pnls):3} trades  ${sum(pnls):+9.2f}")
    for sym, pnls in ranked[-3:][::-1]:
        if sum(pnls) < 0:
            print(f"   - {sym:10} {len(pnls):3} trades  ${sum(pnls):+9.2f}")
    print()

    # ---- how do trades END? misplaced stops/targets show up here ----
    stops = [t for t in trades if t["hit_stop"]]
    targets = [t for t in trades if t["hit_target"]]
    signal_exits = [t for t in trades if not t["hit_stop"] and not t["hit_target"]]
    print(" HOW TRADES END")
    print(f"   stop-loss hit  {len(stops):3}  ${sum(t['profit'] for t in stops):+9.2f}")
    print(f"   target hit     {len(targets):3}  ${sum(t['profit'] for t in targets):+9.2f}")
    print(f"   strategy exit  {len(signal_exits):3}  "
          f"${sum(t['profit'] for t in signal_exits):+9.2f}")
    if stops and s["avg_loss"] > 3 * s["avg_win"]:
        print("   !! avg loss is >3x avg win — stops may be too wide, or targets"
              " too tight/unreachable.")
    print()

    # ---- the improvement lever: who should be CUT? ----
    bystrat = defaultdict(list)
    for t in trades:
        bystrat[f"{t['book']}/{t['strategy']}"].append(t["profit"])

    if show_strategies:
        print(" EVERY STRATEGY (live)")
        print(f"   {'strategy':28} {'n':>4} {'net':>10} {'PF':>6}")
        print("   " + "-" * 52)
        for k, pnls in sorted(bystrat.items(), key=lambda x: -sum(x[1])):
            st = _stats(pnls)
            print(f"   {k:28} {st['n']:4} ${st['net']:+9.2f} {st['pf']:6.2f}")
        print()

    cut = [(k, _stats(p)) for k, p in bystrat.items()
           if len(p) >= MIN_TRADES_TO_JUDGE and sum(p) < 0]
    print(" >>> IMPROVEMENT LEVER: STRATEGIES TO CUT")
    if cut:
        print(f"   These have {MIN_TRADES_TO_JUDGE}+ live trades AND lose money.")
        print("   A backtest is a hypothesis; this is the evidence. Cut them.")
        for k, st in sorted(cut, key=lambda x: x[1]["net"]):
            print(f"     {k:28} {st['n']:3} trades  ${st['net']:+8.2f}  "
                  f"PF {st['pf']:.2f}")
    else:
        judged = sum(1 for p in bystrat.values() if len(p) >= MIN_TRADES_TO_JUDGE)
        print(f"   None yet — only {judged} strategies have {MIN_TRADES_TO_JUDGE}+ "
              f"live trades.")
        print("   You cannot cut what you haven't measured. RUN THE BOT LONGER.")
    print()
    print("=" * 68)
    mt5.shutdown()


if __name__ == "__main__":
    audit(days=int(os.getenv("MT5_AUDIT_DAYS", "30")),
          show_strategies="--strats" in sys.argv)
