#!/usr/bin/env python
"""Execute the theoretical Fib trade plan on a single setup and narrate it.

Strategy (the user's current discovery plan):
  Entry 0.786 | initial SL 1.05 | at 0.618 take a partial + move SL to entry
  (break-even) | TP2 0.382 | TP3 0.0.
Sizing: TP1 25%, TP2 60%, TP3 15% (runner).

Bar-by-bar, conservative (one decisive event per bar). The initial 1.05 SL is an
intrabar hard stop; the break-even stop (SL at entry after the 0.618 partial) is
CLOSE-based -- a wick through entry does not knock you out, only a close beyond it
-- matching the validated simulator and the user's ground truth.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from scripts.place_fibs_tradingview import CORRECTED_SWINGS

ENTRY_C, INIT_SL_C, BE_TRIG_C, TP2_C, TP3_C = 0.786, 1.05, 0.618, 0.382, 0.0
P_TP1, P_TP2, P_TP3 = 0.25, 0.60, 0.15


def _lvl(terminal: float, parent: float, coeff: float) -> float:
    return terminal + (parent - terminal) * coeff


def execute(candles, idx, swing) -> dict:
    parent, terminal = swing["parent_price"], swing["term_price"]
    ti = idx[swing["term_ts"]]
    up = swing["direction"] == "up"
    entry = _lvl(terminal, parent, ENTRY_C)
    init_sl = _lvl(terminal, parent, INIT_SL_C)
    be_trig = _lvl(terminal, parent, BE_TRIG_C)
    tp2 = _lvl(terminal, parent, TP2_C)
    tp3 = _lvl(terminal, parent, TP3_C)
    risk = abs(entry - init_sl)
    r_tp1 = abs(entry - be_trig) / risk
    r_tp2 = abs(entry - tp2) / risk
    r_tp3 = abs(entry - tp3) / risk

    levels = {
        "entry": entry, "init_sl": init_sl, "be_trig": be_trig, "tp2": tp2, "tp3": tp3,
        "r_tp1": r_tp1, "r_tp2": r_tp2, "r_tp3": r_tp3,
    }
    events: list[tuple[str, str, float]] = []

    entry_bar = None
    for j in range(ti + 1, len(candles)):
        c = candles[j]
        if up:
            if c.high > terminal:
                return {"status": "no_trigger", "events": events, "r": 0.0, "levels": levels}
            if c.low <= entry:
                entry_bar = j
                break
        else:
            if c.low < terminal:
                return {"status": "no_trigger", "events": events, "r": 0.0, "levels": levels}
            if c.high >= entry:
                entry_bar = j
                break
    if entry_bar is None:
        return {"status": "no_entry", "events": events, "r": 0.0, "levels": levels}
    events.append(("Entry 0.786", candles[entry_bar].source_timestamp, entry))

    phase, sl, realized = 1, init_sl, 0.0
    c0 = candles[entry_bar]
    if (up and c0.low <= init_sl) or (not up and c0.high >= init_sl):
        events.append(("Initial SL 1.05 - full loss", c0.source_timestamp, init_sl))
        return {"status": "wipeout", "events": events, "r": -1.0, "levels": levels}

    for j in range(entry_bar + 1, len(candles)):
        c = candles[j]
        if phase == 1:
            if (up and c.low <= sl) or (not up and c.high >= sl):
                events.append(("Initial SL 1.05 - full loss", c.source_timestamp, sl))
                return {"status": "wipeout", "events": events, "r": -1.0, "levels": levels}
            if (up and c.high >= be_trig) or (not up and c.low <= be_trig):
                phase, sl = 2, entry
                realized += P_TP1 * r_tp1
                events.append((f"TP1 0.618 - take {P_TP1:.0%}, SL -> entry (break-even)", c.source_timestamp, be_trig))
        elif phase == 2:
            if (up and c.close <= sl) or (not up and c.close >= sl):
                events.append(("Break-even stop (close at entry) - scratch remainder at 0R", c.source_timestamp, sl))
                return {"status": "tp1_then_scratch", "events": events, "r": realized, "levels": levels}
            if (up and c.high >= tp2) or (not up and c.low <= tp2):
                phase = 3
                realized += P_TP2 * r_tp2
                events.append((f"TP2 0.382 - take {P_TP2:.0%}", c.source_timestamp, tp2))
        else:
            if (up and c.close <= sl) or (not up and c.close >= sl):
                events.append(("Break-even stop (close at entry) - scratch runner at 0R", c.source_timestamp, sl))
                return {"status": "tp2_then_scratch", "events": events, "r": realized, "levels": levels}
            if (up and c.high >= tp3) or (not up and c.low <= tp3):
                realized += P_TP3 * r_tp3
                events.append((f"TP3 0.0 - take final {P_TP3:.0%} (full target)", c.source_timestamp, tp3))
                return {"status": "tp3_full", "events": events, "r": realized, "levels": levels}
    return {"status": "open", "events": events, "r": realized, "levels": levels}


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "auto14"
    candles = load_candle_input(DEFAULT_INPUT_PATH).candles
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    swing = next((s for s in CORRECTED_SWINGS if s["name_prefix"] == target), None)
    if swing is None:
        print(f"No corrected swing named {target!r}. Available: "
              f"{[s['name_prefix'] for s in CORRECTED_SWINGS]}")
        return
    res = execute(candles, idx, swing)
    lv = res["levels"]
    print(f"Setup: {target} ({swing['direction']}) {swing['parent_price']} -> {swing['term_price']}")
    print(f"  Entry 0.786 = {lv['entry']:.1f} | Initial SL 1.05 = {lv['init_sl']:.1f} | risk = {abs(lv['entry']-lv['init_sl']):.1f}")
    print(f"  TP1 0.618 = {lv['be_trig']:.1f} ({lv['r_tp1']:.2f}R) | TP2 0.382 = {lv['tp2']:.1f} ({lv['r_tp2']:.2f}R) | TP3 0.0 = {lv['tp3']:.1f} ({lv['r_tp3']:.2f}R)")
    print(f"  Sizing: TP1 {P_TP1:.0%} / TP2 {P_TP2:.0%} / TP3 {P_TP3:.0%}")
    print("  Execution:")
    for label, ts, price in res["events"]:
        print(f"    {ts}  {label}  (@ {price:.1f})")
    print(f"  Outcome: {res['status']}  |  blended result = {res['r']:+.3f}R")


if __name__ == "__main__":
    main()
