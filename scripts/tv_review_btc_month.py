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
import json
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
from scripts.execute_fib_strategy import REGIMES, build_subbar_index
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

# --- BTC 1H config ---
SYMBOL = "BINANCE:BTCUSDT"
TV_INTERVAL = "60"   # 1H
CHART_URL = f"https://www.tradingview.com/chart/?symbol={SYMBOL.replace(':', '%3A')}&interval={TV_INTERVAL}"
CSV_PATH = REPO_ROOT / "data/discovery_bet_1/binance_btcusdt_1h_full_history.csv"
# Detector gates -- MINIMUMS (a 2.0x run includes every deeper leg too). Set
# from the CLI in main(); module-level defaults kept for importers.
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
    'position:fixed; inset:0; z-index:2147483646;' +
    'background:rgba(10,13,18,0.88); backdrop-filter:blur(2px);' +
    'display:flex; flex-direction:column; align-items:center;' +
    'justify-content:center; color:#e6edf3;' +
    'font:15px -apple-system,Segoe UI,sans-serif;'
);
div.innerHTML =
  '<style>@keyframes db1spin{to{transform:rotate(360deg)}}</style>' +
  '<div style="width:44px;height:44px;border:4px solid #30363d;' +
      'border-top-color:#2962ff;border-radius:50%;' +
      'animation:db1spin 0.9s linear infinite;margin-bottom:22px"></div>' +
  '<div style="font-size:19px;font-weight:700;margin-bottom:8px">' +
      'Phoenix Review — preparing your session</div>' +
  '<div id="db1rv-loading-text" style="font-size:15px;color:#f0b90b;' +
      'margin-bottom:14px"></div>' +
  '<div style="font-size:13px;color:#8b949e;max-width:460px;text-align:center;' +
      'line-height:1.5">Nothing is broken — startup and self-recovery take ' +
      '30–90 seconds. The review panel appears in the top-left when ready.</div>';
document.getElementById('db1rv-loading-text').textContent =
    arguments[0] || 'Initializing...';
(document.body || document.documentElement).appendChild(div);
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

