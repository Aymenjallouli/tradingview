"""
paper_broker.py — Module 3: the paper (simulated) broker.

This is the "money" part of the live system. It:
  * Keeps a SQLite database (trades.db) with two tables: positions & trades.
  * Tracks virtual cash (starts at $50), open positions, and P&L.
  * Applies fees (0.1%/side) and slippage (0.05%) on every fill — the SAME
    costs the backtester uses.
  * Enforces one open position per symbol.
  * Can export the full trade log to CSV.

Both the signal engine (Module 1) and the webhook server (Module 2) call into
this same broker, so live behaviour matches the backtest.

Beginner mental model of the tables:
  account   : a single row holding your current cash balance.
  positions : one row per currently-OPEN position (symbol, qty, entry price).
  trades    : one row per COMPLETED round-trip trade (for the log & stats).
"""

import csv
import sqlite3
from datetime import datetime, timezone

import config


# ---------------------------------------------------------------------------
# Fill helpers (identical logic to the backtester)
# ---------------------------------------------------------------------------
def _apply_slippage(price: float, side: str) -> float:
    """Buy fills a bit higher, sell fills a bit lower — realistic slippage."""
    if side == "buy":
        return price * (1 + config.SLIPPAGE_PCT)
    return price * (1 - config.SLIPPAGE_PCT)


def _now_iso() -> str:
    """Current UTC time as an ISO string (nice and sortable in the DB)."""
    return datetime.now(timezone.utc).isoformat()


