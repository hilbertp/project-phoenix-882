"""Fibonacci-level math for the DB1 strategy.

A setup is a clean swing leg between `parent_price` (1.0) and `term_price`
(0.0). Entry, stop, and TP prices are linear retracements along the leg, with
coefficient 1.0 at the parent and 0.0 at the terminal extreme (and 1.05 a hair
beyond parent, where the strategy's invalidation stop sits).

`risk_to_*` ratios express each TP's R-multiple: how much the price moves from
entry to that TP relative to the (entry → init_sl) distance. They are sign-free
positive ratios; the FSM applies them as +R on a profitable touch.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.bot.config import StrategyConfig


@dataclass(frozen=True, slots=True)
class Levels:
    entry: float
    init_sl: float
    tp1: float
    tp2: float
    tp3: float
    risk_per_unit: float
    risk_to_tp1: float
    risk_to_tp2: float
    risk_to_tp3: float
    degenerate: bool  # leg is inverted or zero-width; the FSM must refuse to arm


def _retracement(terminal: float, parent: float, coeff: float) -> float:
    return terminal + (parent - terminal) * coeff


def compute_levels(
    parent_price: float,
    term_price: float,
    direction: str,
    cfg: StrategyConfig,
) -> Levels:
    """Map a leg's two endpoints into entry / stop / TP price levels.

    Degeneracy guard: an "up" leg must have parent < terminal (low to high) and
    a "down" leg parent > terminal. If the leg is inverted or flat the FSM
    refuses to arm — without this an inverted setup yields near-zero risk and
    a bogus -1R wipeout on the first opposing wick.
    """
    entry = _retracement(term_price, parent_price, cfg.entry_coeff)
    init_sl = _retracement(term_price, parent_price, cfg.init_sl_coeff)
    tp1 = _retracement(term_price, parent_price, cfg.tp1_coeff)
    tp2 = _retracement(term_price, parent_price, cfg.tp2_coeff)
    tp3 = _retracement(term_price, parent_price, cfg.tp3_coeff)
    risk = abs(entry - init_sl)
    up = direction == "up"
    degenerate = (
        risk <= 0
        or (up and term_price <= parent_price)
        or (not up and term_price >= parent_price)
    )
    r_tp1 = abs(entry - tp1) / risk if risk else 0.0
    r_tp2 = abs(entry - tp2) / risk if risk else 0.0
    r_tp3 = abs(entry - tp3) / risk if risk else 0.0
    return Levels(
        entry=entry,
        init_sl=init_sl,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        risk_per_unit=risk,
        risk_to_tp1=r_tp1,
        risk_to_tp2=r_tp2,
        risk_to_tp3=r_tp3,
        degenerate=degenerate,
    )
