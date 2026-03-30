from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apps.api.db1_review_writeback.models import ChartTruthVerdictRecord
from apps.api.db1_review_writeback.store import ChartTruthVerdictStore


class DB1ChartTruthVerdictStoreTests(unittest.TestCase):
    def test_append_writes_jsonl_chart_truth_verdict_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ChartTruthVerdictStore(Path(temp_dir))

            store.append(
                ChartTruthVerdictRecord(
                    structure_id="db1-fib-0001",
                    verdict="up",
                    recorded_at_utc="2026-03-31T00:00:00+00:00",
                )
            )

            stored_lines = store.verdicts_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(stored_lines), 1)
        self.assertEqual(json.loads(stored_lines[0])["verdict"], "up")

    def test_latest_for_structure_returns_most_recent_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ChartTruthVerdictStore(Path(temp_dir))
            store.verdicts_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "structure_id": "db1-fib-0001",
                                "verdict": "down",
                                "recorded_at_utc": "2026-03-31T00:00:00+00:00",
                            },
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "structure_id": "db1-fib-0001",
                                "verdict": "meh",
                                "recorded_at_utc": "2026-03-31T00:05:00+00:00",
                            },
                            sort_keys=True,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            record = store.latest_for_structure("db1-fib-0001")

        assert record is not None
        self.assertEqual(record.verdict, "meh")


if __name__ == "__main__":
    unittest.main()