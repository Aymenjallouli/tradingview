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

app = FastAPI(title="Real-Time Paper Trading Engine")

# Claude Code as a near-real-time HELPER (commentary, not the trigger).
# Uses the `claude` CLI (your subscription), not the paid API.
HELPER = ClaudeHelper(ENGINE, interval_seconds=180)


@app.on_event("startup")
def _start_engine():
    """Run the engine in a daemon thread so the web server stays responsive."""
    t = threading.Thread(target=ENGINE.run, daemon=True)
    t.start()
    HELPER.start()


@app.get("/", response_class=HTMLResponse)
def index():
    import os
    with open(os.path.join(os.path.dirname(__file__), "index.html"),
              encoding="utf-8") as f:
        return f.read()


@app.get("/api/state")
def state():
    snap = ENGINE.snapshot()
    snap["claude"] = HELPER.snapshot()
    return JSONResponse(snap)


@app.get("/api/stream")
async def stream():
    """Server-Sent Events: push the engine snapshot on change + heartbeat.

    The dashboard opens ONE connection; the server pushes. No client polling.
    """
    async def gen():
        last = None
        ticks = 0
        while True:
            snap = ENGINE.snapshot()
            snap["claude"] = HELPER.snapshot()   # near-real-time commentary
            # Fingerprint on prices, per-strategy equity + trade counts.
            fp = json.dumps({
                "px": snap["prices"], "conn": snap["connected"],
                "s": [(s["key"], s["equity"], s["stats"]["trades"],
                       len(s["positions"])) for s in snap["strategies"]],
                "claude_at": snap["claude"].get("at"),
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
