"""
server.py — The web dashboard backend (FastAPI).

One local control panel for all three paper-trading experiments:
    * Run any backtest / optimizer and watch its output live.
    * Start / stop the live paper traders.
    * See equity, open positions, trades, and equity-curve charts.

Run it:
    python server.py
Then open http://localhost:8000 in your browser.

Everything runs on YOUR machine. Nothing is exposed to the internet unless you
deliberately change the host. It's paper money — no real funds, no broker keys.

Endpoints (the front-end calls these):
    GET  /                       -> the dashboard HTML page
    GET  /api/summary            -> equity/positions/trades for all 3 systems
    GET  /api/tasks              -> status of every runnable task
    POST /api/tasks/{key}/start  -> start a task (backtest or live trader)
    POST /api/tasks/{key}/stop   -> stop a running task
    GET  /api/tasks/{key}/log    -> tail the task's output log
    POST /api/reset/{system}     -> reset a system's ledger (fresh $50)
"""

import asyncio
import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

import db_reader
import process_manager as pm
from price_feed import FEED

app = FastAPI(title="Paper Trading Dashboard")


@app.on_event("startup")
def _start_feed():
    """Start the live Binance WebSocket price feed when the server boots."""
    FEED.start()

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))


# ---------------------------------------------------------------------------
# Serve the single-page UI.
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "index.html"), "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Data.
# ---------------------------------------------------------------------------
def _mark_to_market(summaries: dict, prices: dict) -> dict:
    """Add a live, mark-to-market equity to each system using real prices.

    Open positions are valued at the latest streamed price when we have one,
    else at their entry price (unchanged). Adds `live_equity` and per-position
    `live_price` / `unrealized` so the UI can show real-time P&L.
    """
    for s in summaries.values():
        equity = s["cash"]
        for pos in s["open_positions"]:
            live = prices.get(pos["symbol"])
            mark = live if live is not None else pos["entry"]
            pos["live_price"] = round(mark, 6)
            pos["unrealized"] = round((mark - pos["entry"]) * pos["qty"], 4)
            equity += pos["qty"] * mark
        s["live_equity"] = round(equity, 4)
    return summaries


@app.get("/api/summary")
def summary():
    summaries = db_reader.get_all_summaries()
    summaries = _mark_to_market(summaries, FEED.get_prices())
    return JSONResponse(summaries)


@app.get("/api/prices")
def prices():
    """Latest real-time prices + whether the live feed is connected."""
    return {"connected": FEED.is_connected(), "prices": FEED.get_prices()}


@app.get("/api/tasks")
def tasks():
    return JSONResponse(pm.all_status())


# ---------------------------------------------------------------------------
# Realtime stream (Server-Sent Events). The browser opens ONE connection and
# the server PUSHES an "update" event whenever state changes, so the UI is
# event-driven rather than the browser polling on a timer.
#
# We push on a change (equity/trades/task status differs from last snapshot)
# and send a heartbeat at least every few seconds so the connection stays warm.
# Reading three small SQLite tables is cheap, so this is effectively realtime
# for a paper system that updates on candle closes / 60s live polls.
# ---------------------------------------------------------------------------
def _snapshot():
    prices = FEED.get_prices()
    summaries = _mark_to_market(db_reader.get_all_summaries(), prices)
    return {
        "summary": summaries,
        "tasks": pm.all_status(),
        "prices": prices,
        "feed_connected": FEED.is_connected(),
    }


def _fingerprint(snap):
    """A cheap signature of the parts the UI cares about, to detect changes.

    Includes live prices (rounded) so a real market tick that moves an OPEN
    position's value pushes a realtime equity update. Prices with no open
    position anywhere still tick the ticker, so we include them too but coarser.
    """
    sig = {}
    for name, s in snap["summary"].items():
        sig[name] = (s["trades"], round(s["cash"], 4),
                     len(s["open_positions"]), s.get("live_equity"))
    for key, st in snap["tasks"].items():
        sig[key] = st["running"]
    # Round prices so we push on meaningful moves, not every micro-tick.
    for sym, px in snap["prices"].items():
        sig["px:" + sym] = round(px, 2)
    sig["feed"] = snap["feed_connected"]
    return json.dumps(sig, sort_keys=True)


