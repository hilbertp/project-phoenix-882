#!/usr/bin/env python
"""Interactive human-in-the-loop review of DB1 fib setups on TradingView.

Injects a small control panel into your logged-in TradingView chart (over the
Selenium debug-port link) and steps through the auto-detected setups one at a
time. For each setup you can:

  Back / Next   - move through the setups (one focused object at a time)
  Accept        - mark the setup correct as drawn
  Reject        - mark it as not a real setup (the engine drops it)
  Save edit     - after dragging the Fib's anchors to the right pivots, capture
                  the corrected anchors (snapped to the candle extremes)
  Done          - end the session

Every verdict is appended to data/discovery_bet_1/human_labels.jsonl, which the
detector consumes: apply_overrides() honours your edits immediately, and
scripts/calibrate_detector.py tunes the detector parameters to your labels.

Usage:
  python scripts/review_fibs_tradingview.py          # review recent-3M setups
  python scripts/review_fibs_tradingview.py manual   # review the 8 reference setups
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.db1_review_tradingview.service import (
    DB1TradingViewSyncService,
    _build_expected_line_tool_points,
)
from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.human_labels import (
    VERDICT_ACCEPT,
    VERDICT_ADJUST,
    VERDICT_REJECT,
    append_label,
    apply_overrides,
    make_label,
)
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from scripts.place_fibs_tradingview import (
    LAYOUT_URL,
    MANUAL_SWINGS,
    MIN_BARS,
    PLACE_FIB_JS,
    RECENT_3M_FROM,
    _clean_legs,
    _make_driver,
    _request_for,
)

DETECTOR_PARAMS = {"min_bars": MIN_BARS, "atr_mult": 4.0}

INJECT_PANEL_JS = r"""
if (document.getElementById('db1-review-panel')) { window.__reviewSeq = window.__reviewSeq || 0; return {ok:true, already:true}; }
window.__reviewSeq = 0;
window.__reviewAction = null;
const p = document.createElement('div');
p.id = 'db1-review-panel';
p.style.cssText = 'position:fixed;top:90px;right:18px;z-index:2147483647;background:#1e222d;color:#fff;padding:10px;border-radius:8px;font:12px -apple-system,sans-serif;box-shadow:0 2px 14px rgba(0,0,0,.6);width:230px';
function b(label, act, bg){ return '<button data-act="'+act+'" style="margin:2px;padding:6px 9px;border:0;border-radius:4px;cursor:pointer;background:'+bg+';color:#fff;font-size:12px">'+label+'</button>'; }
p.innerHTML =
  '<div id="db1rv-title" style="font-weight:bold;margin-bottom:6px">DB1 Setup Review</div>' +
  '<div>' + b('◀ Back','back','#363a45') + b('Next ▶','next','#2962ff') + '</div>' +
  '<div>' + b('✓ Accept','accept','#26a69a') + b('✗ Reject','reject','#ef5350') + '</div>' +
  '<div>' + b('✎ Save edit','save','#f0b90b') + b('Done','done','#363a45') + '</div>' +
  '<div id="db1rv-info" style="margin-top:7px;font-size:11px;color:#9aa4b2;line-height:1.4"></div>';
