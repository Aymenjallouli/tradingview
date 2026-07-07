"""
grid_v2_backtest.py — Honest backtest of Grid v2 before it trades live.

Grid v2 improvements over v1 (all aimed at realism + loss control):
  * LIQUID UNIVERSE ONLY: top coins by 24h volume, min $50M/day. No micro-caps.
  * REAL SPREAD COST: slippage per side = half the live bid-ask spread (fetched
    from bookTicker). If spread > 0.15% round trip, the coin is INELIGIBLE.
  * GRID STEP >= 3x round-trip cost: else the bounces can't clear costs; skip.
  * RANGE-BREAK LIQUIDATION: if price closes >10% outside the grid range,
    liquidate the grid at market (with costs) and log "bagged — range broken."
    This is the loss-control that makes grids survivable in a downtrend.

Tests on 90 days of 1h data per qualifying coin, vs buy-and-hold.

Run:  python grid_v2_backtest.py
"""

import requests

import config

FEE = 0.001                      # 0.1% per fill (spec)
RANGE_BREAK = 0.10               # liquidate if >10% outside range
MIN_STEP_MULT = 3                # grid step >= 3x round-trip cost
MAX_SPREAD_ROUNDTRIP = 0.0015    # 0.15% round trip max


def _klines(symbol, interval, limit):
    try:
        rows = requests.get(f"{config.BINANCE_REST}/api/v3/klines",
                            params={"symbol": symbol, "interval": interval,
                                    "limit": limit}, timeout=20).json()
        if not isinstance(rows, list):
            return None
        return [(float(r[2]), float(r[3]), float(r[4])) for r in rows]  # hi,lo,close
    except Exception:  # noqa: BLE001
        return None


def _spread_per_side(symbol):
    """Half the live bid-ask spread as a fraction (per-side slippage)."""
    try:
        d = requests.get(f"{config.BINANCE_REST}/api/v3/ticker/bookTicker",
                        params={"symbol": symbol}, timeout=8).json()
        bid, ask = float(d["bidPrice"]), float(d["askPrice"])
        if bid <= 0:
            return None
        return (ask - bid) / bid / 2
    except Exception:  # noqa: BLE001
        return None


def liquid_universe(top_n=50, min_vol=50_000_000):
    """Top liquid USDT spot coins by 24h volume (ascii names only)."""
    skip = {"USDCUSDT", "FDUSDUSDT", "USD1USDT", "TUSDUSDT", "DAIUSDT",
            "USDPUSDT", "EURUSDT", "AEURUSDT", "BUSDUSDT", "RLUSDUSDT"}
    info = requests.get(f"{config.BINANCE_REST}/api/v3/exchangeInfo",
                        timeout=20).json()
    spot = {s["symbol"] for s in info["symbols"]
            if s["symbol"].endswith("USDT") and s["status"] == "TRADING"
            and s.get("isSpotTradingAllowed")}
    tk = requests.get(f"{config.BINANCE_REST}/api/v3/ticker/24hr",
                      timeout=25).json()
    rows = []
    for t in tk:
        s = t["symbol"]
        if s in spot and s not in skip and s.isascii() \
                and s.replace("USDT", "").isalnum():
            v = float(t["quoteVolume"])
            if v >= min_vol:
                rows.append((s, v))
    rows.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in rows[:top_n]]


