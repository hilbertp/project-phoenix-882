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

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

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
    VERDICT_ADD,
    VERDICT_ADJUST,
    VERDICT_REJECT,
    append_label,
    apply_overrides,
    latest_by_key,
    load_labels,
    make_label,
    setup_key,
)
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from scripts.execute_fib_strategy import execute
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
var __oldPanel = document.getElementById('db1-review-panel');
if (__oldPanel) { __oldPanel.remove(); }  // always rebuild so the latest buttons show
window.__reviewSeq = 0;
window.__reviewAction = null;
const p = document.createElement('div');
p.id = 'db1-review-panel';
p.style.cssText = 'position:fixed;top:90px;right:18px;z-index:2147483647;background:#1e222d;color:#fff;padding:10px;border-radius:8px;font:12px -apple-system,sans-serif;box-shadow:0 2px 14px rgba(0,0,0,.6);width:280px';
function b(label, act, bg){ return '<button data-act="'+act+'" style="margin:2px;padding:6px 9px;border:0;border-radius:4px;cursor:pointer;background:'+bg+';color:#fff;font-size:12px">'+label+'</button>'; }
p.innerHTML =
  '<div id="db1rv-title" style="font-weight:bold;margin-bottom:6px">DB1 Setup Review</div>' +
  '<div>' + b('◀ Back','back','#363a45') + b('Next ▶','next','#2962ff') + '</div>' +
  '<div>' + b('✓ exaaaactly (to the ms)','accept','#26a69a') + b('✗ wtf','reject','#ef5350') + '</div>' +
  '<div>' + b('✎ Save edit','save','#f0b90b') + b('Done','done','#363a45') + b('ⓘ Info','info','#1f6feb') + '</div>' +
  '<div>' + b('+ Report missed setup','report-missed','#8957e5') + '</div>' +
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

# Read back a Fib the HUMAN drew (to report a missed setup): the most recent Fib
# whose name is NOT one of the controller's (auto / CANDIDATE / REVIEWING).
READBACK_MANUAL_JS = r"""
const c = window._exposed_chartWidgetCollection;
if (!c) { return {ok:false, error:'no collection'}; }
const model = c._activeChartWidgetModel.value();
const chartModel = model.model();
const bars = model.mainSeries().data();
const epochByIndex = {};
bars.each((index, value) => { epochByIndex[index] = value[0]; });
const lts = chartModel.allLineTools();
let fib = null;
for (let i=lts.length-1;i>=0;i--){
    const t=lts[i]; const s=t&&t.state&&t.state();
    if(!(s&&s.type==='LineToolFibRetracement')) continue;
    let txt='';
    try { const ch=t.properties().childs(); txt=(ch.editableText&&ch.editableText.value&&ch.editableText.value())||(ch.title&&ch.title.value&&ch.title.value())||''; } catch(e){}
    if (!/auto\d|CANDIDATE|REVIEWING/.test(String(txt))) { fib = t; break; }
}
if(!fib){ return {ok:false, error:'no hand-drawn Fib found -- draw the missed setup with the Fib tool first'}; }
let pts = null;
try { pts = fib.points(); } catch(e) {}
if(!pts || !pts.length){ try { const st=fib.state(); pts = st && st.points; } catch(e) {} }
if(!pts || pts.length < 2){ return {ok:false, error:'no points'}; }
function epochOf(pt){ if(pt.index!=null && epochByIndex[pt.index]!=null) return epochByIndex[pt.index]; return pt.time_t!=null?pt.time_t:null; }
return {ok:true, points: pts.slice(0,2).map(pt=>({epoch: epochOf(pt), price: pt.price}))};
"""

CLEAR_JS = "const c=window._exposed_chartWidgetCollection; if(c){c._activeChartWidgetModel.value().removeAllDrawingTools();}"

