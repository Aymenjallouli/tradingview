"""
mt5_dashboard.py — Live web dashboard for the MT5 bot (full visibility).

Runs the trading runner in a background thread AND serves a web page that shows,
in real time:
  * account equity / balance / today's P&L
  * every open position with live P&L, SL, TP
  * the FULL SCAN: every strategy x symbol, its status (SIGNAL / holding /
    waiting), and how close breakout strategies are to firing
  * a streaming activity log of every signal, order, close, and heartbeat

Open http://localhost:8000 on this PC, or http://<this-pc-LAN-ip>:8000 on your
phone (same wifi). For remote/phone-over-internet access, front it with a
Cloudflare quick tunnel (see README).

    python mt5_dashboard.py            # live demo trading + dashboard
    python mt5_dashboard.py --dry      # dry-run (no orders) + dashboard

Everything the terminal logs is also visible here — nothing hidden.
"""

import sys
import threading
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

import mt5_log
from mt5_runner import MT5Runner

app = FastAPI(title="MT5 Bot Dashboard")

# The single runner instance (trades in a background thread).
RUNNER = MT5Runner(dry_run="--dry" in sys.argv)


@app.on_event("startup")
def _start_runner():
    t = threading.Thread(target=RUNNER.run, daemon=True)
    t.start()