@app.get("/api/stream")
async def stream():
    async def gen():
        last_fp = None
        ticks = 0
        while True:
            snap = _snapshot()
            fp = _fingerprint(snap)
            # Push when something changed, or every ~4s as a heartbeat so the
            # charts/log stay fresh and the client knows we're alive.
            if fp != last_fp or ticks % 4 == 0:
                last_fp = fp
                yield f"event: update\ndata: {json.dumps(snap)}\n\n"
            ticks += 1
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/tasks/{key}/start")
def start_task(key: str):
    try:
        mgr = pm.get(key)
    except KeyError:
        raise HTTPException(404, f"Unknown task: {key}")
    ok, msg = mgr.start()
    return {"ok": ok, "message": msg, "status": mgr.status()}


@app.post("/api/tasks/{key}/stop")
def stop_task(key: str):
    try:
        mgr = pm.get(key)
    except KeyError:
        raise HTTPException(404, f"Unknown task: {key}")
    ok, msg = mgr.stop()
    return {"ok": ok, "message": msg, "status": mgr.status()}


@app.get("/api/tasks/{key}/log")
def task_log(key: str, lines: int = 200):
    try:
        mgr = pm.get(key)
    except KeyError:
        raise HTTPException(404, f"Unknown task: {key}")
    return {"key": key, "log": mgr.tail(lines), "status": mgr.status()}


# ---------------------------------------------------------------------------
# Reset a system's ledger (fresh $50). Refuses if a live trader is running.
# ---------------------------------------------------------------------------
_RESET_LIVE_KEYS = {
    "scalp": ["scalp_live"],
    "forex": ["forex_live_swing", "forex_live_scalp"],
    "trend": [],
}


@app.post("/api/reset/{system}")
def reset_system(system: str):
    if system not in db_reader.SYSTEMS:
        raise HTTPException(404, f"Unknown system: {system}")

    # Safety: don't wipe a ledger while its live trader is running.
    for key in _RESET_LIVE_KEYS.get(system, []):
        if pm.get(key).is_running():
            raise HTTPException(
                409, f"Stop the live trader ({key}) before resetting.")

    _do_reset(system)
    return {"ok": True, "message": f"{system} ledger reset to "
            f"${db_reader.SYSTEMS[system]['start_capital']:.0f}"}


def _do_reset(system: str):
    """Clear a system's tables and restore starting cash, using each system's
    own ledger class so the schema stays authoritative.
    """
    import sys
    if system == "trend":
        sys.path.insert(0, ROOT)
        from paper_broker import PaperBroker
        b = PaperBroker()
        cur = b.conn.cursor()
        cur.execute("DELETE FROM trades")
        cur.execute("DELETE FROM positions")
        cur.execute("DELETE FROM account")
        b.conn.commit()
        b._ensure_account()
        b.close()
    elif system == "scalp":
        sys.path.insert(0, os.path.join(ROOT, "scalping"))
        import scalp_config
        scalp_config.DATABASE_PATH = db_reader.DB_PATH
        from scalp_ledger import ScalpLedger
        led = ScalpLedger(db_reader.DB_PATH)
        led.reset()
        led.close()
    elif system == "forex":
        sys.path.insert(0, os.path.join(ROOT, "forex"))
        import forex_config
        forex_config.DATABASE_PATH = db_reader.DB_PATH
        from forex_ledger import ForexLedger
        led = ForexLedger(db_reader.DB_PATH)
        led.reset()
        led.close()


if __name__ == "__main__":
    import uvicorn
    print("Dashboard running at  http://localhost:8000")
    print("Press Ctrl+C to stop.")
    uvicorn.run(app, host="127.0.0.1", port=8000)
