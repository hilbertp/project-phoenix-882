from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apps.worker.discovery_bet_1.run_generator import run_generation


class DB1GeneratorRunTests(unittest.TestCase):
    def test_run_generation_produces_locked_market_artifacts_from_manual_csv(self) -> None:
        rows = [
            ("2026-01-01T00:00:00Z", 108, 110, 106, 108, 10),
            ("2026-01-01T01:00:00Z", 110, 112, 108, 110, 10),
            ("2026-01-01T02:00:00Z", 112, 114, 110, 112, 10),
            ("2026-01-01T03:00:00Z", 111, 113, 109, 111, 10),
            ("2026-01-01T04:00:00Z", 109, 111, 107, 109, 10),
            ("2026-01-01T05:00:00Z", 95, 100, 90, 95, 10),
            ("2026-01-01T06:00:00Z", 98, 102, 94, 98, 10),
            ("2026-01-01T07:00:00Z", 101, 105, 98, 101, 10),
            ("2026-01-01T08:00:00Z", 104, 108, 101, 104, 10),
            ("2026-01-01T09:00:00Z", 108, 112, 105, 108, 10),
            ("2026-01-01T10:00:00Z", 112, 116, 110, 112, 10),
            ("2026-01-01T11:00:00Z", 116, 120, 114, 116, 10),
            ("2026-01-01T12:00:00Z", 120, 124, 118, 120, 10),
            ("2026-01-01T13:00:00Z", 124, 128, 122, 124, 10),
            ("2026-01-01T14:00:00Z", 126, 130, 124, 126, 10),
            ("2026-01-01T15:00:00Z", 123, 127, 120, 123, 10),
            ("2026-01-01T16:00:00Z", 121, 123, 118, 121, 10),
            ("2026-01-01T17:00:00Z", 119, 121, 116, 119, 10),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "bitget_btcusdt_p_1h_last_3_months.csv"
            input_path.write_text(
                "timestamp_utc,open,high,low,close,volume\n"
                + "\n".join(
                    ",".join(str(value) for value in row) for row in rows
                )
                + "\n",
                encoding="utf-8",
            )

            outputs = run_generation(
                input_path=input_path,
                artifacts_dir=temp_path / "artifacts",
            )

            manifest = json.loads(outputs.manifest_path.read_text(encoding="utf-8"))
            structures_csv = outputs.structures_csv_path.read_text(encoding="utf-8")

        self.assertEqual(outputs.market_symbol, "BITGET:BTCUSDT.P")
        self.assertEqual(manifest["market_contract"]["human_label"], "BTCUSDT.P on Bitget")
        self.assertGreaterEqual(outputs.accepted_structure_count, 1)
        self.assertIn("BITGET:BTCUSDT.P", structures_csv)


if __name__ == "__main__":
    unittest.main()