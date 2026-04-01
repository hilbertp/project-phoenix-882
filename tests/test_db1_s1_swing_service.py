from __future__ import annotations

import unittest

from apps.api.db1_s1_swing_read.service import DB1S1SwingReadService


class DB1S1SwingReadServiceTests(unittest.TestCase):
    def test_get_swing_payload_uses_strict_two_bar_local_pivot_rule(self) -> None:
        payload = DB1S1SwingReadService().get_swing_payload()

        self.assertEqual(payload["sub_bet"], "DB1.S1")
        self.assertEqual(payload["title"], "Raw 1H Swing Detection")
        self.assertEqual(payload["market_contract"]["tradingview_symbol"], "BITGET:BTCUSDT.P")
        self.assertEqual(payload["market_contract"]["timeframe"], "1H")
        self.assertEqual(payload["detector"]["rule_name"], "strict_local_pivot_2_left_2_right")
        self.assertEqual(payload["detector"]["left_bars"], 2)
        self.assertEqual(payload["detector"]["right_bars"], 2)
        self.assertGreater(payload["summary"]["candle_count"], 0)
        self.assertGreater(payload["summary"]["swing_count"], 0)
        self.assertGreater(payload["summary"]["swing_high_count"], 0)
        self.assertGreater(payload["summary"]["swing_low_count"], 0)
        self.assertEqual(len(payload["candles"]), payload["summary"]["candle_count"])
        self.assertEqual(len(payload["swing_highs"]), payload["summary"]["swing_high_count"])
        self.assertEqual(len(payload["swing_lows"]), payload["summary"]["swing_low_count"])


if __name__ == "__main__":
    unittest.main()