from __future__ import annotations

from dataclasses import asdict, dataclass

from apps.api.db1_review_read.models import MarketContractSnapshot


@dataclass(frozen=True, slots=True)
class ReviewSubmissionSnapshot:
    review_outcome: str
    note: str | None


@dataclass(frozen=True, slots=True)
class WrongCaseReasonCount:
    reason: str
    count: int


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    total_reviewed_structures: int
    good_enough_count: int
    adjusted_accept_count: int
    flatout_wrong_count: int
    combined_positive_count: int
    combined_positive_share: float
    readiness_hint: str


@dataclass(frozen=True, slots=True)
class ReviewSummaryResponse:
    market_contract: MarketContractSnapshot
    summary: ReviewSummary
    wrong_case_reason_counts: list[WrongCaseReasonCount] | None = None

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        if self.wrong_case_reason_counts is None:
            payload.pop("wrong_case_reason_counts", None)
        return payload