# A custom Fib template applies after creation and blanks the text we set, so the
# Object-Tree name (which reads editableText) is lost. Re-apply name = title once
# the template has settled.
REAPPLY_NAMES_JS = r"""
const m = window._exposed_chartWidgetCollection._activeChartWidgetModel.value();
let n = 0;
for (const t of m.model().allLineTools()) {
    const s = t && t.state && t.state();
    if (!(s && s.type === 'LineToolFibRetracement')) continue;
    try {
        const ch = t.properties().childs();
        const nm = ch.title && ch.title.value && ch.title.value();
        if (nm && ch.editableText && ch.editableText.setValue) { ch.editableText.setValue(nm); n++; }
        if (ch.showText && ch.showText.setValue) { ch.showText.setValue(true); }
    } catch (e) {}
}
return n;
"""


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


def _load_recent_range(driver):
    """Load ~3 months of 1H bars so the recent setups' anchors resolve; the
    default chart view only loads ~300 bars (about two weeks)."""
    try:
        btn = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'button[data-name="date-range-tab-3M"]')
            )
        )
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(7)
    except Exception as exc:
        print(f"warning: 3M range click skipped ({type(exc).__name__}); "
              "some setups may not place")


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


def _missing_candidate(a, b):
    """The opposite leg implied between two consecutive same-direction setups:
    a's terminal extreme -> b's parent extreme (the short missing between two longs,
    or the long missing between two shorts)."""
    return {
        "id": "candidate",
        "candidate": True,
        "direction": "down" if a["direction"] == "up" else "up",
        "parent_ts": a["term_ts"], "parent_price": a["term_price"], "parent_kind": a["term_kind"],
        "term_ts": b["parent_ts"], "term_price": b["parent_price"], "term_kind": b["parent_kind"],
    }


def _expand_with_candidates(setups):
    """Insert a CANDIDATE missing leg between every pair of consecutive
    same-direction setups so the reviewer can see and judge it."""
    out = []
    for k, leg in enumerate(setups):
        leg.setdefault("id", f"auto{k + 1}")
        out.append(leg)
        if k + 1 < len(setups) and setups[k + 1]["direction"] == leg["direction"]:
            out.append(_missing_candidate(leg, setups[k + 1]))
    return out


def _annotate_span_depth(leg, idx_map, atr):
    """Attach candle span and ATR depth (the detector's quality gauges)."""
    pi = idx_map.get(leg["parent_ts"])
    ti = idx_map.get(leg["term_ts"])
    if pi is not None and ti is not None:
        leg["span"] = abs(ti - pi)
        denom = atr[ti] or atr[pi] or 1.0
        leg["depth"] = abs(leg["term_price"] - leg["parent_price"]) / denom
    return leg


# Success measured off the Fib level reach: if 0.786 is never tagged it's a
# miss/shrug (no trade); otherwise the furthest level reached sets win/loss.
_OUTCOME_LABEL = {
    "no_trigger": ("miss / shrug — 0.786 never tagged", "miss"),
    "no_entry": ("miss / shrug — no entry", "miss"),
    "wipeout": ("LOSS — stopped at 1.05", "loss"),
    "tp1_then_scratch": ("scratch — TP1 then break-even", "scratch"),
    "tp2_then_scratch": ("partial — TP2 then break-even", "partial"),
    "tp3_full": ("WIN — full 0.0 target", "win"),
    "open_no_tp": ("open — entered, no TP yet", "open"),
    "open_tp1": ("open — past TP1", "open"),
    "open_tp2": ("open — past TP2", "open"),
}


def _annotate_outcome(leg, candles, idx_map):
    """Run the Fib trade plan and attach the success outcome + blended R."""
    try:
        res = execute(candles, idx_map, leg)
    except Exception:
        return leg
    label, kind = _OUTCOME_LABEL.get(res["status"], (res["status"], "open"))
    leg["outcome"] = label
    leg["outcome_kind"] = kind
    leg["outcome_r"] = res["r"]
    return leg


