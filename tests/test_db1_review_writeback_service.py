from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apps.api.db1_review_writeback.service import (
    DB1ReviewWritebackService,
    InvalidReviewSubmissionError,
)


def _base_payload() -> dict[str, object]:
    return {
        "structure_id": "db1-fib-0002",
        "proposed_anchor_pair": {
            "parent_anchor_timestamp_utc": "2026-01-01T05:00:00+00:00",
            "parent_anchor_price": 90.0,
            "terminal_extreme_timestamp_utc": "2026-01-01T14:00:00+00:00",
            "terminal_extreme_price": 130.0,
        },
        "review_outcome": "good_enough",
        "adjusted_anchor_pair": None,
        "note": "looks good",
        "previous_structure_comparison_used": True,
    }


class DB1ReviewWritebackServiceTests(unittest.TestCase):
    def test_submit_review_records_good_enough_submission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DB1ReviewWritebackService(Path(temp_dir))

            response = service.submit_review(_base_payload())

            stored_lines = (Path(temp_dir) / "db1_review_submissions.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(response.structure_id, "db1-fib-0002")
        self.assertEqual(response.review_outcome, "good_enough")
        self.assertEqual(len(stored_lines), 1)

    def test_submit_review_requires_adjusted_anchor_pair_for_adjusted_accept(self) -> None:
        payload = _base_payload()
        payload["review_outcome"] = "adjusted_accept"

        with tempfile.TemporaryDirectory() as temp_dir:
            service = DB1ReviewWritebackService(Path(temp_dir))

            with self.assertRaises(InvalidReviewSubmissionError):
                service.submit_review(payload)

    def test_submit_review_rejects_adjusted_anchor_pair_for_non_adjusted_accept(self) -> None:
        payload = _base_payload()
        payload["adjusted_anchor_pair"] = {
            "parent_anchor_timestamp_utc": "2026-01-01T06:00:00+00:00",
            "parent_anchor_price": 91.0,
            "terminal_extreme_timestamp_utc": "2026-01-01T14:00:00+00:00",
            "terminal_extreme_price": 130.0,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            service = DB1ReviewWritebackService(Path(temp_dir))

            with self.assertRaises(InvalidReviewSubmissionError):
                service.submit_review(payload)

    def test_submit_review_rejects_invalid_outcome(self) -> None:
        payload = _base_payload()
        payload["review_outcome"] = "maybe"

        with tempfile.TemporaryDirectory() as temp_dir:
            service = DB1ReviewWritebackService(Path(temp_dir))

            with self.assertRaises(InvalidReviewSubmissionError):
                service.submit_review(payload)


if __name__ == "__main__":
    unittest.main()