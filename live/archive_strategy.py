"""
archive_strategy.py — Export a strategy's full trade log to archive/ before
deactivating it. Data is NEVER deleted from the DB — this just snapshots it to
CSV with a "cause of death" note, per the champion/challenger discipline.

Usage:
    python archive_strategy.py scalp   "Falsified: 0/69 wins; profit target smaller than round-trip cost. Killed by fees, not market."
    python archive_strategy.py scanner "Retired: PF 0.14. Not a strategy — repurposed as a radar (watchlist generator)."

Run this ON THE VPS (where the real trade data lives) once, to capture history.
"""

import csv
import os
import sqlite3
import sys

import config

ARCHIVE_DIR = os.path.join(os.path.dirname(__file__), "archive")


def archive(strategy: str, note: str, version: str = "v1"):
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("SELECT * FROM trades WHERE strategy=? ORDER BY id",
                        (strategy,)).fetchall()
    out = os.path.join(ARCHIVE_DIR, f"{strategy}_{version}_falsified.csv")

    with open(out, "w", newline="", encoding="utf-8") as f:
        # Header note as a comment line, then the data.
        f.write(f"# {note}\n")
        f.write(f"# archived {len(rows)} trades from strategy '{strategy}'\n")
        if rows:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            for r in rows:
                writer.writerow(dict(r))
        else:
            f.write("# (no trades found for this strategy in the DB)\n")

    conn.close()
    print(f"Archived {len(rows)} '{strategy}' trades -> {out}")
    print(f"Note: {note}")
    print("Data remains in the DB (not deleted). Deactivate the strategy in "
          "config (ENABLED) and app wiring.")
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python archive_strategy.py <strategy> \"<cause-of-death note>\" [version]")
        sys.exit(1)
    strat = sys.argv[1]
    note = sys.argv[2]
    ver = sys.argv[3] if len(sys.argv) > 3 else "v1"
    archive(strat, note, ver)
