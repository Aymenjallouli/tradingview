"""
app.py — Single entry point: runs the real-time engine + the dashboard.

Start it:
    python app.py

This:
  * launches the event-driven engine (engine.py) in a background thread, which
    connects to Binance's WebSocket and trades on live candle closes, and
  * serves a small real-time dashboard at http://HOST:PORT (default localhost).

On a VPS you run exactly this (via Docker or systemd — see the deploy guide).
It's a single always-on process: no cron, no polling, no separate workers.
"""

import asyncio
import json
import threading

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import uvicorn

import config
from engine import ENGINE
from claude_helper import ClaudeHelper
from scanner import Scanner
from arb_monitor import ArbMonitor
from smart_grid import SmartGrid

app = FastAPI(title="Real-Time Paper Trading Engine")

# Claude Code as a near-real-time HELPER (commentary, not the trigger).
# Uses the `claude` CLI (your subscription), not the paid API.
HELPER = ClaudeHelper(ENGINE, interval_seconds=180)

# Multi-market scanner: scans many liquid crypto markets, paper-trades the
# Market RADAR (support role, no trading). Classifies markets as ranging /
# trending and produces watchlists the grid module consumes. Enabled via
# SCAN_ENABLED (default on).
SCAN_ON = config.SCAN_ENABLED
SCANNER = Scanner(top_n=config.SCAN_TOP_N,
                  timeframe=config.SCAN_TIMEFRAME,
                  scan_seconds=config.SCAN_SECONDS) if SCAN_ON else None

# Cross-exchange arbitrage monitor (honest experiment, never real money).
ARB = ArbMonitor(config.DATABASE_PATH) if config.ARB_ENABLED else None

# Smart-grid: our most promising strategy (grids on ranging coins). It reads the
# radar's ranging watchlist during rotation.
GRID = SmartGrid(ENGINE.broker, scan_top=config.GRID_SCAN_TOP,
                 grids=config.GRID_COUNT, per_grid=config.GRID_PER,
                 radar=SCANNER, rescan_seconds=config.GRID_RESCAN) \
    if config.GRID_ENABLED else None


@app.on_event("startup")
def _start_engine():
    """Run the engine in a daemon thread so the web server stays responsive."""
    t = threading.Thread(target=ENGINE.run, daemon=True)
    t.start()
    HELPER.start()
    if SCANNER:
        threading.Thread(target=SCANNER.run, daemon=True).start()
    if ARB:
        threading.Thread(target=ARB.run, daemon=True).start()
    if GRID:
        threading.Thread(target=GRID.run, daemon=True).start()


@app.get("/", response_class=HTMLResponse)
def index():
    import os
    with open(os.path.join(os.path.dirname(__file__), "index.html"),
              encoding="utf-8") as f:
        return f.read()


def _enrich(snap):
    """Add Claude + radar + arb + grid data to an engine snapshot.

    Each add-on is guarded so a failure in one never 500s the whole endpoint —
    the dashboard degrades gracefully instead of going blank.
    """
    try:
        snap["claude"] = HELPER.snapshot()
    except Exception as exc:  # noqa: BLE001
        snap["claude"] = {"text": f"(helper error: {exc})", "at": None}
    if SCANNER:
        # Radar is support-only (no account/trading) — just its watchlists.
        try:
            snap["scanner"] = SCANNER.snapshot()
        except Exception as exc:  # noqa: BLE001
            print(f"[state] scanner snapshot error: {exc}", flush=True)
    if ARB:
        try:
            snap["arb"] = ARB.snapshot()
        except Exception as exc:  # noqa: BLE001
            print(f"[state] arb snapshot error: {exc}", flush=True)
    if GRID:
        try:
            snap["grid"] = GRID.snapshot()
        except Exception as exc:  # noqa: BLE001
            print(f"[state] grid snapshot error: {exc}", flush=True)
    return snap


@app.get("/api/state")
def state():
    try:
        return JSONResponse(_enrich(ENGINE.snapshot()))
    except Exception as exc:  # noqa: BLE001 - never 500 the dashboard
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(exc), "strategies": [],
                             "prices": {}, "connected": {}}, status_code=200)


@app.get("/api/stream")
async def stream():
    """Server-Sent Events: push the engine snapshot on change + heartbeat.

    The dashboard opens ONE connection; the server pushes. No client polling.
    """
    async def gen():
        last = None
        ticks = 0
        while True:
            snap = _enrich(ENGINE.snapshot())
            # Fingerprint on prices, per-strategy equity + trade counts, and
            # grid/radar state, so a meaningful change pushes an update.
            fp = json.dumps({
                "px": snap["prices"], "conn": snap["connected"],
                "s": [(s["key"], s["equity"], s["stats"]["trades"],
                       len(s["positions"])) for s in snap["strategies"]],
                "claude_at": snap.get("claude", {}).get("at"),
                "scan": snap.get("scanner", {}).get("last_scan"),
                "grid_eq": snap.get("grid", {}).get("equity"),
                "grid_tr": snap.get("grid", {}).get("total_trades"),
            }, sort_keys=True)
            if fp != last or ticks % 5 == 0:
                last = fp
                yield f"event: update\ndata: {json.dumps(snap)}\n\n"
            ticks += 1
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/healthz")
def healthz():
    """Health check for the VPS / Docker / uptime monitors."""
    snap = ENGINE.snapshot()
    total_trades = sum(s["stats"]["trades"] for s in snap["strategies"])
    return {"ok": True, "connected": snap["connected"],
            "strategies": [s["key"] for s in snap["strategies"]],
            "total_trades": total_trades}


if __name__ == "__main__":
    print(f"Real-time engine + dashboard starting on "
          f"http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}")
    print(f"Strategies enabled: {', '.join(config.ENABLED)}")
    print(f"Crypto: {', '.join(config.CRYPTO_SYMBOLS)} | "
          f"Forex: {', '.join(config.FOREX_SYMBOLS)}")
    print("Press Ctrl+C to stop.")
    uvicorn.run(app, host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT)
