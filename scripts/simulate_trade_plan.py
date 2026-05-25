#!/usr/bin/env python
"""Simulate the theoretical Fib trade plan over the validated auto setups.

Plan (fixed Phoenix geometry, fib 0.0 at terminal extreme, 1.0 at parent anchor):
  Entry 0.786 | Initial SL 1.05 | TP1 0.618 (take 25%, move SL->entry)
  | TP2 0.382 (take 60%) | Runner TP3 0.0 (15%, exit at the prior extreme)

Bar-by-bar, conservative (stop-before-target within a bar, one event per bar).
Reports: trigger rate, partial(TP1)/wipe-out/TP2/TP3 rates, and blended R expectancy.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.place_fibs_tradingview import MANUAL_SWINGS, _clean_legs
from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH

ENTRY, SL, TP1, TP2, TP3 = 0.786, 1.05, 0.618, 0.382, 0.0
P1, P2, P3 = 0.25, 0.60, 0.15  # TP1 25% / TP2 60% / runner 15%

RISK = SL - ENTRY  # in leg fractions
R_TP1 = (ENTRY - TP1) / RISK
R_TP2 = (ENTRY - TP2) / RISK
R_TP3 = (ENTRY - TP3) / RISK
# Blended R by furthest outcome (remainder after a hit rides to SL=entry => 0R).
R_WIPE = -1.0
R_TP1_ONLY = P1 * R_TP1
R_TP2_ONLY = P1 * R_TP1 + P2 * R_TP2
R_TP3_FULL = P1 * R_TP1 + P2 * R_TP2 + P3 * R_TP3


def _lvl(terminal: float, parent: float, coeff: float) -> float:
    return terminal + (parent - terminal) * coeff


def simulate(candles, idx, swing):
    pi, ti = idx[swing["parent_ts"]], idx[swing["term_ts"]]
    parent, terminal = swing["parent_price"], swing["term_price"]
    up = swing["direction"] == "up"  # up-setup => LONG
    entry = _lvl(terminal, parent, ENTRY)
    sl0 = _lvl(terminal, parent, SL)
    tp1 = _lvl(terminal, parent, TP1)
    tp2 = _lvl(terminal, parent, TP2)
    tp3 = _lvl(terminal, parent, TP3)

    # Phase 0: wait for entry; moot if price breaks beyond the terminal (0.0) first.
    entry_bar = None
    for j in range(ti + 1, len(candles)):
        c = candles[j]
        if up:
            if c.high > terminal:
                return "no_trigger", 0.0, False
            if c.low <= entry:
                entry_bar = j
                break
        else:
            if c.low < terminal:
                return "no_trigger", 0.0, False
            if c.high >= entry:
                entry_bar = j
                break
    if entry_bar is None:
        return "no_entry_eod", 0.0, False

    phase, sl = 1, sl0
    # Entry bar: its favorable extreme happened BEFORE the fill, so it can only
    # stop out here (no phantom TP). TPs are evaluated from the next bar on.
    c0 = candles[entry_bar]
    if (up and c0.low <= sl0) or (not up and c0.high >= sl0):
        return "wipeout", R_WIPE, True
    for j in range(entry_bar + 1, len(candles)):
        c = candles[j]
        if phase == 1:
            if (up and c.low <= sl) or (not up and c.high >= sl):
                return "wipeout", R_WIPE, True
            if (up and c.high >= tp1) or (not up and c.low <= tp1):
                phase, sl = 2, entry  # partial + move SL to entry
        elif phase == 2:
            # Break-even stop (SL at entry) is CLOSE-based: a wick through entry
            # does not knock you out, only a close beyond it.
            if (up and c.close <= sl) or (not up and c.close >= sl):
                return "tp1_then_scratch", R_TP1_ONLY, True
            if (up and c.high >= tp2) or (not up and c.low <= tp2):
                phase = 3
        else:
            if (up and c.close <= sl) or (not up and c.close >= sl):
                return "tp2_then_scratch", R_TP2_ONLY, True
            if (up and c.high >= tp3) or (not up and c.low <= tp3):
                return "tp3_full", R_TP3_FULL, True
    # Ran out of data: classify by furthest phase reached (open trade).
    if phase == 1:
        return "open_no_tp", 0.0, True
    if phase == 2:
        return "open_tp1", R_TP1_ONLY, True
    return "open_tp2", R_TP2_ONLY, True


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "2026"
    candles = load_candle_input(DEFAULT_INPUT_PATH).candles
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    if mode == "manual":
        swings = MANUAL_SWINGS
    else:
        atr = calculate_atr14(candles)
        piv = detect_local_pivots(candles)
        swings = [
            leg for leg in _clean_legs(candles, atr, piv, min_bars=24, mult=4.0)
            if leg["term_ts"] >= "2026-01-01"
        ]
        for i, leg in enumerate(swings, start=1):
            leg["name"] = f"auto{i}"
    print(f"Simulating {len(swings)} setups ({mode}, ATR x4 / min-bars 24)")
    print(f"Fixed R multiples: TP1={R_TP1:.2f}R TP2={R_TP2:.2f}R TP3={R_TP3:.2f}R wipeout=-1R")
    print(f"Sizing: TP1 {P1:.0%} partial / TP2 {P2:.0%} / runner {P3:.0%}\n")
    rows = []
    from collections import Counter
    outcomes: Counter = Counter()
    for s in swings:
        outcome, r, tr = simulate(candles, idx, s)
        rows.append((s["name"], s["direction"], outcome, r, tr))
        outcomes[outcome] += 1
    print("Outcome breakdown:")
    for o, cnt in outcomes.most_common():
        print(f"  {o:20} {cnt}")
    print()

    triggered = [r for r in rows if r[4]]
    n = len(triggered)
    def rate(pred):
        return sum(1 for r in triggered if pred(r[2])) / n if n else 0.0
    tp1_plus = rate(lambda o: o in ("tp1_then_scratch", "tp2_then_scratch", "tp3_full", "open_tp1", "open_tp2"))
    tp2_plus = rate(lambda o: o in ("tp2_then_scratch", "tp3_full", "open_tp2"))
    tp3 = rate(lambda o: o == "tp3_full")
    wipe = rate(lambda o: o == "wipeout")
    avg_r = sum(r[3] for r in triggered) / n if n else 0.0
    print(f"\nSetups: {len(rows)} | triggered (entry filled): {n} | no-trigger: {len(rows)-n}")
    print(f"Win rate (reached >= TP1 / partial): {tp1_plus:.0%}")
    print(f"Wipe-out rate (SL before TP1):       {wipe:.0%}")
    print(f"Reached TP2:                         {tp2_plus:.0%}")
    print(f"Reached TP3 (runner target):         {tp3:.0%}")
    print(f"Average R per triggered trade:       {avg_r:+.3f}R")


if __name__ == "__main__":
    main()
