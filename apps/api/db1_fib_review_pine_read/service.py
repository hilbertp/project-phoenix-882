# ruff: noqa: E501 - this module embeds a Pine Script template whose DSL lines exceed the Python line length.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from apps.worker.discovery_bet_1.anchor_selection import ATR_MULTIPLIER
from apps.worker.discovery_bet_1.atr import ATR_PERIOD, calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.fib_structures import build_fib_candidates
from apps.worker.discovery_bet_1.lifecycle import materialize_fib_structures
from apps.worker.discovery_bet_1.market_contract import (
    LOCKED_MARKET_CONTRACT,
    market_contract_as_dict,
)
from apps.worker.discovery_bet_1.pivots import (
    LEFT_BARS,
    RIGHT_BARS,
    detect_local_pivots,
)
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from apps.worker.discovery_bet_1.types import FibStructure, RejectedAnchor

PINE_ARTIFACT_FILENAME = "db1_auto_fib_review.pine"
INDICATOR_TITLE = "DB1 Auto Fib Candidate Review"
REVIEW_LABEL_TEXT = "Auto Fib Review - Theoretical Trade Plan"
# Phoenix retracement levels measured from the impulse extreme (0.0) back toward
# the parent anchor (1.0), plus the 1.05 invalidation level used for the stop.
PHOENIX_FIB_LEVELS = (0.0, 0.382, 0.5, 0.618, 0.786, 0.882, 0.941, 1.0, 1.05)
# Theoretical trade-plan coefficients (first discovery version, fixed entry).
TRADE_PLAN_ENTRY_COEFF = 0.786
TRADE_PLAN_INITIAL_SL_COEFF = 1.05
TRADE_PLAN_TP1_COEFF = 0.618  # one Phoenix level closer to 0.0 than the entry
TRADE_PLAN_TP2_COEFF = 0.382  # three levels closer to 0.0 (0.618, 0.5, 0.382)
TRADE_PLAN_RUNNER_COEFF = -0.05  # TP3 runner: breakout speculation beyond 0.0
# Fib level reach tracker (discovery aid, not a strategy): after price touches the
# 0.786 entry, record which Fib levels it then reaches, in path order, until the
# 1.05 stop or the 0.0 target ends the trade. Path order = distance from the entry
# coefficient, so price traverses nearer levels before farther ones. 0.236 is a
# tracked reach level even though it is not part of the drawn Phoenix grid.
TRACKER_ENTRY_COEFF = 0.786
TRACKER_LEVELS_IN_PATH_ORDER = (0.882, 0.941, 0.618, 1.0, 1.05, 0.5, 0.382, 0.236, 0.0)
TRACKER_STOP_COEFF = 1.05
TRACKER_TARGET_COEFF = 0.0
# Only the ATR distance-gate rejections are plotted in debug mode. The
# recency ("older_than_selected_eligible_anchor") rejections are explained in
# the parameter label instead of drawn, because they are unbounded and not
# diagnostic of swing quality.
DEBUG_REJECTION_REASON = "atr_threshold_failed"
# Keep the embedded debug set small: the most recent rejections before each
# accepted terminal are the relevant context, and a bounded set keeps the
# generated Pine well within TradingView's script-size limits.
MAX_DEBUG_REJECTED_PER_TERMINAL = 15

_DEBUG_REJECTED_BLOCK = """
    // Debug: ATR distance-gate rejected candidate swings for the focused structure.
    if showDebugRejected and focusStructure >= 1 and maxIndex >= 0
        focusTerminal = array.get(structTerminalTimes, focusStructure - 1)
        rejMax = array.size(rejTerminalTimes) - 1
        drawn = 0
        if rejMax >= 0
            for ri = 0 to rejMax
                if drawn < 100 and array.get(rejTerminalTimes, ri) == focusTerminal
                    rt = array.get(rejCandidateTimes, ri)
                    rp = array.get(rejCandidatePrices, ri)
                    f_label(rt, rp, "x rejected (< ATR distance)", label.style_xcross, colorRejected, color.white, size.tiny)
                    drawn += 1
"""


class DB1FibReviewPineReadError(Exception):
    """The DB1 auto-Fib review Pine payload could not be built."""


