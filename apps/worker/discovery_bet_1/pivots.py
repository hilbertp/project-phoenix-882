from __future__ import annotations

from apps.worker.discovery_bet_1.types import Candle, Pivot, PivotKind

LEFT_BARS = 2
RIGHT_BARS = 2


def detect_local_pivots(candles: list[Candle]) -> list[Pivot]:
    pivots: list[Pivot] = []
    for index in range(LEFT_BARS, len(candles) - RIGHT_BARS):
        candle = candles[index]
        left = candles[index - LEFT_BARS : index]
        right = candles[index + 1 : index + RIGHT_BARS + 1]

        if all(candle.high > other.high for other in left + right):
            pivots.append(
                Pivot(
                    index=index,
                    timestamp_utc=candle.timestamp_utc,
                    kind=PivotKind.HIGH,
                    price=candle.high,
                    candle_low=candle.low,
                    candle_high=candle.high,
                )
            )

        if all(candle.low < other.low for other in left + right):
            pivots.append(
                Pivot(
                    index=index,
                    timestamp_utc=candle.timestamp_utc,
                    kind=PivotKind.LOW,
                    price=candle.low,
                    candle_low=candle.low,
                    candle_high=candle.high,
                )
            )

    return sorted(pivots, key=lambda pivot: (pivot.index, pivot.kind.value))
