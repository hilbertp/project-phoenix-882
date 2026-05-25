#!/usr/bin/env python
"""Place exactly TWO DB1 setups as real native TradingView Fib Retracement objects.

Opens Chrome (chrome-tv-manual profile), loads BITGET:BTCUSDT.P 1H, and creates
two LineToolFibRetracement drawings via the chart API -- each a separate object
in the Object Tree, so they can be shown/hidden individually. The browser is
left open (detach) for human review.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from apps.api.db1_review_tradingview.service import (
    DB1TradingViewSyncService,
    TradingViewMarketContract,
    TradingViewReviewStructure,
    TradingViewSyncRequest,
    _build_expected_line_tool_points,
)
from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from apps.worker.discovery_bet_1.types import PivotKind

CHROME_BINARY = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE_DIR = REPO_ROOT / ".chrome-tv-manual"
SYMBOL = "BITGET:BTCUSDT.P"
CHART_URL = "https://www.tradingview.com/chart/?symbol=BITGET%3ABTCUSDT.P&interval=60"

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
const minE = barRows[0].epochSeconds, maxE = barRows[barRows.length-1].epochSeconds;
function resolve(p){ const ex = barRows.find(r=>r.epochSeconds===p.time_t); return ex?{index:ex.index, interval:chartInterval, offset:0, price:p.price, time_t:p.time_t}:null; }
const parent = resolve(mapped.parentPoint);
const terminal = resolve(mapped.terminalPoint);
if(!parent||!terminal){ return {ok:false, error:'anchor bar not found', interval: interval, want:[mapped.parentPoint.time_t, mapped.terminalPoint.time_t], haveRange:[minE,maxE], barCount: barRows.length}; }
const fromIndex = Math.min(parent.index, terminal.index)-20;
const toIndex = Math.max(parent.index, terminal.index)+20;
try { model.timeScale().zoomToBarsRange(fromIndex, toIndex); } catch(e){}
const line = chartModel.createLineTool({linetool:'LineToolFibRetracement', pane: pane, ownerSource: ownerSource, point:{index:parent.index, price:parent.price}});
let target = chartModel.lineBeingCreated() || line;
if(!target){ return {ok:false, error:'no line creation session', interval: interval}; }
chartModel.continueCreatingLine(terminal, false, false, false, false);
const lts = chartModel.allLineTools();
for(let i=lts.length-1;i>=0;i--){ const s = lts[i]&&lts[i].state&&lts[i].state(); if(s&&s.type==='LineToolFibRetracement'){ target=lts[i]; break; } }
chartModel.finishLineTool(target);
const restored = target&&target.state?target.state():null;
return {ok:true, interval: interval, type: restored&&restored.type, points: restored&&restored.points, fibCount: chartModel.allLineTools().length};
"""


def _clean_setups(candles, atr, pivots, min_bars=24, mult=2.0):
    out = []
    last = -1
    for ti, term in enumerate(pivots):
        a = atr[term.index]
        if a is None:
            continue
        opp = PivotKind.LOW if term.kind == PivotKind.HIGH else PivotKind.HIGH
        for cand in reversed(pivots[:ti]):
            if cand.kind != opp:
                continue
            if (term.index - cand.index) < min_bars:
                continue
            if term.kind == PivotKind.HIGH and term.price <= cand.price:
                continue
            if term.kind == PivotKind.LOW and term.price >= cand.price:
                continue
            if abs(term.price - cand.price) < a * mult:
                continue
            if cand.index >= last:
                out.append((cand, term))
                last = term.index
            break
    return out


def _request_for(cand, term) -> TradingViewSyncRequest:
    direction = "up" if cand.kind == PivotKind.LOW else "down"
    return TradingViewSyncRequest(
        market_contract=TradingViewMarketContract(SYMBOL, "1H"),
        review_structure=TradingViewReviewStructure(
            structure_id=f"setup-{cand.index}-{term.index}",
            direction=direction,
            parent_anchor_source_timestamp=cand.source_timestamp,
            parent_anchor_price=cand.price,
            parent_anchor_kind=cand.kind.value,
            terminal_extreme_source_timestamp=term.source_timestamp,
            terminal_extreme_price=term.price,
            terminal_extreme_kind=term.kind.value,
        ),
    )


def main() -> None:
    candles = load_candle_input(DEFAULT_INPUT_PATH).candles
    atr = calculate_atr14(candles)
    pivots = detect_local_pivots(candles)
    setups = _clean_setups(candles, atr, pivots)[-2:]
    print("Placing 2 setups:")
    for cand, term in setups:
        print(f"  {('up' if cand.kind==PivotKind.LOW else 'down'):4} "
              f"{cand.kind.value}={cand.price}@{cand.source_timestamp} -> "
              f"{term.kind.value}={term.price}@{term.source_timestamp}")

    options = Options()
    options.binary_location = CHROME_BINARY
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    options.add_experimental_option("detach", True)
    driver = webdriver.Chrome(options=options)
    driver.set_window_size(1700, 1100)
    driver.get(CHART_URL)
    time.sleep(10)

    svc = DB1TradingViewSyncService()
    ctx = svc._detect_chart_time_context(driver)
    print(f"chart timezone: {ctx.effective_chart_timezone} (source {ctx.timezone_source})")

    for cand, term in setups:
        req = _request_for(cand, term)
        for tz in (ctx.effective_chart_timezone, "UTC"):
            pts = _build_expected_line_tool_points(req, chart_time_zone=tz)
            mapped = {
                "parentPoint": {"price": pts[0]["price"], "time_t": pts[0]["time_t"],
                                "source_timestamp": req.review_structure.parent_anchor_source_timestamp},
                "terminalPoint": {"price": pts[1]["price"], "time_t": pts[1]["time_t"],
                                  "source_timestamp": req.review_structure.terminal_extreme_source_timestamp},
            }
            result = driver.execute_script(PLACE_FIB_JS, mapped, "60")
            print(f"[{req.review_structure.structure_id}] tz={tz} -> {result}")
            if isinstance(result, dict) and result.get("ok"):
                break
    driver.execute_cdp_cmd("Page.bringToFront", {})
    print("Done. Browser left open for review.")


if __name__ == "__main__":
    main()
