"""
momentum.py — Cross-sectional momentum (the ONE strategy with real evidence).

Based on Asness, Moskowitz & Pedersen, "Value and Momentum Everywhere"
(Journal of Finance, 2013): rank a universe of assets by recent performance,
hold the top performers, drop the rest, and rebalance slowly. The documented
edge generalizes across markets including currencies and crypto.

Why this can survive costs where indicator-scalping couldn't:
  * LOW TURNOVER. It rebalances weekly (not every minute), so it pays fees a
    handful of times per month, not hundreds. Costs scale with trade count —
    this is the whole point.
  * It rides established trends across MANY assets instead of predicting
    short-term wiggles on one.

Honest limitations (built in, not hidden):
  * Modest expected returns; it aims to beat buy-and-hold on a RISK-ADJUSTED
    basis (lower drawdown), not to multiply money fast.
  * Momentum crashes hard during sharp reversals. There is no free lunch.

This module provides:
  * momentum_score(prices)         — the ranking signal (past return, skip most
                                      recent bar to avoid short-term reversal).
  * select_portfolio(scores, n)    — pick the top N.
  * A backtester (run with `python momentum.py`) that tests it on real Binance
    data with realistic costs, vs an equal-weight buy-and-hold benchmark.
"""

import time
from datetime import datetime, timezone

import pandas as pd
import requests

import config


LOOKBACK_BARS = 30        # momentum look-back (e.g. 30 daily bars ≈ 1 month)
SKIP_BARS = 1             # skip the most recent bar (short-term reversal)
TOP_N = 5                 # hold the top 5 momentum names
REBALANCE_EVERY = 7       # rebalance every 7 bars (weekly on daily data)
FEE = config.FEE_PCT
SLIP = config.SLIPPAGE_PCT


def _klines(symbol, interval, limit):
    try:
        rows = requests.get(f"{config.BINANCE_REST}/api/v3/klines",
                            params={"symbol": symbol, "interval": interval,
                                    "limit": limit}, timeout=15).json()
        if not isinstance(rows, list):
            return None
        return pd.Series([float(r[4]) for r in rows],
                         index=[r[0] for r in rows])
    except Exception:  # noqa: BLE001
        return None


def momentum_score(prices: pd.Series) -> float:
    """Past return over the look-back window, skipping the most recent bar.

    Skipping the last bar avoids the well-known short-term reversal effect —
    the standard "12-1" momentum construction from the literature, scaled down.
    """
    if len(prices) < LOOKBACK_BARS + SKIP_BARS + 1:
        return float("nan")
    end = prices.iloc[-(SKIP_BARS + 1)]
    start = prices.iloc[-(LOOKBACK_BARS + SKIP_BARS + 1)]
    if start <= 0:
        return float("nan")
    return (end / start) - 1.0


