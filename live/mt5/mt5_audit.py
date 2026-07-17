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

# Score only trades at/after this date (YYYY-MM-DD). See the ERA FILTER note in
# audit(): recycled magic numbers mean an unscoped window merges deleted code
# with the live books. The VPS books settled on 2026-07-12.
AUDIT_SINCE = os.getenv("MT5_AUDIT_SINCE", "").strip()

# A "fresh start" marker (written when we reset to a simulated $2k account) lets
# the audit score from that moment on a $2k base, ignoring the real demo balance
# and all trades before the reset.
FRESH_PATH = os.path.join(os.path.dirname(__file__), "fresh_start.json")


def _load_fresh():
    try:
        import json
        with open(FRESH_PATH) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def _stats(pnls):
    """Core stats from a list of trade P&Ls."""
    if not pnls:
        return None
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    # Breakeven (exactly 0) is neither. Bucketing it as a loss deflated the win
    # rate and padded worst_streak — and now that costs are netted in, an exact
    # 0 is rare enough that mislabelling it is pure noise in the verdict.
    scratches = [p for p in pnls if p == 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (99.0 if wins else 0.0)
    # worst losing streak actually experienced (a scratch is not a loss)
    streak = worst = 0
    for p in pnls:
        if p < 0:
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
    decided = len(wins) + len(losses)
    return {
        "n": len(pnls),
        "net": sum(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(scratches),
        # Win rate is over DECIDED trades. Scratches in the denominator would
        # drag it toward 0 and make it uncomparable with BACKTEST_WIN.
        "win_rate": (len(wins) / decided) if decided else 0.0,
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
    # position_id -> total cost. `d.profit` is GROSS: MT5 books commission,
    # swap and fee as SEPARATE fields, and commission usually lands on the ENTRY
    # deal — the one the exit-only loop below throws away. Summing both legs by
    # position_id is the only way to get the number that actually hit the
    # balance. This matters more here than almost anywhere: the whole edge was
    # measured at +0.026R AFTER honest costs, and most trades exit on a signal
    # for ~$1, so costs are exactly the scale that decides the sign. Reporting
    # gross would flatter every verdict this file exists to give.
    cost_of = defaultdict(float)
    for d in deals:
        if d.magic not in BOOK:
            continue
        cost_of[d.position_id] += ((getattr(d, "commission", 0.0) or 0.0)
                                   + (getattr(d, "swap", 0.0) or 0.0)
                                   + (getattr(d, "fee", 0.0) or 0.0))
    out = []
    for d in deals:
        if d.entry != 1 or d.magic not in BOOK:   # exits from OUR books only
            continue
        exit_comment = d.comment or ""
        cost = cost_of.get(d.position_id, 0.0)
        out.append({
            "time": datetime.fromtimestamp(d.time, timezone.utc),
            "symbol": d.symbol,
            "profit": d.profit + cost,        # NET — what hit the balance
            "gross": d.profit,                # before costs, for the drag line
            "cost": cost,                     # negative when we paid
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

    # If we've reset to a simulated $2k account, score only from that moment
    # and against the $2k base — the real demo balance is irrelevant to the sim.
    fresh = _load_fresh()
    since = None
    if fresh:
        since = datetime.fromtimestamp(fresh["ts"], timezone.utc)
        trades = [t for t in trades if t["time"] >= since]

    # ERA FILTER. Magic numbers were RECYCLED: 770001 is both mt5_orders' default
    # (so any process without MT5_BOOK stamped it) and, later, v_metals — so
    # BOOK[770001]="METALS" silently merges trades made by DELETED code with
    # today's book. Grading across that boundary cuts clean books to punish
    # ghosts. MT5_AUDIT_SINCE=YYYY-MM-DD scopes the audit to one code era.
    if not fresh and AUDIT_SINCE:
        try:
            since = datetime.fromisoformat(AUDIT_SINCE).replace(tzinfo=timezone.utc)
            trades = [t for t in trades if t["time"] >= since]
        except ValueError:
            print(f" !! MT5_AUDIT_SINCE={AUDIT_SINCE!r} is not YYYY-MM-DD — ignored")
            since = None

    print("=" * 68)
    print(f" AUDIT — ARE WE MAKING MONEY?   (last {days} days)")
    print("=" * 68)
    if fresh:
        vstart = fresh["virtual_start"]
        vbal = vstart + sum(t["profit"] for t in trades)
        print(f" SIMULATED ${vstart:,.0f} ACCOUNT  (fresh start {since:%Y-%m-%d %H:%M} UTC)")
        print(f" virtual balance ${vbal:,.2f}   +floating ${floating:+,.2f} "
              f"= equity ${vbal + floating:,.2f}   on {len(open_pos)} open")
        print(f" (real demo balance ${acc.balance:,.2f} is ignored by the sim)")
    else:
        print(f" balance ${acc.balance:,.2f}   equity ${acc.equity:,.2f}   "
              f"floating ${floating:+,.2f} on {len(open_pos)} open")
    # Say which era is being scored, and warn when it's ALL of them. Without
    # this the reader divides an old loss by today's balance and invents a risk
    # breach that never happened — the balance has been 100k, then $1k, then
    # $6.6k inside a single 30-day window.
    if since:
        print(f" scoring trades from {since:%Y-%m-%d} onward "
              f"({len(trades)} in this era)")
    else:
        print(" !! NO ERA FILTER — this window may merge deleted code with the")
        print("    live books (magic 770001 was the old default AND is now")
        print("    v_metals). Balance has changed by orders of magnitude across")
        print("    it, so a $ loss here is NOT a % of today's balance.")
        print("    Scope it:  MT5_AUDIT_SINCE=2026-07-12")
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
    # What costs actually took. Everything above is NET of these; this line
    # exists so the drag is visible rather than assumed away. If gross is
    # positive and net is negative, the edge is real but the costs eat it —
    # a completely different problem from "the edge is dead".
    gross = sum(t.get("gross", t["profit"]) for t in trades)
    costs = sum(t.get("cost", 0.0) for t in trades)
    if costs:
        print(f"   gross ${gross:+,.2f}   costs ${costs:+,.2f} "
              f"(commission+swap+fee)   NET ${s['net']:+,.2f}")
        print(f"   cost drag ${abs(costs)/s['n']:.2f}/trade")
    else:
        print("   costs $0.00 — broker reports no commission/swap/fee "
              "(spread-only account)")
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
    # Split the ranking so a market can never print as BOTH best and worst (with
    # <6 symbols the old ranked[:3] / ranked[-3:] slices overlapped), and only
    # call a market "best" if it actually MADE money — in an all-losing period
    # the three smallest losers were being listed under "+".
    winners = [(s, p) for s, p in ranked if sum(p) > 0]
    losers = [(s, p) for s, p in ranked if sum(p) < 0]
    if not winners:
        print("   (no market made money in this window)")
    for sym, pnls in winners[:3]:
        print(f"   + {sym:10} {len(pnls):3} trades  ${sum(pnls):+9.2f}")
    for sym, pnls in losers[-3:][::-1]:
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
