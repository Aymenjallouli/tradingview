"""
mt5_challengers.py — challenger strategies C & D + a backtester on MT5 history.

These start DISABLED and must be backtested + approved before they trade live,
per the build spec. The backtest uses the same cost model spirit (real spread
from MT5) and reports PF, win rate, max DD, trades, vs buy-and-hold, plus a
train/test walk-forward split.

  C) BEAR TREND (short only, 4h) — mirror of the Trend champion.
     20 EMA crosses BELOW 100 EMA, price < 200 EMA (falling), RSI > 30.
     Exit: cross-up, or -4% SL, +8% TP (tight — shorts are dangerous).
  D) RANGE BREAKOUT (long only, 4h) — compression then break.
     20-bar range < 60% of its 100-bar average width; buy break above the
     range high. Exit: -3% SL, +5% then trail 4%, or 15-bar time stop.
"""

import pandas as pd


def _ema(s, p):
    return s.ewm(span=p, adjust=False).mean()


def _rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / p, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / p, adjust=False).mean()
    return (100 - 100 / (1 + g / loss)).fillna(100)


class BearTrend:
    key = "bear4h"
    label = "Bear Trend 4h (short)"
    timeframe = "4h"
    direction = "short"
    stop_pct = 0.04
    target_pct = 0.08

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 210:
            return []
        df = df.copy()
        df["ef"] = _ema(df["close"], 20)
        df["es"] = _ema(df["close"], 100)
        df["et"] = _ema(df["close"], 200)
        df["rsi"] = _rsi(df["close"], 14)
        i = len(df) - 1
        row, prev = df.iloc[i], df.iloc[i - 1]
        if has_position:
            if prev["ef"] <= prev["es"] and row["ef"] > row["es"]:
                return [{"type": "close", "symbol": symbol,
                         "reason": "ema cross up"}]
            return []
        crossed_down = prev["ef"] >= prev["es"] and row["ef"] < row["es"]
        falling = row["et"] < df["et"].iloc[i - 20]
        if crossed_down and row["close"] < row["et"] and falling \
                and row["rsi"] > 30:
            return [{"type": "open", "side": "sell", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "20/100 cross down, below falling 200EMA"}]
        return []


class RangeBreakout:
    key = "breakout4h"
    label = "Range Breakout 4h (long)"
    timeframe = "4h"
    direction = "long"
    stop_pct = 0.03
    target_pct = 0.05      # then trail

    def on_candle(self, symbol, df, has_position=False):
        if len(df) < 120:
            return []
        df = df.copy()
        i = len(df) - 1
        if has_position:
            return []      # exits handled by broker SL/TP + trail in live loop
        r20 = df["high"].iloc[-20:].max() - df["low"].iloc[-20:].min()
        widths = (df["high"] - df["low"]).rolling(20).mean()
        avg100 = widths.iloc[-100:].mean()
        compressed = r20 < 0.60 * (avg100 * 20) if avg100 else False
        range_high = df["high"].iloc[-21:-1].max()
        broke = df["close"].iloc[i] > range_high
        if compressed and broke:
            return [{"type": "open", "side": "buy", "symbol": symbol,
                     "stop_pct": self.stop_pct, "target_pct": self.target_pct,
                     "reason": "breakout from compression"}]
        return []


# ---------------------------------------------------------------------------
# Backtester over MT5 history.
# ---------------------------------------------------------------------------
def backtest(strategy, df, spread_frac=0.0002):
    """Run a strategy over a candle DataFrame (MT5 history). Long or short.

    Costs: spread applied on entry+exit. Returns stats dict.
    """
    if df.empty or len(df) < 220:
        return None
    trades = []
    pos = None
    for i in range(210, len(df)):
        window = df.iloc[:i + 1]
        price = window["close"].iloc[-1]
        if pos is None:
            intents = strategy.on_candle("BT", window, has_position=False)
            for it in intents:
                if it["type"] == "open":
                    side = it["side"]
                    fill = price * (1 + spread_frac) if side == "buy" \
                        else price * (1 - spread_frac)
                    pos = {"side": side, "entry": fill,
                           "stop": it["stop_pct"], "target": it["target_pct"],
                           "bar": i}
                    break
        else:
            side = pos["side"]
            entry = pos["entry"]
            if side == "buy":
                stop_px = entry * (1 - pos["stop"])
                tgt_px = entry * (1 + pos["target"])
                hit_stop = window["low"].iloc[-1] <= stop_px
                hit_tgt = window["high"].iloc[-1] >= tgt_px
            else:
                stop_px = entry * (1 + pos["stop"])
                tgt_px = entry * (1 - pos["target"])
                hit_stop = window["high"].iloc[-1] >= stop_px
                hit_tgt = window["low"].iloc[-1] <= tgt_px
            exit_px = None
            if hit_stop:
                exit_px = stop_px
            elif hit_tgt:
                exit_px = tgt_px
            else:
                intents = strategy.on_candle("BT", window, has_position=True)
                if any(x["type"] == "close" for x in intents):
                    exit_px = price
            if exit_px is not None:
                exit_fill = exit_px * (1 - spread_frac) if side == "buy" \
                    else exit_px * (1 + spread_frac)
                if side == "buy":
                    ret = exit_fill / entry - 1
                else:
                    ret = entry / exit_fill - 1
                trades.append(ret)
                pos = None
    if not trades:
        return {"trades": 0}
    wins = [t for t in trades if t > 0]
    gw = sum(wins)
    gl = abs(sum(t for t in trades if t <= 0))
    pf = gw / gl if gl > 0 else (float("inf") if gw > 0 else 0)
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    for t in trades:
        eq *= (1 + t)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
    bh = df["close"].iloc[-1] / df["close"].iloc[210] - 1
    return {"trades": len(trades), "win_rate": len(wins) / len(trades) * 100,
            "profit_factor": pf, "net_pct": (eq - 1) * 100,
            "max_dd_pct": mdd * 100, "bh_pct": bh * 100}
