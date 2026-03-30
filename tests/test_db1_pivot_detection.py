from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.types import Candle, PivotKind


class DB1PivotDetectionTests(unittest.TestCase):
    def test_detect_local_pivots_uses_two_left_two_right_rule(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        highs = [10, 12, 15, 11, 9, 10, 11, 12, 13]
        lows = [8, 7, 6, 5, 3, 4, 5, 6, 7]
        candles = [
            Candle(
                timestamp_utc=start + timedelta(hours=index),
                open=highs[index] - 1,
                high=highs[index],
                low=lows[index],
                close=lows[index] + 1,
                volume=10,
            )
            for index in range(len(highs))
        ]

        pivots = detect_local_pivots(candles)

        self.assertEqual(len(pivots), 2)
        self.assertEqual((pivots[0].index, pivots[0].kind), (2, PivotKind.HIGH))
        self.assertEqual((pivots[1].index, pivots[1].kind), (4, PivotKind.LOW))


if __name__ == "__main__":
    unittest.main()