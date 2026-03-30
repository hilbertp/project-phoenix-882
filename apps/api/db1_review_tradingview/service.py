from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
from threading import Lock
import time
from typing import Any, cast
from urllib.parse import quote

DEFAULT_CHROME_BINARY = Path(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
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


class DB1TradingViewSyncService:
    def __init__(self, chrome_binary: Path = DEFAULT_CHROME_BINARY) -> None:
        self._chrome_binary = chrome_binary
        self._lock = Lock()

    def sync_structure(self, payload: dict[str, object]) -> dict[str, object]:
        request = _parse_sync_request(payload)
        with self._lock:
            driver = self._create_driver()
            try:
                return self._sync_in_browser(driver, request)
            except TradingViewSyncError:
                raise
            except Exception as error:
                raise TradingViewSyncError(
                    "TradingView sync failed during browser automation."
                ) from error
            finally:
                self._close_driver(driver)

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
            driver.get(chart_url)
            driver.execute_cdp_cmd("Page.bringToFront", {})

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
        except TimeoutException as error:
            raise TradingViewSyncError(
                "TradingView sync could not reach the required chart controls."
            ) from error

        focus_payload = driver.execute_script(
            """
const marketContract = arguments[0];
const reviewStructure = arguments[1];
const chartInterval = arguments[2];
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
function resolvePoint(sourceTimestamp, price) {
  const epochSeconds = Date.parse(sourceTimestamp + 'Z') / 1000;
    const exact = barRows.find((row) => row.epochSeconds === epochSeconds);
    if (!exact) {
        throw new Error('TradingView chart does not contain an exact 1H bar for ' + sourceTimestamp + '.');
    }
    return {
        index: exact.index,
        interval: chartInterval,
        offset: 0,
        price,
        time_t: epochSeconds,
    };
}
const parentPoint = resolvePoint(reviewStructure.parent_anchor_source_timestamp, reviewStructure.parent_anchor_price);
const terminalPoint = resolvePoint(reviewStructure.terminal_extreme_source_timestamp, reviewStructure.terminal_extreme_price);
const fromIndex = Math.min(parentPoint.index, terminalPoint.index) - 16;
const toIndex = Math.max(parentPoint.index, terminalPoint.index) + 16;
model.timeScale().zoomToBarsRange(fromIndex, toIndex);
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
const target = chartModel.lineBeingCreated() || line;
chartModel.restoreLineToolState(
        target,
        {
                type: 'LineToolFibRetracement',
                points: [parentPoint, terminalPoint],
                state: {
                        symbol: marketContract.tradingview_symbol,
                        interval: chartInterval,
                        reverse: false,
                        showCoeffs: true,
                        showPrices: true,
                        showText: true,
                },
                zorder: -15000,
        },
        false,
);
chartModel.finishLineTool(target);
return {
  chartTitle: document.title,
  interval: String(model.mainSeries().interval()),
  marketSymbol: marketContract.tradingview_symbol,
  fromIndex,
  toIndex,
    parentPoint,
    terminalPoint,
    restoredState: target && target.state ? target.state() : null,
    targetType: target && target.toolname ? target.toolname : null,
};
""",
            {
                "tradingview_symbol": request.market_contract.tradingview_symbol,
                "timeframe": request.market_contract.timeframe,
            },
            {
                "parent_anchor_source_timestamp": request.review_structure.parent_anchor_source_timestamp,
                "parent_anchor_price": request.review_structure.parent_anchor_price,
                "terminal_extreme_source_timestamp": request.review_structure.terminal_extreme_source_timestamp,
                "terminal_extreme_price": request.review_structure.terminal_extreme_price,
            },
            _chart_interval_for_timeframe(request.market_contract.timeframe),
        )
        driver.execute_cdp_cmd("Page.bringToFront", {})

        if focus_payload["targetType"] != "LineToolFibRetracement":
            raise TradingViewSyncError(
                "TradingView sync did not create a fib retracement drawing on the chart."
            )

        render_verification = _build_render_verification(
            request=request,
            restored_state=focus_payload["restoredState"],
        )

        return {
            "status": "ok",
            "chart_url": chart_url,
            "market_symbol": request.market_contract.tradingview_symbol,
            "timeframe": request.market_contract.timeframe,
            "structure_id": request.review_structure.structure_id,
            "placed_tool": focus_payload["targetType"],
            "chart_title": focus_payload["chartTitle"],
            "render_verification": render_verification,
        }


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

    expected_points = _build_expected_line_tool_points(request)
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
        "direction": request.review_structure.direction,
        "parent_anchor_kind": request.review_structure.parent_anchor_kind,
        "parent_anchor_source_timestamp": request.review_structure.parent_anchor_source_timestamp,
        "parent_anchor_price": request.review_structure.parent_anchor_price,
        "terminal_extreme_kind": request.review_structure.terminal_extreme_kind,
        "terminal_extreme_source_timestamp": request.review_structure.terminal_extreme_source_timestamp,
        "terminal_extreme_price": request.review_structure.terminal_extreme_price,
    }


def _build_expected_line_tool_points(
    request: TradingViewSyncRequest,
) -> list[dict[str, object]]:
    chart_interval = _chart_interval_for_timeframe(request.market_contract.timeframe)
    return [
        {
            "interval": chart_interval,
            "offset": 0,
            "price": request.review_structure.parent_anchor_price,
            "time_t": _source_timestamp_to_epoch_seconds(
                request.review_structure.parent_anchor_source_timestamp
            ),
        },
        {
            "interval": chart_interval,
            "offset": 0,
            "price": request.review_structure.terminal_extreme_price,
            "time_t": _source_timestamp_to_epoch_seconds(
                request.review_structure.terminal_extreme_source_timestamp
            ),
        },
    ]


def _source_timestamp_to_epoch_seconds(source_timestamp: str) -> int:
    try:
        parsed = datetime.fromisoformat(source_timestamp)
    except ValueError as error:
        raise TradingViewSyncError(
            f"TradingView sync received an invalid source timestamp {source_timestamp}."
        ) from error

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return int(parsed.timestamp())