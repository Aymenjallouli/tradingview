"""
mt5_hub.py — ONE unified dashboard for all three books.

The three book processes (metals / short-term / crypto) run headless, each on
its own internal port. This hub fetches all three and shows them TOGETHER on a
single radar page — one link, all books, each clearly labeled.

    # 1) start the three books (they serve their own /api/state):
    python run_bots.py
    # 2) start the hub:
    python mt5_hub.py
    # open http://localhost:8800

The hub itself trades nothing — it only aggregates the three books' state.
"""

import os
import json
import urllib.request
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

app = FastAPI(title="MT5 Hub")

BOOKS = [
    {"key": "metals", "name": "METALS", "url": "http://localhost:8801"},
    {"key": "forex", "name": "FOREX", "url": "http://localhost:8802"},
    {"key": "indices", "name": "INDICES", "url": "http://localhost:8803"},
    {"key": "energy", "name": "ENERGY", "url": "http://localhost:8804"},
    {"key": "crypto", "name": "CRYPTO", "url": "http://localhost:8805"},
    {"key": "softs", "name": "SOFTS", "url": "http://localhost:8806"},
]


def _fetch(url):
    try:
        with urllib.request.urlopen(url + "/api/state", timeout=4) as r:
            return json.load(r)
    except Exception as exc:  # noqa: BLE001
        return {"connected": False, "error": str(exc)}


@app.get("/api/all")
def api_all():
    out = {"server_time": datetime.now(timezone.utc).isoformat(), "books": []}
    total_open_pl = 0.0
    equity = None
    balance = None
    for b in BOOKS:
        st = _fetch(b["url"])
        acc = st.get("account") or {}
        # equity/balance are the SAME account for all books — take the first live one
        if acc.get("equity") is not None and equity is None:
            equity = acc.get("equity")
            balance = acc.get("balance")
        pos = st.get("open_positions", [])
        book_pl = sum(p.get("profit", 0) for p in pos)
        total_open_pl += book_pl
        out["books"].append({
            "key": b["key"], "name": b["name"],
            "connected": st.get("connected", False),
            "strategies": st.get("strategies", []),
            "positions": pos,
            "book_pl": book_pl,
            "scan": st.get("scan", []),
            "daytrader": st.get("daytrader", {"on": False}),
            "poll": st.get("poll_count"),
        })
    out["equity"] = equity
    out["balance"] = balance
    out["total_open_pl"] = total_open_pl
    return JSONResponse(out)


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


