"""API service entry point for the DB1 review read layer."""

from __future__ import annotations

import argparse
from pathlib import Path

from apps.api.db1_review_read.http_app import run_server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve the Discovery Bet 1 review read API.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface for the DB1 review read server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for the DB1 review read server.",
    )
    parser.add_argument(
        "--artifacts-dir",
        default="artifacts/discovery_bet_1",
        help="Directory containing generated DB1 artifact outputs.",
    )
    args = parser.parse_args()

    run_server(
        host=args.host,
        port=args.port,
        artifacts_dir=Path(args.artifacts_dir),
    )


if __name__ == "__main__":
    main()
