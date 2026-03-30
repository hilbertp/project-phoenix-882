from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class PivotKind(StrEnum):
    HIGH = "high"
    LOW = "low"


class StructureDirection(StrEnum):
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class Candle:
    source_timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class Pivot:
    index: int
    source_timestamp: str
    kind: PivotKind
    price: float
    candle_low: float
    candle_high: float


@dataclass(frozen=True, slots=True)
class RejectedAnchor:
    terminal_extreme_source_timestamp: str
    terminal_extreme_price: float
    terminal_extreme_kind: PivotKind
    candidate_anchor_source_timestamp: str
    candidate_anchor_price: float
    candidate_anchor_kind: PivotKind
    atr14_at_terminal: float | None
    distance_to_terminal: float | None
    eligibility_passed: bool
    rejection_reason: str
    selected_anchor_source_timestamp: str | None


@dataclass(frozen=True, slots=True)
class FibCandidate:
    parent_anchor: Pivot
    terminal_extreme: Pivot
    direction: StructureDirection
    anchor_range_low: float
    anchor_range_high: float


@dataclass(frozen=True, slots=True)
class FibStructure:
    structure_id: str
    market_symbol: str
    timeframe: str
    direction: StructureDirection
    parent_anchor_source_timestamp: str
    parent_anchor_price: float
    parent_anchor_kind: PivotKind
    terminal_extreme_source_timestamp: str
    terminal_extreme_price: float
    terminal_extreme_kind: PivotKind
    anchor_range_low: float
    anchor_range_high: float
    activated_at_source_timestamp: str
    invalidated_at_source_timestamp: str | None
    invalidation_reason: str | None
    source_candle_start_timestamp: str
    source_candle_end_timestamp: str


@dataclass(frozen=True, slots=True)
class GenerationOutputs:
    manifest_path: Path
    structures_jsonl_path: Path
    structures_csv_path: Path
    rejected_anchors_csv_path: Path
    market_symbol: str
    accepted_structure_count: int
    rejected_anchor_count: int
