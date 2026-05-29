"""Parity test: bot FSM/simulator must reproduce execute()'s trade outcomes.

CANONICAL REGRESSION TEST — KEEP. This file is part of the Codex-owned
regression suite. It enforces docs/db1_live_bot_acs/fsm_parity.md (AC-PARITY-*)
and is the M2 exit-criterion check from PRD §10 Phase 0.

Coverage: the four CORRECTED_SWINGS the user hand-validated, every leg
detected on the default (12-month BTC) dataset at both PRD-default and a
coarser detector, plus the full 8+year Binance BTC history when present.
"""
from __future__ import annotations

import csv
import unittest
from pathlib import Path

from apps.bot.config import StrategyConfig
from apps.bot.simulation.paper_executor import simulate_setup
from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from apps.worker.discovery_bet_1.swing_detector import clean_legs
from apps.worker.discovery_bet_1.types import Candle
from scripts.execute_fib_strategy import execute
from scripts.place_fibs_tradingview import CORRECTED_SWINGS

REPO_ROOT = Path(__file__).resolve().parents[1]
LONG_HISTORY_BTC = (
    REPO_ROOT / "data" / "discovery_bet_1" / "binance_btcusdt_1h_full_history.csv"
)


def _load_csv_no_provenance(path: Path) -> list[Candle]:
    """Plain CSV loader matching scripts/backtest_long_horizon.py's load_csv.

    The long-history datasets ship without the provenance sidecar that
    apps/worker/discovery_bet_1/candle_input.py requires; the backtest
    scripts read them directly, so we do the same here.
    """
    out: list[Candle] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Candle(
                source_timestamp=row["source_timestamp"],
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
                volume=float(row["volume"]),
            ))
    return out


class FsmParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candles = load_candle_input(DEFAULT_INPUT_PATH).candles
        cls.atr = calculate_atr14(cls.candles)
        cls.idx = {c.source_timestamp: i for i, c in enumerate(cls.candles)}
        cls.cfg = StrategyConfig()  # PRD defaults: 0.941 entry, 1.05 SL, etc.

    def _assert_parity(self, swing: dict) -> None:
        gold = execute(self.candles, self.idx, swing)
        sim = simulate_setup(swing, self.candles, self.idx, self.cfg)
        # status must match exactly
        self.assertEqual(
            sim["status"], gold["status"],
            msg=f"status mismatch on {swing}: sim={sim['status']!r} "
                f"gold={gold['status']!r}",
        )
        # R must match within rounding
        self.assertAlmostEqual(
            sim["r"], gold["r"], places=9,
            msg=f"R mismatch on {swing}: sim={sim['r']} gold={gold['r']}",
        )

    def test_parity_on_corrected_swings(self) -> None:
        """The four CORRECTED_SWINGS the user reviewed by eye must all match."""
        for swing in CORRECTED_SWINGS:
            with self.subTest(name=swing.get("name_prefix")):
                self._assert_parity(swing)

    def test_parity_on_detected_legs(self) -> None:
        """Every detected leg on the recent-3M dataset must match."""
        legs = clean_legs(self.candles, self.atr, None, min_bars=24, mult=4.0)
        self.assertGreater(len(legs), 0)
        for leg in legs:
            with self.subTest(term_ts=leg["term_ts"]):
                self._assert_parity(leg)

    def test_parity_on_fine_detector(self) -> None:
        """And on the PRD's live-bot detector params (6/2.0), much denser."""
        legs = clean_legs(self.candles, self.atr, None, min_bars=6, mult=2.0)
        self.assertGreater(len(legs), 50)
        for leg in legs:
            with self.subTest(term_ts=leg["term_ts"]):
                self._assert_parity(leg)

    @unittest.skipUnless(
        LONG_HISTORY_BTC.exists(),
        "Long-history BTC dataset not present in this checkout",
    )
    def test_parity_on_btc_long_history(self) -> None:
        """8+ years of BTC at the PRD detector. The strongest parity bar."""
        candles = _load_csv_no_provenance(LONG_HISTORY_BTC)
        atr = calculate_atr14(candles)
        idx = {c.source_timestamp: i for i, c in enumerate(candles)}
        legs = clean_legs(candles, atr, None, min_bars=6, mult=2.0)
        self.assertGreater(len(legs), 1000,
                           msg="Expected a deep leg set across 8 years")
        mismatches = 0
        for leg in legs:
            gold = execute(candles, idx, leg)
            sim = simulate_setup(leg, candles, idx, self.cfg)
            if (sim["status"] != gold["status"]
                    or abs(sim["r"] - gold["r"]) > 1e-9):
                mismatches += 1
        self.assertEqual(
            mismatches, 0,
            msg=f"{mismatches}/{len(legs)} legs disagreed with execute()",
        )


if __name__ == "__main__":
    unittest.main()
