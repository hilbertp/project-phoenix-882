#!/usr/bin/env python
"""Self-contained human-in-the-loop review demo (no TradingView / Selenium).

Skip through each auto-detected fib setup, review it, change its anchors by
clicking two candles, and watch the engine ingest your feedback: corrections are
written to the label store and the detector is re-calibrated against your labels
so you can see it adapt.

Run:
  .venv/bin/python scripts/serve_review_demo.py
then open http://127.0.0.1:8765  (it tries to open your browser automatically).

Zero third-party deps -- uses the Python standard library http.server.
"""
from __future__ import annotations

import json
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.db1_fib_review_pine_read.service import PHOENIX_FIB_LEVELS
from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.human_labels import (
    VERDICT_ADJUST,
    LabelRecord,
    append_label,
    latest_by_key,
    load_labels,
    truth_setups,
)
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from scripts.calibrate_detector import (
    MIN_BARS_GRID,
    MULT_GRID,
    _rejected_setups,
    score_params,
)
from scripts.execute_fib_strategy import execute
from scripts.place_fibs_tradingview import MIN_BARS, RECENT_3M_FROM, _clean_legs
from scripts.track_fib_reaches import track_reaches

PORT = 8765
DETECTOR_PARAMS = {"min_bars": MIN_BARS, "atr_mult": 4.0}

_CANDLES = load_candle_input(DEFAULT_INPUT_PATH).candles
_IDX = {c.source_timestamp: i for i, c in enumerate(_CANDLES)}
_ATR = calculate_atr14(_CANDLES)
_PIV = detect_local_pivots(_CANDLES)


def _lvl(terminal: float, parent: float, coeff: float) -> float:
    return terminal + (parent - terminal) * coeff


def _raw_legs() -> list[dict]:
    return [
        leg for leg in _clean_legs(_CANDLES, _ATR, _PIV, min_bars=MIN_BARS, mult=4.0)
        if leg["parent_ts"] >= RECENT_3M_FROM
    ]


def build_state() -> dict:
    raws = _raw_legs()
    verdicts = latest_by_key(load_labels())
    display = []
    for raw in raws:
        key = f"{raw['parent_ts']}|{raw['term_ts']}"
        label = verdicts.get(key)
        if label and label.verdict == "reject":
            continue
        leg = dict(raw)
        if label and label.verdict == "adjust" and label.corrected:
            leg.update(label.corrected)
        leg["_raw_key"] = key
        display.append(leg)

    candle_start = max(0, min(_IDX[leg["parent_ts"]] for leg in display) - 30) if display else 0
    candles = [
        {"t": c.source_timestamp, "o": c.open, "h": c.high, "l": c.low, "c": c.close}
        for c in _CANDLES[candle_start:]
    ]

    setups = []
    for n, leg in enumerate(display, start=1):
        terminal, parent = leg["term_price"], leg["parent_price"]
        reaches = track_reaches(_CANDLES, _IDX, leg)
        execu = execute(_CANDLES, _IDX, leg)
        setups.append(
            {
                "id": f"auto{n}",
                "raw_key": leg["_raw_key"],
                "direction": leg["direction"],
                "parent_ts": leg["parent_ts"],
                "parent_price": parent,
                "term_ts": leg["term_ts"],
                "term_price": terminal,
                "levels": {f"{lv:.3f}": _lvl(terminal, parent, lv) for lv in PHOENIX_FIB_LEVELS},
                "entry": {"price": reaches["entry_price"], "ts": reaches["entry_ts"], "filled": reaches["entered"]},
                "reaches": reaches["sequence"],
                "execution": {"status": execu["status"], "r": round(execu["r"], 3)},
            }
        )

    labels = load_labels()
    counts = {"accept": 0, "reject": 0, "adjust": 0}
    for label in latest_by_key(labels).values():
        counts[label.verdict] = counts.get(label.verdict, 0) + 1

    calibration = None
    truths = truth_setups(labels)
    rejects = _rejected_setups(labels)
    if truths:
        results = [
            score_params(_CANDLES, _ATR, _PIV, _IDX, truths, rejects, mb, mult)
            for mb in MIN_BARS_GRID
            for mult in MULT_GRID
        ]
        results.sort(key=lambda r: (r["score"], r["recall"]), reverse=True)
        baseline = next(
            (r for r in results if r["min_bars"] == MIN_BARS and r["mult"] == 4.0), None
        )
        best = results[0]
        calibration = {
            "best_min_bars": best["min_bars"],
            "best_mult": best["mult"],
            "matched": best["matched"],
            "truths": len(truths),
            "recall": round(best["recall"], 2),
            "baseline_recall": round(baseline["recall"], 2) if baseline else None,
        }

    return {
        "candles": candles,
        "setups": setups,
        "fib_levels": list(PHOENIX_FIB_LEVELS),
        "labels": {**counts, "total": len(latest_by_key(labels))},
        "calibration": calibration,
    }


