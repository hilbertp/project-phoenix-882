from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from apps.api.db1_s2_leg_read.service import DB1S2LegReadService

PINE_ARTIFACT_FILENAME = "db1_s2_candidate_leg_review_lane.pine"
FIB_LEVELS = (1.0, 0.941, 0.882, 0.786, 0.618, 0.5, 0.382, 0.236, 0.0)


class DB1S2TradingViewPineReadError(Exception):
    """The DB1.S2 TradingView Pine payload could not be built."""


@dataclass(frozen=True, slots=True)
class TradingViewCandidateRow:
    candidate_id: str
    rank: int
    direction: str
    score: float
    start_timestamp_ms: int
    start_price: float
    end_timestamp_ms: int
    end_price: float


class DB1S2TradingViewPineReadService:
    def __init__(self, leg_read_service: DB1S2LegReadService | None = None) -> None:
        self._leg_read_service = leg_read_service or DB1S2LegReadService()

    def get_pine_review_payload(self) -> dict[str, object]:
        try:
            candidate_payload = self._leg_read_service.get_candidate_leg_payload()
        except Exception as error:
            raise DB1S2TradingViewPineReadError(str(error)) from error

        candidate_rows = [_build_candidate_row(item) for item in candidate_payload["candidate_legs"]]
        pine_script = _build_pine_script(candidate_rows)
        return {
            "sub_bet": "DB1.S2",
            "title": "TradingView-native candidate review lane",
            "artifact_filename": PINE_ARTIFACT_FILENAME,
            "indicator_title": "DB1.S2 Candidate Fib Review",
            "market_contract": candidate_payload["market_contract"],
            "levels": list(FIB_LEVELS),
            "displayed_candidate_count": len(candidate_rows),
            "candidate_summary": [
                {
                    "candidate_id": row.candidate_id,
                    "rank": row.rank,
                    "direction": row.direction,
                    "score": row.score,
                }
                for row in candidate_rows
            ],
            "pine_script": pine_script,
        }


def _build_candidate_row(candidate: dict[str, Any]) -> TradingViewCandidateRow:
    start_pivot = candidate["start_pivot"]
    end_pivot = candidate["end_pivot"]
    return TradingViewCandidateRow(
        candidate_id=str(candidate["candidate_id"]),
        rank=int(candidate["rank"]),
        direction=str(candidate["direction"]),
        score=float(candidate["score"]),
        start_timestamp_ms=_source_timestamp_to_unix_ms(str(start_pivot["source_timestamp"])),
        start_price=float(start_pivot["price"]),
        end_timestamp_ms=_source_timestamp_to_unix_ms(str(end_pivot["source_timestamp"])),
        end_price=float(end_pivot["price"]),
    )


