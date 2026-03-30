from __future__ import annotations

import unittest

from apps.api.db1_review_tradingview.service import (
    TradingViewMarketContract,
    TradingViewReviewStructure,
    TradingViewSyncError,
    TradingViewSyncRequest,
    _build_expected_line_tool_points,
    _build_render_verification,
)


def _request() -> TradingViewSyncRequest:
    return TradingViewSyncRequest(
        market_contract=TradingViewMarketContract(
            tradingview_symbol="BITGET:BTCUSDT.P",
            timeframe="1H",
        ),
        review_structure=TradingViewReviewStructure(
            structure_id="db1-fib-0001",
            direction="up",
            parent_anchor_source_timestamp="2025-12-31T10:00:00",
            parent_anchor_price=88350.7,
            parent_anchor_kind="low",
            terminal_extreme_source_timestamp="2025-12-31T16:00:00",
            terminal_extreme_price=89180.8,
            terminal_extreme_kind="high",
        ),
    )


class DB1TradingViewServiceTests(unittest.TestCase):
    def test_build_expected_line_tool_points_uses_exact_db1_anchor_pair(self) -> None:
        points = _build_expected_line_tool_points(_request())

        self.assertEqual(
            points,
            [
                {
                    "interval": "60",
                    "offset": 0,
                    "price": 88350.7,
                    "time_t": 1767175200,
                },
                {
                    "interval": "60",
                    "offset": 0,
                    "price": 89180.8,
                    "time_t": 1767196800,
                },
            ],
        )

    def test_build_render_verification_rejects_non_exact_rendered_points(self) -> None:
        with self.assertRaises(TradingViewSyncError) as error_context:
            _build_render_verification(
                request=_request(),
                restored_state={
                    "type": "LineToolFibRetracement",
                    "points": [
                        {
                            "interval": "60",
                            "offset": 0,
                            "price": 88365.34162895927,
                            "time_t": 1767171600,
                        },
                        {
                            "interval": "60",
                            "offset": 0,
                            "price": 89190.40950226245,
                            "time_t": 1767193200,
                        },
                    ],
                },
            )

        self.assertIn("exact detected anchors", str(error_context.exception))


if __name__ == "__main__":
    unittest.main()