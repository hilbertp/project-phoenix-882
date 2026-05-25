#!/usr/bin/env python
"""Deterministic Fib-level movement tracker (the Python twin of the Pine module).

Reproduces, bar-by-bar on the locked candle series, the ordered sequence of Fib
levels price moves through after the 0.786 entry (tracking begins the NEXT bar,
to avoid the intra-entry-bar ambiguity), until the 1.05 stop or the 0.0 target
ends the trade.

Turnaround-aware: a level is recorded every time a bar touches one DIFFERENT from
the last recorded level (consecutive repeats of the same level are collapsed). So
a 0.618 <-> 0.5 chop is captured as 0.618, 0.5, 0.618, 0.5, ... rather than a
single first-touch pair. Within a bar that touches several new levels, they are
appended nearest-first (the order price must traverse).

Levels / stop / target are imported from the Pine module so the two stay in
lockstep. This is the "Required Output" record from the PRD (no PnL / win rate).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.db1_fib_review_pine_read.service import (
    TRACKER_ENTRY_COEFF,
    TRACKER_LEVELS_IN_PATH_ORDER,
    TRACKER_STOP_COEFF,
    TRACKER_TARGET_COEFF,
)
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from scripts.place_fibs_tradingview import CORRECTED_SWINGS


def _level_price(terminal: float, parent: float, coeff: float) -> float:
    return terminal + (parent - terminal) * coeff


def track_reaches(candles, idx, swing) -> dict:
    parent = swing["parent_price"]
    terminal = swing["term_price"]
    term_i = idx[swing["term_ts"]]
    entry_price = _level_price(terminal, parent, TRACKER_ENTRY_COEFF)

    # All tracked levels with their prices; the entry (0.786) is the starting point
    # and is not itself a tracked reach level.
    levels = [
        (coeff, _level_price(terminal, parent, coeff))
        for coeff in TRACKER_LEVELS_IN_PATH_ORDER
    ]

    entered = False
    entry_ts = None
    ended = False
    stopped = False
    targeted = False
    last_coeff = TRACKER_ENTRY_COEFF
    sequence: list[dict] = []

    for j in range(term_i + 1, len(candles)):
        if ended:
            break
        c = candles[j]
        if not entered:
            # First bar whose range contains the entry; tracking starts next bar.
            if c.low <= entry_price <= c.high:
                entered = True
                entry_ts = c.source_timestamp
            continue
        # Levels inside this bar's range that differ from the last recorded level:
        # a move to a new level. Nearest-first = the order price traverses them.
        moves = [
            (coeff, price)
            for coeff, price in levels
            if c.low <= price <= c.high and coeff != last_coeff
        ]
        moves.sort(key=lambda item: abs(item[0] - last_coeff))
        for coeff, price in moves:
            kind = (
                "stop" if coeff == TRACKER_STOP_COEFF
                else "target" if coeff == TRACKER_TARGET_COEFF
                else "reach"
            )
            sequence.append(
                {"coeff": coeff, "ts": c.source_timestamp, "price": price, "kind": kind}
            )
            last_coeff = coeff
            if kind == "stop":
                stopped = ended = True
                break
            if kind == "target":
                targeted = ended = True
                break

    return {
        "entered": entered,
        "entry_ts": entry_ts,
        "entry_price": entry_price,
        "sequence": sequence,
        "stopped": stopped,
        "targeted": targeted,
    }


def describe(swing, result) -> None:
    name = swing.get("name_prefix") or swing.get("name") or "setup"
    span = ""
    print(
        f"Setup: {name} ({swing['direction']}) "
        f"{swing['parent_price']} -> {swing['term_price']}  "
        f"[parent {swing['parent_ts']} | terminal {swing['term_ts']}]{span}"
    )
    if not result["entered"]:
        print("  0.786 entry never touched after the terminal -> no tracking.")
        return
    print(f"  Entry: 0.786 @ {result['entry_ts']}  (price {result['entry_price']:.1f})")
    for n, step in enumerate(result["sequence"], start=1):
        label = (
            "Stopped" if step["kind"] == "stop"
            else "Target" if step["kind"] == "target"
            else "Reached"
        )
        print(
            f"  {n}. {label}: {step['coeff']:<5} @ {step['ts']}  (price {step['price']:.1f})"
        )
    outcome = (
        "Full target reached at 0.0" if result["targeted"]
        else "Stopped out at 1.05" if result["stopped"]
        else "Still open (neither 1.05 nor 0.0 reached in data)"
    )
    print(f"  Outcome: {outcome}")
    print(f"  1.05 stop reached: {result['stopped']} | 0.0 target reached: {result['targeted']}")


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "auto14"
    candles = load_candle_input(DEFAULT_INPUT_PATH).candles
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    swing = next((s for s in CORRECTED_SWINGS if s["name_prefix"] == target), None)
    if swing is None:
        print(f"No corrected swing named {target!r}. Available: "
              f"{[s['name_prefix'] for s in CORRECTED_SWINGS]}")
        return
    describe(swing, track_reaches(candles, idx, swing))


if __name__ == "__main__":
    main()
