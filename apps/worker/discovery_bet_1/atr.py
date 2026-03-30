from __future__ import annotations

from apps.worker.discovery_bet_1.types import Candle

ATR_PERIOD = 14


def calculate_atr14(candles: list[Candle]) -> list[float | None]:
    return calculate_atr(candles, ATR_PERIOD)


def calculate_atr(candles: list[Candle], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("ATR period must be positive.")
    if not candles:
        return []

    true_ranges: list[float] = []
    previous_close: float | None = None
    for candle in candles:
        if previous_close is None:
            true_range = candle.high - candle.low
        else:
            true_range = max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        true_ranges.append(true_range)
        previous_close = candle.close

    atr_values: list[float | None] = [None] * len(candles)
    if len(candles) < period:
        return atr_values

    running_atr = sum(true_ranges[:period]) / period
    atr_values[period - 1] = running_atr

    for index in range(period, len(candles)):
        running_atr = ((running_atr * (period - 1)) + true_ranges[index]) / period
        atr_values[index] = running_atr

    return atr_values
