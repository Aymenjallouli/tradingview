# Forex Experiment — can tighter spreads make scalping work?

The crypto scalper died because its cost (~0.30% round-trip) was **bigger than
its edge**. Forex majors have far tighter spreads (~0.008% round-trip here —
about **35× cheaper**), so this experiment asks the honest follow-up:

> With forex's much lower cost, does a scalp survive? And does a slower "swing"
> version do even better?

It tests **two strategies side by side** on the same data with the same honest,
realistic cost model. **Paper money only. No API key needed** (yfinance forex).

---

## TL;DR of the results so far

| | Crypto scalp | Forex scalp | Forex swing |
|---|---:|---:|---:|
| Round-trip cost | 0.30% | **0.008%** | 0.008% |
| Cost as % of gross profit | 1,353% | **82%** | 21–30% |
| Profit factor (with costs) | 0.05 | 0.70 (→1.16 tuned) | 0.65 combined |
| Verdict | 💀 structurally dead | ⚠️ close but not proven | ⚠️ mixed |

**What changed vs crypto:** forex tightness fixed the *cost* problem — the
strategy went from catastrophic to near-breakeven. **What didn't:** the *edge*
still isn't strong enough to clearly clear even the small remaining cost, on the
short, low-volatility data windows yfinance provides.

**Important nuance:** the swing strategy on **USD/JPY alone** (which actually
trended) hit **profit factor 1.34, cost 21% of gross — passing 2 of 3
criteria.** The combined average was dragged down by EUR/USD and GBP/USD during
a dead-flat month. This is why the honest next step is **forward-testing over
more varied market conditions**, not declaring victory or defeat on one week.

> **The honest bottom line:** I could NOT prove forex scalping is profitable
> with the data available — but unlike crypto, it is **not structurally doomed.**
> The only real way to settle it is to let the live paper trader run for weeks
> and accumulate your own out-of-sample data. That's what it's built for.

---

## Why you can't just "tune it profitable"

This is the single most important lesson from both experiments:

- **Scalping's problem was arithmetic, not settings.** When cost > edge, no
  parameter fixes it. Forex shrinks the cost, so tuning *starts* to help
  (scalp PF went 0.70 → 1.16 after sweeping 81 combos) — but if the underlying
  edge is weak, tuning just finds a lucky fit that won't survive live.
- **The optimizer here ranks by robustness** (median per-pair profit factor +
  how many pairs are profitable), not the single best number, specifically so
  we don't fool ourselves. When it says "still not profitable," believe it.

---

## The two strategies (both in `forex_strategy.py`, one source of truth)

**SCALP** (fast mean-reversion, 1-minute):
- Entry: close < lower Bollinger Band(20, 2.0) AND RSI(7) < 25
- Exit: middle Bollinger Band (TP) / −0.15% stop / 30-min max hold

**SWING** (trend pullback, 5-minute — fewer, bigger trades):
- Entry: 20 EMA > 50 EMA AND price > 200 EMA (uptrend) AND price pulls back to
  the 20 EMA AND RSI(14) < 70
- Exit: +1.2% take profit / −0.6% stop / trend break (20 EMA < 50 EMA)

The swing's bigger targets mean the fixed cost is a *tiny fraction* of each
trade — the structural fix for the scalping problem.

## The cost model (realistic, not softened)

yfinance forex candles are **mid prices** (no spread baked in). Real forex cost
IS the spread, so we model it explicitly per pair, in **pips**:

| Pair | Spread (pips) | Round-trip cost |
|------|--------------:|----------------:|
| EUR/USD | 0.5 | ~0.008% |
| GBP/USD | 0.8 | ~0.009% |
| USD/JPY | 0.7 | ~0.007% |

Plus 0.2 pips slippage per side. Entries fill at the **next candle's open**,
never the signal candle's close. (See `forex_config.py` to adjust.)

---

## Files

