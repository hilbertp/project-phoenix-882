from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from apps.api.db1_review_read.http_app import create_server


def _submission_payload() -> dict[str, object]:
    return {
        "structure_id": "db1-fib-0002",
        "proposed_anchor_pair": {
            "parent_anchor_timestamp_utc": "2026-01-01T05:00:00+00:00",
            "parent_anchor_price": 90.0,
            "terminal_extreme_timestamp_utc": "2026-01-01T14:00:00+00:00",
            "terminal_extreme_price": 130.0,
        },
        "review_outcome": "flatout_wrong",
        "adjusted_anchor_pair": None,
        "note": "invalid setup",
        "previous_structure_comparison_used": True,
    }


class DB1ReviewWritebackApiTests(unittest.TestCase):
    def test_post_submission_returns_created_response_and_persists_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            server, thread = _start_server(artifacts_dir)
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/db1/review/submissions",
                    data=json.dumps(_submission_payload()).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    allow_origin = response.headers.get("Access-Control-Allow-Origin")
            finally:
                _stop_server(server, thread)

            stored_lines = (artifacts_dir / "db1_review_submissions.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(payload["structure_id"], "db1-fib-0002")
        self.assertEqual(payload["review_outcome"], "flatout_wrong")
        self.assertEqual(allow_origin, "*")
        self.assertEqual(len(stored_lines), 1)

    def test_post_submission_rejects_invalid_payload(self) -> None:
        payload = _submission_payload()
        payload["review_outcome"] = "unknown"

        with tempfile.TemporaryDirectory() as temp_dir:
            server, thread = _start_server(Path(temp_dir))
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/db1/review/submissions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as error_context:
                    urlopen(request)
            finally:
                _stop_server(server, thread)

        self.assertEqual(error_context.exception.code, 400)


def _start_server(artifacts_dir: Path) -> tuple[object, threading.Thread]:
    server = create_server(host="127.0.0.1", port=0, artifacts_dir=artifacts_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server: object, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


if __name__ == "__main__":
    unittest.main()