def _source_timestamp_to_unix_ms(source_timestamp: str) -> int:
    parsed = datetime.fromisoformat(source_timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return int(parsed.timestamp() * 1000)


def _pine_string_rows(rows: list[TradingViewCandidateRow], field_name: str) -> str:
    values = [getattr(row, field_name) for row in rows]
    if not values:
        return "array.from()"
    rendered = ", ".join(f'"{value}"' for value in values)
    return f"array.from({rendered})"


def _pine_int_rows(rows: list[TradingViewCandidateRow], field_name: str) -> str:
    values = [str(int(getattr(row, field_name))) for row in rows]
    if not values:
        return "array.from()"
    return f"array.from({', '.join(values)})"


def _pine_float_rows(rows: list[TradingViewCandidateRow], field_name: str) -> str:
    values = [f"{float(getattr(row, field_name)):.6f}" for row in rows]
    if not values:
        return "array.from()"
    return f"array.from({', '.join(values)})"


def _build_pine_script(rows: list[TradingViewCandidateRow]) -> str:
    candidate_count = max(len(rows), 1)
    candidate_ids = _pine_string_rows(rows, "candidate_id")
    directions = _pine_string_rows(rows, "direction")
    ranks = _pine_int_rows(rows, "rank")
    start_times = _pine_int_rows(rows, "start_timestamp_ms")
    end_times = _pine_int_rows(rows, "end_timestamp_ms")
    start_prices = _pine_float_rows(rows, "start_price")
    end_prices = _pine_float_rows(rows, "end_price")
    scores = _pine_float_rows(rows, "score")
    level_values = ", ".join(f"{level:.3f}" for level in FIB_LEVELS)
    return f'''//@version=6
indicator("DB1.S2 Candidate Fib Review", overlay=true, max_lines_count=500, max_labels_count=500)

candidateCount = {candidate_count}
selectedRank = input.int(1, "Candidate rank", minval=1, maxval=candidateCount)
showShortlistAnchors = input.bool(true, "Show shortlist anchor segments")
showLevelLabels = input.bool(true, "Show fib level labels")
anchorColorUp = color.new(color.teal, 55)
anchorColorDown = color.new(color.orange, 55)
selectedAnchorColor = color.new(color.white, 0)
selectedLevelColor = color.new(color.aqua, 0)
candidateIds = {candidate_ids}
candidateDirections = {directions}
candidateRanks = {ranks}
candidateStartTimes = {start_times}
candidateEndTimes = {end_times}
candidateStartPrices = {start_prices}
candidateEndPrices = {end_prices}
candidateScores = {scores}
fibLevels = array.from({level_values})

var line[] activeLines = array.new_line()
var label[] activeLabels = array.new_label()

f_clear() =>
    while array.size(activeLines) > 0
        line.delete(array.pop(activeLines))
    while array.size(activeLabels) > 0
        label.delete(array.pop(activeLabels))

f_push_line(line value) =>
    array.push(activeLines, value)

f_push_label(label value) =>
    array.push(activeLabels, value)

f_level_price(string direction, float startPrice, float endPrice, float coeff) =>
    direction == "up" ? startPrice + (endPrice - startPrice) * coeff : endPrice + (startPrice - endPrice) * coeff

if barstate.islast
    f_clear()
    maxIndex = array.size(candidateRanks) - 1
    if maxIndex >= 0
        selectedIndex = math.min(math.max(selectedRank - 1, 0), maxIndex)
        selectedDirection = array.get(candidateDirections, selectedIndex)
        selectedStartTime = array.get(candidateStartTimes, selectedIndex)
        selectedEndTime = array.get(candidateEndTimes, selectedIndex)
        selectedStartPrice = array.get(candidateStartPrices, selectedIndex)
        selectedEndPrice = array.get(candidateEndPrices, selectedIndex)
        selectedScore = array.get(candidateScores, selectedIndex)
        selectedId = array.get(candidateIds, selectedIndex)
        xLeft = math.min(selectedStartTime, selectedEndTime)
        xRight = math.max(selectedStartTime, selectedEndTime)

        if showShortlistAnchors
            for index = 0 to maxIndex
                direction = array.get(candidateDirections, index)
                startTime = array.get(candidateStartTimes, index)
                endTime = array.get(candidateEndTimes, index)
                startPrice = array.get(candidateStartPrices, index)
                endPrice = array.get(candidateEndPrices, index)
                rankValue = array.get(candidateRanks, index)
                anchorColor = direction == "up" ? anchorColorUp : anchorColorDown
                anchorLine = line.new(startTime, startPrice, endTime, endPrice, xloc=xloc.bar_time, color=anchorColor, width=1)
                f_push_line(anchorLine)
                midpointTime = int(math.round((startTime + endTime) / 2))
                midpointPrice = (startPrice + endPrice) / 2.0
                rankLabel = label.new(midpointTime, midpointPrice, text="#" + str.tostring(rankValue), xloc=xloc.bar_time, style=label.style_label_left, textcolor=color.white, color=color.new(color.black, 65), size=size.tiny)
                f_push_label(rankLabel)

        selectedAnchor = line.new(selectedStartTime, selectedStartPrice, selectedEndTime, selectedEndPrice, xloc=xloc.bar_time, color=selectedAnchorColor, width=3)
        f_push_line(selectedAnchor)

        for levelIndex = 0 to array.size(fibLevels) - 1
            coeff = array.get(fibLevels, levelIndex)
            levelPrice = f_level_price(selectedDirection, selectedStartPrice, selectedEndPrice, coeff)
            fibLine = line.new(xLeft, levelPrice, xRight, levelPrice, xloc=xloc.bar_time, color=selectedLevelColor, width=1, extend=extend.right)
            f_push_line(fibLine)
            if showLevelLabels
                levelLabel = label.new(xRight, levelPrice, text=str.tostring(coeff) + " | #" + str.tostring(selectedRank), xloc=xloc.bar_time, style=label.style_label_left, textcolor=color.white, color=color.new(color.black, 70), size=size.tiny)
                f_push_label(levelLabel)

        headerLabel = label.new(xRight, selectedEndPrice, text="DB1.S2 " + selectedId + " score=" + str.tostring(selectedScore), xloc=xloc.bar_time, style=label.style_label_upper_left, textcolor=color.white, color=color.new(color.blue, 75), size=size.small)
        f_push_label(headerLabel)
'''
