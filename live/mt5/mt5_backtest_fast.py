"""
mt5_backtest_fast.py — fast backtest for the challenger strategies.

Precomputes indicators ONCE per symbol, then does a single linear pass — avoids
the O(n^2) recompute that made the naive version hang. Runs C (Bear Trend) and
D (Range Breakout) over MT5 history and prints a results table for approval.
"""

import statistics

import pandas as pd

from mt5_bridge import MT5Bridge


def _ema(s, p):
    return s.ewm(span=p, adjust=False).mean()


def _rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / p, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / p, adjust=False).mean()
    return (100 - 100 / (1 + g / loss)).fillna(100)


SPREAD = 0.0002    # ~2 bps round-trip-ish per side


def _stats(trades, df):
    if not trades:
        return {"trades": 0}
    wins = [t for t in trades if t > 0]
    gw = sum(wins)
    gl = abs(sum(t for t in trades if t <= 0))
    pf = gw / gl if gl > 0 else (float("inf") if gw > 0 else 0)
    eq = peak = 1.0
    mdd = 0.0
    for t in trades:
        eq *= (1 + t)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
    bh = df["close"].iloc[-1] / df["close"].iloc[210] - 1
    return {"trades": len(trades), "win_rate": len(wins) / len(trades) * 100,
            "pf": pf, "net_pct": (eq - 1) * 100, "mdd_pct": mdd * 100,
            "bh_pct": bh * 100}


def bt_bear(df):
    """Bear Trend: precomputed, single pass."""
    ef = _ema(df["close"], 20).values
    es = _ema(df["close"], 100).values
    et = _ema(df["close"], 200).values
    rsi = _rsi(df["close"], 14).values
    hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
    trades = []
    entry = None
    for i in range(210, len(df)):
        if entry is None:
            crossed = ef[i - 1] >= es[i - 1] and ef[i] < es[i]
            falling = et[i] < et[i - 20]
            if crossed and cl[i] < et[i] and falling and rsi[i] > 30:
                entry = cl[i] * (1 - SPREAD)          # short fill
        else:
            stop_px = entry * 1.04
            tgt_px = entry * 0.92
            if hi[i] >= stop_px:
                trades.append(entry / (stop_px * (1 + SPREAD)) - 1); entry = None
            elif lo[i] <= tgt_px:
                trades.append(entry / (tgt_px * (1 + SPREAD)) - 1); entry = None
            elif ef[i - 1] <= es[i - 1] and ef[i] > es[i]:
                trades.append(entry / (cl[i] * (1 + SPREAD)) - 1); entry = None
    return _stats(trades, df)


def bt_breakout(df):
    """Range Breakout: precomputed, single pass."""
    hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
    width = (df["high"] - df["low"]).rolling(20).mean().values
    trades = []
    entry = None
    entry_bar = 0
    for i in range(120, len(df)):
        if entry is None:
            r20 = max(hi[i - 20:i]) - min(lo[i - 20:i])
            avg100 = pd.Series(width[max(0, i - 100):i]).mean()
            compressed = avg100 and r20 < 0.60 * avg100 * 20
            range_high = max(hi[i - 21:i - 1]) if i >= 21 else hi[i]
            if compressed and cl[i] > range_high:
                entry = cl[i] * (1 + SPREAD); entry_bar = i
        else:
            stop_px = entry * 0.97
            tgt_px = entry * 1.05
            if lo[i] <= stop_px:
                trades.append(stop_px * (1 - SPREAD) / entry - 1); entry = None
            elif hi[i] >= tgt_px:
                trades.append(tgt_px * (1 - SPREAD) / entry - 1); entry = None
            elif i - entry_bar >= 15:              # 15-bar time stop
                trades.append(cl[i] * (1 - SPREAD) / entry - 1); entry = None
    return _stats(trades, df)


def main():
    b = MT5Bridge()
    if not b.connect():
        raise SystemExit("no connect")
    syms = list(b.symbols.keys())

    for name, fn in [("C) BEAR TREND 4h (short)", bt_bear),
                     ("D) RANGE BREAKOUT 4h (long)", bt_breakout)]:
        print(f"\n--- {name} ---")
        print(f"{'symbol':10}{'trades':>7}{'win%':>6}{'PF':>7}"
              f"{'net%':>8}{'maxDD':>7}{'B&H%':>8}")
        pfs = []
        beat = 0
        n = 0
        for s in syms:
            df = b.candles(s, "4h", 3000)          # ~1.4 yr
            if df.empty or len(df) < 250:
                continue
            r = fn(df)
            if not r or r.get("trades", 0) < 3:
                continue
            n += 1
            pf = r["pf"]
            pfstr = "inf" if pf == float("inf") else f"{pf:.2f}"
            pfs.append(min(pf, 10) if pf != float("inf") else 10)
            if r["net_pct"] > r["bh_pct"]:
                beat += 1
            print(f"{s:10}{r['trades']:>7}{r['win_rate']:>5.0f}%{pfstr:>7}"
                  f"{r['net_pct']:>+7.1f}%{r['mdd_pct']:>6.0f}%{r['bh_pct']:>+7.1f}%")
        if pfs:
            print(f"  => median PF {statistics.median(pfs):.2f}, "
                  f"beat B&H on {beat}/{n} symbols")
        else:
            print("  (no symbol produced enough trades)")
    b.shutdown()


if __name__ == "__main__":
    main()
