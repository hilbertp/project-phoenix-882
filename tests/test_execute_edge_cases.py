"""Synthetic edge-case tests for the two rulings of 2026-07-03.

DEV-ONLY iteration aid — NOT part of the Codex-owned regression suite.

Ruling 1 (C2 expansion): "price beyond entry is always post-entry" is sound,
BUT within the fill HOUR the path matters: if price first shot up to 0.882
(TP1 -> stop dragged to entry) and only THEN fell below 1.05, that is a
TP1-then-break-even exit (+~0.14R), NOT a -1R loss. The 5m candles decide.
The same data seen at 1H-only granularity scores LOSS -- which is exactly why
5m sub-bars are mandatory infrastructure.

Ruling 2 (C4): a single 5m candle poking both entry and TP1 is a graze --
no TP1 credit, no stop drag; if the trade is stopped out afterwards,
"we take the L".

These are synthetic candles engineered to isolate each path; no market data
needed.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.discovery_bet_1.types import Candle
from scripts.execute_fib_strategy import build_subbar_index, execute

# Up leg: parent low 100, terminal high 200.
# Levels: entry 0.941 = 105.9 | SL 1.05 = 95.0 | TP1 0.882 = 111.8
SWING = {"parent_price": 100.0, "term_price": 200.0,
         "term_ts": "2026-01-01T01:00:00", "direction": "up"}


def c(ts, o, h, l, cl):
    return Candle(ts, o, h, l, cl, 1.0)


def h1_candles(retrace_hour):
    """parent hour, terminal hour, then the retrace hour under test."""
    return [
        c("2026-01-01T00:00:00", 100, 110, 100, 108),   # parent low 100
        c("2026-01-01T01:00:00", 108, 200, 108, 195),   # terminal high 200
        retrace_hour,
    ]


class FillHourPathTests(unittest.TestCase):
    def test_tp1_before_sl_within_fill_hour_is_scratch_not_loss(self):
        """Ruling 1: fill -> up to TP1 (drag) -> crash through 1.05, all in
        one HOUR. With 5m data: TP1 partial + break-even exit (+~0.14R)."""
        hour = c("2026-01-01T02:00:00", 120, 112, 94, 95)   # touches E+TP1+SL
        candles = h1_candles(hour)
        idx = {x.source_timestamp: i for i, x in enumerate(candles)}
        sub = build_subbar_index([
            c("2026-01-01T02:00:00", 120, 118, 112, 113),   # pre-fill drift
            c("2026-01-01T02:05:00", 113, 110, 105.5, 106), # FILL (no SL, no TP1)
            c("2026-01-01T02:10:00", 106, 112.0, 107, 111), # clean TP1 -> drag SL
            c("2026-01-01T02:15:00", 111, 111, 94, 95),     # crash: BE fires at entry
        ])
        res = execute(candles, idx, SWING, subbars=sub)
        self.assertEqual(res["status"], "tp1_then_scratch")
        self.assertGreater(res["r"], 0.10)   # ~ +0.135R

    def test_same_hour_at_1h_granularity_scores_loss(self):
        """Same OHLC without 5m data: the whole hour is one opaque fill bar
        that touched the stop -> conservative LOSS. This contrast is WHY the
        5m feed is mandatory."""
        hour = c("2026-01-01T02:00:00", 120, 112, 94, 95)
        candles = h1_candles(hour)
        idx = {x.source_timestamp: i for i, x in enumerate(candles)}
        res = execute(candles, idx, SWING, subbars=None)
        self.assertEqual(res["status"], "wipeout")
        self.assertEqual(res["r"], -1.0)

    def test_graze_then_stop_out_takes_the_L(self):
        """Ruling 2: a 5m candle poking both entry and TP1 arms NOTHING; the
        later stop-out is a full -1R loss."""
        hour = c("2026-01-01T02:00:00", 120, 112, 94, 95)
        candles = h1_candles(hour)
        idx = {x.source_timestamp: i for i, x in enumerate(candles)}
        sub = build_subbar_index([
            c("2026-01-01T02:00:00", 120, 118, 112, 113),
            c("2026-01-01T02:05:00", 113, 110, 105.5, 106),   # FILL
            c("2026-01-01T02:10:00", 106, 112.0, 105.6, 107), # GRAZE: TP1+entry -> noise
            c("2026-01-01T02:15:00", 107, 108, 94, 95),       # SL touch -> LOSS
        ])
        res = execute(candles, idx, SWING, subbars=sub)
        self.assertEqual(res["status"], "wipeout")
        self.assertEqual(res["r"], -1.0)


if __name__ == "__main__":
    unittest.main()