| File | What it is |
|------|-----------|
| `forex_config.py` | All settings + the per-pair spread cost model. |
| `forex_feed.py` | yfinance forex download + pip→price cost conversion. |
| `forex_strategy.py` | **Both strategies — single source of truth.** |
| `forex_backtest.py` | Backtest both, with vs without costs, side by side. |
| `forex_optimize.py` | Robustness-ranked parameter sweep (no overfitting). |
| `forex_ledger.py` | SQLite ledger (`fx_*` tables in `../trades.db`). |
| `forex_live.py` | Live paper trader (60s poll, −25% auto-halt). |
| `forex_report.py` | Verdict report + equity-curve PNG. |

---

## HOW TO TEST EVERYTHING (step by step)

From inside the `forex/` folder (`cd forex`). Dependencies are in the project's
top-level `requirements.txt`.

### 1. Backtest both strategies (start here)

```bash
python forex_backtest.py          # both scalp and swing
python forex_backtest.py scalp    # just scalp
python forex_backtest.py swing    # just swing
```

Read the **WITH costs** column and the per-pair breakdown. Look for pairs where
a strategy passes even if the average doesn't (USD/JPY swing did).

### 2. Search for a better config

```bash
python forex_optimize.py          # sweeps both, prints top-5 + best combo
```

It does **not** edit any files — it prints a "BEST combo" block. To use it,
copy those values into the `SCALP` or `SWING` dict in `forex_config.py`, then
re-run the backtest to confirm.

### 3. Forward-test with live paper money (the real test)

```bash
python forex_live.py swing        # or: python forex_live.py scalp
```

- Polls every 60 seconds, prints each signal/fill/equity line.
- **Auto-halts if equity drops 25%.**
- **Ctrl+C** to stop; progress is saved. Re-run to resume.
- Let it run for **days to weeks** — this accumulates out-of-sample data across
  different market conditions, which the short backtest can't give you. This is
  the honest way to judge the edge.

> Forex market hours: ~Sunday 5pm ET to Friday 5pm ET. It's quiet on weekends,
> so signals will be sparse then — that's normal.

To reset the forex ledger and start a clean experiment:

```bash
python -c "from forex_ledger import ForexLedger; l=ForexLedger(); l.reset(); l.close(); print('fx ledger reset')"
```

### 4. Read the verdict any time

```bash
python forex_report.py
```

Prints per-strategy stats, the cost-as-%-of-gross number, the success criteria,
and saves `forex_equity_curve.png`.

### 5. Schedule it (optional, to run unattended)

The live trader loops on its own, so you can just leave it running in a terminal.
To run it as a background task on **Windows**, use Task Scheduler pointing at
`python.exe forex_live.py swing` with "Start in" = this folder (same pattern as
the trend system's README). On **Mac/Linux**, run it in `tmux`/`screen` or as a
`nohup python forex_live.py swing &` background process.

---

## How to judge whether it's actually working

After a real forward-test run, apply the success criteria (the report checks
these automatically):

1. **Profit factor > 1.3** with full costs — the core "is there an edge" test.
2. **Cost < 30% of gross profit** — is the spread eating you alive? (Forex
   passes this far more easily than crypto did.)
3. **Beats buy-and-hold** of the same pairs over the period.
4. **Survives 200+ trades** without hitting the −25% halt.

If it passes all four on paper across varied conditions, you have something
worth studying further. If it fails, you've learned — cheaply, with fake money —
exactly what the crypto experiment taught: **most short-term strategies can't
out-trade their costs, and the ones that survive do it by trading less, not
more.**

---

## The meta-lesson across all three experiments

| Experiment | Trades | Timeframe | Result |
|---|---:|---|---|
| Trend (parent folder) | ~40 / 2yr | 4h | PF 1.37 ✅ |
| Crypto scalp | ~1,700 / 30d | 1m | PF 0.05 💀 |
| Forex scalp | ~220 / 5d | 1m | PF 0.70 ⚠️ |
| Forex swing | ~170 / 30d | 5m | PF 0.65 ⚠️ (1.34 on JPY) |

**Fewer, higher-conviction trades beat many tiny ones — because costs scale with
trade count, not with how sure you are.** The trend system trades 40 times in
two years and works. The scalpers trade thousands of times and fight their own
costs. Forex's tighter spread narrows the gap but doesn't magically create edge.
```
