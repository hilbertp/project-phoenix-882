from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from apps.worker.discovery_bet_1.types import Candle

EXPECTED_COLUMNS = ["source_timestamp", "open", "high", "low", "close", "volume"]
MAX_REVIEW_WINDOW = timedelta(days=93)
SOURCE_PROVENANCE_SUFFIX = ".provenance.json"


class SourceInputContractError(ValueError):
    """The DB1 source input does not satisfy the approved source-truth contract."""


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    acquisition_timestamp_utc: str
    acquisition_operator_or_process: str
    acquisition_method: str
    source_file_sha256: str


@dataclass(frozen=True, slots=True)
class LoadedCandleInput:
    candles: list[Candle]
    provenance: SourceProvenance


def load_candle_input(csv_path: Path) -> LoadedCandleInput:
    provenance = _load_source_provenance(csv_path)
    candles = load_candles(csv_path)
    return LoadedCandleInput(candles=candles, provenance=provenance)


def load_candles(csv_path: Path) -> list[Candle]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Manual input file does not exist: {csv_path}")

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_COLUMNS:
            raise ValueError(
                f"Expected CSV columns {EXPECTED_COLUMNS}, got {reader.fieldnames}."
            )

        candles = [
            Candle(
                source_timestamp=row["source_timestamp"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for row in reader
        ]

    if not candles:
        raise SourceInputContractError("Manual CSV input must contain at least one candle.")

    parsed_timestamps = [_parse_source_timestamp(candle.source_timestamp) for candle in candles]
    _validate_candles(candles, parsed_timestamps)
    return candles


def _load_source_provenance(csv_path: Path) -> SourceProvenance:
    provenance_path = csv_path.with_suffix(SOURCE_PROVENANCE_SUFFIX)
    if not provenance_path.exists():
        raise SourceInputContractError(
            f"Source provenance file does not exist: {provenance_path}"
        )

    try:
        payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SourceInputContractError(
            f"Source provenance file is not valid JSON: {provenance_path}"
        ) from error

    if not isinstance(payload, dict):
        raise SourceInputContractError("Source provenance payload must be a JSON object.")

    provenance = SourceProvenance(
        acquisition_timestamp_utc=_require_non_empty_string(
            payload, "acquisition_timestamp_utc"
        ),
        acquisition_operator_or_process=_require_non_empty_string(
            payload, "acquisition_operator_or_process"
        ),
        acquisition_method=_require_non_empty_string(payload, "acquisition_method"),
        source_file_sha256=_require_non_empty_string(payload, "source_file_sha256"),
    )

    actual_sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    if provenance.source_file_sha256 != actual_sha256:
        raise SourceInputContractError(
            "Source provenance hash does not match the source CSV contents."
        )

    return provenance


def _require_non_empty_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or value == "":
        raise SourceInputContractError(f"Source provenance field {key} must be a non-empty string.")
    return value


def _parse_source_timestamp(raw_value: str) -> datetime:
    try:
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SourceInputContractError(
            "source_timestamp values must be ISO-8601 datetime strings as delivered by the source."
        ) from error


def _validate_candles(
    candles: list[Candle],
    parsed_timestamps: list[datetime],
) -> None:
    previous_timestamp: datetime | None = None
    for candle, current_timestamp in zip(candles, parsed_timestamps, strict=True):
        if candle.low > candle.high:
            raise SourceInputContractError("Candle low cannot be greater than candle high.")
        if previous_timestamp is not None:
            try:
                delta = current_timestamp - previous_timestamp
            except TypeError as error:
                raise SourceInputContractError(
                    "source_timestamp values must use a consistent timezone style across the file."
                ) from error
            if delta <= timedelta(0):
                raise SourceInputContractError(
                    "Candles must be in strictly ascending chronological order."
                )
        previous_timestamp = current_timestamp

    if parsed_timestamps[-1] - parsed_timestamps[0] > MAX_REVIEW_WINDOW:
        raise SourceInputContractError("Manual CSV input must contain last-3-month data only.")
