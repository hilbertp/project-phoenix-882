from __future__ import annotations

import unittest

from apps.api.db1_s2_leg_read.service import DB1S2LegReadService
from apps.api.db1_s2_tradingview_pine_read.service import DB1S2TradingViewPineReadService


class DB1S2LegReadServiceTests(unittest.TestCase):
    def test_get_candidate_leg_payload_builds_ranked_adjacent_alternating_legs(self) -> None:
        payload = DB1S2LegReadService().get_candidate_leg_payload()

        self.assertEqual(payload["sub_bet"], "DB1.S2")
        self.assertEqual(payload["title"], "Candidate Leg Scoring")
        self.assertEqual(payload["detector"]["candidate_leg_rule"]["rule_name"], "adjacent_alternating_pivot_pairs")
        self.assertEqual(
            payload["detector"]["scoring"]["dimensions"],
            ["size", "cleanliness", "prominence", "dominance"],
        )
        self.assertGreater(payload["summary"]["raw_pivot_count"], 0)
        self.assertGreater(payload["summary"]["alternating_pivot_count"], 0)
        self.assertGreater(payload["summary"]["candidate_leg_count"], 0)
        self.assertGreater(len(payload["candidate_legs"]), 0)
        top_candidate = payload["candidate_legs"][0]
        self.assertIn(top_candidate["direction"], {"up", "down"})
        self.assertGreaterEqual(top_candidate["score"], 0.0)
        self.assertLessEqual(top_candidate["score"], 1.0)
        self.assertEqual(top_candidate["rank"], 1)

    def test_get_pine_review_payload_builds_script_for_top_candidates(self) -> None:
        payload = DB1S2TradingViewPineReadService().get_pine_review_payload()

        self.assertEqual(payload["sub_bet"], "DB1.S2")
        self.assertEqual(payload["artifact_filename"], "db1_s2_candidate_leg_review_lane.pine")
        self.assertGreater(payload["displayed_candidate_count"], 0)
        self.assertIn("indicator(\"DB1.S2 Candidate Fib Review\"", payload["pine_script"])
        self.assertIn("selectedRank = input.int", payload["pine_script"])
        self.assertIn("fibLevels = array.from(1.000, 0.941, 0.882, 0.786, 0.618, 0.500, 0.382, 0.236, 0.000)", payload["pine_script"])


if __name__ == "__main__":
    unittest.main()