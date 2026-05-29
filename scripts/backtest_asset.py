#!/usr/bin/env python
"""Backtest the entry regimes (incl. the scaled strategy) on any asset's
DETECTOR-found setups -- a cross-asset / out-of-sample check.

Runs the ATR-zigzag detector (24 candles / 4x ATR) over a 1H candle CSV, then
scores every regime in the catalog plus the scaled strategy with the SAME fixed
executor the dashboard uses. No human review is involved (there are no labels for
non-BTC assets), so this is raw detector output -- use it to see whether the
deep-entry / scaled edge generalizes, not as a clean ground-truth score.

Usage: backtest_asset.py <label> <csv_path>
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candles
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from scripts.build_dashboard import KIND, aggregate
from scripts.execute_fib_strategy import REGIMES, run_regime
from scripts.place_fibs_tradingview import _clean_legs

MIN_BARS, MULT = 24, 4.0
SCALED = {"slug": "scaled", "label": "Scaled 786/882/941", "scaled": True}


def score_asset(label: str, csv_path: str) -> None:
    candles = load_candles(Path(csv_path))
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    atr = calculate_atr14(candles)
    piv = detect_local_pivots(candles)
    legs = [leg for leg in _clean_legs(candles, atr, piv, min_bars=MIN_BARS, mult=MULT)
            if leg["term_ts"] in idx]

    print(f"\n=== {label} ===  {len(candles)} candles  |  {len(legs)} detector setups "
          f"({MIN_BARS}c / {MULT:.0f}xATR)")
    print(f"{'regime':<22}{'N':>4}{'shrug':>7}{'win%':>7}{'loss%':>7}{'even':>6}"
          f"{'avgR':>8}{'totR':>8}")
    regimes = [{"slug": r["slug"], "label": r["label"], "params": r["params"]} for r in REGIMES]
    regimes.append(SCALED)
    for reg in regimes:
        rows = []
        for leg in legs:
            res = run_regime(candles, idx, leg, reg)
            rows.append({"kind": KIND.get(res["status"], "open"),
                         "r": res["r"], "direction": leg["direction"]})
        a = aggregate(rows)
        even = sum(1 for r in rows if r["kind"] == "even")
        print(f"{reg['label']:<22}{a['n']:>4}{a['shrug']:>7}{a['win_rate']*100:>6.0f}%"
              f"{a['loss_rate']*100:>6.0f}%{even:>6}{a['avg_r']:>+8.3f}{a['total_r']:>+8.1f}")


def main() -> None:
    if len(sys.argv) >= 3:
        score_asset(sys.argv[1], sys.argv[2])
    else:
        print("usage: backtest_asset.py <label> <csv_path>")


if __name__ == "__main__":
    main()
