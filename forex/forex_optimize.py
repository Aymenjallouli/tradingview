"""
forex_optimize.py — Sweep parameters for BOTH forex strategies.

Reuses the real strategy + backtest engine (no new logic). Downloads each
pair's candles ONCE, then tests many parameter sets by temporarily overriding
the config the strategy reads. Ranks by a robustness-aware score (median
per-pair profit factor + how many pairs are profitable), NOT the single best
number — so we don't overfit to one lucky pair or window.

Honesty note: yfinance only serves ~5-7 days of 1m forex data, so the scalp
sweep runs on a SMALL sample. Treat scalp results as directional, not proof.
The swing sweep has ~30 days of 5m data (more robust).

Run it:
    python forex_optimize.py            # both
    python forex_optimize.py scalp
    python forex_optimize.py swing
"""

import itertools
import statistics
import sys

import forex_config as cfg
import forex_feed as feed
import forex_strategy as fx
from forex_backtest import backtest, stats


# Parameter grids per strategy.
SCALP_GRID = {
    "bb_std": [1.5, 2.0, 2.5],
    "rsi_entry_max": [20, 25, 30],
    "stop_loss_pct": [0.0010, 0.0015, 0.0025],
    "max_hold_minutes": [15, 30, 60],
}
SWING_GRID = {
    "ema_fast": [10, 20],
    "ema_slow": [50, 100],
    "rsi_entry_max": [65, 70, 75],
    "stop_loss_pct": [0.004, 0.006, 0.010],
    "take_profit_pct": [0.010, 0.015, 0.025],
}

MIN_TRADES_TOTAL = 20
MIN_TRADES_PAIR = 3


def _candles_for(name):
    params = cfg.SCALP if name == "scalp" else cfg.SWING
    out = {}
    for pair in cfg.PAIRS:
        df = feed.get_candles(pair, params["interval"], params["period"])
        if not df.empty and len(df) >= 210:
            out[pair] = df
    return out


def _apply(name, combo):
    """Write a parameter combo into the config dict the strategy reads."""
    target = cfg.SCALP if name == "scalp" else cfg.SWING
    for k, v in combo.items():
        target[k] = v


def _combos(grid):
    keys = list(grid.keys())
    for values in itertools.product(*(grid[k] for k in keys)):
        yield dict(zip(keys, values))


def _score(per_pair_pf, pairs_profitable):
    finite = [min(p, 10.0) if p != float("inf") else 10.0 for p in per_pair_pf]
    if not finite:
        return -1.0
    return statistics.median(finite) + 0.2 * pairs_profitable


def run(name):
    grid = SCALP_GRID if name == "scalp" else SWING_GRID
    combos = list(_combos(grid))
    print("\n" + "=" * 60)
    print(f"OPTIMIZING {name.upper()} — {len(combos)} combos")
    print("=" * 60)

    candles = _candles_for(name)
    if not candles:
        print("  No data available; skipping.")
        return None
    print(f"  Data: {', '.join(f'{p}={len(d)}' for p, d in candles.items())}")

    # Save originals to restore later.
    target = cfg.SCALP if name == "scalp" else cfg.SWING
    original = dict(target)

    results = []
    for combo in combos:
        _apply(name, combo)
        strat = fx.get_strategy(name)
        per_pair_pf = []
        pairs_profitable = 0
        total_trades = 0
        combined_net = 0.0
        for pair, df in candles.items():
            trades, final = backtest(pair, df, strat, costs_on=True)
            s = stats(trades, cfg.STARTING_CAPITAL, final)
            total_trades += s["trades"]
            combined_net += s["net"]
            if s["trades"] >= MIN_TRADES_PAIR:
                per_pair_pf.append(s["pf"])
                if s["net"] > 0:
                    pairs_profitable += 1
        if total_trades >= MIN_TRADES_TOTAL and per_pair_pf:
            results.append({
                "combo": combo,
                "score": _score(per_pair_pf, pairs_profitable),
                "median_pf": statistics.median(
                    [min(p, 10.0) if p != float("inf") else 10.0
                     for p in per_pair_pf]),
                "pairs_profitable": pairs_profitable,
                "trades": total_trades,
                "net": combined_net,
            })

    # Restore original config.
    target.clear()
    target.update(original)

    if not results:
        print("  No combo met the minimum-trades bar.")
        return None

    results.sort(key=lambda r: r["score"], reverse=True)
    print(f"\n  TOP 5 of {len(results)} valid combos:")
    for i, r in enumerate(results[:5], 1):
        print(f"  #{i} score={r['score']:.2f}  median PF={r['median_pf']:.2f}  "
              f"pairs+={r['pairs_profitable']}  net=${r['net']:+.3f}  "
              f"trades={r['trades']}")
        print(f"      {r['combo']}")

    best = results[0]
    print(f"\n  BEST {name.upper()} combo:")
    for k, v in best["combo"].items():
        print(f"    {k} = {v}")
    profitable = best["median_pf"] > 1.0 and best["net"] > 0
    print(f"  Median profit factor {best['median_pf']:.2f} — "
          f"{'profitable-ish' if profitable else 'still not profitable'} "
          f"on this data window.")
    return best


def main():
    which = sys.argv[1].lower() if len(sys.argv) > 1 else "both"
    print("=" * 60)
    print("FOREX OPTIMIZER — robustness-ranked, honest costs")
    print("=" * 60)
    if which in ("scalp", "both"):
        run("scalp")
    if which in ("swing", "both"):
        run("swing")
    print("\n(Config files were NOT modified. Copy winning values yourself.)")


if __name__ == "__main__":
    main()
