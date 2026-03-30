from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from apps.api.db1_review_read.models import (
    MarketContractSnapshot,
    ReviewArtifactBundle,
    ReviewManifest,
    ReviewStructure,
)
from apps.worker.discovery_bet_1.market_contract import (
    LOCKED_MARKET_CONTRACT,
    market_contract_as_dict,
)

MANIFEST_FILENAME = "db1_generation_manifest.json"
STRUCTURES_FILENAME = "db1_fib_structures.jsonl"


class ArtifactReadError(Exception):
    """Base error for DB1 review artifact reads."""


class ArtifactsUnavailableError(ArtifactReadError):
    """Required DB1 review artifacts are not available."""


class ArtifactContractError(ArtifactReadError):
    """DB1 review artifacts failed contract validation."""


def load_review_artifacts(artifacts_dir: Path) -> ReviewArtifactBundle:
    manifest_path = artifacts_dir / MANIFEST_FILENAME
    structures_path = artifacts_dir / STRUCTURES_FILENAME

    if not manifest_path.exists() or not structures_path.exists():
        raise ArtifactsUnavailableError(
            "DB1 review artifacts are unavailable. Generate DB1 artifacts first."
        )

    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_market_contract(manifest_payload)
    manifest = _parse_manifest(manifest_payload)
    structures = _load_structures(structures_path)

    if manifest.accepted_structure_count != len(structures):
        raise ArtifactContractError(
            "DB1 manifest accepted_structure_count does not match structure rows."
        )

    return ReviewArtifactBundle(manifest=manifest, structures=structures)


def _validate_market_contract(manifest_payload: dict[str, object]) -> None:
    actual_market_contract = manifest_payload.get("market_contract")
    expected_market_contract = market_contract_as_dict(LOCKED_MARKET_CONTRACT)
    if actual_market_contract != expected_market_contract:
        raise ArtifactContractError(
            "DB1 review artifacts do not match the locked market contract."
        )


def _parse_manifest(payload: dict[str, object]) -> ReviewManifest:
    market_contract = payload["market_contract"]
    return ReviewManifest(
        market_contract=MarketContractSnapshot(**market_contract),
        input_path=str(payload["input_path"]),
        candle_count=int(payload["candle_count"]),
        pivot_count=int(payload["pivot_count"]),
        candidate_count=int(payload["candidate_count"]),
        accepted_structure_count=int(payload["accepted_structure_count"]),
        rejected_anchor_count=int(payload["rejected_anchor_count"]),
        atr_period=int(payload["atr_period"]),
        atr_multiplier=float(payload["atr_multiplier"]),
        pivot_rule=str(payload["pivot_rule"]),
        generated_at_utc=str(payload["generated_at_utc"]),
    )


def _load_structures(structures_path: Path) -> list[ReviewStructure]:
    structures: list[ReviewStructure] = []
    with structures_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            structures.append(_parse_structure(json.loads(line)))

    structures.sort(
        key=lambda structure: (
            structure.terminal_extreme_timestamp_utc,
            structure.structure_id,
        )
    )
    return structures


def _parse_structure(payload: dict[str, object]) -> ReviewStructure:
    return ReviewStructure(
        structure_id=str(payload["structure_id"]),
        market_symbol=str(payload["market_symbol"]),
        timeframe=str(payload["timeframe"]),
        direction=str(payload["direction"]),
        parent_anchor_timestamp_utc=_parse_timestamp(
            payload["parent_anchor_timestamp_utc"]
        ),
        parent_anchor_price=float(payload["parent_anchor_price"]),
        parent_anchor_kind=str(payload["parent_anchor_kind"]),
        terminal_extreme_timestamp_utc=_parse_timestamp(
            payload["terminal_extreme_timestamp_utc"]
        ),
        terminal_extreme_price=float(payload["terminal_extreme_price"]),
        terminal_extreme_kind=str(payload["terminal_extreme_kind"]),
        anchor_range_low=float(payload["anchor_range_low"]),
        anchor_range_high=float(payload["anchor_range_high"]),
        activated_at_utc=_parse_timestamp(payload["activated_at_utc"]),
        invalidated_at_utc=_parse_optional_timestamp(payload["invalidated_at_utc"]),
        invalidation_reason=_parse_optional_text(payload["invalidation_reason"]),
        source_candle_start_utc=_parse_timestamp(payload["source_candle_start_utc"]),
        source_candle_end_utc=_parse_timestamp(payload["source_candle_end_utc"]),
    )


def _parse_timestamp(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


def _parse_optional_timestamp(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    return _parse_timestamp(value)


def _parse_optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
