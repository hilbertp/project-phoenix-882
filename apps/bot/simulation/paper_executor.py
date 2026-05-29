"""Paper-trading executor: drive a FibFSM over a historical candle stream.

For the M2 milestone exit criterion: re-derive a leg's outcome from the bot's
FSM and assert it matches scripts/execute_fib_strategy.execute() trade-by-trade.
The simulator deliberately stays as a thin driver around the FSM so the parity
test is meaningful — the FSM is the live executor's engine, not a duplicate.

Outputs the same {status, r, levels} shape execute() returns (plus an `events`
trace from the FSM for debugging), so callers can `assert sim["status"] ==
gold["status"] and abs(sim["r"] - gold["r"]) < 1e-9`.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Sequence

from apps.bot.config import StrategyConfig
from apps.bot.strategy.fsm import (
    STATUS_DEGENERATE,
    STATUS_OPEN,
    FibFSM,
    FsmState,
    Setup,
)
from apps.worker.discovery_bet_1.types import Candle


def simulate_setup(
    setup_dict: dict,
    candles: Sequence[Candle],
    idx: dict[str, int],
    cfg: StrategyConfig,
) -> dict:
    """Run one setup through the FSM and return the execute()-shaped outcome.

    Args:
        setup_dict: a leg dict from swing_detector.clean_legs(), or the
            CORRECTED_SWINGS-style dict the existing scripts use. Must carry
            direction, parent_price, term_price, term_ts.
        candles: the full candle stream (NOT pre-sliced).
        idx: timestamp -> index into `candles`, as the backtest scripts use.
        cfg: strategy parameters.

    Returns: dict with keys {status, r, events, levels} mirroring
    execute_fib_strategy.execute()'s return value so callers can compare
    directly.
    """
    setup = Setup(
        asset=setup_dict.get("asset", "?"),
        direction=setup_dict["direction"],
        parent_ts=setup_dict.get("parent_ts", ""),
        parent_price=float(setup_dict["parent_price"]),
        term_ts=setup_dict["term_ts"],
        term_price=float(setup_dict["term_price"]),
    )
    fsm = FibFSM(setup, cfg)
    levels_dict = _levels_payload(fsm)

    if fsm.status == STATUS_DEGENERATE:
        return {
            "status": STATUS_DEGENERATE,
            "events": [],
            "r": 0.0,
            "levels": levels_dict,
        }

    term_idx = idx[setup.term_ts]
    for c in candles[term_idx + 1:]:
        if fsm.finished:
            break
        fsm.on_bar(c)

    if not fsm.finished:
        # End of candle stream without a terminal state. Match execute()'s
        # exit semantics: still-armed -> "no_entry"; in-flight -> "open".
        if fsm.state == FsmState.ARMED:
            fsm.mark_no_entry()
        else:
            fsm.status = STATUS_OPEN

    return {
        "status": fsm.status,
        "events": [asdict(e) for e in fsm.events],
        "r": fsm.realized_r,
        "levels": levels_dict,
        "fsm_state": fsm.state.value,
    }


def _levels_payload(fsm: FibFSM) -> dict:
    """Match the execute()'s `levels` dict shape for backward-compatible diffs."""
    lvl = fsm.levels
    return {
        "entry": lvl.entry,
        "init_sl": lvl.init_sl,
        "be_trig": lvl.tp1,
        "tp2": lvl.tp2,
        "tp3": lvl.tp3,
        "r_tp1": lvl.risk_to_tp1,
        "r_tp2": lvl.risk_to_tp2,
        "r_tp3": lvl.risk_to_tp3,
    }
