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


if __name__ == "__main__":
    unittest.main()
