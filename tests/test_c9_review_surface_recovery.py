from __future__ import annotations

import json
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from typing import Any, cast
import unittest
from urllib.parse import parse_qs, urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


UI_DIR = Path(__file__).resolve().parents[1] / "apps" / "ui"
CHROME_BINARY = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class ReviewSurfaceRecoveryTests(unittest.TestCase):
    def test_retry_path_recovers_current_structure_after_sync_failure(self) -> None:
        api_state = FakeReviewApiState(fail_first_sync_for={"db1-fib-0001"})
        with running_review_servers(api_state) as urls:
            driver = _create_driver(urls.api_base_url)
            try:
                wait = WebDriverWait(driver, 60)
                driver.get(urls.ui_url)

                tradingview_status = wait.until(
                    EC.presence_of_element_located((By.ID, "tradingview-status"))
                )
                review_lock_reason = wait.until(
                    EC.presence_of_element_located((By.ID, "review-lock-reason"))
                )
                sync_button = wait.until(
                    EC.presence_of_element_located((By.ID, "sync-chart-button"))
                )
                okay_button = wait.until(
                    EC.presence_of_element_located((By.ID, "good-enough-button"))
                )

                wait.until(lambda browser: "TradingView sync failed:" in tradingview_status.text)
                self.assertEqual(sync_button.text.strip(), "retry TradingView sync")
                self.assertIn("Retry TradingView sync", review_lock_reason.text)
                self.assertFalse(okay_button.is_enabled())

                sync_button.click()

                wait.until(
                    lambda browser: "TradingView synced for db1-fib-0001" in tradingview_status.text
                )
                wait.until(lambda browser: okay_button.is_enabled())
                self.assertEqual(sync_button.text.strip(), "sync TradingView")
                self.assertEqual(
                    review_lock_reason.text.strip(),
                    "Review actions enabled for the current structure.",
                )
                self.assertEqual(api_state.sync_attempts["db1-fib-0001"], 2)
            finally:
                driver.quit()

    def test_refresh_restores_current_structure_view_state(self) -> None:
        api_state = FakeReviewApiState()
        with running_review_servers(api_state) as urls:
            driver = _create_driver(urls.api_base_url)
            try:
                wait = WebDriverWait(driver, 60)
                driver.get(urls.ui_url)

                okay_button = wait.until(
                    EC.presence_of_element_located((By.ID, "good-enough-button"))
                )
                note_input = wait.until(
                    EC.presence_of_element_located((By.ID, "review-note-input"))
                )
                progress_label = wait.until(
                    EC.presence_of_element_located((By.ID, "progress-label"))
                )
                tradingview_status = wait.until(
                    EC.presence_of_element_located((By.ID, "tradingview-status"))
                )

                wait.until(lambda browser: okay_button.is_enabled())
                okay_button.click()

                wait.until(
                    lambda browser: browser.find_element(By.ID, "progress-label").text.strip()
                    == "structure 2 of 2"
                )
                wait.until(
                    lambda browser: "TradingView synced for db1-fib-0002"
                    in browser.find_element(By.ID, "tradingview-status").text
                )

                previous_button = wait.until(
                    EC.element_to_be_clickable((By.ID, "show-previous-button"))
                )
                previous_button.click()
                note_input.clear()
                note_input.send_keys("resume after refresh")

                driver.refresh()

                wait.until(
                    lambda browser: browser.find_element(By.ID, "progress-label").text.strip()
                    == "structure 2 of 2"
                )
                wait.until(
                    lambda browser: "TradingView synced for db1-fib-0002"
                    in browser.find_element(By.ID, "tradingview-status").text
                )

                viewing_label = wait.until(EC.presence_of_element_located((By.ID, "viewing-label")))
                note_input = wait.until(EC.presence_of_element_located((By.ID, "review-note-input")))
                self.assertEqual(viewing_label.text.strip(), "previous")
                self.assertEqual(note_input.get_attribute("value"), "resume after refresh")
                self.assertGreaterEqual(api_state.sync_attempts["db1-fib-0002"], 2)
            finally:
                driver.quit()


