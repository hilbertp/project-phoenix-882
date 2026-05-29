"""OrderManager tests with a fake ExchangeClient.

DEV-ONLY iteration aid — NOT part of the Codex-owned regression suite.
The authoritative contract lives in docs/db1_live_bot_acs/order_manager.md.
This file may be deleted once Codex's regression suite covers AC-OM-* there.

We don't touch Hyperliquid here — the OrderManager is wired against the
ExchangeClient Protocol, so we record every call into a fake and assert the
expected sequence of placements/cancels happens for each FSM state transition.
"""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from apps.bot.config import RiskConfig, StrategyConfig
from apps.bot.exchange.signed_client import OpenOrder, PlacedOrder, Position
from apps.bot.marketdata import BarCloseEvent
from apps.bot.state import StateStore
from apps.bot.strategy.fsm import Setup
from apps.bot.strategy.order_manager import OrderManager
from apps.worker.discovery_bet_1.types import Candle


@dataclass
class _Call:
    method: str
    coin: str
    qty: float
    price: float | None
    cloid: str
    extra: dict = field(default_factory=dict)


class FakeExchange:
    """In-process exchange that records every call and returns a configured result."""

    def __init__(self) -> None:
        self.calls: list[_Call] = []
        self._open: list[OpenOrder] = []
        self._next_oid = 100

    def _record(self, method: str, coin: str, qty: float, price: float | None,
                cloid: str, **extra) -> PlacedOrder:
        self.calls.append(_Call(method, coin, qty, price, cloid, extra))
        self._next_oid += 1
        return PlacedOrder(
            cloid=cloid, exchange_order_id=self._next_oid,
            status="resting", raw={},
        )

    def place_limit_post_only(self, coin, is_buy, qty, price, cloid):
        return self._record("place_limit_post_only", coin, qty, price, cloid,
                            is_buy=is_buy)

    def place_reduce_only_limit(self, coin, is_buy, qty, price, cloid):
        return self._record("place_reduce_only_limit", coin, qty, price, cloid,
                            is_buy=is_buy)

    def place_stop_market(self, coin, is_buy, qty, trigger_px, cloid):
        return self._record("place_stop_market", coin, qty, trigger_px, cloid,
                            is_buy=is_buy)

    def market_close(self, coin, qty, cloid, slippage=0.05):
        return self._record("market_close", coin, qty, None, cloid,
                            slippage=slippage)

    def cancel(self, coin, cloid):
        self.calls.append(_Call("cancel", coin, 0.0, None, cloid))
        return {"status": "ok"}

    def open_orders(self):
        return list(self._open)

    def positions(self):  # pragma: no cover - not exercised here
        return []


def _candle(ts: str, o: float, h: float, low: float, c: float) -> Candle:
    return Candle(source_timestamp=ts, open=o, high=h, low=low, close=c, volume=1.0)


class OrderManagerArmingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self._tmp.name) / "state.db")
        self.client = FakeExchange()
        self.cfg = StrategyConfig()
        self.risk = RiskConfig()
        self.equity = 100_000.0  # $100k subaccount
        self.manager = OrderManager(
            client=self.client, store=self.store,
            strategy_cfg=self.cfg, risk_cfg=self.risk, equity=self.equity,
        )
        # An up leg from 100 to 110: entry @ ~100.59, init_sl @ ~99.5,
        # tp1 @ 101.18, tp2 @ 105, tp3 @ 110.
        self.setup = Setup(
            asset="BTC", direction="up",
            parent_ts="2026-05-01T00:00:00", parent_price=100.0,
            term_ts="2026-05-02T00:00:00", term_price=110.0,
        )

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_arming_places_entry_only(self) -> None:
        self.manager.arm_setup(self.setup)
        methods = [c.method for c in self.client.calls]
        self.assertEqual(methods, ["place_limit_post_only"])
        # post-only side = buy on an up leg
        self.assertTrue(self.client.calls[0].extra["is_buy"])

    def test_size_is_1R_of_equity(self) -> None:
        self.manager.arm_setup(self.setup)
        entry_call = self.client.calls[0]
        # 1R = $1000 at 1% of $100k; risk_per_unit = init_sl - entry.
        # Levels: entry ≈ 100.59, init_sl = 99.5 (1.05 retracement of leg)
        # risk_per_unit ≈ 1.09 -> qty ≈ 1000 / 1.09 ≈ 917 units
        # Default precision is 8 decimals -> no meaningful rounding for 917.
        self.assertAlmostEqual(entry_call.qty * 1.09, 1000.0, delta=10.0)

    def test_qty_rounded_to_asset_precision(self) -> None:
        """szDecimals for the asset must truncate qty (round-down)."""
        # Re-create the manager with a 2-decimal precision (e.g. SOL).
        self.manager = OrderManager(
            client=self.client, store=self.store,
            strategy_cfg=self.cfg, risk_cfg=self.risk, equity=self.equity,
            qty_precision={"BTC": 2},
        )
        self.client.calls.clear()
        self.manager.arm_setup(self.setup)
        entry_call = self.client.calls[0]
        # 917.43... -> 917.43 at 2 decimals (truncated, not rounded up)
        scaled = entry_call.qty * 100
        self.assertEqual(scaled, int(scaled))
        # Round-DOWN: qty * 100 must be <= 917 * 100 + 99 = 91799
        self.assertLessEqual(entry_call.qty, 917.43 + 0.01)

    def test_below_precision_refuses_to_arm(self) -> None:
        """Equity so small that 1R / risk_per_unit truncates to 0 -> no arm."""
        # equity * 1% / 1.09 must be < 10^-5 to truncate to 0 at precision=5.
        # equity < 1.09e-5 * 100 = 1.09e-3 dollars satisfies this.
        tiny = OrderManager(
            client=self.client, store=self.store,
            strategy_cfg=self.cfg, risk_cfg=self.risk, equity=0.0005,
            qty_precision={"BTC": 5},
        )
        self.client.calls.clear()
        result = tiny.arm_setup(self.setup)
        self.assertIsNone(result)
        self.assertEqual(self.client.calls, [])

    def test_leverage_cap_refuses_to_arm(self) -> None:
        """Notional > equity * maxLeverage[asset] -> refuse."""
        # 1R=$1000, risk_per_unit≈1.09 -> qty≈917; entry≈100.59 ->
        # notional≈92274. With equity=$100k and maxLeverage=10, cap=$1M.
        # That's fine. Lower max_leverage to 0.5 to force a violation.
        capped = OrderManager(
            client=self.client, store=self.store,
            strategy_cfg=self.cfg, risk_cfg=self.risk, equity=self.equity,
            max_leverage={"BTC": 0},   # 0x leverage cap = always violate
        )
        self.client.calls.clear()
        result = capped.arm_setup(self.setup)
        self.assertIsNone(result)
        self.assertEqual(self.client.calls, [])

    def test_no_leverage_cap_is_uncapped(self) -> None:
        """Asset absent from max_leverage map is treated as no cap."""
        loose = OrderManager(
            client=self.client, store=self.store,
            strategy_cfg=self.cfg, risk_cfg=self.risk, equity=self.equity,
            max_leverage={},
        )
        self.client.calls.clear()
        result = loose.arm_setup(self.setup)
        self.assertIsNotNone(result)

    def test_setup_is_stored(self) -> None:
        self.manager.arm_setup(self.setup)
        key = "BTC|up|2026-05-01T00:00:00|2026-05-02T00:00:00"
        orders = self.store.open_orders_for(key)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].level_role, "entry")
        # HL's "resting" status is normalized to "live" in the state store.
        self.assertEqual(orders[0].status, "live")

    def test_degenerate_setup_refused(self) -> None:
        bad = Setup(asset="BTC", direction="up",
                    parent_ts="x", parent_price=110.0,
                    term_ts="y", term_price=100.0)  # up but inverted
        result = self.manager.arm_setup(bad)
        self.assertIsNone(result)
        self.assertEqual(self.client.calls, [])

    def test_history_that_aborts_refuses_to_arm(self) -> None:
        """Price broke past the leg's terminal in history -> no live arm."""
        # Up leg: terminal=110. History bar with high > 110 -> abort.
        history = [
            _candle("2026-05-02T01:00:00", 105.0, 111.0, 104.0, 110.5),
        ]
        result = self.manager.arm_setup(self.setup, history)
        self.assertIsNone(result)
        # No exchange calls were dispatched.
        self.assertEqual(self.client.calls, [])
        # State store records the "missed" outcome.
        state = self.store.get_state(
            "BTC|up|2026-05-01T00:00:00|2026-05-02T00:00:00"
        )
        self.assertIsNotNone(state)
        self.assertEqual(state.state, "missed")
        self.assertEqual(state.payload["reason"], "detection_gap")

    def test_history_that_fills_entry_refuses_to_arm(self) -> None:
        """Price already touched our entry in history -> no live arm."""
        # Up leg: entry ~100.59. History bar with low <= 100.59 fills entry.
        history = [
            _candle("2026-05-02T01:00:00", 105.0, 106.0, 100.0, 105.0),
        ]
        result = self.manager.arm_setup(self.setup, history)
        self.assertIsNone(result)
        self.assertEqual(self.client.calls, [])
        state = self.store.get_state(
            "BTC|up|2026-05-01T00:00:00|2026-05-02T00:00:00"
        )
        self.assertEqual(state.state, "missed")

    def test_empty_history_arms_normally(self) -> None:
        """No history = no behavior change vs. the pre-fix path."""
        result = self.manager.arm_setup(self.setup, history=())
        self.assertIsNotNone(result)
        self.assertEqual([c.method for c in self.client.calls],
                         ["place_limit_post_only"])

    def test_quiet_history_arms_normally(self) -> None:
        """History with no terminal-break or entry-touch arms live."""
        history = [
            _candle("2026-05-02T01:00:00", 105.0, 106.0, 104.0, 105.5),
            _candle("2026-05-02T02:00:00", 105.5, 106.0, 104.5, 105.0),
        ]
        result = self.manager.arm_setup(self.setup, history)
        self.assertIsNotNone(result)
        self.assertEqual([c.method for c in self.client.calls],
                         ["place_limit_post_only"])


