from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from apps.worker.discovery_bet_1.lifecycle import materialize_fib_structures
from apps.worker.discovery_bet_1.types import Candle, FibCandidate, Pivot, PivotKind, StructureDirection


class DB1LifecycleInvalidationTests(unittest.TestCase):
    def test_active_structure_is_not_replaced_until_anchor_range_is_breached(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = []
        for index in range(20):
            low = 105.0
            high = 115.0
            if index == 15:
                low = 99.0
            candles.append(
                Candle(
                    timestamp_utc=start + timedelta(hours=index),
                    open=110.0,
                    high=high,
                    low=low,
                    close=110.0,
                    volume=10.0,
                )
            )

        first_candidate = FibCandidate(
            parent_anchor=Pivot(4, start + timedelta(hours=4), PivotKind.LOW, 100.0, 100.0, 104.0),
            terminal_extreme=Pivot(10, start + timedelta(hours=10), PivotKind.HIGH, 130.0, 124.0, 130.0),
            direction=StructureDirection.UP,
            anchor_range_low=100.0,
            anchor_range_high=104.0,
        )
        blocked_candidate = FibCandidate(
            parent_anchor=Pivot(6, start + timedelta(hours=6), PivotKind.LOW, 101.0, 101.0, 104.0),
            terminal_extreme=Pivot(12, start + timedelta(hours=12), PivotKind.HIGH, 132.0, 126.0, 132.0),
            direction=StructureDirection.UP,
            anchor_range_low=101.0,
            anchor_range_high=104.0,
        )
        replacement_candidate = FibCandidate(
            parent_anchor=Pivot(16, start + timedelta(hours=16), PivotKind.HIGH, 120.0, 118.0, 120.0),
            terminal_extreme=Pivot(17, start + timedelta(hours=17), PivotKind.LOW, 90.0, 90.0, 94.0),
            direction=StructureDirection.DOWN,
            anchor_range_low=118.0,
            anchor_range_high=120.0,
        )

        structures = materialize_fib_structures(
            [first_candidate, blocked_candidate, replacement_candidate],
            candles,
        )

        self.assertEqual(len(structures), 2)
        self.assertEqual(structures[0].terminal_extreme_timestamp_utc, start + timedelta(hours=10))
        self.assertEqual(structures[0].invalidated_at_utc, start + timedelta(hours=15))
        self.assertEqual(structures[1].terminal_extreme_timestamp_utc, start + timedelta(hours=17))


if __name__ == "__main__":
    unittest.main()