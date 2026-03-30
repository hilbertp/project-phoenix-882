from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apps.api.db1_review_writeback.models import AnchorPair, ReviewSubmissionRecord
from apps.api.db1_review_writeback.store import ReviewSubmissionStore


class DB1ReviewWritebackStoreTests(unittest.TestCase):
    def test_append_writes_jsonl_review_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ReviewSubmissionStore(Path(temp_dir))
            record = ReviewSubmissionRecord(
                submission_id="db1-review-000001",
                recorded_at_utc="2026-03-30T00:00:00+00:00",
                structure_id="db1-fib-0001",
                proposed_anchor_pair=AnchorPair(
                    parent_anchor_timestamp_utc="2026-01-01T02:00:00+00:00",
                    parent_anchor_price=120.0,
                    terminal_extreme_timestamp_utc="2026-01-01T10:00:00+00:00",
                    terminal_extreme_price=80.0,
                ),
                review_outcome="good_enough",
                adjusted_anchor_pair=None,
                note="looks good",
                previous_structure_comparison_used=False,
            )

            store.append(record)

            stored_lines = store.submissions_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(stored_lines), 1)
        stored_payload = json.loads(stored_lines[0])
        self.assertEqual(stored_payload["structure_id"], "db1-fib-0001")
        self.assertEqual(stored_payload["review_outcome"], "good_enough")

    def test_next_submission_id_increments_from_existing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ReviewSubmissionStore(Path(temp_dir))
            store.submissions_path.write_text(
                '{"submission_id": "db1-review-000001"}\n{"submission_id": "db1-review-000002"}\n',
                encoding="utf-8",
            )

            next_submission_id = store.next_submission_id()

        self.assertEqual(next_submission_id, "db1-review-000003")


if __name__ == "__main__":
    unittest.main()