"""Worker service entry point for offline generation tasks."""

from __future__ import annotations

import argparse
from pathlib import Path

from apps.worker.discovery_bet_1.run_generator import (
    DEFAULT_ARTIFACTS_DIR,
    DEFAULT_INPUT_PATH,
    run_generation,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Discovery Bet 1 fib structures from manual CSV input.",
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT_PATH),
        help="Path to the manual CSV export for BITGET:BTCUSDT.P.",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(DEFAULT_ARTIFACTS_DIR),
        help="Directory where generator artifacts will be written.",
    )
    args = parser.parse_args()

    outputs = run_generation(
        input_path=Path(args.input),
        artifacts_dir=Path(args.artifacts_dir),
    )
    print(
        "Generated "
        f"{outputs.accepted_structure_count} fib structures and "
        f"{outputs.rejected_anchor_count} rejected-anchor rows "
        f"for {outputs.market_symbol}."
    )


if __name__ == "__main__":
    main()
