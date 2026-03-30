from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apps.worker.discovery_bet_1.types import Candle

EXPECTED_COLUMNS = ["timestamp_utc", "open", "high", "low", "close", "volume"]
EXPECTED_CADENCE = timedelta(hours=1)
MAX_REVIEW_WINDOW = timedelta(days=93)


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
                timestamp_utc=_parse_timestamp(row["timestamp_utc"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for row in reader
        ]

    if not candles:
        raise ValueError("Manual CSV input must contain at least one candle.")

    _validate_candles(candles)
    return candles


def _parse_timestamp(raw_value: str) -> datetime:
    normalized = raw_value.strip().replace("Z", "+00:00")
    timestamp = datetime.fromisoformat(normalized)
    if timestamp.tzinfo is None:
        raise ValueError("timestamp_utc values must be timezone-aware UTC timestamps.")
    if timestamp.utcoffset() != timedelta(0):
        raise ValueError("timestamp_utc values must use UTC offsets only.")
    return timestamp.astimezone(UTC)


def _validate_candles(candles: list[Candle]) -> None:
    previous_timestamp: datetime | None = None
    for candle in candles:
        if candle.low > candle.high:
            raise ValueError("Candle low cannot be greater than candle high.")
        if previous_timestamp is not None:
            delta = candle.timestamp_utc - previous_timestamp
            if delta <= timedelta(0):
                raise ValueError(
                    "Candles must be in strictly ascending chronological order."
                )
            if delta != EXPECTED_CADENCE:
                raise ValueError("Candles must use an exact 1H cadence.")
        previous_timestamp = candle.timestamp_utc

    if candles[-1].timestamp_utc - candles[0].timestamp_utc > MAX_REVIEW_WINDOW:
        raise ValueError("Manual CSV input must contain last-3-month data only.")
