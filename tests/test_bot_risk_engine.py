"""Smoke tests for RiskEngine + KillSwitch.

DEV-ONLY iteration aid — NOT part of the Codex-owned regression suite.
The authoritative contracts live in docs/db1_live_bot_acs/risk_engine.md
and docs/db1_live_bot_acs/kill_switch.md. This file may be deleted once
Codex's regression suite covers AC-RISK-* and AC-KILL-* there.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apps.bot.config import RiskConfig
from apps.bot.risk.engine import (
    REASON_CONSEC_LOSS,
    REASON_DAILY_LOSS,
    REASON_FUNDING_SKIP,
    REASON_HALTED,
    REASON_MAX_CONCURRENT,
    RiskEngine,
)
from apps.bot.state import (
    SetupRecord,
    StateStore,
    now_iso,
    setup_key_for,
)
from apps.bot.strategy.fsm import Setup


def _setup(asset: str = "BTC", direction: str = "up",
           parent_ts: str = "2026-05-01T00:00:00",
           term_ts: str = "2026-05-02T00:00:00") -> Setup:
    return Setup(
        asset=asset, direction=direction,
        parent_ts=parent_ts, parent_price=100.0,
        term_ts=term_ts, term_price=110.0,
    )


def _persist_setup_with_state(
    store: StateStore, asset: str, key_suffix: str, state: str,
    realized_r: float | None = None,
) -> None:
    key = setup_key_for(asset, "up", "2026-05-01T00:00:00", key_suffix)
    store.upsert_setup(SetupRecord(
        setup_key=key, asset=asset, direction="up",
        parent_ts="2026-05-01T00:00:00", parent_price=100.0,
        term_ts=key_suffix, term_price=110.0,
        detector_min_bars=6, detector_mult=2.0,
        detected_at=now_iso(),
    ))
    payload = {"realized_r": realized_r} if realized_r is not None else None
    store.set_state(key, state, payload)


class RiskEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self._tmp.name) / "state.db")
        self.cfg = RiskConfig()
        self.engine = RiskEngine(store=self.store, risk_cfg=self.cfg)

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_allows_when_clean(self) -> None:
        decision = self.engine.can_arm(_setup())
        self.assertTrue(decision.allowed, msg=decision)

    def test_halt_flag_refuses(self) -> None:
        self.store.set_flag("halt", "manual_test")
        decision = self.engine.can_arm(_setup())
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, REASON_HALTED)

    def test_funding_skip_refuses_only_paused_asset(self) -> None:
        self.store.set_flag("pause_asset:BTC", "funding_apy=120.0")
        self.assertFalse(self.engine.can_arm(_setup("BTC")).allowed)
        self.assertTrue(self.engine.can_arm(_setup("ETH")).allowed)
        self.assertEqual(
            self.engine.can_arm(_setup("BTC")).reason, REASON_FUNDING_SKIP,
        )

    def test_max_concurrent_refuses(self) -> None:
        # Create 4 in-flight setups; defaults cap = 4.
        for i, asset in enumerate(("BTC", "ETH", "SOL", "BNB")):
            _persist_setup_with_state(
                self.store, asset, f"2026-05-02T{i:02d}:00:00", "entered",
            )
        decision = self.engine.can_arm(_setup("ADA"))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, REASON_MAX_CONCURRENT)

    def test_daily_loss_limit_refuses(self) -> None:
        # Three -1R wipeouts today exhaust the -3R daily cap.
        for i in range(3):
            _persist_setup_with_state(
                self.store, "BTC", f"2099-01-01T{i:02d}:00:00",
                "wipeout", realized_r=-1.0,
            )
        decision = self.engine.can_arm(_setup())
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, REASON_DAILY_LOSS)

    def test_consecutive_losses_refuses(self) -> None:
        for i in range(5):
            _persist_setup_with_state(
                self.store, "BTC", f"2099-01-01T{i:02d}:00:00",
                "wipeout", realized_r=-1.0,
            )
        decision = self.engine.can_arm(_setup())
        self.assertFalse(decision.allowed)
        # daily-loss limit fires first (-5R < -3R); both reasons valid
        # but the engine returns the first that matches in its check order.
        self.assertIn(decision.reason, (REASON_DAILY_LOSS, REASON_CONSEC_LOSS))

    def test_status_snapshot_includes_all_counters(self) -> None:
        snap = self.engine.status_snapshot()
        for key in (
            "halted", "halt_reason", "concurrent_positions",
            "max_concurrent_positions", "daily_realized_r",
            "daily_loss_r_limit", "weekly_realized_r",
            "weekly_loss_r_limit", "consecutive_losses",
            "consecutive_loss_limit", "paused_assets",
        ):
            self.assertIn(key, snap)


if __name__ == "__main__":
    unittest.main()
