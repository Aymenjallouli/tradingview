# MT5 Execution Wing — Runbook

Connects to your **running MetaTrader 5 terminal (DEMO only)** and auto-trades
validated strategies with broker-side stop-loss + take-profit. This is the
forward-test engine — real broker execution, demo money, real risk controls.

> ⚠️ **Windows + local terminal only.** The MT5 Python API talks only to a
> terminal on the SAME machine. This wing **cannot** run on your Linux VPS —
> run it here, on the Windows machine where MT5 is open and logged in.

---

## One-time MT5 setup

1. Open MT5, log into your **demo** account.
2. **Tools → Options → Expert Advisors → check "Allow algorithmic trading"** → OK.
3. Click the **"Algo Trading"** button in the top toolbar so it's **green**
   (not red). Without this you'll get `AutoTrading disabled by client`.
4. In Market Watch, make sure the symbols you want are visible (right-click →
   Show All, or the bridge auto-selects the mapped ones).

The bridge **refuses to start on a REAL account** — this is a hard safety check
with no override. Real trading is a future manual decision, not a config flag.

---

## What it trades

**Universe (auto-detected on your broker):** BTC, ETH, XAUUSD (gold), 7 forex
majors, and US stocks AMD/NVDA/MSFT/INTC. Indices (US100/US500) are disabled on
the MetaQuotes demo and skipped automatically.

**Strategies (validated / approved):**

| Strategy | Trades | Direction | Notes |
|----------|--------|-----------|-------|
| **A — Candle Lessons** | all symbols, 1h | long | bullish reversal in uptrend, −2%/+4% |
| **B — Trend 4h** (champion) | all symbols, 4h | long | 20/100 EMA cross, −8%/+15% |
| **D — Range Breakout** | **stocks+gold only**, 4h | long | approved on NVDA/MSFT/AMD/INTC/XAUUSD (backtest PF 1.2–2.2) |
| ~~C — Bear Trend~~ | — | — | **rejected** (backtest PF 0.54) |

---

## Risk governor (hard limits, always enforced)

- Max **1.5%** account risk per position (auto lot-sizing from the stop distance)
- Max **5** open positions total, max **3** per strategy
- **Daily circuit breaker:** if equity drops **5%** in a day, all new entries are
  BLOCKED until tomorrow (open positions keep their broker SL/TP)
- Every order has **broker-side SL + TP** — protection survives a script crash
- Trailing stop: winners trail 3% behind the best price after +4%

---

## Run it

You have two ways to run — pick ONE (both run the bot; the dashboard just adds
a live web UI on top). **Don't run both at once** — they'd double-trade.

### Option A — Web dashboard (recommended: full visibility) ⭐

```bash
cd live/mt5
python mt5_dashboard.py            # live demo trading + web UI
python mt5_dashboard.py --dry      # dry-run (no orders) + web UI
```

Then open in your browser:
- **This PC:**  http://localhost:8800
- **Your phone (same wifi):**  http://<this-pc-LAN-ip>:8800

The dashboard shows, refreshing every 3s:
- account equity / balance / open P&L / position count
- every open position (side, entry, SL, TP, live P&L, strategy)
- **the full live scan** — every strategy × symbol, its status
  (SIGNAL / holding / waiting) and how close breakout strategies are to firing
- a **streaming activity log** of every signal, order, close, and heartbeat

Port is 8800 (8000 collides with Docker/WSL on this machine). Override with
`MT5_DASH_PORT=9000 python mt5_dashboard.py`.

Phone can't connect? Allow the port through Windows Firewall (PowerShell as admin):
```powershell
New-NetFirewallRule -DisplayName "MT5 Dash" -Direction Inbound -LocalPort 8800 -Protocol TCP -Action Allow
```

### Option B — Terminal only (no web UI)

```bash
cd live/mt5
python mt5_runner.py --dry         # dry-run
python mt5_runner.py               # live demo
```

Both options poll every 60s, fire strategies on new candle closes, manage
trailing stops, and enforce the risk governor. Every ~5 min a heartbeat line
(`alive · poll #N · N positions · P&L`) proves the loop is alive.

**Stop:** Ctrl+C (or kill the python process).

> ⚠️ The bot only runs while this PC is awake. If the laptop sleeps, the bot
> stops (open positions keep their broker SL/TP, but no new trades fire). For
> true 24/7, run on a VPS / broker Virtual Hosting, or set the PC to never sleep.

---

## Reading it

Every action logs a line: `OPENED NVDA 12 lots @ 203.1 SL=197 TP=213`, or
`BLOCKED — max 5 total positions`, or `CIRCUIT BREAKER: equity -5% today`.

Check open positions and P&L directly in your MT5 terminal's **Trade** tab —
they're real broker positions with visible SL/TP lines on the chart.

---

## Promoting a disabled strategy

Challengers start DISABLED. To enable one after reviewing its backtest:
1. Run its backtest: `python mt5_backtest_fast.py`
2. If it clears its kill criteria (PF above the bar, beats B&H on enough
   symbols), add it to `build_strategies()` in `mt5_strategies.py` — optionally
   with an `allowed_symbols` whitelist (like Range Breakout's stocks+gold).

## Kill criteria (auto-disable — to be wired into the live loop)

- A: PF < 0.9 after 30 trades · B: PF < 0.9 after 20 · D: PF < 0.8 after 25
- Any single-trade loss > 2.5% of account = bug alert (governor should prevent it)

---

## Files

| File | Role |
|------|------|
| `mt5_bridge.py` | Connect (demo guard), symbol mapping, candles/ticks |
| `mt5_orders.py` | Market orders + SL/TP, close, trailing modify, risk-lot sizing |
| `mt5_strategies.py` | Strategies A, B, D (approved) |
| `mt5_challengers.py` | Challenger classes C, D + naive backtester |
| `mt5_backtest_fast.py` | Fast challenger backtest (precomputed indicators) |
| `mt5_orchestrator.py` | Runs strategies, risk governor, executes |
| `mt5_runner.py` | The always-on loop (start here) |
