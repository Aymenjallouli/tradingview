# Real-Time Paper Trader (clean, VPS-ready)

The production-shaped version of the project. It runs **three strategies side by
side** on **real-time, event-driven** market data, with **Claude as a live
helper**, built to run **24/7 on a VPS**.

**To deploy tonight on your pm2 VPS, see [DEPLOY_TONIGHT.md](DEPLOY_TONIGHT.md).**

## What it runs (three paper accounts, each $50)

| Strategy | Market | Speed | Backtest verdict |
|----------|--------|-------|------------------|
| **Trend** | crypto 4h (Binance WS) | real-time candle-close | ✅ passed (PF ~1.37) |
| **Scalp** | crypto 1m (Binance WS) | **tick-level** exits | ❌ lost (costs) — watch it |
| **Forex** | USD/JPY 5m (yfinance) | ~60s refresh | ⚠️ mixed (best economics) |

- **Real-time, no polling for crypto.** Reacts to Binance's live WebSocket.
  Scalp *exits* (stop/target) fire on **every tick** (sub-second), not once a
  minute. Forex has no free tick feed, so it refreshes ~every 60s.
- **Claude as a live helper** (not the trigger). Every ~3 minutes, Claude reads
  the real metrics and gives a plain-language read of what's happening. It uses
  the `claude` CLI (your subscription), NOT the paid API. If `claude` isn't
  installed, the helper shows "offline" and everything else keeps working.
- **Paper money.** Realistic fees + slippage. No broker, no keys, no real funds.
- **One process.** Engine + Claude helper + dashboard in a single always-on app.

> **Why Claude is a helper, not the brain:** an LLM takes seconds per answer —
> far too slow to trigger a scalp, and honestly LLMs don't predict short-term
> prices better than simple rules. So the fast math rules trade; Claude watches
> and explains. That's the honest, useful division of labor.

> **Expectation:** trend/forex trade a few times a week; the scalp trades often.
> "0 trades" right after starting is normal — the strategies wait for real
> signals. The dashboard's "brain" panel shows exactly what each is waiting for.

---

## Run it locally (30 seconds)

```bash
cd live
pip install -r requirements.txt
python app.py
```

Open **http://localhost:8000** (or `DASHBOARD_PORT=8010 python app.py`).

You'll see: a live price ticker, Claude's live read, three strategy cards (each
with equity, stats, and a "brain" panel showing what it's waiting for), and a
live activity log.

---

## Files

| File | Role |
|------|------|
| `app.py` | **Start here.** Runs engine + Claude helper + dashboard. |
| `engine.py` | Real-time multi-strategy, multi-feed engine. |
| `strategy.py` | The three strategies (trend, scalp, forex) — one source of truth. |
| `broker.py` | Multi-account paper broker (one account per strategy). |
| `claude_helper.py` | Claude Code live commentary (via the `claude` CLI). |
| `config.py` | All settings (env-var overridable). |
| `index.html` | The real-time dashboard (SSE, no polling, no CDN). |
| `ecosystem.config.js` | **pm2** deploy config (for your VPS). |
| `Dockerfile`, `docker-compose.yml` | Docker deploy (alternative to pm2). |
| `deploy/rt-paper-trader.service` | systemd deploy (alternative). |
| `DEPLOY_TONIGHT.md` | Step-by-step VPS deploy for your pm2 setup. |

---

## Deploy to your VPS (pm2)

You already run pm2. Add this as a second process — full steps in
[DEPLOY_TONIGHT.md](DEPLOY_TONIGHT.md). Short version:

```bash
cd ~/rt-trader
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
pm2 start ecosystem.config.js
pm2 save
pm2 logs rt-trader
```

Docker and systemd are also provided if you prefer them.

---

## Configuration (env vars — no code edits)

Set these in `ecosystem.config.js`, docker-compose, or your shell:

| Var | Default | Meaning |
|-----|---------|---------|
| `ENABLED` | `trend,scalp,forex` | Which strategies to run. |
| `STARTING_CAPITAL` | `50` | Virtual cash per strategy. |
| `CRYPTO_SYMBOLS` | `BTCUSDT,ETHUSDT` | Crypto pairs. |
| `FOREX_SYMBOLS` | `USDJPY=X,EURUSD=X` | Forex pairs. |
| `SCALP_RSI_ENTRY` | `45` | Scalp oversold entry (higher = trades more). |
| `SCALP_BAND_TOL` | `0.0015` | How near the band counts as a dip. |
| `DASHBOARD_HOST` / `DASHBOARD_PORT` | `127.0.0.1` / `8000` | Dashboard bind. |

---

## How to judge it (tomorrow, and beyond)

Watch each strategy's **equity vs $50** and its **profit factor** once it has
enough trades. The honest bar: profit factor > 1.3 with positive net over a
meaningful number of trades. Expect the scalp to bleed from costs (the backtest
predicted it) — watching that happen live is the lesson.

**Real money stays off the table** until a strategy earns it: paper → broker
testnet (fake money on the broker side) → tiny real size, each gated by results.
