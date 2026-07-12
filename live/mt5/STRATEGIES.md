# Validated Strategy Library

Every strategy below passed a **strict walk-forward test**: split each
market history in half, and the strategy had to win on the recent half it
had never seen, with **OOS Profit Factor >= 1.3 and >= 50 out-of-sample
trades** (enough data to trust, not luck). Costs (spread) are included.

- **PF (Profit Factor)** = gross profit / gross loss. >1 = profitable. 2.0 = makes $2 per $1 lost.
- **OOS** = out-of-sample (the unseen half — the honest test).
- **Win%** = share of winning trades. (Trend strategies win less but win BIG.)
- **Trd/mo** = approx trades per month.

**Total: 29 validated strategies, ~67 trades/month combined (~2.2/day).**

## The methods

- **CryptoTrend** — Donchian 20-bar-high breakout ridden with a WIDE 5xATR trailing stop. Trend-following: cut losers, let winners run.
- **DonchTrend** — Donchian 20-bar-high breakout with a 4xATR trailing stop. Trend-following, low win rate but big payoff.
- **Keltner** — Buys when price dips below the lower Keltner band (EMA20 - 2xATR) then closes back inside; exits at the mid (EMA20). A volatility-band mean-reversion.
- **RangeRSI** — Buys RSI(14)<30 ONLY when price is ranging (near its 50-EMA); exits RSI>55. Range mean-reversion with a trend filter.
- **Stochastic** — Buys when Stochastic %K < 20 (oversold), exits when %K > 80 (overbought). Classic momentum-oscillator mean-reversion.
- **WilliamsR** — Buys when Williams %R < -90 (deep oversold), exits > -30. Similar to stochastic, catches extreme dips.

## METALS (4 strategies)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| XAUUSD | DonchTrend | 4h | **2.64** | 54 | 50% | 1.2 |
| XAUUSD | DonchTrend | 1h | **1.81** | 55 | 49% | 4.7 |
| XAGUSD | DonchTrend | 4h | **1.73** | 61 | 48% | 1.2 |
| XAUUSD | RangeRSI | 1h | **1.68** | 82 | 76% | 6.5 |

## FOREX (7 strategies)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| AUDUSD | RangeRSI | 1h | **2.1** | 77 | 71% | 6.5 |
| AUDUSD | Keltner | 1h | **1.93** | 64 | 67% | 5.2 |
| EURJPY | WilliamsR | 4h | **1.82** | 137 | 74% | 2.9 |
| EURJPY | Keltner | 4h | **1.76** | 60 | 82% | 1.3 |
| EURJPY | RangeRSI | 4h | **1.7** | 88 | 75% | 1.7 |
| GBPUSD | Keltner | 4h | **1.46** | 73 | 73% | 1.5 |
| USDCAD | Stochastic | 4h | **1.39** | 147 | 68% | 3.2 |

## INDICES (15 strategies)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| US100 | Keltner | 4h | **2.5** | 81 | 72% | 1.6 |
| US100 | RangeRSI | 4h | **2.31** | 79 | 75% | 1.6 |
| US500 | DonchTrend | 4h | **2.11** | 64 | 48% | 1.3 |
| US500 | WilliamsR | 4h | **1.96** | 143 | 72% | 2.8 |
| GER40 | DonchTrend | 4h | **1.94** | 61 | 39% | 1.3 |
| US100 | WilliamsR | 4h | **1.91** | 142 | 73% | 2.9 |
| GER40 | Keltner | 4h | **1.91** | 69 | 75% | 1.6 |
| US500 | RangeRSI | 4h | **1.9** | 75 | 72% | 1.6 |
| GER40 | CryptoTrend | 4h | **1.84** | 50 | 40% | 1.0 |
| US500 | Keltner | 4h | **1.83** | 75 | 69% | 1.5 |
| US500 | Stochastic | 4h | **1.81** | 149 | 73% | 3.1 |
| US500 | CryptoTrend | 4h | **1.79** | 58 | 48% | 1.1 |
| US100 | Stochastic | 4h | **1.74** | 147 | 71% | 3.0 |
| US100 | CryptoTrend | 4h | **1.72** | 59 | 42% | 1.2 |
| US100 | DonchTrend | 4h | **1.51** | 72 | 44% | 1.5 |

## ENERGY (1 strategies)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| NATGAS | DonchTrend | 4h | **1.34** | 65 | 38% | 1.4 |

## CRYPTO (2 strategies)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| ETHUSD | DonchTrend | 4h | **1.39** | 55 | 29% | 1.2 |
| BTCUSD | DonchTrend | 4h | **1.34** | 61 | 38% | 1.2 |
