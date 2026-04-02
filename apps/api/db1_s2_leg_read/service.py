from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median

from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.market_contract import LOCKED_MARKET_CONTRACT, market_contract_as_dict
from apps.worker.discovery_bet_1.pivots import LEFT_BARS, RIGHT_BARS, detect_local_pivots
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from apps.worker.discovery_bet_1.types import Candle, Pivot, PivotKind

PROMINENCE_WINDOW_BARS = 24
DISPLAY_CANDIDATE_COUNT = 24


class DB1S2LegReadError(Exception):
    """The DB1.S2 candidate leg payload could not be built."""


@dataclass(frozen=True, slots=True)
class CandidateLegMetrics:
    size_score: float
    cleanliness_score: float
    prominence_score: float
    dominance_score: float
    size_points: float
    size_percent: float
    cleanliness_ratio: float
    prominence_points: float
    dominance_ratio: float


@dataclass(frozen=True, slots=True)
class CandidateLeg:
    candidate_id: str
    rank: int
    score: float
    direction: str
    start_pivot: dict[str, object]
    end_pivot: dict[str, object]
    candle_span: int
    metrics: CandidateLegMetrics


class DB1S2LegReadService:
    def __init__(self, input_path: Path = DEFAULT_INPUT_PATH) -> None:
        self._input_path = input_path

    def get_candidate_leg_payload(self) -> dict[str, object]:
        try:
            loaded_input = load_candle_input(self._input_path)
        except Exception as error:
            raise DB1S2LegReadError(str(error)) from error

        candles = loaded_input.candles
        raw_pivots = detect_local_pivots(candles)
        alternating_pivots = _compress_to_alternating_pivots(raw_pivots)
        candidates = _build_ranked_candidates(candles, alternating_pivots)
        top_candidates = candidates[:DISPLAY_CANDIDATE_COUNT]

        return {
            "sub_bet": "DB1.S2",
            "title": "Candidate Leg Scoring",
            "market_contract": market_contract_as_dict(LOCKED_MARKET_CONTRACT),
            "detector": {
                "raw_pivot_rule": {
                    "rule_name": "strict_local_pivot_2_left_2_right",
                    "left_bars": LEFT_BARS,
                    "right_bars": RIGHT_BARS,
                },
                "candidate_leg_rule": {
                    "rule_name": "adjacent_alternating_pivot_pairs",
                    "description": (
                        "Raw pivots are scanned in time order. Consecutive same-kind pivots are collapsed to the more extreme pivot, "
                        "then every adjacent pair in the alternating sequence becomes one candidate leg."
                    ),
                },
                "scoring": {
                    "dimensions": ["size", "cleanliness", "prominence", "dominance"],
                    "weights": {
                        "size": 0.35,
                        "cleanliness": 0.25,
                        "prominence": 0.20,
                        "dominance": 0.20,
                    },
                },
            },
            "summary": {
                "candle_count": len(candles),
                "raw_pivot_count": len(raw_pivots),
                "alternating_pivot_count": len(alternating_pivots),
                "candidate_leg_count": len(candidates),
                "displayed_candidate_count": len(top_candidates),
                "source_start_timestamp": candles[0].source_timestamp,
                "source_end_timestamp": candles[-1].source_timestamp,
            },
            "source_provenance": loaded_input.provenance,
            "candles": candles,
            "raw_pivots": raw_pivots,
            "alternating_pivots": alternating_pivots,
            "candidate_legs": [
                {
                    "candidate_id": candidate.candidate_id,
                    "rank": candidate.rank,
                    "score": candidate.score,
                    "direction": candidate.direction,
                    "start_pivot": candidate.start_pivot,
                    "end_pivot": candidate.end_pivot,
                    "candle_span": candidate.candle_span,
                    "metrics": asdict(candidate.metrics),
                }
                for candidate in top_candidates
            ],
        }


def _compress_to_alternating_pivots(raw_pivots: list[Pivot]) -> list[Pivot]:
    if not raw_pivots:
        return []

    alternating = [raw_pivots[0]]
    for pivot in raw_pivots[1:]:
        last = alternating[-1]
        if pivot.kind != last.kind:
            alternating.append(pivot)
            continue

        if pivot.kind == PivotKind.HIGH and pivot.price > last.price:
            alternating[-1] = pivot
        elif pivot.kind == PivotKind.LOW and pivot.price < last.price:
            alternating[-1] = pivot

    return alternating


