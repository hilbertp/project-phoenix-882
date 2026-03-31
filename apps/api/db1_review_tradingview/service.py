from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
from threading import Lock
import time
from typing import Any, cast
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_CHROME_BINARY = Path(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)
TRADINGVIEW_DARK_BACKGROUND = "#131722"
TRADINGVIEW_DARK_GRID = "rgba(42, 46, 57, 0.5)"
TRADINGVIEW_DARK_TEXT = "#d1d4dc"
TRADINGVIEW_DARK_LINE = "#2a2e39"
DEFAULT_CHART_TIME_ZONE = "UTC"
REVIEW_FIB_LEVEL_SEQUENCE = (
    0.0,
    0.236,
    0.382,
    0.5,
    0.618,
    0.786,
    0.882,
    0.941,
    1.0,
    1.618,
    2.618,
    3.618,
    4.236,
    1.272,
    1.414,
    2.272,
    2.414,
    2.0,
    3.0,
    3.272,
    3.414,
    4.0,
    4.272,
    4.414,
    4.618,
    4.764,
)
DEFAULT_REVIEW_FIB_LINE_COLOR = "#FFFFFF"
DEFAULT_REVIEW_VISIBLE_FIB_LEVELS = (
    1.0,
    0.941,
    0.882,
    0.786,
    0.618,
    0.5,
    0.382,
    0.236,
    0.0,
)


class InvalidTradingViewSyncRequestError(Exception):
    """The caller supplied an invalid TradingView sync request."""


class TradingViewSyncError(Exception):
    """The local TradingView sync step failed."""


@dataclass(frozen=True, slots=True)
class TradingViewMarketContract:
    tradingview_symbol: str
    timeframe: str


@dataclass(frozen=True, slots=True)
class TradingViewReviewStructure:
    structure_id: str
    direction: str
    parent_anchor_source_timestamp: str
    parent_anchor_price: float
    parent_anchor_kind: str
    terminal_extreme_source_timestamp: str
    terminal_extreme_price: float
    terminal_extreme_kind: str


@dataclass(frozen=True, slots=True)
class TradingViewSyncRequest:
    market_contract: TradingViewMarketContract
    review_structure: TradingViewReviewStructure
    keep_browser_open: bool = False
    preserve_review_context: bool = False


@dataclass(frozen=True, slots=True)
class TradingViewChartTimeContext:
    local_system_timezone: str
    explicit_chart_timezone: str | None
    effective_chart_timezone: str
    timezone_source: str


@dataclass(frozen=True, slots=True)
class TradingViewReviewStyle:
    visible_levels: tuple[float, ...] = DEFAULT_REVIEW_VISIBLE_FIB_LEVELS
    line_color: str = DEFAULT_REVIEW_FIB_LINE_COLOR


DEFAULT_REVIEW_FIB_STYLE = TradingViewReviewStyle()

_DARK_MODE_BOOTSTRAP_SCRIPT = """
(() => {
    const applyTheme = () => {
        const html = document.documentElement;
        if (html) {
            html.classList.remove('theme-light');
            html.classList.add('theme-dark');
        }
        const body = document.body;
        if (body) {
            body.classList.remove('theme-light');
            body.classList.add('theme-dark');
            body.style.backgroundColor = '#131722';
            body.style.color = '#d1d4dc';
        }
        let themeMeta = document.querySelector('meta[name="theme-color"]');
        if (!themeMeta && document.head) {
            themeMeta = document.createElement('meta');
            themeMeta.setAttribute('name', 'theme-color');
            document.head.appendChild(themeMeta);
        }
        if (themeMeta) {
            themeMeta.setAttribute('content', '#131722');
        }
    };
    applyTheme();
    document.addEventListener('DOMContentLoaded', applyTheme, { once: false });
    new MutationObserver(() => applyTheme()).observe(document.documentElement, { childList: true, subtree: true });
})();
"""


