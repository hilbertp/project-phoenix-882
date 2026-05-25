#!/usr/bin/env python
"""Retune the DB1 swing detector against accumulated human review labels.

The "retune" half of the human-in-the-loop loop: take the setups you approved or
adjusted in the review controller (the ground truth) and the ones you rejected,
then sweep the detector's (min_bars, ATR-multiple) grid to find the parameters
that reproduce the most truth setups while producing the fewest rejected ones.

  score = (truth setups reproduced) - (rejected setups reproduced)

Run scripts/review_fibs_tradingview.py first to generate labels.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.human_labels import (
    VERDICT_REJECT,
    latest_by_key,
    load_labels,
    truth_setups,
)
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from scripts.place_fibs_tradingview import _clean_legs

MIN_BARS_GRID = (12, 18, 24, 30, 36, 48)
MULT_GRID = (2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0)
TOL_BARS = 2


def leg_matches(leg: dict, target: dict, idx: dict[str, int], tol_bars: int = TOL_BARS) -> bool:
    """A detected leg reproduces a target setup if it runs the same direction and
    both anchors sit within tol_bars candles of the target's anchors."""
    if leg["direction"] != target["direction"]:
        return False

    def near(ts_a: str, ts_b: str) -> bool:
        return ts_a in idx and ts_b in idx and abs(idx[ts_a] - idx[ts_b]) <= tol_bars

    return near(leg["term_ts"], target["term_ts"]) and near(leg["parent_ts"], target["parent_ts"])


def score_params(candles, atr, pivots, idx, truths, rejects, min_bars, mult, tol_bars=TOL_BARS):
    legs = _clean_legs(candles, atr, pivots, min_bars=min_bars, mult=mult)
    matched = sum(1 for t in truths if any(leg_matches(leg, t, idx, tol_bars) for leg in legs))
    bad = sum(1 for r in rejects if any(leg_matches(leg, r, idx, tol_bars) for leg in legs))
    return {
        "min_bars": min_bars,
        "mult": mult,
        "legs": len(legs),
        "matched": matched,
        "missed": len(truths) - matched,
        "reproduced_rejects": bad,
        "recall": matched / len(truths) if truths else 0.0,
        "score": matched - bad,
    }


def _rejected_setups(labels):
    out = []
    for label in latest_by_key(labels).values():
        if label.verdict == VERDICT_REJECT:
            out.append(
                {
                    "direction": label.direction,
                    "parent_ts": label.parent_ts,
                    "term_ts": label.term_ts,
                }
            )
    return out


def main() -> None:
    candles = load_candle_input(DEFAULT_INPUT_PATH).candles
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    atr = calculate_atr14(candles)
    pivots = detect_local_pivots(candles)

    labels = load_labels()
    truths = truth_setups(labels)
    rejects = _rejected_setups(labels)
    if not truths:
        print("No human labels yet. Review setups first:")
        print("  python scripts/review_fibs_tradingview.py")
        return

    print(f"Calibrating against {len(truths)} approved + {len(rejects)} rejected setups "
          f"(match tol = {TOL_BARS} bars)\n")
    results = [
        score_params(candles, atr, pivots, idx, truths, rejects, mb, mult)
        for mb in MIN_BARS_GRID
        for mult in MULT_GRID
    ]
    results.sort(key=lambda r: (r["score"], r["recall"], -r["reproduced_rejects"]), reverse=True)

    print(f"{'min_bars':>8} {'mult':>5} {'legs':>5} {'match':>6} {'miss':>5} {'bad':>4} {'recall':>7} {'score':>6}")
    for r in results[:12]:
        print(f"{r['min_bars']:>8} {r['mult']:>5.1f} {r['legs']:>5} {r['matched']:>6} "
              f"{r['missed']:>5} {r['reproduced_rejects']:>4} {r['recall']:>6.0%} {r['score']:>6}")
    best = results[0]
    print(f"\nBest: min_bars={best['min_bars']} atr_mult={best['mult']} "
          f"(reproduced {best['matched']}/{len(truths)} approved, "
          f"{best['reproduced_rejects']} rejected) -> score {best['score']}")


if __name__ == "__main__":
    main()
