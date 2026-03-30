from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from apps.api.db1_review_read.models import (
    MarketContractSnapshot,
    ReviewArtifactBundle,
    ReviewManifest,
    ReviewStructure,
    SourceProvenanceSnapshot,
)
from apps.worker.discovery_bet_1.export import ARTIFACT_SCHEMA_VERSION
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
    _validate_manifest_contract(manifest_payload)
    manifest = _parse_manifest(manifest_payload)
    structures = _load_structures(structures_path)

    if manifest.accepted_structure_count != len(structures):
        raise ArtifactContractError(
            "DB1 manifest accepted_structure_count does not match structure rows."
        )

    return ReviewArtifactBundle(manifest=manifest, structures=structures)


def _validate_manifest_contract(manifest_payload: dict[str, object]) -> None:
    schema_version = manifest_payload.get("artifact_schema_version")
    if schema_version != ARTIFACT_SCHEMA_VERSION:
        raise ArtifactContractError(
            "DB1 review artifacts do not match the required source-truth artifact schema version."
        )

    actual_market_contract = manifest_payload.get("market_contract")
    expected_market_contract = market_contract_as_dict(LOCKED_MARKET_CONTRACT)
    if actual_market_contract != expected_market_contract:
        raise ArtifactContractError(
            "DB1 review artifacts do not match the locked market contract."
        )

    source_provenance = manifest_payload.get("source_provenance")
    if not isinstance(source_provenance, dict):
        raise ArtifactContractError(
            "DB1 review artifacts are missing required source provenance metadata."
        )

    for key in (
        "acquisition_timestamp_utc",
        "acquisition_operator_or_process",
        "acquisition_method",
        "source_file_sha256",
    ):
        value = source_provenance.get(key)
        if not isinstance(value, str) or value == "":
            raise ArtifactContractError(
                f"DB1 review artifacts contain invalid source provenance field {key}."
            )


def _parse_manifest(payload: dict[str, object]) -> ReviewManifest:
    market_contract = _require_mapping(payload, "market_contract")
    source_provenance = _require_mapping(payload, "source_provenance")
    return ReviewManifest(
        artifact_schema_version=str(payload["artifact_schema_version"]),
        market_contract=MarketContractSnapshot(
            tradingview_symbol=str(market_contract["tradingview_symbol"]),
            human_label=str(market_contract["human_label"]),
            instrument_label=str(market_contract["instrument_label"]),
            timeframe=str(market_contract["timeframe"]),
            review_window=str(market_contract["review_window"]),
        ),
        input_path=str(payload["input_path"]),
        source_provenance=SourceProvenanceSnapshot(
            acquisition_timestamp_utc=str(source_provenance["acquisition_timestamp_utc"]),
            acquisition_operator_or_process=str(
                source_provenance["acquisition_operator_or_process"]
            ),
            acquisition_method=str(source_provenance["acquisition_method"]),
            source_file_sha256=str(source_provenance["source_file_sha256"]),
        ),
        candle_count=_require_int(payload, "candle_count"),
        pivot_count=_require_int(payload, "pivot_count"),
        candidate_count=_require_int(payload, "candidate_count"),
        accepted_structure_count=_require_int(payload, "accepted_structure_count"),
        rejected_anchor_count=_require_int(payload, "rejected_anchor_count"),
        atr_period=_require_int(payload, "atr_period"),
        atr_multiplier=_require_float(payload, "atr_multiplier"),
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
            structure.terminal_extreme_source_timestamp,
            structure.structure_id,
        )
    )
    return structures


def _parse_structure(payload: dict[str, object]) -> ReviewStructure:
    required_fields = (
        "structure_id",
        "market_symbol",
        "timeframe",
        "direction",
        "parent_anchor_source_timestamp",
        "parent_anchor_price",
        "parent_anchor_kind",
        "terminal_extreme_source_timestamp",
        "terminal_extreme_price",
        "terminal_extreme_kind",
        "anchor_range_low",
        "anchor_range_high",
        "activated_at_source_timestamp",
        "invalidated_at_source_timestamp",
        "invalidation_reason",
        "source_candle_start_timestamp",
        "source_candle_end_timestamp",
    )
    missing_fields = [field for field in required_fields if field not in payload]
    if missing_fields:
        raise ArtifactContractError(
            "DB1 review structure rows do not match the required source-truth schema: "
            + ", ".join(missing_fields)
        )

    return ReviewStructure(
        structure_id=str(payload["structure_id"]),
        market_symbol=str(payload["market_symbol"]),
        timeframe=str(payload["timeframe"]),
        direction=str(payload["direction"]),
        parent_anchor_source_timestamp=str(payload["parent_anchor_source_timestamp"]),
        parent_anchor_price=_require_float(payload, "parent_anchor_price"),
        parent_anchor_kind=str(payload["parent_anchor_kind"]),
        terminal_extreme_source_timestamp=str(
            payload["terminal_extreme_source_timestamp"]
        ),
        terminal_extreme_price=_require_float(payload, "terminal_extreme_price"),
        terminal_extreme_kind=str(payload["terminal_extreme_kind"]),
        anchor_range_low=_require_float(payload, "anchor_range_low"),
        anchor_range_high=_require_float(payload, "anchor_range_high"),
        activated_at_source_timestamp=str(payload["activated_at_source_timestamp"]),
        invalidated_at_source_timestamp=_parse_optional_text(
            payload["invalidated_at_source_timestamp"]
        ),
        invalidation_reason=_parse_optional_text(payload["invalidation_reason"]),
        source_candle_start_timestamp=str(payload["source_candle_start_timestamp"]),
        source_candle_end_timestamp=str(payload["source_candle_end_timestamp"]),
    )


def _parse_optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _require_mapping(
    payload: dict[str, object],
    key: str,
) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ArtifactContractError(
            f"DB1 review artifacts contain invalid manifest field {key}."
        )
    return value


def _require_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ArtifactContractError(
            f"DB1 review artifacts contain invalid numeric field {key}."
        )
    return value


def _require_float(payload: dict[str, object], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)):
        raise ArtifactContractError(
            f"DB1 review artifacts contain invalid numeric field {key}."
        )
    return float(value)
