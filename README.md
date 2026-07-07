# Paper Trading System

A trend-following **paper** (fake-money) trading system with **$50 virtual
capital**. It simulates trades with realistic fees and slippage, logs every
trade to a database, and can ask Claude for a daily performance review.

**Paper trading = no real money is ever at risk.** Nothing here connects to a
real brokerage. It's a safe sandbox to test a strategy before you'd ever
consider real money.

> ✅ **Current config is optimized.** A parameter sweep (`optimize.py`) tuned the
> strategy to **4h candles, 20/100/200 EMAs, −8% stop, +15% target**. This took
> the combined profit factor from a losing **0.90** (original 1h settings) to a
> profitable **1.37**. See [Results](#-results-on-the-optimized-config-current-settings)
> and [Optimization](#optimization--optimizepy).
>
> 🧪 **Also in this project:**
> - A [scalping experiment](scalping/README.md) — tests whether 1-minute crypto
>   scalping survives trading costs. (Backtest answer: no — and it shows why.)
> - A [forex experiment](forex/README.md) — tests whether forex's much tighter
>   spreads let a scalp/swing survive. (Closer, but not proven — real data helps.)
> - A [**web dashboard**](dashboard/README.md) — one browser control panel for
>   all systems, with **live real-time prices** streaming from Binance. Run
>   `cd dashboard && python server.py`, then open http://localhost:8000.

---

## Table of contents
1. [What's in the box](#whats-in-the-box)
2. [Setup (do this once)](#setup-do-this-once)
3. [Module 4 — Backtester (run this FIRST)](#module-4--backtester-run-this-first)
4. [Module 1 — Live signals (free mode, default)](#module-1--live-signals-free-mode-default)
5. [Module 2 — TradingView webhooks (optional, paid plan)](#module-2--tradingview-webhooks-optional-paid-plan)
6. [Module 5 — Daily AI review](#module-5--daily-ai-review)
7. [Scheduling the 4-hour check](#scheduling-the-check)
8. [How to read the results](#how-to-read-the-results)
9. [The strategy in plain English](#the-strategy-in-plain-english)
10. [Changing the timeframe](#changing-the-timeframe)
11. [FAQ / troubleshooting](#faq--troubleshooting)

---

## What's in the box

| File | What it is |
|------|-----------|
| `config.py` | **All settings in one place.** Change numbers here, everything follows. |
| `strategy.py` | **The strategy — the single source of truth.** Indicators + entry/exit rules. Both backtest and live import this. |
| `data_feed.py` | Downloads price candles from Yahoo Finance (yfinance). |
| `paper_broker.py` | **Module 3.** The fake broker: tracks cash, positions, P&L in a SQLite database (`trades.db`). Applies fees + slippage. |
| `backtest.py` | **Module 4.** Runs the strategy over ~2–3 years of history. **Run this first.** |
| `check_signals.py` | **Module 1.** The live signal engine. Run every 4 hours. Free (uses yfinance). |
| `webhook_server.py` | **Module 2.** Optional TradingView webhook receiver (needs a paid TradingView plan). |
| `daily_review.py` | **Module 5.** Summarizes recent trades and asks Claude for a review. |
| `requirements.txt` | Python packages to install. |

Files created **while it runs**: `trades.db` (the database), `trade_log.csv`
(exported log), `reports/YYYY-MM-DD.md` (daily AI reviews).

---

## Setup (do this once)

You need **Python 3.10 or newer**. Check with:

```bash
python --version
```

### 1. (Recommended) Create a virtual environment

A "virtual environment" keeps this project's packages separate from the rest of
your computer.

**Windows (PowerShell):**
```powershell
cd C:\Users\AymenJallouli\Desktop\tradingview
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Mac / Linux:**
```bash
cd /path/to/tradingview
python3 -m venv .venv
source .venv/bin/activate
```

> If PowerShell blocks the activate script, run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` then try again.

### 2. Install the packages

```bash
pip install -r requirements.txt
```

### 3. Set your webhook secret (only if you'll use Module 2)

Open `config.py` and change `WEBHOOK_SECRET` to your own long random string.
For the free mode (Module 1) you can ignore this.

That's it. You're ready.

---

## Module 4 — Backtester (run this FIRST)

**Always start here.** The backtest tells you whether the strategy has any edge
*before* you waste months paper trading it.

```bash
python backtest.py
```

It downloads history for all 4 symbols (BTC-USD, ETH-USD, SPY, AAPL), runs the
exact same strategy code the live system uses, and prints per-symbol and
combined results with a buy-and-hold comparison.

### 📊 Results on the OPTIMIZED config (current settings)

After a parameter sweep (`optimize.py`), the config was changed to: **4h
candles, 20/100/200 EMAs, −8% stop, +15% target, RSI<70.** These are the
current settings in `config.py`.

| Symbol | Trades | Net profit | Win rate | Profit factor | Max DD | vs. Buy & Hold |
|--------|-------:|-----------:|---------:|--------------:|-------:|:--------------:|
| BTC-USD | 13 | +$3.51 (+7.0%) | 30.8% | 1.23 | 10.6% | ❌ lost (B&H +16.0%) |
| ETH-USD | 12 | −$12.56 (−25.1%) | 8.3% | 0.32 | 25.1% | ✅ beat (B&H −37.5%) |
| SPY | 8 | +$7.19 (+14.4%) | 37.5% | 3.32 | 3.0% | ❌ lost (B&H +67.1%) |
| AAPL | 9 | +$18.87 (+37.7%) | 44.4% | 3.19 | 6.6% | ❌ lost (B&H +75.4%) |
| **Combined** | **42** | **+$17.01 (+8.5%)** | **28.6%** | **1.37** | **9.7%** | **❌ lost (B&H +30.3%)** |

> **Honest verdict.** The optimizer turned a **losing** system (1h combined
> profit factor **0.90**) into a **profitable** one (4h combined **1.37**,
> +8.5% net, max drawdown down to 10%). It now **clears the 1.3 profit-factor
> bar.** 3 of 4 symbols are profitable; SPY and AAPL are genuinely strong
> (PF > 3). ETH is the one loser.
>
> **Two honest caveats — read these before trusting it:**
> 1. **It still loses to buy-and-hold** (+8.5% vs +30.3%). In a raging bull
>    market, a cash-heavy strategy that sits out most of the time will trail
>    simply holding. The strategy's value is *lower drawdown* (10% vs holding
>    through −40% ETH crashes), not beating a bull market.
> 2. **Small sample.** 42 trades over 2 years is thin. A
>    [walk-forward check](#optimization--optimizepy) showed the edge is
>    positive but *inconsistent* across time periods. Treat these numbers as
>    "promising, not proven."
>
> **This is why you paper trade it.** The backtest says "worth testing live,"
> not "guaranteed money." See [How to read the results](#how-to-read-the-results).

> **Data note:** Yahoo Finance serves ~2 years of 1h crypto history and ~3
> years for stocks. The backtest uses whatever it can get and prints the exact
> date range per symbol. This is real free data — no perfect, unlimited
> history.

---

## Module 1 — Live signals (free mode, default)

This is the **default** way to run live. It's free and needs no TradingView
account. Every time you run it, it:

1. Downloads fresh candles for all 4 symbols.
2. Checks the most recent **closed** candle for entry/exit signals.
3. Tells the paper broker to buy/sell accordingly.

```bash
python check_signals.py
```

You run this **every 4 hours** (see [Scheduling](#scheduling-the-check)). It's
safe to run more often — it only acts on newly closed candles and won't open a
second position in a symbol it's already holding.

Check your account any time:

```bash
python paper_broker.py      # prints cash, open positions, trade count, exports CSV
```

---

## Module 2 — TradingView webhooks (optional, paid plan)

> ⚠️ **TradingView webhook alerts require a PAID TradingView plan** (Essential
> or higher). On the free plan you cannot send webhooks — use Module 1 instead.

Instead of polling Yahoo yourself, TradingView runs the strategy on *their*
side and pushes an alert to your server. Same paper broker, same rules.

### 1. Start the server

```bash
python webhook_server.py
# or:  uvicorn webhook_server:app --host 0.0.0.0 --port 8000
```

Visit http://localhost:8000/ — you should see `{"status":"ok",...}`.

### 2. Expose it to the internet

TradingView must be able to reach your server. For testing, use
[ngrok](https://ngrok.com/):

```bash
ngrok http 8000
```

Copy the `https://....ngrok-free.app` URL it gives you.

### 3. Create the TradingView alert

Set the alert's **Webhook URL** to `https://YOUR-NGROK-URL/webhook` and paste
**exactly this** into the alert **Message** box (replace the secret with the
value from your `config.py`):

```json
{
  "secret": "change-me-to-a-long-random-string",
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "price": {{close}}
}
```

- `{{ticker}}`, `{{strategy.order.action}}`, `{{close}}` are TradingView
  placeholders it fills in automatically.
- The server **rejects any request with the wrong secret** (HTTP 403).
- It maps TradingView tickers like `BTCUSD` → `BTC-USD` automatically.

---

## Module 5 — Daily AI review

Uses the `claude` command from your **Claude Code subscription** to review your
recent trades. It gathers the last 7 days of trades, your open positions, and
your equity curve, then asks Claude what's working, what's failing, and **one**
suggested adjustment.

```bash
python daily_review.py
```

- The response is saved to `reports/YYYY-MM-DD.md`.
- **It never changes your strategy.** Suggestions are for *you* to read and
  decide on. Nothing is applied automatically.

**Requirements:** the `claude` command must be installed (comes with Claude
Code) and you must be signed in (run `claude` once interactively first).

---

## Scheduling the check

Run `check_signals.py` **every 4 hours**, 24/7 (crypto trades on weekends too).

> Use the **full path to Python inside your venv** so the scheduler finds the
> right packages. Find it with `where python` (Windows) or `which python`
> (Mac/Linux) **while your venv is activated**.

### Windows — Task Scheduler

Easiest via the command line (run PowerShell **as Administrator**):

```powershell
$py = "C:\Users\AymenJallouli\Desktop\tradingview\.venv\Scripts\python.exe"
$script = "C:\Users\AymenJallouli\Desktop\tradingview\check_signals.py"
$action = New-ScheduledTaskAction -Execute $py -Argument $script `
    -WorkingDirectory "C:\Users\AymenJallouli\Desktop\tradingview"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 4)
Register-ScheduledTask -TaskName "PaperTradingSignals" `
    -Action $action -Trigger $trigger -Description "4h paper trading signal check"
```

To remove it later: `Unregister-ScheduledTask -TaskName "PaperTradingSignals"`.

Or use the **Task Scheduler GUI**: Create Task → Trigger: Daily, repeat every 4
hours → Action: Start a program → Program = your venv `python.exe`, Arguments =
`check_signals.py`, "Start in" = the project folder.

### Mac / Linux — cron

Edit your crontab:

```bash
crontab -e
```

Add this line (runs at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00):

```
0 */4 * * * cd /path/to/tradingview && /path/to/tradingview/.venv/bin/python check_signals.py >> signals.log 2>&1
```

Signals and errors get appended to `signals.log` so you can check what happened.

---

## How to read the results

Focus on these numbers from the backtest (and later, from your live CSV log):

- **Profit factor** — total winnings ÷ total losses.
  - `> 1.0` = made money. `> 1.3` = the target for "worth trading".
  - `< 1.0` = **lost money.** (Current combined = 0.90.)
- **Net profit** — the bottom line in dollars/percent.
- **Win rate** — % of trades that made money. Trend strategies often have a
  *low* win rate (many small losses) but still profit *if* the wins are big
  enough. So don't panic at 30% — look at profit factor together with it.
- **Max drawdown** — the worst peak-to-trough drop in your equity. 40% means at
  some point you were down 40% from your high. High drawdown = stressful.
- **vs. Buy & hold** — if just *holding* the asset beats the strategy, the
  strategy isn't adding value on that symbol.

### What to do about the current results

The optimized config **passes the profit-factor bar (1.37 > 1.3)** but still
trails buy-and-hold. Reasonable next steps if you want to push further —
change one thing at a time in `config.py`, re-run `python backtest.py`:

1. **Consider dropping ETH.** It's the only losing symbol (PF 0.32). SPY and
   AAPL carry the whole strategy (PF > 3). A 3-symbol version (no ETH) would
   have a much cleaner combined number — but fewer symbols = fewer trades =
   more luck-dependent. Your call.
2. **Add a trend-strength filter** (only enter when the 200 EMA is *rising*),
   which tends to cut losing trades in choppy markets.
3. **Re-run `optimize.py` periodically** as new data arrives, but resist the
   urge to keep tuning until the number looks perfect — that's overfitting.

**Reality check on "beats buy-and-hold":** over a strong 2-year bull run,
almost *no* risk-managed strategy beats simply holding, because holding is 100%
exposed the whole time and this strategy sits in cash most of it. What this
strategy buys you is a **much smaller drawdown** (≈10% vs riding ETH down −40%).
If your goal is "grow $50 fastest in a bull market," buy-and-hold wins. If your
goal is "learn systematic trading with controlled risk," this is the point.

### Optimization — `optimize.py`

The winning config above was found by `optimize.py`, which sweeps timeframe,
EMA lengths, stop/target, and RSI across all symbols and ranks them by a
**robustness-aware score** (median per-symbol profit factor + how many symbols
are profitable + drawdown penalty), not just the single highest backtest
number. It also runs a **walk-forward check**: it verifies the winner still
works on the *second half* of history alone. Re-run it any time:

```bash
python optimize.py
```

It prints a leaderboard and a ready-to-paste config block. It does **not**
modify `config.py` — you copy the values in yourself.

---

## The strategy in plain English

**Long only** (it only ever buys, never short-sells). One position per symbol at
a time. It uses 95% of your current equity per trade.

- **Enter (buy) when ALL are true:**
  1. The 20 EMA crosses **above** the 50 EMA (a fresh uptrend signal).
  2. Price is **above** the 200 EMA (the bigger trend is up).
  3. RSI(14) is **below 70** (not already overbought).
- **Exit (sell) when ANY is true:**
  1. The 20 EMA crosses **below** the 50 EMA (trend flipping down), **or**
  2. Price drops **−3%** from entry (stop loss), **or**
  3. Price rises **+6%** from entry (take profit).
- **Costs simulated on every trade:** 0.1% fee per side + 0.05% slippage.

*(EMA = Exponential Moving Average, a smoothed trend line. RSI = Relative
Strength Index, a 0–100 momentum gauge; >70 is often "overbought".)*

---

## Changing the timeframe

Everything keys off one line in `config.py`:

```python
TIMEFRAME = "1h"     # change to "4h" for 4-hour candles
```

Valid values that Yahoo serves well: `"1h"`, `"1d"`. For `"4h"` the system
automatically builds 4-hour candles by resampling 1-hour data (so it works for
stocks too). After changing it, **re-run `python backtest.py`** to see the new
numbers before trading it live.

---

## FAQ / troubleshooting

**"Not enough data for SPY/AAPL"** — Yahoo limits intraday history. The code
already pulls the longest window it can. If you see this, Yahoo may be rate
limiting you; wait a few minutes and retry.

**yfinance download errors / empty data** — Yahoo occasionally rate-limits or
has hiccups. The scripts skip a symbol that fails and keep going. Just re-run.

**The `claude` command isn't found (Module 5)** — install Claude Code and sign
in (`claude` once interactively). It's not a pip package.

**I want to start over / reset the account** — delete `trades.db`. A fresh one
with $50 cash is created automatically on the next run.

**Where's my trade log?** — run `python paper_broker.py` to export
`trade_log.csv`, or open `trades.db` with any SQLite viewer (e.g.
[DB Browser for SQLite](https://sqlitebrowser.org/)).

**Is any real money involved?** — No. Never. This is 100% simulated.
```
