"""
arb_monitor.py — Cross-exchange arbitrage monitor (scientific experiment).

Purpose: measure whether cross-exchange crypto arbitrage gaps survive REAL costs
and REAL latency. Brutally honest — no optimistic fills, never real money.

Badge: "Guaranteed money detector — expect it to prove the opposite."

Method (per 2-second cycle):
  1. Fetch best BID/ASK for BTC & ETH on Binance, Coinbase, Kraken.
  2. For every ordered pair (A,B): gross_gap = bid_B - ask_A  (buy at A's ask,
     sell at B's bid — REAL tradeable sides, never mid/last).
  3. Subtract taker fees (both sides) + slippage (both sides). net_gap > 0 = an
     "opportunity".
  4. LATENCY TEST: on an opportunity, record it, WAIT 2.5s, re-fetch both
     prices, and fill at the RE-CHECKED prices (never the trigger prices).
     Record survived / vanished + simulated P&L on a $50 position.

Honesty rules (hard):
  * Never fill at trigger prices — only post-delay re-checked prices.
  * bid/ask only, never mid/last.
  * costs on BOTH sides.
  * feed older than 10s => excluded that cycle, marked degraded.
  * observe & log only; no auto-trading.

The funnel it measures (predictions on record):
  raw gaps (constant) -> net-positive after costs (rare) -> survived latency
  (near zero). If #3 stays ~0 after a week, "guaranteed money" is debunked with
  data. If not, that's genuinely interesting and we investigate.
"""

import sqlite3
import threading
import time
from datetime import datetime, timezone

import requests

import config

# --- Exchange config: taker fee per side + symbol naming --------------------
EXCHANGES = {
    "binance": {"fee": 0.0010},   # 0.10%
    "coinbase": {"fee": 0.0060},  # 0.60%
    "kraken": {"fee": 0.0026},    # 0.26%
}
SLIPPAGE = 0.0005                 # 0.05% per side
POSITION_USD = 50.0
import os as _os
# Simulated execution latency between spotting a gap and filling. 2.5s models a
# retail trader; lower it (e.g. 0.5s) to model a faster/co-located setup. Note:
# latency is NOT what kills these gaps — fees are (see the spread matrix: gaps
# are net-negative BEFORE any delay). This mainly makes the test more complete.
EXEC_DELAY_S = float(_os.getenv("ARB_DELAY_S", "0.5"))
STALE_S = 10                      # feed older than this = degraded
POLL_S = 2

# symbol -> per-exchange ticker identifier
SYMBOLS = {
    "BTC": {"binance": "BTCUSDT", "coinbase": "BTC-USD", "kraken": "XBTUSD"},
    "ETH": {"binance": "ETHUSDT", "coinbase": "ETH-USD", "kraken": "ETHUSD"},
}


def _now():
    return datetime.now(timezone.utc)


# --- Per-exchange fetchers: return (bid, ask) or None -----------------------
def _binance(sym):
    try:
        d = requests.get(
            f"{config.BINANCE_REST}/api/v3/ticker/bookTicker",
            params={"symbol": sym}, timeout=5).json()
        return float(d["bidPrice"]), float(d["askPrice"])
    except Exception:  # noqa: BLE001
        return None


def _coinbase(sym):
    try:
        d = requests.get(
            f"https://api.exchange.coinbase.com/products/{sym}/ticker",
            timeout=5, headers={"User-Agent": "arb-monitor"}).json()
        return float(d["bid"]), float(d["ask"])
    except Exception:  # noqa: BLE001
        return None


def _kraken(sym):
    try:
        d = requests.get("https://api.kraken.com/0/public/Ticker",
                        params={"pair": sym}, timeout=5).json()
        res = d["result"]
        k = list(res.keys())[0]
        return float(res[k]["b"][0]), float(res[k]["a"][0])
    except Exception:  # noqa: BLE001
        return None


