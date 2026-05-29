"""Tests for the bot's SQLite state store.

DEV-ONLY iteration aid — NOT part of the Codex-owned regression suite.
The authoritative contract lives in docs/db1_live_bot_acs/state.md. This
file may be deleted once Codex's regression suite covers AC-STATE-* there.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dataclasses import replace

from apps.bot.state import (
    OrderRecord,
    SetupRecord,
    StateStore,
    now_iso,
    setup_key_for,
)


def _make_setup(asset: str = "BTC", parent_ts: str = "2026-05-01T00:00:00",
                term_ts: str = "2026-05-02T05:00:00") -> SetupRecord:
    return SetupRecord(
        setup_key=setup_key_for(asset, "up", parent_ts, term_ts),
        asset=asset, direction="up",
        parent_ts=parent_ts, parent_price=66000.0,
        term_ts=term_ts, term_price=68500.0,
        detector_min_bars=6, detector_mult=2.0,
        detected_at=now_iso(),
    )


class StateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "state.db"
        self.store = StateStore(self.db_path)

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_upsert_setup_is_idempotent(self) -> None:
        rec = _make_setup()
        self.assertTrue(self.store.upsert_setup(rec))   # new
        self.assertFalse(self.store.upsert_setup(rec))  # dup, no-op
        got = self.store.get_setup(rec.setup_key)
        self.assertEqual(got, rec)

    def test_list_setups_filters_by_asset(self) -> None:
        self.store.upsert_setup(_make_setup(asset="BTC"))
        self.store.upsert_setup(_make_setup(asset="ETH",
                                             parent_ts="2026-05-03T00:00:00",
                                             term_ts="2026-05-04T05:00:00"))
        self.assertEqual(len(self.store.list_setups()), 2)
        self.assertEqual(len(self.store.list_setups(asset="BTC")), 1)
        self.assertEqual(len(self.store.list_setups(asset="ETH")), 1)
        self.assertEqual(len(self.store.list_setups(asset="SOL")), 0)

    def test_state_transitions_record_history(self) -> None:
        rec = _make_setup()
        self.store.upsert_setup(rec)
        self.store.set_state(rec.setup_key, "detected", {"foo": 1})
        self.store.set_state(rec.setup_key, "armed", {"limit": 65000})
        self.store.set_state(rec.setup_key, "entered", {"fill": 65010})
        s = self.store.get_state(rec.setup_key)
        self.assertIsNotNone(s)
        self.assertEqual(s.state, "entered")
        self.assertEqual(s.payload, {"fill": 65010})

        # Transition log should have 3 entries with from-state chaining.
        rows = list(self.store._conn.execute(
            "SELECT from_state, to_state FROM state_transitions "
            "WHERE setup_key = ? ORDER BY id;", (rec.setup_key,)
        ))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["from_state"], None)
        self.assertEqual(rows[0]["to_state"], "detected")
        self.assertEqual(rows[1]["from_state"], "detected")
        self.assertEqual(rows[1]["to_state"], "armed")
        self.assertEqual(rows[2]["from_state"], "armed")
        self.assertEqual(rows[2]["to_state"], "entered")

    def test_order_upsert_updates_status(self) -> None:
        rec = _make_setup()
        self.store.upsert_setup(rec)
        now = now_iso()
        order = OrderRecord(
            client_order_id="db1-BTC-entry-1",
            setup_key=rec.setup_key, asset="BTC", side="buy",
            level_role="entry", qty=0.1, price=65000.0,
            status="pending", exchange_order_id=None,
            created_at=now, updated_at=now,
        )
        self.store.upsert_order(order)
        open_orders = self.store.open_orders_for(rec.setup_key)
        self.assertEqual(len(open_orders), 1)
        self.assertEqual(open_orders[0].status, "pending")

        # Promote to live, then filled.
        self.store.upsert_order(
            replace(order, status="live",
                    exchange_order_id="ex-123", updated_at=now_iso())
        )
        self.store.upsert_order(
            replace(order, status="filled", updated_at=now_iso())
        )
        # Filled orders are no longer "open".
        self.assertEqual(len(self.store.open_orders_for(rec.setup_key)), 0)

    def test_reopening_db_preserves_data(self) -> None:
        rec = _make_setup()
        self.store.upsert_setup(rec)
        self.store.set_state(rec.setup_key, "detected")
        self.store.close()

        store2 = StateStore(self.db_path)
        try:
            self.assertEqual(store2.get_setup(rec.setup_key), rec)
            s = store2.get_state(rec.setup_key)
            self.assertIsNotNone(s)
            self.assertEqual(s.state, "detected")
        finally:
            store2.close()
        # Re-open the original handle so tearDown doesn't choke on a closed db.
        self.store = StateStore(self.db_path)


if __name__ == "__main__":
    unittest.main()