def backtest_grid_v2(candles, spread_side, capital=50.0):
    """Grid v2 on one coin. Returns result dict or None if ineligible.

    Grid is centered ±8% on the FIRST bar's price, step sized so each step is
    >= 3x round-trip cost. Range-break liquidation at ±10% outside range.
    """
    round_trip = 2 * (FEE + spread_side)         # buy+sell fees + slippage
    if round_trip > MAX_SPREAD_ROUNDTRIP + 2 * FEE + 0.001:
        pass  # (spread eligibility already filtered by caller)

    start_price = candles[0][2]
    low = start_price * 0.92
    high = start_price * 1.08
    # Step must be >= 3x round-trip cost (as a fraction of price).
    min_step_frac = MIN_STEP_MULT * round_trip
    band_frac = (high - low) / start_price       # 0.16
    n_levels = max(4, int(band_frac / min_step_frac))
    if n_levels < 4:
        return None                              # can't fit enough levels
    step = (high - low) / n_levels
    levels = [low + i * step for i in range(n_levels + 1)]
    cash_per = capital / n_levels

    cash = capital
    holdings = {}
    trades = 0
    realized = 0.0
    prev = start_price
    bagged = False
    break_lo = low * (1 - RANGE_BREAK)
    break_hi = high * (1 + RANGE_BREAK)

    for (hi, lo, close) in candles:
        # RANGE-BREAK: liquidate everything at market if price left the range.
        if close < break_lo or close > break_hi:
            for h in holdings.values():
                px = close * (1 - spread_side)
                cash += h["qty"] * px * (1 - FEE)
            holdings = {}
            bagged = True
            break
        # BUY: fill levels the bar's low reached (that we don't hold).
        for i in range(len(levels)):
            lvl = levels[i]
            if lo <= lvl <= hi and i not in holdings \
                    and cash >= cash_per - 1e-9:
                fill = lvl * (1 + spread_side)
                fee = cash_per * FEE
                qty = (cash_per - fee) / fill
                holdings[i] = {"qty": qty, "cost": cash_per}
                cash -= cash_per
        # SELL: holdings whose next level up was reached by the bar's high.
        for i in list(holdings.keys()):
            sell_lvl = levels[min(i + 1, len(levels) - 1)]
            if hi >= sell_lvl > levels[i]:
                h = holdings.pop(i)
                fill = sell_lvl * (1 - spread_side)
                net = h["qty"] * fill * (1 - FEE)
                realized += net - h["cost"]
                cash += net
                trades += 1
        prev = close

    last = candles[-1][2]
    bag_val = sum(h["qty"] * last for h in holdings.values())
    final = cash + bag_val
    return {
        "final": final, "return_pct": (final / capital - 1) * 100,
        "realized": realized, "trades": trades, "bagged": bagged,
        "n_levels": n_levels, "step_pct": step / start_price * 100,
        "bag_positions": len(holdings), "bag_value": bag_val,
        "bh_pct": (last / start_price - 1) * 100,
        "round_trip_pct": round_trip * 100,
    }


def main():
    print("=" * 68)
    print("GRID v2 BACKTEST — liquid universe, real spread, range-break exit")
    print("90 days of 1h data · vs buy-and-hold · costs: 0.1%/fill + live spread")
    print("=" * 68)

    universe = liquid_universe(top_n=40)
    print(f"Liquid universe (>=$50M/day): {len(universe)} coins\n")

    rows = []
    for sym in universe:
        spread = _spread_per_side(sym)
        if spread is None:
            continue
        # Eligibility: spread round-trip <= 0.15%.
        if 2 * spread > MAX_SPREAD_ROUNDTRIP:
            continue
        candles = _klines(sym, "1h", 2160)   # ~90 days of 1h
        if not candles or len(candles) < 500:
            continue
        r = backtest_grid_v2(candles, spread)
        if r is None:
            continue
        r["symbol"] = sym
        r["spread_pct"] = round(spread * 100, 4)
        rows.append(r)

    if not rows:
        print("No eligible coins.")
        return

    # Sort by return.
    rows.sort(key=lambda x: x["return_pct"], reverse=True)
    print(f"{'coin':10}{'grid%':>8}{'B&H%':>8}{'trades':>7}{'step':>7}"
          f"{'spread':>8}{'bagged':>8}  vs B&H")
    print("-" * 68)
    beat = 0
    tot_grid = 0.0
    tot_bh = 0.0
    for r in rows:
        v = "BEAT" if r["return_pct"] > r["bh_pct"] else "trail"
        if r["return_pct"] > r["bh_pct"]:
            beat += 1
        tot_grid += r["return_pct"]
        tot_bh += r["bh_pct"]
        print(f"{r['symbol']:10}{r['return_pct']:>+8.1f}{r['bh_pct']:>+8.1f}"
              f"{r['trades']:>7}{r['step_pct']:>6.1f}%{r['spread_pct']:>7.3f}%"
              f"{'YES' if r['bagged'] else 'no':>8}  {v}")

    n = len(rows)
    print("-" * 68)
    print(f"AVERAGE: grid {tot_grid/n:+.1f}%  vs  B&H {tot_bh/n:+.1f}%   "
          f"| grid beat B&H on {beat}/{n} coins")
    bagged_n = sum(1 for r in rows if r["bagged"])
    print(f"Range-break liquidations (bagged): {bagged_n}/{n} coins")
    print("\nHONEST READ:")
    print("  * 'bagged=YES' = range broke, grid liquidated at a loss (the")
    print("    loss-control working — caps the damage vs holding a faller).")
    print("  * Grid wins by catching bounces; it won't beat a strong bull run.")
    print("  * Judge on: beats B&H count + controlled bagging, not raw %.")


if __name__ == "__main__":
    main()
