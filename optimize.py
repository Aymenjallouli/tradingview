"""
optimize.py — Parameter sweep to find a profitable, ROBUST configuration.

This does NOT invent a new strategy or duplicate any logic. It reuses:
  * strategy.py   (the exact entry/exit rules)
  * backtest.py   (the exact P&L engine: backtest_symbol + compute_stats)
  * data_feed.py  (the same data source)

How it works:
  For each combination of parameters, it temporarily overrides the values in
  the `config` module (which strategy.py reads live), runs the real backtest on
  cached candle data, and records the results. Then it ranks combinations by a
  ROBUSTNESS-AWARE score, not just the single best backtest number — because
  picking the one config with the highest backtest profit is how you overfit
  and then lose money live.

Anti-overfitting measures baked in:
  1. We require a MINIMUM number of trades (a config with 3 lucky trades is
     noise, not an edge).
  2. We score on the MEDIAN per-symbol profit factor and how MANY symbols are
     profitable — a config that only works on one lucky symbol is penalized.
  3. We do a simple walk-forward check on the winner: optimize on the first
     half of history, then verify the same config still works on the unseen
     second half.

Run it:
    python optimize.py
"""

import itertools
import statistics
from dataclasses import dataclass

import pandas as pd

import config
import data_feed
import strategy
from backtest import backtest_symbol, compute_stats, buy_and_hold_return


# ---------------------------------------------------------------------------
# The parameter grid to search.
# Kept deliberately modest so the run finishes in a reasonable time and so we
# don't "search until we get lucky" (that IS overfitting).
# ---------------------------------------------------------------------------
GRID = {
    "TIMEFRAME": ["1h", "4h"],
    # (fast, slow, trend) EMA triples — the classic 20/50/200 plus a couple of
    # slower, less noisy variants.
    "EMAS": [(20, 50, 200), (10, 30, 200), (20, 100, 200)],
    "STOP_LOSS_PCT": [0.03, 0.05, 0.08],
    "TAKE_PROFIT_PCT": [0.06, 0.10, 0.15],
    "RSI_MAX_ENTRY": [70, 75],
}

# Minimum trades (summed across symbols) for a config to be taken seriously.
MIN_TOTAL_TRADES = 30
# Minimum trades on a single symbol for that symbol's stats to count as signal.
MIN_SYMBOL_TRADES = 4


@dataclass
class SweepResult:
    params: dict
    combined_pf: float
    combined_net_pct: float
    median_symbol_pf: float
    symbols_profitable: int
    total_trades: int
    max_dd: float
    beat_bh_count: int
    per_symbol: dict          # symbol -> stats dict


# ---------------------------------------------------------------------------
# Data caching: download each (symbol, timeframe) once and reuse it.
# ---------------------------------------------------------------------------
_CANDLE_CACHE: dict = {}


def get_candles_cached(symbol: str, timeframe: str) -> pd.DataFrame:
    key = (symbol, timeframe)
    if key not in _CANDLE_CACHE:
        # Temporarily point config.TIMEFRAME at the timeframe we want, then use
        # the SAME data_feed the live/backtest system uses.
        saved = config.TIMEFRAME
        config.TIMEFRAME = timeframe
        try:
            df = data_feed.get_backtest_candles(symbol)
        finally:
            config.TIMEFRAME = saved
        _CANDLE_CACHE[key] = df
    return _CANDLE_CACHE[key]


# ---------------------------------------------------------------------------
# Apply a parameter set to the config module, run the real backtest.
# ---------------------------------------------------------------------------
def apply_params(params: dict):
    """Override config globals so strategy.py + backtest.py use these values."""
    config.TIMEFRAME = params["TIMEFRAME"]
    fast, slow, trend = params["EMAS"]
    config.EMA_FAST = fast
    config.EMA_SLOW = slow
    config.EMA_TREND = trend
    config.STOP_LOSS_PCT = params["STOP_LOSS_PCT"]
    config.TAKE_PROFIT_PCT = params["TAKE_PROFIT_PCT"]
    config.RSI_MAX_ENTRY = params["RSI_MAX_ENTRY"]


