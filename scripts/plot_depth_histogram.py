#!/usr/bin/env python
"""Plot the ATR-depth distribution of the detected DB1 setups with a normal-curve
overlay, to judge how Gaussian it is. Output: artifacts/discovery_bet_1/depth_histogram.png
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from scripts.place_fibs_tradingview import RECENT_3M_FROM, _clean_legs

MIN_BARS, MULT = 24, 4.0
OUT = REPO_ROOT / "artifacts" / "discovery_bet_1" / "depth_histogram.png"


def main() -> None:
    candles = load_candle_input(DEFAULT_INPUT_PATH).candles
    atr = calculate_atr14(candles)
    pivots = detect_local_pivots(candles)
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    legs = [
        leg for leg in _clean_legs(candles, atr, pivots, min_bars=MIN_BARS, mult=MULT)
        if leg["parent_ts"] >= RECENT_3M_FROM
    ]
    depths = np.array(
        [
            abs(leg["term_price"] - leg["parent_price"]) / (atr[idx[leg["term_ts"]]] or 1.0)
            for leg in legs
        ]
    )
    mu, sd = depths.mean(), depths.std(ddof=1)
    skew = float(((depths - mu) ** 3).mean() / sd**3)

    fig, ax = plt.subplots(figsize=(9, 5))
    bins = np.arange(4, 22, 1)
    ax.hist(depths, bins=bins, color="#2962ff", edgecolor="white", alpha=0.85,
            label=f"{len(depths)} setups")
    xs = np.linspace(4, 21, 200)
    pdf = (1 / (sd * math.sqrt(2 * math.pi))) * np.exp(-0.5 * ((xs - mu) / sd) ** 2)
    ax.plot(xs, pdf * len(depths), color="#f0b90b", lw=2,
            label=f"normal fit (μ={mu:.1f}, σ={sd:.1f})")
    ax.axvline(MULT, color="#ef5350", ls="--", lw=1.5, label=f"{MULT:.0f}× ATR gate (hard floor)")
    ax.axvline(mu, color="#26a69a", ls=":", lw=1.5, label=f"mean {mu:.1f}×")
    ax.set_xlabel("leg depth (× hourly ATR14)")
    ax.set_ylabel("number of setups")
    ax.set_title(
        f"DB1 setup depth distribution ({MIN_BARS}c / {MULT:.0f}×, recent 3M) "
        f"— skew {skew:+.2f}"
    )
    ax.set_xticks(np.arange(4, 22, 1))
    ax.legend()
    ax.grid(alpha=0.2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT, dpi=110)
    print(f"WROTE {OUT}")
    print(f"n={len(depths)} mean={mu:.2f} std={sd:.2f} skew={skew:+.2f} "
          f"min={depths.min():.1f} max={depths.max():.1f} median={np.median(depths):.1f}")


if __name__ == "__main__":
    main()