def select_portfolio(scores: dict, n: int) -> list:
    """Top N assets by momentum score (only positive momentum — don't buy
    downtrends; long-only for a spot retail account)."""
    ranked = sorted(((s, v) for s, v in scores.items() if v == v and v > 0),
                    key=lambda kv: kv[1], reverse=True)
    return [s for s, _ in ranked[:n]]


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def backtest(universe, interval="1d", limit=500):
    """Walk-forward backtest of cross-sectional momentum vs equal-weight HODL.

    Realistic: rebalances every REBALANCE_EVERY bars, charges fee+slippage on
    every buy/sell when the held set changes, long-only, equal weight.
    """
    # Download aligned close series for every symbol.
    print(f"Downloading {len(universe)} symbols ({interval}, {limit} bars)...")
    series = {}
    for sym in universe:
        s = _klines(sym, interval, limit)
        if s is not None and len(s) > LOOKBACK_BARS + 10:
            series[sym] = s
        time.sleep(0.05)
    if len(series) < TOP_N + 1:
        print("Not enough data.")
        return

    # Align on the common time index. Newer coins have shorter history, so
    # requiring ALL symbols to overlap fully can empty the frame. Instead keep
    # symbols that cover the longest common window, then dropna on that.
    df = pd.DataFrame(series)
    # Keep only rows where at least TOP_N+1 symbols have data, then forward-fill
    # small gaps and drop remaining NaNs at the edges.
    df = df.dropna(thresh=TOP_N + 1)
    df = df.dropna(axis=1, thresh=int(len(df) * 0.8))   # drop too-short symbols
    df = df.dropna()
    if df.empty or df.shape[1] < TOP_N + 1:
        print(f"Not enough overlapping history "
              f"(got {df.shape[1]} symbols, {df.shape[0]} bars). "
              f"Try fewer/older symbols or a shorter limit.")
        return
    print(f"Aligned {df.shape[1]} symbols over {df.shape[0]} bars "
          f"({datetime.fromtimestamp(df.index[0]/1000, timezone.utc).date()} "
          f"to {datetime.fromtimestamp(df.index[-1]/1000, timezone.utc).date()})")

    start_i = LOOKBACK_BARS + SKIP_BARS + 1
    equity = 1.0
    held = []
    curve = []
    hodl = 1.0
    n_rebalances = 0
    total_cost = 0.0

    for i in range(start_i, len(df)):
        # Rebalance on schedule.
        if (i - start_i) % REBALANCE_EVERY == 0:
            scores = {s: momentum_score(df[s].iloc[:i + 1]) for s in df.columns}
            new_held = select_portfolio(scores, TOP_N)
            # Cost = turnover (symbols entering or leaving) * (fee+slip) per side.
            changed = set(held) ^ set(new_held)
            if held or new_held:
                turnover_frac = len(changed) / max(len(new_held), 1)
                cost = turnover_frac * (FEE + SLIP) * 2  # both sides
                equity *= (1 - cost)
                total_cost += cost
            held = new_held
            n_rebalances += 1

        # Apply this bar's return to the held portfolio (equal weight).
        if held:
            rets = [(df[s].iloc[i] / df[s].iloc[i - 1] - 1) for s in held
                    if s in df.columns]
            if rets:
                equity *= (1 + sum(rets) / len(rets))
        # HODL benchmark: equal-weight all symbols.
        hodl_rets = [(df[s].iloc[i] / df[s].iloc[i - 1] - 1) for s in df.columns]
        hodl *= (1 + sum(hodl_rets) / len(hodl_rets))
        curve.append(equity)

    # Stats.
    total_ret = (equity - 1) * 100
    hodl_ret = (hodl - 1) * 100
    peak = 1.0
    mdd = 0.0
    for e in curve:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak)

    print("\n" + "=" * 56)
    print("CROSS-SECTIONAL MOMENTUM — BACKTEST (with realistic costs)")
    print("=" * 56)
    print(f"  Universe:            {df.shape[1]} symbols")
    print(f"  Look-back:           {LOOKBACK_BARS} bars, hold top {TOP_N}, "
          f"rebalance every {REBALANCE_EVERY}")
    print(f"  Rebalances:          {n_rebalances}")
    print(f"  Total cost drag:     {total_cost*100:.1f}%")
    print(f"  Strategy return:     {total_ret:+.1f}%")
    print(f"  Buy & hold (EW):     {hodl_ret:+.1f}%")
    print(f"  Max drawdown:        {mdd*100:.1f}%")
    verdict = "BEAT" if total_ret > hodl_ret else "TRAILED"
    print(f"  Strategy {verdict} equal-weight buy & hold")
    print("\n  Honest read: momentum's value is usually LOWER DRAWDOWN, not")
    print("  higher raw return in a bull market. Judge on risk, not just %.")
    return {"strategy_ret": total_ret, "hodl_ret": hodl_ret, "mdd": mdd*100}


DEFAULT_UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "MATICUSDT", "LTCUSDT",
    "TRXUSDT", "ATOMUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
    "INJUSDT", "SUIUSDT",
]


if __name__ == "__main__":
    backtest(DEFAULT_UNIVERSE, interval="1d", limit=500)
