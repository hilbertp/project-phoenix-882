from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apps.api.db1_review_read.artifact_reader import (
    ArtifactContractError,
    ArtifactsUnavailableError,
    load_review_artifacts,
)
from tests.db1_review_read_support import write_review_artifacts


class DB1ReviewReadArtifactReaderTests(unittest.TestCase):
    def test_load_review_artifacts_sorts_structures_in_chronological_review_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(artifacts_dir)

            bundle = load_review_artifacts(artifacts_dir)

        self.assertEqual(bundle.manifest.market_contract.tradingview_symbol, "BITGET:BTCUSDT.P")
        self.assertEqual(
            [structure.structure_id for structure in bundle.structures],
            ["db1-fib-0001", "db1-fib-0002", "db1-fib-0003"],
        )

    def test_load_review_artifacts_rejects_contract_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)
            write_review_artifacts(
                artifacts_dir,
                manifest_market_contract={
                    "tradingview_symbol": "BINANCE:BTCUSDT.P",
                    "human_label": "BTCUSDT.P on Binance",
                    "instrument_label": "BTCUSDT perpetual",
                    "timeframe": "1H",
                    "review_window": "last 3 months",
                },
            )

            with self.assertRaises(ArtifactContractError):
                load_review_artifacts(artifacts_dir)

    def test_load_review_artifacts_requires_manifest_and_structure_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir)

            with self.assertRaises(ArtifactsUnavailableError):
                load_review_artifacts(artifacts_dir)


if __name__ == "__main__":
    unittest.main()