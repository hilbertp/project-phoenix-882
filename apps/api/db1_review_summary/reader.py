from __future__ import annotations

import json
from pathlib import Path

from apps.api.db1_review_summary.models import ReviewSubmissionSnapshot
from apps.api.db1_review_writeback.store import SUBMISSIONS_FILENAME


class ReviewSummaryReadError(Exception):
    """DB1 review summary records could not be read."""


def load_review_submissions(artifacts_dir: Path) -> list[ReviewSubmissionSnapshot]:
    submissions_path = artifacts_dir / SUBMISSIONS_FILENAME
    if not submissions_path.exists():
        return []

    submissions: list[ReviewSubmissionSnapshot] = []
    with submissions_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise ReviewSummaryReadError(
                    "DB1 review submissions contain invalid JSON "
                    f"on line {line_number}."
                ) from error
            submissions.append(_parse_submission(payload, line_number))
    return submissions


def _parse_submission(
    payload: dict[str, object],
    line_number: int,
) -> ReviewSubmissionSnapshot:
    review_outcome = payload.get("review_outcome")
    if not isinstance(review_outcome, str) or review_outcome == "":
        raise ReviewSummaryReadError(
            "DB1 review submissions contain an invalid review_outcome "
            f"on line {line_number}."
        )

    note = payload.get("note")
    if note in (None, ""):
        normalized_note = None
    elif isinstance(note, str):
        normalized_note = note.strip() or None
    else:
        raise ReviewSummaryReadError(
            f"DB1 review submissions contain an invalid note on line {line_number}."
        )

    return ReviewSubmissionSnapshot(
        review_outcome=review_outcome,
        note=normalized_note,
    )