@dataclass(frozen=True, slots=True)
class ReviewStructureRow:
    structure_id: str
    direction: str
    parent_timestamp_ms: int
    parent_price: float
    parent_kind: str
    terminal_timestamp_ms: int
    terminal_price: float
    terminal_kind: str
    invalidated_timestamp_ms: int


@dataclass(frozen=True, slots=True)
class RejectedSwingRow:
    terminal_timestamp_ms: int
    candidate_timestamp_ms: int
    candidate_price: float
    candidate_kind: str


class DB1FibReviewPineReadService:
    def __init__(self, input_path: Path = DEFAULT_INPUT_PATH) -> None:
        self._input_path = input_path

    def get_pine_review_payload(
        self, include_debug_rejected: bool = True
    ) -> dict[str, object]:
        try:
            loaded_input = load_candle_input(self._input_path)
        except Exception as error:
            raise DB1FibReviewPineReadError(str(error)) from error

        candles = loaded_input.candles
        atr_values = calculate_atr14(candles)
        pivots = detect_local_pivots(candles)
        candidates, rejected_anchors = build_fib_candidates(pivots, atr_values)
        structures = materialize_fib_structures(candidates, candles)

        structure_rows = [_build_structure_row(structure) for structure in structures]
        rejected_rows = _build_rejected_rows(structures, rejected_anchors)

        parameters = {
            "min_bars_between_swings": LEFT_BARS,
            "pivot_left_bars": LEFT_BARS,
            "pivot_right_bars": RIGHT_BARS,
            "up_move_atr_multiple": ATR_MULTIPLIER,
            "down_move_atr_multiple": ATR_MULTIPLIER,
            "atr_length": ATR_PERIOD,
        }
        pine_script = _build_pine_script(
            structure_rows, rejected_rows, parameters, include_debug_rejected
        )

        return {
            "sub_bet": "DB1",
            "title": "Auto-drawn Fib candidate review (TradingView Pine)",
            "artifact_filename": PINE_ARTIFACT_FILENAME,
            "indicator_title": INDICATOR_TITLE,
            "review_label": REVIEW_LABEL_TEXT,
            "market_contract": market_contract_as_dict(LOCKED_MARKET_CONTRACT),
            "parameters": parameters,
            "levels": list(PHOENIX_FIB_LEVELS),
            "accepted_structure_count": len(structure_rows),
            "debug_rejected_count": len(rejected_rows),
            "structure_summary": [
                {
                    "structure_id": row.structure_id,
                    "direction": row.direction,
                    "parent_price": row.parent_price,
                    "terminal_price": row.terminal_price,
                }
                for row in structure_rows
            ],
            "pine_script": pine_script,
        }


def _build_structure_row(structure: FibStructure) -> ReviewStructureRow:
    invalidated = structure.invalidated_at_source_timestamp
    return ReviewStructureRow(
        structure_id=str(structure.structure_id),
        direction=str(structure.direction),
        parent_timestamp_ms=_to_unix_ms(structure.parent_anchor_source_timestamp),
        parent_price=float(structure.parent_anchor_price),
        parent_kind=str(structure.parent_anchor_kind),
        terminal_timestamp_ms=_to_unix_ms(structure.terminal_extreme_source_timestamp),
        terminal_price=float(structure.terminal_extreme_price),
        terminal_kind=str(structure.terminal_extreme_kind),
        invalidated_timestamp_ms=(
            _to_unix_ms(invalidated) if invalidated else 0
        ),
    )


