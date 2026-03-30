from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from apps.api.db1_review_read.artifact_reader import (
    ArtifactReadError,
    ArtifactsUnavailableError,
)
from apps.api.db1_review_read.service import (
    DB1ReviewReadService,
    InvalidReviewRequestError,
    ReviewStructureNotFoundError,
)
from apps.api.db1_review_summary.reader import ReviewSummaryReadError
from apps.api.db1_review_summary.service import DB1ReviewSummaryService
from apps.api.db1_review_writeback.service import (
    DB1ReviewWritebackService,
    InvalidReviewSubmissionError,
)


def create_server(
    *,
    host: str,
    port: int,
    artifacts_dir: Path,
) -> ThreadingHTTPServer:
    service = DB1ReviewReadService(artifacts_dir=artifacts_dir)
    summary_service = DB1ReviewSummaryService(artifacts_dir=artifacts_dir)
    writeback_service = DB1ReviewWritebackService(artifacts_dir=artifacts_dir)

    class ReviewRequestHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:
            if parsed_path_supported(urlparse(self.path).path):
                self.send_response(HTTPStatus.NO_CONTENT)
                self._write_cors_headers()
                self.end_headers()
                return
            self.send_response(HTTPStatus.NOT_FOUND)
            self._write_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:
            parsed_url = urlparse(self.path)
            if parsed_url.path == "/db1/review/structures":
                try:
                    query = _extract_query_values(parsed_url.query)
                    payload = service.get_review_payload(**query)
                except InvalidReviewRequestError as error:
                    self._write_error(HTTPStatus.BAD_REQUEST, str(error))
                    return
                except ReviewStructureNotFoundError as error:
                    self._write_error(HTTPStatus.NOT_FOUND, str(error))
                    return
                except ArtifactsUnavailableError as error:
                    self._write_error(HTTPStatus.SERVICE_UNAVAILABLE, str(error))
                    return
                except ArtifactReadError as error:
                    self._write_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))
                    return

                self._write_json(HTTPStatus.OK, payload)
                return

            if parsed_url.path == "/db1/review/summary":
                try:
                    payload = summary_service.get_summary_payload()
                except ArtifactsUnavailableError as error:
                    self._write_error(HTTPStatus.SERVICE_UNAVAILABLE, str(error))
                    return
                except (ArtifactReadError, ReviewSummaryReadError) as error:
                    self._write_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))
                    return

                self._write_json(HTTPStatus.OK, payload)
                return

            self._write_error(
                HTTPStatus.NOT_FOUND,
                "DB1 review endpoint not found.",
            )
            return

        def do_POST(self) -> None:
            parsed_url = urlparse(self.path)
            if parsed_url.path != "/db1/review/submissions":
                self._write_error(
                    HTTPStatus.NOT_FOUND,
                    "DB1 review write endpoint not found.",
                )
                return

            try:
                payload = _read_json_body(self)
                response_payload = writeback_service.submit_review(payload)
            except InvalidReviewSubmissionError as error:
                self._write_error(HTTPStatus.BAD_REQUEST, str(error))
                return
            except ValueError as error:
                self._write_error(HTTPStatus.BAD_REQUEST, str(error))
                return

            self._write_json(HTTPStatus.CREATED, response_payload)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _write_error(self, status: HTTPStatus, message: str) -> None:
            self._write_json(status, {"error": message})

        def _write_json(self, status: HTTPStatus, payload: object) -> None:
            body = json.dumps(_serialize(payload), sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self._write_cors_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    return ThreadingHTTPServer((host, port), ReviewRequestHandler)


def run_server(*, host: str, port: int, artifacts_dir: Path) -> None:
    server = create_server(host=host, port=port, artifacts_dir=artifacts_dir)
    print(f"Serving DB1 review read API on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _extract_query_values(query: str) -> dict[str, int | None]:
    parsed = parse_qs(query, keep_blank_values=True)
    index = _parse_optional_int(parsed, "index")
    position = _parse_optional_int(parsed, "position")
    return {"index": index, "position": position}


def _parse_optional_int(
    parsed_query: dict[str, list[str]],
    key: str,
) -> int | None:
    values = parsed_query.get(key)
    if values is None:
        return None
    if len(values) != 1 or values[0] == "":
        raise InvalidReviewRequestError(f"{key} must be provided exactly once.")
    try:
        return int(values[0])
    except ValueError as error:
        raise InvalidReviewRequestError(f"{key} must be an integer.") from error


def _serialize(value: object) -> Any:
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    content_length = handler.headers.get("Content-Length")
    if content_length is None:
        raise ValueError("Content-Length header is required.")
    try:
        length = int(content_length)
    except ValueError as error:
        raise ValueError("Content-Length header must be an integer.") from error

    raw_body = handler.rfile.read(length)
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("Request body must be valid JSON.") from error

    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    return payload


def parsed_path_supported(path: str) -> bool:
    return path in {
        "/db1/review/structures",
        "/db1/review/submissions",
        "/db1/review/summary",
    }
