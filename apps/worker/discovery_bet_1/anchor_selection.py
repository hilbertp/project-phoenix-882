from __future__ import annotations

from apps.worker.discovery_bet_1.types import Pivot, PivotKind, RejectedAnchor

ATR_MULTIPLIER = 2.0


def select_parent_anchor(
    terminal_extreme: Pivot,
    pivots: list[Pivot],
    atr_values: list[float | None],
    atr_multiplier: float = ATR_MULTIPLIER,
) -> tuple[Pivot | None, list[RejectedAnchor]]:
    atr_at_terminal = atr_values[terminal_extreme.index]
    opposite_kind = _opposite_kind(terminal_extreme.kind)
    prior_candidates = [
        pivot
        for pivot in pivots
        if pivot.index < terminal_extreme.index and pivot.kind == opposite_kind
    ]

    rejected: list[RejectedAnchor] = []
    selected: Pivot | None = None

    for candidate in reversed(prior_candidates):
        distance = abs(terminal_extreme.price - candidate.price)
        if atr_at_terminal is None:
            rejected.append(
                _build_rejection(
                    terminal_extreme=terminal_extreme,
                    candidate=candidate,
                    atr_at_terminal=None,
                    distance_to_terminal=None,
                    eligibility_passed=False,
                    rejection_reason="atr_unavailable",
                    selected=selected,
                )
            )
            continue

        threshold = atr_at_terminal * atr_multiplier
        if distance < threshold:
            rejected.append(
                _build_rejection(
                    terminal_extreme=terminal_extreme,
                    candidate=candidate,
                    atr_at_terminal=atr_at_terminal,
                    distance_to_terminal=distance,
                    eligibility_passed=False,
                    rejection_reason="atr_threshold_failed",
                    selected=selected,
                )
            )
            continue

        if selected is None:
            selected = candidate
            continue

        rejected.append(
            _build_rejection(
                terminal_extreme=terminal_extreme,
                candidate=candidate,
                atr_at_terminal=atr_at_terminal,
                distance_to_terminal=distance,
                eligibility_passed=True,
                rejection_reason="older_than_selected_eligible_anchor",
                selected=selected,
            )
        )

    return selected, list(reversed(rejected))


def _opposite_kind(kind: PivotKind) -> PivotKind:
    if kind == PivotKind.HIGH:
        return PivotKind.LOW
    return PivotKind.HIGH


def _build_rejection(
    *,
    terminal_extreme: Pivot,
    candidate: Pivot,
    atr_at_terminal: float | None,
    distance_to_terminal: float | None,
    eligibility_passed: bool,
    rejection_reason: str,
    selected: Pivot | None,
) -> RejectedAnchor:
    return RejectedAnchor(
        terminal_extreme_timestamp_utc=terminal_extreme.timestamp_utc,
        terminal_extreme_price=terminal_extreme.price,
        terminal_extreme_kind=terminal_extreme.kind,
        candidate_anchor_timestamp_utc=candidate.timestamp_utc,
        candidate_anchor_price=candidate.price,
        candidate_anchor_kind=candidate.kind,
        atr14_at_terminal=atr_at_terminal,
        distance_to_terminal=distance_to_terminal,
        eligibility_passed=eligibility_passed,
        rejection_reason=rejection_reason,
        selected_anchor_timestamp_utc=(
            selected.timestamp_utc if selected is not None else None
        ),
    )
