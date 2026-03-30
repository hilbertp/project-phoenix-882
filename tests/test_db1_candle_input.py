from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apps.worker.discovery_bet_1.candle_input import load_candles


class DB1CandleInputTests(unittest.TestCase):
    def test_load_candles_accepts_locked_manual_csv_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "candles.csv"
            csv_path.write_text(
                "timestamp_utc,open,high,low,close,volume\n"
                "2026-01-01T00:00:00Z,100,105,99,104,10\n"
                "2026-01-01T01:00:00Z,104,106,103,105,11\n"
                "2026-01-01T02:00:00Z,105,107,104,106,12\n",
                encoding="utf-8",
            )

            candles = load_candles(csv_path)

        self.assertEqual(len(candles), 3)
        self.assertEqual(candles[0].timestamp_utc.isoformat(), "2026-01-01T00:00:00+00:00")

    def test_load_candles_rejects_non_hourly_or_non_utc_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "candles.csv"
            csv_path.write_text(
                "timestamp_utc,open,high,low,close,volume\n"
                "2026-01-01T00:00:00+01:00,100,105,99,104,10\n"
                "2026-01-01T01:30:00+01:00,104,106,103,105,11\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_candles(csv_path)


if __name__ == "__main__":
    unittest.main()