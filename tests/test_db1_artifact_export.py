from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apps.worker.discovery_bet_1.export import ARTIFACT_SCHEMA_VERSION, export_generation_artifacts
from apps.worker.discovery_bet_1.market_contract import LOCKED_MARKET_CONTRACT
from apps.worker.discovery_bet_1.types import FibStructure, PivotKind, RejectedAnchor, StructureDirection


class DB1ArtifactExportTests(unittest.TestCase):
    def test_export_generation_artifacts_writes_manifest_and_flat_files(self) -> None:
        structure = FibStructure(
            structure_id="db1-fib-0001",
            market_symbol="BITGET:BTCUSDT.P",
            timeframe="1H",
            direction=StructureDirection.UP,
            parent_anchor_source_timestamp="2026-01-01T00:00:00",
            parent_anchor_price=100.0,
            parent_anchor_kind=PivotKind.LOW,
            terminal_extreme_source_timestamp="2026-01-02T00:00:00",
            terminal_extreme_price=130.0,
            terminal_extreme_kind=PivotKind.HIGH,
            anchor_range_low=99.0,
            anchor_range_high=103.0,
            activated_at_source_timestamp="2026-01-02T00:00:00",
            invalidated_at_source_timestamp=None,
            invalidation_reason=None,
            source_candle_start_timestamp="2026-01-01T00:00:00",
            source_candle_end_timestamp="2026-01-03T00:00:00",
        )
        rejection = RejectedAnchor(
            terminal_extreme_source_timestamp="2026-01-02T00:00:00",
            terminal_extreme_price=130.0,
            terminal_extreme_kind=PivotKind.HIGH,
            candidate_anchor_source_timestamp="2026-01-01T00:00:00",
            candidate_anchor_price=90.0,
            candidate_anchor_kind=PivotKind.LOW,
            atr14_at_terminal=10.0,
            distance_to_terminal=40.0,
            eligibility_passed=True,
            rejection_reason="older_than_selected_eligible_anchor",
            selected_anchor_source_timestamp="2026-01-01T01:00:00",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path, structures_jsonl_path, structures_csv_path, rejected_csv_path = export_generation_artifacts(
                artifacts_dir=Path(temp_dir),
                input_path=Path("data/discovery_bet_1/bitget_btcusdt_p_1h_last_3_months.csv"),
                contract=LOCKED_MARKET_CONTRACT,
                source_provenance={
                    "acquisition_timestamp_utc": "2026-03-30T15:00:00+00:00",
                    "acquisition_operator_or_process": "tests.test_db1_artifact_export",
                    "acquisition_method": "fixture_export",
                    "source_file_sha256": "fixture-source-file-sha256",
                },
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
        self.assertEqual(manifest["artifact_schema_version"], ARTIFACT_SCHEMA_VERSION)
        self.assertEqual(
            manifest["source_provenance"]["acquisition_method"],
            "fixture_export",
        )
        self.assertIn("structure_id", structures_csv)
        self.assertIn("rejection_reason", rejected_csv)
        self.assertIn("db1-fib-0001", structures_jsonl)
        self.assertIn("parent_anchor_source_timestamp", structures_csv)


if __name__ == "__main__":
    unittest.main()