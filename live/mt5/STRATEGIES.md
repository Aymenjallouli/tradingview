# Validated Strategy Library

Every strategy passed a **strict walk-forward test** (trained on the older half of
history, then had to WIN on the unseen recent half) with **OOS Profit Factor >= 1.3**
and **>= 50 out-of-sample trades**. Spread costs included.

**80 strategies · 31 markets · 9 methods · ~248 trades/month (~8.3/day)**

⚠️ **Not guaranteed.** These are edges (profitable on average), not sure things.
Individual trades lose; 10+ losing streaks happen. Risk capped 1-2%/trade.

❌ **Excluded on purpose:** exotic carry-trade pairs (USDTRY, USDZAR, USDBRL...)
showed huge backtest PFs but bleed massive overnight SWAP costs — fantasy edges.

## Methods

- **Aroon** — Buy when AroonUp>70 & AroonDown<30 (strong uptrend starting).
- **CCI** — Buy CCI(20) < -150 (extreme oversold), exit > +100.
- **CryptoTrend** — Donchian breakout + wide 5xATR trailing stop. Trend-following.
- **DonchTrend** — Donchian 20-bar-high breakout + 4xATR trailing stop. Cut losers, let winners run.
- **Keltner** — Buy the dip below the lower Keltner band (EMA20 - 2xATR), exit at the mid. Volatility-band mean-reversion.
- **RangeRSI** — Buy RSI(14)<30 ONLY when ranging (near 50-EMA); exit RSI>55.
- **Stochastic** — Buy %K<20 (oversold), exit %K>80.
- **Supertrend** — ATR bands that flip with trend. Buy the flip up, exit the flip down.
- **WilliamsR** — Buy Williams %R < -90 (deep oversold), exit > -30.

## INDICES — 38 strategies (~122 trd/mo)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| NAS100 | Keltner | 4h | **2.58** | 81 | 72% | 1.6 |
| JPN225 | DonchTrend | 4h | **2.56** | 60 | 50% | 1.2 |
| US100 | Keltner | 4h | **2.5** | 81 | 72% | 1.6 |
| NAS100 | RangeRSI | 4h | **2.37** | 79 | 75% | 1.6 |
| US100 | RangeRSI | 4h | **2.31** | 79 | 75% | 1.6 |
| AUS200 | Keltner | 4h | **2.2** | 74 | 74% | 1.4 |
| US500 | DonchTrend | 4h | **2.11** | 64 | 48% | 1.3 |
| US500 | WilliamsR | 4h | **1.96** | 143 | 72% | 2.8 |
| NAS100 | WilliamsR | 4h | **1.95** | 142 | 73% | 2.9 |
| GER40 | DonchTrend | 4h | **1.94** | 61 | 39% | 1.3 |
| US100 | WilliamsR | 4h | **1.91** | 142 | 73% | 2.9 |
| GER40 | Keltner | 4h | **1.91** | 69 | 75% | 1.6 |
| US500 | RangeRSI | 4h | **1.9** | 75 | 72% | 1.6 |
| GER40 | CryptoTrend | 4h | **1.84** | 50 | 40% | 1.0 |
| US500 | Keltner | 4h | **1.83** | 75 | 69% | 1.5 |
| JPN225 | Keltner | 4h | **1.83** | 59 | 71% | 1.4 |
| US500 | Stochastic | 4h | **1.81** | 149 | 73% | 3.1 |
| NAS100 | CCI | 4h | **1.8** | 87 | 75% | 1.8 |
| US500 | CryptoTrend | 4h | **1.79** | 58 | 48% | 1.1 |
| NAS100 | Stochastic | 4h | **1.77** | 147 | 71% | 3.0 |
| US100 | Stochastic | 4h | **1.74** | 147 | 71% | 3.0 |
| US100 | CryptoTrend | 4h | **1.72** | 59 | 42% | 1.2 |
| US30 | WilliamsR | 4h | **1.68** | 139 | 73% | 2.9 |
| UK100 | WilliamsR | 1h | **1.66** | 158 | 74% | 12.9 |
| NAS100 | CCI | 1h | **1.62** | 103 | 73% | 8.7 |
| UK100 | Stochastic | 1h | **1.61** | 158 | 74% | 13.2 |
| US30 | DonchTrend | 4h | **1.55** | 64 | 44% | 1.3 |
| NAS100 | DonchTrend | 4h | **1.53** | 72 | 46% | 1.5 |
| US100 | DonchTrend | 4h | **1.51** | 72 | 44% | 1.5 |
| UK100 | Stochastic | 4h | **1.48** | 152 | 74% | 3.2 |
| HK50 | DonchTrend | 1h | **1.46** | 60 | 50% | 5.2 |
| JPN225 | WilliamsR | 4h | **1.44** | 144 | 72% | 3.0 |
| JPN225 | Stochastic | 1h | **1.42** | 146 | 64% | 12.3 |
| HK50 | Supertrend | 1h | **1.42** | 88 | 49% | 7.5 |
| NAS100 | Supertrend | 4h | **1.42** | 95 | 42% | 1.9 |
| AUS200 | Stochastic | 4h | **1.39** | 158 | 72% | 3.2 |
| US30 | Keltner | 4h | **1.37** | 68 | 68% | 1.4 |
| NAS100 | Aroon | 4h | **1.36** | 104 | 51% | 2.2 |

