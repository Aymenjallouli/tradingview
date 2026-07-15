# MT5 Algorithmic Trading System

An automated, **demo-only** trading system on a Pepperstone MetaTrader 5 account.
It runs **144 walk-forward-validated strategies** across 36 markets, sizes each
bet by its *measured* edge, protects every trade with data-derived stops, and
pushes every signal to Telegram. It runs on Windows directly, or 24/7 on a Linux
VPS under Wine.

> ⚠️ **DEMO ONLY.** The bridge refuses to start on a real account — a hard check
> with no override flag. Real trading is a future *manual* decision, never a
> config change. This is a forward-test to gather honest evidence, not a
> money-making machine (yet).

---

## The one honest truth about this system

**The edge is real, but thin: about +0.026R per trade after honest costs.**

That number is small on purpose — it's what survived every attempt to disprove
it. It is *not* a backtest fantasy. It survived the single test that kills most
retail systems: removing the look-ahead (see "Honest execution" below). But
because it's thin, two things matter far more than adding more strategies:

1. **Uptime** — a thin edge only pays across *many* trades. A bot that's alive
   15% of the time captures almost none of it. This is why the [VPS](vps/) exists.
2. **Capital** — the edge is a *percentage*. A percentage of a small account is
   a small number, and the broker's minimum lot locks a small account out of
   most markets (see "Account size" below).

Everything in this system is built around protecting that thin edge from being
eaten by costs, oversized bets, or bad stops.

---

## How the strategies were chosen (the methodology)

Most retail systems fail because their backtest lied. Ours were filtered by four
disciplines, each of which *removed* strategies:

1. **Walk-forward validation.** Every strategy was fit on older data and scored
   on newer, unseen data. Anything that only worked in-sample was cut. A high
   profit factor on a tiny sample is the signature of luck (the
   multiple-comparisons trap), not edge — those were cut too.

2. **Honest execution.** The backtest originally "bought" at the signal candle's
   *close* — a price you only know once the candle is over, so you could never
   actually trade it. We re-tested entering at the **next** candle's open, plus
   slippage and swap-as-a-cost. Over 19,399 trades the edge held (+0.032R →
   +0.032R): **it is not a look-ahead artifact.** 7 strategies that only worked
   at impossible prices were cut.

3. **Data-derived stops.** Every strategy was validated exiting on a *signal*
   with no stop. Bolting on a flat 2% stop fired during the very dip a
   mean-reversion trade is built to buy — turning winners into losses (it killed
   16% of trades, cut average PF from 1.53 to 1.32). Each strategy now uses a
   stop sized to its *own* measured adverse excursion (`strategy_stops.json`),
   2–10%, capped at 10%. Still always a broker-side stop — just the right width.

4. **Carry-trap removal.** Exotic pairs with huge overnight swap (USDTRY paid
   −5,323/night) were purged; positive swap is never counted as edge (the broker
   can revoke it any time).

Result: **144 strategies** — metals 10, forex 43, indices 65, crypto 6, energy
7, softs 13 — across 36 markets. See [STRATEGIES.md](STRATEGIES.md) for the full
list with per-strategy stats. The measured honest edge lives in
`strategy_quality.json`.

---

## The six books

The strategies are split into six independent "books," each its own process with
its own magic number and dashboard, so they never collide on the same account:

| Book | Magic | Port | Markets |
|------|-------|------|---------|
| METALS  | 770001 | 8801 | gold, silver, copper |
| FOREX   | 770002 | 8802 | EUR/GBP/JPY/AUD/CAD/CHF/NZD crosses |
| INDICES | 770003 | 8803 | US500, NAS100, GER40, JPN225, HK50, … |
| ENERGY  | 770004 | 8804 | crude, brent, natgas, gasoline |
| CRYPTO  | 770005 | 8805 | BTC, ETH |
| SOFTS   | 770006 | 8806 | coffee, cocoa, sugar, wheat, corn, … |

`run_all.py` launches all six under one **supervisor** — if a book crashes it's
relaunched within 15 seconds. A unified dashboard aggregates them at `:8800`
(`python mt5_hub.py`).

---

## Risk management (the rails that keep it alive)

Sizing is **by measured edge, not by conviction noise.** Agreement (several
strategies firing the same trade) was tested over 19,399 trades and predicts
nothing (t = −0.89). A strategy's *own past edge* predicts its future edge
(r = +0.43). So proven strategies size up, marginal ones size down.

Every one of these is always enforced:

| Rail | Limit | Why |
|------|-------|-----|
| **Kelly cap** | ≤ **2%** per trade | Above Kelly, long-run growth goes *negative* even while winning most trades. This is the line between compounding and ruin. |
| **Risk band** | 0.5–1.5% per trade | Edge-weighted inside the Kelly cap (half-Kelly, because we only *estimate* our win rate). |
| **Oversize guard** | skip if min-lot > 2% | A market whose *smallest* possible trade risks >2% is too big for the account — skipped, never forced. |
| **Correlation cap** | ≤ 4 positions / ≤ 4% per cluster | 12 "diversified" indices can secretly be one big risk-on bet. This is the rail the backtest can't see. |
| **Portfolio cap** | ≤ 20% total risk | Across all six books combined. |
| **Per-book cap** | ≤ 12 positions/book | More *uncorrelated* positions, not bigger bets. |
| **Daily breaker** | −5% in a day → stop | Blocks new entries till tomorrow; open trades keep their SL/TP. |
| **Broker-side SL+TP** | on every order | Protection survives a script crash or power loss. |

