from __future__ import annotations

from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.db1_fib_review_pine_read.service import (
    PHOENIX_FIB_LEVELS,
    PINE_ARTIFACT_FILENAME,
    REVIEW_LABEL_TEXT,
    DB1FibReviewPineReadService,
    RejectedSwingRow,
    ReviewStructureRow,
    _build_pine_script,
)

EXPORT_SCRIPT = REPO_ROOT / "scripts/export_db1_fib_review_pine.py"


def _sample_structures() -> list[ReviewStructureRow]:
    return [
        ReviewStructureRow(
            structure_id="db1-fib-0001",
            direction="up",
            parent_timestamp_ms=1_748_052_000_000,
            parent_price=106741.3,
            parent_kind="low",
            terminal_timestamp_ms=1_748_070_000_000,
            terminal_price=108507.6,
            terminal_kind="high",
            invalidated_timestamp_ms=1_748_174_400_000,
        ),
        ReviewStructureRow(
            structure_id="db1-fib-0002",
            direction="down",
            parent_timestamp_ms=1_748_188_800_000,
            parent_price=107692.7,
            parent_kind="high",
            terminal_timestamp_ms=1_748_196_000_000,
            terminal_price=106510.0,
            terminal_kind="low",
            invalidated_timestamp_ms=0,
        ),
    ]


def _sample_parameters() -> dict[str, float]:
    return {
        "min_bars_between_swings": 2,
        "pivot_left_bars": 2,
        "pivot_right_bars": 2,
        "up_move_atr_multiple": 2.0,
        "down_move_atr_multiple": 2.0,
        "atr_length": 14,
    }


class PineBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rejected = [
            RejectedSwingRow(
                terminal_timestamp_ms=1_748_070_000_000,
                candidate_timestamp_ms=1_748_026_800_000,
                candidate_price=107950.4,
                candidate_kind="high",
            )
        ]
        self.script = _build_pine_script(
            _sample_structures(), self.rejected, _sample_parameters()
        )

    def test_declares_v6_overlay_indicator(self) -> None:
        self.assertIn("//@version=6", self.script)
        self.assertIn('indicator("DB1 Auto Fib Candidate Review"', self.script)
        self.assertIn("overlay=true", self.script)

    def test_draws_accepted_swing_high_and_low_markers(self) -> None:
        self.assertIn("Swing High (accepted)", self.script)
        self.assertIn("Swing Low (accepted)", self.script)

    def test_shows_fib_direction_for_both_legs(self) -> None:
        self.assertIn("bullish leg (low -> high)", self.script)
        self.assertIn("bearish leg (high -> low)", self.script)

    def test_draws_exactly_the_phoenix_fib_levels(self) -> None:
        self.assertIn(
            "fibLevels = array.from(0.000, 0.382, 0.500, 0.618, 0.786, 0.882, 0.941, 1.000, 1.050)",
            self.script,
        )
        # 0.236 is not part of the Phoenix set.
        self.assertNotIn("0.236", self.script.split("fibLevels =")[1].split("\n")[0])

    def test_draws_theoretical_trade_plan(self) -> None:
        self.assertIn("showTradePlan = input.bool(true", self.script)
        self.assertIn("Entry (0.786)", self.script)
        self.assertIn("Initial SL: 1.05", self.script)
        self.assertIn("TP1 (0.618): Partial + move SL to entry", self.script)
        self.assertIn("SL after TP1 -> Entry", self.script)
        self.assertIn("TP2 (0.382): Take 80%", self.script)
        self.assertIn("Runner TP3: breakout beyond 0.0", self.script)
        self.assertIn("Theoretical Trade Plan", self.script)
        # Discovery framing only: no buy/sell signal language as a positive call.
        self.assertNotIn("Buy Signal", self.script)
        self.assertNotIn("Sell Signal", self.script)

    def test_parameter_label_lists_all_required_parameters(self) -> None:
        self.assertIn("Min bars between swings", self.script)
        self.assertIn("Up move ATR multiple", self.script)
        self.assertIn("Down move ATR multiple", self.script)
        self.assertIn("ATR length", self.script)
        self.assertIn("minBarsBetweenSwings = 2", self.script)
        self.assertIn("upMoveAtrMultiple = 2.00", self.script)
        self.assertIn("downMoveAtrMultiple = 2.00", self.script)
        self.assertIn("atrLength = 14", self.script)

    def test_review_label_is_review_not_a_trade_signal(self) -> None:
        self.assertIn(REVIEW_LABEL_TEXT, self.script)
        self.assertIn("Auto Fib Review", self.script)
        self.assertIn("not a buy / sell signal", self.script)

    def test_embeds_structure_anchor_data(self) -> None:
        self.assertIn('structIds = array.from("db1-fib-0001", "db1-fib-0002")', self.script)
        self.assertIn("106741.300000", self.script)
        self.assertIn("108507.600000", self.script)

    def test_debug_rejected_swings_are_present_and_gated(self) -> None:
        self.assertIn("showDebugRejected = input.bool(false", self.script)
        self.assertIn("label.style_xcross", self.script)
        self.assertIn("107950.400000", self.script)

    def test_focus_selector_and_fib_toggles_exist(self) -> None:
        self.assertIn("focusStructure = input.int(0", self.script)
        self.assertIn("showFib = input.bool(true", self.script)
        self.assertIn("extendFibRight = input.bool", self.script)

    def test_fib_level_reach_tracker_is_present_and_gated(self) -> None:
        # Toggle + focused-only gating (label budget), and per-bar data collection.
        self.assertIn("showTracker = input.bool(true", self.script)
        self.assertIn("if showTracker and isFocused", self.script)
        self.assertIn("var int[] barTimes = array.new_int()", self.script)
        self.assertIn("array.push(barTimes, time)", self.script)

    def test_tracker_records_ordered_path_with_standard_levels(self) -> None:
        # Path order = distance from the 0.786 entry; favourable side uses 0.236
        # (standard Fib level), NOT the 0.286 from the original PRD draft.
        self.assertIn(
            "trkCoeffs = array.from(0.882, 0.941, 0.618, 1.0, 1.05, 0.5, 0.382, 0.236, 0.0)",
            self.script,
        )
        self.assertNotIn("0.286", self.script)
        self.assertIn("Entry: 0.786", self.script)
        self.assertIn('"Reached: "', self.script)

    def test_tracker_end_conditions_are_stop_and_target(self) -> None:
        # 1.05 stop (index 4) ends with "Stopped:", 0.0 target (index 8) with "Target:".
        self.assertIn("isStop = bestIdx == 4", self.script)
        self.assertIn("isTarget = bestIdx == 8", self.script)
        self.assertIn('"Stopped: "', self.script)
        self.assertIn('"Target: "', self.script)
        self.assertIn("trkEnded := isStop or isTarget", self.script)

    def test_tracker_is_turnaround_aware_not_first_touch(self) -> None:
        # Records each move to a level different from the last (captures 0.618<->0.5
        # round trips), so it tracks trkLast rather than a one-shot reached flag.
        self.assertIn("trkLast = 0.786", self.script)
        self.assertIn("trkLast := cf", self.script)
        self.assertIn("if cf != trkLast", self.script)
        self.assertIn("turnarounds shown", self.script)
        self.assertNotIn("trkReached", self.script)


