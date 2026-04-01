from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_HTML = REPO_ROOT / "apps/ui/db1-s1-swings.html"
UI_SCRIPT = REPO_ROOT / "apps/ui/db1-s1-swings.js"
UI_STYLE = REPO_ROOT / "apps/ui/db1-s1-swings.css"


class DB1S1SwingAssetTests(unittest.TestCase):
    def test_html_references_required_assets_and_gate_one_copy(self) -> None:
        html = UI_HTML.read_text(encoding="utf-8")

        self.assertIn("db1-s1-swings.css", html)
        self.assertIn("db1-s1-swings.js", html)
        self.assertIn("DB1.S1 Raw 1H Swing Detection", html)
        self.assertIn("1H candles with raw swing markers", html)
        self.assertIn("Detected Swings", html)
        self.assertNotIn("fib", html.lower().replace("fib review surface", ""))

    def test_script_fetches_swing_payload_and_renders_svg_chart(self) -> None:
        script = UI_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('/db1/s1/swings', script)
        self.assertIn('renderChart(state.payload.candles, state.payload.swing_highs, state.payload.swing_lows)', script)
        self.assertIn('elements.detectorCopy.textContent = detector.description', script)
        self.assertIn('DEFAULT_VISIBLE_CANDLES = 24 * 7', script)
        self.assertIn('centerOnSwing', script)
        self.assertIn('polygon', script)
        self.assertNotIn('/db1/review/tradingview/sync', script)

    def test_html_exposes_chart_controls(self) -> None:
        html = UI_HTML.read_text(encoding="utf-8")

        self.assertIn('s1-pan-left', html)
        self.assertIn('s1-pan-right', html)
        self.assertIn('s1-zoom-in', html)
        self.assertIn('s1-zoom-out', html)

    def test_stylesheet_exists(self) -> None:
        self.assertTrue(UI_STYLE.exists())


if __name__ == "__main__":
    unittest.main()