"""
mt5_dashboard.py — Live RADAR dashboard for the MT5 bot.

An always-moving, air-traffic-control-style radar that plots every market as a
blip, sweeps continuously, and flashes when a signal fires or a trade opens.
Plus live equity, open positions, the full scan, and a streaming activity log.

Runs the trading runner in a background thread AND serves the page.

Open http://localhost:8800 on this PC, or http://<this-pc-LAN-ip>:8800 on your
phone (same wifi).

    python mt5_dashboard.py            # live demo trading + dashboard
    python mt5_dashboard.py --dry      # dry-run (no orders) + dashboard
    MT5_GOLD_FOCUS=1 python mt5_dashboard.py   # metals-only specialist
"""

import os
import sys
import threading
from datetime import datetime, timezone

# Load live/mt5/.env before anything reads config (Telegram, focus mode, etc.).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:  # noqa: BLE001
    pass

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

import mt5_log
from mt5_runner import MT5Runner

app = FastAPI(title="MT5 Radar")

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
<title>◎ MT5 RADAR</title>
<style>
  :root{
    --bg:#04070a; --bg2:#070c12; --grid:#0d2818; --scan:#00ff9c;
    --text:#cfe9df; --muted:#5a7d70; --amber:#ffcf3a; --red:#ff4d5e;
    --blue:#4dd2ff; --green:#00ff9c; --panel:#0a1119; --line:#12321f;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%}
  body{background:radial-gradient(ellipse at 30% 0%,#0a1a14,#04070a 60%);
    color:var(--text);font-family:"SF Mono",ui-monospace,"Cascadia Code",Menlo,monospace;
    overflow-x:hidden;-webkit-text-size-adjust:100%}
  .top{display:flex;align-items:center;gap:16px;padding:12px 18px;
    border-bottom:1px solid var(--line);background:linear-gradient(180deg,#061019,#04070acc);
    position:sticky;top:0;z-index:20;backdrop-filter:blur(6px);flex-wrap:wrap}
  .brand{font-size:18px;font-weight:800;letter-spacing:3px;color:var(--green);
    text-shadow:0 0 12px #00ff9c88}
  .brand small{color:var(--muted);letter-spacing:1px;font-weight:400}
  .stat{display:flex;flex-direction:column;line-height:1.15}
  .stat .k{font-size:9px;color:var(--muted);letter-spacing:2px;text-transform:uppercase}
  .stat .v{font-size:17px;font-weight:700;font-variant-numeric:tabular-nums}
  .grow{flex:1}
  .led{display:inline-block;width:8px;height:8px;border-radius:50%;
    background:var(--green);box-shadow:0 0 10px var(--green);animation:pulse 1.4s infinite}
  .led.off{background:var(--red);box-shadow:0 0 10px var(--red)}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
  .wrap{display:grid;grid-template-columns:1fr;gap:16px;padding:16px;max-width:1400px;margin:0 auto}
  @media(min-width:980px){.wrap{grid-template-columns:minmax(360px,560px) 1fr}}
  .radar-card{background:var(--panel);border:1px solid var(--line);border-radius:16px;
    padding:14px;position:relative;overflow:hidden}
  .radar-wrap{position:relative;width:100%;aspect-ratio:1;max-width:560px;margin:0 auto}
  canvas{width:100%;height:100%;display:block}
  .side{display:flex;flex-direction:column;gap:14px;min-width:0}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:12px 14px}
  .card h3{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);
    margin-bottom:10px;display:flex;align-items:center;gap:8px}
  .card h3 .dot{width:6px;height:6px;border-radius:50%;background:var(--green);
    box-shadow:0 0 8px var(--green)}
  table{width:100%;border-collapse:collapse;font-size:12px}
  th{text-align:left;color:var(--muted);font-weight:600;font-size:9px;letter-spacing:1px;
    text-transform:uppercase;padding:5px 8px;border-bottom:1px solid var(--line)}
  td{padding:7px 8px;border-bottom:1px solid #0c1a13;font-variant-numeric:tabular-nums}
  tr:last-child td{border-bottom:none}
  .up{color:var(--green)} .down{color:var(--red)} .muted{color:var(--muted)}
  .tag{font-size:9px;padding:2px 7px;border-radius:5px;font-weight:700;letter-spacing:.5px}
  .t-sig{background:#00ff9c22;color:var(--green);box-shadow:0 0 12px #00ff9c33}
  .t-acted{background:#ffcf3a22;color:var(--amber)}
  .t-hold{background:#4dd2ff22;color:var(--blue)}
  .t-wait{background:#5a7d7018;color:var(--muted)}
  .log{max-height:280px;overflow:auto;font-size:11px;line-height:1.7}
  .log div{white-space:pre-wrap;word-break:break-word;opacity:0;animation:fade .4s forwards}
  @keyframes fade{to{opacity:1}}
  .log .ord{color:var(--amber)} .log .sig{color:var(--green);text-shadow:0 0 8px #00ff9c55}
  .log .cls{color:var(--blue)} .log .hb{color:#3a5248}
  .signals-strip{display:flex;gap:8px;flex-wrap:wrap;min-height:30px}
  .chip{background:#00ff9c14;border:1px solid #00ff9c44;border-radius:20px;padding:5px 12px;
    font-size:11px;font-weight:700;color:var(--green);animation:chipIn .5s;
    box-shadow:0 0 14px #00ff9c22}
  @keyframes chipIn{from{transform:scale(.7);opacity:0}to{transform:scale(1);opacity:1}}
  .empty{color:var(--muted);font-size:11px;padding:6px}
  .bignum{font-size:26px;font-weight:800;font-variant-numeric:tabular-nums}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
  .kpi{background:linear-gradient(180deg,#0b1720,#08111a);border:1px solid var(--line);
    border-radius:12px;padding:10px 12px;text-align:center}
  .kpi .k{font-size:9px;color:var(--muted);letter-spacing:1px;text-transform:uppercase}
  .kpi .v{font-size:18px;font-weight:800;margin-top:3px;font-variant-numeric:tabular-nums}
  .flashbar{position:fixed;top:0;left:0;right:0;height:3px;background:var(--green);
    transform:scaleX(0);transform-origin:left;box-shadow:0 0 20px var(--green);z-index:40}
</style>
</head>
<body>
<div class="flashbar" id="flashbar"></div>
<div class="top">
  <div class="brand">◎ MT5&nbsp;RADAR <small id="mode">—</small></div>
  <div class="stat"><span class="k"><span class="led" id="led"></span> Link</span><span class="v" id="conn" style="font-size:12px">—</span></div>
  <div class="stat"><span class="k">Equity</span><span class="v" id="equity">—</span></div>
  <div class="stat"><span class="k">Open P&L</span><span class="v" id="openpl">—</span></div>
  <div class="stat"><span class="k">Sweep</span><span class="v" id="poll" style="font-size:12px">—</span></div>
  <div class="grow"></div>
  <div class="stat"><span class="k">Time</span><span class="v" id="clock" style="font-size:12px">—</span></div>
</div>

<div class="wrap">
  <!-- RADAR -->
  <div class="radar-card">
    <div class="radar-wrap"><canvas id="radar"></canvas></div>
    <div style="margin-top:10px">
      <div class="card" style="border:none;background:transparent;padding:0">
        <h3><span class="dot"></span> LIVE SIGNALS</h3>
        <div class="signals-strip" id="signals"><span class="empty">scanning…</span></div>
      </div>
    </div>
  </div>

  <!-- SIDE -->
  <div class="side">
    <div class="kpis">
      <div class="kpi"><div class="k">Balance</div><div class="v" id="balance">—</div></div>
      <div class="kpi"><div class="k">Positions</div><div class="v" id="poscount">—</div></div>
      <div class="kpi"><div class="k">Markets</div><div class="v" id="mktcount">—</div></div>
      <div class="kpi"><div class="k">Signals</div><div class="v up" id="sigcount">—</div></div>
    </div>

    <div class="card">
      <h3><span class="dot"></span> Open Positions</h3>
      <table><thead><tr><th>Market</th><th>Side</th><th>Vol</th><th>P&L</th><th>Strategy</th></tr></thead>
      <tbody id="positions"><tr><td colspan="5" class="empty">—</td></tr></tbody></table>
    </div>

    <div class="card">
      <h3><span class="dot"></span> Radar Contacts <span class="muted" id="scanmeta"></span></h3>
      <table><thead><tr><th>Strat</th><th>Market</th><th>Status</th><th>Distance</th></tr></thead>
      <tbody id="scan"><tr><td colspan="4" class="empty">—</td></tr></tbody></table>
    </div>

    <div class="card">
      <h3><span class="dot"></span> Activity Feed</h3>
      <div class="log" id="log"><div class="hb">booting radar…</div></div>
    </div>
  </div>
</div>

<script>
const $=s=>document.querySelector(s);
const fmt=(n,d=2)=>(n==null||isNaN(n))?'—':Number(n).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const cls=n=>n>0?'up':(n<0?'down':'');

// ---------- RADAR CANVAS ----------
const cv=$('#radar'), ctx=cv.getContext('2d');
let W=0,H=0,CX=0,CY=0,R=0,DPR=Math.min(2,window.devicePixelRatio||1);
function resize(){
  const b=cv.getBoundingClientRect();
  W=cv.width=b.width*DPR; H=cv.height=b.height*DPR;
  CX=W/2; CY=H/2; R=Math.min(W,H)/2-8*DPR;
}
window.addEventListener('resize',resize);

let sweep=0;                 // sweep angle
let blips=[];               // {ang, dist(0..1), label, status, ping}
let lastSig=new Set();

function polar(ang,dist){ return [CX+Math.cos(ang)*R*dist, CY+Math.sin(ang)*R*dist]; }

function drawRadar(){
  ctx.clearRect(0,0,W,H);
  // background disc
  const g=ctx.createRadialGradient(CX,CY,0,CX,CY,R);
  g.addColorStop(0,'#06140d'); g.addColorStop(1,'#040a07');
  ctx.fillStyle=g; ctx.beginPath(); ctx.arc(CX,CY,R,0,7); ctx.fill();
  // range rings
  ctx.strokeStyle='#0e3a24'; ctx.lineWidth=1*DPR;
  for(let i=1;i<=4;i++){ ctx.beginPath(); ctx.arc(CX,CY,R*i/4,0,7); ctx.stroke(); }
  // cross-hairs
  ctx.beginPath(); ctx.moveTo(CX-R,CY); ctx.lineTo(CX+R,CY);
  ctx.moveTo(CX,CY-R); ctx.lineTo(CX,CY+R); ctx.stroke();
  // diagonal hairs
  ctx.strokeStyle='#0b2c1b';
  for(let a=0;a<8;a++){const ang=a*Math.PI/4;ctx.beginPath();ctx.moveTo(CX,CY);
    ctx.lineTo(CX+Math.cos(ang)*R,CY+Math.sin(ang)*R);ctx.stroke();}

  // sweep gradient wedge
  const trail=0.55;
  for(let i=0;i<40;i++){
    const a=sweep-i*0.014;
    const alpha=(1-i/40)*0.35;
    ctx.strokeStyle=`rgba(0,255,156,${alpha})`;
    ctx.lineWidth=2*DPR;
    ctx.beginPath(); ctx.moveTo(CX,CY);
    ctx.lineTo(CX+Math.cos(a)*R,CY+Math.sin(a)*R); ctx.stroke();
  }
  // bright leading edge
  ctx.strokeStyle='rgba(0,255,156,0.9)'; ctx.lineWidth=2.5*DPR;
  ctx.beginPath(); ctx.moveTo(CX,CY);
  ctx.lineTo(CX+Math.cos(sweep)*R,CY+Math.sin(sweep)*R); ctx.stroke();

  // blips
  const now=performance.now();
  blips.forEach(b=>{
    const [x,y]=polar(b.ang,b.dist);
    // ping when the sweep passes over the blip
    let d=((sweep-b.ang)%(Math.PI*2)+Math.PI*2)%(Math.PI*2);
    if(d<0.08){ b.ping=now; }
    const age=(now-(b.ping||0));
    const lit=age<900;
    const pr=lit?(1-age/900):0;
    let color=b.status==='SIGNAL'?'#00ff9c':b.status==='acted'?'#ffcf3a':b.status==='holding'?'#4dd2ff':'#2b6b4d';
    if(b.status==='SIGNAL'){
      // signals always glow + pulse
      const pl=0.5+0.5*Math.sin(now/200);
      ctx.fillStyle=`rgba(0,255,156,${0.5+0.5*pl})`;
      ctx.beginPath(); ctx.arc(x,y,5*DPR,0,7); ctx.fill();
      ctx.strokeStyle=`rgba(0,255,156,${pl})`; ctx.lineWidth=1.5*DPR;
      ctx.beginPath(); ctx.arc(x,y,(9+pl*7)*DPR,0,7); ctx.stroke();
    }else{
      ctx.fillStyle=color; ctx.beginPath(); ctx.arc(x,y,3*DPR,0,7); ctx.fill();
    }
    // expanding ping ring when swept
    if(lit){
      ctx.strokeStyle=`rgba(0,255,156,${pr*0.8})`; ctx.lineWidth=1.5*DPR;
      ctx.beginPath(); ctx.arc(x,y,(4+ (1-pr)*16)*DPR,0,7); ctx.stroke();
    }
    // label for signals / holdings
    if(b.status!=='waiting'||lit){
      ctx.fillStyle=b.status==='SIGNAL'?'#aeffda':'#6fae95';
      ctx.font=`${10*DPR}px ui-monospace,monospace`;
      ctx.fillText(b.label, x+7*DPR, y+3*DPR);
    }
  });

  // center hub
  ctx.fillStyle='#00ff9c'; ctx.beginPath(); ctx.arc(CX,CY,3*DPR,0,7); ctx.fill();
  ctx.strokeStyle='rgba(0,255,156,.3)'; ctx.beginPath(); ctx.arc(CX,CY,7*DPR,0,7); ctx.stroke();

  sweep+=0.03;
  requestAnimationFrame(drawRadar);
}

// map scan rows -> blips. distance from center = "how close to firing"
// signals sit near the edge (bright), waiting rows sit by their distance%.
function updateBlips(scan){
  const seen={};
  scan.forEach((x,i)=>{
    const key=x.symbol;
    // one blip per symbol (strongest status wins)
    const rank=s=>s==='SIGNAL'?3:s==='holding'?2:1;
    if(seen[key] && rank(seen[key].status)>=rank(x.status)) return;
    // distance: closer to a breakout => closer to the EDGE (more urgent).
    let dist=0.55;
    if(x.status==='SIGNAL') dist=0.9;
    else if(x.status==='acted') dist=0.78;
    else if(x.status==='holding') dist=0.7;
    else if(x.distance!=null){ dist=Math.max(0.2,Math.min(0.85,0.85-(x.distance/10))); }
    // stable angle per symbol (hash)
    let hsh=0; for(let c of key) hsh=(hsh*31+c.charCodeAt(0))%360;
    seen[key]={ang:hsh*Math.PI/180, dist, label:key, status:x.status,
               ping:(blips.find(b=>b.label===key)||{}).ping||0};
  });
  blips=Object.values(seen);
}

// ---------- DATA POLL ----------
let lastLogKey='';
async function tick(){
  let s;
  try{ s=await (await fetch('/api/state',{cache:'no-store'})).json(); }
  catch(e){ setLink(false,'no link'); return; }
  const acc=s.account, connected=s.connected&&acc;
  setLink(connected, connected?(acc.server||'demo'):'offline');
  $('#mode').textContent = s.dry_run?'· DRY':'· LIVE';
  $('#poll').textContent = '#'+(s.poll_count??'—');
  $('#clock').textContent = new Date(s.server_time).toLocaleTimeString();
  if(acc){ $('#equity').textContent='$'+fmt(acc.equity); $('#balance').textContent='$'+fmt(acc.balance); }

  const pos=s.open_positions||[];
  const opl=pos.reduce((a,p)=>a+(p.profit||0),0);
  const e=$('#openpl'); e.textContent=(opl>=0?'+$':'-$')+fmt(Math.abs(opl)); e.className='v '+cls(opl);
  $('#poscount').textContent=pos.length;

  const scan=s.scan||[];
  const sigs=scan.filter(x=>x.status==='SIGNAL');
  $('#mktcount').textContent=new Set(scan.map(x=>x.symbol)).size;
  $('#sigcount').textContent=sigs.length;
  $('#scanmeta').textContent='· '+scan.length+' contacts';

  updateBlips(scan);

  // signal chips + flash when a NEW signal appears
  const sigKeys=new Set(sigs.map(x=>x.strategy+'|'+x.symbol));
  let fresh=false; sigKeys.forEach(k=>{ if(!lastSig.has(k)) fresh=true; });
  if(fresh && sigs.length) flash();
  lastSig=sigKeys;
  $('#signals').innerHTML = sigs.length? sigs.map(x=>
    `<span class="chip">◉ ${x.symbol} · ${x.strategy}${x.confidence?' · '+x.confidence:''}</span>`).join('')
    : '<span class="empty">no active signals — radar sweeping</span>';

  // positions
  $('#positions').innerHTML = pos.length? pos.map(p=>`<tr>
    <td><b>${p.symbol}</b></td>
    <td class="${p.type==='buy'?'up':'down'}">${p.type.toUpperCase()}</td>
    <td>${p.volume}</td>
    <td class="${cls(p.profit)}">${p.profit>=0?'+':''}${fmt(p.profit)}</td>
    <td class="muted">${p.strategy||''}</td></tr>`).join('')
    : '<tr><td colspan="5" class="empty">no open positions</td></tr>';

  // scan (signals + nearest first — already sorted server-side)
  $('#scan').innerHTML = scan.slice(0,14).map(x=>{
    const t=x.status==='SIGNAL'?'t-sig':x.status==='acted'?'t-acted':x.status==='holding'?'t-hold':'t-wait';
    let d='—';
    if(x.distance!=null) d=x.distance<=0?'<span class="up">HIT</span>':'+'+fmt(x.distance)+'%';
    return `<tr><td class="muted">${x.strategy}</td><td><b>${x.symbol}</b></td>
      <td><span class="tag ${t}">${x.status}</span></td><td>${d}</td></tr>`;
  }).join('');

  // log
  const log=s.log||[];
  const key=log.length?(log[0].time+log[0].msg):'';
  if(key!==lastLogKey){
    lastLogKey=key;
    $('#log').innerHTML=log.slice(0,60).map(l=>{
      const m=l.msg||''; let c='';
      if(/OPENED|WOULD|REQUEST/.test(m))c='ord';
      else if(/SIGNAL|signal|entry/.test(m))c='sig';
      else if(/CLOSED|CLOSE|cover/.test(m))c='cls';
      else if(/alive|poll|rebalanc/.test(m))c='hb';
      return `<div class="${c}">${new Date(l.time).toLocaleTimeString()} · ${m}</div>`;
    }).join('');
  }
}
function setLink(ok,txt){ $('#led').className='led'+(ok?'':' off'); $('#conn').textContent=txt; }
function flash(){ const f=$('#flashbar'); f.style.transition='none'; f.style.transform='scaleX(0)';
  requestAnimationFrame(()=>{ f.style.transition='transform 1.1s ease'; f.style.transform='scaleX(1)'; }); }

resize(); drawRadar(); tick(); setInterval(tick,3000);
</script>
</body>
</html>
"""


PORT = int(os.getenv("MT5_DASH_PORT", "8800"))   # 8800 avoids Docker/WSL on 8000

if __name__ == "__main__":
    print("=" * 62)
    print(" MT5 RADAR DASHBOARD")
    print(f" Open on THIS PC : http://localhost:{PORT}")
    print(f" Open on PHONE   : http://<this-pc-LAN-ip>:{PORT}  (same wifi)")
    print("=" * 62)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
