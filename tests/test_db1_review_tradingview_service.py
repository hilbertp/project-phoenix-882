from __future__ import annotations

from pathlib import Path
from typing import cast
import unittest

from apps.api.db1_review_tradingview.service import (
    DB1TradingViewSyncService,
    DEFAULT_REVIEW_FIB_LINE_COLOR,
    DEFAULT_REVIEW_FIB_STYLE,
    DEFAULT_REVIEW_VISIBLE_FIB_LEVELS,
    TradingViewMarketContract,
    TradingViewReviewStyle,
    TradingViewReviewStructure,
    TradingViewSyncError,
    TradingViewSyncRequest,
    _build_anchor_pair_from_line_tool_state,
    _chart_theme_implementation_for_variant,
    _chart_theme_mode_for_variant,
    _build_review_fib_state,
    _build_expected_line_tool_points,
    _build_render_verification,
    _parse_sync_request,
    _review_style_payload_for_variant,
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

    def test_build_expected_line_tool_points_aligns_to_chart_timezone_when_provided(self) -> None:
        points = _build_expected_line_tool_points(
            _request(),
            chart_time_zone="Asia/Nicosia",
        )

        self.assertEqual(
            points,
            [
                {
                    "interval": "60",
                    "offset": 0,
                    "price": 88350.7,
                    "time_t": 1767168000,
                },
                {
                    "interval": "60",
                    "offset": 0,
                    "price": 89180.8,
                    "time_t": 1767189600,
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

    def test_parse_sync_request_defaults_keep_browser_open_to_false(self) -> None:
        request = _parse_sync_request(
            {
                "market_contract": {
                    "tradingview_symbol": "BITGET:BTCUSDT.P",
                    "timeframe": "1H",
                },
                "review_structure": {
                    "structure_id": "db1-fib-0001",
                    "direction": "up",
                    "parent_anchor_source_timestamp": "2025-12-31T10:00:00",
                    "parent_anchor_price": 88350.7,
                    "parent_anchor_kind": "low",
                    "terminal_extreme_source_timestamp": "2025-12-31T16:00:00",
                    "terminal_extreme_price": 89180.8,
                    "terminal_extreme_kind": "high",
                },
            }
        )

        self.assertIs(request.keep_browser_open, False)
        self.assertIs(request.preserve_review_context, False)
        self.assertIs(request.use_tradingview_defaults, False)
        self.assertEqual(request.visual_variant, "review-custom")

    def test_parse_sync_request_accepts_review_context_flags(self) -> None:
        request = _parse_sync_request(
            {
                "keep_browser_open": True,
                "preserve_review_context": True,
                "market_contract": {
                    "tradingview_symbol": "BITGET:BTCUSDT.P",
                    "timeframe": "1H",
                },
                "review_structure": {
                    "structure_id": "db1-fib-0001",
                    "direction": "up",
                    "parent_anchor_source_timestamp": "2025-12-31T10:00:00",
                    "parent_anchor_price": 88350.7,
                    "parent_anchor_kind": "low",
                    "terminal_extreme_source_timestamp": "2025-12-31T16:00:00",
                    "terminal_extreme_price": 89180.8,
                    "terminal_extreme_kind": "high",
                },
            }
        )

        self.assertIs(request.keep_browser_open, True)
        self.assertIs(request.preserve_review_context, True)
        self.assertIs(request.use_tradingview_defaults, False)
        self.assertEqual(request.visual_variant, "review-custom")

    def test_parse_sync_request_accepts_tradingview_default_mode(self) -> None:
        request = _parse_sync_request(
            {
                "use_tradingview_defaults": True,
                "market_contract": {
                    "tradingview_symbol": "BITGET:BTCUSDT.P",
                    "timeframe": "1H",
                },
                "review_structure": {
                    "structure_id": "db1-fib-0001",
                    "direction": "up",
                    "parent_anchor_source_timestamp": "2025-12-31T10:00:00",
                    "parent_anchor_price": 88350.7,
                    "parent_anchor_kind": "low",
                    "terminal_extreme_source_timestamp": "2025-12-31T16:00:00",
                    "terminal_extreme_price": 89180.8,
                    "terminal_extreme_kind": "high",
                },
            }
        )

        self.assertIs(request.use_tradingview_defaults, True)
        self.assertEqual(request.visual_variant, "baseline")

    def test_parse_sync_request_accepts_visual_variant(self) -> None:
        request = _parse_sync_request(
            {
                "visual_variant": "labels-prices-only",
                "market_contract": {
                    "tradingview_symbol": "BITGET:BTCUSDT.P",
                    "timeframe": "1H",
                },
                "review_structure": {
                    "structure_id": "db1-fib-0001",
                    "direction": "up",
                    "parent_anchor_source_timestamp": "2025-12-31T10:00:00",
                    "parent_anchor_price": 88350.7,
                    "parent_anchor_kind": "low",
                    "terminal_extreme_source_timestamp": "2025-12-31T16:00:00",
                    "terminal_extreme_price": 89180.8,
                    "terminal_extreme_kind": "high",
                },
            }
        )

        self.assertEqual(request.visual_variant, "labels-prices-only")

    def test_sync_structure_keeps_driver_open_when_requested(self) -> None:
        service = _FakeSyncService()

        payload = {
            "keep_browser_open": True,
            "market_contract": {
                "tradingview_symbol": "BITGET:BTCUSDT.P",
                "timeframe": "1H",
            },
            "review_structure": {
                "structure_id": "db1-fib-0001",
                "direction": "up",
                "parent_anchor_source_timestamp": "2025-12-31T10:00:00",
                "parent_anchor_price": 88350.7,
                "parent_anchor_kind": "low",
                "terminal_extreme_source_timestamp": "2025-12-31T16:00:00",
                "terminal_extreme_price": 89180.8,
                "terminal_extreme_kind": "high",
            },
        }

        response = service.sync_structure(payload)

        self.assertIs(response["browser_retained"], True)
        chart_theme = cast(dict[str, object], response["chart_theme"])
        self.assertEqual(chart_theme["mode"], "dark")
        self.assertEqual(
            chart_theme["implementation"],
            "preload-theme-bootstrap-plus-chart-properties",
        )
        self.assertEqual(service.closed_drivers, [])
        self.assertIs(service._retained_driver, service.created_drivers[0])

    def test_sync_structure_reuses_retained_browser_for_same_review_target(self) -> None:
        service = _FakeSyncService()

        payload = {
            "keep_browser_open": True,
            "preserve_review_context": True,
            "market_contract": {
                "tradingview_symbol": "BITGET:BTCUSDT.P",
                "timeframe": "1H",
            },
            "review_structure": {
                "structure_id": "db1-fib-0001",
                "direction": "up",
                "parent_anchor_source_timestamp": "2025-12-31T10:00:00",
                "parent_anchor_price": 88350.7,
                "parent_anchor_kind": "low",
                "terminal_extreme_source_timestamp": "2025-12-31T16:00:00",
                "terminal_extreme_price": 89180.8,
                "terminal_extreme_kind": "high",
            },
        }

        first_response = service.sync_structure(payload)
        second_response = service.sync_structure(payload)

        self.assertEqual(len(service.created_drivers), 1)
        self.assertIs(first_response["browser_retained"], True)
        self.assertIs(second_response["browser_session_reused"], True)
        second_review_tool = cast(dict[str, object], second_response["review_tool"])
        self.assertIs(second_review_tool["selected_for_editing"], True)
        self.assertTrue(service.sync_calls[1]["reuse_browser_session"])
        self.assertTrue(service.sync_calls[1]["prefer_preserved_review_tool"])

    def test_build_anchor_pair_from_line_tool_state_uses_chart_timezone(self) -> None:
        anchor_pair = _build_anchor_pair_from_line_tool_state(
            {
                "type": "LineToolFibRetracement",
                "points": [
                    {
                        "interval": "60",
                        "offset": 0,
                        "price": 88350.7,
                        "time_t": 1767168000,
                    },
                    {
                        "interval": "60",
                        "offset": 0,
                        "price": 89180.8,
                        "time_t": 1767189600,
                    },
                ],
            },
            chart_time_zone="Asia/Nicosia",
        )

        self.assertEqual(
            anchor_pair,
            {
                "parent_anchor_source_timestamp": "2025-12-31T10:00:00",
                "parent_anchor_price": 88350.7,
                "terminal_extreme_source_timestamp": "2025-12-31T16:00:00",
                "terminal_extreme_price": 89180.8,
            },
        )

    def test_build_review_fib_state_uses_white_only_selected_levels(self) -> None:
        state = _build_review_fib_state(
            market_symbol="BITGET:BTCUSDT.P",
            chart_interval="60",
        )
        visible_levels = [
            value[0]
            for key, value in state.items()
            if key.startswith("level") and isinstance(value, list) and value[2] is True
        ]

        self.assertTrue(state["showCoeffs"])
        self.assertTrue(state["showPrices"])
        self.assertTrue(state["showText"])
        trendline = cast(dict[str, object], state["trendline"])
        self.assertEqual(trendline["color"], DEFAULT_REVIEW_FIB_LINE_COLOR)
        self.assertEqual(state["level1"], [0.0, DEFAULT_REVIEW_FIB_LINE_COLOR, True, ""])
        self.assertEqual(state["level2"], [0.236, DEFAULT_REVIEW_FIB_LINE_COLOR, True, ""])
        self.assertEqual(state["level3"], [0.382, DEFAULT_REVIEW_FIB_LINE_COLOR, True, ""])
        self.assertEqual(state["level4"], [0.5, DEFAULT_REVIEW_FIB_LINE_COLOR, True, ""])
        self.assertEqual(state["level5"], [0.618, DEFAULT_REVIEW_FIB_LINE_COLOR, True, ""])
        self.assertEqual(state["level6"], [0.786, DEFAULT_REVIEW_FIB_LINE_COLOR, True, ""])
        self.assertEqual(state["level7"], [0.882, DEFAULT_REVIEW_FIB_LINE_COLOR, True, ""])
        self.assertEqual(state["level8"], [0.941, DEFAULT_REVIEW_FIB_LINE_COLOR, True, ""])
        self.assertEqual(state["level9"], [1.0, DEFAULT_REVIEW_FIB_LINE_COLOR, True, ""])
        self.assertEqual(state["level10"], [1.618, DEFAULT_REVIEW_FIB_LINE_COLOR, False, ""])
        self.assertEqual(DEFAULT_REVIEW_FIB_STYLE.visible_levels, DEFAULT_REVIEW_VISIBLE_FIB_LEVELS)
        self.assertEqual(
            DEFAULT_REVIEW_VISIBLE_FIB_LEVELS,
            (1.0, 0.941, 0.882, 0.786, 0.618, 0.5, 0.382, 0.236, 0.0),
        )
        self.assertEqual(
            visible_levels,
            [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 0.882, 0.941, 1.0],
        )

    def test_build_review_fib_state_uses_injected_review_style_levels(self) -> None:
        state = _build_review_fib_state(
            market_symbol="BITGET:BTCUSDT.P",
            chart_interval="60",
            review_style=TradingViewReviewStyle(
                visible_levels=(0.236, 0.382, 0.786),
                line_color="#ABCDEF",
            ),
        )

        self.assertEqual(state["level1"], [0.0, "#ABCDEF", False, ""])
        self.assertEqual(state["level2"], [0.236, "#ABCDEF", True, ""])
        self.assertEqual(state["level3"], [0.382, "#ABCDEF", True, ""])
        self.assertEqual(state["level6"], [0.786, "#ABCDEF", True, ""])
        self.assertEqual(state["level7"], [0.882, "#ABCDEF", False, ""])
        self.assertEqual(state["level8"], [0.941, "#ABCDEF", False, ""])
        self.assertEqual(state["level9"], [1.0, "#ABCDEF", False, ""])

    def test_build_review_fib_state_can_isolate_visibility_changes(self) -> None:
        state = _build_review_fib_state(
            market_symbol="BITGET:BTCUSDT.P",
            chart_interval="60",
            apply_levels=False,
            apply_visibility=True,
            apply_white_style=False,
        )

        self.assertTrue(state["showCoeffs"])
        self.assertTrue(state["showPrices"])
        self.assertTrue(state["showText"])
        self.assertNotIn("level1", state)
        self.assertNotIn("trendline", state)

    def test_build_review_fib_state_can_isolate_white_style_changes(self) -> None:
        state = _build_review_fib_state(
            market_symbol="BITGET:BTCUSDT.P",
            chart_interval="60",
            apply_levels=False,
            apply_visibility=False,
            apply_white_style=True,
        )

        trendline = cast(dict[str, object], state["trendline"])
        self.assertEqual(trendline["color"], DEFAULT_REVIEW_FIB_LINE_COLOR)
        self.assertNotIn("showPrices", state)
        self.assertNotIn("level1", state)

    def test_sync_service_uses_configured_review_style(self) -> None:
        service = _FakeSyncService(
            review_style=TradingViewReviewStyle(
                visible_levels=(0.236, 0.382),
                line_color="#123456",
            )
        )

        response = service.sync_structure(
            {
                "keep_browser_open": True,
                "market_contract": {
                    "tradingview_symbol": "BITGET:BTCUSDT.P",
                    "timeframe": "1H",
                },
                "review_structure": {
                    "structure_id": "db1-fib-0001",
                    "direction": "up",
                    "parent_anchor_source_timestamp": "2025-12-31T10:00:00",
                    "parent_anchor_price": 88350.7,
                    "parent_anchor_kind": "low",
                    "terminal_extreme_source_timestamp": "2025-12-31T16:00:00",
                    "terminal_extreme_price": 89180.8,
                    "terminal_extreme_kind": "high",
                },
            }
        )

        review_style = cast(dict[str, object], response["review_style"])
        self.assertEqual(review_style["visible_levels"], [0.236, 0.382])
        self.assertEqual(review_style["line_color"], "#123456")

    def test_sync_service_reports_tradingview_default_mode(self) -> None:
        service = _FakeSyncService()

        response = service.sync_structure(
            {
                "keep_browser_open": True,
                "use_tradingview_defaults": True,
                "market_contract": {
                    "tradingview_symbol": "BITGET:BTCUSDT.P",
                    "timeframe": "1H",
                },
                "review_structure": {
                    "structure_id": "db1-fib-0001",
                    "direction": "up",
                    "parent_anchor_source_timestamp": "2025-12-31T10:00:00",
                    "parent_anchor_price": 88350.7,
                    "parent_anchor_kind": "low",
                    "terminal_extreme_source_timestamp": "2025-12-31T16:00:00",
                    "terminal_extreme_price": 89180.8,
                    "terminal_extreme_kind": "high",
                },
            }
        )

        chart_theme = cast(dict[str, object], response["chart_theme"])
        review_style = cast(dict[str, object], response["review_style"])
        self.assertEqual(chart_theme["mode"], "platform-default")
        self.assertEqual(chart_theme["implementation"], "tradingview-default")
        self.assertEqual(review_style["mode"], "tradingview-default")
        self.assertIsNone(review_style["line_color"])
        self.assertIsNone(review_style["visible_levels"])

    def test_sync_service_reports_isolated_variant_metadata(self) -> None:
        service = _FakeSyncService()

        response = service.sync_structure(
            {
                "visual_variant": "darkmode-only",
                "market_contract": {
                    "tradingview_symbol": "BITGET:BTCUSDT.P",
                    "timeframe": "1H",
                },
                "review_structure": {
                    "structure_id": "db1-fib-0001",
                    "direction": "up",
                    "parent_anchor_source_timestamp": "2025-12-31T10:00:00",
                    "parent_anchor_price": 88350.7,
                    "parent_anchor_kind": "low",
                    "terminal_extreme_source_timestamp": "2025-12-31T16:00:00",
                    "terminal_extreme_price": 89180.8,
                    "terminal_extreme_kind": "high",
                },
            }
        )

        chart_theme = cast(dict[str, object], response["chart_theme"])
        review_style = cast(dict[str, object], response["review_style"])
        self.assertEqual(chart_theme["mode"], "dark")
        self.assertEqual(review_style["mode"], "darkmode-only")

    def test_build_render_verification_accepts_chart_timezone_aligned_points(self) -> None:
        verification = _build_render_verification(
            request=_request(),
            restored_state={
                "type": "LineToolFibRetracement",
                "points": [
                    {
                        "interval": "60",
                        "offset": 0,
                        "price": 88350.7,
                        "time_t": 1767168000,
                    },
                    {
                        "interval": "60",
                        "offset": 0,
                        "price": 89180.8,
                        "time_t": 1767189600,
                    },
                ],
            },
            chart_time_zone="Asia/Nicosia",
        )

        self.assertTrue(verification["verified"])
        self.assertEqual(verification["chart_time_zone"], "Asia/Nicosia")


class _FakeSyncService(DB1TradingViewSyncService):
    def __init__(
        self,
        review_style: TradingViewReviewStyle = DEFAULT_REVIEW_FIB_STYLE,
    ) -> None:
        super().__init__(
            chrome_binary=Path("/tmp/unused-chrome"),
            review_style=review_style,
        )
        self.created_drivers: list[object] = []
        self.closed_drivers: list[object] = []
        self.sync_calls: list[dict[str, object]] = []

    def _create_driver(self) -> object:
        driver = object()
        self.created_drivers.append(driver)
        return driver

    def _close_driver(self, driver: object) -> None:
        self.closed_drivers.append(driver)

    def _sync_in_browser(
        self,
        driver: object,
        request: TradingViewSyncRequest,
        *,
        reuse_browser_session: bool,
        prefer_preserved_review_tool: bool,
    ) -> dict[str, object]:
        self.sync_calls.append(
            {
                "driver": driver,
                "request": request,
                "reuse_browser_session": reuse_browser_session,
                "prefer_preserved_review_tool": prefer_preserved_review_tool,
            }
        )
        return {
            "status": "ok",
            "chart_url": "https://www.tradingview.com/chart/?symbol=BITGET%3ABTCUSDT.P",
            "browser_retained": request.keep_browser_open,
            "browser_session_reused": reuse_browser_session,
            "chart_theme": {
                "mode": _chart_theme_mode_for_variant(request.visual_variant),
                "implementation": _chart_theme_implementation_for_variant(
                    request.visual_variant
                ),
            },
            "market_symbol": request.market_contract.tradingview_symbol,
            "timeframe": request.market_contract.timeframe,
            "structure_id": request.review_structure.structure_id,
            "placed_tool": "LineToolFibRetracement",
            "chart_title": "BTCUSDT.P proof",
            "review_style": _review_style_payload_for_variant(
                request.visual_variant,
                self._review_style,
            ),
            "review_tool": {
                "source": "retained-live-tool" if prefer_preserved_review_tool else "proposal-render",
                "reused_existing_tool": prefer_preserved_review_tool,
                "selected_for_editing": True,
                "selection_count": 1,
                "matches_proposed_anchors": True,
                "anchor_pair": {
                    "parent_anchor_source_timestamp": request.review_structure.parent_anchor_source_timestamp,
                    "parent_anchor_price": request.review_structure.parent_anchor_price,
                    "terminal_extreme_source_timestamp": request.review_structure.terminal_extreme_source_timestamp,
                    "terminal_extreme_price": request.review_structure.terminal_extreme_price,
                },
            },
            "render_verification": {
                "verified": True,
                "direction": request.review_structure.direction,
                "parent_anchor_source_timestamp": request.review_structure.parent_anchor_source_timestamp,
                "parent_anchor_price": request.review_structure.parent_anchor_price,
                "terminal_extreme_source_timestamp": request.review_structure.terminal_extreme_source_timestamp,
                "terminal_extreme_price": request.review_structure.terminal_extreme_price,
            },
        }


if __name__ == "__main__":
    unittest.main()