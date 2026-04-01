from __future__ import annotations

from pathlib import Path

from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.market_contract import LOCKED_MARKET_CONTRACT, market_contract_as_dict
from apps.worker.discovery_bet_1.pivots import LEFT_BARS, RIGHT_BARS, detect_local_pivots
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from apps.worker.discovery_bet_1.types import PivotKind


class DB1S1SwingReadError(Exception):
    """The DB1.S1 swing read payload could not be built."""


class DB1S1SwingReadService:
    def __init__(self, input_path: Path = DEFAULT_INPUT_PATH) -> None:
        self._input_path = input_path

    def get_swing_payload(self) -> dict[str, object]:
        try:
            loaded_input = load_candle_input(self._input_path)
        except Exception as error:
            raise DB1S1SwingReadError(str(error)) from error

        candles = loaded_input.candles
        swings = detect_local_pivots(candles)
        swing_highs = [swing for swing in swings if swing.kind == PivotKind.HIGH]
        swing_lows = [swing for swing in swings if swing.kind == PivotKind.LOW]

        return {
            "sub_bet": "DB1.S1",
            "title": "Raw 1H Swing Detection",
            "market_contract": market_contract_as_dict(LOCKED_MARKET_CONTRACT),
            "detector": {
                "rule_name": "strict_local_pivot_2_left_2_right",
                "description": (
                    "Swing high: candle high strictly greater than the highs of the previous 2 and next 2 candles. "
                    "Swing low: candle low strictly less than the lows of the previous 2 and next 2 candles."
                ),
                "left_bars": LEFT_BARS,
                "right_bars": RIGHT_BARS,
            },
            "summary": {
                "candle_count": len(candles),
                "swing_count": len(swings),
                "swing_high_count": len(swing_highs),
                "swing_low_count": len(swing_lows),
                "source_start_timestamp": candles[0].source_timestamp,
                "source_end_timestamp": candles[-1].source_timestamp,
            },
            "source_provenance": loaded_input.provenance,
            "candles": candles,
            "swing_highs": swing_highs,
            "swing_lows": swing_lows,
        }