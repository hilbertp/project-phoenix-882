from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from apps.worker.discovery_bet_1.anchor_selection import select_parent_anchor
from apps.worker.discovery_bet_1.types import Pivot, PivotKind


class DB1AnchorSelectionTests(unittest.TestCase):
    def test_select_parent_anchor_uses_most_recent_eligible_opposite_pivot(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        terminal_extreme = Pivot(
            index=14,
            timestamp_utc=start + timedelta(hours=14),
            kind=PivotKind.HIGH,
            price=130.0,
            candle_low=124.0,
            candle_high=130.0,
        )
        pivots = [
            Pivot(3, start + timedelta(hours=3), PivotKind.LOW, 90.0, 90.0, 95.0),
            Pivot(7, start + timedelta(hours=7), PivotKind.LOW, 112.0, 112.0, 115.0),
            Pivot(9, start + timedelta(hours=9), PivotKind.LOW, 105.0, 105.0, 109.0),
            terminal_extreme,
        ]
        atr_values = [None] * 20
        atr_values[14] = 10.0

        selected, rejected = select_parent_anchor(terminal_extreme, pivots, atr_values)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.index, 9)
        self.assertEqual([entry.rejection_reason for entry in rejected], [
            "older_than_selected_eligible_anchor",
            "atr_threshold_failed",
        ])


if __name__ == "__main__":
    unittest.main()