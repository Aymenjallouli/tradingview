"""
grid.py — Grid trading strategy + honest backtester.

Grid trading does NOT predict direction. It places a ladder of buy orders below
the price and sell orders above, and profits from the price OSCILLATING up and
down through the levels. Each time price falls to a buy level then rises to the
next level up, it books a small profit. It's the one strategy that fits a
"run a bot 24/7" edge, because its whole job is to sit there catching bounces.

HONEST mechanics (worked example, 10 levels between $100 and $110):
  levels: 100,101,...,110. Say price is 105.
  * Price dips to 104 -> a buy fills (we now hold a bit).
  * Price rises to 105 -> we sell that bit for ~1% gross, minus fees.
  * Repeat forever while price stays in the range.

THE CATCH (why it's not free money):
  * If price CRASHES below the range, every buy level fills on the way down and
    NONE of the sells trigger -> you're left holding a bag of a falling asset
    with all your cash spent. That's the real risk, and this backtester SHOWS it
    by testing a crash period, not just a calm one.

This module:
  * backtest_grid(prices, low, high, n_levels)  — simulate honestly with fees.
  * A __main__ that tests BOTH a recent range period AND a crash, on live data.
"""

import requests

import config

FEE = config.FEE_PCT          # 0.1% per side
SLIP = config.SLIPPAGE_PCT    # 0.05% per side


def _klines(symbol, interval, limit):
    rows = requests.get(f"{config.BINANCE_REST}/api/v3/klines",
                        params={"symbol": symbol, "interval": interval,
                                "limit": limit}, timeout=20).json()
    return [(float(r[2]), float(r[3]), float(r[4])) for r in rows]  # high,low,close


def backtest_grid(candles, low, high, n_levels, capital=50.0):
    """Simulate a grid between `low` and `high` with `n_levels` buy/sell lines.

    Model: capital is split across the levels. Each level below price holds a
    resting BUY; when price trades down through a level we buy one unit-slice;
    when price trades back up through the NEXT level we sell it for the grid
    step's gross profit, minus fees+slippage on both sides.

    candles: list of (high, low, close) per bar.
    Returns a dict of results including final value INCLUDING any bag held.
    """
    step = (high - low) / n_levels
    levels = [low + i * step for i in range(n_levels + 1)]
    cash_per_level = capital / n_levels

    cash = capital
    # holdings[level_index] = qty bought at that level, waiting to sell one up.
    holdings = {}
    trades = 0
    realized = 0.0
    prev_close = candles[0][2]

    for (hi, lo, close) in candles:
        # BUYS: a buy at level i fills only when price CROSSES DOWN through it
        # this bar (prev price was above the level, this bar's low reached it).
        # This avoids filling every level at once on bar 1.
        for i in range(len(levels)):
            lvl = levels[i]
            crossed_down = prev_close > lvl and lo <= lvl
            if crossed_down and i not in holdings and cash >= cash_per_level - 1e-9:
                fill = lvl * (1 + SLIP)
                fee = cash_per_level * FEE
                qty = (cash_per_level - fee) / fill
                holdings[i] = {"qty": qty, "buy_fill": fill,
                               "cost": cash_per_level}
                cash -= cash_per_level
        # SELLS: a holding bought at level i sells when this bar's HIGH reaches
        # the NEXT level up — booking one grid step of profit minus fees.
        for i in list(holdings.keys()):
            sell_lvl = levels[min(i + 1, len(levels) - 1)]
            if hi >= sell_lvl and sell_lvl > levels[i]:
                h = holdings.pop(i)
                fill = sell_lvl * (1 - SLIP)
                gross = h["qty"] * fill
                fee = gross * FEE
                net = gross - fee
                realized += net - h["cost"]
                cash += net
                trades += 1
        prev_close = close

    # End value = cash + value of any bag still held (at last close).
    last = candles[-1][2]
    bag_value = sum(h["qty"] * last for h in holdings.values())
    final = cash + bag_value
    return {
        "final": final, "start": capital,
        "return_pct": (final / capital - 1) * 100,
        "realized_pnl": realized, "trades": trades,
        "bag_positions": len(holdings), "bag_value": bag_value,
        "price_start": candles[0][2], "price_end": last,
        "bh_pct": (last / candles[0][2] - 1) * 100,
    }


def _report(title, r):
    print(f"\n=== {title} ===")
    print(f"  Price moved {r['price_start']:.2f} -> {r['price_end']:.2f} "
          f"(buy&hold {r['bh_pct']:+.1f}%)")
    print(f"  Grid final value: ${r['final']:.2f} ({r['return_pct']:+.1f}%)")
    print(f"  Completed grid trades: {r['trades']}, realized ${r['realized_pnl']:+.2f}")
    if r["bag_positions"]:
        print(f"  [!] Still holding {r['bag_positions']} unsold buys "
              f"(${r['bag_value']:.2f}) — a 'bag' from price leaving the range")
    verdict = "BEAT" if r["return_pct"] > r["bh_pct"] else "TRAILED"
    print(f"  Grid {verdict} buy & hold")


def main():
    print("=" * 60)
    print("GRID TRADING — HONEST BACKTEST (real live Binance data)")
    print("=" * 60)
    print(f"Costs: {FEE*100:.1f}% fee/side + {SLIP*100:.2f}% slippage")

    # Pull recent hourly candles for ETH (volatile enough to bounce).
    sym = "ETHUSDT"
    candles = _klines(sym, "1h", 1000)   # ~41 days of hourly data
    closes = [c[2] for c in candles]

    # --- Test 1: a RANGE-BOUND window (grid's happy place) --------------
    # Find a stretch where price stayed relatively flat.
    # Use the middle third and set the grid to its actual hi/lo.
    third = len(candles) // 3
    mid = candles[third:2 * third]
    mid_lo = min(c[1] for c in mid)
    mid_hi = max(c[0] for c in mid)
    r1 = backtest_grid(mid, mid_lo, mid_hi, 20)
    _report(f"{sym} — range-bound window (grid's best case)", r1)

    # --- Test 2: the FULL window incl. any trend/crash ------------------
    full_lo = min(c[1] for c in candles)
    full_hi = max(c[0] for c in candles)
    r2 = backtest_grid(candles, full_lo, full_hi, 20)
    _report(f"{sym} — full window (includes trends/drops)", r2)

    # --- Test 3: a CRASH scenario (grid's worst case) ------------------
    # Find the biggest peak-to-trough drop and grid across the TOP of it, so
    # price crashes OUT the bottom (the bagholding failure mode).
    peak_i = closes.index(max(closes))
    crash = candles[peak_i:]
    if len(crash) > 30:
        c_lo = min(c[1] for c in crash)
        c_hi = max(c[0] for c in crash)
        # Grid only across the UPPER half of the range, so the crash exits below.
        r3 = backtest_grid(crash, (c_lo + c_hi) / 2, c_hi, 20)
        _report(f"{sym} — CRASH scenario (grid set high, price falls out)", r3)

    print("\n" + "=" * 60)
    print("HONEST READ:")
    print("  * Grid WINS when price chops sideways inside the range.")
    print("  * Grid gets BAGGED when price crashes out the bottom — you're left")
    print("    holding a falling asset. That's the real risk; a live version")
    print("    needs a stop-loss / range-exit rule.")
    print("  * Returns depend entirely on picking a ranging market + a stop.")
    print("=" * 60)


if __name__ == "__main__":
    main()
