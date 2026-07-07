# Real-Time Multi-Strategy Trading & Research Platform

A production-grade, 24/7 **paper-trading and quantitative-research platform** for
crypto and forex. It runs multiple strategies side by side on live market data,
backtests them honestly, monitors cross-exchange arbitrage, and uses AI (Claude)
for live commentary — all viewable from a real-time web dashboard, deployable to
any VPS.

**Built entirely in Python + vanilla JS. No paid data feeds, no API keys for
market data, no frameworks bloat.**

> This is a research platform, not financial advice. All trading is simulated
> (paper money). It was built to answer a real question — *can a small retail
> trader actually beat the market?* — with data instead of hype. The honest
> answer, documented here with backtests and academic sources, is mostly "no,"
> and the platform proves it live.

---

## What it does

| Capability | Detail |
|---|---|
| **Real-time engine** | Event-driven, reacts to Binance WebSocket candle closes (no polling). Tick-level exit checks. |
| **Multiple strategies** | Trend (4h EMA), forex swing (5m), and a **smart grid** that scans ~100 coins and grids the most range-bound ones. Each has its own paper account. |
| **Honest backtesting** | Every strategy is backtested with realistic fees (0.1%/side) + slippage before going live. Includes crash scenarios, not just the happy path. |
| **Cross-exchange arb monitor** | Live Binance/Coinbase/Kraken spread comparison with a strict latency + cost model. A "guaranteed-money detector" that proves arbitrage doesn't survive costs for retail. |
| **AI commentary** | Claude (via the Claude Code CLI) reads live metrics every few minutes and explains what's happening in plain language. |
| **Real-time dashboard** | Single-page web UI, live via Server-Sent Events with a polling fallback (works through proxies/tunnels). Phone-friendly. |
| **VPS-ready** | Docker, docker-compose, systemd, and pm2 configs included. Runs 24/7, survives reboots, data persists. |

---

## Architecture

```
Binance WebSocket ─┐
Binance REST ──────┤
yfinance (forex) ──┼──► engine.py ──► strategies ──► MultiBroker (SQLite)
Coinbase/Kraken ───┘         │                              │
                             ├──► smart_grid.py             │
                             ├──► arb_monitor.py            │
                             └──► claude_helper.py          │
                                          │                 │
                                   app.py (FastAPI) ◄───────┘
                                          │
                                   SSE / polling
                                          │
                                   index.html (live dashboard)
```

- **`engine.py`** — real-time multi-strategy, multi-feed engine
- **`strategy.py`** — pluggable strategies (one source of truth for backtest + live)
- **`smart_grid.py`** — grid trading on auto-selected ranging coins
- **`arb_monitor.py`** — honest cross-exchange arbitrage experiment
- **`broker.py`** — multi-account paper broker with realistic cost modeling
- **`claude_helper.py`** — AI live commentary via the Claude CLI
- **`app.py`** — FastAPI server (SSE stream, REST, health checks)
- **`index.html`** — real-time dashboard (no build step, no CDN)

---

## Run it

```bash
cd live
pip install -r requirements.txt
python app.py
# open http://localhost:8000
```

Deploy to a VPS with Docker (`docker compose up -d --build`), systemd, or pm2 —
see [live/DEPLOY_TONIGHT.md](live/DEPLOY_TONIGHT.md).

---

## The research behind it

This project didn't assume strategies work — it tested them and followed the
evidence. Backtested and documented findings (with academic sources):

- **Simple indicator strategies** (EMA/RSI/Bollinger) don't beat costs — a study
  of 7,846 rules over 114 years of Dow data found no edge net of costs.
- **Scalping is structurally dead for retail** — proven live here (0% win rate
  even at 0% fees) and in the HFT literature (races won in microseconds).
- **Cross-exchange arbitrage** doesn't survive costs + transfer time + the speed
  race — the arb monitor demonstrates this live (hundreds of raw gaps, zero
  survive).
- **Grid trading** is the one strategy that showed a real, repeatable edge in
  backtests (beat buy-and-hold on 8/10 coins) — because it profits from
  volatility, not prediction. Modest returns, real risk (bagging in downtrends).

The honest conclusion, backed by data: retail edges are thin, slow, and modest;
the value here is the *engineering* and the *rigor*, not a money machine.

---

## Tech stack

Python 3.10+ · FastAPI · WebSockets · SQLite · pandas · vanilla JS/SSE ·
Docker · pm2 · Claude AI integration
