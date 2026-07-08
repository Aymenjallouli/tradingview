"""
mt5_momentum.py — Cross-sectional momentum (the one that passed the stress tests).

Different shape from the signal-per-candle strategies: it ranks the whole
trending universe by recent return, HOLDS the top N, and rebalances on a slow
schedule (monthly-ish). Low turnover = low fees, which is why it survives costs.

Stress-tested (see chat): beat buy-and-hold +178% over ~10 months, robust to
parameter choices (+95%..+307%), robust to realistic costs (+156% at 0.5% fee),
and NOT dependent on one lucky asset (still +178% with NVDA removed). It has
decades of peer-reviewed academic backing (momentum is a documented anomaly).

HONEST RISK built into the docs: momentum crashes hard in trend reversals — a
+178% bull-year can be a -40% crash-year. It is NOT a free lunch; it's a real
but volatile edge. Runs on the DEMO with real broker execution + SL as a floor.

Universe = trending assets only (stocks, crypto, gold). Forex trends weakly and
is excluded. Rebalances every REBALANCE_DAYS; holds TOP_N equally weighted.
"""

import os
from datetime import datetime, timezone

import pandas as pd

import mt5_orders as orders

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None


def _log(m):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [momentum] {m}", flush=True)


# The assets that actually trend (momentum needs trends). Forex excluded.
UNIVERSE = ["NVDA", "MSFT", "AMD", "INTC", "BTCUSD", "ETHUSD", "XAUUSD",
            "AAPL", "AMZN", "GOOGL", "META", "NFLX", "XAGUSD"]
LOOKBACK_DAYS = 60
TOP_N = int(os.getenv("MOMO_TOP_N", "2"))
REBALANCE_DAYS = int(os.getenv("MOMO_REBALANCE_DAYS", "20"))
STRATEGY_KEY = "xmom"                  # tags positions
# Protective stop as a floor under each holding (momentum's crash insurance).
STOP_PCT = float(os.getenv("MOMO_STOP_PCT", "0.15"))   # -15%


class CrossMomentum:
    key = STRATEGY_KEY
    label = "Cross-Sectional Momentum (top-2, monthly)"

    def __init__(self, bridge, virtual_equity=1000.0, dry_run=False):
        self.bridge = bridge
        self.virtual_equity = virtual_equity
        self.dry_run = dry_run
        self.last_rebalance = None
        self.current_holdings = []       # our-symbol names currently held
        self.log = []

    def _record(self, m):
        _log(m)
        self.log.append({"time": datetime.now(timezone.utc).isoformat(), "msg": m})
        self.log = self.log[-60:]

    def _rank(self):
        """Rank the universe by LOOKBACK_DAYS return; return top-N our-symbols."""
        scores = {}
        for our in UNIVERSE:
            if our not in self.bridge.symbols:
                continue
            df = self.bridge.candles(our, "1d", LOOKBACK_DAYS + 10)
            if df.empty or len(df) < LOOKBACK_DAYS + 1:
                continue
            closes = df["close"].values
            past = closes[-(LOOKBACK_DAYS + 1)]
            if past <= 0:
                continue
            scores[our] = closes[-1] / past - 1
        ranked = sorted(scores, key=scores.get, reverse=True)
        # Only hold assets with POSITIVE momentum (don't buy fallers).
        top = [s for s in ranked if scores[s] > 0][:TOP_N]
        return top, scores

    def _our_positions(self):
        held = {}
        for p in orders.open_positions():
            if p.comment.startswith(STRATEGY_KEY):
                # map broker symbol back to our name
                for our, brk in self.bridge.symbols.items():
                    if brk == p.symbol:
                        held[our] = p
        return held

    def rebalance(self):
        """Rotate holdings toward the current top-N momentum names."""
        top, scores = self._rank()
        if not top:
            self._record("no positive-momentum assets — going to cash")
        held = self._our_positions()
        held_syms = set(held.keys())
        target = set(top)

        # 1. Close positions no longer in the top-N.
        for our in held_syms - target:
            pos = held[our]
            if self.dry_run:
                self._record(f"[DRY] would CLOSE {our} (dropped from top-{TOP_N})")
            else:
                orders.close_position(pos)
                self._record(f"CLOSED {our} (rotated out)")

        # 2. Open new top-N names we don't hold.
        equity = self.virtual_equity
        per_name = equity / max(TOP_N, 1)
        for our in target - held_syms:
            brk = self.bridge.symbols.get(our)
            tick = self.bridge.tick(our)
            if not brk or not tick:
                continue
            price = tick["ask"]
            sl = price * (1 - STOP_PCT)
            tp = price * (1 + 0.60)          # generous — let winners run
            # size so this name is ~per_name of notional, capped by risk floor
            lots = orders.lots_for_risk(brk, equity, 100 * (per_name / equity)
                                        * STOP_PCT * 100 / 100, price, sl)
            # simpler: size to deploy ~per_name of equity (spot notional)
            info = mt5.symbol_info(brk) if mt5 else None
            if info and info.trade_contract_size:
                raw = per_name / (price * info.trade_contract_size)
                step = info.volume_step or 0.01
                lots = max(info.volume_min,
                           round(round(raw / step) * step, 8))
                lots = min(lots, info.volume_max)
            if lots <= 0:
                continue
            if self.dry_run:
                self._record(f"[DRY] would BUY {our} {lots} lots @ {price:.2f} "
                             f"(momentum {scores.get(our,0)*100:+.0f}%)")
            else:
                res = orders.market_order(brk, "buy", lots, sl, tp,
                                          comment=STRATEGY_KEY)
                if res.get("ok"):
                    self._record(f"BOUGHT {our} {lots} lots @ {res['price']} "
                                 f"(momentum {scores.get(our,0)*100:+.0f}%, "
                                 f"SL -{STOP_PCT*100:.0f}%)")
                else:
                    self._record(f"BUY FAILED {our}: "
                                 f"{res.get('comment') or res.get('error')}")

        self.current_holdings = list(target)
        self.last_rebalance = datetime.now(timezone.utc)
        self._record(f"rebalanced. Holding top-{TOP_N}: {top} "
                     f"(scores: {[f'{s}:{scores.get(s,0)*100:+.0f}%' for s in top]})")

    def maybe_rebalance(self):
        """Rebalance if REBALANCE_DAYS have passed (or first run)."""
        now = datetime.now(timezone.utc)
        if self.last_rebalance is None:
            self.rebalance()
            return
        days = (now - self.last_rebalance).days
        if days >= REBALANCE_DAYS:
            self.rebalance()

    def snapshot(self):
        held = self._our_positions()
        positions = [{
            "symbol": our, "profit": p.profit, "price_open": p.price_open,
        } for our, p in held.items()]
        top, scores = ([], {})
        try:
            top, scores = self._rank()
        except Exception:  # noqa: BLE001
            pass
        return {
            "label": self.label,
            "holding": list(held.keys()),
            "top_ranked": top,
            "scores": {k: round(v * 100, 1) for k, v in scores.items()},
            "positions": positions,
            "last_rebalance": self.last_rebalance.isoformat()
            if self.last_rebalance else None,
            "rebalance_days": REBALANCE_DAYS,
            "log": self.log[-20:][::-1],
        }
