from __future__ import annotations

from apps.worker.discovery_bet_1.anchor_selection import select_parent_anchor
from apps.worker.discovery_bet_1.types import (
    FibCandidate,
    Pivot,
    PivotKind,
    RejectedAnchor,
    StructureDirection,
)


def build_fib_candidates(
    pivots: list[Pivot],
    atr_values: list[float | None],
) -> tuple[list[FibCandidate], list[RejectedAnchor]]:
    candidates: list[FibCandidate] = []
    rejected_anchors: list[RejectedAnchor] = []

    for terminal_extreme in pivots:
        parent_anchor, rejected = select_parent_anchor(
            terminal_extreme=terminal_extreme,
            pivots=pivots,
            atr_values=atr_values,
        )
        rejected_anchors.extend(rejected)
        if parent_anchor is None:
            continue

        candidates.append(
            FibCandidate(
                parent_anchor=parent_anchor,
                terminal_extreme=terminal_extreme,
                direction=_direction_for(parent_anchor),
                anchor_range_low=parent_anchor.candle_low,
                anchor_range_high=parent_anchor.candle_high,
            )
        )

    return candidates, rejected_anchors


def _direction_for(parent_anchor: Pivot) -> StructureDirection:
    if parent_anchor.kind == PivotKind.LOW:
        return StructureDirection.UP
    return StructureDirection.DOWN
