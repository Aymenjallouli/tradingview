"""
forex_ledger.py — SQLite ledger for the FOREX paper experiment.

Uses the shared project database (../trades.db) but its OWN fx_* tables, so it
never mixes with the trend system or the crypto scalper:
    fx_account    : single row, current virtual cash
    fx_positions  : open positions (one per pair)
    fx_trades     : completed trades (permanent log)

Applies the realistic forex cost model (spread + slippage, per pair) via
forex_feed on every fill. Used by the live trader and read by the report.
"""

import sqlite3
from datetime import datetime, timezone

import forex_config as cfg
import forex_feed as feed


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class ForexLedger:
    def __init__(self, db_path=None):
        self.db_path = db_path or cfg.DATABASE_PATH
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create()
        self._ensure_account()

    def _create(self):
        cur = self.conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS fx_account (
            id INTEGER PRIMARY KEY CHECK (id=1), cash REAL NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS fx_positions (
            pair TEXT PRIMARY KEY, strategy TEXT NOT NULL, qty REAL NOT NULL,
            entry_fill REAL NOT NULL, cash_committed REAL NOT NULL,
            entry_cost REAL NOT NULL, entry_time TEXT NOT NULL,
            entry_bar_ms INTEGER NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS fx_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pair TEXT NOT NULL,
            strategy TEXT NOT NULL, entry_time TEXT NOT NULL,
            exit_time TEXT NOT NULL, entry_fill REAL NOT NULL,
            exit_fill REAL NOT NULL, qty REAL NOT NULL, pnl REAL NOT NULL,
            return_pct REAL NOT NULL, cost_paid REAL NOT NULL,
            exit_reason TEXT NOT NULL, minutes_held INTEGER NOT NULL)""")
        self.conn.commit()

    def _ensure_account(self):
        cur = self.conn.cursor()
        cur.execute("SELECT cash FROM fx_account WHERE id=1")
        if cur.fetchone() is None:
            cur.execute("INSERT INTO fx_account (id, cash) VALUES (1, ?)",
                        (cfg.STARTING_CAPITAL,))
            self.conn.commit()

    def get_cash(self):
        cur = self.conn.cursor()
        cur.execute("SELECT cash FROM fx_account WHERE id=1")
        return float(cur.fetchone()["cash"])

    def _set_cash(self, c):
        self.conn.execute("UPDATE fx_account SET cash=? WHERE id=1", (c,))
        self.conn.commit()

    def get_position(self, pair):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM fx_positions WHERE pair=?", (pair,))
        return cur.fetchone()

    def has_position(self, pair):
        return self.get_position(pair) is not None

    def open_positions(self):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM fx_positions")
        return cur.fetchall()

    def get_equity(self, prices=None):
        prices = prices or {}
        eq = self.get_cash()
        for p in self.open_positions():
            eq += p["qty"] * prices.get(p["pair"], p["entry_fill"])
        return eq

    def buy(self, pair, mid_price, strategy, entry_bar_ms):
        if self.has_position(pair):
            return False
        equity, cash = self.get_equity(), self.get_cash()
        committed = min(equity * cfg.POSITION_SIZE_PCT, cash)
        if committed <= 0:
            return False
        fill = feed.apply_cost(pair, mid_price, "buy")
        comm = committed * cfg.COMMISSION_PCT
        qty = (committed - comm) / fill
        cost = qty * (fill - mid_price) + comm
        self._set_cash(cash - committed)
        self.conn.execute("""INSERT INTO fx_positions
            (pair, strategy, qty, entry_fill, cash_committed, entry_cost,
             entry_time, entry_bar_ms) VALUES (?,?,?,?,?,?,?,?)""",
            (pair, strategy, qty, fill, committed, cost, _now_iso(),
             entry_bar_ms))
        self.conn.commit()
        return True

    def sell(self, pair, mid_price, reason, minutes_held):
        pos = self.get_position(pair)
        if pos is None:
            return None
        qty, committed = pos["qty"], pos["cash_committed"]
        fill = feed.apply_cost(pair, mid_price, "sell")
        comm = (qty * fill) * cfg.COMMISSION_PCT
        net = qty * fill - comm
        pnl = net - committed
        ret = pnl / committed if committed else 0.0
        cost = pos["entry_cost"] + (qty * (mid_price - fill) + comm)
        self._set_cash(self.get_cash() + net)
        self.conn.execute("""INSERT INTO fx_trades
            (pair, strategy, entry_time, exit_time, entry_fill, exit_fill, qty,
             pnl, return_pct, cost_paid, exit_reason, minutes_held)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pair, pos["strategy"], pos["entry_time"], _now_iso(),
             pos["entry_fill"], fill, qty, pnl, ret, cost, reason,
             minutes_held))
        self.conn.execute("DELETE FROM fx_positions WHERE pair=?", (pair,))
        self.conn.commit()
        return {"pnl": pnl, "return_pct": ret, "cost_paid": cost,
                "reason": reason}

    def all_trades(self):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM fx_trades ORDER BY id")
        return cur.fetchall()

    def reset(self):
        for t in ("fx_trades", "fx_positions", "fx_account"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()
        self._ensure_account()

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    l = ForexLedger()
    print(f"FX cash ${l.get_cash():.2f} | open {len(l.open_positions())} | "
          f"trades {len(l.all_trades())}")
    l.close()
