from __future__ import annotations

from collections import Counter
from pathlib import Path

from apps.api.db1_review_read.artifact_reader import load_review_artifacts
from apps.api.db1_review_summary.models import (
    ReviewSummary,
    ReviewSummaryResponse,
    WrongCaseReasonCount,
)
from apps.api.db1_review_summary.reader import load_review_submissions

DEFAULT_ARTIFACTS_DIR = Path("artifacts/discovery_bet_1")
CONTINUE_THRESHOLD = 0.65
REFINE_ONCE_THRESHOLD = 0.40


class DB1ReviewSummaryService:
    def __init__(self, artifacts_dir: Path = DEFAULT_ARTIFACTS_DIR) -> None:
        self._artifacts_dir = artifacts_dir

    def get_summary_payload(self) -> dict[str, object]:
        artifact_bundle = load_review_artifacts(self._artifacts_dir)
        submissions = load_review_submissions(self._artifacts_dir)

        outcome_counts = Counter(
            submission.review_outcome for submission in submissions
        )
        total_reviewed_structures = len(submissions)
        good_enough_count = outcome_counts.get("good_enough", 0)
        adjusted_accept_count = outcome_counts.get("adjusted_accept", 0)
        flatout_wrong_count = outcome_counts.get("flatout_wrong", 0)
        combined_positive_count = good_enough_count + adjusted_accept_count
        combined_positive_share = (
            round(
                combined_positive_count / total_reviewed_structures,
                4,
            )
            if total_reviewed_structures
            else 0.0
        )

        wrong_case_reason_counts = _build_wrong_case_reason_counts(submissions)
        response = ReviewSummaryResponse(
            market_contract=artifact_bundle.manifest.market_contract,
            summary=ReviewSummary(
                total_reviewed_structures=total_reviewed_structures,
                good_enough_count=good_enough_count,
                adjusted_accept_count=adjusted_accept_count,
                flatout_wrong_count=flatout_wrong_count,
                combined_positive_count=combined_positive_count,
                combined_positive_share=combined_positive_share,
                readiness_hint=_determine_readiness_hint(combined_positive_share),
            ),
            wrong_case_reason_counts=wrong_case_reason_counts,
        )
        return response.to_payload()


def _build_wrong_case_reason_counts(
    submissions: list[object],
) -> list[WrongCaseReasonCount] | None:
    notes = Counter(
        submission.note
        for submission in submissions
        if submission.review_outcome == "flatout_wrong" and submission.note
    )
    if not notes:
        return None
    return [
        WrongCaseReasonCount(reason=reason, count=count)
        for reason, count in sorted(notes.items(), key=lambda item: (-item[1], item[0]))
    ]


def _determine_readiness_hint(combined_positive_share: float) -> str:
    if combined_positive_share == 0.0:
        return "refine once"
    if combined_positive_share >= CONTINUE_THRESHOLD:
        return "continue"
    if combined_positive_share >= REFINE_ONCE_THRESHOLD:
        return "refine once"
    return "kill and switch"
