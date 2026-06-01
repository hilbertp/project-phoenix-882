#!/usr/bin/env python
"""WSAD-driven TradingView review of ADA 15m setups in the last 3 months.

End-to-end:
  1. Loads data/discovery_bet_1/binance_adausdt_15m_full_history.csv
  2. Detects clean swing legs at 6c / 2.0x ATR (project default for 15m).
  3. Filters to the last 3 months (calendar window, anchored to TODAY).
  4. Connects to debug Chrome on :9222 (run scripts/tv-login.sh first if not up).
  5. Navigates the active tab to BITGET:ADAUSDT.P @ 15m and waits for bars.
  6. Injects the floating WSAD review panel onto the chart and walks through
     each setup, auto-panning to it, scoring it against the 0.941 entry regime.
  7. Verdicts append to data/discovery_bet_1/human_labels.jsonl with the
     'asset':'ADA' marker so we can pivot the BTC vs ADA review streams later.
  8. On exit (Enter or Ctrl-C), writes a Markdown session report to
     artifacts/discovery_bet_1/manual_review_ada_15m/SESSION_<ts>.md
     summarising verdicts, per-cohort breakdown, and the 0.941 R-rollup.

Usage:
  ./scripts/tv-ada.sh            # canonical wrapper -- recommended
  PYTHONPATH=. .venv/bin/python scripts/tv_review_ada_15m.py
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.human_labels import (
    VERDICT_ACCEPT,
    VERDICT_ADJUST,
    VERDICT_REJECT,
    append_label,
    make_label,
)
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.swing_detector import clean_legs as _clean_legs
from apps.worker.discovery_bet_1.types import Candle
from scripts.build_dashboard import KIND
from scripts.execute_fib_strategy import execute
from scripts.place_fibs_tradingview import (
    PLACE_FIB_JS,
    REMOVE_VOLUME_JS,
)
from scripts.review_fibs_tradingview import (
    CLEAR_JS,
    INJECT_PANEL_JS,
    NAVIGATE_TO_FIB_JS,
    REAPPLY_NAMES_JS,
    _annotate_outcome,
    _annotate_span_depth,
    _info_html,
)
import scripts.review_fibs_tradingview as _rf

# Override the shared DETECTOR_PARAMS so the panel's gate-check line (rendered
# by _info_html) shows our ADA-specific thresholds. _info_html resolves the
# constants via the module's namespace, so mutating the dict here is enough.
_rf.DETECTOR_PARAMS["min_bars"] = 6
_rf.DETECTOR_PARAMS["atr_mult"] = 2.0


# ADA-specific panel: simpler verdict scheme.
#   W / Up    = all ok                       (VERDICT_ACCEPT)
#   S / Down  = something wrong -> sub-menu  (then R or F)
#     R       = setup is wrong (anchors)     (VERDICT_ADJUST)
#     F       = outcome is wrong (scoring)   (VERDICT_REJECT)
#     Escape  = cancel sub-menu
#   A / Left  = previous setup
#   D / Right = next setup
#   Enter     = Done (end session, write report)
ADA_INJECT_PANEL_JS = r"""
if (window.__reviewKeyHandler) {
  document.removeEventListener('keydown', window.__reviewKeyHandler, true);
}
var __oldPanel = document.getElementById('db1rv-panel');
if (__oldPanel) { __oldPanel.remove(); }
window.__reviewSeq = 0;
window.__reviewAction = null;
var p = document.createElement('div');
p.id = 'db1rv-panel';
// Position on the LEFT side (past the ~60px drawing-tools toolbar) so the
// panel never hides behind TV's right-side Object Tree / Data Window pane.
p.style.cssText = 'position:fixed;top:90px;left:80px;z-index:2147483647;background:#1e222d;color:#fff;padding:10px;border-radius:8px;font:12px -apple-system,sans-serif;box-shadow:0 2px 14px rgba(0,0,0,.6);width:320px';
function b(label, act, bg, title){
  return '<button data-act="'+act+'" title="'+(title||'')+'" '+
    'style="margin:2px;padding:7px 10px;border:0;border-radius:4px;cursor:pointer;background:'+bg+';color:#fff;font-size:12px">'+label+'</button>';
}
p.innerHTML =
  '<div id="db1rv-title" style="font-weight:bold;margin-bottom:8px">ADA 15m Review</div>' +
  '<div id="db1rv-main">' +
    '<div>' + b('◀ Back (A)','back','#363a45','Previous setup') +
              b('Next (D) ▶','next','#2962ff','Next setup') + '</div>' +
    '<div>' + b('✓ all ok (W)','accept','#26a69a','Setup AND outcome look right') +
              b('✗ something wrong (S)','wrong','#ef5350','Either setup or outcome is wrong (then press R or F)') + '</div>' +
    '<div>' + b('Done — end session (Enter)','done','#363a45',
                  'End the review. Session report is written to artifacts/discovery_bet_1/manual_review_ada_15m/') + '</div>' +
  '</div>' +
  '<div id="db1rv-wrong" style="display:none;border:1px solid #f0b90b;border-radius:6px;padding:8px;margin-top:6px">' +
    '<div style="margin-bottom:6px;font-weight:bold;color:#f0b90b">Whats wrong?</div>' +
    '<div>' + b('Setup wrong (R)','wrong_setup','#7a6a1f',
                  'Anchors do not match a real swing (VERDICT_ADJUST)') +
              b('Outcome wrong (F)','wrong_outcome_pick','#7a2f31',
                  'Anchors fine but executor scored the wrong outcome (then pick 1/2/3/L/M)') + '</div>' +
    '<div style="margin-top:5px;font-size:10px;color:#9aa4b2">Esc to cancel</div>' +
  '</div>' +
  '<div id="db1rv-outcome" style="display:none;border:1px solid #ef5350;border-radius:6px;padding:8px;margin-top:6px">' +
    '<div style="margin-bottom:6px;font-weight:bold;color:#ef5350">What was the correct outcome?</div>' +
    '<div>' + b('TP1 (1)','expected_tp1','#7a6a1f','Trade should have scored TP1 (small partial)') +
              b('TP2 (2)','expected_tp2','#7a5230','Trade should have scored TP2 (decent partial)') +
              b('TP3 (3)','expected_tp3','#1f6f63','Trade should have scored TP3 (full win)') + '</div>' +
    '<div>' + b('Loss (L)','expected_loss','#7a2f31','Trade should have been a -1R loss') +
              b('Miss (M)','expected_miss','#363a45','Trade should never have triggered') + '</div>' +
    '<div style="margin-top:5px;font-size:10px;color:#9aa4b2">Esc to cancel</div>' +
  '</div>' +
  '<div style="font-size:10px;color:#6b7785;margin-top:8px;line-height:1.5">' +
    'keys: <b>W</b>=all ok &middot; <b>S</b>=wrong (then <b>R</b>=setup / <b>F</b>=outcome &rarr; <b>1/2/3/L/M</b>) &middot; ' +
    '<b>A</b>/<b>D</b>=prev/next &middot; <b>Enter</b>=done' +
  '</div>' +
  '<div id="db1rv-info" style="margin-top:7px;font-size:11px;color:#9aa4b2;line-height:1.4"></div>';