class OrderManagerFlowTests(unittest.TestCase):
    """Drive the FSM bar-by-bar and assert the right orders are placed/cancelled."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self._tmp.name) / "state.db")
        self.client = FakeExchange()
        self.manager = OrderManager(
            client=self.client, store=self.store,
            strategy_cfg=StrategyConfig(), risk_cfg=RiskConfig(),
            equity=100_000.0,
        )
        # Setup whose entry sits at retracement 0.941 of a 100->110 leg.
        # Numerically: entry = 110 + (100-110)*0.941 = 100.59
        # init_sl = 110 + (100-110)*1.05 = 99.5
        # tp1 = 110 + (100-110)*0.882 = 101.18
        # tp2 = 110 + (100-110)*0.5 = 105.0
        # tp3 = 110 + (100-110)*0.0 = 110.0
        self.setup = Setup(
            asset="BTC", direction="up",
            parent_ts="2026-05-01T00:00:00", parent_price=100.0,
            term_ts="2026-05-02T00:00:00", term_price=110.0,
        )
        self.manager.arm_setup(self.setup)

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def _bar_close(self, candle: Candle) -> None:
        evt = BarCloseEvent(asset="BTC", interval="1h",
                            closed_open_ms=0, candles=(candle,))
        self.manager.on_bar_close(evt)

    def test_entry_fill_places_sl_and_tp1(self) -> None:
        self.client.calls.clear()
        # A bar whose low touches entry (100.59) without breaking terminal:
        self._bar_close(_candle("2026-05-02T01:00:00", 102.0, 102.5, 100.0, 102.0))
        methods = [c.method for c in self.client.calls]
        self.assertIn("place_stop_market", methods)
        self.assertIn("place_reduce_only_limit", methods)

    def test_tp1_hit_cancels_sl_and_places_tp2(self) -> None:
        # Bar 1: fill entry
        self._bar_close(_candle("2026-05-02T01:00:00", 102.0, 102.5, 100.0, 102.0))
        self.client.calls.clear()
        # Bar 2 (entry-bar is skipped; this bar is phase 1): wick to TP1
        # without touching SL.
        self._bar_close(_candle("2026-05-02T02:00:00", 102.0, 101.5, 100.7, 101.4))
        methods = [c.method for c in self.client.calls]
        self.assertIn("cancel", methods)            # cancel initial SL
        self.assertIn("place_reduce_only_limit", methods)  # place TP2

    def test_be_close_fires_market_close(self) -> None:
        # Bar 1: fill entry
        self._bar_close(_candle("2026-05-02T01:00:00", 102.0, 102.5, 100.0, 102.0))
        # Bar 2: hit TP1 (this is the first phase-1 bar; entry-bar skipped)
        self._bar_close(_candle("2026-05-02T02:00:00", 102.0, 101.5, 100.7, 101.4))
        self.client.calls.clear()
        # Bar 3: close BELOW entry (100.59) -> BE stop fires in software
        self._bar_close(_candle("2026-05-02T03:00:00", 101.0, 101.0, 99.6, 100.0))
        methods = [c.method for c in self.client.calls]
        self.assertIn("market_close", methods)


if __name__ == "__main__":
    unittest.main()