class DB1TradingViewSyncService:
    def __init__(
        self,
        chrome_binary: Path = DEFAULT_CHROME_BINARY,
        review_style: TradingViewReviewStyle = DEFAULT_REVIEW_FIB_STYLE,
    ) -> None:
        self._chrome_binary = chrome_binary
        self._review_style = review_style
        self._lock = Lock()
        self._retained_driver: Any | None = None
        self._retained_request_key: tuple[str, str, str] | None = None

    def sync_structure(self, payload: dict[str, object]) -> dict[str, object]:
        request = _parse_sync_request(payload)
        with self._lock:
            request_key = _build_request_key(request)
            reuse_browser_session = (
                request.keep_browser_open
                and request.preserve_review_context
                and self._retained_driver is not None
            )
            reuse_existing_tool = (
                reuse_browser_session and self._retained_request_key == request_key
            )

            if reuse_browser_session:
                driver = self._retained_driver
                self._retained_driver = None
                self._retained_request_key = None
            else:
                if request.keep_browser_open:
                    self._release_retained_driver()
                driver = self._create_driver()

            if driver is None:
                self._release_retained_driver()
                driver = self._create_driver()
            try:
                response_payload = self._sync_in_browser(
                    driver,
                    request,
                    reuse_browser_session=reuse_browser_session,
                    prefer_preserved_review_tool=reuse_existing_tool,
                )
                if request.keep_browser_open:
                    self._retained_driver = driver
                    self._retained_request_key = request_key
                    driver = None
                return response_payload
            except TradingViewSyncError:
                raise
            except Exception as error:
                raise TradingViewSyncError(
                    "TradingView sync failed during browser automation."
                ) from error
            finally:
                if driver is not None:
                    self._close_driver(driver)

    def _release_retained_driver(self) -> None:
        if self._retained_driver is None:
            return
        self._close_driver(self._retained_driver)
        self._retained_driver = None
        self._retained_request_key = None

    def _create_driver(self) -> Any:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError as error:
            raise TradingViewSyncError(
                "selenium is required for local TradingView review sync."
            ) from error

        if not self._chrome_binary.exists():
            raise TradingViewSyncError(
                f"Chrome binary was not found at {self._chrome_binary}."
            )

        options = Options()
        options.binary_location = str(self._chrome_binary)
        driver = cast(Any, webdriver).Chrome(options=options)
        driver.set_window_size(1600, 1200)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": _DARK_MODE_BOOTSTRAP_SCRIPT},
        )
        return driver

    def _close_driver(self, driver: Any) -> None:
        try:
            driver.quit()
        except Exception:
            pass

    def _sync_in_browser(
        self,
        driver: Any,
        request: TradingViewSyncRequest,
        *,
        reuse_browser_session: bool,
        prefer_preserved_review_tool: bool,
    ) -> dict[str, object]:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.common.exceptions import TimeoutException

        wait = WebDriverWait(driver, 20)
        chart_url = (
            "https://www.tradingview.com/chart/?symbol="
            + quote(request.market_contract.tradingview_symbol, safe="")
        )
        try:
            if not prefer_preserved_review_tool:
                driver.get(chart_url)
            driver.execute_cdp_cmd("Page.bringToFront", {})

            if not prefer_preserved_review_tool:
                wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[aria-label="Change interval"]'))
                ).click()
                interval_input = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="text"]'))
                )
                interval_input.send_keys(Keys.COMMAND, "a")
                interval_input.send_keys("60")
                interval_input.send_keys(Keys.ENTER)
                time.sleep(3)

                wait.until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, 'button[data-name="date-range-tab-3M"]')
                    )
                ).click()
                time.sleep(4)
            self._apply_dark_mode(driver)
        except TimeoutException as error:
            raise TradingViewSyncError(
                "TradingView sync could not reach the required chart controls."
            ) from error

        chart_time_context = self._detect_chart_time_context(driver)
        aligned_points = _build_expected_line_tool_points(
            request,
            chart_time_zone=chart_time_context.effective_chart_timezone,
        )
        review_style_state = _build_review_fib_state(
            market_symbol=request.market_contract.tradingview_symbol,
            chart_interval=_chart_interval_for_timeframe(request.market_contract.timeframe),
            review_style=self._review_style,
        )

        focus_payload = driver.execute_script(
            """
const marketContract = arguments[0];
const mappedPoints = arguments[1];
const fibState = arguments[2];
const chartInterval = arguments[3];
const preferPreservedReviewTool = arguments[4];
const c = window._exposed_chartWidgetCollection;
if (!c) {
  throw new Error('TradingView chart widget collection is unavailable.');
}
const model = c._activeChartWidgetModel.value();
const chartModel = model.model();
const pane = model.panes()[0];
const ownerSource = pane.mainDataSource ? pane.mainDataSource() : model.mainSeries();
if (String(model.mainSeries().interval()) !== chartInterval) {
    throw new Error('TradingView chart did not apply the required interval.');
}
const bars = model.mainSeries().data();
const barRows = [];
bars.each((index, value) => {
    barRows.push({ index, epochSeconds: value[0] });
});
if (barRows.length === 0) {
  throw new Error('TradingView hourly bar data is unavailable.');
}
function resolvePoint(point) {
    const epochSeconds = point.time_t;
    const exact = barRows.find((row) => row.epochSeconds === epochSeconds);
    if (!exact) {
                throw new Error('TradingView chart does not contain an exact 1H bar for ' + point.source_timestamp + ' after chart-time alignment.');
    }
    return {
        index: exact.index,
        interval: chartInterval,
        offset: 0,
                price: point.price,
        time_t: epochSeconds,
    };
}
function resolveExistingPoint(point) {
    const epochSeconds = point && typeof point.time_t === 'number' ? point.time_t : null;
    if (epochSeconds === null) {
        throw new Error('TradingView preserved fib state is missing anchor timestamps.');
    }
    const exact = barRows.find((row) => row.epochSeconds === epochSeconds);
    if (!exact) {
        throw new Error('TradingView preserved fib anchor is not present in the current 1H chart range.');
    }
    return {
        index: exact.index,
        interval: chartInterval,
        offset: 0,
        price: point.price,
        time_t: epochSeconds,
    };
}
function findExistingReviewTool() {
    if (typeof chartModel.allLineTools !== 'function') {
        return null;
    }
    const lineTools = chartModel.allLineTools();
    if (!Array.isArray(lineTools)) {
        return null;
    }
    for (let index = lineTools.length - 1; index >= 0; index -= 1) {
        const candidate = lineTools[index];
        if (!candidate || typeof candidate.state !== 'function') {
            continue;
        }
        const candidateState = candidate.state();
        if (candidateState && candidateState.type === 'LineToolFibRetracement') {
            return candidate;
        }
    }
    return null;
}
function ensureReviewToolSelected(target) {
    const selection = typeof chartModel.selection === 'function' ? chartModel.selection() : null;
    if (!selection || typeof selection.add !== 'function' || typeof selection.isSelected !== 'function') {
        throw new Error('TradingView fib placement could not access the chart selection model.');
    }
    selection.add(target);
    if (!selection.isSelected(target)) {
        throw new Error('TradingView fib placement did not leave the fib selected for editing.');
    }
    return selection.allSources ? selection.allSources().length : null;
}
const parentPoint = resolvePoint(mappedPoints.parentPoint);
const terminalPoint = resolvePoint(mappedPoints.terminalPoint);
let target = null;
let restoredState = null;
let activeParentPoint = parentPoint;
let activeTerminalPoint = terminalPoint;
let reusedExistingTool = false;
let selectionCount = null;
if (preferPreservedReviewTool) {
    target = findExistingReviewTool();
    restoredState = target && typeof target.state === 'function' ? target.state() : null;
    if (
        restoredState
        && Array.isArray(restoredState.points)
        && restoredState.points.length === 2
    ) {
        activeParentPoint = resolveExistingPoint(restoredState.points[0]);
        activeTerminalPoint = resolveExistingPoint(restoredState.points[1]);
        reusedExistingTool = true;
    } else {
        target = null;
        restoredState = null;
    }
}
const fromIndex = Math.min(activeParentPoint.index, activeTerminalPoint.index) - 16;
const toIndex = Math.max(activeParentPoint.index, activeTerminalPoint.index) + 16;
model.timeScale().zoomToBarsRange(fromIndex, toIndex);
if (!reusedExistingTool) {
    model.removeAllDrawingTools();
    const line = chartModel.createLineTool({
            linetool: 'LineToolFibRetracement',
            pane,
            ownerSource,
            point: {
                    index: parentPoint.index,
                    price: parentPoint.price,
            },
    });
    target = chartModel.lineBeingCreated() || line;
    if (!target) {
        throw new Error('TradingView fib placement did not start a native line creation session.');
    }
    chartModel.continueCreatingLine(
            terminalPoint,
            false,
            false,
            false,
            false,
    );
    target = findExistingReviewTool() || line;
    const properties = target && typeof target.properties === 'function' ? target.properties() : null;
    if (!properties || typeof properties.mergePreferences !== 'function') {
        throw new Error('TradingView fib placement could not access line tool preferences.');
    }
    properties.mergePreferences(fibState);
    chartModel.finishLineTool(target);
    if (chartModel.lineBeingCreated()) {
        throw new Error('TradingView fib placement left the drawing in unfinished creation mode.');
    }
    restoredState = target && target.state ? target.state() : null;
}
if (!target) {
    throw new Error('TradingView fib placement could not resolve the review fib tool.');
}
selectionCount = ensureReviewToolSelected(target);
return {
  chartTitle: document.title,
  interval: String(model.mainSeries().interval()),
  marketSymbol: marketContract.tradingview_symbol,
  fromIndex,
  toIndex,
    parentPoint: activeParentPoint,
    terminalPoint: activeTerminalPoint,
    restoredState,
    reusedExistingTool,
    selectionCount,
    selectedForEditing: true,
    targetType: restoredState && restoredState.type ? restoredState.type : (target && target.toolname ? target.toolname : null),
};
""",
            {
                "tradingview_symbol": request.market_contract.tradingview_symbol,
                "timeframe": request.market_contract.timeframe,
            },
            {
                "parentPoint": {
                    "price": aligned_points[0]["price"],
                    "source_timestamp": request.review_structure.parent_anchor_source_timestamp,
                    "time_t": aligned_points[0]["time_t"],
                },
                "terminalPoint": {
                    "price": aligned_points[1]["price"],
                    "source_timestamp": request.review_structure.terminal_extreme_source_timestamp,
                    "time_t": aligned_points[1]["time_t"],
                },
            },
            review_style_state,
            _chart_interval_for_timeframe(request.market_contract.timeframe),
            prefer_preserved_review_tool,
        )
        driver.execute_cdp_cmd("Page.bringToFront", {})

        if focus_payload["targetType"] != "LineToolFibRetracement":
            raise TradingViewSyncError(
                "TradingView sync did not create a fib retracement drawing on the chart."
            )
        if cast(bool, focus_payload["selectedForEditing"]) is not True:
            raise TradingViewSyncError(
                "TradingView sync rendered the fib but did not leave it selected for editing."
            )

        live_anchor_pair = _build_anchor_pair_from_line_tool_state(
            cast(dict[str, object] | None, focus_payload["restoredState"]),
            chart_time_zone=chart_time_context.effective_chart_timezone,
        )
        if live_anchor_pair is None:
            raise TradingViewSyncError(
                "TradingView sync could not read back the live fib anchor pair from the chart."
            )

        proposed_anchor_pair = _build_proposed_anchor_pair(request)
        matches_proposed_anchors = _anchor_pairs_match(
            live_anchor_pair,
            proposed_anchor_pair,
        )
        if cast(bool, focus_payload["reusedExistingTool"]) and not matches_proposed_anchors:
            render_verification = {
                "verified": False,
                "mode": "retained-live-tool",
                "reviewer_adjusted": True,
                "chart_time_zone": chart_time_context.effective_chart_timezone,
                "direction": request.review_structure.direction,
                "parent_anchor_kind": request.review_structure.parent_anchor_kind,
                "parent_anchor_source_timestamp": request.review_structure.parent_anchor_source_timestamp,
                "parent_anchor_price": request.review_structure.parent_anchor_price,
                "terminal_extreme_kind": request.review_structure.terminal_extreme_kind,
                "terminal_extreme_source_timestamp": request.review_structure.terminal_extreme_source_timestamp,
                "terminal_extreme_price": request.review_structure.terminal_extreme_price,
            }
        else:
            render_verification = _build_render_verification(
                request=request,
                restored_state=focus_payload["restoredState"],
                chart_time_zone=chart_time_context.effective_chart_timezone,
            )
            if cast(bool, focus_payload["reusedExistingTool"]):
                render_verification["mode"] = "retained-live-tool"
                render_verification["reviewer_adjusted"] = False

        return {
            "status": "ok",
            "chart_url": chart_url,
            "browser_retained": request.keep_browser_open,
            "browser_session_reused": reuse_browser_session,
            "chart_theme": {
                "mode": "dark",
                "implementation": "preload-theme-bootstrap-plus-chart-properties",
            },
            "chart_time_alignment": {
                "local_system_timezone": chart_time_context.local_system_timezone,
                "explicit_chart_timezone": chart_time_context.explicit_chart_timezone,
                "effective_chart_timezone": chart_time_context.effective_chart_timezone,
                "timezone_source": chart_time_context.timezone_source,
            },
            "market_symbol": request.market_contract.tradingview_symbol,
            "timeframe": request.market_contract.timeframe,
            "structure_id": request.review_structure.structure_id,
            "placed_tool": focus_payload["targetType"],
            "chart_title": focus_payload["chartTitle"],
            "review_style": {
                "line_color": self._review_style.line_color,
                "visible_levels": list(self._review_style.visible_levels),
            },
            "review_tool": {
                "source": (
                    "retained-live-tool"
                    if cast(bool, focus_payload["reusedExistingTool"])
                    else "proposal-render"
                ),
                "reused_existing_tool": focus_payload["reusedExistingTool"],
                "selected_for_editing": focus_payload["selectedForEditing"],
                "selection_count": focus_payload["selectionCount"],
                "matches_proposed_anchors": matches_proposed_anchors,
                "anchor_pair": live_anchor_pair,
            },
            "render_verification": render_verification,
        }

    def _apply_dark_mode(self, driver: Any) -> None:
        payload = driver.execute_script(
            """
const html = document.documentElement;
const body = document.body;
if (!html || !body) {
    return { applied: false, reason: 'document-unavailable' };
}

html.classList.remove('theme-light');
body.classList.remove('theme-light');
html.classList.add('theme-dark');
body.classList.add('theme-dark');
html.style.backgroundColor = '#131722';
body.style.backgroundColor = '#131722';
body.style.color = '#d1d4dc';

let themeMeta = document.querySelector('meta[name="theme-color"]');
if (!themeMeta && document.head) {
    themeMeta = document.createElement('meta');
    themeMeta.setAttribute('name', 'theme-color');
    document.head.appendChild(themeMeta);
}
if (themeMeta) {
    themeMeta.setAttribute('content', '#131722');
}

const collection = window._exposed_chartWidgetCollection;
if (collection && collection._activeChartWidgetModel && collection._activeChartWidgetModel.value) {
    const widgetModel = collection._activeChartWidgetModel.value();
    const chartModel = widgetModel && typeof widgetModel.model === 'function' ? widgetModel.model() : null;
    const chartProperties = chartModel && typeof chartModel.properties === 'function' ? chartModel.properties() : null;
    const childs = chartProperties && typeof chartProperties.childs === 'function' ? chartProperties.childs() : null;
    if (childs && childs.paneProperties && childs.scalesProperties) {
        const pane = childs.paneProperties.childs();
        const scales = childs.scalesProperties.childs();
        pane.background.setValue('#131722');
        pane.backgroundGradientStartColor.setValue('#131722');
        pane.backgroundGradientEndColor.setValue('#131722');
        pane.separatorColor.setValue('#2a2e39');
        pane.vertGridProperties.childs().color.setValue('rgba(42, 46, 57, 0.5)');
        pane.horzGridProperties.childs().color.setValue('rgba(42, 46, 57, 0.5)');
        scales.backgroundColor.setValue('#131722');
        scales.textColor.setValue('#d1d4dc');
        scales.lineColor.setValue('#2a2e39');
    }
}

return {
    applied: html.classList.contains('theme-dark') && body.classList.contains('theme-dark'),
    htmlClassName: html.className,
    bodyClassName: body.className,
    themeMeta: themeMeta ? themeMeta.getAttribute('content') : null,
};
"""
        )
        if (
            not isinstance(payload, dict)
            or payload.get("applied") is not True
            or payload.get("themeMeta") != TRADINGVIEW_DARK_BACKGROUND
        ):
            raise TradingViewSyncError(
                "TradingView sync could not switch the review chart into dark mode."
            )

    def _detect_chart_time_context(self, driver: Any) -> TradingViewChartTimeContext:
        payload = driver.execute_script(
            """
const explicitChartTimeZone = null;
const browserLocalTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || null;
const effectiveChartTimeZone = explicitChartTimeZone || browserLocalTimeZone || 'UTC';
return {
  localSystemTimeZone: browserLocalTimeZone || 'UTC',
  explicitChartTimeZone,
  effectiveChartTimeZone,
  timezoneSource: explicitChartTimeZone ? 'chart-setting' : (browserLocalTimeZone ? 'browser-local-fallback' : 'utc-fallback'),
};
"""
        )

        if not isinstance(payload, dict):
            raise TradingViewSyncError(
                "TradingView sync could not detect the active chart timezone context."
            )

        local_system_timezone = str(payload.get("localSystemTimeZone") or DEFAULT_CHART_TIME_ZONE)
        explicit_chart_timezone_raw = payload.get("explicitChartTimeZone")
        explicit_chart_timezone = (
            str(explicit_chart_timezone_raw)
            if isinstance(explicit_chart_timezone_raw, str) and explicit_chart_timezone_raw
            else None
        )
        effective_chart_timezone = _normalize_chart_time_zone(
            str(payload.get("effectiveChartTimeZone") or local_system_timezone)
        )
        timezone_source = str(payload.get("timezoneSource") or "utc-fallback")
        return TradingViewChartTimeContext(
            local_system_timezone=local_system_timezone,
            explicit_chart_timezone=explicit_chart_timezone,
            effective_chart_timezone=effective_chart_timezone,
            timezone_source=timezone_source,
        )


