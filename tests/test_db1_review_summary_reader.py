from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apps.api.db1_review_summary.reader import (
    ReviewSummaryReadError,
    load_review_submissions,
)
from tests.db1_review_read_support import write_review_submissions


class DB1ReviewSummaryReaderTests(unittest.TestCase):
    def test_load_review_submissions_reads_valid_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_submissions(artifacts_dir)

            submissions = load_review_submissions(artifacts_dir)

        self.assertEqual(len(submissions), 3)
        self.assertEqual(submissions[0].review_outcome, "good_enough")
        self.assertEqual(submissions[2].note, "anchor pair was not usable")

    def test_load_review_submissions_returns_empty_when_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            submissions = load_review_submissions(Path(temp_dir))

        self.assertEqual(submissions, [])

    def test_load_review_submissions_ignores_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_submissions(artifacts_dir)
            submissions_path = artifacts_dir / "db1_review_submissions.jsonl"
            submissions_path.write_text(
                submissions_path.read_text(encoding="utf-8") + "\n\n",
                encoding="utf-8",
            )

            submissions = load_review_submissions(artifacts_dir)

        self.assertEqual(len(submissions), 3)

    def test_load_review_submissions_raises_for_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            (artifacts_dir / "db1_review_submissions.jsonl").write_text(
                "{not valid json}\n",
                encoding="utf-8",
            )

            with self.assertRaises(ReviewSummaryReadError):
                load_review_submissions(artifacts_dir)


if __name__ == "__main__":
    unittest.main()