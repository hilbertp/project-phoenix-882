#!/usr/bin/env python
"""Sweep detector params (min-bars x ATR-multiple) on one asset and score every
regime, so we can re-tune detection for an asset whose swing frequency differs
from BTC (the default 24c/4xATR was tuned on BTC).

Usage: sweep_asset_detector.py <csv_path> [label]
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

MINBARS_GRID = [6, 9, 12, 18, 24, 36]
MULT_GRID = [2.0, 2.5, 3.0, 4.0]
REGS = [{"slug": r["slug"], "label": r["label"], "params": r["params"]} for r in REGIMES]
REGS.append({"slug": "scaled", "label": "Scaled", "scaled": True})


def score(legs, candles, idx, reg):
    rows = []
    for leg in legs:
        if leg["term_ts"] not in idx:
            continue
        res = run_regime(candles, idx, leg, reg)
        rows.append({"kind": KIND.get(res["status"], "open"), "r": res["r"],
                     "direction": leg["direction"]})
    a = aggregate(rows)
    return a


def main() -> None:
    csv_path = sys.argv[1]
    label = sys.argv[2] if len(sys.argv) > 2 else Path(csv_path).stem
    candles = load_candles(Path(csv_path))
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    atr = calculate_atr14(candles)
    piv = detect_local_pivots(candles)

    print(f"Detector sweep on {label} ({len(candles)} candles)")
    print("total R per regime (and N detected setups) across min-bars x ATR-mult\n")
    hdr = f"{'min_bars':>8}{'mult':>6}{'N':>5}" + "".join(f"{r['label'][:8]:>10}" for r in REGS)
    print(hdr)
    best = None
    for mb in MINBARS_GRID:
        for mult in MULT_GRID:
            legs = [leg for leg in _clean_legs(candles, atr, piv, min_bars=mb, mult=mult)
                    if leg["term_ts"] in idx]
            cells = []
            for reg in REGS:
                a = score(legs, candles, idx, reg)
                cells.append(a["total_r"])
                if reg["slug"] == "scaled":
                    cand = (a["total_r"], mb, mult, a["n"], a["win_rate"])
                    if best is None or cand[0] > best[0]:
                        best = cand
            print(f"{mb:>8}{mult:>6.1f}{len(legs):>5}" + "".join(f"{v:>+10.1f}" for v in cells))
    print(f"\nbest scaled total R: {best[0]:+.1f}  at min_bars={best[1]} mult={best[2]} "
          f"(N={best[3]} triggered, win {best[4]*100:.0f}%)")


if __name__ == "__main__":
    main()
