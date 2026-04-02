from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORT_SCRIPT = REPO_ROOT / "scripts/export_db1_s2_tradingview_pine.py"


class DB1S2TradingViewPineAssetTests(unittest.TestCase):
    def test_export_script_targets_db1_s2_pine_artifact(self) -> None:
        script = EXPORT_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("PINE_ARTIFACT_FILENAME", script)
        self.assertIn("DB1S2TradingViewPineReadService", script)


if __name__ == "__main__":
    unittest.main()