def _build_rejected_rows(
    structures: list[FibStructure],
    rejected_anchors: list[RejectedAnchor],
) -> list[RejectedSwingRow]:
    accepted_terminals = {
        structure.terminal_extreme_source_timestamp for structure in structures
    }
    per_terminal: dict[str, list[RejectedSwingRow]] = {}
    seen: set[tuple[str, str, float]] = set()
    for rejected in rejected_anchors:
        if rejected.rejection_reason != DEBUG_REJECTION_REASON:
            continue
        terminal_timestamp = rejected.terminal_extreme_source_timestamp
        if terminal_timestamp not in accepted_terminals:
            continue
        key = (
            terminal_timestamp,
            rejected.candidate_anchor_source_timestamp,
            float(rejected.candidate_anchor_price),
        )
        if key in seen:
            continue
        seen.add(key)
        per_terminal.setdefault(terminal_timestamp, []).append(
            RejectedSwingRow(
                terminal_timestamp_ms=_to_unix_ms(terminal_timestamp),
                candidate_timestamp_ms=_to_unix_ms(
                    rejected.candidate_anchor_source_timestamp
                ),
                candidate_price=float(rejected.candidate_anchor_price),
                candidate_kind=str(rejected.candidate_anchor_kind),
            )
        )

    rows: list[RejectedSwingRow] = []
    for terminal_rows in per_terminal.values():
        terminal_rows.sort(key=lambda row: row.candidate_timestamp_ms)
        rows.extend(terminal_rows[-MAX_DEBUG_REJECTED_PER_TERMINAL:])
    return rows


