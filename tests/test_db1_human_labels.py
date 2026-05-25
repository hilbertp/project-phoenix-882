from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.discovery_bet_1.human_labels import (
    LabelRecord,
    append_label,
    apply_overrides,
    latest_by_key,
    load_labels,
    make_label,
    setup_key,
    truth_setups,
)


def _leg(parent_ts: str, term_ts: str, direction: str = "up", pp: float = 100.0, tp: float = 110.0) -> dict:
    kind_p, kind_t = ("low", "high") if direction == "up" else ("high", "low")
    return {
        "direction": direction,
        "parent_ts": parent_ts, "parent_price": pp, "parent_kind": kind_p,
        "term_ts": term_ts, "term_price": tp, "term_kind": kind_t,
    }


class HumanLabelsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "human_labels.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_make_label_requires_corrected_for_adjust(self) -> None:
        leg = _leg("2026-03-30T01:00:00", "2026-04-01T10:00:00")
        with self.assertRaises(ValueError):
            make_label(leg, "adjust")
        with self.assertRaises(ValueError):
            make_label(leg, "bogus")

    def test_append_and_load_round_trip(self) -> None:
        leg = _leg("2026-03-30T01:00:00", "2026-04-01T10:00:00")
        append_label(make_label(leg, "accept", detector_params={"min_bars": 24}), self.path)
        loaded = load_labels(self.path)
        self.assertEqual(len(loaded), 1)
        self.assertIsInstance(loaded[0], LabelRecord)
        self.assertEqual(loaded[0].verdict, "accept")
        self.assertEqual(loaded[0].setup_key, setup_key(leg["parent_ts"], leg["term_ts"]))

    def test_latest_verdict_per_key_wins(self) -> None:
        leg = _leg("2026-03-30T01:00:00", "2026-04-01T10:00:00")
        append_label(make_label(leg, "accept"), self.path)
        append_label(make_label(leg, "reject"), self.path)
        latest = latest_by_key(load_labels(self.path))
        self.assertEqual(len(latest), 1)
        self.assertEqual(next(iter(latest.values())).verdict, "reject")

    def test_apply_overrides_drops_rejects(self) -> None:
        keep = _leg("2026-01-01T00:00:00", "2026-01-02T00:00:00")
        drop = _leg("2026-02-01T00:00:00", "2026-02-02T00:00:00")
        append_label(make_label(drop, "reject"), self.path)
        out = apply_overrides([keep, drop], path=self.path)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["parent_ts"], keep["parent_ts"])

    def test_apply_overrides_replaces_adjusted_anchors(self) -> None:
        raw = _leg("2026-03-04T21:00:00", "2026-03-08T06:00:00", "down", 74031.8, 66510.0)
        corrected = {
            "direction": "down",
            "parent_ts": "2026-03-04T21:00:00", "parent_price": 74031.8, "parent_kind": "high",
            "term_ts": "2026-03-09T00:00:00", "term_price": 65556.0, "term_kind": "low",
        }
        append_label(make_label(raw, "adjust", corrected=corrected), self.path)
        out = apply_overrides([raw], path=self.path)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["term_ts"], "2026-03-09T00:00:00")
        self.assertEqual(out[0]["term_price"], 65556.0)
        # matched by the ORIGINAL key, so the raw leg's identity still resolves it.
        self.assertEqual(setup_key(raw["parent_ts"], raw["term_ts"]),
                         setup_key("2026-03-04T21:00:00", "2026-03-08T06:00:00"))

    def test_truth_setups_uses_corrected_and_excludes_rejects(self) -> None:
        accepted = _leg("2026-01-01T00:00:00", "2026-01-02T00:00:00")
        rejected = _leg("2026-02-01T00:00:00", "2026-02-02T00:00:00")
        raw = _leg("2026-03-04T21:00:00", "2026-03-08T06:00:00", "down", 74031.8, 66510.0)
        corrected = {"direction": "down", "parent_ts": "2026-03-04T21:00:00",
                     "parent_price": 74031.8, "term_ts": "2026-03-09T00:00:00", "term_price": 65556.0}
        append_label(make_label(accepted, "accept"), self.path)
        append_label(make_label(rejected, "reject"), self.path)
        append_label(make_label(raw, "adjust", corrected=corrected), self.path)
        truths = truth_setups(path=self.path)
        term_ts = {t["term_ts"] for t in truths}
        self.assertIn("2026-01-02T00:00:00", term_ts)       # accepted original
        self.assertIn("2026-03-09T00:00:00", term_ts)       # adjusted -> corrected
        self.assertNotIn("2026-02-02T00:00:00", term_ts)    # rejected excluded


if __name__ == "__main__":
    unittest.main()