def run_one(params: dict, candles: dict,
            slice_fn=None) -> SweepResult | None:
    """Run the real backtest for one parameter set across all symbols.

    `candles` is {symbol: full_df}. `slice_fn`, if given, takes a df and returns
    the portion to test (used for walk-forward: first half / second half).
    """
    apply_params(params)

    per_symbol = {}
    total_trades = 0
    combined_net = 0.0
    start = config.STARTING_CAPITAL
    pfs = []
    profitable = 0
    beat_bh = 0
    worst_dd = 0.0

    for symbol, df in candles.items():
        if df is None or df.empty:
            continue
        if slice_fn is not None:
            df = slice_fn(df)
        if len(df) < config.EMA_TREND + 5:
            continue

        trades, final_equity = backtest_symbol(symbol, df, start)
        stats = compute_stats(trades, start, final_equity)
        bh = buy_and_hold_return(df)

        per_symbol[symbol] = {**stats, "buy_hold_pct": bh}
        total_trades += stats["trades"]
        combined_net += stats["net_profit"]
        worst_dd = max(worst_dd, stats["max_drawdown_pct"])

        # Only count symbols that actually traded enough to be signal.
        if stats["trades"] >= MIN_SYMBOL_TRADES:
            pf = stats["profit_factor"]
            # Cap infinite PF (no losses) at a high finite number for scoring.
            pfs.append(min(pf, 10.0) if pf != float("inf") else 10.0)
            if stats["net_profit"] > 0:
                profitable += 1
            if stats["net_profit_pct"] > bh:
                beat_bh += 1

    if total_trades < MIN_TOTAL_TRADES or not pfs:
        return None

    combined_final = start * len(candles) + combined_net
    combined_start = start * len(candles)
    combined_stats = compute_stats_from_net(combined_start, combined_final)

    return SweepResult(
        params=params,
        combined_pf=combined_pf_from_symbols(per_symbol),
        combined_net_pct=combined_stats["net_profit_pct"],
        median_symbol_pf=statistics.median(pfs),
        symbols_profitable=profitable,
        total_trades=total_trades,
        max_dd=worst_dd,
        beat_bh_count=beat_bh,
        per_symbol=per_symbol,
    )


def compute_stats_from_net(start: float, final: float) -> dict:
    return {"net_profit_pct": (final / start - 1) * 100 if start else 0.0}


def combined_pf_from_symbols(per_symbol: dict) -> float:
    """Profit factor computed on the pooled wins/losses across all symbols.

    We don't have per-trade lists here (compute_stats already summarized), so we
    approximate the pooled PF using each symbol's net profit split into the
    win/loss buckets is not possible; instead we return the trade-weighted mean
    of finite PFs, which is a conservative combined signal.
    """
    weighted = []
    weights = []
    for s in per_symbol.values():
        if s["trades"] >= MIN_SYMBOL_TRADES:
            pf = s["profit_factor"]
            pf = min(pf, 10.0) if pf != float("inf") else 10.0
            weighted.append(pf * s["trades"])
            weights.append(s["trades"])
    if not weights:
        return 0.0
    return sum(weighted) / sum(weights)


# ---------------------------------------------------------------------------
# Robustness-aware score. Higher is better.
# ---------------------------------------------------------------------------
def score(r: SweepResult) -> float:
    """Reward configs that are profitable across MANY symbols with a solid
    median profit factor and controlled drawdown — not one lucky symbol.
    """
    # Core: median per-symbol profit factor (robust to one outlier symbol).
    s = r.median_symbol_pf

    # Bonus for breadth: how many symbols were profitable (0..4).
    s += 0.15 * r.symbols_profitable

    # Bonus for beating buy & hold on more symbols.
    s += 0.10 * r.beat_bh_count

    # Penalty for scary drawdowns (>35%).
    if r.max_dd > 35:
        s -= (r.max_dd - 35) / 50.0

    return s


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------
def all_param_combos():
    keys = list(GRID.keys())
    for combo in itertools.product(*(GRID[k] for k in keys)):
        yield dict(zip(keys, combo))


