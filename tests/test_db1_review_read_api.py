from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from apps.api.db1_review_read.http_app import create_server
from tests.db1_review_read_support import write_review_artifacts


class DB1ReviewReadApiTests(unittest.TestCase):
    def test_get_structures_endpoint_returns_current_previous_and_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)
            server, thread = _start_server(artifacts_dir)
            try:
                payload = _read_json(
                    f"http://127.0.0.1:{server.server_port}/db1/review/structures?position=2"
                )
            finally:
                _stop_server(server, thread)

        self.assertEqual(payload["current_structure"]["structure_id"], "db1-fib-0002")
        self.assertEqual(payload["previous_structure"]["structure_id"], "db1-fib-0001")
        self.assertEqual(payload["progress"]["label"], "structure 2 of 3")
        self.assertEqual(
            payload["current_structure"]["terminal_extreme_source_timestamp"],
            "2026-01-01T14:00:00",
        )

    def test_get_structures_endpoint_allows_cross_origin_ui_fetches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)
            server, thread = _start_server(artifacts_dir)
            try:
                with urlopen(
                    f"http://127.0.0.1:{server.server_port}/db1/review/structures?index=0"
                ) as response:
                    allow_origin = response.headers.get("Access-Control-Allow-Origin")
            finally:
                _stop_server(server, thread)

        self.assertEqual(allow_origin, "*")

    def test_get_structures_endpoint_rejects_invalid_query_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)
            server, thread = _start_server(artifacts_dir)
            try:
                with self.assertRaises(HTTPError) as error_context:
                    urlopen(
                        f"http://127.0.0.1:{server.server_port}/db1/review/structures?index=0&position=1"
                    )
            finally:
                _stop_server(server, thread)

        self.assertEqual(error_context.exception.code, 400)

    def test_get_structures_endpoint_returns_service_unavailable_when_artifacts_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server, thread = _start_server(Path(temp_dir))
            try:
                with self.assertRaises(HTTPError) as error_context:
                    urlopen(
                        f"http://127.0.0.1:{server.server_port}/db1/review/structures?index=0"
                    )
            finally:
                _stop_server(server, thread)

        self.assertEqual(error_context.exception.code, 503)


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