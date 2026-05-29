"""Reconciler tests with a fake ExchangeClient.

DEV-ONLY iteration aid — NOT part of the Codex-owned regression suite.
The authoritative contract lives in docs/db1_live_bot_acs/reconciler.md.
This file may be deleted once Codex's regression suite covers AC-REC-* there.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apps.bot.exchange.signed_client import OpenOrder, Position
from apps.bot.state import (
    OrderRecord,
    SetupRecord,
    StateStore,
    now_iso,
    setup_key_for,
)
from apps.bot.strategy.reconciler import reconcile


class _FakeExchange:
    def __init__(self, open_orders=(), positions=()):
        self._open = list(open_orders)
        self._positions = list(positions)
        self.calls = 0

    def open_orders(self):
        self.calls += 1
        return self._open

    def positions(self):
        return self._positions


def _make_setup(asset: str = "BTC") -> SetupRecord:
    return SetupRecord(
        setup_key=setup_key_for(asset, "up",
                                "2026-05-01T00:00:00", "2026-05-02T00:00:00"),
        asset=asset, direction="up",
        parent_ts="2026-05-01T00:00:00", parent_price=100.0,
        term_ts="2026-05-02T00:00:00", term_price=110.0,
        detector_min_bars=6, detector_mult=2.0,
        detected_at=now_iso(),
    )


class ReconcilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self._tmp.name) / "state.db")

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_clean_when_everything_empty(self) -> None:
        result = reconcile(_FakeExchange(), self.store)
        self.assertEqual(result.category, "CLEAN")
        self.assertTrue(result.ok)
        self.assertEqual(result.issues, [])

    def test_ambiguous_when_orphan_position_exists(self) -> None:
        ex = _FakeExchange(positions=[
            Position(coin="BTC", size=0.5, entry_px=100.0,
                     unrealized_pnl=0.0, raw={}),
        ])
        result = reconcile(ex, self.store)
        self.assertEqual(result.category, "AMBIGUOUS")
        self.assertFalse(result.ok)
        self.assertTrue(
            any("orphan position" in i for i in result.issues),
            msg=result.issues,
        )

    def test_ambiguous_when_entered_setup_has_no_position(self) -> None:
        rec = _make_setup()
        self.store.upsert_setup(rec)
        self.store.set_state(rec.setup_key, "entered")
        result = reconcile(_FakeExchange(), self.store)
        self.assertEqual(result.category, "AMBIGUOUS")
        self.assertTrue(
            any("no position exists" in i for i in result.issues),
            msg=result.issues,
        )

    def test_ambiguous_when_expected_order_missing_on_exchange(self) -> None:
        rec = _make_setup()
        self.store.upsert_setup(rec)
        self.store.set_state(rec.setup_key, "entered")
        # State.db expects this order to be live...
        now = now_iso()
        self.store.upsert_order(OrderRecord(
            client_order_id="0xdeadbeef" + "00" * 12,
            setup_key=rec.setup_key, asset="BTC", side="sell",
            level_role="init_sl", qty=0.5, price=99.5,
            status="live", exchange_order_id=None,
            created_at=now, updated_at=now,
        ))
        # ...but the exchange shows no orders and no position.
        result = reconcile(_FakeExchange(), self.store)
        self.assertEqual(result.category, "AMBIGUOUS")
        self.assertTrue(
            any("missing order" in i for i in result.issues),
            msg=result.issues,
        )

    def test_ambiguous_when_surplus_order_on_exchange(self) -> None:
        ex = _FakeExchange(open_orders=[
            OpenOrder(coin="BTC", cloid="0xfeedface" + "00" * 12,
                      oid=1, side="B", qty=0.5, price=100.0,
                      reduce_only=False, raw={}),
        ])
        result = reconcile(ex, self.store)
        self.assertEqual(result.category, "AMBIGUOUS")
        self.assertTrue(
            any("surplus open order" in i for i in result.issues),
            msg=result.issues,
        )

    def test_resumable_when_state_and_exchange_match(self) -> None:
        rec = _make_setup()
        self.store.upsert_setup(rec)
        self.store.set_state(rec.setup_key, "entered")
        sl_cloid = "0xabc" + "0" * 29
        tp1_cloid = "0xdef" + "0" * 29
        now = now_iso()
        for cloid, role, price in (
            (sl_cloid, "init_sl", 99.5), (tp1_cloid, "tp1", 101.18),
        ):
            self.store.upsert_order(OrderRecord(
                client_order_id=cloid, setup_key=rec.setup_key,
                asset="BTC", side="sell", level_role=role,
                qty=0.5, price=price, status="live",
                exchange_order_id=None,
                created_at=now, updated_at=now,
            ))
        ex = _FakeExchange(
            open_orders=[
                OpenOrder(coin="BTC", cloid=sl_cloid, oid=1, side="A",
                          qty=0.5, price=99.5, reduce_only=True, raw={}),
                OpenOrder(coin="BTC", cloid=tp1_cloid, oid=2, side="A",
                          qty=0.5, price=101.18, reduce_only=True, raw={}),
            ],
            positions=[
                Position(coin="BTC", size=0.5, entry_px=100.59,
                         unrealized_pnl=0.0, raw={}),
            ],
        )
        result = reconcile(ex, self.store)
        self.assertEqual(result.category, "RESUMABLE", msg=result.issues)
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