def _window_name(setups, j, role):
    leg = setups[j]
    pd = f"{leg['parent_ts'][8:10]}-{leg['parent_ts'][5:7]}"
    td = f"{leg['term_ts'][8:10]}-{leg['term_ts'][5:7]}"
    if leg.get("candidate"):
        kind = "short" if leg["direction"] == "down" else "long"
        return f"CANDIDATE missing {kind} {pd}->{td}"
    return f"{leg.get('id', 'auto' + str(j + 1))} {role} {leg['direction']} {pd}->{td}"


def _place_current(driver, setups, i, ctx):
    """Show ONE Fib at a time -- only the current setup. Overlapping prev/next
    Fibs made visual review confusing; Back/Next swaps the single chart instead."""
    driver.execute_script(CLEAR_JS)
    placed = _place_one(driver, setups[i], _window_name(setups, i, "<< REVIEWING >>"), ctx)
    time.sleep(0.3)  # let the custom Fib template settle, then re-apply the name
    driver.execute_script(REAPPLY_NAMES_JS)
    return placed


def _capture_adjustment(driver, candles, maps, readback_js=READBACK_FIB_JS):
    """Read a Fib back, snap each anchor to its candle's extreme, and return a
    leg dict (or None if read-back failed). readback_js selects which Fib:
    the current REVIEWING one (default) or the human's hand-drawn one."""
    res = driver.execute_script(readback_js)
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


_VERDICT_BADGE = {
    "accept": ("&#10003; ACCEPTED", "#26a69a"),
    "reject": ("&#10007; REJECTED", "#ef5350"),
    "adjust": ("&#9998; ADJUSTED", "#f0b90b"),
    "add": ("&#43; ADDED (missing)", "#8957e5"),
}

_OUTCOME_COLOR = {
    "win": "#26a69a",
    "loss": "#ef5350",
    "partial": "#3fb950",
    "scratch": "#d29922",
    "miss": "#6b7785",
    "open": "#58a6ff",
}

_HELP_HTML = (
    "<b style='color:#58a6ff'>How your edits are saved</b><br>"
    "&bull; <b>Fix a setup:</b> drag the current Fib's anchors to the right "
    "pivots, then <b>Save edit</b>.<br>"
    "&bull; <b>Add a missed one:</b> draw a NEW Fib with TradingView's Fib tool, "
    "then <b>+ Report missed</b>.<br>"
    "The system reads the Fib you changed, <b>snaps</b> it to the exact candle "
    "high/low, redraws it, and echoes back what it captured. If that echo matches "
    "what you drew, it's <b>persisted</b> as your feedback. If it's wrong, just "
    "redraw and click again (latest wins)."
)


def _capture_confirm(leg, what):
    """Echo back exactly what the system read, so the user can confirm it understood."""
    pd = leg["parent_ts"][5:16]
    td = leg["term_ts"][5:16]
    return (
        f"<b style='color:#26a69a'>&#10003; {what} &mdash; system read your chart as:</b><br>"
        f"<b>{leg['direction']}</b> &nbsp; {leg['parent_price']:.0f} ({pd}) "
        f"&rarr; {leg['term_price']:.0f} ({td})<br>"
        f"snapped to candle extremes &amp; <b>persisted</b>. "
        f"Not what you drew? Redraw &amp; click again."
    )


