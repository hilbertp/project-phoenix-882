from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from apps.worker.discovery_bet_1.export import export_generation_artifacts
from apps.worker.discovery_bet_1.market_contract import LOCKED_MARKET_CONTRACT
from apps.worker.discovery_bet_1.types import FibStructure, PivotKind, RejectedAnchor, StructureDirection


class DB1ArtifactExportTests(unittest.TestCase):
    def test_export_generation_artifacts_writes_manifest_and_flat_files(self) -> None:
        structure = FibStructure(
            structure_id="db1-fib-0001",
            market_symbol="BITGET:BTCUSDT.P",
            timeframe="1H",
            direction=StructureDirection.UP,
            parent_anchor_timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
            parent_anchor_price=100.0,
            parent_anchor_kind=PivotKind.LOW,
            terminal_extreme_timestamp_utc=datetime(2026, 1, 2, tzinfo=UTC),
            terminal_extreme_price=130.0,
            terminal_extreme_kind=PivotKind.HIGH,
            anchor_range_low=99.0,
            anchor_range_high=103.0,
            activated_at_utc=datetime(2026, 1, 2, tzinfo=UTC),
            invalidated_at_utc=None,
            invalidation_reason=None,
            source_candle_start_utc=datetime(2026, 1, 1, tzinfo=UTC),
            source_candle_end_utc=datetime(2026, 1, 3, tzinfo=UTC),
        )
        rejection = RejectedAnchor(
            terminal_extreme_timestamp_utc=datetime(2026, 1, 2, tzinfo=UTC),
            terminal_extreme_price=130.0,
            terminal_extreme_kind=PivotKind.HIGH,
            candidate_anchor_timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
            candidate_anchor_price=90.0,
            candidate_anchor_kind=PivotKind.LOW,
            atr14_at_terminal=10.0,
            distance_to_terminal=40.0,
            eligibility_passed=True,
            rejection_reason="older_than_selected_eligible_anchor",
            selected_anchor_timestamp_utc=datetime(2026, 1, 1, 1, tzinfo=UTC),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path, structures_jsonl_path, structures_csv_path, rejected_csv_path = export_generation_artifacts(
                artifacts_dir=Path(temp_dir),
                input_path=Path("data/discovery_bet_1/bitget_btcusdt_p_1h_last_3_months.csv"),
                contract=LOCKED_MARKET_CONTRACT,
                candle_count=20,
                pivot_count=2,
                candidate_count=1,
                fib_structures=[structure],
                rejected_anchors=[rejection],
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            structures_csv = structures_csv_path.read_text(encoding="utf-8")
            rejected_csv = rejected_csv_path.read_text(encoding="utf-8")
            structures_jsonl = structures_jsonl_path.read_text(encoding="utf-8")

        self.assertEqual(
            manifest["market_contract"]["tradingview_symbol"],
            "BITGET:BTCUSDT.P",
        )
        self.assertIn("structure_id", structures_csv)
        self.assertIn("rejection_reason", rejected_csv)
        self.assertIn("db1-fib-0001", structures_jsonl)


if __name__ == "__main__":
    unittest.main()