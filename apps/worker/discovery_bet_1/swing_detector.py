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
