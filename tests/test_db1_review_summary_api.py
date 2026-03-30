from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from apps.api.db1_review_read.http_app import create_server
from tests.db1_review_read_support import write_review_artifacts, write_review_submissions


class DB1ReviewSummaryApiTests(unittest.TestCase):
    def test_get_summary_endpoint_returns_decision_ready_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)
            write_review_submissions(artifacts_dir)
            server, thread = _start_server(artifacts_dir)
            try:
                with urlopen(
                    f"http://127.0.0.1:{server.server_port}/db1/review/summary"
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    allow_origin = response.headers.get("Access-Control-Allow-Origin")
            finally:
                _stop_server(server, thread)

        self.assertEqual(payload["summary"]["total_reviewed_structures"], 3)
        self.assertEqual(payload["summary"]["readiness_hint"], "continue")
        self.assertEqual(payload["market_contract"]["review_window"], "last 3 months")
        self.assertEqual(allow_origin, "*")

    def test_get_summary_endpoint_returns_zero_payload_without_submissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)
            server, thread = _start_server(artifacts_dir)
            try:
                payload = _read_json(
                    f"http://127.0.0.1:{server.server_port}/db1/review/summary"
                )
            finally:
                _stop_server(server, thread)

        self.assertEqual(payload["summary"]["total_reviewed_structures"], 0)
        self.assertEqual(payload["summary"]["flatout_wrong_count"], 0)

    def test_get_summary_endpoint_returns_internal_error_for_malformed_submissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)
            (artifacts_dir / "db1_review_submissions.jsonl").write_text(
                "{bad json}\n",
                encoding="utf-8",
            )
            server, thread = _start_server(artifacts_dir)
            try:
                with self.assertRaises(HTTPError) as error_context:
                    urlopen(
                        f"http://127.0.0.1:{server.server_port}/db1/review/summary"
                    )
            finally:
                _stop_server(server, thread)

        self.assertEqual(error_context.exception.code, 500)


def _start_server(artifacts_dir: Path) -> tuple[object, threading.Thread]:
    server = create_server(host="127.0.0.1", port=0, artifacts_dir=artifacts_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server: object, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


def _read_json(url: str) -> dict[str, object]:
    with urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()