from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from apps.api.db1_review_writeback.models import ReviewSubmissionRecord

SUBMISSIONS_FILENAME = "db1_review_submissions.jsonl"


class ReviewSubmissionStore:
    def __init__(self, artifacts_dir: Path) -> None:
        self._artifacts_dir = artifacts_dir
        self._submissions_path = artifacts_dir / SUBMISSIONS_FILENAME

    @property
    def submissions_path(self) -> Path:
        return self._submissions_path

    def append(self, record: ReviewSubmissionRecord) -> None:
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        with self._submissions_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")

    def next_submission_id(self) -> str:
        line_count = 0
        if self._submissions_path.exists():
            with self._submissions_path.open("r", encoding="utf-8") as handle:
                line_count = sum(1 for line in handle if line.strip())
        return f"db1-review-{line_count + 1:06d}"