document.body.appendChild(p);
p.querySelectorAll('button').forEach(function(btn){ btn.onclick = function(){ window.__reviewSeq++; window.__reviewAction = {seq: window.__reviewSeq, action: btn.getAttribute('data-act')}; }; });
window.__reviewStatus = function(title, info){ var t=document.getElementById('db1rv-title'); if(t) t.textContent=title; var i=document.getElementById('db1rv-info'); if(i && info!=null) i.innerHTML=info; };
return {ok:true};
"""

READBACK_FIB_JS = r"""
const c = window._exposed_chartWidgetCollection;
if (!c) { return {ok:false, error:'no collection'}; }
const model = c._activeChartWidgetModel.value();
const chartModel = model.model();
const bars = model.mainSeries().data();
const epochByIndex = {};
bars.each((index, value) => { epochByIndex[index] = value[0]; });
const lts = chartModel.allLineTools();
let fib = null, fallback = null;
for (let i=lts.length-1;i>=0;i--){
    const t=lts[i]; const s=t&&t.state&&t.state();
    if(!(s&&s.type==='LineToolFibRetracement')) continue;
    if(!fallback) fallback = t;
    let txt='';
    try { const ch=t.properties().childs(); txt=(ch.editableText&&ch.editableText.value&&ch.editableText.value())||(ch.title&&ch.title.value&&ch.title.value())||''; } catch(e){}
    if (String(txt).indexOf('REVIEWING') >= 0) { fib = t; break; }
}
if(!fib) fib = fallback;
if(!fib){ return {ok:false, error:'no fib on chart'}; }
let pts = null;
try { pts = fib.points(); } catch(e) {}
if(!pts || !pts.length){ try { const st=fib.state(); pts = st && st.points; } catch(e) {} }
if(!pts || pts.length < 2){ return {ok:false, error:'no points'}; }
function epochOf(pt){ if(pt.index!=null && epochByIndex[pt.index]!=null) return epochByIndex[pt.index]; return pt.time_t!=null?pt.time_t:null; }
return {ok:true, points: pts.slice(0,2).map(pt=>({epoch: epochOf(pt), price: pt.price}))};
"""

CLEAR_JS = "const c=window._exposed_chartWidgetCollection; if(c){c._activeChartWidgetModel.value().removeAllDrawingTools();}"


def _build_epoch_maps(candles, tznames):
    """epoch_seconds -> candle index, for each candidate chart timezone."""
    maps = {}
    for tzname in tznames:
        try:
            tz = ZoneInfo(tzname)
        except Exception:
            continue
        m = {}
        for i, c in enumerate(candles):
            dt = datetime.fromisoformat(c.source_timestamp).replace(tzinfo=tz)
            m[int(dt.timestamp())] = i
        maps[tzname] = m
    return maps


def _epoch_to_candle(epoch, maps):
    for m in maps.values():
        if epoch in m:
            return m[epoch]
    # tolerate small drift: snap to nearest known epoch within 30 min
    best = None
    for m in maps.values():
        for e, i in m.items():
            d = abs(e - epoch)
            if d <= 1800 and (best is None or d < best[0]):
                best = (d, i)
    return best[1] if best else None


def _place_one(driver, leg, name, ctx):
    req = _request_for({**leg, "name": name})
    for tz in (ctx.effective_chart_timezone, "UTC"):
        pts = _build_expected_line_tool_points(req, chart_time_zone=tz)
        mapped = {
            "parentPoint": {"price": pts[0]["price"], "time_t": pts[0]["time_t"]},
            "terminalPoint": {"price": pts[1]["price"], "time_t": pts[1]["time_t"]},
        }
        result = driver.execute_script(PLACE_FIB_JS, mapped, "60", name, True)
        if isinstance(result, dict) and result.get("ok"):
            return True
    return False


def _window_name(setups, j, role):
    leg = setups[j]
    pd = f"{leg['parent_ts'][8:10]}-{leg['parent_ts'][5:7]}"
    td = f"{leg['term_ts'][8:10]}-{leg['term_ts'][5:7]}"
    return f"auto{j + 1} {role} {leg['direction']} {pd}->{td}"


def _place_window(driver, setups, i, ctx):
    """Show the previous, current, and next setup as named Object-Tree entries so
    the reviewer can see context and navigate. Current is marked REVIEWING."""
    driver.execute_script(CLEAR_JS)
    if i - 1 >= 0:
        _place_one(driver, setups[i - 1], _window_name(setups, i - 1, "(prev)"), ctx)
    if i + 1 < len(setups):
        _place_one(driver, setups[i + 1], _window_name(setups, i + 1, "(next)"), ctx)
    # Place current LAST so it sits on top and is the read-back target.
    return _place_one(driver, setups[i], _window_name(setups, i, "<< REVIEWING >>"), ctx)


def _capture_adjustment(driver, candles, maps):
    """Read the edited Fib back, snap each anchor to its candle's extreme, and
    return a corrected leg dict (or None if read-back failed)."""
    res = driver.execute_script(READBACK_FIB_JS)
    if not (isinstance(res, dict) and res.get("ok")):
        return None, res
    pts = res["points"]
    resolved = []
    for pt in pts:
        ci = _epoch_to_candle(int(pt["epoch"]), maps) if pt.get("epoch") is not None else None
        if ci is None:
            return None, {"error": "anchor not on a known candle", "point": pt}
        resolved.append((ci, float(pt["price"])))
    # Order by time: earlier anchor = parent (origin), later = terminal (extreme).
    resolved.sort(key=lambda r: r[0])
    (pi, p_price), (ti, t_price) = resolved[0], resolved[1]
    up = p_price < t_price  # origin lower than the extreme reached => up leg
    pc, tc = candles[pi], candles[ti]
    corrected = {
        "direction": "up" if up else "down",
        "parent_ts": pc.source_timestamp,
        "parent_price": pc.low if up else pc.high,
        "parent_kind": "low" if up else "high",
        "term_ts": tc.source_timestamp,
        "term_price": tc.high if up else tc.low,
        "term_kind": "high" if up else "low",
    }
    return corrected, res


def _info_html(i, n, leg, extra=""):
    span = ""
    return (
        f"{i + 1} / {n} &nbsp; <b>{leg['direction']}</b><br>"
        f"{leg['parent_ts'][5:16]} &rarr; {leg['term_ts'][5:16]}<br>"
        f"{leg['parent_price']:.0f} &rarr; {leg['term_price']:.0f}{span}"
        f"{('<br>' + extra) if extra else ''}"
    )


def _load_setups(mode, candles, atr, pivots):
    if mode == "manual":
        legs = [dict(s) for s in MANUAL_SWINGS]
    else:
        legs = [
            leg for leg in _clean_legs(candles, atr, pivots, min_bars=MIN_BARS, mult=4.0)
            if leg["parent_ts"] >= RECENT_3M_FROM
        ]
    return apply_overrides(legs)  # honour existing human verdicts


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "recent"
    candles = load_candle_input(DEFAULT_INPUT_PATH).candles
    atr = calculate_atr14(candles)
    pivots = detect_local_pivots(candles)
    setups = _load_setups(mode, candles, atr, pivots)
    if not setups:
        print("No setups to review.")
        return
    print(f"Reviewing {len(setups)} setups ({mode}). Use the panel in the TradingView window.")

    driver, attached = _make_driver()
    if not attached or "tradingview.com/chart" not in driver.current_url:
        driver.get(LAYOUT_URL)
        time.sleep(10)
    svc = DB1TradingViewSyncService()
    ctx = svc._detect_chart_time_context(driver)
    maps = _build_epoch_maps(candles, [ctx.effective_chart_timezone, "UTC", "Asia/Nicosia"])

    driver.execute_script(INJECT_PANEL_JS)
    driver.execute_cdp_cmd("Page.bringToFront", {})

    i = 0
    last_seq = 0

    def show(extra=""):
        leg = setups[i]
        _place_window(driver, setups, i, ctx)
        driver.execute_script(
            "window.__reviewStatus(arguments[0], arguments[1]);",
            f"DB1 Review  {i + 1}/{len(setups)}",
            _info_html(i, len(setups), leg, extra),
        )

    show()
    print("Panel ready. Reviewing live; press Ctrl-C here to stop early.")
    try:
        while True:
            action = driver.execute_script("return window.__reviewAction;")
            seq = action.get("seq", 0) if isinstance(action, dict) else 0
            if seq <= last_seq:
                time.sleep(0.4)
                continue
            last_seq = seq
            act = action.get("action")
            leg = setups[i]
            if act == "done":
                break
            elif act == "next":
                i = (i + 1) % len(setups)
                show()
            elif act == "back":
                i = (i - 1) % len(setups)
                show()
            elif act == "accept":
                append_label(make_label(leg, VERDICT_ACCEPT, detector_params=DETECTOR_PARAMS))
                print(f"  accept  {leg['parent_ts']} -> {leg['term_ts']}")
                i = (i + 1) % len(setups)
                show("saved: accepted")
            elif act == "reject":
                append_label(make_label(leg, VERDICT_REJECT, detector_params=DETECTOR_PARAMS))
                print(f"  reject  {leg['parent_ts']} -> {leg['term_ts']}")
                i = (i + 1) % len(setups)
                show("saved: rejected")
            elif act == "save":
                corrected, res = _capture_adjustment(driver, candles, maps)
                if corrected is None:
                    print(f"  save FAILED: {res}")
                    show("edit read-back failed; drag anchors onto candles")
                    continue
                append_label(
                    make_label(leg, VERDICT_ADJUST, corrected=corrected, detector_params=DETECTOR_PARAMS)
                )
                print(f"  adjust  -> {corrected['direction']} {corrected['parent_ts']} "
                      f"{corrected['parent_price']:.1f} -> {corrected['term_ts']} {corrected['term_price']:.1f}")
                setups[i] = {**leg, **corrected}
                show("saved: adjusted (snapped to candle extremes)")
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopped.")
    print("Review session ended. Labels in data/discovery_bet_1/human_labels.jsonl")


if __name__ == "__main__":
    main()
