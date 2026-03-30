from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.worker.discovery_bet_1.market_contract import (
    MarketContract,
    market_contract_as_dict,
)
from apps.worker.discovery_bet_1.types import FibStructure, RejectedAnchor


def export_generation_artifacts(
    *,
    artifacts_dir: Path,
    input_path: Path,
    contract: MarketContract,
    candle_count: int,
    pivot_count: int,
    candidate_count: int,
    fib_structures: list[FibStructure],
    rejected_anchors: list[RejectedAnchor],
) -> tuple[Path, Path, Path, Path]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = artifacts_dir / "db1_generation_manifest.json"
    structures_jsonl_path = artifacts_dir / "db1_fib_structures.jsonl"
    structures_csv_path = artifacts_dir / "db1_fib_structures.csv"
    rejected_anchors_csv_path = artifacts_dir / "db1_rejected_anchors.csv"

    manifest = {
        "market_contract": market_contract_as_dict(contract),
        "input_path": str(input_path),
        "candle_count": candle_count,
        "pivot_count": pivot_count,
        "candidate_count": candidate_count,
        "accepted_structure_count": len(fib_structures),
        "rejected_anchor_count": len(rejected_anchors),
        "atr_period": 14,
        "atr_multiplier": 2.0,
        "pivot_rule": "2-left/2-right",
        "generated_at_utc": datetime.now().astimezone().isoformat(),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with structures_jsonl_path.open("w", encoding="utf-8", newline="") as handle:
        for structure in fib_structures:
            handle.write(
                json.dumps(_serialize_dataclass(structure), sort_keys=True) + "\n"
            )

    _write_csv(structures_csv_path, fib_structures)
    _write_csv(rejected_anchors_csv_path, rejected_anchors)

    return (
        manifest_path,
        structures_jsonl_path,
        structures_csv_path,
        rejected_anchors_csv_path,
    )


def _write_csv(path: Path, rows: list[object]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    serialized_rows = [_serialize_dataclass(row) for row in rows]
    fieldnames = list(serialized_rows[0].keys())

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(serialized_rows)


def _serialize_dataclass(value: object) -> dict[str, Any]:
    raw_dict = asdict(value)
    serialized: dict[str, Any] = {}
    for key, item in raw_dict.items():
        if isinstance(item, datetime):
            serialized[key] = item.isoformat()
        elif item is None:
            serialized[key] = ""
        else:
            serialized[key] = str(item) if hasattr(item, "value") else item
    return serialized
