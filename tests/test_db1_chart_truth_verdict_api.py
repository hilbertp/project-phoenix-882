from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from apps.api.db1_review_read.http_app import create_server


class DB1ChartTruthVerdictApiTests(unittest.TestCase):
    def test_post_and_get_chart_truth_verdict_round_trip_through_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            server, thread = _start_server(artifacts_dir)
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/db1/review/chart-truth-verdict",
                    data=json.dumps(
                        {"structure_id": "db1-fib-0001", "verdict": "meh"}
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request) as response:
                    post_payload = json.loads(response.read().decode("utf-8"))

                with urlopen(
                    f"http://127.0.0.1:{server.server_port}/db1/review/chart-truth-verdict?structure_id=db1-fib-0001"
                ) as response:
                    get_payload = json.loads(response.read().decode("utf-8"))
            finally:
                _stop_server(server, thread)

            stored_lines = (artifacts_dir / "db1_chart_truth_verdicts.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(post_payload["verdict"], "meh")
        self.assertEqual(get_payload["structure_id"], "db1-fib-0001")
        self.assertEqual(get_payload["verdict"], "meh")
        self.assertEqual(len(stored_lines), 1)


def _start_server(artifacts_dir: Path) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = create_server(host="127.0.0.1", port=0, artifacts_dir=artifacts_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server: ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


if __name__ == "__main__":
    unittest.main()