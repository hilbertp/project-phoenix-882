from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_INDEX = REPO_ROOT / "apps/ui/index.html"
UI_SCRIPT = REPO_ROOT / "apps/ui/review-surface.js"
UI_STYLE = REPO_ROOT / "apps/ui/review-surface.css"


class DB1ReviewSurfaceAssetTests(unittest.TestCase):
    def test_review_surface_html_references_local_assets_and_actions(self) -> None:
        html = UI_INDEX.read_text(encoding="utf-8")

        self.assertIn("review-surface.css", html)
        self.assertIn("review-surface.js", html)
        self.assertIn("good_enough", html)
        self.assertIn("adjusted_accept", html)
        self.assertIn("flatout_wrong", html)
        self.assertIn("Optional review note", html)
        self.assertIn("Market Context", html)
        self.assertIn("Parent Anchor", html)
        self.assertIn("Terminal Extreme", html)
        self.assertIn("Anchor Range", html)
        self.assertIn("Viewing current structure", html)

    def test_review_surface_script_contains_local_in_memory_review_flow(self) -> None:
        script = UI_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("adjustmentMode", script)
        self.assertIn("finalise adjusted_accept", UI_INDEX.read_text(encoding="utf-8"))
        self.assertIn("currentPayload", script)
        self.assertIn("previous_structure", script)
        self.assertIn("loadPosition", script)
        self.assertIn("/db1/review/submissions", script)
        self.assertIn("previousComparisonUsed", script)

    def test_review_surface_stylesheet_exists(self) -> None:
        self.assertTrue(UI_STYLE.exists())


if __name__ == "__main__":
    unittest.main()