@app.get("/api/state")
def api_state():
    try:
        snap = RUNNER.snapshot()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc), "connected": False})
    snap["server_time"] = datetime.now(timezone.utc).isoformat()
    snap["dry_run"] = RUNNER.dry_run
    # The FULL log stream (every module: order/orch/runner/mt5/momentum),
    # not just the orchestrator's sparse event list.
    snap["log"] = mt5_log.recent(200)
    return JSONResponse(snap)


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MT5 Bot — Live</title>
<style>
  :root{
    --bg:#0b0e14; --panel:#141925; --panel2:#1b2233; --line:#26304a;
    --text:#e6edf7; --muted:#8b98b0; --green:#2ec26a; --red:#ff5d5d;
    --amber:#ffb02e; --blue:#4d9fff; --accent:#7c5cff;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    font-size:14px;-webkit-text-size-adjust:100%}
  header{position:sticky;top:0;z-index:5;background:linear-gradient(180deg,#0b0e14,#0b0e14ee);
    padding:12px 16px;border-bottom:1px solid var(--line);
    display:flex;align-items:center;gap:14px;flex-wrap:wrap}
  header h1{font-size:16px;margin:0;font-weight:700;letter-spacing:.2px}
  .dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:6px}
  .dot.on{background:var(--green);box-shadow:0 0 8px var(--green)}
  .dot.off{background:var(--red);box-shadow:0 0 8px var(--red)}
  .pill{background:var(--panel2);border:1px solid var(--line);border-radius:999px;
    padding:4px 10px;font-size:12px;color:var(--muted)}
  .wrap{padding:14px;max-width:1200px;margin:0 auto}
  .grid{display:grid;gap:14px}
  @media(min-width:900px){.top{grid-template-columns:repeat(4,1fr)}}
  .top{grid-template-columns:repeat(2,1fr)}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px}
  .kpi .label{color:var(--muted);font-size:12px;margin-bottom:4px}
  .kpi .val{font-size:22px;font-weight:800}
  .green{color:var(--green)} .red{color:var(--red)} .amber{color:var(--amber)}
  .blue{color:var(--blue)} .muted{color:var(--muted)}
  h2{font-size:13px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);
    margin:20px 4px 8px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{text-align:left;color:var(--muted);font-weight:600;font-size:11px;
    text-transform:uppercase;letter-spacing:.4px;padding:8px 10px;border-bottom:1px solid var(--line)}
  td{padding:9px 10px;border-bottom:1px solid #1c2334}
  tr:last-child td{border-bottom:none}
  .tag{font-size:11px;padding:2px 7px;border-radius:6px;font-weight:700;letter-spacing:.3px}
  .t-signal{background:rgba(46,194,106,.16);color:var(--green)}
  .t-holding{background:rgba(77,159,255,.16);color:var(--blue)}
  .t-waiting{background:rgba(139,152,176,.14);color:var(--muted)}
  .t-nodata{background:rgba(255,93,93,.14);color:var(--red)}
  .mono{font-variant-numeric:tabular-nums;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .log{background:#0a0d13;border:1px solid var(--line);border-radius:12px;
    padding:10px;max-height:340px;overflow:auto;font-family:ui-monospace,Menlo,monospace;
    font-size:12px;line-height:1.55}
  .log div{padding:1px 0;white-space:pre-wrap;word-break:break-word}
  .log .ord{color:var(--amber)} .log .sig{color:var(--green)}
  .log .cls{color:var(--blue)} .log .hb{color:#5b6478}
  .bar{height:6px;background:#1c2334;border-radius:4px;overflow:hidden;margin-top:4px}
  .bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--amber),var(--green))}
  .sub{color:var(--muted);font-size:12px}
  .flash{animation:fl 1s ease}
  @keyframes fl{0%{background:rgba(124,92,255,.25)}100%{background:transparent}}
</style>
</head>
<body>
<header>
  <h1>🤖 MT5 Bot</h1>
  <span class="pill"><span id="dot" class="dot off"></span><span id="conn">connecting…</span></span>
  <span class="pill" id="mode">—</span>
  <span class="pill" id="poll">poll —</span>
  <span class="pill" id="clock">—</span>
  <span class="pill" id="refresh">updates every 3s</span>
</header>
<div class="wrap">
  <div class="grid top">
    <div class="card kpi"><div class="label">Equity</div><div class="val mono" id="equity">—</div></div>
    <div class="card kpi"><div class="label">Balance</div><div class="val mono" id="balance">—</div></div>
    <div class="card kpi"><div class="label">Open P&L</div><div class="val mono" id="openpl">—</div></div>
    <div class="card kpi"><div class="label">Open positions</div><div class="val mono" id="poscount">—</div></div>
  </div>

  <h2>Open Positions</h2>
  <div class="card" style="padding:4px 4px">
    <table><thead><tr>
      <th>Symbol</th><th>Side</th><th>Vol</th><th>Entry</th><th>SL</th><th>TP</th><th>P&L</th><th>Strategy</th>
    </tr></thead><tbody id="positions">
      <tr><td colspan="8" class="muted" style="padding:14px">Loading…</td></tr>
    </tbody></table>
  </div>

  <h2>Live Scan — what every strategy sees right now</h2>
  <div class="sub" style="margin:0 4px 8px">Sorted: signals &amp; near-misses first. “Distance” = how far price is from a breakout firing.</div>
  <div class="card" style="padding:4px 4px">
    <table><thead><tr>
      <th>Strategy</th><th>Symbol</th><th>Status</th><th>Detail</th><th>Distance to signal</th>
    </tr></thead><tbody id="scan">
      <tr><td colspan="5" class="muted" style="padding:14px">Loading…</td></tr>
    </tbody></table>
  </div>

  <h2>Activity Log — every signal, order, close &amp; heartbeat</h2>
  <div class="log" id="log">waiting for data…</div>
</div>

<script>
const $ = s => document.querySelector(s);
const fmt = (n,d=2) => (n==null||isNaN(n))?'—':Number(n).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const cls = n => n>0?'green':(n<0?'red':'');
let lastLogKey = '';

async function tick(){
  let s;
  try{ s = await (await fetch('/api/state',{cache:'no-store'})).json(); }
  catch(e){ setConn(false,'server unreachable'); return; }

  const acc = s.account;
  const connected = s.connected && acc;
  setConn(connected, connected ? (acc.server||'demo') : (s.status||'not connected'));

  $('#mode').textContent = s.dry_run ? 'DRY-RUN (no orders)' : 'LIVE DEMO';
  $('#mode').className = 'pill ' + (s.dry_run ? 'amber' : 'green');
  $('#poll').textContent = 'poll #' + (s.poll_count ?? '—');
  $('#clock').textContent = new Date(s.server_time).toLocaleTimeString();

  if(acc){
    $('#equity').textContent = '$'+fmt(acc.equity);
    $('#balance').textContent = '$'+fmt(acc.balance);
  }
  const pos = s.open_positions||[];
  const openpl = pos.reduce((a,p)=>a+(p.profit||0),0);
  const e = $('#openpl'); e.textContent = (openpl>=0?'+$':'-$')+fmt(Math.abs(openpl));
  e.className = 'val mono '+cls(openpl);
  $('#poscount').textContent = pos.length;

  // positions
  $('#positions').innerHTML = pos.length ? pos.map(p=>`
    <tr><td><b>${p.symbol}</b></td>
    <td class="${p.type==='buy'?'green':'red'}">${p.type.toUpperCase()}</td>
    <td class="mono">${p.volume}</td>
    <td class="mono">${fmt(p.price_open,p.price_open<10?5:2)}</td>
    <td class="mono muted">${p.sl?fmt(p.sl,p.sl<10?5:2):'—'}</td>
    <td class="mono muted">${p.tp?fmt(p.tp,p.tp<10?5:2):'—'}</td>
    <td class="mono ${cls(p.profit)}">${p.profit>=0?'+':''}${fmt(p.profit)}</td>
    <td class="muted">${p.strategy||''}</td></tr>`).join('')
    : `<tr><td colspan="8" class="muted" style="padding:14px">No open positions.</td></tr>`;

  // scan
  const scan = s.scan||[];
  $('#scan').innerHTML = scan.length ? scan.map(x=>{
    const tag = x.status==='SIGNAL'?'t-signal':x.status==='holding'?'t-holding':
                x.status==='no-data'?'t-nodata':'t-waiting';
    let dist='—';
    if(x.distance!=null){
      if(x.distance<=0) dist='<span class="green">breakout!</span>';
      else{
        const pct=Math.max(0,Math.min(100,100-(x.distance/8*100)));
        dist=`<span class="mono">+${fmt(x.distance,2)}%</span>
              <div class="bar"><i style="width:${pct}%"></i></div>`;
      }
    }
    return `<tr><td class="muted">${x.strategy}</td><td><b>${x.symbol}</b></td>
      <td><span class="tag ${tag}">${x.status}</span></td>
      <td class="sub">${x.detail||''}</td><td>${dist}</td></tr>`;
  }).join('') : `<tr><td colspan="5" class="muted" style="padding:14px">Scan starting…</td></tr>`;

  // log
  const log = s.log||[];
  const key = log.length? (log[0].time+log[0].msg):'';
  if(key!==lastLogKey){
    lastLogKey = key;
    $('#log').innerHTML = log.map(l=>{
      const m=l.msg||''; let c='';
      if(/OPENED|WOULD|REQUEST/.test(m))c='ord';
      else if(/SIGNAL|signal/.test(m))c='sig';
      else if(/CLOSED|CLOSE/.test(m))c='cls';
      else if(/alive|poll/.test(m))c='hb';
      const t=new Date(l.time).toLocaleTimeString();
      return `<div class="${c}">[${t}] ${m}</div>`;
    }).join('');
  }
}
function setConn(ok,txt){
  $('#dot').className='dot '+(ok?'on':'off');
  $('#conn').textContent=txt;
}
tick(); setInterval(tick,3000);
</script>
</body>
</html>
"""


import os
PORT = int(os.getenv("MT5_DASH_PORT", "8800"))   # 8800 avoids Docker/WSL on 8000

if __name__ == "__main__":
    print("=" * 62)
    print(" MT5 DASHBOARD")
    print(f" Open on THIS PC : http://localhost:{PORT}")
    print(f" Open on PHONE   : http://<this-pc-LAN-ip>:{PORT}  (same wifi)")
    print("=" * 62)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
