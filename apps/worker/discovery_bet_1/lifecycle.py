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
                parent_anchor_timestamp_utc=candidate.parent_anchor.timestamp_utc,
                parent_anchor_price=candidate.parent_anchor.price,
                parent_anchor_kind=candidate.parent_anchor.kind,
                terminal_extreme_timestamp_utc=candidate.terminal_extreme.timestamp_utc,
                terminal_extreme_price=candidate.terminal_extreme.price,
                terminal_extreme_kind=candidate.terminal_extreme.kind,
                anchor_range_low=candidate.anchor_range_low,
                anchor_range_high=candidate.anchor_range_high,
                activated_at_utc=candidate.terminal_extreme.timestamp_utc,
                invalidated_at_utc=(
                    candles[invalidation_index].timestamp_utc
                    if invalidation_index is not None
                    else None
                ),
                invalidation_reason=(
                    "anchor_range_breached" if invalidation_index is not None else None
                ),
                source_candle_start_utc=candles[0].timestamp_utc,
                source_candle_end_utc=candles[-1].timestamp_utc,
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