class FakeReviewApiState:
    def __init__(self, fail_first_sync_for: set[str] | None = None) -> None:
        self.fail_first_sync_for = fail_first_sync_for or set()
        self.sync_attempts: dict[str, int] = {}
        self.submissions: list[dict[str, object]] = []
        self.structures = [
            _structure_payload(
                structure_id="db1-fib-0001",
                current_position=1,
                total_structures=2,
                previous_structure=None,
            ),
            _structure_payload(
                structure_id="db1-fib-0002",
                current_position=2,
                total_structures=2,
                previous_structure=_structure(
                    structure_id="db1-fib-0001-prev",
                    direction="up",
                    parent_anchor_source_timestamp="2026-03-01T08:00:00",
                    terminal_extreme_source_timestamp="2026-03-01T12:00:00",
                ),
            ),
        ]

    def structure_for_position(self, position: int) -> dict[str, object]:
        if position < 1 or position > len(self.structures):
            raise KeyError(position)
        return self.structures[position - 1]

    def summary_payload(self) -> dict[str, object]:
        total_reviewed = len(self.submissions)
        good_enough = sum(1 for item in self.submissions if item.get("review_outcome") == "good_enough")
        adjusted_accept = sum(
            1 for item in self.submissions if item.get("review_outcome") == "adjusted_accept"
        )
        flatout_wrong = sum(
            1 for item in self.submissions if item.get("review_outcome") == "flatout_wrong"
        )
        positive_count = good_enough + adjusted_accept
        positive_share = positive_count / total_reviewed if total_reviewed else 0.0
        return {
            "summary": {
                "total_reviewed_structures": total_reviewed,
                "good_enough_count": good_enough,
                "adjusted_accept_count": adjusted_accept,
                "flatout_wrong_count": flatout_wrong,
                "combined_positive_share": positive_share,
                "readiness_hint": "refine once",
            },
            "wrong_case_reason_counts": [],
        }

    def submit(self, payload: dict[str, object]) -> dict[str, object]:
        self.submissions.append(payload)
        return {
            "status": "recorded",
            "structure_id": payload.get("structure_id"),
            "review_outcome": payload.get("review_outcome"),
        }

    def sync(self, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        review_structure = payload.get("review_structure")
        if not isinstance(review_structure, dict):
            return HTTPStatus.BAD_REQUEST, {"error": "review_structure must be an object."}

        structure_id = str(review_structure.get("structure_id"))
        attempts = self.sync_attempts.get(structure_id, 0) + 1
        self.sync_attempts[structure_id] = attempts
        if structure_id in self.fail_first_sync_for and attempts == 1:
            return HTTPStatus.INTERNAL_SERVER_ERROR, {
                "error": "TradingView sync did not create a fib retracement drawing on the chart.",
            }

        return HTTPStatus.ACCEPTED, {
            "status": "ok",
            "market_symbol": "BITGET:BTCUSDT.P",
            "timeframe": "1H",
            "structure_id": structure_id,
            "placed_tool": "LineToolFibRetracement",
            "chart_title": "BTCUSDT.P proof",
        }


class SimpleReviewApiHandler(SimpleHTTPRequestHandler):
    def __init__(self, api_state: FakeReviewApiState, *args: Any, **kwargs: Any) -> None:
        self._api_state = api_state
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/db1/review/structures":
            try:
                position = int(parse_qs(parsed.query).get("position", ["1"])[0])
                payload = self._api_state.structure_for_position(position)
            except (KeyError, ValueError):
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "Structure not found."})
                return

            self._write_json(HTTPStatus.OK, payload)
            return

        if parsed.path == "/db1/review/summary":
            self._write_json(HTTPStatus.OK, self._api_state.summary_payload())
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length) if content_length else b"{}"
        payload = json.loads(body.decode("utf-8"))

        if parsed.path == "/db1/review/tradingview/sync":
            status, response_payload = self._api_state.sync(payload)
            self._write_json(status, response_payload)
            return

        if parsed.path == "/db1/review/submissions":
            self._write_json(HTTPStatus.ACCEPTED, self._api_state.submit(payload))
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _write_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ServerUrls:
    def __init__(self, api_base_url: str, ui_url: str) -> None:
        self.api_base_url = api_base_url
        self.ui_url = ui_url


class running_review_servers:
    def __init__(self, api_state: FakeReviewApiState) -> None:
        self._api_state = api_state
        self._servers: list[ThreadingHTTPServer] = []
        self._threads: list[threading.Thread] = []

    def __enter__(self) -> ServerUrls:
        api_handler = partial(SimpleReviewApiHandler, self._api_state)
        api_server = ThreadingHTTPServer(("127.0.0.1", 0), api_handler)
        ui_handler = partial(SimpleHTTPRequestHandler, directory=str(UI_DIR))
        ui_server = ThreadingHTTPServer(("127.0.0.1", 0), ui_handler)

        self._start(api_server)
        self._start(ui_server)

        return ServerUrls(
            api_base_url=f"http://127.0.0.1:{api_server.server_port}",
            ui_url=f"http://127.0.0.1:{ui_server.server_port}/index.html",
        )

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        for server in self._servers:
            server.shutdown()
        for thread in self._threads:
            thread.join(timeout=2)
        for server in self._servers:
            server.server_close()

    def _start(self, server: ThreadingHTTPServer) -> None:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._servers.append(server)
        self._threads.append(thread)


def _create_driver(api_base_url: str) -> Any:
    options = Options()
    options.binary_location = CHROME_BINARY
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,1200")
    options.add_argument("--no-sandbox")
    driver = cast(Any, webdriver).Chrome(options=options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": (
                "window.DB1_REVIEW_API_BASE_URL = "
                + json.dumps(api_base_url)
                + ";"
            )
        },
    )
    return driver


def _structure_payload(
    *,
    structure_id: str,
    current_position: int,
    total_structures: int,
    previous_structure: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "market_contract": {
            "human_label": "BTCUSDT.P on Bitget",
            "tradingview_symbol": "BITGET:BTCUSDT.P",
            "instrument_label": "BTCUSDTPERP PERPETUAL MIX CONTRACT",
            "timeframe": "1H",
        },
        "progress": {
            "label": f"structure {current_position} of {total_structures}",
            "current_position": current_position,
            "total_structures": total_structures,
        },
        "current_structure": _structure(
            structure_id=structure_id,
            direction="up",
            parent_anchor_source_timestamp="2026-03-02T08:00:00",
            terminal_extreme_source_timestamp="2026-03-02T12:00:00",
        ),
        "previous_structure": previous_structure,
    }


def _structure(
    *,
    structure_id: str,
    direction: str,
    parent_anchor_source_timestamp: str,
    terminal_extreme_source_timestamp: str,
) -> dict[str, object]:
    return {
        "structure_id": structure_id,
        "direction": direction,
        "parent_anchor_kind": "low",
        "parent_anchor_price": 88350.7,
        "parent_anchor_source_timestamp": parent_anchor_source_timestamp,
        "terminal_extreme_kind": "high",
        "terminal_extreme_price": 89180.8,
        "terminal_extreme_source_timestamp": terminal_extreme_source_timestamp,
        "anchor_range_low": 88350.7,
        "anchor_range_high": 89180.8,
        "invalidation_reason": None,
    }


if __name__ == "__main__":
    unittest.main()