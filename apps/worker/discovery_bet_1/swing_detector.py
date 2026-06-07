"""ATR-zigzag swing detector for DB1 setups.

A CLEAN leg: from a start fractal to the opposite extreme with no higher high
than the terminal and no lower low than the parent in between -- i.e. the start
is the segment's extreme and the end is the opposite extreme, with nothing
breaching either bound between them. Gated by min-bars and ATR multiple.

This is the canonical detector used by the backtest engine (scripts/backtest_*)
and the live bot (apps/bot). It was originally inlined in
scripts/place_fibs_tradingview.py and was moved here so the bot package can
import it without depending on scripts/. The script re-exports the function for
backward compatibility with the many existing call sites.
"""
from __future__ import annotations

from typing import Any

from apps.worker.discovery_bet_1.types import Candle


def clean_legs(
    candles: list[Candle],
    atr: list[float | None],
    pivots: Any = None,
    min_bars: int = 6,
    mult: float = 2.0,
) -> list[dict]:
    """Return cleanly-detected legs from an ATR-zigzag walk over `candles`.

    A leg reverses only when price retraces >= ATR*mult from the running
    extreme, so each leg runs extreme-to-extreme with no breach beyond the ATR
    tolerance in between (clean major swing). Gated by min-bars span between
    the two pivots.

    `pivots` is accepted for backward compatibility with the original signature
    but is unused -- the zigzag is computed from candles + atr directly.

    Defaults match the live-bot PRD (min_bars=6, mult=2.0); the TradingView
    placement and backtest scripts pass their own values (typically 24 / 3.0 or
    24 / 4.0).
    """
    del pivots  # vestigial; kept for back-compat with the original signature
    n = len(candles)
    piv: list[tuple[int, float, str]] = []
    direction = 0  # 1 = up phase, -1 = down phase, 0 = undetermined
    cur_hi, cur_hi_i = candles[0].high, 0
    cur_lo, cur_lo_i = candles[0].low, 0
    for i in range(1, n):
        c = candles[i]
        thr = (atr[i] or 0.0) * mult
        if thr <= 0:
            if c.high > cur_hi:
                cur_hi, cur_hi_i = c.high, i
            if c.low < cur_lo:
                cur_lo, cur_lo_i = c.low, i
            continue
        if direction != -1 and c.high > cur_hi:
            cur_hi, cur_hi_i = c.high, i
        if direction != 1 and c.low < cur_lo:
            cur_lo, cur_lo_i = c.low, i
        if direction != -1 and (cur_hi - c.low) >= thr:
            piv.append((cur_hi_i, cur_hi, "high"))
            direction = -1
            cur_lo, cur_lo_i = c.low, i
        elif direction != 1 and (c.high - cur_lo) >= thr:
            piv.append((cur_lo_i, cur_lo, "low"))
            direction = 1
            cur_hi, cur_hi_i = c.high, i

    # ------------------------------------------------------------------ #
    # Pivot refinement (swing-correction): re-anchor each pivot to the
    # true extreme bar within [prev_pivot+1, next_pivot).
    #
    # Why this exists: the zigzag walk fires a pivot the moment the
    # ATR*mult retracement threshold is met. If the trend then *resumes*
    # to a more extreme bar (a common "fake-out" pattern), the new
    # extreme is NOT recognized -- the `direction != -1` guards on the
    # walk-loop's cur_hi/cur_lo updates block it. The result is a pivot
    # locked at the premature trigger bar, a few candles to the left of
    # the visual extreme.
    #
    # The fix: after the walk, for every pivot scan the bars between
    # its neighbors and snap the pivot to the actual extreme. This
    # never crosses a neighbor, so pivot ordering is preserved.
    # ------------------------------------------------------------------ #
    if len(piv) >= 2:
        refined: list[tuple[int, float, str]] = []
        for j, (pi, pp, pk) in enumerate(piv):
            lo = (refined[-1][0] + 1) if refined else 0
            hi = piv[j + 1][0] if j + 1 < len(piv) else min(pi + 1, n)
            if lo >= hi:
                refined.append((pi, pp, pk))
                continue
            if pk == "high":
                # `>=` (not `>`) so among tied-extreme bars (flat top resistance)
                # the LATEST one wins. The walk uses strict `>` which biases the
                # anchor to the EARLIEST tied bar -- producing the user-visible
                # "anchor a few candles to the left of the visual extreme."
                best_i, best_p = pi, pp
                for k in range(lo, hi):
                    if candles[k].high >= best_p:
                        best_p, best_i = candles[k].high, k
            else:  # "low"
                # Same logic for lows: `<=` lets the LATEST tied-low bar win.
                best_i, best_p = pi, pp
                for k in range(lo, hi):
                    if candles[k].low <= best_p:
                        best_p, best_i = candles[k].low, k
            refined.append((best_i, best_p, pk))
        piv = refined

    legs: list[dict] = []
    for (pi, pp, pk), (ti, tp, tk) in zip(piv, piv[1:]):
        if (ti - pi) < min_bars:
            continue
        legs.append({
            "direction": "up" if pk == "low" else "down",
            "size": abs(tp - pp),
            "parent_idx": pi, "parent_price": pp, "parent_kind": pk,
            "parent_ts": candles[pi].source_timestamp,
            "term_idx": ti, "term_price": tp, "term_kind": tk,
            "term_ts": candles[ti].source_timestamp,
        })
    return legs