def _to_unix_ms(source_timestamp: str) -> int:
    parsed = datetime.fromisoformat(source_timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return int(parsed.timestamp() * 1000)


def _int_array(values: list[int]) -> str:
    if not values:
        return "array.from(0)"
    return f"array.from({', '.join(str(int(value)) for value in values)})"


def _float_array(values: list[float]) -> str:
    if not values:
        return "array.from(0.0)"
    return f"array.from({', '.join(f'{float(value):.6f}' for value in values)})"


def _string_array(values: list[str]) -> str:
    if not values:
        return 'array.from("")'
    return f"array.from({', '.join(f'\"{value}\"' for value in values)})"


def _build_pine_script(
    structures: list[ReviewStructureRow],
    rejected: list[RejectedSwingRow],
    parameters: dict[str, float],
    include_debug_rejected: bool = True,
) -> str:
    structure_count = max(len(structures), 1)
    levels = ", ".join(f"{level:.3f}" for level in PHOENIX_FIB_LEVELS)

    struct_ids = _string_array([row.structure_id for row in structures])
    struct_dirs = _string_array([row.direction for row in structures])
    parent_times = _int_array([row.parent_timestamp_ms for row in structures])
    parent_prices = _float_array([row.parent_price for row in structures])
    parent_kinds = _string_array([row.parent_kind for row in structures])
    terminal_times = _int_array([row.terminal_timestamp_ms for row in structures])
    terminal_prices = _float_array([row.terminal_price for row in structures])
    terminal_kinds = _string_array([row.terminal_kind for row in structures])
    invalidated_times = _int_array(
        [row.invalidated_timestamp_ms for row in structures]
    )

    if include_debug_rejected:
        debug_input_line = (
            '\nshowDebugRejected = input.bool(false, '
            '"Debug: show ATR-rejected candidate swings (focused only)")'
        )
        rejected_arrays_block = (
            f"rejTerminalTimes = {_int_array([row.terminal_timestamp_ms for row in rejected])}\n"
            f"rejCandidateTimes = {_int_array([row.candidate_timestamp_ms for row in rejected])}\n"
            f"rejCandidatePrices = {_float_array([row.candidate_price for row in rejected])}\n\n"
        )
        debug_block = _DEBUG_REJECTED_BLOCK
    else:
        debug_input_line = ""
        rejected_arrays_block = ""
        debug_block = ""

    min_bars = int(parameters["min_bars_between_swings"])
    up_mult = float(parameters["up_move_atr_multiple"])
    down_mult = float(parameters["down_move_atr_multiple"])
    atr_length = int(parameters["atr_length"])
    entry_coeff = TRADE_PLAN_ENTRY_COEFF
    initial_sl_coeff = TRADE_PLAN_INITIAL_SL_COEFF
    tp1_coeff = TRADE_PLAN_TP1_COEFF
    tp2_coeff = TRADE_PLAN_TP2_COEFF
    runner_coeff = TRADE_PLAN_RUNNER_COEFF
    tracker_coeff = TRACKER_ENTRY_COEFF
    tracker_levels = ", ".join(str(coeff) for coeff in TRACKER_LEVELS_IN_PATH_ORDER)
    tracker_stop_index = TRACKER_LEVELS_IN_PATH_ORDER.index(TRACKER_STOP_COEFF)
    tracker_target_index = TRACKER_LEVELS_IN_PATH_ORDER.index(TRACKER_TARGET_COEFF)

    return f'''//@version=6
// DB1 auto-drawn Fib candidate review lane.
// Set the chart to BITGET:BTCUSDT.P, 1H, timezone UTC so bar-time anchors line up.
// This overlay is a REVIEW aid only: it is not an entry / buy / sell signal.
indicator("{INDICATOR_TITLE}", overlay=true, max_lines_count=500, max_labels_count=500)

structureCount = {structure_count}
focusStructure = input.int(0, "Focus structure (0 = show all)", minval=0, maxval=structureCount)
showFib = input.bool(true, "Show Phoenix Fib levels")
showLevelLabels = input.bool(true, "Show Fib level labels")
extendFibRight = input.bool(false, "Extend focused Fib levels to the right")
showTradePlan = input.bool(true, "Show theoretical trade plan (focused structure)")
showTracker = input.bool(true, "Show Fib level reach tracker (focused structure)"){debug_input_line}

colorUp = color.new(color.teal, 0)
colorDown = color.new(color.red, 0)
colorUpFill = color.new(color.teal, 60)
colorDownFill = color.new(color.red, 60)
colorLevel = color.new(color.gray, 20)
colorHigh = color.new(color.lime, 0)
colorLow = color.new(color.fuchsia, 0)
colorRejected = color.new(color.orange, 30)
colorInfo = color.new(color.blue, 80)
colorEntry = color.new(color.yellow, 0)
colorSL = color.new(color.red, 0)
colorTP = color.new(color.lime, 0)
colorMoveSL = color.new(color.orange, 0)

structIds = {struct_ids}
structDirections = {struct_dirs}
structParentTimes = {parent_times}
structParentPrices = {parent_prices}
structParentKinds = {parent_kinds}
structTerminalTimes = {terminal_times}
structTerminalPrices = {terminal_prices}
structTerminalKinds = {terminal_kinds}
structInvalidatedTimes = {invalidated_times}

{rejected_arrays_block}fibLevels = array.from({levels})

minBarsBetweenSwings = {min_bars}
upMoveAtrMultiple = {up_mult:.2f}
downMoveAtrMultiple = {down_mult:.2f}
atrLength = {atr_length}

var line[] activeLines = array.new_line()
var label[] activeLabels = array.new_label()

f_clear() =>
    while array.size(activeLines) > 0
        line.delete(array.pop(activeLines))
    while array.size(activeLabels) > 0
        label.delete(array.pop(activeLabels))

f_line(int x1, float y1, int x2, float y2, color col, int wid, bool doExt) =>
    ln = line.new(x1, y1, x2, y2, xloc=xloc.bar_time, color=col, width=wid, extend=doExt ? extend.right : extend.none)
    array.push(activeLines, ln)
    ln

f_label(int x, float y, string txt, string style, color col, color txtcol, string sz) =>
    lb = label.new(x, y, text=txt, xloc=xloc.bar_time, style=style, color=col, textcolor=txtcol, size=sz)
    array.push(activeLabels, lb)
    lb

f_level_price(float terminalPrice, float parentPrice, float coeff) =>
    terminalPrice + (parentPrice - terminalPrice) * coeff

// Collect each bar's time/high/low so the focused reach tracker can scan forward
// from a structure's terminal through the post-entry price action on the last bar.
var int[] barTimes = array.new_int()
var float[] barHighs = array.new_float()
var float[] barLows = array.new_float()
array.push(barTimes, time)
array.push(barHighs, high)
array.push(barLows, low)

if barstate.islast
    f_clear()
    maxIndex = array.size(structIds) - 1

    // Parameter + review labels (anchored to the most recent structure).
    if maxIndex >= 0
        infoTime = array.get(structTerminalTimes, maxIndex)
        infoPrice = array.get(structTerminalPrices, maxIndex)
        paramText = "DB1 detector parameters" + "\\nMin bars between swings: " + str.tostring(minBarsBetweenSwings) + " (pivot 2L/2R)" + "\\nUp move ATR multiple: " + str.tostring(upMoveAtrMultiple) + "\\nDown move ATR multiple: " + str.tostring(downMoveAtrMultiple) + "\\nATR length: " + str.tostring(atrLength) + "\\nAnchor = nearest swing >= ATR multiple; older eligible swings dropped" + "\\nAccepted structures: " + str.tostring(structureCount)
        f_label(infoTime, infoPrice, paramText, label.style_label_left, colorInfo, color.white, size.small)
        reviewText = "{REVIEW_LABEL_TEXT}\\nVisual management plan - review only, not a buy / sell signal\\nSet Focus to 1.." + str.tostring(structureCount) + " to see each setup's trade plan"
        f_label(infoTime, infoPrice, reviewText, label.style_label_lower_left, color.new(color.purple, 30), color.white, size.normal)

    if maxIndex >= 0
        for i = 0 to maxIndex
            if focusStructure == 0 or focusStructure == i + 1
                direction = array.get(structDirections, i)
                parentTime = array.get(structParentTimes, i)
                parentPrice = array.get(structParentPrices, i)
                terminalTime = array.get(structTerminalTimes, i)
                terminalPrice = array.get(structTerminalPrices, i)
                structId = array.get(structIds, i)
                invalidatedTime = array.get(structInvalidatedTimes, i)
                isUp = direction == "up"
                legColor = isUp ? colorUp : colorDown
                isFocused = focusStructure == i + 1
                xLeft = int(math.min(parentTime, terminalTime))
                xRight = int(math.max(parentTime, terminalTime))

                // Impulse leg: parent anchor -> terminal extreme.
                f_line(parentTime, parentPrice, terminalTime, terminalPrice, legColor, 2, false)

                // Accepted swing markers (high vs low independent of direction).
                highTime = parentPrice >= terminalPrice ? parentTime : terminalTime
                highPrice = math.max(parentPrice, terminalPrice)
                lowTime = parentPrice >= terminalPrice ? terminalTime : parentTime
                lowPrice = math.min(parentPrice, terminalPrice)
                f_label(highTime, highPrice, "Swing High (accepted)", label.style_label_down, colorHigh, color.black, size.small)
                f_label(lowTime, lowPrice, "Swing Low (accepted)", label.style_label_up, colorLow, color.black, size.small)

                // Direction + identity.
                midTime = int(math.round((parentTime + terminalTime) / 2))
                midPrice = (parentPrice + terminalPrice) / 2.0
                dirText = isUp ? "up bullish leg (low -> high)" : "down bearish leg (high -> low)"
                invalidText = invalidatedTime > 0 ? "" : " [still active]"
                f_label(midTime, midPrice, structId + ": " + dirText + invalidText, label.style_label_center, isUp ? colorUpFill : colorDownFill, color.white, size.tiny)

                // Phoenix Fib levels (0.0 at terminal extreme -> 1.0 at parent anchor).
                if showFib
                    doExtend = extendFibRight and isFocused
                    for li = 0 to array.size(fibLevels) - 1
                        coeff = array.get(fibLevels, li)
                        lvl = f_level_price(terminalPrice, parentPrice, coeff)
                        f_line(xLeft, lvl, xRight, lvl, colorLevel, 1, doExtend)
                        if showLevelLabels
                            f_label(xRight, lvl, str.tostring(coeff, "#.###"), label.style_label_left, color.new(color.gray, 40), color.white, size.tiny)

                // Theoretical trade plan (focused structure only) - visual review, not a signal.
                if showTradePlan and isFocused
                    entryPrice = f_level_price(terminalPrice, parentPrice, {entry_coeff})
                    initialSlPrice = f_level_price(terminalPrice, parentPrice, {initial_sl_coeff})
                    tp1Price = f_level_price(terminalPrice, parentPrice, {tp1_coeff})
                    tp2Price = f_level_price(terminalPrice, parentPrice, {tp2_coeff})
                    runnerPrice = f_level_price(terminalPrice, parentPrice, {runner_coeff})
                    f_line(xLeft, entryPrice, xRight, entryPrice, colorEntry, 2, true)
                    f_label(xRight, entryPrice, "Entry (0.786)", label.style_label_left, colorEntry, color.black, size.normal)
                    f_line(xLeft, initialSlPrice, xRight, initialSlPrice, colorSL, 2, true)
                    f_label(xRight, initialSlPrice, "Initial SL: 1.05", label.style_label_left, colorSL, color.white, size.small)
                    f_line(xLeft, tp1Price, xRight, tp1Price, colorTP, 1, true)
                    f_label(xRight, tp1Price, "TP1 (0.618): Partial + move SL to entry", label.style_label_left, colorTP, color.black, size.small)
                    f_label(xLeft, entryPrice, "SL after TP1 -> Entry (risk = 0)", label.style_label_right, colorMoveSL, color.white, size.small)
                    f_line(xLeft, tp2Price, xRight, tp2Price, colorTP, 2, true)
                    f_label(xRight, tp2Price, "TP2 (0.382): Take 80%", label.style_label_left, colorTP, color.black, size.small)
                    f_line(xLeft, runnerPrice, xRight, runnerPrice, colorTP, 1, true)
                    f_label(xRight, runnerPrice, "Runner TP3: breakout beyond 0.0 (15%)", label.style_label_left, colorTP, color.black, size.small)
                    f_label(midTime, highPrice, "Theoretical Trade Plan (visual review, not a signal): Entry 0.786 -> TP1 0.618 (move SL to entry) -> TP2 0.382 (80%) -> Runner breakout > 0.0", label.style_label_down, colorInfo, color.white, size.small)

                // Fib level reach tracker (focused structure only) - discovery aid, NOT
                // PnL / win rate / signal. After price touches the 0.786 entry, record
                // each level price MOVES to (the nearest level in the bar that differs
                // from the last recorded one), so turnarounds within the retracement are
                // captured, until the 1.05 stop or the 0.0 target ends the trade. The
                // Python twin (scripts/track_fib_reaches.py) is the authoritative record;
                // here one level-change is drawn per bar to bound label count.
                if showTracker and isFocused
                    trkEntryPrice = f_level_price(terminalPrice, parentPrice, {tracker_coeff})
                    trkCoeffs = array.from({tracker_levels})
                    trkN = array.size(trkCoeffs)
                    trkBars = array.size(barTimes)
                    trkEntered = false
                    trkEnded = false
                    trkLast = {tracker_coeff}
                    f_label(xLeft, trkEntryPrice, "Reach tracker (after 0.786 entry, turnarounds shown): adverse 0.882>0.941>1.0>1.05 | favor 0.618>0.5>0.382>0.236>0.0", label.style_label_right, colorInfo, color.white, size.tiny)
                    for bi = 0 to trkBars - 1
                        bt = array.get(barTimes, bi)
                        if not trkEnded and bt > terminalTime
                            bh = array.get(barHighs, bi)
                            bl = array.get(barLows, bi)
                            if not trkEntered
                                if bl <= trkEntryPrice and trkEntryPrice <= bh
                                    trkEntered := true
                                    f_label(bt, trkEntryPrice, "Entry: 0.786", label.style_label_left, colorEntry, color.black, size.small)
                            else
                                bestIdx = -1
                                bestDist = 1e9
                                for li = 0 to trkN - 1
                                    cf = array.get(trkCoeffs, li)
                                    if cf != trkLast
                                        lp = f_level_price(terminalPrice, parentPrice, cf)
                                        if bl <= lp and lp <= bh and math.abs(cf - trkLast) < bestDist
                                            bestDist := math.abs(cf - trkLast)
                                            bestIdx := li
                                if bestIdx >= 0
                                    cf = array.get(trkCoeffs, bestIdx)
                                    lp = f_level_price(terminalPrice, parentPrice, cf)
                                    isStop = bestIdx == {tracker_stop_index}
                                    isTarget = bestIdx == {tracker_target_index}
                                    pfx = isStop ? "Stopped: " : (isTarget ? "Target: " : "Reached: ")
                                    lcol = isStop ? colorSL : (isTarget ? colorTP : colorMoveSL)
                                    tcol = isStop ? color.white : color.black
                                    f_label(bt, lp, pfx + str.tostring(cf, "0.0##"), label.style_label_left, lcol, tcol, size.tiny)
                                    trkLast := cf
                                    trkEnded := isStop or isTarget
                    if not trkEntered
                        f_label(xRight, trkEntryPrice, "Reach tracker: 0.786 entry not yet touched", label.style_label_left, colorInfo, color.white, size.small)
{debug_block}'''