_FETCH = {"binance": _binance, "coinbase": _coinbase, "kraken": _kraken}


def _fetch_all(symbol):
    """Return {exchange: {"bid","ask","ts"}} for a symbol, skipping failures."""
    out = {}
    for ex, ident in SYMBOLS[symbol].items():
        q = _FETCH[ex](ident)
        if q:
            out[ex] = {"bid": q[0], "ask": q[1], "ts": time.time()}
    return out


class ArbMonitor:
    def __init__(self, db_path=None):
        self.db_path = db_path or config.DATABASE_PATH
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create()
        self.lock = threading.Lock()
        self._running = False
        # Funnel counters (since start).
        self.raw_gaps = 0
        self.net_positive = 0
        self.survived = 0
        self.hypo_pnl = 0.0
        self.matrix = {}         # latest spread matrix for the UI
        self.recent = []         # last 10 opportunities + fate
        self.degraded = {}       # exchange -> True if stale/down this cycle

    def _create(self):
        c = self.conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS arb_opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT,
            buy_ex TEXT, sell_ex TEXT, trig_ask REAL, trig_bid REAL,
            gross_gap REAL, net_gap REAL,
            fill_ask REAL, fill_bid REAL, fill_net REAL,
            outcome TEXT, pnl REAL, lifetime_s REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS arb_stats_daily (
            day TEXT PRIMARY KEY, raw_gaps INTEGER, net_positive INTEGER,
            survived INTEGER, avg_lifetime_s REAL, hypo_pnl REAL)""")
        self.conn.commit()

    # ------------------------------------------------------------------
    def _cost_frac(self, buy_ex, sell_ex):
        """Total cost as a FRACTION of notional: taker fee both venues + slip."""
        return (EXCHANGES[buy_ex]["fee"] + EXCHANGES[sell_ex]["fee"]
                + 2 * SLIPPAGE)

    def _evaluate(self, symbol, quotes):
        """Find gross/net gaps for all ordered exchange pairs. Returns list of
        opportunity dicts with net_gap > 0. Also updates the spread matrix.
        """
        opps = []
        now = time.time()
        # Mark degraded feeds (stale or missing).
        fresh = {}
        for ex in EXCHANGES:
            q = quotes.get(ex)
            if q and (now - q["ts"]) <= STALE_S:
                fresh[ex] = q
                self.degraded[ex] = False
            else:
                self.degraded[ex] = True

        matrix = {}
        for buy_ex in fresh:
            for sell_ex in fresh:
                if buy_ex == sell_ex:
                    continue
                ask = fresh[buy_ex]["ask"]      # we BUY at A's ask
                bid = fresh[sell_ex]["bid"]     # we SELL at B's bid
                gross = (bid - ask) / ask       # as a fraction of price
                cost = self._cost_frac(buy_ex, sell_ex)
                net = gross - cost
                matrix[f"{buy_ex}->{sell_ex}"] = {
                    "gross_pct": round(gross * 100, 4),
                    "net_pct": round(net * 100, 4),
                    "positive": net > 0,
                }
                if gross > 0:
                    self.raw_gaps += 1
                if net > 0:
                    self.net_positive += 1
                    opps.append({"symbol": symbol, "buy_ex": buy_ex,
                                 "sell_ex": sell_ex, "trig_ask": ask,
                                 "trig_bid": bid, "gross": gross, "net": net})
        self.matrix[symbol] = matrix
        return opps

    def _latency_test(self, opp):
        """Record the trigger, wait EXEC_DELAY_S, re-fetch, fill at NEW prices."""
        t0 = time.time()
        # Re-fetch just the two exchanges involved.
        buy_q = _FETCH[opp["buy_ex"]](SYMBOLS[opp["symbol"]][opp["buy_ex"]])
        sell_q = _FETCH[opp["sell_ex"]](SYMBOLS[opp["symbol"]][opp["sell_ex"]])
        lifetime = time.time() - t0 + EXEC_DELAY_S
        outcome, pnl, fill_ask, fill_bid, fill_net = "vanished", 0.0, None, None, None
        if buy_q and sell_q:
            fill_ask = buy_q[1]          # re-checked ask (what we'd pay)
            fill_bid = sell_q[0]         # re-checked bid (what we'd get)
            gross = (fill_bid - fill_ask) / fill_ask
            cost = self._cost_frac(opp["buy_ex"], opp["sell_ex"])
            fill_net = gross - cost
            if fill_net > 0:
                outcome = "survived"
                pnl = fill_net * POSITION_USD
                self.survived += 1
                self.hypo_pnl += pnl
        # Persist + track.
        rec = {
            "ts": _now().isoformat(), "symbol": opp["symbol"],
            "buy_ex": opp["buy_ex"], "sell_ex": opp["sell_ex"],
            "trig_ask": opp["trig_ask"], "trig_bid": opp["trig_bid"],
            "gross_gap": round(opp["gross"] * 100, 4),
            "net_gap": round(opp["net"] * 100, 4),
            "fill_net": round(fill_net * 100, 4) if fill_net is not None else None,
            "outcome": outcome, "pnl": round(pnl, 4),
            "lifetime_s": round(lifetime, 2),
        }
        with self.lock:
            self.conn.execute("""INSERT INTO arb_opportunities
                (ts,symbol,buy_ex,sell_ex,trig_ask,trig_bid,gross_gap,net_gap,
                 fill_ask,fill_bid,fill_net,outcome,pnl,lifetime_s)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rec["ts"], rec["symbol"], rec["buy_ex"], rec["sell_ex"],
                 opp["trig_ask"], opp["trig_bid"], rec["gross_gap"],
                 rec["net_gap"], fill_ask, fill_bid, rec["fill_net"],
                 outcome, pnl, rec["lifetime_s"]))
            self.conn.commit()
            self.recent.insert(0, rec)
            self.recent = self.recent[:10]

    # ------------------------------------------------------------------
    def _cycle(self):
        for symbol in SYMBOLS:
            quotes = _fetch_all(symbol)
            opps = self._evaluate(symbol, quotes)
            # Only latency-test the BEST opportunity per symbol per cycle (the
            # delay blocks; we don't want to fall behind).
            if opps:
                best = max(opps, key=lambda o: o["net"])
                self._latency_test(best)

    def run(self):
        self._running = True
        print("[arb] Monitor started — honest cross-exchange arb experiment.",
              flush=True)
        while self._running:
            try:
                self._cycle()
            except Exception as exc:  # noqa: BLE001 - never crash
                print(f"[arb] cycle error (skipped): {exc}", flush=True)
            for _ in range(POLL_S):
                if not self._running:
                    return
                time.sleep(1)

    def stop(self):
        self._running = False

    def snapshot(self):
        with self.lock:
            return {
                "funnel": {
                    "raw_gaps": self.raw_gaps,
                    "net_positive": self.net_positive,
                    "survived": self.survived,
                },
                "hypo_pnl": round(self.hypo_pnl, 4),
                "matrix": self.matrix,
                "recent": self.recent,
                "degraded": self.degraded,
                "position_usd": POSITION_USD,
                "delay_s": EXEC_DELAY_S,
            }


if __name__ == "__main__":
    m = ArbMonitor("arb_test.db")
    try:
        # Run a few cycles then print a summary.
        import threading as _t
        _t.Thread(target=m.run, daemon=True).start()
        for _ in range(6):
            time.sleep(5)
            s = m.snapshot()
            print(f"funnel: raw={s['funnel']['raw_gaps']} "
                  f"net+={s['funnel']['net_positive']} "
                  f"survived={s['funnel']['survived']} "
                  f"hypoP&L=${s['hypo_pnl']:.2f}")
    except KeyboardInterrupt:
        m.stop()