document.body.appendChild(p);
// Three-stage panel state:
//   'main'    : show main buttons (Back/Next/all-ok/wrong/done)
//   'wrong'   : show R/F sub-menu (after S pressed)
//   'outcome' : show 1/2/3/L/M sub-menu (after F pressed)
function __setMode(which){
  document.getElementById('db1rv-main').style.display    = (which === 'main')    ? 'block' : 'none';
  document.getElementById('db1rv-wrong').style.display   = (which === 'wrong')   ? 'block' : 'none';
  document.getElementById('db1rv-outcome').style.display = (which === 'outcome') ? 'block' : 'none';
}
function __emit(act){
  __setMode('main');
  window.__reviewSeq = (window.__reviewSeq || 0) + 1;
  window.__reviewAction = {seq: window.__reviewSeq, action: act};
}
function __handle(act){
  if (act === 'wrong')              { __setMode('wrong');   return; }
  if (act === 'wrong_outcome_pick') { __setMode('outcome'); return; }
  if (act === 'cancel')             { __setMode('main');    return; }
  __emit(act);
}
p.querySelectorAll('button').forEach(function(btn){
  btn.onclick = function(){ __handle(btn.getAttribute('data-act')); };
});
window.__reviewStatus = function(title, info){
  var t = document.getElementById('db1rv-title');
  if (t) t.textContent = title;
  var i = document.getElementById('db1rv-info');
  if (i && info != null) i.innerHTML = info;
};
window.__reviewKeyHandler = function(e){
  if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable)) return;
  var inWrong   = document.getElementById('db1rv-wrong').style.display   === 'block';
  var inOutcome = document.getElementById('db1rv-outcome').style.display === 'block';
  var k = (e.key || '').toLowerCase();
  var act = null;
  if (inOutcome) {
    // 1/2/3/L/M -> emit verdict + correct-outcome tag; Esc -> back to main
    if (k === '1')      act = 'expected_tp1';
    else if (k === '2') act = 'expected_tp2';
    else if (k === '3') act = 'expected_tp3';
    else if (k === 'l') act = 'expected_loss';
    else if (k === 'm') act = 'expected_miss';
    else if (k === 'escape') { __setMode('main'); e.preventDefault(); e.stopPropagation(); return; }
  } else if (inWrong) {
    // R -> emit setup-wrong verdict; F -> step into outcome-correction;
    // Esc -> back to main; A/D/Enter cancel-then-act.
    if (k === 'r')                 act = 'wrong_setup';
    else if (k === 'f')            { __setMode('outcome'); e.preventDefault(); e.stopPropagation(); return; }
    else if (k === 'escape')       { __setMode('main'); e.preventDefault(); e.stopPropagation(); return; }
    else if (k === 'a' || k === 'arrowleft')  { __setMode('main'); act = 'back'; }
    else if (k === 'd' || k === 'arrowright') { __setMode('main'); act = 'next'; }
    else if (k === 'enter')        { __setMode('main'); act = 'done'; }
  } else {
    var m = {
      w:'accept', arrowup:'accept',
      s:'wrong',  arrowdown:'wrong',
      a:'back',   arrowleft:'back',
      d:'next',   arrowright:'next',
      enter:'done'
    };
    act = m[k];
  }
  if (act) {
    __handle(act);
    e.preventDefault();
    e.stopPropagation();
  }
};
document.addEventListener('keydown', window.__reviewKeyHandler, true);
return {ok:true, panel_created: !!document.getElementById('db1rv-panel')};
"""
from apps.api.db1_review_tradingview.service import (
    DB1TradingViewSyncService,
    TradingViewMarketContract,
    TradingViewReviewStructure,
    TradingViewSyncRequest,
    _build_expected_line_tool_points,
)
from apps.worker.discovery_bet_1.types import PivotKind

# --- ADA 15m config ---
# IMPORTANT: SYMBOL must match the data source. The CSV is from Binance public
# REST (spot ADAUSDT) so the TV chart MUST be BINANCE:ADAUSDT (spot), NOT
# BITGET:ADAUSDT.P (Bitget perp). Mismatched exchanges -> different OHLC per
# candle -> parent/term dots land on bars with different highs/lows -> "anchors
# very very badly mismatched". We learned this the hard way on a real review.
SYMBOL = "BINANCE:ADAUSDT"
TV_INTERVAL = "15"
CHART_URL = f"https://www.tradingview.com/chart/?symbol={SYMBOL.replace(':', '%3A')}&interval={TV_INTERVAL}"
CSV_PATH = REPO_ROOT / "data/discovery_bet_1/binance_adausdt_15m_full_history.csv"
MIN_BARS = 6
ATR_MULT = 2.0
DEBUG_PORT = 9222

OUT_DIR = REPO_ROOT / "artifacts/discovery_bet_1/manual_review_ada_15m"
LABELS_PATH = REPO_ROOT / "data/discovery_bet_1/human_labels.jsonl"


def load_csv(path: Path) -> list[Candle]:
    out: list[Candle] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Candle(row["source_timestamp"], float(row["open"]),
                              float(row["high"]), float(row["low"]),
                              float(row["close"]), float(row["volume"])))
    return out


def attach_chrome():
    """Attach to running debug Chrome. Errors with a clear hint if not up."""
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{DEBUG_PORT}")
    try:
        return webdriver.Chrome(options=opts)
    except WebDriverException as exc:
        raise SystemExit(
            f"No debug Chrome on 127.0.0.1:{DEBUG_PORT}. Run:\n"
            f"  ./scripts/tv-login.sh\n"
            f"first and log into TradingView, then re-run this script.\n"
            f"(Underlying error: {exc})"
        )


def navigate_to_ada(driver):
    """Navigate the active tab to ADA 15m, waiting for bars to load."""
    print(f"  navigating to {CHART_URL}")
    driver.get(CHART_URL)
    print("  waiting 15s for chart to load + render bars...", flush=True)
    time.sleep(15)


def _utc_iso(ts: str) -> str:
    """Tag a naive ISO timestamp as UTC so _source_timestamp_to_epoch_seconds
    takes the 'has tzinfo' branch (astimezone-to-UTC) instead of the broken
    'no tzinfo' branch that REPLACES the timezone with the chart's local TZ.

    The CSV is from Binance public REST -- timestamps are UTC epochs but
    stored as naive ISO strings. Without this tag, a Vienna-localized
    chart_time_zone shifts every anchor 2 hours earlier on every setup.
    """
    if "+" in ts or ts.endswith("Z"):
        return ts
    return ts + "+00:00"


def _request_for(leg):
    """Build a TradingViewSyncRequest matching the dataclass schema in
    apps.api.db1_review_tradingview.service (singular review_structure,
    structure_id not review_id, anchor_* not pivot_*).

    Timestamps get an explicit UTC tag so the chart_time_zone naive-handling
    branch doesn't silently shift our anchors into the chart's local time.
    """
    return TradingViewSyncRequest(
        market_contract=TradingViewMarketContract(SYMBOL, "15M"),
        review_structure=TradingViewReviewStructure(
            structure_id=str(leg.get("name") or leg.get("id", "auto")),
            direction=leg["direction"],
            parent_anchor_source_timestamp=_utc_iso(leg["parent_ts"]),
            parent_anchor_price=leg["parent_price"],
            parent_anchor_kind=leg["parent_kind"],
            terminal_extreme_source_timestamp=_utc_iso(leg["term_ts"]),
            terminal_extreme_price=leg["term_price"],
            terminal_extreme_kind=leg["term_kind"],
        ),
    )


def place_one(driver, leg, name, ctx):
    """Place a single Fib retracement on the chart, named for the Object Tree."""
    req = _request_for({**leg, "name": name})
    for tz in (ctx.effective_chart_timezone, "UTC"):
        pts = _build_expected_line_tool_points(req, chart_time_zone=tz)
        mapped = {
            "parentPoint": {"price": pts[0]["price"], "time_t": pts[0]["time_t"]},
            "terminalPoint": {"price": pts[1]["price"], "time_t": pts[1]["time_t"]},
        }
        result = driver.execute_script(PLACE_FIB_JS, mapped, TV_INTERVAL, name, True)
        if isinstance(result, dict) and result.get("ok"):
            return True
    return False


def navigate_to_fib(driver, leg):
    """Auto-pan the chart so the current setup is centered + visible."""
    try:
        parent_epoch = int(datetime.fromisoformat(leg["parent_ts"]).replace(
            tzinfo=ZoneInfo("UTC")).timestamp())
        term_epoch = int(datetime.fromisoformat(leg["term_ts"]).replace(
            tzinfo=ZoneInfo("UTC")).timestamp())
        return driver.execute_script(NAVIGATE_TO_FIB_JS, parent_epoch, term_epoch)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


_ADA_OUTCOME_STYLE = {
    # Five outcomes the user cares about (no internal-jargon names):
    # kind (executor status) -> (display label, color)
    "miss":    ("MISSED", "#9aa4b2"),   # gray
    "loss":    ("LOSS",   "#ef5350"),   # red
    "scratch": ("TP1",    "#f0b90b"),   # yellow (small partial)
    "partial": ("TP2",    "#f0a020"),   # orange (decent partial)
    "win":     ("TP3",    "#26a69a"),   # green (full target)
    "open":    ("OPEN",   "#9aa4b2"),   # gray (treat 'still running' as neutral)
}


def _ada_info_html(i: int, n: int, leg: dict, extra: str = "", verdict: str | None = None) -> str:
    """ADA panel info: ONE colored thing (the outcome), everything else neutral.

    Layout (top to bottom):
      [verdict badge if any   -- plain, no color]
      [BIG outcome             -- the ONLY colored element]
      setup i / n
      parent_ts -> term_ts
      N candles, X.X x ATR deep
      gate line (neutral)
    """
    parts = []

    # Verdict badge (if reviewed) -- plain, no color per user "remove all
    # color coding except for the outcome"
    if verdict:
        verdict_text = {
            "accept": "ACCEPTED",
            "adjust": "SETUP WRONG",
            "reject": "OUTCOME WRONG",
            "add":    "ADDED",
        }.get(verdict, verdict.upper())
        parts.append(
            f"<div style='font-weight:bold;font-size:12px;color:#cdd9e5;"
            f"margin-bottom:8px'>{verdict_text}</div>"
        )
    else:
        parts.append(
            "<div style='color:#6b7785;font-size:11px;margin-bottom:8px'>"
            "&bull; not reviewed yet</div>"
        )

    # THE BIG colored thing: outcome label. 24px, bold, the only color cue.
    kind = leg.get("outcome_kind") or "open"
    olabel, ocol = _ADA_OUTCOME_STYLE.get(kind, ("?", "#9aa4b2"))
    parts.append(
        f"<div style='font-weight:bold;font-size:24px;color:{ocol};"
        f"line-height:1.1;margin-bottom:12px;letter-spacing:0.04em'>"
        f"{olabel}</div>"
    )

    # Setup index (no direction -- the chart already shows up/down geometry)
    parts.append(
        f"<div style='font-size:11px;color:#6b7785;margin-bottom:4px'>"
        f"setup {i + 1} / {n}</div>"
    )

    # Timestamps in mono, plain
    parts.append(
        f"<div style='font-size:11px;color:#9aa4b2;font-family:ui-monospace,monospace;"
        f"margin-bottom:4px'>"
        f"{leg['parent_ts'][5:16]} &rarr; {leg['term_ts'][5:16]}"
        f"</div>"
    )

    # Span + depth (the detector's quality gauges) -- plain
    span = leg.get("span", "?")
    depth = leg.get("depth", 0.0)
    parts.append(
        f"<div style='font-size:11px;color:#cdd9e5;margin-bottom:2px'>"
        f"{span} candles &middot; {depth:.1f}&times; ATR deep"
        f"</div>"
    )

    # Gate-clear line: NEUTRAL gray (user explicitly asked: don't color this)
    if span != "?":
        min_bars = 6
        min_atr = 2.0
        span_ok = (isinstance(span, int) and span >= min_bars)
        depth_ok = (depth >= min_atr)
        if span_ok and depth_ok:
            gate_text = f"clears gates (&ge;{min_bars}c, &ge;{int(min_atr)}&times; ATR)"
        else:
            why = []
            if not span_ok:
                why.append(f"{span}c &lt; {min_bars}")
            if not depth_ok:
                why.append(f"{depth:.1f} &lt; {int(min_atr)}&times; ATR")
            gate_text = f"below gate: {' &amp; '.join(why)}"
        parts.append(
            f"<div style='font-size:10px;color:#9aa4b2;margin-bottom:2px'>{gate_text}</div>"
        )

    if extra:
        parts.append(f"<div style='font-size:11px;color:#6b7785;margin-top:6px'>{extra}</div>")

    return "".join(parts)


def cohort_for(depth_atr: float) -> str:
    if depth_atr < 6: return "4-6"
    if depth_atr < 8: return "6-8"
    if depth_atr < 10: return "8-10"
    if depth_atr < 12: return "10-12"
    if depth_atr < 16: return "12-16"
    return "16+"


def write_session_report(setups, verdicts, started_at, ended_at, out_path):
    """Markdown session report. Verdict counts + per-cohort breakdown + R rollup."""
    from collections import Counter
    n = len(verdicts)
    verdict_counts = Counter(verdicts.values())
    by_cohort = {}
    for k, leg in enumerate(setups):
        c = cohort_for(leg.get("depth", 0))
        by_cohort.setdefault(c, {"reviewed": 0, "accept": 0,
                                  "setup_wrong": 0, "outcome_wrong": 0, "skip": 0})
        if k in verdicts:
            by_cohort[c]["reviewed"] += 1
            v = verdicts[k]
            if v == VERDICT_ACCEPT:        by_cohort[c]["accept"] += 1
            elif v == "setup_wrong":       by_cohort[c]["setup_wrong"] += 1
            elif str(v).startswith("outcome_wrong"): by_cohort[c]["outcome_wrong"] += 1
        else:
            by_cohort[c]["skip"] += 1
    # R-rollup over what the user APPROVED (those are the trades the user
    # considers "real" -- their net R is the user-curated edge).
    accepted_r = [setups[k].get("outcome_r", 0.0) for k, v in verdicts.items()
                  if v == VERDICT_ACCEPT]
    n_accept = len(accepted_r)
    total_r = sum(accepted_r)
    wins = sum(1 for r in accepted_r if r > 0.5)
    losses = sum(1 for r in accepted_r if r <= -0.5)
    scratches = n_accept - wins - losses
    elapsed = (ended_at - started_at).total_seconds()
    lines = [
        f"# ADA 15m manual review session",
        f"",
        f"- **Started:** {started_at.isoformat(timespec='seconds')}",
        f"- **Ended:**   {ended_at.isoformat(timespec='seconds')}",
        f"- **Elapsed:** {elapsed:.0f}s ({elapsed/60:.1f} min)",
        f"- **Symbol:**  {SYMBOL} @ {TV_INTERVAL}m",
        f"- **Detector:** {MIN_BARS}c / {ATR_MULT}x ATR",
        f"- **Window:**  last 3 months",
        f"- **Total setups in window:** {len(setups)}",
        f"- **Reviewed:** {n} / {len(setups)}  ({n/max(1,len(setups))*100:.0f}%)",
        f"",
        f"## Verdict counts",
        f"",
        f"| Verdict | Count | Meaning |",
        f"|---|---|---|",
        f"| accept (W)             | {verdict_counts.get(VERDICT_ACCEPT, 0)} | all ok |",
        f"| setup wrong (S → R)    | {sum(1 for v in verdicts.values() if v == 'setup_wrong')} | not a real swing |",
        f"| outcome wrong (S → F)  | {sum(1 for v in verdicts.values() if str(v).startswith('outcome_wrong'))} | executor scored wrong |",
        f"| (skipped — no verdict) | {len(setups) - n} | not reviewed |",
        f"",
        f"## Per-cohort breakdown",
        f"",
        f"| Cohort (×ATR) | Total | Reviewed | Accept (W) | Setup-wrong (R) | Outcome-wrong (F) |",
        f"|---|---|---|---|---|---|",
    ]
    for cohort, c in sorted(by_cohort.items()):
        total = c["reviewed"] + c["skip"]
        lines.append(f"| {cohort} | {total} | {c['reviewed']} | {c['accept']} | {c['setup_wrong']} | {c['outcome_wrong']} |")
    lines += [
        f"",
        f"## 0.941 entry R, accepted setups only",
        f"",
        f"- **Triggered:** {n_accept}",
        f"- **Wins (R > +0.5):**  {wins}",
        f"- **Scratches:**        {scratches}",
        f"- **Losses (R < -0.5):** {losses}",
        f"- **Total R:** {total_r:+.2f}",
        f"- **Avg R / accepted trade:** {total_r / max(1, n_accept):+.3f}",
        f"",
        f"## Where verdicts went",
        f"",
        f"- File: `data/discovery_bet_1/human_labels.jsonl`",
        f"- Each verdict tagged `asset=ADA`. Filter with `jq 'select(.asset==\"ADA\")'`.",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    if not CSV_PATH.exists():
        raise SystemExit(f"missing {CSV_PATH}; run a long-history acquire first.")

    print(f"==> loading {CSV_PATH.name}...", flush=True)
    candles = load_csv(CSV_PATH)
    idx_map = {c.source_timestamp: i for i, c in enumerate(candles)}
    atr = calculate_atr14(candles)
    pivots = detect_local_pivots(candles)

    # Last 3 months from TODAY (not relative to the CSV's end -- the user wants
    # CALENDAR last-3-months, and the CSV is updated to ~now).
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=90)
    cutoff = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"==> filtering to setups with parent_ts >= {cutoff}", flush=True)

    legs = [l for l in _clean_legs(candles, atr, pivots,
                                   min_bars=MIN_BARS, mult=ATR_MULT)
            if l["term_ts"] in idx_map and l["parent_ts"] >= cutoff]
    print(f"==> {len(legs)} clean legs in window")

    for leg in legs:
        _annotate_span_depth(leg, idx_map, atr)
        _annotate_outcome(leg, candles, idx_map)

    # Filter out 'miss' outcomes: setups where the 0.941 entry never tagged
    # (the trade never triggered, nothing to review). Set
    # PHOENIX_REVIEW_INCLUDE_MISSES=1 to keep them in the review set.
    include_misses = os.environ.get("PHOENIX_REVIEW_INCLUDE_MISSES") in ("1", "true", "yes")
    if not include_misses:
        triggered = [l for l in legs if l.get("outcome_kind") != "miss"]
        n_missed = len(legs) - len(triggered)
        print(f"==> filtered out {n_missed} miss / shrug setups (0.941 never tagged). "
              f"{len(triggered)} triggered setups remain.")
        print(f"    set PHOENIX_REVIEW_INCLUDE_MISSES=1 to keep them.")
        legs = triggered
    else:
        print(f"==> keeping all {len(legs)} setups (PHOENIX_REVIEW_INCLUDE_MISSES set)")

    if not legs:
        raise SystemExit("no triggered setups in window. Try a longer cutoff window "
                         "or set PHOENIX_REVIEW_INCLUDE_MISSES=1 to include misses.")

    # Attach to running Chrome + force-navigate to a FRESH ADA chart URL
    # (don't reuse whatever the user had open -- saved layouts can keep
    # the view zoomed in such that only ~300 bars get loaded, which kills
    # the bar-range filter).
    print("==> attaching to Chrome on :9222...", flush=True)
    driver = attach_chrome()
    print(f"  current URL: {driver.current_url[:80]}", flush=True)
    if "tradingview.com/chart" not in driver.current_url \
            or "ADAUSDT" not in driver.current_url.upper() \
            or "interval=15" not in driver.current_url:
        navigate_to_ada(driver)
    else:
        print("  already on ADA 15m chart; not re-navigating.")

    # Click TV's '3M' date-range tab to explicitly request 3 months of data.
    # On a fresh 15m chart that loads ~8640 bars; on saved layouts it forces
    # the zoom to span 3 months. Best primary path. Fall through to
    # requestMoreHistoryPoints() if the button is missing or click is ignored.
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        print("==> clicking TV's '3M' date-range tab...", flush=True)
        btn = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'button[data-name="date-range-tab-3M"]')
            )
        )
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(7)
        print("  clicked, slept 7s for history fetch.", flush=True)
    except Exception as exc:
        print(f"  3M click skipped: {type(exc).__name__}; relying on "
              f"requestMoreHistoryPoints fallback.", flush=True)

    # Fallback safety net: poke requestMoreHistoryPoints() until we have at
    # least NEED_BARS or TV stops paging in new data for 3 attempts.
    NEED_BARS = 90 * 24 * 4 + 200   # 3 months of 15m + safety margin
    print(f"==> ensuring TV has at least {NEED_BARS} bars loaded...", flush=True)
    last_n = -1
    for attempt in range(40):
        n = driver.execute_script(
            "const c=window._exposed_chartWidgetCollection;"
            "if(!c) return 0;"
            "return c._activeChartWidgetModel.value().model().mainSeries().data().size();"
        ) or 0
        if n >= NEED_BARS:
            print(f"  loaded {n} bars (target {NEED_BARS}), proceeding.")
            break
        if n == last_n and attempt > 5:
            print(f"  TV stopped loading new bars at {n} (3 attempts with no progress); "
                  f"proceeding with what we have.")
            break
        # Request more history. The method exists on the timeScale.
        driver.execute_script(
            "const c=window._exposed_chartWidgetCollection;"
            "if(c){const ts=c._activeChartWidgetModel.value().model().timeScale();"
            "if(ts.requestMoreHistoryPoints) ts.requestMoreHistoryPoints();}"
        )
        if attempt % 5 == 0:
            print(f"  attempt {attempt + 1}: {n} bars so far, requesting more...", flush=True)
        last_n = n
        time.sleep(1.0)
    else:
        print(f"  WARNING: gave up after 40 attempts; reviewing whatever's loaded.")

    # Now read TV's actual loaded bar range + filter setups to those that fit.
    print("==> reading TV's loaded bar range + filtering setups...", flush=True)
    bar_range = driver.execute_script(
        "const c=window._exposed_chartWidgetCollection;"
        "if(!c) return null;"
        "const d=c._activeChartWidgetModel.value().model().mainSeries().data();"
        "const f=d.first(), l=d.last();"
        "return {first: f && f.value[0], last: l && l.value[0], n: d.size()};"
    )
    if not (bar_range and bar_range.get("first") and bar_range.get("last")):
        raise SystemExit("could not read TV bar range -- is the chart loaded?")
    first_ep = int(bar_range["first"]); last_ep = int(bar_range["last"])
    print(f"  TV's loaded window: {datetime.fromtimestamp(first_ep, tz=timezone.utc).isoformat()} "
          f"-> {datetime.fromtimestamp(last_ep, tz=timezone.utc).isoformat()} "
          f"({bar_range['n']} bars)", flush=True)
    pad_secs = 15 * 60   # 15 minutes margin (was 60 min, but a single bar of pad is enough)
    kept = []
    for s in legs:
        try:
            p_ep = int(datetime.fromisoformat(s["parent_ts"]).replace(
                tzinfo=ZoneInfo("UTC")).timestamp())
            t_ep = int(datetime.fromisoformat(s["term_ts"]).replace(
                tzinfo=ZoneInfo("UTC")).timestamp())
        except Exception:
            continue
        if p_ep >= first_ep + pad_secs and t_ep <= last_ep:
            kept.append(s)
    if len(kept) < len(legs):
        print(f"  reviewing {len(kept)} of {len(legs)} setups that fit in TV's window.")
    if not kept:
        # Diagnose what slipped through. Show the oldest setup's timestamp vs
        # TV's earliest loaded bar to make the gap obvious.
        oldest = min(legs, key=lambda s: s["parent_ts"]) if legs else None
        if oldest:
            print(f"  oldest setup parent_ts: {oldest['parent_ts']}")
            print(f"  TV's earliest loaded:   "
                  f"{datetime.fromtimestamp(first_ep, tz=timezone.utc).isoformat()}")
        raise SystemExit(
            "no setups fall in TV's loaded bar range. Options:\n"
            "  1. Manually drag the TV chart left to load more bars, then re-run.\n"
            "  2. Click TV's 'All' tab in the bottom-left date-range bar.\n"
            "  3. Run on a shorter window: edit cutoff_dt in main() to (now - 14 days)."
        )
    setups = kept

    # Number them for the panel/object tree.
    for i, leg in enumerate(setups, start=1):
        leg["id"] = f"auto{i}"

    # Inject panel + reset action state
    print(f"==> injecting WSAD panel + starting review ({len(setups)} setups)...", flush=True)
    svc = DB1TradingViewSyncService()
    ctx = svc._detect_chart_time_context(driver)
    driver.execute_script(REMOVE_VOLUME_JS)
    inject_result = driver.execute_script(ADA_INJECT_PANEL_JS)
    print(f"  panel inject returned: {inject_result}", flush=True)
    driver.execute_script("window.__reviewSeq = 0; window.__reviewAction = null;")
    driver.execute_cdp_cmd("Page.bringToFront", {})

    verdicts = {}      # setup_index -> verdict string
    started_at = datetime.now(timezone.utc)

    def show(i, extra=""):
        leg = setups[i]
        # Single fib at a time. Clear THEN small pause so TV's renderer
        # actually flushes the removed drawing before we add a new one --
        # without the pause, fast successive show() calls can leave the
        # old fib briefly visible (the 'shows multiple sometime' bug).
        driver.execute_script(CLEAR_JS)
        time.sleep(0.05)
        place_one(driver, leg, f"auto{i+1} << REVIEWING >> {i+1}/{len(setups)}", ctx)
        time.sleep(0.25)
        driver.execute_script(REAPPLY_NAMES_JS)
        nav = navigate_to_fib(driver, leg)
        if not (isinstance(nav, dict) and nav.get("ok")):
            print(f"  navigate warning: {nav}", file=sys.stderr)
        # Update the floating panel's status text via the ADA-specific renderer
        # (BIG color-coded outcome + R, neutral gate-clear line).
        driver.execute_script(
            "window.__reviewStatus(arguments[0], arguments[1]);",
            f"ADA 15m Review  {i + 1}/{len(setups)}",
            _ada_info_html(i, len(setups), leg, extra,
                           verdict=verdicts.get(i)),
        )

    i = 0
    last_seq = 0
    show(i)
    # After every show() returns, drain any key presses that the user may have
    # made WHILE show() was running (CLEAR + place + sleep + nav = ~1s). Without
    # this, a stale press queued during one show fires as soon as we loop, causing
    # 'jump 2 instead of 1'. Sync last_seq to the current __reviewSeq so anything
    # that landed during the show is treated as already-seen.
    def _drain_stale():
        nonlocal last_seq
        cur = driver.execute_script("return window.__reviewSeq || 0;")
        try:
            last_seq = int(cur) if cur is not None else last_seq
        except (TypeError, ValueError):
            pass
        driver.execute_script("window.__reviewAction = null;")

    _drain_stale()
    print("==> Panel ready. Press W/S/A/D/Enter in the TV chart window.", flush=True)
    print("    Verdicts append to data/discovery_bet_1/human_labels.jsonl.", flush=True)
    print("    Ctrl-C here to end early (still writes a session report).", flush=True)

    try:
        while True:
            action = driver.execute_script("return window.__reviewAction;")
            seq = action.get("seq", 0) if isinstance(action, dict) else 0
            if seq <= last_seq:
                time.sleep(0.15)   # tighter poll, less perceived latency
                continue
            last_seq = seq
            act = action.get("action") if isinstance(action, dict) else None
            if act == "done":
                break
            elif act == "next":
                if i + 1 < len(setups):
                    i += 1; show(i)
                else:
                    show(i, extra="<i>(at last setup)</i>")
                _drain_stale()
            elif act == "back":
                if i > 0:
                    i -= 1; show(i)
                else:
                    show(i, extra="<i>(at first setup)</i>")
                _drain_stale()
            elif act in ("accept", "wrong_setup",
                         "expected_tp1", "expected_tp2", "expected_tp3",
                         "expected_loss", "expected_miss"):
                leg = setups[i]
                expected_outcome = None
                wrong_kind = None
                if act == "accept":
                    verdict = VERDICT_ACCEPT          # W: all ok
                elif act == "wrong_setup":
                    # S then R: 'this isn't a real swing setup at all.'
                    # NOT VERDICT_ADJUST -- ADJUST requires corrected anchors
                    # (the user dragged the fib to a new place). R alone is
                    # just 'reject this setup', so VERDICT_REJECT is right.
                    verdict = VERDICT_REJECT
                    wrong_kind = "setup"
                else:                                  # S then F then 1/2/3/L/M
                    # Setup is fine but executor scored the wrong outcome.
                    verdict = VERDICT_REJECT
                    wrong_kind = "outcome"
                    expected_outcome = {
                        "expected_tp1":  "TP1",
                        "expected_tp2":  "TP2",
                        "expected_tp3":  "TP3",
                        "expected_loss": "LOSS",
                        "expected_miss": "MISSED",
                    }[act]
                detector_params = {
                    "source": "tv_review_ada_15m",
                    "asset": "ADA",
                    "interval": "15m",
                    "min_bars": MIN_BARS,
                    "mult": ATR_MULT,
                    "scored_outcome": leg.get("outcome_kind"),
                    "scored_R": leg.get("outcome_r"),
                }
                if wrong_kind is not None:
                    detector_params["wrong_kind"] = wrong_kind
                if expected_outcome is not None:
                    detector_params["expected_outcome"] = expected_outcome
                label = make_label({
                    "parent_ts": leg["parent_ts"], "term_ts": leg["term_ts"],
                    "direction": leg["direction"],
                    "parent_price": float(leg["parent_price"]),
                    "term_price": float(leg["term_price"]),
                }, verdict, detector_params=detector_params)
                append_label(label, path=LABELS_PATH)
                # Track a richer verdict tag for the session report so R vs F
                # are distinguishable (both write VERDICT_REJECT to the labels
                # file, differentiated only by detector_params.wrong_kind).
                if wrong_kind == "setup":
                    verdicts[i] = "setup_wrong"
                elif wrong_kind == "outcome":
                    verdicts[i] = f"outcome_wrong:{expected_outcome}"
                else:
                    verdicts[i] = verdict
                # Auto-advance to next on a verdict, then drop any stale presses
                # the user made WHILE show()'s ~1s render was running. Without
                # this drain, a queued press fires immediately for the new setup
                # -> the 'jump 2 instead of 1' bug.
                if i + 1 < len(setups):
                    i += 1; show(i)
                else:
                    show(i, extra=f"<i>recorded: {verdict}. last setup.</i>")
                _drain_stale()
    except KeyboardInterrupt:
        print("\n==> Ctrl-C received -- writing session report...")
    finally:
        ended_at = datetime.now(timezone.utc)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = ended_at.strftime("%Y%m%dT%H%M%S")
        report_path = OUT_DIR / f"SESSION_{ts}.md"
        write_session_report(setups, verdicts, started_at, ended_at, report_path)
        print(f"==> session report: {report_path}")
        print(f"==> labels appended to: {LABELS_PATH}")
        # Best-effort: clear the review panel and leave the chart usable.
        try:
            driver.execute_script(
                "const p=document.getElementById('db1rv-panel');"
                "if(p) p.remove();"
                "if(window.__reviewKeyHandler){"
                "  document.removeEventListener('keydown', window.__reviewKeyHandler, true);"
                "  window.__reviewKeyHandler = null; }"
            )
            driver.execute_script(CLEAR_JS)
        except Exception:
            pass


if __name__ == "__main__":
    main()