---

## Account size — why it decides everything

The broker sets a **minimum lot size** you cannot trade below. If that minimum
risks more than 2% of your account, that market is off-limits — you literally
can't bet smaller. So account size decides how much of the system you can run:

| Balance | Tradeable markets | Notes |
|---------|-------------------|-------|
| $1,000 | ~15% | 85% of markets priced out; forced to ~1.4%/trade |
| $2,000 | ~40% | Roughly half the engine |
| $3,500 | ~64% | Most markets |
| **$6,500 (current)** | **~100%** | **Full engine — every market fits under 2%** |

At the **current ~$6,500 real balance, the whole engine runs with no oversized
bets** — gold, indices and all. `MT5_VIRTUAL_EQUITY` can simulate a smaller
account faithfully (it makes the guards judge risk against the virtual size), but
it's currently `0` = trade the real balance.

Honest forecast at $6,500 running 24/7, after correlation and live-decay
haircuts: **roughly +5%/month.** This is a *forecast*, not a promise — the only
proof is live evidence, which needs uptime.

---

## Confidence score (on every signal)

Each signal carries a 0–100 confidence built from three honest inputs:

```
confidence = (0.55 × edge_strength  +  0.45 × win_rate)  ×  sample_trust
   win_score    = (win% − 50) / 35, clamped 0..1     (50% → 0, 85% → 1)
   sample_trust = 0.75 + 0.25 × min(1, n / 60)       (small samples discounted)
```

Every signal also shows the raw numbers behind the score — out-of-sample win
rate, measured edge in R, and sample size — so it's transparent, not a black
box. Unmeasured (trend) strategies honestly show 50/AVERAGE rather than a faked
number. This is separate from the *sizing* score, which uses edge rank alone.

---

## Telegram signals

Every signal is pushed to Telegram (once per candle, no spam):

- **✅ Taken** — trades the account actually opened, with confidence, track
  record, and real "if TP hit / if SL hit" dollar amounts.
- **👀 Watchlist** — signals the account *skipped* (e.g. min-lot too big for the
  simulated size), still real setups a larger account could take.
- **❌ Closes** — wins *and* losses, honestly.

Setup: create a bot via **@BotFather**, then add to `live/mt5/.env` (gitignored,
never committed):

```
MT5_TG_TOKEN=123456:ABC...
MT5_TG_CHAT=@your_channel      # or a numeric chat id
```

> ⚠️ Selling paid signals is regulated financial advice in most countries. Run
> the channel **free** first to build a public, honest track record. Every
> message carries a demo / not-financial-advice disclaimer.

---

## Running it — Windows (local)

One-time MT5 setup:
1. Open MT5, log into the **demo** account.
2. **Tools → Options → Expert Advisors → "Allow algorithmic trading"** → OK.
3. Click the toolbar **"Algo Trading"** button so it's **green**.

Then:
```bash
cd live/mt5
python run_all.py          # all six books, supervised
python mt5_hub.py          # unified dashboard at http://localhost:8800
```

The launcher also sets the machine to not sleep on AC / lid-close, but a laptop
is not a reliable 24/7 host — for that, use the VPS.

## Running it — Ubuntu VPS (24/7)

The MT5 Python API is Windows-only, but it runs on Linux under **Wine**. The full
staged deployment (Wine + a headless MT5 terminal + the supervised books, as a
systemd service that survives reboots) is in **[vps/README.md](vps/README.md)** —
six self-verifying scripts you run over SSH.

> **One bot per account.** The VPS and the laptop both log into the same demo
> account, so run only **one** at a time — two would double-trade. When the VPS
> is live, stop the laptop.

---

## Monitoring — are we making money?

```bash
python mt5_audit.py          # the honest scorecard from broker records
python mt5_audit.py --strats # per-strategy P&L (who earns, who bleeds)
```

The audit reads the broker's own closed-deal history (the only source of truth):
net P&L, win rate, profit factor, expectancy, max drawdown, worst streak, and a
blunt verdict on whether the live edge is holding vs the backtest. A strategy
that loses money live gets cut, whatever its backtest said.

---

## Key files

| File | Role |
|------|------|
| `run_all.py` | Launches + supervises the six books |
| `mt5_bridge.py` | Connect (demo guard), symbol mapping, candles/ticks |
| `mt5_orchestrator.py` | Strategies, all risk rails, execution, signal notify |
| `mt5_strategies.py` | The 22 strategy classes + validated-book builder |
| `mt5_orders.py` | Market orders + SL/TP, close, risk-lot sizing |
| `mt5_conviction.py` | Edge-based sizing + the confidence calculation |
| `mt5_stops.py` | Data-derived stop per strategy-market |
| `mt5_correlation.py` | The correlation cap (rolling real correlation) |
| `mt5_telegram.py` | Signal / close cards to Telegram |
| `mt5_audit.py` | The honest "are we making money?" scorecard |
| `mt5_hub.py` | Unified dashboard across all six books |
| `validated_strategies.json` | The 144 validated strategies |
| `strategy_stops.json` | Per-strategy data-derived stops |
| `strategy_quality.json` | Per-strategy measured honest edge (R) |
| `STRATEGIES.md` | Full documented strategy library |
| `vps/` | The 24/7 Ubuntu deployment suite |
