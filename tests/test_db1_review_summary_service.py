from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apps.api.db1_review_summary.service import DB1ReviewSummaryService
from tests.db1_review_read_support import write_review_artifacts, write_review_submissions


class DB1ReviewSummaryServiceTests(unittest.TestCase):
    def test_get_summary_payload_counts_outcomes_and_positive_share(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)
            write_review_submissions(artifacts_dir)
            service = DB1ReviewSummaryService(artifacts_dir)

            payload = service.get_summary_payload()

        self.assertEqual(payload["market_contract"]["review_window"], "last 3 months")
        self.assertEqual(payload["summary"]["total_reviewed_structures"], 3)
        self.assertEqual(payload["summary"]["good_enough_count"], 1)
        self.assertEqual(payload["summary"]["adjusted_accept_count"], 1)
        self.assertEqual(payload["summary"]["flatout_wrong_count"], 1)
        self.assertEqual(payload["summary"]["combined_positive_count"], 2)
        self.assertEqual(payload["summary"]["combined_positive_share"], 0.6667)
        self.assertEqual(payload["summary"]["readiness_hint"], "continue")
        self.assertEqual(
            payload["wrong_case_reason_counts"],
            [{"reason": "anchor pair was not usable", "count": 1}],
        )

    def test_get_summary_payload_returns_zero_state_without_submissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)
            service = DB1ReviewSummaryService(artifacts_dir)

            payload = service.get_summary_payload()

        self.assertEqual(payload["summary"]["total_reviewed_structures"], 0)
        self.assertEqual(payload["summary"]["combined_positive_share"], 0.0)
        self.assertEqual(payload["summary"]["readiness_hint"], "refine once")
        self.assertNotIn("wrong_case_reason_counts", payload)

    def test_get_summary_payload_returns_refine_once_for_midrange_positive_share(self) -> None:
        submissions = [
            _submission_row("db1-review-000001", "good_enough"),
            _submission_row("db1-review-000002", "flatout_wrong", note="bad anchor"),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)
            write_review_submissions(artifacts_dir, submissions=submissions)
            service = DB1ReviewSummaryService(artifacts_dir)

            payload = service.get_summary_payload()

        self.assertEqual(payload["summary"]["combined_positive_share"], 0.5)
        self.assertEqual(payload["summary"]["readiness_hint"], "refine once")


def _submission_row(
    submission_id: str,
    review_outcome: str,
    *,
    note: str | None = None,
) -> dict[str, object]:
    return {
        "submission_id": submission_id,
        "recorded_at_utc": "2026-03-30T01:00:00+00:00",
        "structure_id": "db1-fib-0001",
        "proposed_anchor_pair": {
            "parent_anchor_source_timestamp": "2026-01-01T02:00:00",
            "parent_anchor_price": 120.0,
            "terminal_extreme_source_timestamp": "2026-01-01T10:00:00",
            "terminal_extreme_price": 80.0,
        },
        "review_outcome": review_outcome,
        "adjusted_anchor_pair": None,
        "note": note,
        "previous_structure_comparison_used": False,
    }


if __name__ == "__main__":
    unittest.main()