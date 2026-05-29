#!/usr/bin/env python
"""Execute the theoretical Fib trade plan on a single setup and narrate it.

The trade plan is one of the regimes in REGIMES below; the FIRST entry is the
live default (entry | initial SL | a TP1 partial that also drags SL to break-even
| TP2 | TP3). Sizing: TP1 25%, TP2 60%, TP3 15% (runner).

Bar-by-bar, conservative (one decisive event per bar). The initial SL is an
intrabar hard stop; the break-even stop (SL at entry after the TP1 partial) is
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

# Regime catalog -- the single source of truth. The FIRST entry is the live
# default: it drives execute()'s default args, the review panel, and this CLI.
# Every entry is scored side by side in the dashboard. be_trig_c doubles as TP1
# (take p1, then drag SL to entry). Add or reorder regimes here.
REGIMES = [
    {"slug": "x941", "label": "0.941 entry",
     "params": dict(entry_c=0.941, init_sl_c=1.05, be_trig_c=0.882, tp2_c=0.5, tp3_c=0.0)},
    {"slug": "x882", "label": "0.882 entry",
     "params": dict(entry_c=0.882, init_sl_c=1.05, be_trig_c=0.786, tp2_c=0.5, tp3_c=0.0)},
    {"slug": "x786", "label": "0.786 entry",
     "params": dict(entry_c=0.786, init_sl_c=1.05, be_trig_c=0.618, tp2_c=0.382, tp3_c=0.0)},
]
_DEFAULT = REGIMES[0]["params"]
ENTRY_C = _DEFAULT["entry_c"]
INIT_SL_C = _DEFAULT["init_sl_c"]
BE_TRIG_C = _DEFAULT["be_trig_c"]
TP2_C = _DEFAULT["tp2_c"]
TP3_C = _DEFAULT["tp3_c"]
P_TP1, P_TP2, P_TP3 = 0.25, 0.60, 0.15

# Scaled-entry strategy: fill three tranches as price retraces deeper, share the
# 1.05 stop, drag to BLENDED break-even once price reclaims the average entry,
# then scale out partials. Weights sum to 100%.
SCALED_TRANCHES = [(0.786, 0.50), (0.882, 0.25), (0.941, 0.25)]  # (coeff, weight)
SCALED_SL_C = 1.05
# Exit philosophy: take ONE small partial, then let the runner ride a lagging stop
# (don't scale out a chunk at every level). 25% off at TP1 (0.618); the remaining
# 75% rides to the 0.0 target, protected by an SL that lags up behind price --
# blended break-even first, then trailed to 0.618 once price tags 0.5.
SCALED_TP1_C, SCALED_TP1_FRAC = 0.618, 0.25
SCALED_TRAIL_AT, SCALED_TRAIL_TO = 0.5, 0.618   # tag 0.5 -> lag SL up to 0.618
SCALED_TARGET_C = 0.0
# Drag SL to blended break-even once price (from its deepest fill) recovers to this
# level. The 941->882 case still sits below the blended entry, so the executor also
# requires price to reclaim the blended entry before arming (no underwater stop).
SCALED_RECOVER = {0.941: 0.882, 0.882: 0.786, 0.786: 0.618}


def _lvl(terminal: float, parent: float, coeff: float) -> float:
    return terminal + (parent - terminal) * coeff


def execute(
    candles,
    idx,
    swing,
    *,
    entry_c: float = ENTRY_C,
    init_sl_c: float = INIT_SL_C,
    be_trig_c: float = BE_TRIG_C,
    tp2_c: float = TP2_C,
    tp3_c: float = TP3_C,
    p1: float = P_TP1,
    p2: float = P_TP2,
    p3: float = P_TP3,
) -> dict:
    parent, terminal = swing["parent_price"], swing["term_price"]
    ti = idx[swing["term_ts"]]
    up = swing["direction"] == "up"
    entry = _lvl(terminal, parent, entry_c)
    init_sl = _lvl(terminal, parent, init_sl_c)
    be_trig = _lvl(terminal, parent, be_trig_c)
    tp2 = _lvl(terminal, parent, tp2_c)
    tp3 = _lvl(terminal, parent, tp3_c)
    risk = abs(entry - init_sl)
    # Degenerate/inverted geometry: terminal must be beyond parent in the trade
    # direction (up => high above the low; down => low below the high). Without
    # this guard an inverted leg yields a near-zero risk and a bogus -1R wipeout.
    degenerate = (
        risk <= 0
        or (up and terminal <= parent)
        or (not up and terminal >= parent)
    )
    r_tp1 = abs(entry - be_trig) / risk if risk else 0.0
    r_tp2 = abs(entry - tp2) / risk if risk else 0.0
    r_tp3 = abs(entry - tp3) / risk if risk else 0.0

    levels = {
        "entry": entry, "init_sl": init_sl, "be_trig": be_trig, "tp2": tp2, "tp3": tp3,
        "r_tp1": r_tp1, "r_tp2": r_tp2, "r_tp3": r_tp3,
    }
    events: list[tuple[str, str, float]] = []
    if degenerate:
        return {"status": "degenerate", "events": events, "r": 0.0, "levels": levels}

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
    events.append((f"Entry {entry_c}", candles[entry_bar].source_timestamp, entry))

    # The entry bar is skipped entirely (evaluation starts the NEXT bar), matching
    # the reach engine (scripts/track_fib_reaches.py) which begins tracking after
    # the fill to avoid intra-entry-bar ambiguity. The old code allowed an entry-bar
    # stop-out but never an entry-bar TP -- an asymmetry that fabricated losses,
    # worst for deep entries whose TP1->SL band a single bar often spans.
    phase, sl, realized = 1, init_sl, 0.0
    for j in range(entry_bar + 1, len(candles)):
        c = candles[j]
        if phase == 1:
            hit_tp1 = c.high >= be_trig if up else c.low <= be_trig
            hit_sl = c.low <= sl if up else c.high >= sl
            # Nearest-first within a bar (reach-engine convention): entry sits
            # between TP1 and the initial SL, TP1 being the nearer level, so a bar
            # spanning both traverses TP1 first.
            if hit_tp1:
                phase, sl = 2, entry
                realized += p1 * r_tp1
                events.append((f"TP1 {be_trig_c} - take {p1:.0%}, SL -> entry (break-even)", c.source_timestamp, be_trig))
            elif hit_sl:
                events.append((f"Initial SL {init_sl_c} - full loss", c.source_timestamp, sl))
                return {"status": "wipeout", "events": events, "r": -1.0, "levels": levels}
        elif phase == 2:
            # Intrabar TP wick precedes the bar's close, so a TP2 touch is taken
            # before the close-based break-even stop is evaluated.
            if (up and c.high >= tp2) or (not up and c.low <= tp2):
                phase = 3
                realized += p2 * r_tp2
                events.append((f"TP2 {tp2_c} - take {p2:.0%}", c.source_timestamp, tp2))
            elif (up and c.close <= sl) or (not up and c.close >= sl):
                events.append(("Break-even stop (close at entry) - scratch remainder at 0R", c.source_timestamp, sl))
                return {"status": "tp1_then_scratch", "events": events, "r": realized, "levels": levels}
        else:
            if (up and c.high >= tp3) or (not up and c.low <= tp3):
                realized += p3 * r_tp3
                events.append((f"TP3 {tp3_c} - take final {p3:.0%} (full target)", c.source_timestamp, tp3))
                return {"status": "tp3_full", "events": events, "r": realized, "levels": levels}
            elif (up and c.close <= sl) or (not up and c.close >= sl):
                events.append(("Break-even stop (close at entry) - scratch runner at 0R", c.source_timestamp, sl))
                return {"status": "tp2_then_scratch", "events": events, "r": realized, "levels": levels}
    return {"status": "open", "events": events, "r": realized, "levels": levels}


def execute_scaled(candles, idx, swing) -> dict:
    """Scaled three-tranche entry with a blended break-even trail and partial TPs.

    Fill 0.786 (50%), 0.882 (25%), 0.941 (25%) as price retraces deeper; all share
    the 1.05 stop. Take ONE small partial (25% at 0.618), then let the 75% runner
    ride a lagging stop: SL -> blended break-even on recovery, then trailed up to
    0.618 once price tags 0.5; the runner exits at the 0.0 target or the lagging SL.

    1R = the full intended position's risk to 1.05, so a full fill stopped at 1.05
    is exactly -1R and a partial fill that stops loses proportionally less. Returns
    the same shape as execute() plus ``level_lines`` for charting.
    """
    parent, terminal = swing["parent_price"], swing["term_price"]
    ti = idx[swing["term_ts"]]
    up = swing["direction"] == "up"

    def P(c):
        return _lvl(terminal, parent, c)

    sl_p = P(SCALED_SL_C)
    r1 = sum(w * abs(c - SCALED_SL_C) for c, w in SCALED_TRANCHES)  # full-position 1R
    level_lines = (
        [{"label": f"entry {c}", "price": P(c), "role": "entry"} for c, _ in SCALED_TRANCHES]
        + [{"label": "SL 1.05", "price": sl_p, "role": "sl"}]
        + [{"label": "TP1 0.618", "price": P(SCALED_TP1_C), "role": "tp"},
           {"label": "TP2 0.5", "price": P(SCALED_TRAIL_AT), "role": "tp"},
           {"label": "TP3 0.0", "price": P(SCALED_TARGET_C), "role": "tp"}]
    )
    levels = {"sl": sl_p, "r1": r1, **{f"e_{c}": P(c) for c, _ in SCALED_TRANCHES},
              "tp1": P(SCALED_TP1_C), "tp2": P(SCALED_TRAIL_AT), "tp3": P(SCALED_TARGET_C)}
    base = {"levels": levels, "level_lines": level_lines}

    if (up and terminal <= parent) or (not up and terminal >= parent):
        return {"status": "degenerate", "events": [], "r": 0.0, **base}

    def hit_deep(c, price):  # price retraced down to a level (deeper, loss side)
        return c.low <= price if up else c.high >= price

    def hit_prof(c, price):  # price recovered up to a level (toward terminal, profit)
        return c.high >= price if up else c.low <= price

    def closed_loss(c, price):  # bar closed beyond a level on the loss side
        return c.close <= price if up else c.close >= price

    events: list[tuple[str, str, float]] = []
    filled: list[tuple[float, float]] = []
    weight = we = realized = 0.0
    be_armed = False
    be_p = 0.0
    sl_coeff = SCALED_SL_C
    tp1_done = False
    entered = False

    for j in range(ti + 1, len(candles)):
        c = candles[j]
        if not entered and ((up and c.high > terminal) or (not up and c.low < terminal)):
            return {"status": "no_trigger", "events": events, "r": 0.0, **base}
        # 1) fills (deep side) -- add any tranche price has now reached
        for cc, w in SCALED_TRANCHES:
            if all(cc != f[0] for f in filled) and hit_deep(c, P(cc)):
                filled.append((cc, w)); weight += w; we += w * cc
                events.append((f"Fill {cc} ({w:.0%})", c.source_timestamp, P(cc)))
                entered = True
        if not entered:
            continue
        e = we / weight  # blended entry coeff
        # 2) hard stop at 1.05 while still pre-break-even (full fill => -1R)
        if not be_armed and hit_deep(c, sl_p):
            realized = weight * (e - SCALED_SL_C) / r1
            events.append(("SL 1.05 - full stop", c.source_timestamp, sl_p))
            return {"status": "wipeout", "events": events, "r": realized, **base}
        # 3) arm blended break-even at the recovery threshold for the deepest fill,
        #    but never while still below the blended entry (would be an instant stop)
        if not be_armed:
            thr = SCALED_RECOVER[max(f[0] for f in filled)]
            if hit_prof(c, P(thr)) and hit_prof(c, P(e)):
                be_armed, be_p, sl_coeff = True, P(e), e
                events.append(("SL -> blended break-even", c.source_timestamp, be_p))
        # 4) TP1: take ONE 25% partial at 0.618
        if not tp1_done and hit_prof(c, P(SCALED_TP1_C)):
            realized += SCALED_TP1_FRAC * weight * (e - SCALED_TP1_C) / r1
            tp1_done = True
            events.append((f"TP1 {SCALED_TP1_C} - take {SCALED_TP1_FRAC:.0%}", c.source_timestamp, P(SCALED_TP1_C)))
        # 4b) lagging stop: once price tags 0.5, trail the SL up to 0.618
        if be_armed and sl_coeff > SCALED_TRAIL_TO and hit_prof(c, P(SCALED_TRAIL_AT)):
            sl_coeff, be_p = SCALED_TRAIL_TO, P(SCALED_TRAIL_TO)
            events.append((f"SL trails to {SCALED_TRAIL_TO}", c.source_timestamp, be_p))
        # 4c) runner's full target 0.0 -- exit the remaining 75%
        if hit_prof(c, P(SCALED_TARGET_C)):
            rem = 1.0 - (SCALED_TP1_FRAC if tp1_done else 0.0)
            realized += rem * weight * (e - SCALED_TARGET_C) / r1
            events.append((f"TP3 {SCALED_TARGET_C} - exit runner", c.source_timestamp, P(SCALED_TARGET_C)))
            return {"status": "tp_full", "events": events, "r": realized, **base}
        # 5) lagging SL stop (close-based) -- exit the remainder at the trailed level
        if be_armed and closed_loss(c, be_p):
            rem = 1.0 - (SCALED_TP1_FRAC if tp1_done else 0.0)
            realized += rem * weight * (e - sl_coeff) / r1
            status = "tp_then_scratch" if tp1_done else "be_scratch"
            events.append(("SL stop - exit remainder", c.source_timestamp, be_p))
            return {"status": status, "events": events, "r": realized, **base}

    return {"status": "open" if entered else "no_entry", "events": events, "r": realized, **base}


def run_regime(candles, idx, swing, reg: dict) -> dict:
    """Dispatch a regime dict to the right executor (scaled vs single-entry)."""
    if reg.get("scaled"):
        return execute_scaled(candles, idx, swing)
    return execute(candles, idx, swing, **reg["params"])


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
    print(f"  Entry {ENTRY_C} = {lv['entry']:.1f} | Initial SL {INIT_SL_C} = {lv['init_sl']:.1f} | risk = {abs(lv['entry']-lv['init_sl']):.1f}")
    print(f"  TP1 {BE_TRIG_C} = {lv['be_trig']:.1f} ({lv['r_tp1']:.2f}R) | TP2 {TP2_C} = {lv['tp2']:.1f} ({lv['r_tp2']:.2f}R) | TP3 {TP3_C} = {lv['tp3']:.1f} ({lv['r_tp3']:.2f}R)")
    print(f"  Sizing: TP1 {P_TP1:.0%} / TP2 {P_TP2:.0%} / TP3 {P_TP3:.0%}")
    print("  Execution:")
    for label, ts, price in res["events"]:
        print(f"    {ts}  {label}  (@ {price:.1f})")
    print(f"  Outcome: {res['status']}  |  blended result = {res['r']:+.3f}R")


if __name__ == "__main__":
    main()
