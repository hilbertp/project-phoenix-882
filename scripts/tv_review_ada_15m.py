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
              b('Outcome wrong (F)','wrong_outcome','#7a2f31',
                  'Anchors fine but executor scored the wrong outcome (VERDICT_REJECT)') + '</div>' +
    '<div style="margin-top:5px;font-size:10px;color:#9aa4b2">Esc to cancel</div>' +
  '</div>' +
  '<div style="font-size:10px;color:#6b7785;margin-top:8px;line-height:1.5">' +
    'keys: <b>W</b>=all ok &middot; <b>S</b>=wrong (then <b>R</b>=setup / <b>F</b>=outcome) &middot; ' +
    '<b>A</b>/<b>D</b>=prev/next &middot; <b>Enter</b>=done' +
  '</div>' +
  '<div id="db1rv-info" style="margin-top:7px;font-size:11px;color:#9aa4b2;line-height:1.4"></div>';
document.body.appendChild(p);
function __setWrongMode(on){
  document.getElementById('db1rv-main').style.display = on ? 'none' : 'block';
  document.getElementById('db1rv-wrong').style.display = on ? 'block' : 'none';
}
function __emit(act){
  __setWrongMode(false);
  window.__reviewSeq = (window.__reviewSeq || 0) + 1;
  window.__reviewAction = {seq: window.__reviewSeq, action: act};
}
function __handle(act){
  if (act === 'wrong')  { __setWrongMode(true); return; }
  if (act === 'cancel') { __setWrongMode(false); return; }
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
  var wrong = document.getElementById('db1rv-wrong').style.display === 'block';
  var k = (e.key || '').toLowerCase();
  var act = null;
  if (wrong) {
    if (k === 'r')        act = 'wrong_setup';
    else if (k === 'f')   act = 'wrong_outcome';
    else if (k === 'escape') { __setWrongMode(false); e.preventDefault(); e.stopPropagation(); return; }
    else if (k === 'a' || k === 'arrowleft')  { __setWrongMode(false); act = 'back'; }
    else if (k === 'd' || k === 'arrowright') { __setWrongMode(false); act = 'next'; }
    else if (k === 'enter') { __setWrongMode(false); act = 'done'; }
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
                                  "adjust": 0, "reject": 0, "skip": 0})
        if k in verdicts:
            by_cohort[c]["reviewed"] += 1
            v = verdicts[k]
            if v == VERDICT_ACCEPT: by_cohort[c]["accept"] += 1
            elif v == VERDICT_ADJUST: by_cohort[c]["adjust"] += 1
            elif v == VERDICT_REJECT: by_cohort[c]["reject"] += 1
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
        f"| accept (W)               | {verdict_counts.get(VERDICT_ACCEPT, 0)} | all ok |",
        f"| adjust (S → R)           | {verdict_counts.get(VERDICT_ADJUST, 0)} | setup wrong (anchors) |",
        f"| reject (S → F)           | {verdict_counts.get(VERDICT_REJECT, 0)} | outcome wrong (scoring) |",
        f"| (skipped — no verdict)   | {len(setups) - n} | not reviewed |",
        f"",
        f"## Per-cohort breakdown",
        f"",
        f"| Cohort (×ATR) | Total | Reviewed | Accept (W) | Setup-wrong (R) | Outcome-wrong (F) |",
        f"|---|---|---|---|---|---|",
    ]
    for cohort, c in sorted(by_cohort.items()):
        total = c["reviewed"] + c["skip"]
        lines.append(f"| {cohort} | {total} | {c['reviewed']} | {c['accept']} | {c['adjust']} | {c['reject']} |")
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

    # Attach to running Chrome + navigate to ADA chart.
    print("==> attaching to Chrome on :9222...", flush=True)
    driver = attach_chrome()
    if "tradingview.com/chart" not in driver.current_url \
            or "ADAUSDT" not in driver.current_url.upper():
        navigate_to_ada(driver)

    # Read TV's actual loaded bar range + filter setups to those that fit.
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
    pad_secs = 60 * 60   # 60 minutes of margin
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
        print(f"  TV loaded {bar_range['n']} bars; reviewing "
              f"{len(kept)} of {len(legs)} setups in that window.")
    if not kept:
        raise SystemExit("no setups fall in TV's loaded bar range -- scroll left in TV first.")
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
        # Single fib at a time -- match the BTC review's UX.
        driver.execute_script(CLEAR_JS)
        place_one(driver, leg, f"auto{i+1} << REVIEWING >> {i+1}/{len(setups)}", ctx)
        time.sleep(0.25)
        driver.execute_script(REAPPLY_NAMES_JS)
        nav = navigate_to_fib(driver, leg)
        if not (isinstance(nav, dict) and nav.get("ok")):
            print(f"  navigate warning: {nav}", file=sys.stderr)
        # Update the floating panel's status text
        driver.execute_script(
            "window.__reviewStatus(arguments[0], arguments[1]);",
            f"ADA 15m Review  {i + 1}/{len(setups)}",
            _info_html(i, len(setups), leg, extra,
                       verdict=verdicts.get(i)),
        )

    i = 0
    last_seq = 0
    show(i)
    print("==> Panel ready. Press W/S/A/D/Enter in the TV chart window.", flush=True)
    print("    Verdicts append to data/discovery_bet_1/human_labels.jsonl.", flush=True)
    print("    Ctrl-C here to end early (still writes a session report).", flush=True)

    try:
        while True:
            action = driver.execute_script("return window.__reviewAction;")
            seq = action.get("seq", 0) if isinstance(action, dict) else 0
            if seq <= last_seq:
                time.sleep(0.4)
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
            elif act == "back":
                if i > 0:
                    i -= 1; show(i)
                else:
                    show(i, extra="<i>(at first setup)</i>")
            elif act in ("accept", "wrong_setup", "wrong_outcome"):
                leg = setups[i]
                if act == "accept":
                    verdict = VERDICT_ACCEPT      # W: all ok
                elif act == "wrong_setup":
                    verdict = VERDICT_ADJUST      # S then R: anchors wrong
                else:                              # act == "wrong_outcome"
                    verdict = VERDICT_REJECT      # S then F: outcome scoring wrong
                label = make_label({
                    "parent_ts": leg["parent_ts"], "term_ts": leg["term_ts"],
                    "direction": leg["direction"],
                    "parent_price": float(leg["parent_price"]),
                    "term_price": float(leg["term_price"]),
                }, verdict, detector_params={
                    "source": "tv_review_ada_15m",
                    "asset": "ADA",
                    "interval": "15m",
                    "min_bars": MIN_BARS,
                    "mult": ATR_MULT,
                })
                append_label(label, path=LABELS_PATH)
                verdicts[i] = verdict
                # Auto-advance to next on a verdict
                if i + 1 < len(setups):
                    i += 1; show(i)
                else:
                    show(i, extra=f"<i>recorded: {verdict}. last setup.</i>")
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
