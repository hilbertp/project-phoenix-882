from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from apps.api.db1_review_writeback.models import (
    AnchorPair,
    ChartTruthVerdictRecord,
    ChartTruthVerdictRequest,
    ChartTruthVerdictResponse,
    ReviewSubmissionRecord,
    ReviewSubmissionRequest,
    ReviewSubmissionResponse,
)
from apps.api.db1_review_writeback.store import ChartTruthVerdictStore, ReviewSubmissionStore

ALLOWED_REVIEW_OUTCOMES = {"good_enough", "adjusted_accept", "flatout_wrong"}
ALLOWED_CHART_TRUTH_VERDICTS = {"up", "down", "meh"}
DEFAULT_ARTIFACTS_DIR = Path("artifacts/discovery_bet_1")


class InvalidReviewSubmissionError(Exception):
    """The caller supplied an invalid DB1 review submission."""


class InvalidChartTruthVerdictError(Exception):
    """The caller supplied an invalid chart-truth verdict payload."""


class DB1ReviewWritebackService:
    def __init__(self, artifacts_dir: Path = DEFAULT_ARTIFACTS_DIR) -> None:
        self._store = ReviewSubmissionStore(artifacts_dir)
        self._chart_truth_store = ChartTruthVerdictStore(artifacts_dir)

    def submit_review(self, payload: dict[str, object]) -> ReviewSubmissionResponse:
        request = _parse_submission_request(payload)
        submission_id = self._store.next_submission_id()
        recorded_at_utc = datetime.now(UTC).isoformat()
        record = ReviewSubmissionRecord(
            submission_id=submission_id,
            recorded_at_utc=recorded_at_utc,
            structure_id=request.structure_id,
            proposed_anchor_pair=request.proposed_anchor_pair,
            review_outcome=request.review_outcome,
            adjusted_anchor_pair=request.adjusted_anchor_pair,
            note=request.note,
            previous_structure_comparison_used=request.previous_structure_comparison_used,
        )
        self._store.append(record)
        return ReviewSubmissionResponse(
            submission_id=submission_id,
            structure_id=request.structure_id,
            review_outcome=request.review_outcome,
            recorded_at_utc=recorded_at_utc,
        )

    def save_chart_truth_verdict(
        self, payload: dict[str, object]
    ) -> ChartTruthVerdictResponse:
        request = _parse_chart_truth_verdict_request(payload)
        recorded_at_utc = datetime.now(UTC).isoformat()
        record = ChartTruthVerdictRecord(
            structure_id=request.structure_id,
            verdict=request.verdict,
            recorded_at_utc=recorded_at_utc,
        )
        self._chart_truth_store.append(record)
        return ChartTruthVerdictResponse(
            structure_id=request.structure_id,
            verdict=request.verdict,
            recorded_at_utc=recorded_at_utc,
        )

    def get_chart_truth_verdict(self, structure_id: str) -> ChartTruthVerdictResponse:
        if structure_id == "":
            raise InvalidChartTruthVerdictError("structure_id must be a non-empty string.")

        record = self._chart_truth_store.latest_for_structure(structure_id)
        if record is None:
            return ChartTruthVerdictResponse(
                structure_id=structure_id,
                verdict=None,
                recorded_at_utc=None,
            )

        return ChartTruthVerdictResponse(
            structure_id=record.structure_id,
            verdict=record.verdict,
            recorded_at_utc=record.recorded_at_utc,
        )


