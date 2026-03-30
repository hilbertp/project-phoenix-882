from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.types import Candle


class DB1Atr14Tests(unittest.TestCase):
    def test_calculate_atr14_matches_flat_true_range_series(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = [
            Candle(
                timestamp_utc=start + timedelta(hours=index),
                open=100 + index,
                high=105 + index,
                low=95 + index,
                close=100 + index,
                volume=10,
            )
            for index in range(15)
        ]

        atr_values = calculate_atr14(candles)

        self.assertIsNone(atr_values[12])
        self.assertEqual(atr_values[13], 10.0)
        self.assertEqual(atr_values[14], 10.0)


if __name__ == "__main__":
    unittest.main()