from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MarketContractSnapshot:
    tradingview_symbol: str
    human_label: str
    instrument_label: str
    timeframe: str
    review_window: str


@dataclass(frozen=True, slots=True)
class ReviewManifest:
    market_contract: MarketContractSnapshot
    input_path: str
    candle_count: int
    pivot_count: int
    candidate_count: int
    accepted_structure_count: int
    rejected_anchor_count: int
    atr_period: int
    atr_multiplier: float
    pivot_rule: str
    generated_at_utc: str


@dataclass(frozen=True, slots=True)
class ReviewStructure:
    structure_id: str
    market_symbol: str
    timeframe: str
    direction: str
    parent_anchor_timestamp_utc: datetime
    parent_anchor_price: float
    parent_anchor_kind: str
    terminal_extreme_timestamp_utc: datetime
    terminal_extreme_price: float
    terminal_extreme_kind: str
    anchor_range_low: float
    anchor_range_high: float
    activated_at_utc: datetime
    invalidated_at_utc: datetime | None
    invalidation_reason: str | None
    source_candle_start_utc: datetime
    source_candle_end_utc: datetime


@dataclass(frozen=True, slots=True)
class ReviewProgress:
    current_index: int
    current_position: int
    total_structures: int
    label: str


@dataclass(frozen=True, slots=True)
class ReviewReadResponse:
    market_contract: MarketContractSnapshot
    progress: ReviewProgress
    current_structure: ReviewStructure
    previous_structure: ReviewStructure | None


@dataclass(frozen=True, slots=True)
class ReviewArtifactBundle:
    manifest: ReviewManifest
    structures: list[ReviewStructure]
