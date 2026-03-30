from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from apps.worker.discovery_bet_1.fib_structures import build_fib_candidates
from apps.worker.discovery_bet_1.types import Pivot, PivotKind, StructureDirection


class DB1FibGenerationTests(unittest.TestCase):
    def test_build_fib_candidates_constructs_parent_to_terminal_structure(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        pivots = [
            Pivot(4, start + timedelta(hours=4), PivotKind.LOW, 100.0, 99.0, 103.0),
            Pivot(10, start + timedelta(hours=10), PivotKind.HIGH, 130.0, 124.0, 130.0),
        ]
        atr_values = [None] * 12
        atr_values[10] = 10.0

        candidates, rejected = build_fib_candidates(pivots, atr_values)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(rejected), 0)
        self.assertEqual(candidates[0].direction, StructureDirection.UP)
        self.assertEqual(candidates[0].anchor_range_low, 99.0)
        self.assertEqual(candidates[0].terminal_extreme.price, 130.0)


if __name__ == "__main__":
    unittest.main()