"""
broker.py — Multi-account paper broker.

Each strategy (trend / scalp / forex) gets its OWN isolated account: its own
cash, its own open positions, its own trade log. They never mix. Everything
lives in one SQLite file, keyed by a `strategy` column.

Realistic costs on every fill:
  * crypto: 0.1% fee/side + 0.05% slippage
  * forex : spread (pips, per pair) + slippage pips  (no percentage fee)
One position per (strategy, symbol). Paper money only.
"""

import sqlite3
from datetime import datetime, timezone

import config


def _now():
    return datetime.now(timezone.utc).isoformat()


class MultiBroker:
    def __init__(self, db_path=None):
        self.conn = sqlite3.connect(db_path or config.DATABASE_PATH,
                                    check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create()

    def _create(self):
        c = self.conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS accounts (
            strategy TEXT PRIMARY KEY, cash REAL NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS positions (
            strategy TEXT, symbol TEXT, qty REAL, entry_price REAL,
            fill_price REAL, cash_committed REAL, cost_in REAL,
            entry_time TEXT, entry_bar_ms INTEGER,
            PRIMARY KEY (strategy, symbol))""")
        c.execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, strategy TEXT, symbol TEXT,
            entry_time TEXT, exit_time TEXT, entry_price REAL, exit_price REAL,
            qty REAL, pnl REAL, return_pct REAL, cost_paid REAL,
            exit_reason TEXT)""")
        self.conn.commit()

    def ensure_account(self, strategy):
        c = self.conn.cursor()
        c.execute("SELECT cash FROM accounts WHERE strategy=?", (strategy,))
        if c.fetchone() is None:
            c.execute("INSERT INTO accounts (strategy, cash) VALUES (?,?)",
                      (strategy, config.STARTING_CAPITAL))
            self.conn.commit()

    # -- account -------------------------------------------------------------
    def cash(self, strategy):
        r = self.conn.execute("SELECT cash FROM accounts WHERE strategy=?",
                              (strategy,)).fetchone()
        return float(r["cash"]) if r else config.STARTING_CAPITAL

    def _set_cash(self, strategy, v):
        self.conn.execute("UPDATE accounts SET cash=? WHERE strategy=?",
                          (v, strategy))
        self.conn.commit()

    def position(self, strategy, symbol):
        return self.conn.execute(
            "SELECT * FROM positions WHERE strategy=? AND symbol=?",
            (strategy, symbol)).fetchone()

    def has_position(self, strategy, symbol):
        return self.position(strategy, symbol) is not None

    def open_positions(self, strategy):
        return self.conn.execute(
            "SELECT * FROM positions WHERE strategy=?", (strategy,)).fetchall()

    def equity(self, strategy, prices=None):
        prices = prices or {}
        eq = self.cash(strategy)
        for p in self.open_positions(strategy):
            eq += p["qty"] * prices.get(p["symbol"], p["fill_price"])
        return eq

    # -- fills ---------------------------------------------------------------
    def buy(self, strategy, symbol, price, size_pct, cost_fn, entry_bar_ms=0):
        """cost_fn(mid, side) -> fill_price (applies fees/spread/slippage)."""
        if self.has_position(strategy, symbol):
            return None
        cash = self.cash(strategy)
        committed = min(self.equity(strategy) * size_pct, cash)
        if committed <= 0:
            return None
        fill = cost_fn(price, "buy")
        # Percentage fee applies to crypto; forex fee is baked into the spread
        # via cost_fn, so we pass fee=0 there. We detect market by strategy.
        fee = committed * config.FEE_PCT if strategy != "forex" else 0.0
        qty = (committed - fee) / fill
        cost_in = qty * (fill - price) + fee
        self._set_cash(strategy, cash - committed)
        self.conn.execute("""INSERT INTO positions
            (strategy, symbol, qty, entry_price, fill_price, cash_committed,
             cost_in, entry_time, entry_bar_ms) VALUES (?,?,?,?,?,?,?,?,?)""",
            (strategy, symbol, qty, price, fill, committed, cost_in, _now(),
             entry_bar_ms))
        self.conn.commit()
        return {"symbol": symbol, "committed": committed, "fill": fill}

    def sell(self, strategy, symbol, price, reason, cost_fn):
        pos = self.position(strategy, symbol)
        if pos is None:
            return None
        fill = cost_fn(price, "sell")
        gross = pos["qty"] * fill
        fee = gross * config.FEE_PCT if strategy != "forex" else 0.0
        net = gross - fee
        pnl = net - pos["cash_committed"]
        ret = pnl / pos["cash_committed"] if pos["cash_committed"] else 0.0
        cost_out = pos["qty"] * (price - fill) + fee
        self._set_cash(strategy, self.cash(strategy) + net)
        self.conn.execute("""INSERT INTO trades
            (strategy, symbol, entry_time, exit_time, entry_price, exit_price,
             qty, pnl, return_pct, cost_paid, exit_reason)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (strategy, symbol, pos["entry_time"], _now(), pos["entry_price"],
             price, pos["qty"], pnl, ret, pos["cost_in"] + cost_out, reason))
        self.conn.execute(
            "DELETE FROM positions WHERE strategy=? AND symbol=?",
            (strategy, symbol))
        self.conn.commit()
        return {"symbol": symbol, "pnl": pnl, "return_pct": ret, "reason": reason}

    # -- reporting -----------------------------------------------------------
    def trades(self, strategy):
        return self.conn.execute(
            "SELECT * FROM trades WHERE strategy=? ORDER BY id",
            (strategy,)).fetchall()

    def stats(self, strategy):
        t = self.trades(strategy)
        n = len(t)
        wins = [x for x in t if x["pnl"] > 0]
        gw = sum(x["pnl"] for x in wins)
        gl = abs(sum(x["pnl"] for x in t if x["pnl"] <= 0))
        pf = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else 0.0)
        return {
            "trades": n,
            "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
            "profit_factor": (None if pf == float("inf") else round(pf, 2)),
            "net_pnl": round(sum(x["pnl"] for x in t), 4),
            "cost_paid": round(sum(x["cost_paid"] for x in t), 4),
        }

    def close(self):
        self.conn.close()
