from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from apps.worker.discovery_bet_1.candle_input import SourceInputContractError, load_candle_input, load_candles


class DB1CandleInputTests(unittest.TestCase):
    def test_load_candles_accepts_raw_source_timestamps_and_preserves_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "candles.csv"
            csv_path.write_text(
                "source_timestamp,open,high,low,close,volume\n"
                "2026-03-29T01:00:00,100,105,99,104,10\n"
                "2026-03-29T02:00:00,104,106,103,105,11\n"
                "2026-03-29T04:00:00,105,107,104,106,12\n",
                encoding="utf-8",
            )

            csv_sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest()
            csv_path.with_suffix(".provenance.json").write_text(
                json.dumps(
                    {
                        "acquisition_timestamp_utc": "2026-03-30T15:00:00+00:00",
                        "acquisition_operator_or_process": "tests.test_db1_candle_input",
                        "acquisition_method": "fixture_source_write",
                        "source_file_sha256": csv_sha256,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            loaded_input = load_candle_input(csv_path)

        self.assertEqual(len(loaded_input.candles), 3)
        self.assertEqual(loaded_input.candles[0].source_timestamp, "2026-03-29T01:00:00")
        self.assertEqual(loaded_input.candles[-1].source_timestamp, "2026-03-29T04:00:00")
        self.assertEqual(
            loaded_input.provenance.acquisition_method,
            "fixture_source_write",
        )

    def test_load_candles_rejects_non_ascending_source_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "candles.csv"
            csv_path.write_text(
                "source_timestamp,open,high,low,close,volume\n"
                "2026-01-01T02:00:00,100,105,99,104,10\n"
                "2026-01-01T01:00:00,104,106,103,105,11\n",
                encoding="utf-8",
            )

            csv_path.with_suffix(".provenance.json").write_text(
                json.dumps(
                    {
                        "acquisition_timestamp_utc": "2026-03-30T15:00:00+00:00",
                        "acquisition_operator_or_process": "tests.test_db1_candle_input",
                        "acquisition_method": "fixture_source_write",
                        "source_file_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_candles(csv_path)

    def test_load_candle_input_rejects_missing_provenance_or_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "candles.csv"
            csv_path.write_text(
                "source_timestamp,open,high,low,close,volume\n"
                "2026-03-29T01:00:00,100,105,99,104,10\n",
                encoding="utf-8",
            )

            with self.assertRaises(SourceInputContractError):
                load_candle_input(csv_path)

            csv_path.with_suffix(".provenance.json").write_text(
                json.dumps(
                    {
                        "acquisition_timestamp_utc": "2026-03-30T15:00:00+00:00",
                        "acquisition_operator_or_process": "tests.test_db1_candle_input",
                        "acquisition_method": "fixture_source_write",
                        "source_file_sha256": "bad-hash",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(SourceInputContractError):
                load_candle_input(csv_path)


if __name__ == "__main__":
    unittest.main()