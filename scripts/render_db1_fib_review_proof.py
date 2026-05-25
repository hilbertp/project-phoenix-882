#!/usr/bin/env python
"""Render local proof images for the DB1 auto-Fib review structures.

Produces two PNGs in artifacts/discovery_bet_1/:
  - db1_auto_fib_review_overview.png : all structures over the full 12 months
  - db1_auto_fib_review_zoom_grid.png : one zoom panel per structure for anchor review

This mirrors what the TradingView Pine overlay draws, but locally, so anchor
quality can be judged without a TradingView session.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from apps.api.db1_fib_review_pine_read.service import PHOENIX_FIB_LEVELS
from apps.worker.discovery_bet_1.anchor_selection import ATR_MULTIPLIER
from apps.worker.discovery_bet_1.atr import ATR_PERIOD, calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.fib_structures import build_fib_candidates
from apps.worker.discovery_bet_1.lifecycle import materialize_fib_structures
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH

ARTIFACTS = Path("artifacts/discovery_bet_1")
UP = "#26a69a"
DOWN = "#ef5350"
BG = "#0e1117"
FG = "#d0d4dc"


def _dt(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00").split("+")[0])


def _load():
    candles = load_candle_input(DEFAULT_INPUT_PATH).candles
    atr = calculate_atr14(candles)
    pivots = detect_local_pivots(candles)
    cands, _ = build_fib_candidates(pivots, atr)
    structures = materialize_fib_structures(cands, candles)
    return candles, structures


def _level_price(terminal: float, parent: float, coeff: float) -> float:
    return terminal + (parent - terminal) * coeff


def _draw_candles(ax, window) -> None:
    for c in window:
        x = _dt(c.source_timestamp)
        color = UP if c.close >= c.open else DOWN
        ax.plot([x, x], [c.low, c.high], color=color, linewidth=0.6, alpha=0.7)
        ax.plot([x, x], [c.open, c.close], color=color, linewidth=2.2, alpha=0.9)


def render_overview(candles, structures, out: Path) -> None:
    times = [_dt(c.source_timestamp) for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]

    fig, ax = plt.subplots(figsize=(28, 11))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.fill_between(times, lows, highs, color="#2a2e39", alpha=0.6, linewidth=0)
    ax.plot(times, closes, color="#8893a6", linewidth=0.7, alpha=0.9)

    for idx, s in enumerate(structures, start=1):
        is_up = str(s.direction) == "up"
        color = UP if is_up else DOWN
        px, py = _dt(s.parent_anchor_source_timestamp), s.parent_anchor_price
        tx, ty = _dt(s.terminal_extreme_source_timestamp), s.terminal_extreme_price
        ax.plot([px, tx], [py, ty], color=color, linewidth=2.0)
        high_xy = (px, py) if py >= ty else (tx, ty)
        low_xy = (tx, ty) if py >= ty else (px, py)
        ax.scatter(*high_xy, marker="v", s=42, color="#b2ff59", zorder=5, edgecolors="black", linewidths=0.4)
        ax.scatter(*low_xy, marker="^", s=42, color="#ea80fc", zorder=5, edgecolors="black", linewidths=0.4)
        for coeff in PHOENIX_FIB_LEVELS:
            lvl = _level_price(ty, py, coeff)
            ax.plot([px, tx], [lvl, lvl], color="#6b7280", linewidth=0.6, alpha=0.6)
        ax.annotate(str(idx), xy=((px if is_up else tx), max(py, ty)),
                    color=FG, fontsize=7, ha="center", va="bottom")

    ax.set_title(
        "DB1 Auto Fib Candidate Review (REVIEW ONLY - not entry/buy/sell)  |  "
        "BITGET:BTCUSDT.P 1H last 12 months  |  "
        f"ATR len {ATR_PERIOD}, up/down ATR x {ATR_MULTIPLIER}, pivot 2L/2R  |  "
        f"{len(structures)} accepted structures",
        color=FG, fontsize=13,
    )
    ax.tick_params(colors=FG)
    for spine in ax.spines.values():
        spine.set_color("#2a2e39")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.grid(color="#1c2230", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(out, dpi=110, facecolor=BG)
    plt.close(fig)


def render_zoom_grid(candles, structures, out: Path, context: int = 60) -> None:
    n = len(structures)
    cols = 4
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(7 * cols, 4.2 * rows))
    fig.patch.set_facecolor(BG)
    axes = axes.flatten()

    index_by_stamp = {c.source_timestamp: i for i, c in enumerate(candles)}
    for ax in axes[n:]:
        ax.set_visible(False)

    for idx, s in enumerate(structures):
        ax = axes[idx]
        ax.set_facecolor(BG)
        pi = index_by_stamp[s.parent_anchor_source_timestamp]
        ti = index_by_stamp[s.terminal_extreme_source_timestamp]
        lo = max(0, min(pi, ti) - context)
        hi = min(len(candles), max(pi, ti) + context)
        window = candles[lo:hi]
        _draw_candles(ax, window)

        is_up = str(s.direction) == "up"
        color = UP if is_up else DOWN
        px, py = _dt(s.parent_anchor_source_timestamp), s.parent_anchor_price
        tx, ty = _dt(s.terminal_extreme_source_timestamp), s.terminal_extreme_price
        ax.plot([px, tx], [py, ty], color=color, linewidth=1.6, zorder=4)
        high_xy = (px, py) if py >= ty else (tx, ty)
        low_xy = (tx, ty) if py >= ty else (px, py)
        ax.scatter(*high_xy, marker="v", s=70, color="#b2ff59", zorder=6, edgecolors="black", linewidths=0.5)
        ax.scatter(*low_xy, marker="^", s=70, color="#ea80fc", zorder=6, edgecolors="black", linewidths=0.5)
        xs = [_dt(c.source_timestamp) for c in window]
        x0, x1 = min(xs), max(xs)
        for coeff in PHOENIX_FIB_LEVELS:
            lvl = _level_price(ty, py, coeff)
            ax.plot([x0, x1], [lvl, lvl], color="#6b7280", linewidth=0.7, alpha=0.7)
            ax.annotate(f"{coeff:.3f}", xy=(x1, lvl), color="#9aa4b2", fontsize=6, va="center")

        direction_txt = "bullish low->high" if is_up else "bearish high->low"
        active = " [active]" if not s.invalidated_at_source_timestamp else ""
        ax.set_title(f"#{idx + 1} {s.structure_id} {direction_txt}{active}",
                     color=FG, fontsize=9)
        ax.tick_params(colors=FG, labelsize=6)
        for spine in ax.spines.values():
            spine.set_color("#2a2e39")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %Hh"))
        ax.grid(color="#1c2230", linewidth=0.4)

    fig.suptitle(
        "DB1 Auto Fib anchor review - per structure (green v = accepted swing high, "
        "purple ^ = accepted swing low, grey = Phoenix fib 0.5-1.0)",
        color=FG, fontsize=14,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    fig.savefig(out, dpi=95, facecolor=BG)
    plt.close(fig)


def main() -> None:
    candles, structures = _load()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    overview = ARTIFACTS / "db1_auto_fib_review_overview.png"
    zoom = ARTIFACTS / "db1_auto_fib_review_zoom_grid.png"
    render_overview(candles, structures, overview)
    render_zoom_grid(candles, structures, zoom)
    print(overview)
    print(zoom)
    print(f"structures={len(structures)} candles={len(candles)}")


if __name__ == "__main__":
    main()
