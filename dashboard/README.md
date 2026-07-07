# Web Dashboard

One local control panel for all three paper-trading experiments — the trend
system, the crypto scalper, and the forex experiment. Run backtests, start/stop
the live paper traders, and watch equity, positions, trades, and **real-time
prices** — all from your browser.

**Paper money only. Real market data.** Prices stream live from Binance's public
WebSocket (real ticks, no API key). Your open paper positions are marked to
market in real time, so equity moves with the actual market — but every order is
still simulated. No broker, no real funds, no risk.

---

## Run it

From the project root:

```bash
pip install -r requirements.txt          # once
cd dashboard
python server.py
```

Then open **http://localhost:8000** in your browser.

It binds to `127.0.0.1` (your machine only) — nothing is exposed to the internet.

---

## What you can do

**Live price ticker (top):** BTC / ETH / SOL streaming in real time from
Binance. Green/red flashes show up/down ticks. The badge shows feed status.

**System cards (one per experiment):** live mark-to-market equity, net P&L,
cash, open positions, unrealized P&L, cost paid, and a mini equity curve.

**Live & backtests panel:** every runnable task as a tab. For each:
- **Run/Start** — launches the script (backtest, optimizer, or live trader).
- **Stop** — stops a running live trader.
- The output log tails live below the buttons.

Runnable tasks:

| Task | What it does |
|------|--------------|
| `trend_backtest` / `trend_optimize` | Backtest / optimize the trend system |
| `trend_signals` | Run one 4h signal check |
| `scalp_backtest` | Crypto scalp backtest (with vs without costs) |
| `scalp_live` | **Live** crypto paper scalper (60s poll, −25% halt) |
| `forex_backtest_both/scalp/swing` | Forex backtests |
| `forex_optimize` | Forex parameter sweep |
| `forex_live_swing` / `forex_live_scalp` | **Live** forex paper traders |

**Recent trades table:** the latest closed trades across all three systems,
newest first.

---

## How the realtime works (no polling)

- The browser opens **one** Server-Sent Events connection (`/api/stream`).
- The server **pushes** an update whenever equity, trades, task status, or a
  live price changes — plus a heartbeat every few seconds.
- The live price feed (`price_feed.py`) runs a background WebSocket to Binance
  and keeps the latest real price for each symbol in memory.

So the dashboard itself is fully event-driven. Note the *strategies* still act
on their own cadence (trend on 4h closes, live traders on 60s polls) — the
dashboard shows their state in real time, but a 60s-poll strategy won't create
sub-second trade events. Real-time *prices* update continuously; real-time
*trades* happen as fast as each strategy trades.

---

## Files

| File | What it is |
|------|-----------|
| `server.py` | FastAPI backend: data, task control, SSE stream, live prices. |
| `db_reader.py` | Read-only access to all three ledgers (never writes). |
| `process_manager.py` | Launches/stops scripts as subprocesses, tails logs. |
| `price_feed.py` | Live Binance WebSocket price feed (real ticks, no key). |
| `index.html` | The single-page dashboard UI (no build step, no CDN). |

---

## Roadmap: connecting a REAL broker (do this LAST, carefully)

You asked to eventually run real trades through a real platform. Here's the
honest, safe path — and why we're not there yet.

### Why not yet

The backtests currently show these strategies **mostly fail** their success
criteria (trend clears 1.3 profit factor but trails buy-and-hold; both scalpers
fail with costs). **Connecting real money to a strategy that fails on paper is
how you lose money.** The whole point of this project is to test with fake money
*until the numbers earn the right* to risk real money.

### The staged path (each stage gates the next)

1. **Real data, paper orders** ✅ *(you are here)* — real prices stream in,
   orders are simulated. Let the live traders run for weeks. Collect real
   out-of-sample results.
2. **Broker testnet/sandbox** — connect a real broker API in its *fake-money*
   mode (Binance **Spot Testnet**, or **Alpaca Paper** for stocks/forex). Same
   code path as real orders, but no real funds. This proves the order plumbing
   works. Requires you to create a testnet account and API keys.
3. **Real money, tiny size** — only if stages 1–2 pass the success criteria over
   a meaningful sample. Start with the smallest size the broker allows, with
   hard risk limits and a kill switch.

### What stage 2 would need (when you're ready)

- A broker with a free API + testnet. Good beginner options:
  - **Alpaca** — US stocks + crypto, excellent paper-trading API, free keys.
  - **Binance Spot Testnet** — crypto, matches the scalper's symbols.
- An `execution/` module with one interface (`place_order`, `get_position`,
  `cancel`) and two backends: `PaperExecutor` (what we have now) and
  `BrokerExecutor` (calls the real API). The strategies wouldn't change — only
  which executor they're handed.
- Safeguards baked in: max position size, max daily loss, a global kill switch,
  and confirmation that you're pointed at *testnet* before any real endpoint.

Tell me when your paper results justify stage 2, and I'll build the executor
abstraction and wire in Alpaca Paper or Binance Testnet. Not before — that's the
responsible order to do this in.
```