def _parse_sync_request(payload: dict[str, object]) -> TradingViewSyncRequest:
    market_contract_raw = payload.get("market_contract")
    review_structure_raw = payload.get("review_structure")

    if not isinstance(market_contract_raw, dict):
        raise InvalidTradingViewSyncRequestError("market_contract must be an object.")
    if not isinstance(review_structure_raw, dict):
        raise InvalidTradingViewSyncRequestError("review_structure must be an object.")

    market_contract = TradingViewMarketContract(
        tradingview_symbol=_require_text(
            market_contract_raw, "tradingview_symbol", "market_contract"
        ),
        timeframe=_require_text(market_contract_raw, "timeframe", "market_contract"),
    )
    if market_contract.timeframe != "1H":
        raise InvalidTradingViewSyncRequestError(
            "TradingView sync currently supports 1H structures only."
        )

    review_structure = TradingViewReviewStructure(
        structure_id=_require_text(review_structure_raw, "structure_id", "review_structure"),
        direction=_require_text(review_structure_raw, "direction", "review_structure"),
        parent_anchor_source_timestamp=_require_text(
            review_structure_raw,
            "parent_anchor_source_timestamp",
            "review_structure",
        ),
        parent_anchor_price=_require_float(
            review_structure_raw, "parent_anchor_price", "review_structure"
        ),
        parent_anchor_kind=_require_text(
            review_structure_raw, "parent_anchor_kind", "review_structure"
        ),
        terminal_extreme_source_timestamp=_require_text(
            review_structure_raw,
            "terminal_extreme_source_timestamp",
            "review_structure",
        ),
        terminal_extreme_price=_require_float(
            review_structure_raw, "terminal_extreme_price", "review_structure"
        ),
        terminal_extreme_kind=_require_text(
            review_structure_raw, "terminal_extreme_kind", "review_structure"
        ),
    )

    return TradingViewSyncRequest(
        market_contract=market_contract,
        review_structure=review_structure,
        keep_browser_open=_parse_optional_bool(payload, "keep_browser_open"),
        preserve_review_context=_parse_optional_bool(payload, "preserve_review_context"),
    )