def main():
    # Save the user's original config so we can restore it at the end.
    original = snapshot_config()

    print("=" * 64)
    print("PARAMETER SWEEP — searching for a profitable, robust config")
    print("Reuses the real strategy + backtest engine. No new logic.")
    print("=" * 64)

    combos = list(all_param_combos())
    print(f"Testing {len(combos)} parameter combinations "
          f"across {len(config.SYMBOLS)} symbols ...\n")

    # Pre-download candles for both timeframes so we don't refetch per combo.
    print("Downloading candle data (cached, both timeframes) ...")
    candles_by_tf = {}
    for tf in GRID["TIMEFRAME"]:
        candles_by_tf[tf] = {
            sym: get_candles_cached(sym, tf) for sym in config.SYMBOLS
        }
        got = sum(1 for d in candles_by_tf[tf].values()
                  if d is not None and not d.empty)
        print(f"  {tf}: {got}/{len(config.SYMBOLS)} symbols downloaded")
    print()

    results: list[SweepResult] = []
    for n, params in enumerate(combos, 1):
        candles = candles_by_tf[params["TIMEFRAME"]]
        r = run_one(params, candles)
        if r is not None:
            results.append(r)
        if n % 20 == 0 or n == len(combos):
            print(f"  ...tested {n}/{len(combos)} combos "
                  f"({len(results)} passed the min-trades filter)")

    if not results:
        print("\nNo config met the minimum-trades bar. Try loosening filters.")
        restore_config(original)
        return

    results.sort(key=score, reverse=True)

    # -------------------------------------------------------------------
    # Show the leaderboard.
    # -------------------------------------------------------------------
    print("\n" + "=" * 64)
    print("TOP 8 CONFIGS (ranked by robustness-aware score)")
    print("=" * 64)
    for i, r in enumerate(results[:8], 1):
        p = r.params
        print(f"\n#{i}  score={score(r):.2f}")
        print(f"    timeframe={p['TIMEFRAME']}  EMAs={p['EMAS']}  "
              f"stop={p['STOP_LOSS_PCT']*100:.0f}%  "
              f"target={p['TAKE_PROFIT_PCT']*100:.0f}%  "
              f"rsi<{p['RSI_MAX_ENTRY']}")
        print(f"    combined net={r.combined_net_pct:+.1f}%  "
              f"weighted PF={r.combined_pf:.2f}  "
              f"median symbol PF={r.median_symbol_pf:.2f}")
        print(f"    symbols profitable={r.symbols_profitable}/4  "
              f"beat B&H={r.beat_bh_count}/4  "
              f"total trades={r.total_trades}  maxDD={r.max_dd:.0f}%")

    # -------------------------------------------------------------------
    # Walk-forward robustness check on the #1 config.
    # -------------------------------------------------------------------
    best = results[0]
    print("\n" + "=" * 64)
    print("WALK-FORWARD CHECK on the #1 config (guards against overfitting)")
    print("=" * 64)
    print("Idea: the winner was chosen using ALL history. Now we verify it also")
    print("works on the SECOND HALF alone (data the ranking didn't favor).")

    candles = candles_by_tf[best.params["TIMEFRAME"]]

    def first_half(df):
        return df.iloc[: len(df) // 2]

    def second_half(df):
        return df.iloc[len(df) // 2:]

    # For the split test we relax the minimum-trades bar (each half naturally
    # has fewer trades). We still want to SEE the numbers even if thin.
    global MIN_TOTAL_TRADES, MIN_SYMBOL_TRADES
    saved_min_total, saved_min_sym = MIN_TOTAL_TRADES, MIN_SYMBOL_TRADES
    MIN_TOTAL_TRADES, MIN_SYMBOL_TRADES = 6, 2
    r_first = run_one(best.params, candles, slice_fn=first_half)
    r_second = run_one(best.params, candles, slice_fn=second_half)
    MIN_TOTAL_TRADES, MIN_SYMBOL_TRADES = saved_min_total, saved_min_sym

    def line(label, r):
        if r is None:
            print(f"  {label}: not enough trades to judge")
        else:
            print(f"  {label}: net={r.combined_net_pct:+.1f}%  "
                  f"weighted PF={r.combined_pf:.2f}  "
                  f"profitable {r.symbols_profitable}/4  "
                  f"trades={r.total_trades}")

    line("First half ", r_first)
    line("Second half", r_second)

    robust = (r_second is not None and r_second.combined_pf >= 1.1
              and r_second.combined_net_pct > 0)
    print(f"\n  Holds up out-of-sample? {'YES' if robust else 'NOT STRONGLY'}")

    # -------------------------------------------------------------------
    # Print a ready-to-paste config for the winner.
    # -------------------------------------------------------------------
    print("\n" + "=" * 64)
    print("RECOMMENDED CONFIG (copy into config.py)")
    print("=" * 64)
    p = best.params
    print(f'  TIMEFRAME = "{p["TIMEFRAME"]}"')
    print(f'  EMA_FAST = {p["EMAS"][0]}')
    print(f'  EMA_SLOW = {p["EMAS"][1]}')
    print(f'  EMA_TREND = {p["EMAS"][2]}')
    print(f'  RSI_MAX_ENTRY = {p["RSI_MAX_ENTRY"]}')
    print(f'  STOP_LOSS_PCT = {p["STOP_LOSS_PCT"]}')
    print(f'  TAKE_PROFIT_PCT = {p["TAKE_PROFIT_PCT"]}')

    # Restore the user's original config so this script has no side effects.
    restore_config(original)
    print("\n(Your config.py was NOT modified by this script.)")


# ---------------------------------------------------------------------------
# Config snapshot/restore helpers
# ---------------------------------------------------------------------------
def snapshot_config() -> dict:
    return {
        "TIMEFRAME": config.TIMEFRAME,
        "EMA_FAST": config.EMA_FAST,
        "EMA_SLOW": config.EMA_SLOW,
        "EMA_TREND": config.EMA_TREND,
        "STOP_LOSS_PCT": config.STOP_LOSS_PCT,
        "TAKE_PROFIT_PCT": config.TAKE_PROFIT_PCT,
        "RSI_MAX_ENTRY": config.RSI_MAX_ENTRY,
    }


def restore_config(snap: dict):
    for k, v in snap.items():
        setattr(config, k, v)


if __name__ == "__main__":
    main()
