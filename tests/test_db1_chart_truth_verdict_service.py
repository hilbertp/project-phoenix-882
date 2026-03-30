from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apps.api.db1_review_writeback.service import (
    DB1ReviewWritebackService,
    InvalidChartTruthVerdictError,
)


class DB1ChartTruthVerdictServiceTests(unittest.TestCase):
    def test_save_and_load_chart_truth_verdict_uses_artifact_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DB1ReviewWritebackService(Path(temp_dir))

            save_response = service.save_chart_truth_verdict(
                {"structure_id": "db1-fib-0001", "verdict": "up"}
            )
            load_response = service.get_chart_truth_verdict("db1-fib-0001")

        self.assertEqual(save_response.verdict, "up")
        self.assertEqual(load_response.structure_id, "db1-fib-0001")
        self.assertEqual(load_response.verdict, "up")
        self.assertIsNotNone(load_response.recorded_at_utc)

    def test_save_chart_truth_verdict_rejects_invalid_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DB1ReviewWritebackService(Path(temp_dir))

            with self.assertRaises(InvalidChartTruthVerdictError):
                service.save_chart_truth_verdict(
                    {"structure_id": "db1-fib-0001", "verdict": "sideways"}
                )


if __name__ == "__main__":
    unittest.main()