# Scalping Experiment

A **scientific test**, not a money-maker: *can a 1-minute mean-reversion scalp
survive realistic trading costs?* Spoiler from the backtest — **no.** But the
point is to *measure* exactly how and why, honestly, without softening the cost
assumptions.

This lives in the `scalping/` subfolder of the paper-trading project. It shares
the SQLite database (`../trades.db`) but writes to its **own** `scalp_*` tables,
so it never mixes with the trend system.

**Paper only. No real money. No API key needed** (Binance public market data).

---

## The strategy (mean-reversion scalp, long only)

- **Symbols:** BTCUSDT, ETHUSDT, SOLUSDT (Binance spot)
- **Timeframe:** 1-minute candles
- **Entry:** candle closes **below** the lower Bollinger Band (20, 2.0)
  **AND** RSI(7) < 25 (deeply oversold)
- **Exit:** price touches the **middle** Bollinger Band (take profit),
  **OR** −0.6% stop loss, **OR** 30-minute max hold — whichever comes first
- **Sizing:** 30% of virtual equity per trade, one position per symbol
- **Capital:** $50 virtual

## The cost model (deliberately realistic — the whole experiment)

- **Fee:** 0.1% per side (Binance spot taker)
- **Slippage:** 0.05% per side
- **Execution delay:** entries fill at the **next** candle's open after the
  signal, never the signal candle's close.

---

## Files

| File | What it is |
|------|-----------|
| `scalp_config.py` | All scalping settings in one place. |
| `scalp_strategy.py` | **The strategy — single source of truth.** Bollinger + RSI + exit logic. Used by both backtest and live. |
| `binance_feed.py` | Pulls 1m candles from Binance's public API (paginated). |
| `scalp_backtest.py` | **Module A.** Backtest with vs without costs, side by side. |
| `scalp_ledger.py` | The scalp SQLite ledger (`scalp_*` tables in `../trades.db`). |
| `scalp_live.py` | **Module B.** Live paper scalper: polls every 60s, auto-halts at −25%. |
| `scalp_report.py` | **Module C.** Verdict report + equity-curve PNG. |

---

## How to run it

From **inside the `scalping/` folder**:

```bash
cd scalping
```

(Dependencies are in the project's top-level `requirements.txt` — if you haven't
already: `pip install -r ../requirements.txt`.)

### Module A — Backtester (run this FIRST)

```bash
python scalp_backtest.py
```

Downloads ~30 days of 1-minute history for all 3 coins and prints results
**with** and **without** costs side by side, plus the buy-and-hold comparison
and the four success criteria.

### Module B — Live paper scalper

```bash
python scalp_live.py
```

Polls Binance every 60 seconds, prints each signal/fill/equity line, and
**auto-halts if equity drops 25%**. Stop any time with **Ctrl+C** — progress is
saved in the ledger. To wipe the ledger and start fresh:

```bash
python -c "from scalp_ledger import ScalpLedger; l=ScalpLedger(); l.reset(); l.close(); print('scalp ledger reset')"
```

### Module C — Verdict report

```bash
python scalp_report.py
```

Reads the ledger (from your live run), prints the verdict metrics, and saves
`scalp_equity_curve.png`.

---

## 📊 Backtest results (30 days, with vs without costs)

This is the actual output of `scalp_backtest.py`:

| Metric (combined, 3 coins) | **WITH costs** | WITHOUT costs |
|---|---:|---:|
| Trades | 1,748 | 1,735 |
| Net P&L | **−39.1%** | +3.1% |
| Win rate | **10.4%** | 67.4% |
| Profit factor | **0.05** | 1.17 |
| Max drawdown | 39.1% | 1.0% |
| Total fees paid | **$41.27** | $0.00 |
| Buy & hold | +17.4% | +17.4% |

**The number that kills scalping:**

- Gross profit from winners (with costs): **$3.05**
- Total fees paid: **$41.27**
- **Fees as % of gross profit: 1,353%**
- Average P&L per trade: **−$0.03**

### Verdict against the success criteria

| Criterion | Result |
|---|---|
| Profit factor > 1.3 with full costs | ❌ **FAIL** (0.05) |
| Fees below 30% of gross profit | ❌ **FAIL** (1,353%) |
| Beats buy-and-hold | ❌ **FAIL** (−39% vs +17%) |
| Survives 200+ trades without −25% halt | ❌ **FAIL** (would halt fast) |

---

## What this experiment proves

The strategy has a **real edge** — *without* costs it wins ~67% of the time at a
1.17 profit factor. The mean-reversion signal genuinely predicts a small bounce.

But the edge per trade is **tiny** (fractions of a percent), and the round-trip
cost (0.1% + 0.1% fees + 0.05% + 0.05% slippage ≈ **0.3%**) is *larger than the
edge*. So every trade starts ~0.3% in the hole, and the 67% win rate collapses
to 10% once each winner has to clear that hurdle.

**This is why retail scalping loses money.** It's not that the signal is bad —
it's that you can't out-trade your transaction costs when your edge is smaller
than the spread + fees. The more you trade, the more you pay. 1,748 trades × a
small negative expectancy = a steady bleed to zero.

> As your prompt put it: *"If it fails on paper, it fails harder with real
> money."* Real spreads are wider, real slippage on market orders is worse, and
> real fills lag further. Paper is the **optimistic** case, and paper already
> fails.

**Takeaway:** the trend system in the parent folder trades ~40 times over 2
years and clears a 1.37 profit factor. This scalper trades ~1,700 times in 30
days and dies. Fewer, higher-quality trades beat many tiny ones — because costs
scale with trade count, not with conviction.
```
