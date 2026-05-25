from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.calibrate_detector import leg_matches

IDX = {f"2026-04-{d:02d}T00:00:00": d for d in range(1, 29)}


def _leg(direction, parent_d, term_d):
    return {
        "direction": direction,
        "parent_ts": f"2026-04-{parent_d:02d}T00:00:00",
        "term_ts": f"2026-04-{term_d:02d}T00:00:00",
    }


class LegMatchesTests(unittest.TestCase):
    def test_exact_match(self) -> None:
        target = _leg("up", 10, 14)
        self.assertTrue(leg_matches(_leg("up", 10, 14), target, IDX))

    def test_within_tolerance(self) -> None:
        target = _leg("up", 10, 14)
        # parent off by 1 bar, term off by 2 bars -> still within TOL_BARS=2
        self.assertTrue(leg_matches(_leg("up", 11, 12), target, IDX))

    def test_direction_mismatch_fails(self) -> None:
        target = _leg("up", 10, 14)
        self.assertFalse(leg_matches(_leg("down", 10, 14), target, IDX))

    def test_outside_tolerance_fails(self) -> None:
        target = _leg("up", 10, 14)
        self.assertFalse(leg_matches(_leg("up", 10, 20), target, IDX))  # term off by 6 bars


if __name__ == "__main__":
    unittest.main()
