"""Tests for the extracted ATR-zigzag swing detector used by the live bot.

DEV-ONLY iteration aid — NOT part of the Codex-owned regression suite.
The detector itself lives in apps/worker/discovery_bet_1/swing_detector.py
and its contract is shared with the backtest engine (see scripts/backtest_*).
The bot's *use* of it is covered by docs/db1_live_bot_acs/detector_loop.md.
"""
from __future__ import annotations

import unittest

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from apps.worker.discovery_bet_1.swing_detector import clean_legs


class SwingDetectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candles = load_candle_input(DEFAULT_INPUT_PATH).candles
        cls.atr = calculate_atr14(cls.candles)

    def test_idempotent(self) -> None:
        """Same input + params produces the same legs every call."""
        a = clean_legs(self.candles, self.atr, None, min_bars=6, mult=2.0)
        b = clean_legs(self.candles, self.atr, None, min_bars=6, mult=2.0)
        self.assertEqual(a, b)
        self.assertGreater(len(a), 0)

    def test_min_bars_filters_short_legs(self) -> None:
        """Larger min_bars yields fewer legs (subset / monotone)."""
        loose = clean_legs(self.candles, self.atr, None, min_bars=6, mult=2.0)
        strict = clean_legs(self.candles, self.atr, None, min_bars=24, mult=2.0)
        self.assertLessEqual(len(strict), len(loose))

    def test_mult_filters_small_legs(self) -> None:
        """Larger ATR mult yields fewer legs."""
        loose = clean_legs(self.candles, self.atr, None, min_bars=6, mult=2.0)
        strict = clean_legs(self.candles, self.atr, None, min_bars=6, mult=4.0)
        self.assertLessEqual(len(strict), len(loose))

    def test_each_leg_is_internally_consistent(self) -> None:
        """An up leg goes low -> high (term > parent); a down leg, high -> low."""
        legs = clean_legs(self.candles, self.atr, None, min_bars=6, mult=2.0)
        for leg in legs:
            self.assertGreater(leg["term_idx"], leg["parent_idx"])
            if leg["direction"] == "up":
                self.assertEqual(leg["parent_kind"], "low")
                self.assertEqual(leg["term_kind"], "high")
                self.assertGreater(leg["term_price"], leg["parent_price"])
            else:
                self.assertEqual(leg["parent_kind"], "high")
                self.assertEqual(leg["term_kind"], "low")
                self.assertLess(leg["term_price"], leg["parent_price"])

    def test_pivot_snaps_to_latest_tied_extreme(self) -> None:
        """Anchor should land on the LATEST bar of a multi-bar flat extreme.

        Constructs a synthetic series with an up-move into a 6-bar flat
        top at high=110 (bars 10-15), then a real reversal down. With the
        zigzag's strict-`>` cur_hi update rule, the high pivot fires at
        bar 10 (the FIRST tied-extreme bar). The post-walk refinement
        with `>=` tie-break snaps it to bar 15 (the LAST tied bar).

        User-visible symptom this defends against: 'anchors a few candles
        to the left of where they should be' on flat extremes (which are
        common around resistance/support levels).
        """
        from apps.worker.discovery_bet_1.types import Candle

        candles: list[Candle] = []
        for i in range(40):
            candles.append(Candle(f"2026-01-01T{i:02d}:00:00", 100, 100, 100, 100, 0))

        def sb(i: int, o: float, h: float, l: float, c: float) -> None:
            candles[i] = Candle(f"2026-01-01T{i:02d}:00:00", o, h, l, c, 0)

        # Up phase bars 1-9 ramping 101 -> 109.
        for i in range(1, 10):
            p = 100 + i
            sb(i, p - 0.4, p + 0.1, p - 0.6, p)
        # Flat top bars 10-15: all touch high=110 (resistance kissed 6 times).
        for i in range(10, 16):
            sb(i, 109.5, 110.0, 109.3, 109.7)
        # Reversal: deep drop fires the down threshold cleanly.
        sb(16, 109.0, 109.5, 105.0, 105.5)
        # Down continuation so the next low pivot fires further out.
        for i in range(17, 25):
            p = 105.0 - (i - 16) * 0.6
            sb(i, p + 0.2, p + 0.3, p - 0.3, p)
        # Bounce so the low pivot eventually fires.
        for i in range(25, 32):
            p = 100 + (i - 25) * 0.6
            sb(i, p - 0.2, p + 0.3, p - 0.3, p)

        atr: list[float | None] = [1.0] * len(candles)
        legs = clean_legs(candles, atr, None, min_bars=4, mult=2.0)
        ups = [l for l in legs if l["direction"] == "up"]
        self.assertTrue(ups, f"expected an up-leg, got {legs}")
        # The up-leg whose term lives in the flat-top region 10..15
        relevant = [l for l in ups if 10 <= l["term_idx"] <= 18]
        self.assertTrue(relevant,
                        f"no up-leg with term in flat-top range; got ups={ups}")
        leg = relevant[0]
        # Without tie-break refinement, term_idx == 10 (first tied bar).
        # With the fix, term_idx should be 15 (LAST tied bar).
        self.assertGreaterEqual(
            leg["term_idx"], 13,
            f"anchor still biased leftward on tied flat-top: term_idx="
            f"{leg['term_idx']} (expected >=13, ideally 15)"
        )
        self.assertAlmostEqual(leg["term_price"], 110.0, places=5)


if __name__ == "__main__":
    unittest.main()
