"""Tests for the bot's config loader.

DEV-ONLY iteration aid — NOT part of the Codex-owned regression suite.
The authoritative contract lives in docs/db1_live_bot_acs/config.md. This
file may be deleted once Codex's regression suite covers AC-CFG-* there.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apps.bot.config import DEFAULT_UNIVERSE, BotConfig, load_config


class ConfigDefaultsTests(unittest.TestCase):
    def test_defaults_match_prd(self) -> None:
        cfg = load_config()
        self.assertEqual(cfg.mode, "paper")
        self.assertEqual(cfg.universe, DEFAULT_UNIVERSE)
        self.assertEqual(cfg.detector.min_bars, 6)
        self.assertEqual(cfg.detector.mult, 2.0)
        self.assertEqual(cfg.detector.interval, "1h")
        self.assertEqual(cfg.strategy.entry_coeff, 0.941)
        self.assertEqual(cfg.strategy.init_sl_coeff, 1.05)
        self.assertEqual(cfg.strategy.tp1_size, 0.25)
        self.assertEqual(cfg.strategy.tp2_size, 0.60)
        self.assertEqual(cfg.strategy.tp3_size, 0.15)
        self.assertEqual(cfg.risk.account_risk_pct, 1.0)
        self.assertFalse(cfg.hyperliquid.testnet)
        self.assertEqual(cfg.hyperliquid.rest_url, "https://api.hyperliquid.xyz")


class ConfigTomlOverrideTests(unittest.TestCase):
    def test_toml_overrides_defaults(self) -> None:
        body = """
        [bot]
        mode = "live"
        state_db_path = "/tmp/phoenix-test/state.db"

        [universe]
        assets = ["BTC", "ETH"]

        [detector]
        min_bars = 24
        mult = 3.0

        [strategy]
        entry_coeff = 0.786

        [risk]
        account_risk_pct = 0.5

        [hyperliquid]
        testnet = true
        """
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(body)
            path = fh.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg.mode, "live")
            self.assertEqual(cfg.universe, ("BTC", "ETH"))
            self.assertEqual(cfg.detector.min_bars, 24)
            self.assertEqual(cfg.detector.mult, 3.0)
            self.assertEqual(cfg.strategy.entry_coeff, 0.786)
            self.assertEqual(cfg.risk.account_risk_pct, 0.5)
            self.assertTrue(cfg.hyperliquid.testnet)
            self.assertEqual(cfg.hyperliquid.rest_url,
                             "https://api.hyperliquid-testnet.xyz")
            self.assertEqual(cfg.state_db_path, Path("/tmp/phoenix-test/state.db"))
        finally:
            os.unlink(path)

    def test_env_overrides_account_address(self) -> None:
        with mock.patch.dict(os.environ,
                             {"PHOENIX_HL_ACCOUNT_ADDRESS": "0xdeadbeef"}):
            cfg = load_config()
        self.assertEqual(cfg.hyperliquid.account_address, "0xdeadbeef")

    def test_unknown_keys_rejected(self) -> None:
        body = "[detector]\nunknown_key = 1\n"
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(body)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                load_config(path)
        finally:
            os.unlink(path)


class ConfigValidationTests(unittest.TestCase):
    def test_invalid_mode_rejected(self) -> None:
        body = '[bot]\nmode = "live-yolo"\n'
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(body)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                load_config(path)
        finally:
            os.unlink(path)

    def test_tp_sizes_must_sum_to_one(self) -> None:
        body = "[strategy]\ntp1_size = 0.5\ntp2_size = 0.3\ntp3_size = 0.3\n"
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(body)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                load_config(path)
        finally:
            os.unlink(path)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_config("/does/not/exist.toml")


class ConfigDetectorLoopIntegrationTests(unittest.TestCase):
    def test_config_is_frozen_dataclass(self) -> None:
        cfg = load_config()
        with self.assertRaises(Exception):
            cfg.mode = "live"  # frozen


if __name__ == "__main__":
    unittest.main()