def _require_text(payload: dict[str, object], key: str, scope: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or value == "":
        raise InvalidTradingViewSyncRequestError(
            f"{scope}.{key} must be a non-empty string."
        )
    return value


def _require_float(payload: dict[str, object], key: str, scope: str) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)):
        raise InvalidTradingViewSyncRequestError(f"{scope}.{key} must be numeric.")
    return float(value)


def _parse_optional_bool(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise InvalidTradingViewSyncRequestError(f"{key} must be a boolean.")
    return value


def _chart_interval_for_timeframe(timeframe: str) -> str:
    if timeframe == "1H":
        return "60"
    raise TradingViewSyncError(
        f"TradingView sync does not support chart interval mapping for {timeframe}."
    )


def _build_render_verification(
    *,
    request: TradingViewSyncRequest,
    restored_state: dict[str, object] | None,
    chart_time_zone: str | None = None,
) -> dict[str, object]:
    if not isinstance(restored_state, dict):
        raise TradingViewSyncError(
            "TradingView sync could not read back the rendered fib state from the chart."
        )

    if restored_state.get("type") != "LineToolFibRetracement":
        raise TradingViewSyncError(
            "TradingView sync rendered a drawing, but it was not a fib retracement."
        )

    restored_points = restored_state.get("points")
    if not isinstance(restored_points, list) or len(restored_points) != 2:
        raise TradingViewSyncError(
            "TradingView sync could not verify the rendered fib anchor pair on the chart."
        )

    expected_points = _build_expected_line_tool_points(
        request,
        chart_time_zone=chart_time_zone,
    )
    for expected_point, restored_point in zip(expected_points, restored_points):
        if not isinstance(restored_point, dict):
            raise TradingViewSyncError(
                "TradingView sync returned an invalid rendered fib point from the chart."
            )

        expected_price = expected_point["price"]
        if not isinstance(expected_price, (int, float)):
            raise TradingViewSyncError(
                "TradingView sync produced an invalid expected fib anchor price."
            )

        restored_time = restored_point.get("time_t")
        restored_price = restored_point.get("price")
        restored_interval = restored_point.get("interval")
        if not isinstance(restored_time, (int, float)) or not isinstance(
            restored_price, (int, float)
        ):
            raise TradingViewSyncError(
                "TradingView sync returned an invalid rendered fib point payload from the chart."
            )

        if (
            int(restored_time) != expected_point["time_t"]
            or str(restored_interval) != expected_point["interval"]
            or not math.isclose(
                float(restored_price),
                float(expected_price),
                rel_tol=0.0,
                abs_tol=1e-9,
            )
        ):
            raise TradingViewSyncError(
                "TradingView sync did not render the DB1 fib on the exact detected anchors."
            )

    return {
        "verified": True,
        "chart_time_zone": chart_time_zone or DEFAULT_CHART_TIME_ZONE,
        "direction": request.review_structure.direction,
        "parent_anchor_kind": request.review_structure.parent_anchor_kind,
        "parent_anchor_source_timestamp": request.review_structure.parent_anchor_source_timestamp,
        "parent_anchor_price": request.review_structure.parent_anchor_price,
        "terminal_extreme_kind": request.review_structure.terminal_extreme_kind,
        "terminal_extreme_source_timestamp": request.review_structure.terminal_extreme_source_timestamp,
        "terminal_extreme_price": request.review_structure.terminal_extreme_price,
    }


def _build_request_key(request: TradingViewSyncRequest) -> tuple[str, str, str]:
    return (
        request.market_contract.tradingview_symbol,
        request.market_contract.timeframe,
        request.review_structure.structure_id,
    )


def _build_proposed_anchor_pair(request: TradingViewSyncRequest) -> dict[str, object]:
    return {
        "parent_anchor_source_timestamp": request.review_structure.parent_anchor_source_timestamp,
        "parent_anchor_price": request.review_structure.parent_anchor_price,
        "terminal_extreme_source_timestamp": request.review_structure.terminal_extreme_source_timestamp,
        "terminal_extreme_price": request.review_structure.terminal_extreme_price,
    }


def _build_anchor_pair_from_line_tool_state(
    restored_state: dict[str, object] | None,
    *,
    chart_time_zone: str,
) -> dict[str, object] | None:
    if not isinstance(restored_state, dict):
        return None

    restored_points = restored_state.get("points")
    if not isinstance(restored_points, list) or len(restored_points) != 2:
        return None

    anchor_values: list[tuple[str, float]] = []
    for point in restored_points:
        if not isinstance(point, dict):
            return None
        time_value = point.get("time_t")
        price_value = point.get("price")
        if not isinstance(time_value, (int, float)) or not isinstance(
            price_value, (int, float)
        ):
            return None
        anchor_values.append(
            (
                _epoch_seconds_to_source_timestamp(
                    int(time_value),
                    chart_time_zone=chart_time_zone,
                ),
                float(price_value),
            )
        )

    return {
        "parent_anchor_source_timestamp": anchor_values[0][0],
        "parent_anchor_price": anchor_values[0][1],
        "terminal_extreme_source_timestamp": anchor_values[1][0],
        "terminal_extreme_price": anchor_values[1][1],
    }


def _anchor_pairs_match(
    left: dict[str, object],
    right: dict[str, object],
) -> bool:
    left_parent_price = _coerce_float(left.get("parent_anchor_price"))
    right_parent_price = _coerce_float(right.get("parent_anchor_price"))
    left_terminal_price = _coerce_float(left.get("terminal_extreme_price"))
    right_terminal_price = _coerce_float(right.get("terminal_extreme_price"))
    if (
        left_parent_price is None
        or right_parent_price is None
        or left_terminal_price is None
        or right_terminal_price is None
    ):
        return False

    return (
        str(left.get("parent_anchor_source_timestamp"))
        == str(right.get("parent_anchor_source_timestamp"))
        and math.isclose(
            left_parent_price,
            right_parent_price,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        and str(left.get("terminal_extreme_source_timestamp"))
        == str(right.get("terminal_extreme_source_timestamp"))
        and math.isclose(
            left_terminal_price,
            right_terminal_price,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    )


def _coerce_float(value: object) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return float(value)


def _build_expected_line_tool_points(
    request: TradingViewSyncRequest,
    chart_time_zone: str | None = None,
) -> list[dict[str, object]]:
    chart_interval = _chart_interval_for_timeframe(request.market_contract.timeframe)
    return [
        {
            "interval": chart_interval,
            "offset": 0,
            "price": request.review_structure.parent_anchor_price,
            "time_t": _source_timestamp_to_epoch_seconds(
                request.review_structure.parent_anchor_source_timestamp,
                chart_time_zone=chart_time_zone,
            ),
        },
        {
            "interval": chart_interval,
            "offset": 0,
            "price": request.review_structure.terminal_extreme_price,
            "time_t": _source_timestamp_to_epoch_seconds(
                request.review_structure.terminal_extreme_source_timestamp,
                chart_time_zone=chart_time_zone,
            ),
        },
    ]


def _source_timestamp_to_epoch_seconds(
    source_timestamp: str,
    *,
    chart_time_zone: str | None = None,
) -> int:
    try:
        parsed = datetime.fromisoformat(source_timestamp)
    except ValueError as error:
        raise TradingViewSyncError(
            f"TradingView sync received an invalid source timestamp {source_timestamp}."
        ) from error

    if parsed.tzinfo is None and chart_time_zone is not None:
        parsed = parsed.replace(tzinfo=ZoneInfo(_normalize_chart_time_zone(chart_time_zone)))
    elif parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return int(parsed.timestamp())


def _epoch_seconds_to_source_timestamp(
    epoch_seconds: int,
    *,
    chart_time_zone: str,
) -> str:
    timestamp = datetime.fromtimestamp(
        epoch_seconds,
        tz=ZoneInfo(_normalize_chart_time_zone(chart_time_zone)),
    )
    return timestamp.replace(tzinfo=None).isoformat(timespec="seconds")


def _normalize_chart_time_zone(chart_time_zone: str) -> str:
    try:
        ZoneInfo(chart_time_zone)
    except ZoneInfoNotFoundError:
        return DEFAULT_CHART_TIME_ZONE
    return chart_time_zone


def _build_review_fib_state(
    *,
    market_symbol: str,
    chart_interval: str,
    review_style: TradingViewReviewStyle = DEFAULT_REVIEW_FIB_STYLE,
) -> dict[str, object]:
    visible_levels = frozenset(review_style.visible_levels)
    state: dict[str, object] = {
        "symbol": market_symbol,
        "interval": chart_interval,
        "reverse": False,
        "showCoeffs": True,
        "showPrices": True,
        "showText": True,
        "fillBackground": False,
        "transparency": 100,
        "extendLines": False,
        "extendLinesLeft": False,
        "horzLabelsAlign": "left",
        "vertLabelsAlign": "middle",
        "horzTextAlign": "center",
        "vertTextAlign": "middle",
        "coeffsAsPercents": False,
        "fibLevelsBasedOnLogScale": False,
        "labelFontSize": 12,
        "levelsStyle": {
            "linestyle": 0,
            "linewidth": 2,
        },
        "trendline": {
            "color": review_style.line_color,
            "linestyle": 0,
            "linewidth": 2,
            "visible": True,
        },
    }

    for index, level_value in enumerate(REVIEW_FIB_LEVEL_SEQUENCE, start=1):
        state[f"level{index}"] = [
            level_value,
            review_style.line_color,
            level_value in visible_levels,
            "",
        ]

    return state