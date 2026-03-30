from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_HTML = REPO_ROOT / "apps/ui/chart-truth.html"
UI_SCRIPT = REPO_ROOT / "apps/ui/chart-truth.js"
UI_STYLE = REPO_ROOT / "apps/ui/chart-truth.css"


class ChartTruthAssetTests(unittest.TestCase):
    def test_chart_truth_html_references_local_assets_and_required_fields(self) -> None:
        html = UI_HTML.read_text(encoding="utf-8")

        self.assertIn("chart-truth.css", html)
        self.assertIn("chart-truth.js", html)
        self.assertIn("Structure ID", html)
        self.assertIn("Direction", html)
        self.assertIn("Anchor 1", html)
        self.assertIn("Anchor 2", html)
        self.assertNotIn("good_enough", html)
        self.assertNotIn("TradingView Review", html)

    def test_chart_truth_script_loads_single_structure_and_syncs_one_fib(self) -> None:
        script = UI_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("/db1/review/structures?position=1", script)
        self.assertIn("/db1/review/tradingview/sync", script)
        self.assertIn("verifyRenderTruth", script)
        self.assertNotIn("/db1/review/submissions", script)
        self.assertNotIn("/db1/review/summary", script)

    def test_chart_truth_stylesheet_exists(self) -> None:
        self.assertTrue(UI_STYLE.exists())


if __name__ == "__main__":
    unittest.main()