def _snap_corrected(click_parent_ts: str, click_term_ts: str) -> dict:
    i1, i2 = _IDX[click_parent_ts], _IDX[click_term_ts]
    a, b = (i1, i2) if i1 < i2 else (i2, i1)  # earlier click is the origin (parent)
    ca, cb = _CANDLES[a], _CANDLES[b]
    up = (cb.high - ca.low) >= (ca.high - cb.low)  # larger-magnitude interpretation wins
    return {
        "direction": "up" if up else "down",
        "parent_ts": ca.source_timestamp,
        "parent_price": ca.low if up else ca.high,
        "parent_kind": "low" if up else "high",
        "term_ts": cb.source_timestamp,
        "term_price": cb.high if up else cb.low,
        "term_kind": "high" if up else "low",
    }


def record_feedback(body: dict) -> None:
    verdict = body["verdict"]
    raw_key = body["raw_key"]
    disp = body.get("display", {})
    corrected = None
    if verdict == VERDICT_ADJUST:
        corrected = _snap_corrected(body["click_parent_ts"], body["click_term_ts"])
    record = LabelRecord(
        setup_key=raw_key,
        verdict=verdict,
        direction=disp.get("direction", ""),
        parent_ts=disp.get("parent_ts", raw_key.split("|")[0]),
        parent_price=float(disp.get("parent_price", 0.0)),
        term_ts=disp.get("term_ts", raw_key.split("|")[1]),
        term_price=float(disp.get("term_price", 0.0)),
        corrected=corrected,
        detector_params=DETECTOR_PARAMS,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    append_label(record)


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>DB1 Fib Setup Review</title>
<style>
  :root{color-scheme:dark}
  body{margin:0;background:#0e1116;color:#e6edf3;font:13px -apple-system,Segoe UI,sans-serif}
  header{padding:10px 16px;background:#161b22;border-bottom:1px solid #30363d;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
  h1{font-size:15px;margin:0}
  .pill{padding:2px 8px;border-radius:10px;background:#21262d;font-size:12px}
  .wrap{display:flex;gap:14px;padding:14px;align-items:flex-start}
  canvas{background:#0b0e13;border:1px solid #30363d;border-radius:8px;cursor:crosshair}
  .side{width:300px;display:flex;flex-direction:column;gap:10px}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px}
  .card h2{font-size:12px;margin:0 0 6px;color:#8b949e;text-transform:uppercase;letter-spacing:.04em}
  button{border:0;border-radius:6px;padding:8px 10px;color:#fff;cursor:pointer;font-size:13px;margin:2px}
  .nav button{background:#30363d}.acc{background:#238636!important}.rej{background:#da3633!important}
  .adj{background:#9e6a03!important}.save{background:#1f6feb!important}
  button:disabled{opacity:.4;cursor:not-allowed}
  .seq span{display:inline-block;margin:1px;padding:1px 5px;border-radius:4px;background:#21262d;font-size:11px}
  .stop{background:#5a1e1e!important}.tgt{background:#1e5a2e!important}
  .big{font-size:22px;font-weight:700}
  .muted{color:#8b949e}
  .hint{color:#d29922}
</style></head>
<body>
<header>
  <h1>DB1 Fib Setup Review</h1>
  <span class="pill" id="counter">- / -</span>
  <span class="pill" id="dir">-</span>
  <span class="pill" id="dates">-</span>
  <span class="pill" id="outcome">-</span>
  <span class="pill hint" id="mode"></span>
</header>
<div class="wrap">
  <canvas id="c" width="1040" height="560"></canvas>
  <div class="side">
    <div class="card nav">
      <h2>Navigate</h2>
      <button onclick="step(-1)">&#9664; Back</button>
      <button onclick="step(1)">Next &#9654;</button>
    </div>
    <div class="card">
      <h2>Review this setup</h2>
      <button class="acc" onclick="feedback('accept')">&#10003; Accept</button>
      <button class="rej" onclick="feedback('reject')">&#10007; Reject</button>
      <button class="adj" id="adjbtn" onclick="toggleAdjust()">&#9998; Adjust anchors</button>
      <button class="save" id="savebtn" onclick="saveAdjust()" disabled>Save change</button>
      <div class="muted" id="adjhint"></div>
    </div>
    <div class="card">
      <h2>Level reach sequence</h2>
      <div class="seq" id="seq"></div>
      <div class="muted" id="exec"></div>
    </div>
    <div class="card">
      <h2>Engine (learns from your feedback)</h2>
      <div id="labels" class="muted"></div>
      <div id="calib"></div>
    </div>
  </div>
</div>
<script>
let S=null, i=0, adjust=false, clicks=[];
const cv=document.getElementById('c'), ctx=cv.getContext('2d');
const PAD={l:8,r:64,t:10,b:20};
async function load(){ S=await (await fetch('/api/state')).json(); if(i>=S.setups.length)i=Math.max(0,S.setups.length-1); render(); }
function tIndex(){ const m={}; S.candles.forEach((c,k)=>m[c.t]=k); return m; }
function curWindow(s,m){ const p=m[s.parent_ts], t=m[s.term_ts]; let last=Math.max(p,t); (s.reaches||[]).forEach(r=>{if(m[r.ts]!=null)last=Math.max(last,m[r.ts])}); const a=Math.max(0,Math.min(p,t)-20), b=Math.min(S.candles.length-1,last+20); return [a,b]; }
function render(){
  if(!S||!S.setups.length){ ctx.fillStyle='#888';ctx.fillText('No setups',20,20); return; }
  const s=S.setups[i], m=tIndex(), [a,b]=curWindow(s,m), win=S.candles.slice(a,b+1);
  let hi=-1e9,lo=1e9; win.forEach(c=>{hi=Math.max(hi,c.h);lo=Math.min(lo,c.l)});
  Object.values(s.levels).forEach(v=>{hi=Math.max(hi,v);lo=Math.min(lo,v)});
  const pad=(hi-lo)*0.06; hi+=pad; lo-=pad;
  const W=cv.width-PAD.l-PAD.r, H=cv.height-PAD.t-PAD.b;
  const x=k=>PAD.l+(k/(win.length-1))*W, y=p=>PAD.t+(1-(p-lo)/(hi-lo))*H;
  ctx.clearRect(0,0,cv.width,cv.height);
  // fib levels
  const order=['1.050','1.000','0.941','0.882','0.786','0.618','0.500','0.382','0.000'];
  ctx.font='10px sans-serif';
  for(const k in s.levels){ const yy=y(s.levels[k]); ctx.strokeStyle='#2b3340'; ctx.beginPath();ctx.moveTo(PAD.l,yy);ctx.lineTo(PAD.l+W,yy);ctx.stroke(); ctx.fillStyle='#6b7785'; ctx.fillText(k,PAD.l+W+4,yy+3); }
  // trade plan: entry/sl/tp
  function plan(lv,col,txt){ const yy=y(s.levels[lv]); ctx.strokeStyle=col; ctx.setLineDash([5,4]); ctx.beginPath();ctx.moveTo(PAD.l,yy);ctx.lineTo(PAD.l+W,yy);ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle=col; ctx.fillText(txt,PAD.l+4,yy-3); }
  plan('0.786','#e3b341','Entry .786'); plan('1.050','#f85149','SL 1.05'); plan('0.382','#3fb950','TP2 .382'); plan('0.000','#3fb950','TP3 0.0');
  // candles
  const cw=Math.max(2,W/win.length*0.7);
  win.forEach((c,k)=>{ const up=c.c>=c.o, col=up?'#3fb950':'#f85149'; const xx=x(k); ctx.strokeStyle=col; ctx.beginPath();ctx.moveTo(xx,y(c.h));ctx.lineTo(xx,y(c.l));ctx.stroke(); ctx.fillStyle=col; const yo=y(c.o),yc=y(c.c); ctx.fillRect(xx-cw/2,Math.min(yo,yc),cw,Math.max(1,Math.abs(yc-yo))); });
  // entry marker + reach markers
  function mark(ts,price,col,label){ if(m[ts]==null)return; const k=m[ts]-a; if(k<0||k>=win.length)return; const xx=x(k),yy=y(price); ctx.fillStyle=col; ctx.beginPath();ctx.arc(xx,yy,3.5,0,7);ctx.fill(); if(label){ctx.fillStyle='#cdd9e5';ctx.fillText(label,xx+5,yy-4);} }
  if(s.entry&&s.entry.filled) mark(s.entry.ts,s.entry.price,'#e3b341','entry');
  (s.reaches||[]).forEach(r=>{ const col=r.kind==='stop'?'#f85149':r.kind==='target'?'#3fb950':'#58a6ff'; mark(r.ts,r.price,col,r.coeff); });
  // adjust click preview
  clicks.forEach(ts=>{ if(m[ts]==null)return; const k=m[ts]-a; if(k<0||k>=win.length)return; const xx=x(k); ctx.strokeStyle='#d29922';ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(xx,PAD.t);ctx.lineTo(xx,PAD.t+H);ctx.stroke();ctx.setLineDash([]); });
  // header + side panels
  document.getElementById('counter').textContent=(i+1)+' / '+S.setups.length+'  ('+s.id+')';
  document.getElementById('dir').textContent=s.direction;
  document.getElementById('dates').textContent=s.parent_ts.slice(5,16)+' -> '+s.term_ts.slice(5,16);
  document.getElementById('outcome').textContent=s.execution.status+'  '+(s.execution.r>=0?'+':'')+s.execution.r+'R';
  const seq=document.getElementById('seq'); seq.innerHTML='';
  const e=document.createElement('span'); e.textContent='entry .786'; seq.appendChild(e);
  (s.reaches||[]).forEach(r=>{ const sp=document.createElement('span'); sp.textContent=r.coeff; if(r.kind==='stop')sp.className='stop'; if(r.kind==='target')sp.className='tgt'; seq.appendChild(sp); });
  document.getElementById('exec').textContent = s.entry.filled? ('entry filled '+ (s.entry.ts||'').slice(5,16)) : 'entry 0.786 not touched';
  const L=S.labels; document.getElementById('labels').innerHTML='labels: <b>'+L.total+'</b> &nbsp; accept '+L.accept+' / reject '+L.reject+' / adjust '+L.adjust;
  const cb=document.getElementById('calib');
  if(S.calibration){ const c=S.calibration; cb.innerHTML='<div class="big">min_bars '+c.best_min_bars+' &middot; ATR x'+c.best_mult+'</div><div class="muted">reproduces '+c.matched+'/'+c.truths+' of your approved setups (recall '+(c.recall*100).toFixed(0)+'%, baseline '+(c.baseline_recall!=null?(c.baseline_recall*100).toFixed(0)+'%':'-')+')</div>'; }
  else cb.innerHTML='<span class="muted">Accept or adjust a few setups and the detector will retune to match you.</span>';
  document.getElementById('mode').textContent = adjust? 'ADJUST: click the origin candle, then the extreme candle' : '';
}
function step(d){ adjust=false;clicks=[]; document.getElementById('savebtn').disabled=true; document.getElementById('adjhint').textContent=''; i=(i+d+S.setups.length)%S.setups.length; render(); }
function toggleAdjust(){ adjust=!adjust; clicks=[]; document.getElementById('savebtn').disabled=true; document.getElementById('adjhint').textContent=adjust?'Click two candles: origin then extreme.':''; render(); }
cv.addEventListener('click',ev=>{ if(!adjust||!S)return; const s=S.setups[i],m=tIndex(),[a,b]=curWindow(s,m),win=S.candles.slice(a,b+1); const W=cv.width-PAD.l-PAD.r; const rel=(ev.offsetX-PAD.l)/W; let k=Math.round(rel*(win.length-1)); k=Math.max(0,Math.min(win.length-1,k)); const ts=win[k].t; clicks.push(ts); if(clicks.length>2)clicks=clicks.slice(-2); document.getElementById('savebtn').disabled=clicks.length!==2; document.getElementById('adjhint').textContent=clicks.length===2?'Ready: Save change to teach the engine.':'Now click the extreme candle.'; render(); });
async function feedback(verdict){ const s=S.setups[i]; await post({verdict,raw_key:s.raw_key,display:{direction:s.direction,parent_ts:s.parent_ts,parent_price:s.parent_price,term_ts:s.term_ts,term_price:s.term_price}}); }
async function saveAdjust(){ if(clicks.length!==2)return; const s=S.setups[i]; await post({verdict:'adjust',raw_key:s.raw_key,display:{direction:s.direction,parent_ts:s.parent_ts,parent_price:s.parent_price,term_ts:s.term_ts,term_price:s.term_price},click_parent_ts:clicks[0],click_term_ts:clicks[1]}); adjust=false;clicks=[]; document.getElementById('savebtn').disabled=true; }
async function post(body){ S=await (await fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json(); if(i>=S.setups.length)i=Math.max(0,S.setups.length-1); render(); }
load();
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, code: int, body, ctype="application/json") -> None:
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            self._send(200, json.dumps(build_state()))
        else:
            self._send(200, HTML, "text/html; charset=utf-8")

    def do_POST(self):
        if not self.path.startswith("/api/feedback"):
            self._send(404, "{}")
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        try:
            record_feedback(body)
        except Exception as error:  # surface, don't crash the server
            self._send(400, json.dumps({"error": str(error)}))
            return
        self._send(200, json.dumps(build_state()))


def main() -> None:
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Review demo running at {url}  (Ctrl-C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