class PaperBroker:
    """A tiny simulated broker backed by SQLite."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DATABASE_PATH
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._ensure_account()

    # ------------------------------------------------------------------
    # Schema setup
    # ------------------------------------------------------------------
    def _create_tables(self):
        cur = self.conn.cursor()

        # Single-row account table for cash.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS account (
                id      INTEGER PRIMARY KEY CHECK (id = 1),
                cash    REAL NOT NULL
            )
        """)

        # Currently open positions (max one per symbol).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                symbol       TEXT PRIMARY KEY,
                qty          REAL NOT NULL,
                entry_price  REAL NOT NULL,   -- raw candle price at entry
                fill_price   REAL NOT NULL,   -- price after slippage
                cash_committed REAL NOT NULL, -- cash deployed into the trade
                entry_time   TEXT NOT NULL
            )
        """)

        # Completed round-trip trades (the permanent log).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT NOT NULL,
                entry_time   TEXT NOT NULL,
                exit_time    TEXT NOT NULL,
                entry_price  REAL NOT NULL,
                exit_price   REAL NOT NULL,
                fill_entry   REAL NOT NULL,
                fill_exit    REAL NOT NULL,
                qty          REAL NOT NULL,
                pnl          REAL NOT NULL,
                return_pct   REAL NOT NULL,
                exit_reason  TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def _ensure_account(self):
        """Create the account row with the starting cash if it doesn't exist."""
        cur = self.conn.cursor()
        cur.execute("SELECT cash FROM account WHERE id = 1")
        if cur.fetchone() is None:
            cur.execute("INSERT INTO account (id, cash) VALUES (1, ?)",
                        (config.STARTING_CAPITAL,))
            self.conn.commit()

    # ------------------------------------------------------------------
    # Account helpers
    # ------------------------------------------------------------------
    def get_cash(self) -> float:
        cur = self.conn.cursor()
        cur.execute("SELECT cash FROM account WHERE id = 1")
        return float(cur.fetchone()["cash"])

    def _set_cash(self, cash: float):
        cur = self.conn.cursor()
        cur.execute("UPDATE account SET cash = ? WHERE id = 1", (cash,))
        self.conn.commit()

    def get_position(self, symbol: str):
        """Return the open position row for `symbol`, or None."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,))
        return cur.fetchone()

    def has_position(self, symbol: str) -> bool:
        return self.get_position(symbol) is not None

    def open_positions(self):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM positions")
        return cur.fetchall()

    # ------------------------------------------------------------------
    # Equity (cash + value of open positions)
    # ------------------------------------------------------------------
    def get_equity(self, prices: dict = None) -> float:
        """Total account value = cash + current value of open positions.

        `prices` is an optional dict of {symbol: current_price}. Positions
        whose price isn't provided are valued at their entry fill price.
        """
        prices = prices or {}
        equity = self.get_cash()
        for pos in self.open_positions():
            symbol = pos["symbol"]
            price = prices.get(symbol, pos["fill_price"])
            equity += pos["qty"] * price
        return equity

    # ------------------------------------------------------------------
    # BUY — open a position
    # ------------------------------------------------------------------
    def buy(self, symbol: str, price: float) -> bool:
        """Open a long position in `symbol` at market `price`.

        Uses 95% of current EQUITY as the cash to deploy. Applies slippage and
        the entry fee. Refuses if a position is already open for this symbol.

        Returns True if the trade was opened, False otherwise.
        """
        if self.has_position(symbol):
            print(f"  [broker] Already in a position for {symbol}; skipping buy.")
            return False

        equity = self.get_equity()
        cash = self.get_cash()

        cash_committed = equity * config.POSITION_SIZE_PCT
        # Can't deploy more cash than we actually have on hand.
        if cash_committed > cash:
            cash_committed = cash
        if cash_committed <= 0:
            print(f"  [broker] No cash available to buy {symbol}.")
            return False

        fill = _apply_slippage(price, "buy")
        entry_fee = cash_committed * config.FEE_PCT
        qty = (cash_committed - entry_fee) / fill

        # Deduct the committed cash from the balance.
        self._set_cash(cash - cash_committed)

        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO positions
                (symbol, qty, entry_price, fill_price, cash_committed, entry_time)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (symbol, qty, price, fill, cash_committed, _now_iso()))
        self.conn.commit()

        print(f"  [broker] BOUGHT {qty:.6f} {symbol} @ {fill:.4f} "
              f"(committed ${cash_committed:.2f}, fee ${entry_fee:.4f})")
        return True

    # ------------------------------------------------------------------
    # SELL — close a position
    # ------------------------------------------------------------------
    def sell(self, symbol: str, price: float, reason: str = "signal") -> bool:
        """Close the open position in `symbol` at market `price`.

        Applies slippage and the exit fee, computes net P&L, returns the cash
        (committed +/- P&L) to the balance, records the completed trade, and
        removes the open position. Returns True if a position was closed.
        """
        pos = self.get_position(symbol)
        if pos is None:
            print(f"  [broker] No open position for {symbol}; nothing to sell.")
            return False

        qty = pos["qty"]
        entry_price = pos["entry_price"]
        cash_committed = pos["cash_committed"]

        fill = _apply_slippage(price, "sell")
        gross_proceeds = qty * fill
        exit_fee = gross_proceeds * config.FEE_PCT
        net_proceeds = gross_proceeds - exit_fee

        pnl = net_proceeds - cash_committed
        return_pct = pnl / cash_committed if cash_committed else 0.0

        # Return the net proceeds to cash.
        self._set_cash(self.get_cash() + net_proceeds)

        cur = self.conn.cursor()
        # Record the completed trade.
        cur.execute("""
            INSERT INTO trades
                (symbol, entry_time, exit_time, entry_price, exit_price,
                 fill_entry, fill_exit, qty, pnl, return_pct, exit_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, pos["entry_time"], _now_iso(), entry_price, price,
              pos["fill_price"], fill, qty, pnl, return_pct, reason))
        # Remove the open position.
        cur.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
        self.conn.commit()

        print(f"  [broker] SOLD {qty:.6f} {symbol} @ {fill:.4f} "
              f"({reason}) P&L ${pnl:+.4f} ({return_pct*100:+.2f}%)")
        return True

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------
    def all_trades(self):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM trades ORDER BY id")
        return cur.fetchall()

    def recent_trades(self, since_iso: str):
        """Trades whose EXIT time is on/after `since_iso` (ISO string)."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM trades WHERE exit_time >= ? ORDER BY id",
                    (since_iso,))
        return cur.fetchall()

    def export_csv(self, path: str = None) -> str:
        """Write the full trade log to a CSV file. Returns the file path."""
        path = path or config.TRADE_LOG_CSV
        trades = self.all_trades()

        fieldnames = ["id", "symbol", "entry_time", "exit_time",
                      "entry_price", "exit_price", "fill_entry", "fill_exit",
                      "qty", "pnl", "return_pct", "exit_reason"]

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for t in trades:
                writer.writerow({k: t[k] for k in fieldnames})

        print(f"  [broker] Exported {len(trades)} trades to {path}")
        return path

    def close(self):
        self.conn.close()


# ---------------------------------------------------------------------------
# Allow `python paper_broker.py` to export the CSV as a convenience.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    broker = PaperBroker()
    print(f"Cash: ${broker.get_cash():.2f}")
    print(f"Open positions: {len(broker.open_positions())}")
    print(f"Completed trades: {len(broker.all_trades())}")
    broker.export_csv()
    broker.close()