def _parse_submission_request(payload: dict[str, object]) -> ReviewSubmissionRequest:
    structure_id = _require_non_empty_string(payload, "structure_id")
    review_outcome = _require_non_empty_string(payload, "review_outcome")
    if review_outcome not in ALLOWED_REVIEW_OUTCOMES:
        raise InvalidReviewSubmissionError(
            f"review_outcome must be one of {sorted(ALLOWED_REVIEW_OUTCOMES)}."
        )

    proposed_anchor_pair = _parse_anchor_pair(
        payload.get("proposed_anchor_pair"), "proposed_anchor_pair"
    )
    adjusted_anchor_pair_payload = payload.get("adjusted_anchor_pair")
    adjusted_anchor_pair = (
        _parse_anchor_pair(adjusted_anchor_pair_payload, "adjusted_anchor_pair")
        if adjusted_anchor_pair_payload not in (None, "")
        else None
    )

    if review_outcome == "adjusted_accept" and adjusted_anchor_pair is None:
        raise InvalidReviewSubmissionError(
            "adjusted_anchor_pair is required when review_outcome is adjusted_accept."
        )
    if review_outcome != "adjusted_accept" and adjusted_anchor_pair is not None:
        raise InvalidReviewSubmissionError(
            "adjusted_anchor_pair is only allowed for adjusted_accept submissions."
        )

    previous_structure_comparison_used = payload.get(
        "previous_structure_comparison_used"
    )
    if not isinstance(previous_structure_comparison_used, bool):
        raise InvalidReviewSubmissionError(
            "previous_structure_comparison_used must be a boolean."
        )

    note = payload.get("note")
    if note in (None, ""):
        normalized_note = None
    elif isinstance(note, str):
        normalized_note = note
    else:
        raise InvalidReviewSubmissionError("note must be a string when provided.")

    return ReviewSubmissionRequest(
        structure_id=structure_id,
        proposed_anchor_pair=proposed_anchor_pair,
        review_outcome=review_outcome,
        adjusted_anchor_pair=adjusted_anchor_pair,
        note=normalized_note,
        previous_structure_comparison_used=previous_structure_comparison_used,
    )


def _parse_chart_truth_verdict_request(
    payload: dict[str, object]
) -> ChartTruthVerdictRequest:
    structure_id = _require_non_empty_string(payload, "structure_id")
    verdict = _require_non_empty_string(payload, "verdict")
    if verdict not in ALLOWED_CHART_TRUTH_VERDICTS:
        raise InvalidChartTruthVerdictError(
            f"verdict must be one of {sorted(ALLOWED_CHART_TRUTH_VERDICTS)}."
        )

    return ChartTruthVerdictRequest(structure_id=structure_id, verdict=verdict)


def _require_non_empty_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or value == "":
        raise InvalidReviewSubmissionError(f"{key} must be a non-empty string.")
    return value


def _parse_anchor_pair(value: object, key: str) -> AnchorPair:
    if not isinstance(value, dict):
        raise InvalidReviewSubmissionError(f"{key} must be an object.")
    try:
        parent_anchor_source_timestamp = _require_anchor_string(
            value, "parent_anchor_source_timestamp"
        )
        parent_anchor_price = _require_anchor_float(value, "parent_anchor_price")
        terminal_extreme_source_timestamp = _require_anchor_string(
            value, "terminal_extreme_source_timestamp"
        )
        terminal_extreme_price = _require_anchor_float(value, "terminal_extreme_price")
    except InvalidReviewSubmissionError as error:
        raise InvalidReviewSubmissionError(f"{key}: {error}") from error
    return AnchorPair(
        parent_anchor_source_timestamp=parent_anchor_source_timestamp,
        parent_anchor_price=parent_anchor_price,
        terminal_extreme_source_timestamp=terminal_extreme_source_timestamp,
        terminal_extreme_price=terminal_extreme_price,
    )


def _require_anchor_string(value: dict[str, object], key: str) -> str:
    raw_value = value.get(key)
    if not isinstance(raw_value, str) or raw_value == "":
        raise InvalidReviewSubmissionError(f"{key} must be a non-empty string.")
    return raw_value


def _require_anchor_float(value: dict[str, object], key: str) -> float:
    raw_value = value.get(key)
    if not isinstance(raw_value, (int, float)):
        raise InvalidReviewSubmissionError(f"{key} must be numeric.")
    return float(raw_value)
