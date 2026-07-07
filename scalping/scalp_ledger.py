"""
scalp_ledger.py — SQLite ledger for the SCALPING experiment.

Uses the SAME database file as the trend system (../trades.db) but writes to
its OWN tables, prefixed `scalp_`, so the two experiments never mix:
    scalp_account    : single row, current virtual cash
    scalp_positions  : currently-open scalp positions (one per symbol)
    scalp_trades     : completed scalp trades (the permanent log)

Applies the same realistic costs as the backtester. Used by the live paper
scalper (Module B) and read by the verdict report (Module C).
"""

import sqlite3
from datetime import datetime, timezone

import scalp_config as cfg


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_slippage(price: float, side: str) -> float:
    if side == "buy":
        return price * (1 + cfg.SLIPPAGE_PCT)
    return price * (1 - cfg.SLIPPAGE_PCT)


class ScalpLedger:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or cfg.DATABASE_PATH
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._ensure_account()

    def _create_tables(self):
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scalp_account (
                id   INTEGER PRIMARY KEY CHECK (id = 1),
                cash REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scalp_positions (
                symbol         TEXT PRIMARY KEY,
                qty            REAL NOT NULL,
                entry_fill     REAL NOT NULL,
                cash_committed REAL NOT NULL,
                entry_fee      REAL NOT NULL,
                entry_time     TEXT NOT NULL,
                entry_bar_ms   INTEGER NOT NULL  -- candle open time (ms) of entry
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scalp_trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT NOT NULL,
                entry_time  TEXT NOT NULL,
                exit_time   TEXT NOT NULL,
                entry_fill  REAL NOT NULL,
                exit_fill   REAL NOT NULL,
                qty         REAL NOT NULL,
                pnl         REAL NOT NULL,
                return_pct  REAL NOT NULL,
                fees_paid   REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                minutes_held INTEGER NOT NULL
            )
        """)
        self.conn.commit()

    def _ensure_account(self):
        cur = self.conn.cursor()
        cur.execute("SELECT cash FROM scalp_account WHERE id = 1")
        if cur.fetchone() is None:
            cur.execute("INSERT INTO scalp_account (id, cash) VALUES (1, ?)",
                        (cfg.STARTING_CAPITAL,))
            self.conn.commit()

    # ---- account -----------------------------------------------------------
    def get_cash(self) -> float:
        cur = self.conn.cursor()
        cur.execute("SELECT cash FROM scalp_account WHERE id = 1")
        return float(cur.fetchone()["cash"])

    def _set_cash(self, cash: float):
        cur = self.conn.cursor()
        cur.execute("UPDATE scalp_account SET cash = ? WHERE id = 1", (cash,))
        self.conn.commit()

    def get_position(self, symbol: str):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM scalp_positions WHERE symbol = ?", (symbol,))
        return cur.fetchone()

    def has_position(self, symbol: str) -> bool:
        return self.get_position(symbol) is not None

    def open_positions(self):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM scalp_positions")
        return cur.fetchall()

    def get_equity(self, prices: dict = None) -> float:
        prices = prices or {}
        equity = self.get_cash()
        for pos in self.open_positions():
            price = prices.get(pos["symbol"], pos["entry_fill"])
            equity += pos["qty"] * price
        return equity

    # ---- fills -------------------------------------------------------------
    def buy(self, symbol: str, raw_price: float, entry_bar_ms: int) -> bool:
        """Open a scalp position. `raw_price` is the fill price BEFORE slippage
        (the live loop passes the next candle's open). Returns True if opened.
        """
        if self.has_position(symbol):
            return False
        equity = self.get_equity()
        cash = self.get_cash()
        cash_committed = min(equity * cfg.POSITION_SIZE_PCT, cash)
        if cash_committed <= 0:
            return False

        fill = _apply_slippage(raw_price, "buy")
        entry_fee = cash_committed * cfg.FEE_PCT
        qty = (cash_committed - entry_fee) / fill

        self._set_cash(cash - cash_committed)
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO scalp_positions
              (symbol, qty, entry_fill, cash_committed, entry_fee,
               entry_time, entry_bar_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (symbol, qty, fill, cash_committed, entry_fee,
              _now_iso(), entry_bar_ms))
        self.conn.commit()
        return True

    def sell(self, symbol: str, raw_price: float, reason: str,
             minutes_held: int) -> dict | None:
        """Close a scalp position. Returns a dict describing the trade, or None
        if there was no open position.
        """
        pos = self.get_position(symbol)
        if pos is None:
            return None

        qty = pos["qty"]
        cash_committed = pos["cash_committed"]
        fill = _apply_slippage(raw_price, "sell")
        gross = qty * fill
        exit_fee = gross * cfg.FEE_PCT
        net_proceeds = gross - exit_fee
        pnl = net_proceeds - cash_committed
        ret = pnl / cash_committed if cash_committed else 0.0
        fees_paid = pos["entry_fee"] + exit_fee

        self._set_cash(self.get_cash() + net_proceeds)
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO scalp_trades
              (symbol, entry_time, exit_time, entry_fill, exit_fill, qty,
               pnl, return_pct, fees_paid, exit_reason, minutes_held)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, pos["entry_time"], _now_iso(), pos["entry_fill"], fill,
              qty, pnl, ret, fees_paid, reason, minutes_held))
        cur.execute("DELETE FROM scalp_positions WHERE symbol = ?", (symbol,))
        self.conn.commit()

        return {"symbol": symbol, "pnl": pnl, "return_pct": ret,
                "fees_paid": fees_paid, "reason": reason}

    # ---- reporting ---------------------------------------------------------
    def all_trades(self):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM scalp_trades ORDER BY id")
        return cur.fetchall()

    def reset(self):
        """Wipe scalp tables and restore starting cash (fresh experiment)."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM scalp_trades")
        cur.execute("DELETE FROM scalp_positions")
        cur.execute("DELETE FROM scalp_account")
        self.conn.commit()
        self._ensure_account()

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    led = ScalpLedger()
    print(f"Scalp cash: ${led.get_cash():.2f} | "
          f"open: {len(led.open_positions())} | "
          f"trades: {len(led.all_trades())}")
    led.close()
