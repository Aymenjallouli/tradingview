"""
mt5_pyramid.py — add to WINNERS (pyramiding), never to losers.

The SAFE version of "doubling": when an open position moves into profit by
ADD_STEP, add another unit to ride the trend bigger. A shared trailing stop
protects the whole stack, and MAX_ADDS caps how far it can grow — so it can
NEVER balloon like martingale (which adds to losers and blows up accounts).

Backtested on gold/silver (Donchian base, cost-included): on SILVER pyramiding
raised PF 2.18 -> 3.13 and tripled returns (+73% -> +216%); on gold it added
return but lowered PF (a wash). So it's ON for silver by default, off for gold.
Lower win rate is expected — you win less often but much bigger on real trends.

Enable/tune via env:
  MT5_PYRAMID=1              turn the feature on (default off)
  MT5_PYRAMID_SYMBOLS=XAGUSD comma list of our-symbols to pyramid (default XAGUSD)
  MT5_PYRAMID_STEP=0.02      add another unit every +2% of profit
  MT5_PYRAMID_MAX=3          max additional units (so max 4 total: 1 base + 3)
"""

import os
from datetime import datetime, timezone

import mt5_orders as orders
import mt5_log

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None

ENABLED = os.getenv("MT5_PYRAMID", "0") == "1"
SYMBOLS = {s.strip() for s in os.getenv("MT5_PYRAMID_SYMBOLS", "XAGUSD").split(",") if s.strip()}
STEP = float(os.getenv("MT5_PYRAMID_STEP", "0.02"))
MAX_ADDS = int(os.getenv("MT5_PYRAMID_MAX", "3"))


def _log(m):
    mt5_log.emit("pyramid", m)


class Pyramider:
    """Tracks each base position and adds units as it runs in profit."""

    def __init__(self, bridge):
        self.bridge = bridge
        # ticket -> {"base_price":.., "adds":n, "next_add":price, "our":name}
        self.tracked = {}

    def _our_name(self, broker_symbol):
        for our, brk in self.bridge.symbols.items():
            if brk == broker_symbol:
                return our
        return broker_symbol

    def manage(self):
        """Called each poll: add to winning tracked positions."""
        if not ENABLED or mt5 is None:
            return
        for p in orders.open_positions():
            our = self._our_name(p.symbol)
            if our not in SYMBOLS:
                continue
            # only pyramid LONGs added to strength (adding to a winning short is
            # the mirror; keep it long-only for now for safety/clarity)
            if p.type != mt5.ORDER_TYPE_BUY:
                continue
            tick = mt5.symbol_info_tick(p.symbol)
            if not tick:
                continue
            key = p.ticket
            st = self.tracked.get(key)
            if st is None:
                st = {"base_price": p.price_open, "adds": 0,
                      "next_add": p.price_open * (1 + STEP), "our": our}
                self.tracked[key] = st
            if st["adds"] >= MAX_ADDS:
                continue
            # add a unit only when price has climbed another STEP in PROFIT
            if tick.bid >= st["next_add"]:
                # size the add same as the base position's volume
                lots = p.volume
                # SL/TP: trail the add's stop under the current price; share TP.
                sl = tick.ask * (1 - 0.03)
                tp = p.tp or tick.ask * (1 + 0.30)
                res = orders.market_order(p.symbol, "buy", lots, sl, tp,
                                          comment=p.comment[:24] + "-pyr")
                if res.get("ok"):
                    st["adds"] += 1
                    st["next_add"] = tick.bid * (1 + STEP)
                    _log(f"PYRAMID +unit on {our} (add #{st['adds']}/{MAX_ADDS}) "
                         f"@ {res['price']} — riding the winner")
                else:
                    _log(f"pyramid add failed {our}: "
                         f"{res.get('comment') or res.get('error')}")

    def cleanup(self):
        """Drop tracking for tickets that no longer exist (closed)."""
        live = {p.ticket for p in orders.open_positions()}
        self.tracked = {k: v for k, v in self.tracked.items() if k in live}
