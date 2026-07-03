#!/usr/bin/env python
"""Compare frozen engine predictions against the human's manual verdicts.

Joins data/discovery_bet_1/engine_predictions.jsonl (written by
record_predictions.py BEFORE the review) with human_labels.jsonl (written by
the TV review panel DURING it), per setup_key, latest human verdict wins.

For every mismatch it prints a MISTAKE CLASS so patterns are visible:
  OVER-SCORED     engine claimed a better outcome than the human saw
  UNDER-SCORED    engine claimed worse
  SETUP-REJECTED  human says the leg isn't a real swing (detector taste,
                  not an outcome bug)
  UNREVIEWED      no human verdict yet

Usage:
  PYTHONPATH=. .venv/bin/python scripts/compare_predictions.py --run-id 2026-05_6c4x_e941_runner
  PYTHONPATH=. .venv/bin/python scripts/compare_predictions.py            # latest run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRED = REPO_ROOT / "data/discovery_bet_1/engine_predictions.jsonl"
LABELS = REPO_ROOT / "data/discovery_bet_1/human_labels.jsonl"

RANK = {"MISSED": 0, "LOSS": 1, "TP1": 2, "TP2": 3, "TP3": 4}
SCORED_CLASS = {"scratch": "TP1", "partial": "TP2", "win": "TP3",
                "loss": "LOSS", "miss": "MISSED"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", help="default: the most recently recorded run")
    args = ap.parse_args()

    preds = [json.loads(l) for l in PRED.read_text().splitlines() if l.strip()]
    if not preds:
        sys.exit("no predictions recorded yet (scripts/record_predictions.py)")
    run_id = args.run_id or preds[-1]["run_id"]
    run = {p["setup_key"]: p for p in preds if p["run_id"] == run_id}
    if not run:
        sys.exit(f"run_id {run_id!r} not found")

    latest: dict[str, dict] = {}
    for line in LABELS.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        dp = rec.get("detector_params") or {}
        if dp.get("asset") == "BTC" and dp.get("interval") == "1h":
            key = rec.get("setup_key") or f"{rec.get('parent_ts')}|{rec.get('term_ts')}"
            latest[key] = rec

    print(f"run_id: {run_id}  ({len(run)} predictions)\n")
    print(f"{'setup':<37}{'engine':>7}{'human':>7}   verdict")
    print("-" * 75)
    tallies = {"MATCH": 0, "OVER-SCORED": 0, "UNDER-SCORED": 0,
               "SETUP-REJECTED": 0, "UNREVIEWED": 0}
    for key, p in sorted(run.items()):
        rec = latest.get(key)
        eng = p["engine_class"]
        if rec is None:
            cls, human = "UNREVIEWED", "-"
        else:
            dp = rec.get("detector_params") or {}
            if rec.get("verdict") == "accept":
                human = SCORED_CLASS.get(dp.get("scored_outcome"), "?")
            elif dp.get("wrong_kind") == "outcome":
                human = dp.get("expected_outcome", "?")
            elif dp.get("wrong_kind") == "setup":
                human = "not-a-swing"
            else:
                human = rec.get("verdict", "?")
            if human == "not-a-swing":
                cls = "SETUP-REJECTED"
            elif human == eng:
                cls = "MATCH"
            elif RANK.get(eng, -1) > RANK.get(human, -1):
                cls = "OVER-SCORED"
            else:
                cls = "UNDER-SCORED"
        tallies[cls] = tallies.get(cls, 0) + 1
        mark = "  ✓" if cls == "MATCH" else f"  ← {cls}" if cls != "UNREVIEWED" else ""
        print(f"{p['parent_ts'][:16]} {p['direction']:<5}{eng:>7}{human:>12}{mark}")
    print("\nsummary:", "  ".join(f"{k}={v}" for k, v in tallies.items() if v))
    reviewed = sum(v for k, v in tallies.items() if k != "UNREVIEWED")
    if reviewed:
        print(f"engine accuracy on reviewed outcomes: "
              f"{tallies['MATCH']}/{reviewed} "
              f"({100*tallies['MATCH']/reviewed:.0f}%)")
    print("\nnext: mismatches -> inspect the 5m tape per setup, decide rule vs "
          "label, and absorb into tests/test_execute_outcome_ground_truth.py")


if __name__ == "__main__":
    main()