## FOREX — 24 strategies (~68 trd/mo)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| CHFJPY | CCI | 4h | **3.17** | 88 | 76% | 1.8 |
| CHFJPY | Keltner | 4h | **2.41** | 57 | 74% | 1.1 |
| USDCNH | RangeRSI | 4h | **2.11** | 74 | 76% | 1.4 |
| AUDUSD | RangeRSI | 1h | **2.1** | 77 | 71% | 6.5 |
| CHFJPY | WilliamsR | 4h | **1.96** | 138 | 72% | 2.8 |
| AUDUSD | Keltner | 1h | **1.93** | 64 | 67% | 5.2 |
| EURAUD | RangeRSI | 4h | **1.92** | 74 | 73% | 1.6 |
| EURJPY | WilliamsR | 4h | **1.82** | 137 | 74% | 2.9 |
| EURJPY | Keltner | 4h | **1.76** | 60 | 82% | 1.3 |
| EURCAD | CCI | 4h | **1.75** | 81 | 67% | 1.9 |
| CHFJPY | DonchTrend | 1h | **1.72** | 55 | 47% | 4.6 |
| EURJPY | RangeRSI | 4h | **1.7** | 88 | 75% | 1.7 |
| EURCAD | WilliamsR | 4h | **1.59** | 132 | 65% | 3.0 |
| CADJPY | Keltner | 1h | **1.54** | 67 | 66% | 5.7 |
| GBPUSD | Keltner | 4h | **1.46** | 73 | 73% | 1.5 |
| EURCHF | Keltner | 4h | **1.43** | 59 | 75% | 1.3 |
| USDCAD | Stochastic | 4h | **1.39** | 147 | 68% | 3.2 |
| USDNOK | Stochastic | 4h | **1.38** | 152 | 70% | 3.1 |
| EURGBP | WilliamsR | 4h | **1.35** | 145 | 63% | 3.0 |
| NZDUSD | RangeRSI | 4h | **1.35** | 70 | 64% | 1.5 |
| EURCHF | Keltner | 1h | **1.35** | 63 | 67% | 5.3 |
| EURGBP | Stochastic | 4h | **1.33** | 147 | 63% | 3.1 |
| GBPJPY | Keltner | 4h | **1.33** | 58 | 74% | 1.3 |
| EURCAD | Stochastic | 4h | **1.3** | 133 | 63% | 3.1 |

## SOFTS — 7 strategies (~26 trd/mo)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| COCOA | Supertrend | 4h | **1.88** | 75 | 40% | 2.2 |
| COCOA | Aroon | 4h | **1.62** | 79 | 46% | 2.3 |
| COFFEE | RangeRSI | 4h | **1.6** | 50 | 70% | 1.5 |
| COFFEE | RangeRSI | 4h | **1.6** | 50 | 70% | 1.5 |
| COCOA | DonchTrend | 1h | **1.59** | 56 | 43% | 5.2 |
| COCOA | DonchTrend | 1h | **1.59** | 56 | 43% | 5.2 |
| COCOA | Supertrend | 1h | **1.34** | 87 | 44% | 7.8 |

## METALS — 5 strategies (~15 trd/mo)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| XAUUSD | DonchTrend | 4h | **2.64** | 54 | 50% | 1.2 |
| XAUUSD | DonchTrend | 1h | **1.81** | 55 | 49% | 4.7 |
| XAGUSD | DonchTrend | 4h | **1.74** | 61 | 48% | 1.2 |
| XAGUSD | DonchTrend | 4h | **1.73** | 61 | 48% | 1.2 |
| XAUUSD | RangeRSI | 1h | **1.68** | 82 | 76% | 6.5 |

## ENERGY — 4 strategies (~15 trd/mo)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| NATGAS | DonchTrend | 4h | **1.34** | 65 | 38% | 1.4 |
| BRENT | Keltner | 1h | **1.34** | 66 | 68% | 6.1 |
| BRENT | Keltner | 1h | **1.34** | 66 | 68% | 6.1 |
| NATGAS | DonchTrend | 4h | **1.34** | 65 | 38% | 1.4 |

## CRYPTO — 2 strategies (~2 trd/mo)

| Symbol | Method | TF | OOS PF | OOS trades | Win% | Trd/mo |
|--------|--------|----|--------|-----------|------|--------|
| ETHUSD | DonchTrend | 4h | **1.39** | 55 | 29% | 1.2 |
| BTCUSD | DonchTrend | 4h | **1.34** | 61 | 38% | 1.2 |