def _build_ranked_candidates(candles: list[Candle], alternating_pivots: list[Pivot]) -> list[CandidateLeg]:
    if len(alternating_pivots) < 2:
        return []

    raw_candidates: list[dict[str, object]] = []
    for index in range(len(alternating_pivots) - 1):
        start = alternating_pivots[index]
        end = alternating_pivots[index + 1]
        size_points = abs(end.price - start.price)
        size_percent = size_points / max(abs(start.price), 1.0)
        cleanliness_ratio = _calculate_cleanliness_ratio(candles, start.index, end.index)
        prominence_points = _calculate_leg_prominence(candles, start, end)
        raw_candidates.append(
            {
                "start": start,
                "end": end,
                "size_points": size_points,
                "size_percent": size_percent,
                "cleanliness_ratio": cleanliness_ratio,
                "prominence_points": prominence_points,
            }
        )

    max_size_percent = max(candidate["size_percent"] for candidate in raw_candidates) or 1.0
    max_prominence_points = max(candidate["prominence_points"] for candidate in raw_candidates) or 1.0
    global_median_size = median(candidate["size_percent"] for candidate in raw_candidates) or 1.0
    dominance_raw_values: list[float] = []
    for index, candidate in enumerate(raw_candidates):
        neighbor_sizes = []
        if index > 0:
            neighbor_sizes.append(float(raw_candidates[index - 1]["size_percent"]))
        if index + 1 < len(raw_candidates):
            neighbor_sizes.append(float(raw_candidates[index + 1]["size_percent"]))
        local_reference = sum(neighbor_sizes) / len(neighbor_sizes) if neighbor_sizes else global_median_size
        dominance_raw = float(candidate["size_percent"]) / max(local_reference, 1e-9)
        candidate["dominance_ratio"] = dominance_raw
        dominance_raw_values.append(dominance_raw)

    max_dominance_ratio = max(dominance_raw_values) or 1.0
    ranked: list[CandidateLeg] = []
    for candidate in raw_candidates:
        size_score = float(candidate["size_percent"]) / max_size_percent
        cleanliness_score = float(candidate["cleanliness_ratio"])
        prominence_score = float(candidate["prominence_points"]) / max_prominence_points
        dominance_score = float(candidate["dominance_ratio"]) / max_dominance_ratio
        score = (
            0.35 * size_score
            + 0.25 * cleanliness_score
            + 0.20 * prominence_score
            + 0.20 * dominance_score
        )
        start = candidate["start"]
        end = candidate["end"]
        assert isinstance(start, Pivot)
        assert isinstance(end, Pivot)
        ranked.append(
            CandidateLeg(
                candidate_id=f"leg-{start.index}-{end.index}",
                rank=0,
                score=round(score, 6),
                direction="up" if start.kind == PivotKind.LOW else "down",
                start_pivot=_serialize_pivot(start),
                end_pivot=_serialize_pivot(end),
                candle_span=end.index - start.index,
                metrics=CandidateLegMetrics(
                    size_score=round(size_score, 6),
                    cleanliness_score=round(cleanliness_score, 6),
                    prominence_score=round(prominence_score, 6),
                    dominance_score=round(dominance_score, 6),
                    size_points=round(float(candidate["size_points"]), 4),
                    size_percent=round(float(candidate["size_percent"]), 6),
                    cleanliness_ratio=round(float(candidate["cleanliness_ratio"]), 6),
                    prominence_points=round(float(candidate["prominence_points"]), 4),
                    dominance_ratio=round(float(candidate["dominance_ratio"]), 6),
                ),
            )
        )

    ranked.sort(key=lambda item: (-item.score, -item.metrics.size_percent, item.start_pivot["index"]))
    return [
        CandidateLeg(
            candidate_id=item.candidate_id,
            rank=index + 1,
            score=item.score,
            direction=item.direction,
            start_pivot=item.start_pivot,
            end_pivot=item.end_pivot,
            candle_span=item.candle_span,
            metrics=item.metrics,
        )
        for index, item in enumerate(ranked)
    ]


def _calculate_cleanliness_ratio(candles: list[Candle], start_index: int, end_index: int) -> float:
    segment = candles[start_index : end_index + 1]
    if len(segment) < 2:
        return 0.0
    total_travel = 0.0
    for left, right in zip(segment, segment[1:]):
        total_travel += abs(right.close - left.close)
    if total_travel == 0.0:
        return 0.0
    net_move = abs(segment[-1].close - segment[0].close)
    return min(net_move / total_travel, 1.0)


def _calculate_leg_prominence(candles: list[Candle], start: Pivot, end: Pivot) -> float:
    return (_calculate_pivot_prominence(candles, start) + _calculate_pivot_prominence(candles, end)) / 2.0


def _calculate_pivot_prominence(candles: list[Candle], pivot: Pivot) -> float:
    left = max(0, pivot.index - PROMINENCE_WINDOW_BARS)
    right = min(len(candles), pivot.index + PROMINENCE_WINDOW_BARS + 1)
    neighbors = candles[left:pivot.index] + candles[pivot.index + 1 : right]
    if not neighbors:
        return 0.0
    if pivot.kind == PivotKind.HIGH:
        surrounding_reference = max(candle.high for candle in neighbors)
        return max(pivot.price - surrounding_reference, 0.0)
    surrounding_reference = min(candle.low for candle in neighbors)
    return max(surrounding_reference - pivot.price, 0.0)


def _serialize_pivot(pivot: Pivot) -> dict[str, object]:
    return {
        "index": pivot.index,
        "source_timestamp": pivot.source_timestamp,
        "kind": pivot.kind.value,
        "price": pivot.price,
        "candle_low": pivot.candle_low,
        "candle_high": pivot.candle_high,
    }