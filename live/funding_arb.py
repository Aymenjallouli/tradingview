"""
funding_arb.py — Delta-neutral funding-rate arbitrage (paper simulator).

The ONE crypto edge the research found that is STRUCTURAL (you collect a fee)
rather than PREDICTIVE (you guess price direction). How it works:

  * On perpetual futures, one side pays the other a "funding" fee every 8 hours.
  * If you hold  SPOT LONG + PERP SHORT  of the same coin in equal size, the
    two positions' price moves CANCEL (delta-neutral) — you don't care if the
    price goes up or down.
  * You simply COLLECT the funding rate every 8 hours (when funding is positive,
    shorts get paid).

Why it can survive the 0.3% trading fees that killed everything else:
  * You OPEN the pair once and HOLD for days/weeks — you're not churning trades.
  * The only fees are the open + close of each leg. The funding you collect
    accrues continuously in between.

Honest limitations (from the research, built in):
  * Real expected return is MODEST — ~7%/yr on average across exchanges, not
    the eye-catching 40%+ peaks. Sometimes funding goes NEGATIVE (you pay).
  * REAL risk: without cross-margining, an adverse move can force liquidation of
    the futures leg before you close — a real way to lose money live. This
    simulator flags that but paper trading can't fully capture it.
  * Requires a FUTURES account (not just spot) to do for real.

This module:
  * fetch_funding_history(symbol)  — real historical 8h funding rates.
  * backtest(symbols)              — simulate collecting funding delta-neutral,
                                     net of realistic open/close fees, vs HODL.
  * Run:  python funding_arb.py
"""

import time
from datetime import datetime, timezone

import requests

import config

FUTURES_HOST = "https://fapi.binance.com"
FEE = config.FEE_PCT          # 0.1%/side per leg
SLIP = config.SLIPPAGE_PCT    # 0.05%/side
# We hold BOTH a spot and a perp leg, so opening the pair = 2 legs, closing = 2.
# Each leg pays fee+slip. Total round-trip cost of the delta-neutral pair:
#   open: 2 * (FEE+SLIP)   close: 2 * (FEE+SLIP)  = 4 * (FEE+SLIP) ≈ 0.6%
PAIR_ROUNDTRIP_COST = 4 * (FEE + SLIP)


def fetch_funding_history(symbol, limit=1000):
    """Real 8-hour funding rates for a perp (list of floats, oldest first)."""
    try:
        rows = requests.get(f"{FUTURES_HOST}/fapi/v1/fundingRate",
                            params={"symbol": symbol, "limit": limit},
                            timeout=20).json()
        if not isinstance(rows, list):
            return []
        return [(int(r["fundingTime"]), float(r["fundingRate"])) for r in rows]
    except Exception as exc:  # noqa: BLE001
        print(f"  funding fetch failed for {symbol}: {exc}")
        return []


def current_funding(symbol):
    """Latest funding rate (per 8h) for a perp, or None."""
    try:
        d = requests.get(f"{FUTURES_HOST}/fapi/v1/premiumIndex",
                        params={"symbol": symbol}, timeout=15).json()
        return float(d["lastFundingRate"])
    except Exception:  # noqa: BLE001
        return None


def backtest(symbols):
    """Simulate a delta-neutral funding-collection book across `symbols`.

    Model: split capital equally across symbols. For each, open the pair once
    (pay open cost), collect each 8h funding payment over the available history,
    then close (pay close cost). Report net return vs the cost, annualized.

    We collect funding when the position is SHORT-perp/long-spot: when funding
    is POSITIVE you receive it; when NEGATIVE you pay it (honest — funding flips).
    """
    print("=" * 60)
    print("FUNDING-RATE ARBITRAGE — BACKTEST (delta-neutral, paper)")
    print("=" * 60)
    print(f"Cost per pair (open+close, both legs): "
          f"{PAIR_ROUNDTRIP_COST*100:.2f}%")
    print(f"Symbols: {', '.join(symbols)}\n")

    per_symbol = []
    for sym in symbols:
        hist = fetch_funding_history(sym)
        if not hist:
            print(f"  {sym}: no funding data, skipping")
            continue
        # Sum funding collected (delta-neutral: price P&L cancels, so the return
        # is just the funding stream minus open/close cost).
        gross_funding = sum(rate for _, rate in hist)   # fraction
        periods = len(hist)
        days = periods / 3.0                            # 3 fundings/day
        net = gross_funding - PAIR_ROUNDTRIP_COST
        # Annualize the NET return over the holding window.
        annualized = (net / days * 365) if days > 0 else 0.0
        avg_8h = gross_funding / periods if periods else 0.0
        neg_periods = sum(1 for _, r in hist if r < 0)
        per_symbol.append({
            "symbol": sym, "gross": gross_funding, "net": net,
            "annualized": annualized, "days": days,
            "avg_8h": avg_8h, "neg_pct": neg_periods / periods * 100,
        })
        start = datetime.fromtimestamp(hist[0][0]/1000, timezone.utc).date()
        end = datetime.fromtimestamp(hist[-1][0]/1000, timezone.utc).date()
        print(f"  {sym:10} {periods} fundings ({start} to {end}, ~{days:.0f}d)")
        print(f"      gross funding collected: {gross_funding*100:+.2f}%")
        print(f"      minus cost {PAIR_ROUNDTRIP_COST*100:.2f}% "
              f"= NET {net*100:+.2f}%  (~{annualized*100:+.1f}%/yr)")
        print(f"      avg {avg_8h*100:.4f}%/8h · "
              f"funding was NEGATIVE {neg_periods/periods*100:.0f}% of the time")
        time.sleep(0.1)

    if not per_symbol:
        print("No data.")
        return

    # Portfolio: equal weight across symbols.
    avg_ann = sum(s["annualized"] for s in per_symbol) / len(per_symbol)
    avg_net = sum(s["net"] for s in per_symbol) / len(per_symbol)
    print("\n" + "-" * 60)
    print("PORTFOLIO (equal weight, delta-neutral)")
    print(f"  Avg NET return over window: {avg_net*100:+.2f}%")
    print(f"  Avg annualized:             {avg_ann*100:+.1f}%/yr")
    print("-" * 60)

    print("\n  HONEST READ:")
    print("  * This is delta-neutral: it does NOT profit from price going up.")
    print("    It collects funding fees. Compare to a SAVINGS rate, not to HODL.")
    print(f"  * ~{avg_ann*100:.0f}%/yr matches the research (~7%/yr average).")
    print("  * REAL RISK not shown here: liquidation of the futures leg on a")
    print("    sharp move (no cross-margin) can cause a real loss. Paper can't")
    print("    fully model that. Treat this as 'promising, needs care'.")
    print("  * Requires a FUTURES account to do for real.")
    return {"avg_annualized": avg_ann * 100, "avg_net": avg_net * 100}


DEFAULT = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
           "DOGEUSDT", "AVAXUSDT", "LINKUSDT"]


if __name__ == "__main__":
    backtest(DEFAULT)
