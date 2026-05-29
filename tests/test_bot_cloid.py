"""Tests for the deterministic cloid scheme.

DEV-ONLY iteration aid — NOT part of the Codex-owned regression suite.
The authoritative contract lives in docs/db1_live_bot_acs/cloid.md. This
file may be deleted once Codex's regression suite covers AC-CLOID-* there.
"""
from __future__ import annotations

import unittest

from apps.bot.strategy.cloid import make_cloid


class CloidTests(unittest.TestCase):
    def test_deterministic(self) -> None:
        a = make_cloid("BTC|up|2026-05-01T00:00:00|2026-05-02T00:00:00", "entry")
        b = make_cloid("BTC|up|2026-05-01T00:00:00|2026-05-02T00:00:00", "entry")
        self.assertEqual(a, b)

    def test_distinguishes_setup_role_seq(self) -> None:
        base = "BTC|up|2026-05-01T00:00:00|2026-05-02T00:00:00"
        keys = [
            make_cloid(base, "entry"),
            make_cloid(base, "init_sl"),
            make_cloid(base, "tp1"),
            make_cloid(base, "tp2"),
            make_cloid(base, "tp3"),
            make_cloid(base, "be_close", 1),
            make_cloid(base, "be_close", 2),
            make_cloid("BTC|up|2026-05-01T00:00:00|2026-05-02T05:00:00", "entry"),
        ]
        self.assertEqual(len(set(keys)), len(keys), "cloids collided")

    def test_hyperliquid_format(self) -> None:
        cloid = make_cloid("any-key", "entry")
        # HL requires "0x" + 32 hex chars (16 bytes / 128 bits).
        self.assertEqual(len(cloid), 34)
        self.assertTrue(cloid.startswith("0x"))
        int(cloid, 16)  # parses as hex


if __name__ == "__main__":
    unittest.main()
