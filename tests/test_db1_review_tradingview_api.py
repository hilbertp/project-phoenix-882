from __future__ import annotations

import json
import tempfile
import threading
from typing import Any, cast
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from apps.api.db1_review_read.http_app import create_server
from apps.api.db1_review_tradingview.service import TradingViewSyncError


class FakeTradingViewSyncService:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def sync_structure(self, payload: dict[str, object]) -> dict[str, object]:
        self.payloads.append(payload)
        return {
            "status": "ok",
            "chart_url": "https://www.tradingview.com/chart/?symbol=BITGET%3ABTCUSDT.P",
            "market_symbol": "BITGET:BTCUSDT.P",
            "timeframe": "1H",
            "structure_id": "db1-fib-0001",
            "placed_tool": "LineToolFibRetracement",
            "chart_title": "BTCUSDT.P proof",
        }


class FailingTradingViewSyncService:
    def sync_structure(self, payload: dict[str, object]) -> dict[str, object]:
        raise TradingViewSyncError("TradingView sync did not create a fib retracement drawing on the chart.")


def _sync_payload() -> dict[str, object]:
    return {
        "market_contract": {
            "tradingview_symbol": "BITGET:BTCUSDT.P",
            "timeframe": "1H",
        },
        "review_structure": {
            "structure_id": "db1-fib-0001",
            "direction": "up",
            "parent_anchor_source_timestamp": "2025-12-31T10:00:00",
            "parent_anchor_price": 88350.7,
            "parent_anchor_kind": "low",
            "terminal_extreme_source_timestamp": "2025-12-31T16:00:00",
            "terminal_extreme_price": 89180.8,
            "terminal_extreme_kind": "high",
        },
    }


class DB1ReviewTradingViewApiTests(unittest.TestCase):
    def test_post_tradingview_sync_returns_accepted_response(self) -> None:
        fake_service = FakeTradingViewSyncService()
        with tempfile.TemporaryDirectory() as temp_dir:
            server, thread = _start_server(Path(temp_dir), fake_service)
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/db1/review/tradingview/sync",
                    data=json.dumps(_sync_payload()).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                _stop_server(server, thread)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["placed_tool"], "LineToolFibRetracement")
        self.assertEqual(len(fake_service.payloads), 1)

    def test_post_tradingview_sync_rejects_non_object_payload(self) -> None:
        fake_service = FakeTradingViewSyncService()
        with tempfile.TemporaryDirectory() as temp_dir:
            server, thread = _start_server(Path(temp_dir), fake_service)
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/db1/review/tradingview/sync",
                    data=json.dumps(["not-an-object"]).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as error_context:
                    urlopen(request)
            finally:
                _stop_server(server, thread)

        self.assertEqual(error_context.exception.code, 400)

    def test_post_tradingview_sync_returns_internal_error_when_helper_fails(self) -> None:
        failing_service = FailingTradingViewSyncService()
        with tempfile.TemporaryDirectory() as temp_dir:
            server, thread = _start_server(Path(temp_dir), failing_service)
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/db1/review/tradingview/sync",
                    data=json.dumps(_sync_payload()).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as error_context:
                    urlopen(request)
            finally:
                _stop_server(server, thread)

        self.assertEqual(error_context.exception.code, 500)


def _start_server(
    artifacts_dir: Path,
    fake_service: object,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = create_server(
        host="127.0.0.1",
        port=0,
        artifacts_dir=artifacts_dir,
        tradingview_sync_service=cast(Any, fake_service),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server: ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


if __name__ == "__main__":
    unittest.main()