from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnchorPair:
    parent_anchor_source_timestamp: str
    parent_anchor_price: float
    terminal_extreme_source_timestamp: str
    terminal_extreme_price: float


@dataclass(frozen=True, slots=True)
class ReviewSubmissionRequest:
    structure_id: str
    proposed_anchor_pair: AnchorPair
    review_outcome: str
    adjusted_anchor_pair: AnchorPair | None
    note: str | None
    previous_structure_comparison_used: bool


@dataclass(frozen=True, slots=True)
class ReviewSubmissionRecord:
    submission_id: str
    recorded_at_utc: str
    structure_id: str
    proposed_anchor_pair: AnchorPair
    review_outcome: str
    adjusted_anchor_pair: AnchorPair | None
    note: str | None
    previous_structure_comparison_used: bool


@dataclass(frozen=True, slots=True)
class ReviewSubmissionResponse:
    submission_id: str
    structure_id: str
    review_outcome: str
    recorded_at_utc: str
