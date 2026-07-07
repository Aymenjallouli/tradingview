"""
db_reader.py — Read-only access to all three experiments' data.

The dashboard uses this to show equity, open positions, and trades for:
    * trend  (tables: account, positions, trades)
    * scalp  (tables: scalp_account, scalp_positions, scalp_trades)
    * forex  (tables: fx_account, fx_positions, fx_trades)

All three live in the SAME SQLite file (../trades.db). This module NEVER
writes — it only reads, so it can't corrupt an experiment that's running.

Each system exposes the same shape to the dashboard via `get_system_summary`:
    { cash, equity_realized, trades, wins, win_rate, profit_factor,
      net_pnl, open_positions[], recent_trades[], equity_curve[] }
so the front-end can treat all three identically.
"""

import os
import sqlite3

# The shared database lives in the project root (one level up).
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "trades.db")

# Per-system table + column mapping so we can use one code path for all three.
SYSTEMS = {
    "trend": {
        "label": "Trend (stocks/crypto, 4h)",
        "account": "account",
        "positions": "positions",
        "trades": "trades",
        "start_capital": 50.0,
        "symbol_col": "symbol",
        "pos_entry_col": "entry_price",
        # trades table has no fees/cost column; report 0.
        "cost_col": None,
    },
    "scalp": {
        "label": "Crypto scalp (1m)",
        "account": "scalp_account",
        "positions": "scalp_positions",
        "trades": "scalp_trades",
        "start_capital": 50.0,
        "symbol_col": "symbol",
        "pos_entry_col": "entry_fill",
        "cost_col": "fees_paid",
    },
    "forex": {
        "label": "Forex (scalp + swing)",
        "account": "fx_account",
        "positions": "fx_positions",
        "trades": "fx_trades",
        "start_capital": 50.0,
        "symbol_col": "pair",
        "pos_entry_col": "entry_fill",
        "cost_col": "cost_paid",
    },
}


def _connect():
    """Open a read-only connection. Returns None if the DB doesn't exist yet."""
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn, name):
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def _safe_rows(conn, sql, params=()):
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []


def get_system_summary(system: str) -> dict:
    """Return a uniform summary dict for one system (see module docstring)."""
    cfg = SYSTEMS[system]
    empty = {
        "system": system, "label": cfg["label"], "exists": False,
        "cash": cfg["start_capital"], "start_capital": cfg["start_capital"],
        "net_pnl": 0.0, "trades": 0, "wins": 0, "win_rate": 0.0,
        "profit_factor": 0.0, "total_cost": 0.0, "open_positions": [],
        "recent_trades": [], "equity_curve": [cfg["start_capital"]],
    }

    conn = _connect()
    if conn is None:
        return empty
    try:
        if not _table_exists(conn, cfg["trades"]):
            return empty

        # Cash.
        cash = cfg["start_capital"]
        if _table_exists(conn, cfg["account"]):
            row = _safe_rows(conn, f"SELECT cash FROM {cfg['account']} WHERE id=1")
            if row:
                cash = float(row[0]["cash"])

        # Trades.
        trades = _safe_rows(conn, f"SELECT * FROM {cfg['trades']} ORDER BY id")
        n = len(trades)
        wins = [t for t in trades if t["pnl"] > 0]
        gross_win = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
        pf = (gross_win / gross_loss) if gross_loss > 0 \
            else (float("inf") if gross_win > 0 else 0.0)
        net = sum(t["pnl"] for t in trades)

        cost_col = cfg["cost_col"]
        total_cost = sum(t[cost_col] for t in trades) if cost_col else 0.0

        # Open positions.
        positions = []
        if _table_exists(conn, cfg["positions"]):
            for p in _safe_rows(conn, f"SELECT * FROM {cfg['positions']}"):
                positions.append({
                    "symbol": p[cfg["symbol_col"]],
                    "qty": round(p["qty"], 8),
                    "entry": round(p[cfg["pos_entry_col"]], 6),
                    "strategy": (p["strategy"] if "strategy" in p.keys()
                                 else system),
                })

        # Recent trades (last 25, newest first) — normalized shape.
        recent = []
        for t in trades[-25:][::-1]:
            recent.append({
                "symbol": t[cfg["symbol_col"]],
                "pnl": round(t["pnl"], 4),
                "return_pct": round(t["return_pct"] * 100, 3),
                "reason": t["exit_reason"],
                "exit_time": t["exit_time"],
                "strategy": (t["strategy"] if "strategy" in t.keys()
                             else system),
            })

        # Equity curve (realized, per closed trade).
        eq = cfg["start_capital"]
        curve = [round(eq, 4)]
        for t in trades:
            eq += t["pnl"]
            curve.append(round(eq, 4))

        return {
            "system": system, "label": cfg["label"], "exists": True,
            "cash": round(cash, 4), "start_capital": cfg["start_capital"],
            "net_pnl": round(net, 4), "trades": n, "wins": len(wins),
            "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
            "profit_factor": (None if pf == float("inf") else round(pf, 2)),
            "total_cost": round(total_cost, 4),
            "open_positions": positions, "recent_trades": recent,
            "equity_curve": curve,
        }
    finally:
        conn.close()


def get_all_summaries() -> dict:
    """Summaries for all three systems, keyed by system name."""
    return {name: get_system_summary(name) for name in SYSTEMS}