HTML = r"""
<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>MT5 HUB</title>
<style>
  :root{--bg:#04070a;--scan:#00ff9c;--text:#cfe9df;--muted:#5a7d70;
    --amber:#ffcf3a;--red:#ff4d5e;--blue:#4dd2ff;--green:#00ff9c;
    --panel:#0a1119;--line:#12321f;}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:radial-gradient(ellipse at 30% 0%,#0a1a14,#04070a 60%);
    color:var(--text);font-family:"SF Mono",ui-monospace,Menlo,monospace;
    -webkit-text-size-adjust:100%}
  .top{display:flex;align-items:center;gap:16px;padding:12px 18px;
    border-bottom:1px solid var(--line);position:sticky;top:0;z-index:20;
    background:linear-gradient(180deg,#061019,#04070acc);backdrop-filter:blur(6px);flex-wrap:wrap}
  .brand{font-size:18px;font-weight:800;letter-spacing:3px;color:var(--green);
    text-shadow:0 0 12px #00ff9c88}
  .stat{display:flex;flex-direction:column;line-height:1.15}
  .stat .k{font-size:9px;color:var(--muted);letter-spacing:2px;text-transform:uppercase}
  .stat .v{font-size:18px;font-weight:800;font-variant-numeric:tabular-nums}
  .grow{flex:1}
  .up{color:var(--green)}.down{color:var(--red)}.muted{color:var(--muted)}
  .wrap{padding:16px;max-width:1500px;margin:0 auto;display:grid;gap:16px}
  @media(min-width:1000px){.wrap{grid-template-columns:repeat(3,1fr)}}
  .book{background:var(--panel);border:1px solid var(--line);border-radius:16px;
    padding:14px;position:relative;overflow:hidden}
  .book.off{opacity:.5}
  .book h2{font-size:13px;letter-spacing:2px;color:var(--green);margin-bottom:2px;
    display:flex;align-items:center;gap:8px}
  .book .sub{font-size:10px;color:var(--muted);margin-bottom:10px}
  .led{width:8px;height:8px;border-radius:50%;background:var(--green);
    box-shadow:0 0 10px var(--green);animation:pulse 1.4s infinite}
  .led.off{background:var(--red);box-shadow:0 0 10px var(--red)}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
  .radar{width:100%;aspect-ratio:1;max-width:260px;margin:0 auto 10px;display:block}
  .bpl{text-align:center;font-size:20px;font-weight:800;margin:6px 0}
  table{width:100%;border-collapse:collapse;font-size:11px}
  th{text-align:left;color:var(--muted);font-weight:600;font-size:9px;letter-spacing:1px;
    text-transform:uppercase;padding:4px 6px;border-bottom:1px solid var(--line)}
  td{padding:6px 6px;border-bottom:1px solid #0c1a13;font-variant-numeric:tabular-nums}
  tr:last-child td{border-bottom:none}
  .tag{font-size:9px;padding:2px 6px;border-radius:5px;font-weight:700}
  .t-sig{background:#00ff9c22;color:var(--green)}
  .t-hold{background:#4dd2ff22;color:var(--blue)}.t-wait{background:#5a7d7018;color:var(--muted)}
  .pill{font-size:9px;color:var(--muted);border:1px solid var(--line);border-radius:20px;
    padding:2px 8px;display:inline-block;margin:1px}
  .dtbar{font-size:10px;color:var(--amber);margin:6px 0}
  h4{font-size:9px;letter-spacing:1px;color:var(--muted);text-transform:uppercase;margin:10px 0 4px}
  .empty{color:var(--muted);font-size:10px;padding:5px}
</style></head>
<body>
<div class="top">
  <div class="brand">◎ MT5 HUB</div>
  <div class="stat"><span class="k">Equity</span><span class="v" id="equity">—</span></div>
  <div class="stat"><span class="k">Balance</span><span class="v" id="balance">—</span></div>
  <div class="stat"><span class="k">Total Open P&L</span><span class="v" id="totalpl">—</span></div>
  <div class="grow"></div>
  <div class="stat"><span class="k">Time</span><span class="v" id="clock" style="font-size:12px">—</span></div>
</div>
<div class="wrap" id="books"></div>

<script>
const $=s=>document.querySelector(s);
const fmt=(n,d=2)=>(n==null||isNaN(n))?'—':Number(n).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const cls=n=>n>0?'up':(n<0?'down':'');
const radars={};  // per-book radar state

function drawRadar(cv,scan,sweepRef){
  const ctx=cv.getContext('2d'); const DPR=Math.min(2,devicePixelRatio||1);
  const b=cv.getBoundingClientRect(); cv.width=b.width*DPR; cv.height=b.height*DPR;
  const W=cv.width,H=cv.height,CX=W/2,CY=H/2,R=Math.min(W,H)/2-4*DPR;
  ctx.clearRect(0,0,W,H);
  const g=ctx.createRadialGradient(CX,CY,0,CX,CY,R);
  g.addColorStop(0,'#06140d');g.addColorStop(1,'#040a07');
  ctx.fillStyle=g;ctx.beginPath();ctx.arc(CX,CY,R,0,7);ctx.fill();
  ctx.strokeStyle='#0e3a24';ctx.lineWidth=1*DPR;
  for(let i=1;i<=3;i++){ctx.beginPath();ctx.arc(CX,CY,R*i/3,0,7);ctx.stroke();}
  ctx.beginPath();ctx.moveTo(CX-R,CY);ctx.lineTo(CX+R,CY);ctx.moveTo(CX,CY-R);ctx.lineTo(CX,CY+R);ctx.stroke();
  const sweep=sweepRef.a;
  for(let i=0;i<30;i++){const a=sweep-i*0.02;
    ctx.strokeStyle=`rgba(0,255,156,${(1-i/30)*0.3})`;ctx.lineWidth=2*DPR;
    ctx.beginPath();ctx.moveTo(CX,CY);ctx.lineTo(CX+Math.cos(a)*R,CY+Math.sin(a)*R);ctx.stroke();}
  ctx.strokeStyle='rgba(0,255,156,.9)';ctx.lineWidth=2*DPR;
  ctx.beginPath();ctx.moveTo(CX,CY);ctx.lineTo(CX+Math.cos(sweep)*R,CY+Math.sin(sweep)*R);ctx.stroke();
  const seen={};
  (scan||[]).forEach(x=>{
    const rank=s=>s==='SIGNAL'?3:s==='holding'?2:1;
    if(seen[x.symbol]&&rank(seen[x.symbol].status)>=rank(x.status))return;
    seen[x.symbol]=x;
  });
  const now=performance.now();
  Object.values(seen).forEach(x=>{
    let dist=x.status==='SIGNAL'?0.88:x.status==='holding'?0.66:
      (x.distance!=null?Math.max(0.2,Math.min(0.8,0.8-x.distance/10)):0.5);
    let hsh=0;for(let c of x.symbol)hsh=(hsh*31+c.charCodeAt(0))%360;
    const ang=hsh*Math.PI/180, px=CX+Math.cos(ang)*R*dist, py=CY+Math.sin(ang)*R*dist;
    if(x.status==='SIGNAL'){const pl=0.5+0.5*Math.sin(now/200);
      ctx.fillStyle=`rgba(0,255,156,${0.6+0.4*pl})`;ctx.beginPath();ctx.arc(px,py,4*DPR,0,7);ctx.fill();
      ctx.strokeStyle=`rgba(0,255,156,${pl})`;ctx.beginPath();ctx.arc(px,py,(7+pl*6)*DPR,0,7);ctx.stroke();
    }else{ctx.fillStyle=x.status==='holding'?'#4dd2ff':'#2b6b4d';
      ctx.beginPath();ctx.arc(px,py,3*DPR,0,7);ctx.fill();}
    if(x.status!=='waiting'){ctx.fillStyle=x.status==='SIGNAL'?'#aeffda':'#6fae95';
      ctx.font=`${9*DPR}px monospace`;ctx.fillText(x.symbol,px+6*DPR,py+3*DPR);}
  });
  ctx.fillStyle='#00ff9c';ctx.beginPath();ctx.arc(CX,CY,2.5*DPR,0,7);ctx.fill();
  sweepRef.a+=0.03;
}

function animate(){
  document.querySelectorAll('canvas[data-book]').forEach(cv=>{
    const k=cv.dataset.book; const st=radars[k];
    if(st) drawRadar(cv, st.scan, st);
  });
  requestAnimationFrame(animate);
}

async function tick(){
  let s; try{ s=await(await fetch('/api/all',{cache:'no-store'})).json(); }catch(e){return;}
  $('#equity').textContent = s.equity!=null?'$'+fmt(s.equity):'—';
  $('#balance').textContent = s.balance!=null?'$'+fmt(s.balance):'—';
  const t=$('#totalpl'); t.textContent=(s.total_open_pl>=0?'+$':'-$')+fmt(Math.abs(s.total_open_pl));
  t.className='v '+cls(s.total_open_pl);
  $('#clock').textContent=new Date(s.server_time).toLocaleTimeString();

  $('#books').innerHTML = s.books.map(bk=>{
    const sigs=(bk.scan||[]).filter(x=>x.status==='SIGNAL');
    const dt=bk.daytrader&&bk.daytrader.on?`<div class="dtbar">⚡ day-trader: ${bk.daytrader.trades}/${bk.daytrader.max_trades} trades · ${bk.daytrader.losses}/${bk.daytrader.max_losses} losses${bk.daytrader.stopped?' · STOPPED':''}</div>`:'';
    const posRows=(bk.positions||[]).length?bk.positions.map(p=>`<tr>
      <td><b>${p.symbol}</b></td><td class="${p.type==='buy'?'up':'down'}">${p.type.toUpperCase()}</td>
      <td class="${cls(p.profit)}">${p.profit>=0?'+':''}${fmt(p.profit)}</td>
      <td class="muted">${p.strategy||''}</td></tr>`).join(''):'<tr><td colspan="4" class="empty">no positions</td></tr>';
    const scanRows=(bk.scan||[]).slice(0,6).map(x=>{
      const tg=x.status==='SIGNAL'?'t-sig':x.status==='holding'?'t-hold':'t-wait';
      let d=x.distance!=null?(x.distance<=0?'HIT':'+'+fmt(x.distance)+'%'):'—';
      return `<tr><td class="muted">${x.strategy}</td><td><b>${x.symbol}</b></td>
        <td><span class="tag ${tg}">${x.status}</span></td><td>${d}</td></tr>`;}).join('');
    return `<div class="book ${bk.connected?'':'off'}">
      <h2><span class="led ${bk.connected?'':'off'}"></span>${bk.name}</h2>
      <div class="sub">${(bk.strategies||[]).length} strategies · poll #${bk.poll??'—'} · ${sigs.length} signals</div>
      <canvas class="radar" data-book="${bk.key}"></canvas>
      <div class="bpl ${cls(bk.book_pl)}">${bk.book_pl>=0?'+$':'-$'}${fmt(Math.abs(bk.book_pl))}</div>
      ${dt}
      <div>${(bk.strategies||[]).map(st=>`<span class="pill">${st}</span>`).join('')}</div>
      <h4>Positions</h4><table><tbody>${posRows}</tbody></table>
      <h4>Radar</h4><table><tbody>${scanRows||'<tr><td class="empty">scanning…</td></tr>'}</tbody></table>
    </div>`;
  }).join('');

  // update radar state
  s.books.forEach(bk=>{ if(!radars[bk.key])radars[bk.key]={a:Math.random()*6};
    radars[bk.key].scan=bk.scan; });
}
animate(); tick(); setInterval(tick,3000);
</script>
</body></html>
"""


PORT = int(os.getenv("MT5_HUB_PORT", "8800"))

if __name__ == "__main__":
    print("=" * 60)
    print(" MT5 HUB — all 3 books in one dashboard")
    print(f" Open: http://localhost:{PORT}")
    print(" (make sure run_bots.py is running the 3 books first)")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
