"""Finite-state machine for a single DB1 setup.

Mirrors scripts/execute_fib_strategy.execute() exactly. The FSM is fed closed
bars one at a time via on_bar() and returns an event list per bar; once
.finished is True the .status and .realized_r are stable.

State machine:
                                       on_terminal_break
    [ARMED] ---------------------------> [ABORTED] (terminal: no_trigger)
       |
       | on entry-touch (this bar IS the entry bar; TP/SL skipped on it)
       v
    [ENTERED] -- on initial SL wick -> [DONE: wipeout, -1R]
       |
       | on TP1 wick (nearest-first vs SL in same bar)
       v
    [TP1_HIT] -- on close-based BE stop -> [DONE: tp1_then_scratch, +tp1 R]
       |
       | on TP2 wick (taken BEFORE the bar's close evaluates BE)
       v
    [TP2_HIT] -- on close-based BE stop -> [DONE: tp2_then_scratch, +tp1+tp2 R]
       |
       | on TP3 wick
       v
    [DONE: tp3_full, +tp1+tp2+tp3 R]

Terminal states: aborted, wipeout, tp1_then_scratch, tp2_then_scratch,
tp3_full, degenerate, no_entry (set externally when the bar stream is drained
without a fill).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from apps.bot.config import StrategyConfig
from apps.bot.strategy.levels import Levels, compute_levels
from apps.worker.discovery_bet_1.types import Candle


class FsmState(StrEnum):
    ARMED = "armed"
    ENTERED = "entered"
    TP1_HIT = "tp1_hit"
    TP2_HIT = "tp2_hit"
    DONE = "done"
    ABORTED = "aborted"
    DEGENERATE = "degenerate"


# Final status strings, kept identical to execute()'s return-value strings so
# the parity test can compare without translation.
STATUS_NO_TRIGGER = "no_trigger"
STATUS_NO_ENTRY = "no_entry"
STATUS_WIPEOUT = "wipeout"
STATUS_TP1_SCRATCH = "tp1_then_scratch"
STATUS_TP2_SCRATCH = "tp2_then_scratch"
STATUS_TP3_FULL = "tp3_full"
STATUS_DEGENERATE = "degenerate"
STATUS_OPEN = "open"


@dataclass(frozen=True, slots=True)
class FsmEvent:
    """A side-effect emitted by the FSM. M2 uses them for traces + tests; M3
    will translate them into actual exchange order placements/cancels."""

    kind: str            # e.g. "place_entry", "fill_entry", "tp1_hit", "done"
    candle_ts: str | None
    price: float | None
    payload: dict | None = None


@dataclass(frozen=True, slots=True)
class Setup:
    asset: str
    direction: str
    parent_ts: str
    parent_price: float
    term_ts: str
    term_price: float


class FibFSM:
    """One FSM per (asset, setup). Drive it by calling on_bar() per closed bar.

    The FSM does NOT consume bars before the setup's terminal — the caller is
    responsible for slicing the candle stream so on_bar() only sees bars
    strictly after the terminal.
    """

    def __init__(self, setup: Setup, cfg: StrategyConfig):
        self.setup = setup
        self.cfg = cfg
        self.levels: Levels = compute_levels(
            setup.parent_price, setup.term_price, setup.direction, cfg,
        )
        self.realized_r: float = 0.0
        self.status: str | None = None
        self.events: list[FsmEvent] = []
        self._current_sl: float = self.levels.init_sl

        if self.levels.degenerate:
            self.state = FsmState.DEGENERATE
            self.status = STATUS_DEGENERATE
            return

        self.state = FsmState.ARMED
        self._emit("place_entry", None, self.levels.entry, {
            "init_sl": self.levels.init_sl,
            "tp1": self.levels.tp1,
            "tp2": self.levels.tp2,
            "tp3": self.levels.tp3,
        })

    # --- public API -------------------------------------------------------

    @property
    def finished(self) -> bool:
        return self.state in (
            FsmState.DONE, FsmState.ABORTED, FsmState.DEGENERATE,
        )

    @property
    def up(self) -> bool:
        return self.setup.direction == "up"

    def on_bar(self, candle: Candle) -> list[FsmEvent]:
        """Process one closed bar; return any events newly emitted by it."""
        before = len(self.events)
        if self.state == FsmState.ARMED:
            self._step_armed(candle)
        elif self.state == FsmState.ENTERED:
            self._step_entered(candle)
        elif self.state == FsmState.TP1_HIT:
            self._step_tp1_hit(candle)
        elif self.state == FsmState.TP2_HIT:
            self._step_tp2_hit(candle)
        return self.events[before:]

    def mark_no_entry(self) -> None:
        """Caller signals that the candle stream is exhausted without a fill.

        Used by the simulator at end-of-history to match execute()'s "no_entry"
        return value when an armed setup never triggered.
        """
        if self.state == FsmState.ARMED:
            self.state = FsmState.ABORTED
            self.status = STATUS_NO_ENTRY
            self._emit("done", None, None, {"status": STATUS_NO_ENTRY})

    # --- state-step helpers ----------------------------------------------

    def _step_armed(self, c: Candle) -> None:
        lvl = self.levels
        if self.up:
            broke = c.high > self.setup.term_price
            entry_fill = c.low <= lvl.entry
        else:
            broke = c.low < self.setup.term_price
            entry_fill = c.high >= lvl.entry
        # Terminal-break check FIRST — matches execute()'s ordering. A bar
        # that both breaks the terminal AND retraces to entry aborts.
        if broke:
            self.state = FsmState.ABORTED
            self.status = STATUS_NO_TRIGGER
            self._emit("cancel_entry", c.source_timestamp, None,
                       {"reason": "terminal_break"})
            self._emit("done", c.source_timestamp, None,
                       {"status": STATUS_NO_TRIGGER})
            return
        if entry_fill:
            # The current bar IS the entry bar -- TP/SL are NOT evaluated on
            # it (matches execute()'s `range(entry_bar + 1, len(candles))`).
            # By transitioning to ENTERED here without touching TP/SL logic,
            # the NEXT on_bar call (one bar later) becomes phase-1's first
            # evaluation, which is the contract.
            self.state = FsmState.ENTERED
            self._emit("fill_entry", c.source_timestamp, lvl.entry, None)
            self._emit("place_initial_sl", c.source_timestamp, lvl.init_sl,
                       None)
            self._emit("place_tp1", c.source_timestamp, lvl.tp1,
                       {"size_fraction": self.cfg.tp1_size})

    def _step_entered(self, c: Candle) -> None:
        lvl = self.levels
        if self.up:
            hit_tp1 = c.high >= lvl.tp1
            hit_sl = c.low <= self._current_sl
        else:
            hit_tp1 = c.low <= lvl.tp1
            hit_sl = c.high >= self._current_sl
        # Nearest-first within a bar: entry sits between TP1 and the initial
        # SL, with TP1 closer, so a bar that spans both traverses TP1 first.
        if hit_tp1:
            self.realized_r += self.cfg.tp1_size * lvl.risk_to_tp1
            self.state = FsmState.TP1_HIT
            self._current_sl = lvl.entry  # drag SL to break-even
            self._emit("tp1_hit", c.source_timestamp, lvl.tp1, {
                "size_fraction": self.cfg.tp1_size,
                "realized_r": self.realized_r,
            })
            self._emit("cancel_initial_sl", c.source_timestamp, None, None)
            self._emit("place_tp2", c.source_timestamp, lvl.tp2,
                       {"size_fraction": self.cfg.tp2_size})
            return
        if hit_sl:
            self.realized_r = -1.0
            self.state = FsmState.DONE
            self.status = STATUS_WIPEOUT
            self._emit("initial_sl_hit", c.source_timestamp,
                       self._current_sl, None)
            self._emit("done", c.source_timestamp, None,
                       {"status": STATUS_WIPEOUT,
                        "realized_r": self.realized_r})

    def _step_tp1_hit(self, c: Candle) -> None:
        lvl = self.levels
        # Intrabar wick to TP2 is taken BEFORE evaluating the bar's close-based
        # BE stop — matches execute()'s ordering and the reach-engine.
        if self.up and c.high >= lvl.tp2:
            self._take_tp2(c)
            return
        if not self.up and c.low <= lvl.tp2:
            self._take_tp2(c)
            return
        if self._close_breaks_be(c):
            self.state = FsmState.DONE
            self.status = STATUS_TP1_SCRATCH
            self._emit("be_stop_close", c.source_timestamp,
                       self._current_sl, {"phase": "tp1_hit"})
            self._emit("done", c.source_timestamp, None,
                       {"status": STATUS_TP1_SCRATCH,
                        "realized_r": self.realized_r})

    def _step_tp2_hit(self, c: Candle) -> None:
        lvl = self.levels
        if self.up and c.high >= lvl.tp3:
            self._take_tp3(c)
            return
        if not self.up and c.low <= lvl.tp3:
            self._take_tp3(c)
            return
        if self._close_breaks_be(c):
            self.state = FsmState.DONE
            self.status = STATUS_TP2_SCRATCH
            self._emit("be_stop_close", c.source_timestamp,
                       self._current_sl, {"phase": "tp2_hit"})
            self._emit("done", c.source_timestamp, None,
                       {"status": STATUS_TP2_SCRATCH,
                        "realized_r": self.realized_r})

    # --- inner helpers ----------------------------------------------------

    def _take_tp2(self, c: Candle) -> None:
        self.realized_r += self.cfg.tp2_size * self.levels.risk_to_tp2
        self.state = FsmState.TP2_HIT
        self._emit("tp2_hit", c.source_timestamp, self.levels.tp2, {
            "size_fraction": self.cfg.tp2_size,
            "realized_r": self.realized_r,
        })
        self._emit("place_tp3", c.source_timestamp, self.levels.tp3,
                   {"size_fraction": self.cfg.tp3_size})

    def _take_tp3(self, c: Candle) -> None:
        self.realized_r += self.cfg.tp3_size * self.levels.risk_to_tp3
        self.state = FsmState.DONE
        self.status = STATUS_TP3_FULL
        self._emit("tp3_hit", c.source_timestamp, self.levels.tp3, {
            "size_fraction": self.cfg.tp3_size,
            "realized_r": self.realized_r,
        })
        self._emit("done", c.source_timestamp, None,
                   {"status": STATUS_TP3_FULL,
                    "realized_r": self.realized_r})

    def _close_breaks_be(self, c: Candle) -> bool:
        if self.up:
            return c.close <= self._current_sl
        return c.close >= self._current_sl

    def _emit(self, kind: str, ts: str | None, price: float | None,
              payload: dict | None) -> None:
        self.events.append(FsmEvent(kind=kind, candle_ts=ts, price=price,
                                    payload=payload))


def run_fsm(setup: Setup, candles: Sequence[Candle], cfg: StrategyConfig) -> FibFSM:
    """Convenience: drive a fresh FSM over a candle stream until terminal.

    `candles` must start AFTER the setup's terminal bar (i.e. the first
    element is the bar where pre-trigger evaluation begins). If the FSM
    reaches the end of the stream still armed or in-flight, the final state
    is "no_entry" (armed -> aborted) or "open" (entered but no resolution).
    """
    fsm = FibFSM(setup, cfg)
    for c in candles:
        if fsm.finished:
            break
        fsm.on_bar(c)
    if not fsm.finished:
        if fsm.state == FsmState.ARMED:
            fsm.mark_no_entry()
        else:
            # Entered but unresolved by end of history -> "open"
            fsm.status = STATUS_OPEN
    return fsm
