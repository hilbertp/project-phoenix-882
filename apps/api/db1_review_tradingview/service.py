from __future__ import annotations

from dataclasses import dataclass
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
    parent_anchor_source_timestamp: str
    parent_anchor_price: float
    terminal_extreme_source_timestamp: str
    terminal_extreme_price: float


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
const c = window._exposed_chartWidgetCollection;
if (!c) {
  throw new Error('TradingView chart widget collection is unavailable.');
}
const model = c._activeChartWidgetModel.value();
if (String(model.mainSeries().interval()) !== '60') {
  throw new Error('TradingView chart did not apply the 1H interval.');
}
const bars = model.mainSeries().data();
const firstBar = bars.first();
if (!firstBar) {
  throw new Error('TradingView hourly bar data is unavailable.');
}
const firstEpoch = firstBar.value[0];
const firstIndex = firstBar.index;
function indexForSourceTimestamp(sourceTimestamp) {
  const epochSeconds = Date.parse(sourceTimestamp + 'Z') / 1000;
  const offsetHours = Math.round((epochSeconds - firstEpoch) / 3600);
  return firstIndex + offsetHours;
}
const parentIndex = indexForSourceTimestamp(reviewStructure.parent_anchor_source_timestamp);
const terminalIndex = indexForSourceTimestamp(reviewStructure.terminal_extreme_source_timestamp);
const fromIndex = Math.min(parentIndex, terminalIndex) - 16;
const toIndex = Math.max(parentIndex, terminalIndex) + 16;
model.timeScale().zoomToBarsRange(fromIndex, toIndex);
return {
  chartTitle: document.title,
  interval: String(model.mainSeries().interval()),
  buttonText: (document.querySelector('button[aria-label="Change interval"]')?.innerText || '').trim(),
  marketSymbol: marketContract.tradingview_symbol,
  fromIndex,
  toIndex,
  parentIndex,
  terminalIndex,
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
        )
        time.sleep(3)

        driver.execute_script(
            """
const c = window._exposed_chartWidgetCollection;
const model = c._activeChartWidgetModel.value();
model.removeAllDrawingTools();
"""
        )
        time.sleep(1)

        wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[aria-label="Fib retracement"]'))
        ).click()
        time.sleep(1)

        placement_payload = driver.execute_script(
            """
const reviewStructure = arguments[0];
const focusPayload = arguments[1];
const c = window._exposed_chartWidgetCollection;
const model = c._activeChartWidgetModel.value();
const pane = model.panes()[0];
const ts = model.timeScale();
const ps = pane.defaultPriceScale();
const firstValue = model.mainSeries().firstValue();
const canvas = document.querySelectorAll('canvas')[1];
if (!canvas) {
  throw new Error('TradingView chart canvas is unavailable.');
}
const rect = canvas.getBoundingClientRect();
const beforeIds = pane.dataSources().map((source) => source.id ? source.id() : null);
window.__db1SyncBeforeIds = beforeIds;
return {
  p1: {
    x: rect.left + ts.indexToCoordinate(focusPayload.parentIndex),
    y: rect.top + ps.priceToCoordinate(reviewStructure.parent_anchor_price, firstValue),
  },
  p2: {
    x: rect.left + ts.indexToCoordinate(focusPayload.terminalIndex),
    y: rect.top + ps.priceToCoordinate(reviewStructure.terminal_extreme_price, firstValue),
  },
};
""",
            {
                "parent_anchor_price": request.review_structure.parent_anchor_price,
                "terminal_extreme_price": request.review_structure.terminal_extreme_price,
            },
            focus_payload,
        )

        for point in (placement_payload["p1"], placement_payload["p2"]):
            self._click_point(driver, point)
            time.sleep(1)

        time.sleep(2)

        result = driver.execute_script(
            """
const c = window._exposed_chartWidgetCollection;
const model = c._activeChartWidgetModel.value();
const pane = model.panes()[0];
const beforeIds = window.__db1SyncBeforeIds || [];
const all = pane.dataSources();
const added = all.filter((source) => !beforeIds.includes(source.id ? source.id() : null));
const target = added.length ? added[added.length - 1] : null;
return {
  addedCount: added.length,
  interval: String(model.mainSeries().interval()),
  buttonText: (document.querySelector('button[aria-label="Change interval"]')?.innerText || '').trim(),
  chartTitle: document.title,
  targetType: target && target.toolname ? target.toolname : null,
};
"""
        )
        driver.execute_cdp_cmd("Page.bringToFront", {})

        if result["targetType"] != "LineToolFibRetracement":
            raise TradingViewSyncError(
                "TradingView sync did not create a fib retracement drawing on the chart."
            )

        return {
            "status": "ok",
            "chart_url": chart_url,
            "market_symbol": request.market_contract.tradingview_symbol,
            "timeframe": request.market_contract.timeframe,
            "structure_id": request.review_structure.structure_id,
            "placed_tool": result["targetType"],
            "chart_title": result["chartTitle"],
        }

    def _click_point(self, driver: Any, point: dict[str, float]) -> None:
        x = float(point["x"])
        y = float(point["y"])
        driver.execute_cdp_cmd(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": x,
                "y": y,
                "button": "none",
                "pointerType": "mouse",
            },
        )
        driver.execute_cdp_cmd(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
                "pointerType": "mouse",
            },
        )
        driver.execute_cdp_cmd(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
                "pointerType": "mouse",
            },
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
        parent_anchor_source_timestamp=_require_text(
            review_structure_raw,
            "parent_anchor_source_timestamp",
            "review_structure",
        ),
        parent_anchor_price=_require_float(
            review_structure_raw, "parent_anchor_price", "review_structure"
        ),
        terminal_extreme_source_timestamp=_require_text(
            review_structure_raw,
            "terminal_extreme_source_timestamp",
            "review_structure",
        ),
        terminal_extreme_price=_require_float(
            review_structure_raw, "terminal_extreme_price", "review_structure"
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