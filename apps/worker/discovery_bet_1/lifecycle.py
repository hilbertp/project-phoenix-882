from __future__ import annotations

from apps.worker.discovery_bet_1.market_contract import LOCKED_MARKET_CONTRACT
from apps.worker.discovery_bet_1.types import (
    Candle,
    FibCandidate,
    FibStructure,
    StructureDirection,
)


def materialize_fib_structures(
    candidates: list[FibCandidate],
    candles: list[Candle],
) -> list[FibStructure]:
    accepted: list[FibStructure] = []
    active_until_index = -1

    for candidate in sorted(candidates, key=lambda item: item.terminal_extreme.index):
        if candidate.terminal_extreme.index <= active_until_index:
            continue

        invalidation_index = _find_invalidation_index(candidate, candles)
        accepted.append(
            FibStructure(
                structure_id=f"db1-fib-{len(accepted) + 1:04d}",
                market_symbol=LOCKED_MARKET_CONTRACT.tradingview_symbol,
                timeframe=LOCKED_MARKET_CONTRACT.timeframe,
                direction=candidate.direction,
                parent_anchor_source_timestamp=candidate.parent_anchor.source_timestamp,
                parent_anchor_price=candidate.parent_anchor.price,
                parent_anchor_kind=candidate.parent_anchor.kind,
                terminal_extreme_source_timestamp=candidate.terminal_extreme.source_timestamp,
                terminal_extreme_price=candidate.terminal_extreme.price,
                terminal_extreme_kind=candidate.terminal_extreme.kind,
                anchor_range_low=candidate.anchor_range_low,
                anchor_range_high=candidate.anchor_range_high,
                activated_at_source_timestamp=candidate.terminal_extreme.source_timestamp,
                invalidated_at_source_timestamp=(
                    candles[invalidation_index].source_timestamp
                    if invalidation_index is not None
                    else None
                ),
                invalidation_reason=(
                    "anchor_range_breached" if invalidation_index is not None else None
                ),
                source_candle_start_timestamp=candles[0].source_timestamp,
                source_candle_end_timestamp=candles[-1].source_timestamp,
            )
        )

        active_until_index = (
            invalidation_index if invalidation_index is not None else len(candles)
        )

    return accepted


def _find_invalidation_index(
    candidate: FibCandidate,
    candles: list[Candle],
) -> int | None:
    for index in range(candidate.terminal_extreme.index + 1, len(candles)):
        candle = candles[index]
        if _is_anchor_range_breached(
            candidate.direction,
            candle,
            candidate.anchor_range_low,
            candidate.anchor_range_high,
        ):
            return index
    return None


def _is_anchor_range_breached(
    direction: StructureDirection,
    candle: Candle,
    anchor_range_low: float,
    anchor_range_high: float,
) -> bool:
    if direction == StructureDirection.UP:
        return candle.low < anchor_range_low
    return candle.high > anchor_range_high
