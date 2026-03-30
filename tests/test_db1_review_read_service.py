from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apps.api.db1_review_read.service import (
    DB1ReviewReadService,
    InvalidReviewRequestError,
    ReviewStructureNotFoundError,
)
from tests.db1_review_read_support import write_review_artifacts


class DB1ReviewReadServiceTests(unittest.TestCase):
    def test_get_review_payload_by_index_returns_current_previous_and_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)
            service = DB1ReviewReadService(artifacts_dir=artifacts_dir)

            payload = service.get_review_payload(index=1)

        self.assertEqual(payload.current_structure.structure_id, "db1-fib-0002")
        self.assertEqual(payload.previous_structure.structure_id, "db1-fib-0001")
        self.assertEqual(payload.progress.current_index, 1)
        self.assertEqual(payload.progress.current_position, 2)
        self.assertEqual(payload.progress.total_structures, 3)
        self.assertEqual(payload.progress.label, "structure 2 of 3")

    def test_get_review_payload_by_position_returns_first_structure_without_previous(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)
            service = DB1ReviewReadService(artifacts_dir=artifacts_dir)

            payload = service.get_review_payload(position=1)

        self.assertEqual(payload.current_structure.structure_id, "db1-fib-0001")
        self.assertIsNone(payload.previous_structure)

    def test_get_review_payload_requires_exactly_one_locator(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)
            service = DB1ReviewReadService(artifacts_dir=artifacts_dir)

            with self.assertRaises(InvalidReviewRequestError):
                service.get_review_payload()

            with self.assertRaises(InvalidReviewRequestError):
                service.get_review_payload(index=0, position=1)

    def test_get_review_payload_rejects_out_of_range_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)
            service = DB1ReviewReadService(artifacts_dir=artifacts_dir)

            with self.assertRaises(ReviewStructureNotFoundError):
                service.get_review_payload(index=5)


if __name__ == "__main__":
    unittest.main()