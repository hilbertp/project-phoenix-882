#!/usr/bin/env python
"""Score the human-reviewed DB1 setups under one or more trade regimes.

The ground truth is the human-endorsed setup set from
``data/discovery_bet_1/human_labels.jsonl`` (accept -> original anchors,
adjust -> corrected anchors, add -> a missed setup). Rejects are excluded:
under the latest labelling pass a reject either flagged a wrong OLD outcome
(re-scored fresh here) or removed the duplicate left behind by an adjust, so
``truth_setups`` already yields exactly one copy of each real setup.

Each setup is executed bar-by-bar with scripts/execute_fib_strategy.execute and
the run is scored the way the user defines it:
  N (sample) = triggered trades only (entry filled); shrugs are NOT in N.
  win rate  = (reached >= TP1) / N
  loss rate = wipeouts / N
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.human_labels import truth_setups
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from scripts.execute_fib_strategy import REGIMES, execute

SHRUG = {"no_trigger", "no_entry"}
WIN_CLOSED = {"tp1_then_scratch", "tp2_then_scratch", "tp3_full"}


def score(candles, idx, setups, regime) -> dict:
    outcomes: Counter = Counter()
    triggered_r: list[float] = []
    wins = losses = open_undecided = 0
    reached = Counter()  # tp1 / tp2 / tp3 reach counts (cumulative)
    for s in setups:
        if s["term_ts"] not in idx:
            outcomes["missing_bar"] += 1
            continue
        res = execute(candles, idx, s, **regime)
        st = res["status"]
        outcomes[st] += 1
        if st in SHRUG or st == "degenerate":
            continue
        triggered_r.append(res["r"])
        if st == "wipeout":
            losses += 1
        elif st in WIN_CLOSED or (st == "open" and res["r"] > 0):
            wins += 1
            reached["tp1"] += 1
            if st in ("tp2_then_scratch", "tp3_full"):
                reached["tp2"] += 1
            if st == "tp3_full":
                reached["tp3"] += 1
        else:  # open with r == 0: entered, no TP1 yet, not stopped
            open_undecided += 1
    n = len(triggered_r)
    return {
        "outcomes": outcomes,
        "n": n,
        "wins": wins,
        "losses": losses,
        "open_undecided": open_undecided,
        "reached": reached,
        "avg_r": (sum(triggered_r) / n) if n else 0.0,
    }


def _pct(num, den) -> str:
    return f"{(num / den * 100):.0f}%" if den else "n/a"


def main() -> None:
    candles = load_candle_input(DEFAULT_INPUT_PATH).candles
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    setups = truth_setups()
    print(f"Ground truth: {len(setups)} human-endorsed setups "
          f"(accept + adjust-corrected + add; rejects excluded)\n")

    for reg in REGIMES:
        regime = reg["params"]
        r = score(candles, idx, setups, regime)
        print(f"=== Regime: {reg['label']} ===")
        print("  " + " | ".join(f"{k}={v}" for k, v in regime.items()))
        print("  Outcome breakdown:")
        for o, cnt in r["outcomes"].most_common():
            print(f"    {o:18} {cnt}")
        n = r["n"]
        print(f"  Triggered (N): {n}   "
              f"shrug: {r['outcomes'].get('no_trigger', 0) + r['outcomes'].get('no_entry', 0)}   "
              f"degenerate: {r['outcomes'].get('degenerate', 0)}")
        print(f"  Win rate  (>= TP1)/N : {_pct(r['wins'], n)}  ({r['wins']}/{n})")
        print(f"  Loss rate (wipeout)/N: {_pct(r['losses'], n)}  ({r['losses']}/{n})")
        print(f"  Open/undecided   /N  : {_pct(r['open_undecided'], n)}  ({r['open_undecided']}/{n})")
        print(f"  Reach: TP1 {_pct(r['reached']['tp1'], n)} | "
              f"TP2 {_pct(r['reached']['tp2'], n)} | TP3 {_pct(r['reached']['tp3'], n)}")
        print(f"  Avg R per triggered  : {r['avg_r']:+.3f}R\n")


if __name__ == "__main__":
    main()
