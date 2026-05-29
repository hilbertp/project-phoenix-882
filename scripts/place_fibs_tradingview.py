#!/usr/bin/env python
"""Place clean DB1 swing setups as real native TradingView Fib Retracement objects.

A CLEAN leg (the user's rule): from a start fractal to the opposite extreme with
NO higher high than the terminal and NO lower low than the parent in between --
i.e. the start is the segment's extreme and the end is the opposite extreme, with
nothing breaching either bound between them. Gated by min-bars and ATR multiple.

Each setup becomes a separate LineToolFibRetracement in the Object Tree.

Usage:
  python scripts/place_fibs_tradingview.py dry [N]   # print legs, no browser
  python scripts/place_fibs_tradingview.py login     # open window for manual login
  python scripts/place_fibs_tradingview.py [N]       # place N (default 12)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from apps.api.db1_review_tradingview.service import (
    DB1TradingViewSyncService,
    TradingViewMarketContract,
    TradingViewReviewStructure,
    TradingViewSyncRequest,
    _build_expected_line_tool_points,
)
from apps.api.db1_s2_leg_read.service import _compress_to_alternating_pivots
from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from apps.worker.discovery_bet_1.types import PivotKind

def _find_chrome_binary() -> str:
    """Auto-detect a Chrome binary that works on macOS, Linux (incl. WSL/WSLg),
    and Windows. Override with the PHOENIX_CHROME_BINARY env var.

    On WSL2 with WSLg (Windows 11), install Chrome inside the Linux distro via
    `sudo apt install ./google-chrome-stable_current_amd64.deb` -- WSLg will
    surface its window natively on the Windows desktop, no extra setup needed.
    """
    import os as _os
    override = _os.environ.get("PHOENIX_CHROME_BINARY")
    if override:
        return override
    candidates = [
        # macOS
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        # Linux (apt-installed; same path inside WSL)
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
        # Native Windows (running cpython on Windows directly, not via WSL)
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        # Windows-side Chrome reachable from WSL via /mnt/c (used only when
        # someone explicitly overrides; the profile dir would live on Windows)
        "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
        "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    raise SystemExit(
        "No Chrome binary found. Set PHOENIX_CHROME_BINARY to the full path, "
        "or install Chrome:\n"
        "  macOS:  brew install --cask google-chrome\n"
        "  Linux/WSL: sudo apt install ./google-chrome-stable_current_amd64.deb\n"
        "then re-run."
    )


CHROME_BINARY = _find_chrome_binary()
PROFILE_DIR = REPO_ROOT / ".chrome-tv-manual"
DEBUG_PORT = 9222
SYMBOL = "BITGET:BTCUSDT.P"
CHART_URL = "https://www.tradingview.com/chart/?symbol=BITGET%3ABTCUSDT.P&interval=60"
LAYOUT_URL = "https://www.tradingview.com/chart/HrY4M7tK/?symbol=BITGET%3ABTCUSDT.P&interval=60"
# Date >= which a 3M view loads 1H bars reliably (relative to current data end).
RECENT_3M_FROM = "2026-02-23"
MIN_BARS = 24
ATR_MULT = 3.0

REMOVE_VOLUME_JS = r"""
const c = window._exposed_chartWidgetCollection;
if (!c) { return {ok:false, error:'no collection'}; }
const cm = c._activeChartWidgetModel.value().model();
const removed = [];
const srcs = (cm.dataSources ? cm.dataSources() : []).slice();
for (const s of srcs) {
    let nm = '';
    try { nm = (s.title ? s.title(true) : '') || (s.title ? s.title() : ''); } catch (e) {}
    try { if (!nm && s.metaInfo) { const mi = s.metaInfo(); nm = (mi && (mi.description || mi.shortDescription)) || ''; } } catch (e) {}
    if (/volume/i.test(String(nm))) {
        try { cm.removeSource(s); removed.push(String(nm)); }
        catch (e) { try { cm.removeSource(s.id ? s.id() : s); removed.push(String(nm)); } catch (e2) {} }
    }
}
return {ok:true, removed: removed};
"""

PLACE_FIB_JS = r"""
const mapped = arguments[0];
const chartInterval = arguments[1];
const c = window._exposed_chartWidgetCollection;
if (!c) { return {ok:false, error:'no _exposed_chartWidgetCollection'}; }
const model = c._activeChartWidgetModel.value();
const chartModel = model.model();
const pane = model.panes()[0];
const ownerSource = pane.mainDataSource ? pane.mainDataSource() : model.mainSeries();
const interval = String(model.mainSeries().interval());
const bars = model.mainSeries().data();
const barRows = [];
bars.each((index, value) => { barRows.push({index: index, epochSeconds: value[0]}); });
if (barRows.length === 0) { return {ok:false, error:'no bars loaded', interval: interval}; }
function resolve(p){ const ex = barRows.find(r=>r.epochSeconds===p.time_t); return ex?{index:ex.index, interval:chartInterval, offset:0, price:p.price, time_t:p.time_t}:null; }
const parent = resolve(mapped.parentPoint);
const terminal = resolve(mapped.terminalPoint);
if(!parent||!terminal){ return {ok:false, error:'anchor bar not found', want:[mapped.parentPoint.time_t, mapped.terminalPoint.time_t], haveRange:[barRows[0].epochSeconds, barRows[barRows.length-1].epochSeconds]}; }
const line = chartModel.createLineTool({linetool:'LineToolFibRetracement', pane: pane, ownerSource: ownerSource, point:{index:parent.index, price:parent.price}});
let target = chartModel.lineBeingCreated() || line;
if(!target){ return {ok:false, error:'no line creation session'}; }
chartModel.continueCreatingLine(terminal, false, false, false, false);
const lts = chartModel.allLineTools();
for(let i=lts.length-1;i>=0;i--){ const s = lts[i]&&lts[i].state&&lts[i].state(); if(s&&s.type==='LineToolFibRetracement'){ target=lts[i]; break; } }
chartModel.finishLineTool(target);
const name = arguments[2];
if (name) {
    try {
        const ch = target.properties().childs();
        if (ch.title && ch.title.setValue) { ch.title.setValue(name); }
        if (ch.editableText && ch.editableText.setValue) { ch.editableText.setValue(name); }
        if (ch.showText && ch.showText.setValue) { ch.showText.setValue(true); }
    } catch (e) {}
}
if (arguments[3] === false) {
    try { const chv = target.properties().childs(); if (chv.visible && chv.visible.setValue) { chv.visible.setValue(false); } } catch (e) {}
}
const restored = target&&target.state?target.state():null;
return {ok:true, type: restored&&restored.type, name: (target.name?target.name():null), fibCount: chartModel.allLineTools().length};
"""

REMOVE_BY_PREFIX_JS = r"""
const prefix = arguments[0];
const c = window._exposed_chartWidgetCollection;
if (!c) { return {ok:false, error:'no collection'}; }
const cm = c._activeChartWidgetModel.value().model();
const removed = [];
const lts = cm.allLineTools().slice();
for (const t of lts) {
    let txt = '';
    try {
        const ch = t.properties().childs();
        txt = (ch.editableText && ch.editableText.value && ch.editableText.value())
           || (ch.title && ch.title.value && ch.title.value()) || '';
    } catch (e) {}
    if (String(txt).indexOf(prefix) === 0) {
        try { cm.removeSource(t); removed.push(String(txt)); } catch (e) {}
    }
}
return {ok:true, removed: removed};
"""

# User-validated / corrected reference swings, placed explicitly with names.
MANUAL_SWINGS = [
    {"name": "auto1", "direction": "down", "parent_kind": "high", "term_kind": "low",
     "parent_ts": "2026-05-21T20:00:00", "parent_price": 78063.0,
     "term_ts": "2026-05-23T10:00:00", "term_price": 74204.7},
    {"name": "auto2", "direction": "up", "parent_kind": "low", "term_kind": "high",
     "parent_ts": "2026-05-18T18:00:00", "parent_price": 76010.0,
     "term_ts": "2026-05-21T11:00:00", "term_price": 78185.0},
    {"name": "auto3", "direction": "up", "parent_kind": "low", "term_kind": "high",
     "parent_ts": "2026-05-13T19:00:00", "parent_price": 78755.1,
     "term_ts": "2026-05-14T20:00:00", "term_price": 81998.4},
    {"name": "auto4", "direction": "down", "parent_kind": "high", "term_kind": "low",
     "parent_ts": "2026-05-11T22:00:00", "parent_price": 82047.7,
     "term_ts": "2026-05-13T19:00:00", "term_price": 78755.1},
    {"name": "auto5", "direction": "up", "parent_kind": "low", "term_kind": "high",
     "parent_ts": "2026-05-08T06:00:00", "parent_price": 79124.8,
     "term_ts": "2026-05-11T02:00:00", "term_price": 82435.2},
    {"name": "auto6", "direction": "down", "parent_kind": "high", "term_kind": "low",
     "parent_ts": "2026-05-06T14:00:00", "parent_price": 82799.0,
     "term_ts": "2026-05-08T06:00:00", "term_price": 79124.8},
    {"name": "auto7", "direction": "up", "parent_kind": "low", "term_kind": "high",
     "parent_ts": "2026-05-04T13:00:00", "parent_price": 78161.3,
     "term_ts": "2026-05-06T14:00:00", "term_price": 82799.0},
    {"name": "auto8", "direction": "down", "parent_kind": "high", "term_kind": "low",
     "parent_ts": "2026-04-27T04:00:00", "parent_price": 79459.0,
     "term_ts": "2026-04-29T21:00:00", "term_price": 74904.0},
]

# Human-taught corrections to the auto-detected recent-3M set: each one replaces
# the object whose tree name starts with name_prefix. auto5's terminal was the
# early 66510 low (a 4.4-ATR bounce tripped the zigzag); the true bottom is the
# 65556 low at 2026-03-09T00:00 (which is auto6's parent).
CORRECTED_SWINGS = [
    {"name_prefix": "auto5", "direction": "down", "parent_kind": "high", "term_kind": "low",
     "parent_ts": "2026-03-04T21:00:00", "parent_price": 74031.8,
     "term_ts": "2026-03-09T00:00:00", "term_price": 65556.0},
    # auto14 stopped short of the true high: a 4.5-ATR pullback off 68380 tripped
    # the zigzag, but price ran on to 69288 (Apr 1 10:00), which is auto15's parent.
    {"name_prefix": "auto14", "direction": "up", "parent_kind": "low", "term_kind": "high",
     "parent_ts": "2026-03-30T01:00:00", "parent_price": 64936.8,
     "term_ts": "2026-04-01T10:00:00", "term_price": 69288.0},
    # auto12+auto13 were one down move split by a sub-24-bar bounce; merged into a
    # single leg to the true low. Collapses both originals and the MERGE overlay.
    {"name_prefix": "auto12", "also_remove": ["auto13", "MERGE"],
     "direction": "down", "parent_kind": "high", "term_kind": "low",
     "parent_ts": "2026-03-25T13:00:00", "parent_price": 72000.0,
     "term_ts": "2026-03-30T01:00:00", "term_price": 64936.8},
]

# Proposal overlays drawn alongside the existing objects (no removal) so the user
# can compare by eye before committing. Cleared with the "clear-candidates" mode.
CANDIDATE_SWINGS = [
    {"name": "MERGE auto12+13 25-03 to 30-03 107c 17.4a",
     "direction": "down", "parent_kind": "high", "term_kind": "low",
     "parent_ts": "2026-03-25T13:00:00", "parent_price": 72000.0,
     "term_ts": "2026-03-30T01:00:00", "term_price": 64936.8},
]


from apps.worker.discovery_bet_1.swing_detector import clean_legs as _clean_legs_impl


def _clean_legs(candles, atr, pivots, min_bars=MIN_BARS, mult=ATR_MULT):
    """Re-export of apps.worker.discovery_bet_1.swing_detector.clean_legs.

    The detector moved to the worker package so the live bot can import it
    without depending on scripts/. This thin wrapper preserves the historical
    signature for the many existing callers in scripts/.
    """
    return _clean_legs_impl(candles, atr, pivots, min_bars=min_bars, mult=mult)


def _request_for(leg) -> TradingViewSyncRequest:
    return TradingViewSyncRequest(
        market_contract=TradingViewMarketContract(SYMBOL, "1H"),
        review_structure=TradingViewReviewStructure(
            structure_id=str(leg.get("name") or f"setup-{leg.get('parent_idx', '?')}-{leg.get('term_idx', '?')}"),
            direction=leg["direction"],
            parent_anchor_source_timestamp=leg["parent_ts"],
            parent_anchor_price=leg["parent_price"],
            parent_anchor_kind=leg["parent_kind"],
            terminal_extreme_source_timestamp=leg["term_ts"],
            terminal_extreme_price=leg["term_price"],
            terminal_extreme_kind=leg["term_kind"],
        ),
    )


def _make_driver(launch_if_missing: bool = False) -> tuple[object, bool]:
    attach = Options()
    attach.add_experimental_option("debuggerAddress", f"127.0.0.1:{DEBUG_PORT}")
    try:
        return webdriver.Chrome(options=attach), True
    except WebDriverException:
        if not launch_if_missing:
            raise SystemExit(
                f"No debug Chrome on 127.0.0.1:{DEBUG_PORT}. Launch it and log into "
                f"TradingView first:\n"
                f"  .venv/bin/python scripts/place_fibs_tradingview.py login\n"
                f"then re-run. (Refusing to launch a second Chrome on the in-use "
                f"profile -- that collides with the running browser and crashes.)"
            ) from None
    opts = Options()
    opts.binary_location = CHROME_BINARY
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument(f"--remote-debugging-port={DEBUG_PORT}")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_experimental_option("detach", True)
    driver = webdriver.Chrome(options=opts)
    driver.set_window_size(1700, 1100)
    return driver, False


def main() -> None:
    args = sys.argv[1:]
    mode = args[0] if args else "12"

    candles = load_candle_input(DEFAULT_INPUT_PATH).candles
    atr = calculate_atr14(candles)
    pivots = detect_local_pivots(candles)
    legs = _clean_legs(candles, atr, pivots)

    if mode == "dry":
        count = int(args[1]) if len(args) > 1 else 12
        print(f"clean legs total: {len(legs)} | showing last {count}")
        for leg in legs[-count:]:
            print(f"  {leg['direction']:4} {leg['parent_ts']} {leg['parent_price']} -> "
                  f"{leg['term_ts']} {leg['term_price']}  (span {leg['term_idx']-leg['parent_idx']}, size {leg['size']:.1f})")
        return

    # `login` mode bypasses selenium entirely: selenium-managed chromedriver
    # ignores our --remote-debugging-port=9222 flag and binds its own random
    # port, so the placement step can never attach. Spawn Chrome directly via
    # subprocess and let the user log in. The next non-login invocation uses
    # the same .chrome-tv-manual profile and attaches to 9222 cleanly.
    if mode == "login":
        import subprocess as _sp
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        chrome_cmd = [
            CHROME_BINARY,
            f"--remote-debugging-port={DEBUG_PORT}",
            f"--user-data-dir={PROFILE_DIR}",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            CHART_URL,
        ]
        _sp.Popen(chrome_cmd, stdin=_sp.DEVNULL, stdout=_sp.DEVNULL,
                  stderr=_sp.DEVNULL, start_new_session=True)
        print(f"Spawned Chrome with debug port {DEBUG_PORT} + profile {PROFILE_DIR}.")
        print("Log in with the Email option, then re-run without 'login' to place setups.")
        return

    driver, attached = _make_driver(launch_if_missing=False)
    if not attached or "tradingview.com/chart" not in driver.current_url:
        driver.get(CHART_URL)
        time.sleep(10)
    elif mode == "2026":
        # Reset to a clean 1H layout: a prior run may have left the chart on 1D.
        driver.get(LAYOUT_URL)
        time.sleep(10)

    if mode == "correct":
        # Surgically replace specific objects in place; leave the rest of the
        # chart and the current view untouched (no wipe, no re-range).
        # Optional arg selects a single correction by prefix (e.g. "correct auto14").
        only = args[1] if len(args) > 1 else None
        ts_index = {c.source_timestamp: i for i, c in enumerate(candles)}
        svc = DB1TradingViewSyncService()
        ctx = svc._detect_chart_time_context(driver)
        for leg in CORRECTED_SWINGS:
            prefix = leg["name_prefix"]
            if only and prefix != only:
                continue
            rem = driver.execute_script(REMOVE_BY_PREFIX_JS, prefix + " ")
            removed = list(rem.get("removed", []))
            for ap in leg.get("also_remove", []):
                r2 = driver.execute_script(REMOVE_BY_PREFIX_JS, ap + " ")
                removed += r2.get("removed", [])
            pi, ti = ts_index[leg["parent_ts"]], ts_index[leg["term_ts"]]
            depth = abs(leg["term_price"] - leg["parent_price"]) / (atr[ti] or atr[pi] or 1.0)
            pd = f"{leg['parent_ts'][8:10]}-{leg['parent_ts'][5:7]}"
            td = f"{leg['term_ts'][8:10]}-{leg['term_ts'][5:7]}"
            leg["name"] = f"{prefix} {pd} to {td} {ti - pi}c {depth:.1f}a"
            req = _request_for(leg)
            for tz in (ctx.effective_chart_timezone, "UTC"):
                pts = _build_expected_line_tool_points(req, chart_time_zone=tz)
                mapped = {
                    "parentPoint": {"price": pts[0]["price"], "time_t": pts[0]["time_t"]},
                    "terminalPoint": {"price": pts[1]["price"], "time_t": pts[1]["time_t"]},
                }
                result = driver.execute_script(PLACE_FIB_JS, mapped, "60", leg["name"], True)
                if isinstance(result, dict) and result.get("ok"):
                    print(f"corrected {prefix}: removed {removed} -> placed {leg['name']!r}")
                    break
            else:
                print(f"FAILED to place corrected {prefix}: {result}")
        driver.execute_cdp_cmd("Page.bringToFront", {})
        return

    if mode == "candidate":
        # Overlay proposal legs alongside existing objects (no wipe/removal).
        svc = DB1TradingViewSyncService()
        ctx = svc._detect_chart_time_context(driver)
        for leg in CANDIDATE_SWINGS:
            req = _request_for(leg)
            for tz in (ctx.effective_chart_timezone, "UTC"):
                pts = _build_expected_line_tool_points(req, chart_time_zone=tz)
                mapped = {
                    "parentPoint": {"price": pts[0]["price"], "time_t": pts[0]["time_t"]},
                    "terminalPoint": {"price": pts[1]["price"], "time_t": pts[1]["time_t"]},
                }
                result = driver.execute_script(PLACE_FIB_JS, mapped, "60", leg["name"], True)
                if isinstance(result, dict) and result.get("ok"):
                    print(f"candidate placed: {leg['name']!r}")
                    break
            else:
                print(f"FAILED candidate {leg['name']!r}: {result}")
        driver.execute_cdp_cmd("Page.bringToFront", {})
        return

    if mode == "clear-candidates":
        rem = driver.execute_script(REMOVE_BY_PREFIX_JS, "MERGE ")
        print(f"cleared candidates: {rem.get('removed')}")
        driver.execute_cdp_cmd("Page.bringToFront", {})
        return

    if mode == "manual":
        setups = MANUAL_SWINGS
        all_visible = False
    elif mode == "2026":
        # TradingView keeps 1H bars only on a ~3-month view; a wider range
        # downsamples to 1D and no anchor bars resolve. Place the recent chunk.
        setups = [
            leg for leg in _clean_legs(candles, atr, pivots, min_bars=MIN_BARS, mult=4.0)
            if leg["parent_ts"] >= RECENT_3M_FROM
        ]
        all_visible = True
    else:
        count = int(mode)
        setups = legs[-count:]
        all_visible = False
    # Encode each swing's measured variables into its name: <span>c <depth>a
    ts_index = {c.source_timestamp: i for i, c in enumerate(candles)}
    for i, leg in enumerate(setups, start=1):
        pi = leg.get("parent_idx", ts_index.get(leg["parent_ts"]))
        ti = leg.get("term_idx", ts_index.get(leg["term_ts"]))
        span = ti - pi
        size = abs(leg["term_price"] - leg["parent_price"])
        depth = size / (atr[ti] or atr[pi] or 1.0)
        pd = f"{leg['parent_ts'][8:10]}-{leg['parent_ts'][5:7]}"
        td = f"{leg['term_ts'][8:10]}-{leg['term_ts'][5:7]}"
        leg["name"] = f"auto{i} {pd} to {td} {span}c {depth:.1f}a"
        leg["visible"] = True if all_visible else (i >= len(setups) - 1)
    print(f"Placing {len(setups)} setups (attached={attached}):")
    for leg in setups:
        print(f"  {leg.get('name',''):6} {leg['direction']:4} {leg['parent_ts']} -> {leg['term_ts']}")

    range_tab = "3M"  # YTD/6M downsample 1H -> 1D; 3M keeps hourly bars
    try:
        btn = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, f'button[data-name="date-range-tab-{range_tab}"]')
            )
        )
        driver.execute_script("arguments[0].click();", btn)  # JS click avoids overlay interception
        time.sleep(7)
    except Exception as exc:  # non-fatal: keep placing within already-loaded bars
        print(f"warning: {range_tab} date-range click skipped ({type(exc).__name__}); continuing")
    driver.execute_script(
        "const c=window._exposed_chartWidgetCollection; if(c){c._activeChartWidgetModel.value().removeAllDrawingTools();}"
    )
    try:
        vol = driver.execute_script(REMOVE_VOLUME_JS)
        print(f"volume removal: {vol}")
    except Exception as exc:
        print(f"volume removal skipped ({type(exc).__name__})")

    svc = DB1TradingViewSyncService()
    ctx = svc._detect_chart_time_context(driver)
    placed = 0
    for leg in setups:
        req = _request_for(leg)
        for tz in (ctx.effective_chart_timezone, "UTC"):
            pts = _build_expected_line_tool_points(req, chart_time_zone=tz)
            mapped = {
                "parentPoint": {"price": pts[0]["price"], "time_t": pts[0]["time_t"]},
                "terminalPoint": {"price": pts[1]["price"], "time_t": pts[1]["time_t"]},
            }
            result = driver.execute_script(PLACE_FIB_JS, mapped, "60", leg.get("name", ""), leg.get("visible", True))
            if isinstance(result, dict) and result.get("ok"):
                placed += 1
                print(f"  placed {leg.get('name','')}: tree-name={result.get('name')!r}")
                break
        else:
            print(f"  FAILED {req.review_structure.structure_id}: {result}")
    driver.execute_cdp_cmd("Page.bringToFront", {})
    print(f"Done. Placed {placed}/{len(setups)} fib objects.")


if __name__ == "__main__":
    main()
