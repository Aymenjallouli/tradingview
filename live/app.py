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

app = FastAPI(title="Real-Time Paper Trading Engine")

# Claude Code as a near-real-time HELPER (commentary, not the trigger).
# Uses the `claude` CLI (your subscription), not the paid API.
HELPER = ClaudeHelper(ENGINE, interval_seconds=180)

# Multi-market scanner: scans many liquid crypto markets, paper-trades the
# strongest signals into its own account. Scanning is periodic; EXITS on held
# positions are checked every 2s (near-realtime) so fills are close to what
# real money would get. Enabled via SCAN_ENABLED env (default on).
SCAN_ON = config.SCAN_ENABLED
SCANNER = Scanner(ENGINE.broker, top_n=config.SCAN_TOP_N,
                  hold_slots=config.SCAN_SLOTS,
                  timeframe=config.SCAN_TIMEFRAME,
                  scan_seconds=config.SCAN_SECONDS) if SCAN_ON else None


@app.on_event("startup")
def _start_engine():
    """Run the engine in a daemon thread so the web server stays responsive."""
    t = threading.Thread(target=ENGINE.run, daemon=True)
    t.start()
    HELPER.start()
    if SCANNER:
        threading.Thread(target=SCANNER.run, daemon=True).start()


@app.get("/", response_class=HTMLResponse)
def index():
    import os
    with open(os.path.join(os.path.dirname(__file__), "index.html"),
              encoding="utf-8") as f:
        return f.read()


def _enrich(snap):
    """Add Claude + scanner data to an engine snapshot (used by both endpoints)."""
    snap["claude"] = HELPER.snapshot()
    if SCANNER:
        # Scanner's own paper account, presented like a strategy card.
        b = ENGINE.broker
        prices = snap.get("prices", {})
        # Value scanner positions at last scanned price (fallback to entry).
        positions = []
        equity = b.cash("scanner")
        for p in b.open_positions("scanner"):
            mark = SCANNER._last_prices.get(p["symbol"], p["fill_price"])
            positions.append({
                "symbol": p["symbol"], "entry": round(p["entry_price"], 6),
                "price": round(mark, 6),
                "unrealized": round((mark - p["fill_price"]) * p["qty"], 4)})
            equity += p["qty"] * mark
        snap["scanner"] = {
            "account": {
                "key": "scanner", "label": "Scanner (many markets)",
                "market": "crypto", "timeframe": SCANNER.timeframe,
                "cash": round(b.cash("scanner"), 2),
                "equity": round(equity, 2),
                "start_capital": config.STARTING_CAPITAL,
                "positions": positions, "stats": b.stats("scanner"),
                "recent_trades": [{
                    "symbol": t["symbol"], "pnl": round(t["pnl"], 4),
                    "return_pct": round(t["return_pct"] * 100, 2),
                    "reason": t["exit_reason"], "exit_time": t["exit_time"],
                } for t in b.trades("scanner")[-15:][::-1]],
            },
            **SCANNER.snapshot(),
        }
    return snap


@app.get("/api/state")
def state():
    return JSONResponse(_enrich(ENGINE.snapshot()))


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
            # Fingerprint on prices, per-strategy equity + trade counts.
            fp = json.dumps({
                "px": snap["prices"], "conn": snap["connected"],
                "s": [(s["key"], s["equity"], s["stats"]["trades"],
                       len(s["positions"])) for s in snap["strategies"]],
                "claude_at": snap["claude"].get("at"),
                "scan": (snap.get("scanner", {}).get("last_scan")),
                "scan_eq": (snap.get("scanner", {}).get("account", {})
                            .get("equity")),
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