class PineServiceIntegrationTests(unittest.TestCase):
    def test_get_pine_review_payload_runs_on_locked_market_series(self) -> None:
        payload = DB1FibReviewPineReadService().get_pine_review_payload()

        self.assertEqual(payload["sub_bet"], "DB1")
        self.assertEqual(payload["artifact_filename"], PINE_ARTIFACT_FILENAME)
        self.assertEqual(payload["review_label"], "Auto Fib Review - Theoretical Trade Plan")
        self.assertEqual(payload["levels"], list(PHOENIX_FIB_LEVELS))
        self.assertEqual(
            payload["market_contract"]["review_window"], "last 12 months"
        )
        self.assertEqual(payload["parameters"]["atr_length"], 14)
        self.assertEqual(payload["parameters"]["up_move_atr_multiple"], 2.0)
        self.assertEqual(payload["parameters"]["min_bars_between_swings"], 2)
        self.assertGreater(payload["accepted_structure_count"], 0)
        self.assertGreaterEqual(payload["debug_rejected_count"], 0)
        self.assertIn('indicator("DB1 Auto Fib Candidate Review"', payload["pine_script"])
        self.assertIn("Swing High (accepted)", payload["pine_script"])
        self.assertIn("showTracker = input.bool(true", payload["pine_script"])
        self.assertIn("Entry: 0.786", payload["pine_script"])


class PineExportAssetTests(unittest.TestCase):
    def test_export_script_targets_review_pine_artifact(self) -> None:
        script = EXPORT_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("PINE_ARTIFACT_FILENAME", script)
        self.assertIn("DB1FibReviewPineReadService", script)
        self.assertEqual(PINE_ARTIFACT_FILENAME, "db1_auto_fib_review.pine")


if __name__ == "__main__":
    unittest.main()