def _info_html(i, n, leg, extra="", verdict=None):
    if verdict:
        txt, col = _VERDICT_BADGE.get(verdict, (verdict.upper(), "#9aa4b2"))
        badge = f"<div style='font-weight:bold;color:{col};margin-bottom:4px'>{txt}</div>"
    else:
        badge = "<div style='color:#6b7785;margin-bottom:4px'>&bull; not reviewed yet</div>"
    head = ""
    if leg.get("candidate"):
        kind = "short" if leg["direction"] == "down" else "long"
        head = (f"<b style='color:#f0b90b'>CANDIDATE missing {kind}</b> &mdash; "
                f"real setup? Accept / Reject<br>")
    meta = ""
    if leg.get("span") is not None:
        min_bars = DETECTOR_PARAMS["min_bars"]
        min_atr = DETECTOR_PARAMS["atr_mult"]
        span_ok = leg["span"] >= min_bars
        depth_ok = leg["depth"] >= min_atr
        meta = (f"<br><b style='color:#cdd9e5'>{leg['span']} candles</b> &middot; "
                f"<b style='color:#cdd9e5'>{leg['depth']:.1f} ATR</b> deep")
        if span_ok and depth_ok:
            meta += (f"<br><span style='color:#26a69a'>&#10003; clears gates "
                     f"(&ge;{min_bars}c, &ge;{min_atr:.0f}&times; ATR)</span>")
        else:
            why = []
            if not span_ok:
                why.append(f"{leg['span']}c &lt; {min_bars}")
            if not depth_ok:
                why.append(f"{leg['depth']:.1f} &lt; {min_atr:.0f}&times; ATR")
            meta += (f"<br><span style='color:#ef5350'>&#10007; below gate: "
                     f"{' &amp; '.join(why)} &rarr; detector skipped it</span>")
    outcome = ""
    if leg.get("outcome"):
        ocol = _OUTCOME_COLOR.get(leg.get("outcome_kind"), "#9aa4b2")
        outcome = (f"<br><b style='color:{ocol}'>{leg['outcome']}</b> "
                   f"({leg.get('outcome_r', 0.0):+.2f}R)")
    return (
        badge
        + head
        + f"{i + 1} / {n} &nbsp; <b>{leg['direction']}</b><br>"
        f"{leg['parent_ts'][5:16]} &rarr; {leg['term_ts'][5:16]}<br>"
        f"{leg['parent_price']:.0f} &rarr; {leg['term_price']:.0f}"
        + meta
        + outcome
        + f"{('<br>' + extra) if extra else ''}"
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
    _load_recent_range(driver)
    # A freshly launched TradingView chart loads only a limited bar window, and
    # the date-range tabs are not always present to widen it. Keep only setups
    # whose anchors fall inside the currently-loaded bars so every shown setup
    # actually places. (Full-history loading is a separate, Codex-owned fix.)
    loaded_n = driver.execute_script(
        "let n=0; const c=window._exposed_chartWidgetCollection;"
        "if(c){c._activeChartWidgetModel.value().model().mainSeries().data().each(()=>{n++});}"
        " return n;"
    ) or 0
    if loaded_n and int(loaded_n) < len(candles):
        # Margin so the earliest kept setup's anchor is safely inside the loaded
        # window (the very first loaded bar can be just short of a boundary anchor).
        cutoff = candles[max(0, len(candles) - int(loaded_n) + 60)].source_timestamp
        kept = [s for s in setups if s["parent_ts"] >= cutoff and s["term_ts"] >= cutoff]
        if kept:
            print(f"Chart has {loaded_n} bars loaded -> reviewing {len(kept)} of "
                  f"{len(setups)} setups that fall inside that window.")
            setups[:] = kept
    # Insert CANDIDATE missing legs wherever two same-direction setups sit in a row.
    setups[:] = _expand_with_candidates(setups)
    idx_map = {c.source_timestamp: k for k, c in enumerate(candles)}
    for s in setups:
        _annotate_span_depth(s, idx_map, atr)
        _annotate_outcome(s, candles, idx_map)
    n_cand = sum(1 for s in setups if s.get("candidate"))
    if n_cand:
        print(f"Inserted {n_cand} candidate missing setups (same-direction gaps) to judge.")
    svc = DB1TradingViewSyncService()
    ctx = svc._detect_chart_time_context(driver)
    maps = _build_epoch_maps(candles, [ctx.effective_chart_timezone, "UTC", "Asia/Nicosia"])

    driver.execute_script(INJECT_PANEL_JS)
    # Reset the panel's action counter so a restart never replays a stale click.
    driver.execute_script("window.__reviewSeq = 0; window.__reviewAction = null;")
    driver.execute_cdp_cmd("Page.bringToFront", {})

    # Per-setup verdict so the panel shows accepted/rejected/adjusted/added.
    # Seed from existing labels (matched by anchor key) so prior reviews show too.
    existing = latest_by_key(load_labels())
    reviewed = {
        k: existing[setup_key(s["parent_ts"], s["term_ts"])].verdict
        for k, s in enumerate(setups)
        if setup_key(s["parent_ts"], s["term_ts"]) in existing
    }
    i = 0
    last_seq = 0

    def show(extra=""):
        leg = setups[i]
        _place_current(driver, setups, i, ctx)
        driver.execute_script(
            "window.__reviewStatus(arguments[0], arguments[1]);",
            f"DB1 Review  {i + 1}/{len(setups)}",
            _info_html(i, len(setups), leg, extra, verdict=reviewed.get(i)),
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
            is_cand = leg.get("candidate", False)
            if act == "done":
                break
            elif act == "next":
                i = (i + 1) % len(setups)
                show()
            elif act == "back":
                i = (i - 1) % len(setups)
                show()
            elif act == "info":
                driver.execute_script(
                    "window.__reviewStatus(arguments[0], arguments[1]);",
                    "DB1 Review — how feedback works",
                    _HELP_HTML,
                )
            elif act == "accept":
                # Accepting a candidate = "this missing setup is real" -> add.
                verdict = VERDICT_ADD if is_cand else VERDICT_ACCEPT
                append_label(make_label(leg, verdict, detector_params=DETECTOR_PARAMS))
                reviewed[i] = verdict
                print(f"  {verdict}  {leg['parent_ts']} -> {leg['term_ts']}")
                i = (i + 1) % len(setups)
                show(f"saved: {verdict}")
            elif act == "reject":
                # Rejecting a candidate = "no real setup here" -> reject (don't loosen for it).
                append_label(make_label(leg, VERDICT_REJECT, detector_params=DETECTOR_PARAMS))
                reviewed[i] = VERDICT_REJECT
                print(f"  reject  {leg['parent_ts']} -> {leg['term_ts']}")
                i = (i + 1) % len(setups)
                show("saved: rejected")
            elif act == "save":
                corrected, res = _capture_adjustment(driver, candles, maps)
                if corrected is None:
                    print(f"  save FAILED: {res}")
                    show("edit read-back failed; drag anchors onto candles")
                    continue
                verdict = VERDICT_ADD if is_cand else VERDICT_ADJUST
                append_label(
                    make_label(leg, verdict, corrected=corrected, detector_params=DETECTOR_PARAMS)
                )
                print(f"  {verdict}  -> {corrected['direction']} {corrected['parent_ts']} "
                      f"{corrected['parent_price']:.1f} -> {corrected['term_ts']} {corrected['term_price']:.1f}")
                reviewed[i] = verdict
                setups[i] = {**leg, **corrected}
                show(_capture_confirm(corrected, "edit saved"))
            elif act == "report-missed":
                # The human drew a Fib on a setup the detector missed: snap it, add it
                # to the list, and jump to it so its span/ATR vs the gates explain the miss.
                corrected, res = _capture_adjustment(driver, candles, maps, READBACK_MANUAL_JS)
                if corrected is None:
                    show("Draw the missed setup with the Fib tool, then click Report missed.")
                    continue
                corrected["id"] = "reported"
                corrected["reported"] = True
                _annotate_span_depth(corrected, idx_map, atr)
                append_label(make_label(corrected, VERDICT_ADD, detector_params=DETECTOR_PARAMS))
                setups.append(corrected)
                reviewed[len(setups) - 1] = VERDICT_ADD
                i = len(setups) - 1
                print(f"  add (missed)  {corrected['direction']} {corrected['parent_ts']} "
                      f"{corrected['parent_price']:.1f} -> {corrected['term_ts']} {corrected['term_price']:.1f} "
                      f"({corrected.get('span','?')}c {corrected.get('depth',0):.1f}a)")
                show(_capture_confirm(corrected, "missed setup added"))
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopped.")
    print("Review session ended. Labels in data/discovery_bet_1/human_labels.jsonl")


if __name__ == "__main__":
    main()
