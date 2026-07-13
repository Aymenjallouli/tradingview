# Validated Strategy Library

Every strategy passed a **strict walk-forward test**: trained on the older half of
history, then had to WIN on the recent half it had never seen, with **OOS Profit
Factor >= 1.3 and >= 50 out-of-sample trades**. Spread costs included.

**50 validated strategies across 23 markets — ~150 trades/month (~5.0/day).**

⚠️ **Not guaranteed.** These are *edges* (profitable on average over many trades),
not sure things. Individual trades lose. Losing streaks of 10+ are possible.
Risk is capped at 1-2% per trade so the edge survives the streaks.

## The methods

- **CryptoTrend** — Donchian 20-bar-high breakout ridden with a wide 5xATR trailing stop. Trend-following.
- **DonchTrend** — Donchian 20-bar-high breakout with a 4xATR trailing stop. Trend-following: cut losers, let winners run. Low win rate, big payoff.
- **Keltner** — Buys when price dips below the lower Keltner band (EMA20 - 2xATR) then closes back inside; exits at the mid (EMA20). Volatility-band mean-reversion.
- **RangeRSI** — Buys RSI(14)<30 ONLY when price is ranging (near its 50-EMA); exits RSI>55. Range mean-reversion with a trend filter.
- **Stochastic** — Buys Stochastic %K<20 (oversold), exits %K>80. Oscillator mean-reversion.
- **WilliamsR** — Buys Williams %R < -90 (deep oversold), exits > -30. Catches extreme dips.

## INDICES — 27 strategies (~84 trades/mo)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| JPN225 | DonchTrend | 4h | **2.56** | 60 | 50% | 1.2 |
| US100 | Keltner | 4h | **2.5** | 81 | 72% | 1.6 |
| US100 | RangeRSI | 4h | **2.31** | 79 | 75% | 1.6 |
| AUS200 | Keltner | 4h | **2.2** | 74 | 74% | 1.4 |
| US500 | DonchTrend | 4h | **2.11** | 64 | 48% | 1.3 |
| US500 | WilliamsR | 4h | **1.96** | 143 | 72% | 2.8 |
| GER40 | DonchTrend | 4h | **1.94** | 61 | 39% | 1.3 |
| US100 | WilliamsR | 4h | **1.91** | 142 | 73% | 2.9 |
| GER40 | Keltner | 4h | **1.91** | 69 | 75% | 1.6 |
| US500 | RangeRSI | 4h | **1.9** | 75 | 72% | 1.6 |
| GER40 | CryptoTrend | 4h | **1.84** | 50 | 40% | 1.0 |
| US500 | Keltner | 4h | **1.83** | 75 | 69% | 1.5 |
| JPN225 | Keltner | 4h | **1.83** | 59 | 71% | 1.4 |
| US500 | Stochastic | 4h | **1.81** | 149 | 73% | 3.1 |
| US500 | CryptoTrend | 4h | **1.79** | 58 | 48% | 1.1 |
| US100 | Stochastic | 4h | **1.74** | 147 | 71% | 3.0 |
| US100 | CryptoTrend | 4h | **1.72** | 59 | 42% | 1.2 |
| US30 | WilliamsR | 4h | **1.68** | 139 | 73% | 2.9 |
| UK100 | WilliamsR | 1h | **1.66** | 158 | 74% | 12.9 |
| UK100 | Stochastic | 1h | **1.61** | 158 | 74% | 13.2 |
| US30 | DonchTrend | 4h | **1.55** | 64 | 44% | 1.3 |
| US100 | DonchTrend | 4h | **1.51** | 72 | 44% | 1.5 |
| UK100 | Stochastic | 4h | **1.48** | 152 | 74% | 3.2 |
| JPN225 | WilliamsR | 4h | **1.44** | 144 | 72% | 3.0 |
| JPN225 | Stochastic | 1h | **1.42** | 146 | 64% | 12.3 |
| AUS200 | Stochastic | 4h | **1.39** | 158 | 72% | 3.2 |
| US30 | Keltner | 4h | **1.37** | 68 | 68% | 1.4 |

## FOREX — 12 strategies (~34 trades/mo)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| AUDUSD | RangeRSI | 1h | **2.1** | 77 | 71% | 6.5 |
| AUDUSD | Keltner | 1h | **1.93** | 64 | 67% | 5.2 |
| EURJPY | WilliamsR | 4h | **1.82** | 137 | 74% | 2.9 |
| EURJPY | Keltner | 4h | **1.76** | 60 | 82% | 1.3 |
| EURJPY | RangeRSI | 4h | **1.7** | 88 | 75% | 1.7 |
| GBPUSD | Keltner | 4h | **1.46** | 73 | 73% | 1.5 |
| USDCAD | Stochastic | 4h | **1.39** | 147 | 68% | 3.2 |
| USDNOK | Stochastic | 4h | **1.38** | 152 | 70% | 3.1 |
| EURGBP | WilliamsR | 4h | **1.35** | 145 | 63% | 3.0 |
| NZDUSD | RangeRSI | 4h | **1.35** | 70 | 64% | 1.5 |
| EURGBP | Stochastic | 4h | **1.33** | 147 | 63% | 3.1 |
| GBPJPY | Keltner | 4h | **1.33** | 58 | 74% | 1.3 |

## METALS — 5 strategies (~15 trades/mo)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| XAUUSD | DonchTrend | 4h | **2.64** | 54 | 50% | 1.2 |
| XAUUSD | DonchTrend | 1h | **1.81** | 55 | 49% | 4.7 |
| XAGUSD | DonchTrend | 4h | **1.74** | 61 | 48% | 1.2 |
| XAGUSD | DonchTrend | 4h | **1.73** | 61 | 48% | 1.2 |
| XAUUSD | RangeRSI | 1h | **1.68** | 82 | 76% | 6.5 |

## ENERGY — 2 strategies (~8 trades/mo)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| NATGAS | DonchTrend | 4h | **1.34** | 65 | 38% | 1.4 |
| BRENT | Keltner | 1h | **1.34** | 66 | 68% | 6.1 |

## CRYPTO — 2 strategies (~2 trades/mo)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| ETHUSD | DonchTrend | 4h | **1.39** | 55 | 29% | 1.2 |
| BTCUSD | DonchTrend | 4h | **1.34** | 61 | 38% | 1.2 |

## SOFTS — 2 strategies (~7 trades/mo)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| COFFEE | RangeRSI | 4h | **1.6** | 50 | 70% | 1.5 |
| COCOA | DonchTrend | 1h | **1.59** | 56 | 43% | 5.2 |
