from __future__ import annotations

import json
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
import unittest

from apps.api.db1_review_read.http_app import create_server


class FakeSwingReadService:
    def get_swing_payload(self) -> dict[str, object]:
        return {
            "sub_bet": "DB1.S1",
            "title": "Raw 1H Swing Detection",
            "market_contract": {
                "tradingview_symbol": "BITGET:BTCUSDT.P",
                "human_label": "BTCUSDT.P on Bitget",
                "instrument_label": "BTCUSDTPERP PERPETUAL MIX CONTRACT",
                "timeframe": "1H",
                "review_window": "last 3 months",
            },
            "detector": {
                "rule_name": "strict_local_pivot_2_left_2_right",
                "description": "strict swing detector",
                "left_bars": 2,
                "right_bars": 2,
            },
            "summary": {
                "candle_count": 4,
                "swing_count": 2,
                "swing_high_count": 1,
                "swing_low_count": 1,
                "source_start_timestamp": "2026-01-01T00:00:00",
                "source_end_timestamp": "2026-01-01T03:00:00",
            },
            "source_provenance": {
                "acquisition_timestamp_utc": "2026-01-01T04:00:00+00:00",
                "acquisition_operator_or_process": "test",
                "acquisition_method": "fixture",
                "source_file_sha256": "abc",
            },
            "candles": [
                {
                    "source_timestamp": "2026-01-01T00:00:00",
                    "open": 1.0,
                    "high": 2.0,
                    "low": 0.5,
                    "close": 1.5,
                    "volume": 10.0,
                }
            ],
            "swing_highs": [
                {
                    "index": 2,
                    "source_timestamp": "2026-01-01T02:00:00",
                    "kind": "high",
                    "price": 3.0,
                    "candle_low": 1.0,
                    "candle_high": 3.0,
                }
            ],
            "swing_lows": [
                {
                    "index": 1,
                    "source_timestamp": "2026-01-01T01:00:00",
                    "kind": "low",
                    "price": 0.5,
                    "candle_low": 0.5,
                    "candle_high": 1.8,
                }
            ],
        }


class DB1S1SwingApiTests(unittest.TestCase):
    def test_get_swings_returns_gate_one_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server, thread = _start_server(Path(temp_dir), FakeSwingReadService())
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/db1/s1/swings") as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                _stop_server(server, thread)

        self.assertEqual(payload["sub_bet"], "DB1.S1")
        self.assertEqual(payload["detector"]["left_bars"], 2)
        self.assertEqual(payload["summary"]["swing_high_count"], 1)
        self.assertEqual(payload["summary"]["swing_low_count"], 1)
        self.assertEqual(payload["swing_highs"][0]["kind"], "high")
        self.assertEqual(payload["swing_lows"][0]["kind"], "low")


def _start_server(
    artifacts_dir: Path,
    fake_service: object,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = create_server(
        host="127.0.0.1",
        port=0,
        artifacts_dir=artifacts_dir,
        swing_read_service=fake_service,
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