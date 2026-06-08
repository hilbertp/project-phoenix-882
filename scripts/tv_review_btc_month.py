#!/usr/bin/env python
"""WSAD-driven TradingView review of BTC 1H setups for one calendar month.

Same UX as tv_review_ada_15m.py but pointed at BINANCE:BTCUSDT @ 1H with
the (6c / 2.0x ATR) detector configured for the month-at-a-time workflow.

Usage:
  PYTHONPATH=. .venv/bin/python scripts/tv_review_btc_month.py --month 2026-05
  PYTHONPATH=. .venv/bin/python scripts/tv_review_btc_month.py --month 2026-06

Or via the wrapper:
  ./scripts/tv-btc-may.sh           # May 2026
  ./scripts/tv-btc.sh 2026-06       # any month

The CSV is re-acquired by the wrapper before each run so it always covers
the requested month. The script then walks setups whose parent_ts falls
inside that month, scores against the 0.941 entry, filters out misses,
injects the WSAD panel, and renders an end-of-session report on the chart.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
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
    VERDICT_REJECT,
    append_label,
    make_label,
)
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.swing_detector import clean_legs as _clean_legs
from apps.worker.discovery_bet_1.types import Candle
from apps.api.db1_review_tradingview.service import (
    DB1TradingViewSyncService,
    TradingViewMarketContract,
    TradingViewReviewStructure,
    TradingViewSyncRequest,
    _build_expected_line_tool_points,
)
from scripts.place_fibs_tradingview import (
    PLACE_FIB_JS,
    REMOVE_VOLUME_JS,
)
from scripts.review_fibs_tradingview import (
    NAVIGATE_TO_FIB_JS,
    REAPPLY_NAMES_JS,
    REPORT_OVERLAY_JS,
    _annotate_outcome,
    _annotate_span_depth,
)
import scripts.review_fibs_tradingview as _rf

# Reuse the ADA-flavored UI: the panel JS, info renderer, and report builder.
from scripts.tv_review_ada_15m import (
    ADA_INJECT_PANEL_JS,
    _ada_info_html,
    build_ada_report_html,
)

# Override detector params shown in the panel's gate-check line.
_rf.DETECTOR_PARAMS["min_bars"] = 6
_rf.DETECTOR_PARAMS["atr_mult"] = 2.0

# --- BTC 1H config ---
SYMBOL = "BINANCE:BTCUSDT"
TV_INTERVAL = "60"   # 1H
CHART_URL = f"https://www.tradingview.com/chart/?symbol={SYMBOL.replace(':', '%3A')}&interval={TV_INTERVAL}"
CSV_PATH = REPO_ROOT / "data/discovery_bet_1/binance_btcusdt_1h_full_history.csv"
MIN_BARS = 6
ATR_MULT = 2.0
DEBUG_PORT = 9222

OUT_DIR = REPO_ROOT / "artifacts/discovery_bet_1/manual_review_btc_1h_month"
LABELS_PATH = REPO_ROOT / "data/discovery_bet_1/human_labels.jsonl"


LOADING_OVERLAY_JS = r"""
const existing = document.getElementById('db1rv-loading');
if (existing) existing.remove();
const div = document.createElement('div');
div.id = 'db1rv-loading';
div.style.cssText = (
    'position:fixed; top:120px; right:6px; z-index:99999;' +
    'background:#0d1117; color:#e6edf3;' +
    'border:1px solid #30363d; border-radius:6px;' +
    'padding:10px 12px; font:13px -apple-system,Segoe UI,sans-serif;' +
    'width:260px; box-shadow:0 4px 12px rgba(0,0,0,0.5);'
);
const title = document.createElement('div');
title.style.cssText = 'font-weight:600; margin-bottom:4px; color:#7d8590;';
title.textContent = 'Phoenix Review (loading)';
const text = document.createElement('div');
text.id = 'db1rv-loading-text';
text.textContent = arguments[0] || 'Initializing...';
div.appendChild(title);
div.appendChild(text);
document.body.appendChild(div);
return true;
"""

UPDATE_LOADING_JS = r"""
const el = document.getElementById('db1rv-loading-text');
if (el) { el.textContent = arguments[0]; return true; }
return false;
"""

REMOVE_LOADING_JS = r"""
const el = document.getElementById('db1rv-loading');
if (el) el.remove();
return true;
"""


def _loading(driver, text: str) -> None:
    """Inject (or update) the on-chart loading badge. Silent on failure --
    the panel still works without it; this is purely UX feedback."""
    try:
        if not driver.execute_script(UPDATE_LOADING_JS, text):
            driver.execute_script(LOADING_OVERLAY_JS, text)
    except Exception:
        pass


def load_csv(path: Path) -> list[Candle]:
    out: list[Candle] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Candle(row["source_timestamp"], float(row["open"]),
                              float(row["high"]), float(row["low"]),
                              float(row["close"]), float(row["volume"])))
    return out


def attach_chrome():
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


def navigate_to_btc(driver):
    print(f"  navigating to {CHART_URL}")
    driver.get(CHART_URL)
    print("  waiting 15s for chart to load + render bars...", flush=True)
    # Wait in 1s increments so the loading badge can be injected as soon as
    # the document is ready, giving the user a visible heartbeat instead of
    # a blank 15s of empty TV canvas.
    for waited in range(1, 16):
        time.sleep(1)
        if waited >= 2:
            _loading(driver, f"Loading TradingView chart ({15 - waited}s left)...")


def _utc_iso(ts: str) -> str:
    if "+" in ts or ts.endswith("Z"):
        return ts
    return ts + "+00:00"


def _request_for(leg):
    return TradingViewSyncRequest(
        market_contract=TradingViewMarketContract(SYMBOL, "1H"),
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
    try:
        parent_epoch = int(datetime.fromisoformat(leg["parent_ts"]).replace(
            tzinfo=ZoneInfo("UTC")).timestamp())
        term_epoch = int(datetime.fromisoformat(leg["term_ts"]).replace(
            tzinfo=ZoneInfo("UTC")).timestamp())
        return driver.execute_script(NAVIGATE_TO_FIB_JS, parent_epoch, term_epoch)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def parse_month(s: str) -> tuple[str, str, str]:
    """Returns (label, cutoff_start_iso, cutoff_end_iso) for a YYYY-MM string."""
    m = re.match(r"^(\d{4})-(\d{2})$", s)
    if not m:
        raise SystemExit(f"--month must be YYYY-MM (e.g. 2026-05); got {s!r}")
    year, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12):
        raise SystemExit(f"month {month} out of range")
    last_day = calendar.monthrange(year, month)[1]
    start = f"{year:04d}-{month:02d}-01T00:00:00"
    end = f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59"
    label = datetime(year, month, 1).strftime("%B %Y")
    return label, start, end


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True, help="YYYY-MM, e.g. 2026-05")
    args = ap.parse_args()
    month_label, cutoff_start, cutoff_end = parse_month(args.month)

    if not CSV_PATH.exists():
        raise SystemExit(f"missing {CSV_PATH}; run acquire_long_asset BTCUSDT 1h first.")

    print(f"==> loading {CSV_PATH.name}...", flush=True)
    candles = load_csv(CSV_PATH)
    idx_map = {c.source_timestamp: i for i, c in enumerate(candles)}
    atr = calculate_atr14(candles)
    pivots = detect_local_pivots(candles)

    print(f"==> {month_label}: filtering setups with parent_ts in "
          f"[{cutoff_start}, {cutoff_end}]", flush=True)

    legs = [l for l in _clean_legs(candles, atr, pivots,
                                   min_bars=MIN_BARS, mult=ATR_MULT)
            if l["term_ts"] in idx_map
            and l["parent_ts"] >= cutoff_start
            and l["parent_ts"] <= cutoff_end]
    print(f"==> {len(legs)} clean legs in {month_label}")

    for leg in legs:
        _annotate_span_depth(leg, idx_map, atr)
        _annotate_outcome(leg, candles, idx_map)

    include_misses = os.environ.get("PHOENIX_REVIEW_INCLUDE_MISSES") in ("1", "true", "yes")
    if not include_misses:
        triggered = [l for l in legs if l.get("outcome_kind") != "miss"]
        n_missed = len(legs) - len(triggered)
        print(f"==> filtered out {n_missed} miss / shrug setups (0.941 never tagged). "
              f"{len(triggered)} triggered setups remain.")
        print(f"    set PHOENIX_REVIEW_INCLUDE_MISSES=1 to keep them.")
        legs = triggered

    if not legs:
        raise SystemExit(f"no triggered setups in {month_label}.")

    print("==> attaching to Chrome on :9222...", flush=True)
    driver = attach_chrome()
    print(f"  current URL: {driver.current_url[:80]}", flush=True)
    has_layout_id = "/chart/HrY4" in driver.current_url or \
                    bool(re.search(r"/chart/[A-Za-z0-9]{6,}/", driver.current_url))
    needs_nav = (
        "tradingview.com/chart" not in driver.current_url
        or "BTCUSDT" not in driver.current_url.upper()
        or "interval=60" not in driver.current_url
        or has_layout_id
    )
    if needs_nav:
        if has_layout_id:
            print("  saved-layout ID detected; navigating to clean chart to avoid "
                  "persisted-drawing overlap.")
        navigate_to_btc(driver)
    else:
        print("  already on clean BTC 1H chart; not re-navigating.")
        _loading(driver, "Chart already loaded. Paging in history...")

    # Page in enough history to cover the month (~720 bars + 200 margin)
    TARGET_BARS = 1000
    print(f"==> paging in TV history (target {TARGET_BARS} bars = ~6 weeks of 1H)...",
          flush=True)
    _loading(driver, f"Paging in TV history (target {TARGET_BARS} bars)...")
    last_n = -1
    stagnant_streak = 0
    n = 0
    for attempt in range(25):
        n = driver.execute_script(
            "const c=window._exposed_chartWidgetCollection;"
            "if(!c) return 0;"
            "return c._activeChartWidgetModel.value().model().mainSeries().data().size();"
        ) or 0
        if n >= TARGET_BARS:
            print(f"  loaded {n} bars (target {TARGET_BARS}), proceeding.")
            break
        if n == last_n:
            stagnant_streak += 1
            if stagnant_streak >= 8:
                print(f"  TV stopped paging at {n} bars; proceeding.")
                break
        else:
            stagnant_streak = 0
        driver.execute_script(
            "const c=window._exposed_chartWidgetCollection;"
            "if(c){const ts=c._activeChartWidgetModel.value().model().timeScale();"
            "if(ts.requestMoreHistoryPoints) ts.requestMoreHistoryPoints();"
            "if(ts.scrollToFirstBar) ts.scrollToFirstBar();}"
        )
        if attempt % 3 == 0:
            print(f"  attempt {attempt + 1:2}: {n} bars so far...", flush=True)
        _loading(driver,
                 f"Paging TV history: {n}/{TARGET_BARS} bars "
                 f"(attempt {attempt + 1}/25)...")
        last_n = n
        time.sleep(2.0)

    print("==> reading TV's loaded bar range + filtering setups...", flush=True)
    _loading(driver, "Reading TV bar range + filtering setups...")
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
    first_iso = datetime.fromtimestamp(first_ep, tz=timezone.utc).isoformat()
    last_iso = datetime.fromtimestamp(last_ep, tz=timezone.utc).isoformat()
    print(f"  TV's loaded window: {first_iso} -> {last_iso} "
          f"({bar_range['n']} bars)", flush=True)
    pad_secs = 15 * 60
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
    if not kept:
        raise SystemExit(
            f"TV's loaded window ({first_iso[:10]} -> {last_iso[:10]}) doesn't\n"
            f"cover {month_label}. Drag the chart leftward in TradingView to load\n"
            f"older bars, then re-run."
        )
    print(f"  reviewing {len(kept)} of {len(legs)} setups in {month_label}.")
    setups = kept

    for i, leg in enumerate(setups, start=1):
        leg["id"] = f"auto{i}"

    print(f"==> injecting WSAD panel + starting review ({len(setups)} setups)...", flush=True)
    _loading(driver, f"Injecting review panel for {len(setups)} setups...")
    svc = DB1TradingViewSyncService()
    ctx = svc._detect_chart_time_context(driver)
    driver.execute_script(REMOVE_VOLUME_JS)
    inject_result = driver.execute_script(ADA_INJECT_PANEL_JS)
    print(f"  panel inject returned: {inject_result}", flush=True)
    # Loading badge has done its job -- WSAD panel takes over the upper-right.
    try:
        driver.execute_script(REMOVE_LOADING_JS)
    except Exception:
        pass
    # Customize the panel title for BTC's month.
    driver.execute_script(
        "const t=document.getElementById('db1rv-title');"
        "if(t) t.textContent = arguments[0];",
        f"BTC 1H Review -- {month_label}"
    )
    driver.execute_script("window.__reviewSeq = 0; window.__reviewAction = null;")
    driver.execute_cdp_cmd("Page.bringToFront", {})

    verdicts = {}
    started_at = datetime.now(timezone.utc)

    REMOVE_ALL_LINETOOLS_JS = r"""
        const c = window._exposed_chartWidgetCollection;
        if (!c) return -1;
        const widget = c._activeChartWidgetModel.value();
        const model = widget.model();
        let removed = 0;
        const panes = (model.panes && model.panes()) || [];
        for (const pane of panes) {
            const sources = (pane.dataSources && pane.dataSources().slice()) || [];
            for (const src of sources) {
                try {
                    const name = (src && src.constructor && src.constructor.name) || '';
                    if (/LineTool|Fib|Retracement|Drawing/.test(name)) {
                        try { model.removeSource(src); removed++; } catch(e) {}
                    }
                } catch (e) {}
            }
        }
        try {
            const tools = (model.allLineTools && model.allLineTools().slice()) || [];
            for (const t of tools) {
                try { model.removeSource(t); removed++; } catch(e) {}
            }
        } catch (e) {}
        return removed;
    """
    COUNT_LINETOOLS_JS = r"""
        const c = window._exposed_chartWidgetCollection;
        if (!c) return -1;
        const model = c._activeChartWidgetModel.value().model();
        let count = 0;
        const panes = (model.panes && model.panes()) || [];
        for (const pane of panes) {
            const sources = (pane.dataSources && pane.dataSources()) || [];
            for (const src of sources) {
                try {
                    const name = (src && src.constructor && src.constructor.name) || '';
                    if (/LineTool|Fib|Retracement|Drawing/.test(name)) count++;
                } catch (e) {}
            }
        }
        return count;
    """

    def _clear_and_wait(max_ms=1000):
        driver.execute_script(REMOVE_ALL_LINETOOLS_JS)
        deadline = time.time() + max_ms / 1000
        while time.time() < deadline:
            n = driver.execute_script(COUNT_LINETOOLS_JS) or 0
            if n <= 0:
                return True
            driver.execute_script(REMOVE_ALL_LINETOOLS_JS)
            time.sleep(0.04)
        return False

    def show(i, extra=""):
        leg = setups[i]
        if not _clear_and_wait(max_ms=1000):
            n_left = driver.execute_script(COUNT_LINETOOLS_JS) or 0
            print(f"  warn: chart still has {n_left} drawings after clear", file=sys.stderr)
        place_one(driver, leg, f"auto{i+1} << REVIEWING >> {i+1}/{len(setups)}", ctx)
        time.sleep(0.2)
        driver.execute_script(REAPPLY_NAMES_JS)
        nav = navigate_to_fib(driver, leg)
        if not (isinstance(nav, dict) and nav.get("ok")):
            print(f"  navigate warning: {nav}", file=sys.stderr)
        driver.execute_script(
            "window.__reviewStatus(arguments[0], arguments[1]);",
            f"BTC 1H {month_label}  {i + 1}/{len(setups)}",
            _ada_info_html(i, len(setups), leg, extra,
                           verdict=verdicts.get(i)),
        )

    i = 0
    last_seq = 0
    show(i)

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

    try:
        while True:
            action = driver.execute_script("return window.__reviewAction;")
            seq = action.get("seq", 0) if isinstance(action, dict) else 0
            if seq <= last_seq:
                time.sleep(0.15)
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
                    verdict = VERDICT_ACCEPT
                elif act == "wrong_setup":
                    verdict = VERDICT_REJECT
                    wrong_kind = "setup"
                else:
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
                    "source": "tv_review_btc_month",
                    "asset": "BTC",
                    "interval": "1h",
                    "min_bars": MIN_BARS,
                    "mult": ATR_MULT,
                    "month": args.month,
                    "scored_outcome": leg.get("outcome_kind"),
                    "scored_R": leg.get("outcome_r"),
                }
                if wrong_kind:
                    detector_params["wrong_kind"] = wrong_kind
                if expected_outcome:
                    detector_params["expected_outcome"] = expected_outcome
                label = make_label({
                    "parent_ts": leg["parent_ts"], "term_ts": leg["term_ts"],
                    "direction": leg["direction"],
                    "parent_price": float(leg["parent_price"]),
                    "term_price": float(leg["term_price"]),
                }, verdict, detector_params=detector_params)
                append_label(label, path=LABELS_PATH)
                if wrong_kind == "setup":
                    verdicts[i] = "setup_wrong"
                elif wrong_kind == "outcome":
                    verdicts[i] = f"outcome_wrong:{expected_outcome}"
                else:
                    verdicts[i] = verdict
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
        report_path = OUT_DIR / f"SESSION_BTC_{args.month}_{ts}.md"
        # Reuse the ADA markdown writer -- the schema is the same.
        from scripts.tv_review_ada_15m import write_session_report
        write_session_report(setups, verdicts, started_at, ended_at, report_path)
        print(f"==> session report (markdown): {report_path}")
        print(f"==> labels appended to: {LABELS_PATH}")
        try:
            report_html = build_ada_report_html(setups, verdicts, started_at, ended_at)
            # Tweak the title to say BTC instead of ADA.
            report_html = report_html.replace(
                "ADA 15m Review", f"BTC 1H Review &mdash; {month_label}", 1)
            report_html = report_html.replace(
                "BINANCE:ADAUSDT @ 15m", "BINANCE:BTCUSDT @ 1H", 1)
            driver.execute_script(REPORT_OVERLAY_JS, report_html)
            print(f"==> report overlay rendered on TV chart.")
        except Exception as exc:
            print(f"  warn: report overlay failed: {exc}", file=sys.stderr)
        try:
            driver.execute_script(
                "const p=document.getElementById('db1rv-panel');"
                "if(p) p.remove();"
                "if(window.__reviewKeyHandler){"
                "  document.removeEventListener('keydown', window.__reviewKeyHandler, true);"
                "  window.__reviewKeyHandler = null; }"
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
