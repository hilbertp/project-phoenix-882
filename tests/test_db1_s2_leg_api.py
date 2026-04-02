from __future__ import annotations

import json
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
import unittest

from apps.api.db1_review_read.http_app import create_server


class FakeLegReadService:
    def get_candidate_leg_payload(self) -> dict[str, object]:
        return {
            "sub_bet": "DB1.S2",
            "title": "Candidate Leg Scoring",
            "market_contract": {
                "tradingview_symbol": "BITGET:BTCUSDT.P",
                "human_label": "BTCUSDT.P on Bitget",
                "instrument_label": "BTCUSDTPERP PERPETUAL MIX CONTRACT",
                "timeframe": "1H",
                "review_window": "last 3 months",
            },
            "detector": {
                "candidate_leg_rule": {"rule_name": "adjacent_alternating_pivot_pairs"},
                "scoring": {"dimensions": ["size", "cleanliness", "prominence", "dominance"]},
            },
            "summary": {
                "raw_pivot_count": 20,
                "alternating_pivot_count": 12,
                "candidate_leg_count": 11,
                "displayed_candidate_count": 2,
                "source_start_timestamp": "2026-01-01T00:00:00",
                "source_end_timestamp": "2026-01-02T00:00:00",
            },
            "source_provenance": {},
            "candles": [
                {"source_timestamp": "2026-01-01T00:00:00", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.4, "volume": 10.0}
            ],
            "raw_pivots": [
                {"index": 1, "kind": "low", "price": 0.5, "source_timestamp": "2026-01-01T01:00:00", "candle_low": 0.5, "candle_high": 1.5}
            ],
            "alternating_pivots": [
                {"index": 1, "kind": "low", "price": 0.5, "source_timestamp": "2026-01-01T01:00:00", "candle_low": 0.5, "candle_high": 1.5},
                {"index": 4, "kind": "high", "price": 2.5, "source_timestamp": "2026-01-01T04:00:00", "candle_low": 1.7, "candle_high": 2.5},
            ],
            "candidate_legs": [
                {
                    "candidate_id": "leg-1-4",
                    "rank": 1,
                    "score": 0.82,
                    "direction": "up",
                    "start_pivot": {"index": 1, "kind": "low", "price": 0.5, "source_timestamp": "2026-01-01T01:00:00"},
                    "end_pivot": {"index": 4, "kind": "high", "price": 2.5, "source_timestamp": "2026-01-01T04:00:00"},
                    "candle_span": 3,
                    "metrics": {
                        "size_score": 1.0,
                        "cleanliness_score": 0.7,
                        "prominence_score": 0.6,
                        "dominance_score": 0.8,
                        "size_points": 2.0,
                        "size_percent": 4.0,
                        "cleanliness_ratio": 0.7,
                        "prominence_points": 0.4,
                        "dominance_ratio": 1.3,
                    },
                }
            ],
        }


class FakeTradingViewPineReadService:
    def get_pine_review_payload(self) -> dict[str, object]:
        return {
            "sub_bet": "DB1.S2",
            "title": "TradingView-native candidate review lane",
            "artifact_filename": "db1_s2_candidate_leg_review_lane.pine",
            "indicator_title": "DB1.S2 Candidate Fib Review",
            "market_contract": {"tradingview_symbol": "BITGET:BTCUSDT.P", "timeframe": "1H"},
            "levels": [1.0, 0.941, 0.882, 0.786, 0.618, 0.5, 0.382, 0.236, 0.0],
            "displayed_candidate_count": 2,
            "candidate_summary": [
                {"candidate_id": "leg-1-4", "rank": 1, "direction": "up", "score": 0.82}
            ],
            "pine_script": "//@version=6\nindicator(\"DB1.S2 Candidate Fib Review\", overlay=true)",
        }


class DB1S2LegApiTests(unittest.TestCase):
    def test_get_candidate_legs_returns_ranked_leg_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server, thread = _start_server(
                Path(temp_dir),
                FakeLegReadService(),
                FakeTradingViewPineReadService(),
            )
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/db1/s2/candidate-legs") as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                _stop_server(server, thread)

        self.assertEqual(payload["sub_bet"], "DB1.S2")
        self.assertEqual(payload["candidate_legs"][0]["rank"], 1)
        self.assertEqual(payload["candidate_legs"][0]["direction"], "up")
        self.assertEqual(payload["detector"]["candidate_leg_rule"]["rule_name"], "adjacent_alternating_pivot_pairs")

    def test_get_tradingview_pine_returns_json_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server, thread = _start_server(
                Path(temp_dir),
                FakeLegReadService(),
                FakeTradingViewPineReadService(),
            )
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/db1/s2/tradingview-pine") as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                _stop_server(server, thread)

        self.assertEqual(payload["artifact_filename"], "db1_s2_candidate_leg_review_lane.pine")
        self.assertEqual(payload["indicator_title"], "DB1.S2 Candidate Fib Review")
        self.assertIn("pine_script", payload)

    def test_get_tradingview_pine_raw_returns_plain_text_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server, thread = _start_server(
                Path(temp_dir),
                FakeLegReadService(),
                FakeTradingViewPineReadService(),
            )
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/db1/s2/tradingview-pine?format=raw") as response:
                    payload = response.read().decode("utf-8")
                    content_type = response.headers.get_content_type()
            finally:
                _stop_server(server, thread)

        self.assertEqual(content_type, "text/plain")
        self.assertIn("indicator(\"DB1.S2 Candidate Fib Review\"", payload)


def _start_server(
    artifacts_dir: Path,
    fake_service: object,
    fake_pine_service: object,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = create_server(
        host="127.0.0.1",
        port=0,
        artifacts_dir=artifacts_dir,
        leg_read_service=fake_service,
        tradingview_pine_read_service=fake_pine_service,
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