# Keep the chart locked to BINANCE:BTCUSDT during a review WITHOUT hiding the
# watchlist (the user wants the asset list visible + usable). The drift path we
# still block is the accidental one: typing a letter while the chart has focus
# opens TV's "symbol search" popup and switches the chart. A capture-phase
# keydown swallows stray printable chars so that popup never opens. Panel keys
# (W/S/A/D/R/F/1/2/3/L/M/arrows/Enter/Esc) pass through to the panel handler;
# anything typed into a real input (incl. the watchlist search box) passes too.
#
# We intentionally do NOT hide the watchlist anymore. Clicking a watchlist
# symbol will still switch the chart -- if that happens, click BTCUSDT back and
# press A then D. (Earlier we hid it via CSS; that greyed-out the asset list,
# which the user did not want.)
#
# Belt-and-suspenders: also remove any leftover hide-CSS from an older build so
# a stale session doesn't keep the watchlist greyed after this update.
SYMBOL_LOCK_JS = r"""
try {
  var old = document.getElementById('db1rv-symlock-css');
  if (old) old.remove();
} catch (e) {}
if (window.__symLockHandler) {
  document.removeEventListener('keydown', window.__symLockHandler, true);
}
var __panelKeys = ['w','s','a','d','r','f','m','l','1','2','3',
                   'arrowup','arrowdown','arrowleft','arrowright','enter','escape'];
window.__symLockHandler = function(e){
  var t = e.target;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
  var k = (e.key || '').toLowerCase();
  // Block any single printable char that isn't a panel key -- those are what
  // open TV's symbol-search popup. Modifiers / function keys (length > 1) pass.
  if (__panelKeys.indexOf(k) === -1 && (e.key || '').length === 1) {
    e.preventDefault();
    e.stopImmediatePropagation();
  }
};
document.addEventListener('keydown', window.__symLockHandler, true);

// --- Ad-blocker-nag watchdog -------------------------------------------
// TradingView intermittently throws a full-page 'Ad blocker detected'
// modal (the user's network blocks ads, e.g. VPN NetShield). It swallows
// every click, freezes feature loading (the lazy fib-module wedge!), and
// reappears on each page load -- so it must be killed continuously, not
// once. Scan every 2s; text-match so nothing legitimate gets removed.
function __killAdNag(doc) {
  let killed = 0;
  try {
    const root = doc.getElementById('overlap-manager-root');
    const pools = [];
    if (root) pools.push(...Array.from(root.children));
    pools.push(...Array.from(doc.querySelectorAll('div[data-dialog-name]')));
    for (const el of pools) {
      const txt = el.textContent || '';
      if (/ad.?blocker|allow ads|ad-supported|go ad-free/i.test(txt)) {
        el.remove(); killed++;
      }
    }
    if (killed) { doc.body.style.overflow = ''; }
  } catch (e) {}
  return killed;
}
if (window.__adNagKiller) { clearInterval(window.__adNagKiller); }
window.__adNagKiller = setInterval(function () {
  let n = __killAdNag(document);
  for (const f of Array.from(document.querySelectorAll('iframe'))) {
    try { if (f.contentDocument) n += __killAdNag(f.contentDocument); } catch (e) {}
  }
  if (n) console.log('db1rv: removed ad-blocker nag overlay x' + n);
}, 2000);

return {ok:true, watchlist_visible: true, keylock: true, adnag_watchdog: true};
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
    print(f"  navigating to {CHART_URL}", flush=True)
    driver.get(CHART_URL)
    # POLL for readiness instead of sleeping a fixed 15s. Exit as soon as TV's
    # chart API is exposed AND the main series has bars -- usually ~3-5s, not
    # 15. Cap at 15s so a slow load still proceeds.
    ready_js = (
        "const c=window._exposed_chartWidgetCollection;"
        "if(!c) return 0;"
        "try{return c._activeChartWidgetModel.value().model()"
        ".mainSeries().data().size();}catch(e){return 0;}"
    )
    for waited in range(1, 31):  # up to ~15s (0.5s steps)
        time.sleep(0.5)
        try:
            n = driver.execute_script(ready_js) or 0
        except Exception:
            n = 0
        if waited % 2 == 0:
            _loading(driver, f"Loading TradingView chart... ({n} bars)")
        if n >= 50:  # chart is up with real bars -- stop waiting
            print(f"  chart ready after ~{waited * 0.5:.0f}s ({n} bars).", flush=True)
            return
    print("  chart load hit 15s cap; proceeding.", flush=True)


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
        print(f"  place failed (tz={tz}): {result}", flush=True)
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


def load_prior_verdicts(setups: list, labels_path: Path, config: dict) -> dict:
    """Reload verdicts already given for these setups so a relaunch resumes
    instead of starting blank.

    human_labels.jsonl persists every verdict keyed by setup_key
    (`parent_ts|term_ts`), latest-wins. We map each current setup's index to
    its most recent stored verdict, in the SAME display form the live loop
    uses (VERDICT_ACCEPT / 'setup_wrong' / 'outcome_wrong:TPx'). Only BTC 1h
    labels are considered, so ADA/other-asset labels can't bleed in.

    `config` = {min_bars, mult, entry, exit_plan}: only verdicts recorded
    under the SAME trade config count as prior review -- the same swing leg
    scored under a different entry level or exit plan is a different claim,
    and its verdict must not pre-fill this session. Labels written before
    these fields existed default to the values they were reviewed under
    (entry 941, exit plan runner).

    Returns {setup_index: display_verdict}.
    """
    if not labels_path.exists():
        return {}
    latest: dict[str, dict] = {}
    for line in labels_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        dp = rec.get("detector_params", {}) or {}
        if dp.get("asset") != "BTC" or dp.get("interval") != "1h":
            continue
        if dp.get("min_bars") != config["min_bars"] or dp.get("mult") != config["mult"]:
            continue
        if str(dp.get("entry", "941")) != str(config["entry"]):
            continue
        if dp.get("exit_plan", "runner") != config["exit_plan"]:
            continue
        key = rec.get("setup_key") or f"{rec.get('parent_ts')}|{rec.get('term_ts')}"
        latest[key] = rec  # later lines overwrite -> latest wins
    out: dict[int, str] = {}
    for idx, leg in enumerate(setups):
        rec = latest.get(f"{leg['parent_ts']}|{leg['term_ts']}")
        if not rec:
            continue
        dp = rec.get("detector_params", {}) or {}
        if rec.get("verdict") == VERDICT_ACCEPT:
            out[idx] = VERDICT_ACCEPT
        elif dp.get("wrong_kind") == "setup":
            out[idx] = "setup_wrong"
        elif dp.get("wrong_kind") == "outcome":
            out[idx] = f"outcome_wrong:{dp.get('expected_outcome', '?')}"
        else:
            out[idx] = rec.get("verdict", VERDICT_REJECT)
    return out


def rewrite_btc_session_report(path: Path, *, month_label: str, window_tag: str,
                               exit_plan: str) -> None:
    """The shared markdown writer is ADA-specific; normalize BTC metadata."""
    text = path.read_text(encoding="utf-8")
    text = text.replace("# ADA 15m manual review session",
                        "# BTC 1H manual review session", 1)
    text = text.replace("- **Symbol:**  BINANCE:ADAUSDT @ 15m",
                        "- **Symbol:**  BINANCE:BTCUSDT @ 1H", 1)
    text = re.sub(
        r"- \*\*Detector:\*\* .+",
        f"- **Detector:** {MIN_BARS}c / {ATR_MULT:g}x ATR",
        text,
        count=1,
    )
    text = text.replace("- **Window:**  last 3 months",
                        f"- **Window:**  {month_label} ({window_tag}, {exit_plan})", 1)
    text = text.replace(
        "- Each verdict tagged `asset=ADA`. Filter with `jq 'select(.asset==\"ADA\")'`.",
        "- Each verdict tagged `detector_params.asset=BTC`. "
        "Filter with `jq 'select(.detector_params.asset==\"BTC\")'`.",
        1,
    )
    path.write_text(text, encoding="utf-8")


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
    global MIN_BARS, ATR_MULT
    ap = argparse.ArgumentParser()
    win = ap.add_mutually_exclusive_group(required=True)
    win.add_argument("--month", help="YYYY-MM, e.g. 2026-05")
    win.add_argument("--last-days", type=int,
                     help="trailing window in days (e.g. 92 for ~3 months)")
    ap.add_argument("--exit-plan", choices=["runner", "rest50"], default="runner",
                    help="runner = TP1 25%%/TP2 60%%/TP3 15%% at 0.0 (default); "
                         "rest50 = TP1 25%% (SL->entry), remaining 75%% "
                         "all out at 0.5, no runner")
    ap.add_argument("--entry", choices=["941", "882", "786"], default="941",
                    help="entry fib level (regime from execute_fib_strategy."
                         "REGIMES: TP1/SL-drag at the next-shallower level, "
                         "TP2 0.5, TP3 0.0; SL 1.05 fixed)")
    ap.add_argument("--fresh", action="store_true",
                    help="start blank: ignore verdicts already recorded for "
                         "this config (deliberate blind re-grade). NOTE: also "
                         "disables crash-resume -- a mid-session relaunch "
                         "starts over.")
    ap.add_argument("--min-bars", type=int, default=6,
                    help="detector minimum bars per leg (default 6)")
    ap.add_argument("--mult", type=float, default=2.0,
                    help="detector MINIMUM ATR multiple (default 2.0; deeper "
                         "legs always qualify)")
    args = ap.parse_args()
    MIN_BARS, ATR_MULT = args.min_bars, args.mult
    _rf.DETECTOR_PARAMS["min_bars"] = MIN_BARS
    _rf.DETECTOR_PARAMS["atr_mult"] = ATR_MULT
    config_tag = f"{MIN_BARS}c/{ATR_MULT:g}x e{args.entry}"
    regime = next(r for r in REGIMES if r["slug"] == f"x{args.entry}")
    exec_kwargs = dict(regime["params"])
    if args.exit_plan == "rest50":
        exec_kwargs.update({"p1": 0.25, "p2": 0.75, "p3": 0.0})
        config_tag += " rest50"
    if args.month:
        month_label, cutoff_start, cutoff_end = parse_month(args.month)
        window_tag = args.month
    else:
        # trailing window off the CSV's last bar; label doubles as month tag
        _last = load_csv(CSV_PATH)[-1].source_timestamp
        _lo = (datetime.fromisoformat(_last)
               - __import__("datetime").timedelta(days=args.last_days))
        cutoff_start, cutoff_end = _lo.isoformat(), _last
        month_label = f"last {args.last_days}d"
        window_tag = f"last{args.last_days}d"

    if not CSV_PATH.exists():
        raise SystemExit(f"missing {CSV_PATH}; run acquire_long_asset BTCUSDT 1h first.")

    print(f"==> loading {CSV_PATH.name}...", flush=True)
    candles = load_csv(CSV_PATH)
    idx_map = {c.source_timestamp: i for i, c in enumerate(candles)}
    atr = calculate_atr14(candles)
    pivots = detect_local_pivots(candles)

    print(f"==> {month_label} @ {config_tag}: filtering setups with parent_ts in "
          f"[{cutoff_start}, {cutoff_end}]", flush=True)

    legs = [l for l in _clean_legs(candles, atr, pivots,
                                   min_bars=MIN_BARS, mult=ATR_MULT)
            if l["term_ts"] in idx_map
            and l["parent_ts"] >= cutoff_start
            and l["parent_ts"] <= cutoff_end]
    print(f"==> {len(legs)} clean legs in {month_label}")

    # Sub-bars resolve intra-1H event order (which of SL/TP was hit first) from
    # data instead of conservative guessing; finest available granularity wins.
    # Optional: without any sub-bar file the outcomes fall back to 1H ties.
    subbars = None
    for grain in ("5m", "15m"):
        p = REPO_ROOT / f"data/discovery_bet_1/binance_btcusdt_{grain}_full_history.csv"
        if p.exists():
            subbars = build_subbar_index(load_csv(p))
            print(f"==> {grain} sub-bars loaded for intra-bar outcome resolution "
                  f"({len(subbars)} hours).", flush=True)
            break
    if subbars is None:
        print("==> WARN: no sub-bar CSV; outcomes use conservative 1H tie-breaks. "
              "Run: scripts/acquire_long_asset.py BTCUSDT 5m", flush=True)

    for leg in legs:
        _annotate_span_depth(leg, idx_map, atr)
        _annotate_outcome(leg, candles, idx_map, subbars=subbars, exec_kwargs=exec_kwargs)

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
    _loading(driver, "Connected. Checking the chart...")
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

    # Page history back only until the requested MONTH is covered, then stop.
    # Stopping on "first loaded bar <= a few days before month start" (instead
    # of a blind 1000-bar target) makes this exit as soon as we actually have
    # what we need -- the single biggest time saver after skipping the refresh.
    month_start_ep = int(datetime.fromisoformat(cutoff_start).replace(
        tzinfo=ZoneInfo("UTC")).timestamp())
    need_back_to = month_start_ep - 3 * 24 * 3600  # 3-day margin before month
    FIRST_BAR_JS = (
        "const c=window._exposed_chartWidgetCollection;"
        "if(!c) return [0,0];"
        "try{const d=c._activeChartWidgetModel.value().model().mainSeries().data();"
        "const f=d.first(); return [d.size(), (f&&f.value[0])||0];}catch(e){return [0,0];}"
    )
    def page_in_history():
        """Page TV's lazy history back until the month is covered. Called once
        at startup AND again whenever TV silently EVICTS old bars mid-session
        (it does -- the series resets to ~recent bars and every placement
        starts failing with 'anchor bar not found')."""
        last_n = -1
        stagnant_streak = 0
        for attempt in range(25):
            res = driver.execute_script(FIRST_BAR_JS) or [0, 0]
            n = int(res[0] or 0)
            first_ep = int(res[1] or 0)
            if first_ep and first_ep <= need_back_to:
                print(f"  history covers {month_label} ({n} bars, first "
                      f"{datetime.fromtimestamp(first_ep, tz=timezone.utc).date()}), "
                      f"proceeding.", flush=True)
                return True
            if n == last_n:
                stagnant_streak += 1
                if stagnant_streak >= 8:
                    print(f"  TV stopped paging at {n} bars; proceeding.")
                    return False
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
            _loading(driver, f"Paging TV history: {n} bars (attempt {attempt + 1}/25)...")
            last_n = n
            time.sleep(1.0)
        return False

    print(f"==> paging TV history until {month_label} is covered...", flush=True)
    _loading(driver, f"Paging TV history to cover {month_label}...")
    page_in_history()

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
    # Lock the chart to BTC: hide watchlist + swallow stray keys so the symbol
    # can't drift onto GOLD/Bitget mid-review (which silently breaks anchors).
    try:
        lock = driver.execute_script(SYMBOL_LOCK_JS)
        print(f"  symbol-lock: {lock}", flush=True)
    except Exception as exc:
        print(f"  symbol-lock warning: {exc}", file=sys.stderr)
    # Customize the panel title for BTC's month.
    driver.execute_script(
        "const t=document.getElementById('db1rv-title');"
        "if(t) t.textContent = arguments[0];",
        f"BTC 1H Review -- {month_label} ({config_tag})"
    )
    driver.execute_script("window.__reviewSeq = 0; window.__reviewAction = null;")
    driver.execute_cdp_cmd("Page.bringToFront", {})

    # Reload verdicts already given for these setups (persisted in
    # human_labels.jsonl, latest-wins) so a relaunch after a bug fix doesn't
    # make the user re-grade everything from scratch. Only verdicts for THIS
    # config (min-bars/mult/entry/exit-plan) count; --fresh skips even those.
    if args.fresh:
        verdicts = {}
        print(f"==> --fresh: starting blank; all {len(setups)} setups "
              f"unreviewed this session.", flush=True)
    else:
        verdicts = load_prior_verdicts(setups, LABELS_PATH, {
            "min_bars": MIN_BARS, "mult": ATR_MULT,
            "entry": args.entry, "exit_plan": args.exit_plan,
        })
        if verdicts:
            print(f"==> resumed {len(verdicts)} prior verdicts from "
                  f"{LABELS_PATH.name} (same config only); "
                  f"{len(setups) - len(verdicts)} setups "
                  f"still unreviewed.", flush=True)
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

    def _place_with_retry(leg, name, tries=10, delay=1.5):
        """TradingView lazy-loads the Fib line-tool module; on a freshly loaded
        chart the first createLineTool can throw 'LineToolFibRetracement is not
        loaded'. Retry until TV fetches the chunk instead of crashing the whole
        review session."""
        for t in range(tries):
            try:
                if place_one(driver, leg, name, ctx):
                    return True
            except WebDriverException as exc:
                if "not loaded" not in str(exc):
                    raise
                if t == 0:
                    print("  TV fib tool module not loaded yet; retrying...",
                          flush=True)
                # Pre-warm: TV's own hotkey Alt+F selects the Fib Retracement
                # tool -- the REAL human code path, which forces the lazy
                # module to load. (createLineTool alone never triggers the
                # fetch, and the internal selectLineTool APIs proved absent.)
                # Escape afterwards so the user isn't left in drawing mode.
                try:
                    from selenium.webdriver.common.action_chains import ActionChains
                    from selenium.webdriver.common.keys import Keys
                    ActionChains(driver).key_down(Keys.ALT).send_keys("f") \
                        .key_up(Keys.ALT).perform()
                    time.sleep(1.2)
                    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                except WebDriverException:
                    pass
            time.sleep(delay)
        return False

    def reinit_chart(reason):
        """Last-resort recovery: a FULL page reload + re-init. Cures every
        known wedge (lazy fib-module assertion that retries can't fix, evicted
        history that re-paging can't fix, broken panel DOM) at the cost of
        ~30s. The python-side review state (setups, index, verdicts) survives;
        only the browser side is rebuilt."""
        nonlocal last_seq
        print(f"==> chart wedged ({reason}); full page reload + re-init...",
              flush=True)
        navigate_to_btc(driver)
        try:
            driver.execute_script(REMOVE_VOLUME_JS)
        except Exception:
            pass
        page_in_history()
        inject = driver.execute_script(ADA_INJECT_PANEL_JS)
        driver.execute_script(
            "const t=document.getElementById('db1rv-title');"
            "if(t) t.textContent = arguments[0];",
            f"BTC 1H Review -- {month_label} ({config_tag})"
        )
        driver.execute_script("window.__reviewSeq = 0; window.__reviewAction = null;")
        last_seq = 0
        try:
            driver.execute_script(SYMBOL_LOCK_JS)
            driver.execute_script(REMOVE_LOADING_JS)
        except Exception:
            pass
        print(f"  reinit done: {inject}", flush=True)

    def show(i, extra=""):
        leg = setups[i]
        # INSTANT acknowledgment: flip the panel to 'loading' the moment the
        # action is consumed, BEFORE the (possibly slow) place/zoom work. A
        # keypress that produces no visible change within ~200ms reads as
        # 'broken' even when the machinery behind it is grinding correctly.
        try:
            driver.execute_script(
                "window.__reviewStatus(arguments[0], arguments[1]);",
                f"BTC 1H {month_label} {config_tag}  {i + 1}/{len(setups)}",
                "<b style='color:#f0b90b'>... loading setup, give me a few "
                "seconds (auto-recovery can take ~1 min)</b>")
        except Exception:
            pass
        if not _clear_and_wait(max_ms=1000):
            n_left = driver.execute_script(COUNT_LINETOOLS_JS) or 0
            print(f"  warn: chart still has {n_left} drawings after clear", file=sys.stderr)
        name = f"auto{i+1} << REVIEWING >> {i+1}/{len(setups)}"
        # Escalation ladder, each rung cures a different wedge:
        #   1. quick retry        (transient)
        #   2. re-page history    (TV evicted old bars)
        #   3. page reload+reinit (lazy-module assertion / broken page state)
        if not _place_with_retry(leg, name, tries=2, delay=1.0):
            print(f"  setup {i+1}: placement failing; re-paging history...",
                  flush=True)
            page_in_history()
            if not _place_with_retry(leg, name, tries=3, delay=1.0):
                reinit_chart(f"setup {i+1} placement still failing after re-page")
                if not _place_with_retry(leg, name, tries=6, delay=1.5):
                    print(f"  warn: could not place fib for setup {i+1}",
                          file=sys.stderr)
        time.sleep(0.2)
        driver.execute_script(REAPPLY_NAMES_JS)
        # Zoom to the setup. TV's fib-creation triggers an async re-render that
        # can RESET the view AFTER our first zoom lands -- so we zoom, let the
        # re-render settle, then zoom AGAIN. The second zoom sticks. Every nav
        # is logged to stdout (the readable /tmp log) so we can diagnose
        # without attaching selenium (which kills the shared browser).
        nav = navigate_to_fib(driver, leg)
        time.sleep(0.35)
        nav = navigate_to_fib(driver, leg)
        ok = isinstance(nav, dict) and nav.get("ok")
        landed = isinstance(nav, dict) and nav.get("landed")
        vis = nav.get("visible") if isinstance(nav, dict) else None
        print(f"  show {i+1}/{len(setups)} {leg['parent_ts'][:16]} "
              f"nav={nav.get('method') if isinstance(nav, dict) else nav} "
              f"landed={landed} visible={vis}", flush=True)
        if not ok:
            print(f"  navigate warning: {nav}", file=sys.stderr)
        driver.execute_script(
            "window.__reviewStatus(arguments[0], arguments[1]);",
            f"BTC 1H {month_label} {config_tag}  {i + 1}/{len(setups)}",
            _ada_info_html(i, len(setups), leg, extra,
                           verdict=verdicts.get(i),
                           min_bars=MIN_BARS, min_atr=ATR_MULT),
        )

    # Resume at the first unreviewed setup (verdicts reloaded above).
    i = 0
    while i in verdicts and i + 1 < len(setups):
        i += 1
    last_seq = 0
    show(i)

    # Initial HARD reset: discard any keypresses that piled up while the chart
    # was first loading/rendering, so the review starts clean at setup 1.
    cur = driver.execute_script("return window.__reviewSeq || 0;")
    try:
        last_seq = int(cur) if cur is not None else 0
    except (TypeError, ValueError):
        last_seq = 0
    driver.execute_script("window.__reviewAction = null;")

    def _drain_stale():
        # Clear ONLY the action we just processed; PRESERVE any newer action the
        # user submitted DURING show() (~1.5s of clear+place+double-zoom). The
        # old version jumped last_seq to the current global seq and nulled
        # unconditionally, which silently dropped a click/keypress made while the
        # chart was still rendering -- that was the "clicking outcome doesn't
        # advance" race. last_seq already equals the processed action's seq
        # (set in the loop), so this nulls the stale one and lets a fresher one
        # through on the next poll.
        driver.execute_script(
            "if (window.__reviewAction && (window.__reviewAction.seq||0) <= arguments[0])"
            " { window.__reviewAction = null; }", last_seq)
    print("==> Panel ready. Press W/S/A/D/Enter in the TV chart window.", flush=True)
    print("    Verdicts append to data/discovery_bet_1/human_labels.jsonl.", flush=True)

    consecutive_errors = 0
    try:
        while True:
            # Resilient poll: a transient WebDriverException (TV re-render,
            # momentary unresponsiveness) must NOT end the whole session.
            # Catch, log, back off, and retry. Only give up if the browser is
            # gone for many consecutive polls (genuinely closed/crashed).
            try:
                action = driver.execute_script("return window.__reviewAction;")
                consecutive_errors = 0
            except WebDriverException as exc:
                consecutive_errors += 1
                if consecutive_errors >= 40:  # ~20s of solid failure
                    print(f"\n==> browser unreachable for {consecutive_errors} "
                          f"polls; ending session. ({str(exc)[:80]})", flush=True)
                    globals()["_BROWSER_LOST"] = True
                    break
                time.sleep(0.5)
                continue
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
                    "month": window_tag,
                    "entry": args.entry,
                    "exit_plan": args.exit_plan,
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
        report_path = OUT_DIR / f"SESSION_BTC_{window_tag}_{MIN_BARS}c{ATR_MULT:g}x_e{args.entry}_{args.exit_plan}_{ts}.md"
        # Reuse the ADA markdown writer -- the schema is the same.
        from scripts.tv_review_ada_15m import write_session_report
        write_session_report(setups, verdicts, started_at, ended_at, report_path)
        rewrite_btc_session_report(
            report_path,
            month_label=month_label,
            window_tag=window_tag,
            exit_plan=args.exit_plan,
        )
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
    if globals().get("_BROWSER_LOST"):
        sys.exit(2)   # tells the supervisor wrapper to restart chrome + resume
