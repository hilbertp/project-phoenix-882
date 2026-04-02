from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_HTML = REPO_ROOT / "apps/ui/db1-s2-candidate-legs.html"
UI_SCRIPT = REPO_ROOT / "apps/ui/db1-s2-candidate-legs.js"
UI_STYLE = REPO_ROOT / "apps/ui/db1-s2-candidate-legs.css"


class DB1S2LegAssetTests(unittest.TestCase):
    def test_html_references_required_assets_and_leg_scoring_copy(self) -> None:
        html = UI_HTML.read_text(encoding="utf-8")

        self.assertIn("db1-s2-candidate-legs.css", html)
        self.assertIn("db1-s2-candidate-legs.js", html)
        self.assertIn("DB1.S2 Candidate Leg Scoring", html)
        self.assertIn("Top ranked candidate legs over 1H candles", html)
        self.assertIn("Top leg shortlist", html)
        self.assertNotIn("fib", html.lower())

    def test_script_fetches_candidate_leg_payload_and_renders_chart(self) -> None:
        script = UI_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('/db1/s2/candidate-legs', script)
        self.assertIn('renderCandidateTable', script)
        self.assertIn('centerOnCandidate', script)
        self.assertIn('selected candidate', script)
        self.assertNotIn('/db1/review/tradingview/sync', script)

    def test_stylesheet_exists(self) -> None:
        self.assertTrue(UI_STYLE.exists())


if __name__ == "__main__":
    unittest.main()