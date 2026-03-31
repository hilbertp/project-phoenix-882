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
            "chart_theme": {
                "mode": (
                    "platform-default"
                    if payload.get("use_tradingview_defaults")
                    else "dark"
                ),
                "implementation": (
                    "tradingview-default"
                    if payload.get("use_tradingview_defaults")
                    else "preload-theme-bootstrap-plus-chart-properties"
                ),
            },
            "chart_time_alignment": {
                "local_system_timezone": "Asia/Nicosia",
                "explicit_chart_timezone": None,
                "effective_chart_timezone": "Asia/Nicosia",
                "timezone_source": "browser-local-fallback",
            },
            "market_symbol": "BITGET:BTCUSDT.P",
            "timeframe": "1H",
            "structure_id": "db1-fib-0001",
            "placed_tool": "LineToolFibRetracement",
            "chart_title": "BTCUSDT.P proof",
            "review_style": {
                "mode": (
                    "tradingview-default"
                    if payload.get("use_tradingview_defaults")
                    else "review-custom"
                ),
                "line_color": None if payload.get("use_tradingview_defaults") else "#FFFFFF",
                "visible_levels": None if payload.get("use_tradingview_defaults") else [1.0, 0.941, 0.882, 0.786, 0.618, 0.5, 0.382, 0.236, 0.0],
            },
            "review_tool": {
                "source": "proposal-render",
                "reused_existing_tool": False,
                "selected_for_editing": True,
                "selection_count": 1,
                "matches_proposed_anchors": True,
                "anchor_pair": {
                    "parent_anchor_source_timestamp": "2025-12-31T10:00:00",
                    "parent_anchor_price": 88350.7,
                    "terminal_extreme_source_timestamp": "2025-12-31T16:00:00",
                    "terminal_extreme_price": 89180.8,
                },
            },
        }


class FailingTradingViewSyncService:
    def sync_structure(self, payload: dict[str, object]) -> dict[str, object]:
        raise TradingViewSyncError("TradingView sync did not create a fib retracement drawing on the chart.")


def _sync_payload() -> dict[str, object]:
    return {
        "keep_browser_open": True,
        "preserve_review_context": True,
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
        self.assertEqual(payload["chart_theme"]["mode"], "dark")
        self.assertEqual(
            payload["chart_theme"]["implementation"],
            "preload-theme-bootstrap-plus-chart-properties",
        )
        self.assertEqual(
            payload["chart_time_alignment"]["effective_chart_timezone"],
            "Asia/Nicosia",
        )
        self.assertEqual(payload["review_style"]["line_color"], "#FFFFFF")
        self.assertEqual(payload["review_style"]["mode"], "review-custom")
        self.assertEqual(payload["review_tool"]["source"], "proposal-render")
        self.assertIs(payload["review_tool"]["selected_for_editing"], True)
        self.assertEqual(payload["review_tool"]["selection_count"], 1)
        self.assertEqual(len(fake_service.payloads), 1)
        self.assertIs(fake_service.payloads[0]["keep_browser_open"], True)
        self.assertIs(fake_service.payloads[0]["preserve_review_context"], True)

    def test_post_tradingview_sync_accepts_tradingview_default_mode(self) -> None:
        fake_service = FakeTradingViewSyncService()
        sync_payload = _sync_payload()
        sync_payload["use_tradingview_defaults"] = True
        with tempfile.TemporaryDirectory() as temp_dir:
            server, thread = _start_server(Path(temp_dir), fake_service)
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/db1/review/tradingview/sync",
                    data=json.dumps(sync_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                _stop_server(server, thread)

        self.assertEqual(payload["chart_theme"]["mode"], "platform-default")
        self.assertEqual(payload["chart_theme"]["implementation"], "tradingview-default")
        self.assertEqual(payload["review_style"]["mode"], "tradingview-default")
        self.assertIsNone(payload["review_style"]["line_color"])
        self.assertIsNone(payload["review_style"]["visible_levels"])
        self.assertIs(fake_service.payloads[0]["use_tradingview_defaults"], True)

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