#!/usr/bin/env python
"""Stratified-sample ADA 15m setups (6c / 2.0x ATR detector) and render one PNG
per setup for human visual review.

Each PNG shows: candlesticks around the setup (with padding), the parent and
terminal pivots marked, all phoenix-fib levels drawn (0, 0.5, 0.618, 0.786,
0.882, 0.941, 1.0, 1.05), and the executed events for the 0.941 entry regime
(entry, BE drag, TP1/TP2/TP3, SL where applicable).

Sampling: 60 setups total, stratified across {4-6 ATR, 6-8 ATR, 8-10 ATR} x
{win, scratch, loss, open} so the sheet reflects the population the strategy
trades, not just the typical case.

Output: artifacts/discovery_bet_1/manual_review_ada_15m/
  - 00_index.csv  -- per-setup metadata + R outcome
  - <id>_<outcome>_<cohort>.png  -- one chart per sampled setup
"""
from __future__ import annotations

import csv
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import ConnectionPatch, Rectangle

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.types import Candle
from scripts.build_dashboard import KIND
from scripts.execute_fib_strategy import REGIMES, run_regime
from scripts.place_fibs_tradingview import _clean_legs

CSV_PATH = REPO_ROOT / "data/discovery_bet_1/binance_adausdt_15m_full_history.csv"
CSV_PATH_5M = REPO_ROOT / "data/discovery_bet_1/binance_adausdt_5m_full_history.csv"
OUT_DIR = REPO_ROOT / "artifacts/discovery_bet_1/manual_review_ada_15m"

# 0.941 entry regime is the headline finding -- review against that one.
REG_941 = next(r for r in REGIMES if r["slug"] == "x941")

# Sampling spec: 60 cards total, stratified.
COHORTS = [(4, 6), (6, 8), (8, 10)]
OUTCOMES = ("win", "partial", "loss", "scratch", "open")
TARGET_PER_BUCKET = 5    # 3 cohorts * 4 dominant outcomes = ~60 cards
SAMPLE_SEED = 882        # reproducible

# Chart appearance
BG = "#0e1117"
PANEL = "#161b22"
FG = "#d0d4dc"
GRID = "#262d38"
UP = "#26a69a"
DOWN = "#ef5350"
PARENT_C = "#facc15"
TERM_C = "#60a5fa"
ENTRY_C = "#22c55e"
SL_C = "#ef4444"
TP_C = "#a78bfa"
BE_C = "#f59e0b"

LEVELS_TO_DRAW = [
    (0.0, "#94a3b8", "TP3 0.0"),
    (0.5, "#94a3b8", "TP2 0.5"),
    (0.618, "#94a3b8", "0.618"),
    (0.786, "#94a3b8", "0.786"),
    (0.882, "#facc15", "0.882"),
    (0.941, "#22c55e", "0.941 ENTRY"),
    (1.0, "#60a5fa", "parent 1.0"),
    (1.05, "#ef4444", "SL 1.05"),
]

PAD_BEFORE_PARENT = 20      # bars of context before parent pivot
PAD_AFTER_TERM = 50         # bars after term so we can see the outcome unfold


def load_csv(path: Path) -> list[Candle]:
    out: list[Candle] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Candle(row["source_timestamp"], float(row["open"]),
                              float(row["high"]), float(row["low"]),
                              float(row["close"]), float(row["volume"])))
    return out


def _dt(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00").split("+")[0])


def fib_price(parent: float, term: float, coeff: float) -> float:
    return term + coeff * (parent - term)


def cohort_label(depth_atr: float) -> str | None:
    for lo, hi in COHORTS:
        if lo <= depth_atr < hi:
            return f"{lo}-{hi}"
    return None


def find_ambiguous_bars(candles_15m: list[Candle], idx_15m: dict[str, int],
                        leg: dict, res: dict) -> list[dict]:
    """Walk the executor's phase-1 path; find every 15m bar that touches BOTH
    TP1 and SL within the same bar (i.e. the outcome depends on intrabar order).

    Returns a list of {bar_i, bar_ts, hi, lo, tp1, sl, entry} dicts. Empty if the
    trade has no intrabar ambiguity.
    """
    parent = leg["parent_price"]; term = leg["term_price"]
    up = leg["direction"] == "up"
    entry = fib_price(parent, term, 0.941)
    tp1 = fib_price(parent, term, 0.882)
    sl  = fib_price(parent, term, 1.05)

    ti = idx_15m[leg["term_ts"]]
    # find entry bar (matches executor: skip-entry-bar)
    entry_bar = None
    for j in range(ti + 1, len(candles_15m)):
        c = candles_15m[j]
        if up:
            if c.high > term:  return []   # no_trigger
            if c.low <= entry: entry_bar = j; break
        else:
            if c.low < term:    return []
            if c.high >= entry: entry_bar = j; break
    if entry_bar is None:
        return []

    # phase 1 only -- after TP1 the BE-drag changes the SL level and the question
    # we care about ("could SL have hit before TP1?") no longer applies.
    ambig = []
    for j in range(entry_bar + 1, len(candles_15m)):
        c = candles_15m[j]
        hit_tp1 = (c.high >= tp1) if up else (c.low <= tp1)
        hit_sl  = (c.low <= sl)   if up else (c.high >= sl)
        if hit_tp1 and hit_sl:
            ambig.append({"bar_i": j, "bar_ts": c.source_timestamp,
                          "hi": c.high, "lo": c.low, "open": c.open, "close": c.close,
                          "tp1": tp1, "sl": sl, "entry": entry, "up": up})
        if hit_tp1 or hit_sl:
            break   # phase 1 ends here
    return ambig


def draw_magnifier(fig, ax_main, candles_5m: list[Candle], idx_5m: dict[str, int],
                   ambig: dict, slot: int, total_slots: int) -> None:
    """Draw a 5m zoom inset for a single ambiguous 15m bar.

    Layout: insets stack along the right edge of the figure. `slot` is 0..total-1
    (top to bottom). Each shows the 3 5m sub-bars + horizontal lines for TP1,
    SL, entry, with an annotation declaring which level was hit FIRST in time.
    """
    bar_ts = ambig["bar_ts"]
    if bar_ts not in idx_5m:
        return
    base = idx_5m[bar_ts]
    sub = candles_5m[base:base + 3]
    if len(sub) < 3:
        return

    # Resolve order of TP1 / SL hits within the 5m sub-bars.
    up = ambig["up"]; tp1 = ambig["tp1"]; sl = ambig["sl"]
    tp1_idx = sl_idx = None
    sub_ambig = False
    for k, sc in enumerate(sub):
        hit_tp1 = (sc.high >= tp1) if up else (sc.low <= tp1)
        hit_sl  = (sc.low <= sl)   if up else (sc.high >= sl)
        if hit_tp1 and hit_sl:
            sub_ambig = True
            if tp1_idx is None: tp1_idx = k
            if sl_idx is None: sl_idx = k
        elif hit_tp1 and tp1_idx is None:
            tp1_idx = k
        elif hit_sl and sl_idx is None:
            sl_idx = k

    if tp1_idx is not None and sl_idx is not None and tp1_idx != sl_idx:
        verdict = ("TP1 first (executor correct)"
                   if tp1_idx < sl_idx else "SL first (executor OVERCOUNTED -> -1R)")
        verdict_color = ENTRY_C if tp1_idx < sl_idx else SL_C
    elif tp1_idx is not None and sl_idx is None:
        verdict = "TP1 only (executor correct)"; verdict_color = ENTRY_C
    elif sl_idx is not None and tp1_idx is None:
        verdict = "SL only (executor OVERCOUNTED)"; verdict_color = SL_C
    elif sub_ambig:
        verdict = "5m bar still spans both - need 1m"; verdict_color = BE_C
    else:
        verdict = "neither - extended path"; verdict_color = FG

    # Position the inset on the right side of the figure, stacked.
    inset_h = 0.78 / total_slots
    inset_y = 0.10 + (total_slots - 1 - slot) * (inset_h + 0.02)
    ax_in = fig.add_axes([0.82, inset_y, 0.16, inset_h * 0.94])
    ax_in.set_facecolor(PANEL)
    for s in ax_in.spines.values():
        s.set_color(GRID)
    ax_in.tick_params(colors=FG, labelsize=6)

    # Draw the 3 5m candles
    for k, sc in enumerate(sub):
        color = UP if sc.close >= sc.open else DOWN
        ax_in.plot([k, k], [sc.low, sc.high], color=color, linewidth=1.2)
        ax_in.plot([k, k], [sc.open, sc.close], color=color, linewidth=5.0)

    # Fib levels in the inset
    ax_in.hlines(tp1, -0.4, 2.4, colors=ENTRY_C, linewidth=1.0, linestyles="--", alpha=0.9)
    ax_in.hlines(sl,  -0.4, 2.4, colors=SL_C,    linewidth=1.0, linestyles="--", alpha=0.9)
    ax_in.hlines(ambig["entry"], -0.4, 2.4, colors=FG, linewidth=0.6, linestyles=":", alpha=0.5)
    # Right-edge labels
    ax_in.annotate("TP1", xy=(2.5, tp1), color=ENTRY_C, fontsize=6, va="center")
    ax_in.annotate("SL",  xy=(2.5, sl),  color=SL_C,    fontsize=6, va="center")
    ax_in.annotate("entry", xy=(2.5, ambig["entry"]), color=FG, fontsize=6, va="center", alpha=0.6)

    # Mark which sub-bar hit which level first
    if tp1_idx is not None:
        ax_in.scatter([tp1_idx], [tp1], s=40, color=ENTRY_C, marker="X",
                      zorder=5, edgecolors="black", linewidths=0.5)
    if sl_idx is not None:
        ax_in.scatter([sl_idx], [sl], s=40, color=SL_C, marker="X",
                      zorder=5, edgecolors="black", linewidths=0.5)

    ax_in.set_xticks([0, 1, 2])
    ax_in.set_xticklabels([_dt(s.source_timestamp).strftime("%H:%M") for s in sub],
                          color=FG, fontsize=6)
    ax_in.set_xlim(-0.6, 2.6)
    ax_in.set_title(f"5m: {bar_ts}\n{verdict}", color=verdict_color, fontsize=7, pad=4)

    # Draw a yellow box on the main chart at the ambiguous 15m bar + connector line
    ambig_x = _dt(bar_ts)
    ambig_x_num = mdates.date2num(ambig_x)
    box_lo = min(ambig["lo"], sl) * 0.999
    box_hi = max(ambig["hi"], tp1) * 1.001
    rect = Rectangle((ambig_x_num - 0.005, box_lo),
                     width=0.010, height=box_hi - box_lo,
                     fill=False, edgecolor=BE_C, linewidth=1.2, zorder=10)
    ax_main.add_patch(rect)
    # Connector: convert datetime to float for fig.add_artist (no auto-convert
    # at the figure level, only within an axes with a date locator).
    conn = ConnectionPatch(
        xyA=(ambig_x_num, box_hi), coordsA=ax_main.transData,
        xyB=(0.0, 1.0), coordsB=ax_in.transAxes,
        color=BE_C, linewidth=0.8, alpha=0.7,
    )
    fig.add_artist(conn)


def draw_card(candles: list[Candle], idx: dict[str, int], atr: list[float],
              leg: dict, res: dict, card_id: str, outcome: str,
              cohort: str, out_path: Path,
              candles_5m: list[Candle] | None = None,
              idx_5m: dict[str, int] | None = None) -> int:
    """Render one review card. Returns the number of ambiguous bars drawn as
    magnifier insets (0 for unambiguous trades)."""
    pi = idx[leg["parent_ts"]]
    ti = idx[leg["term_ts"]]
    last_event_i = ti
    for ev in res.get("events", []):
        ev_i = idx.get(ev[1])
        if ev_i and ev_i > last_event_i:
            last_event_i = ev_i
    win_lo = max(0, pi - PAD_BEFORE_PARENT)
    win_hi = min(len(candles), last_event_i + PAD_AFTER_TERM)
    window = candles[win_lo:win_hi]
    if not window:
        return 0

    # Detect intrabar-ambiguity bars during phase 1.
    ambig_bars = []
    if candles_5m is not None and idx_5m is not None:
        ambig_bars = find_ambiguous_bars(candles, idx, leg, res)

    # Widen the figure to make room for magnifier insets along the right side.
    fig_w = 18 if ambig_bars else 14
    fig, ax = plt.subplots(figsize=(fig_w, 7))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)
    # Reserve right margin for insets when present.
    if ambig_bars:
        fig.subplots_adjust(left=0.05, right=0.78, top=0.92, bottom=0.10)

    # Candles
    xs = [_dt(c.source_timestamp) for c in window]
    for x, c in zip(xs, window):
        color = UP if c.close >= c.open else DOWN
        ax.plot([x, x], [c.low, c.high], color=color, linewidth=0.7, alpha=0.85)
        ax.plot([x, x], [c.open, c.close], color=color, linewidth=2.2, alpha=0.95)

    # Fib levels (horizontal lines spanning parent -> last event)
    parent = leg["parent_price"]
    term = leg["term_price"]
    fib_x_lo = _dt(candles[pi].source_timestamp)
    fib_x_hi = _dt(candles[last_event_i].source_timestamp)
    for coeff, color, label in LEVELS_TO_DRAW:
        price = fib_price(parent, term, coeff)
        ax.hlines(price, fib_x_lo, fib_x_hi, colors=color, linewidth=1.1,
                  linestyles="-" if coeff in (0.941, 1.0, 1.05) else "--", alpha=0.85)
        ax.annotate(label, xy=(fib_x_hi, price), xycoords="data",
                    color=color, fontsize=8, va="center",
                    xytext=(6, 0), textcoords="offset points")

    # Parent / terminal markers
    ax.scatter([_dt(leg["parent_ts"])], [parent], s=80, color=PARENT_C,
               zorder=5, edgecolors="black", linewidths=0.8)
    ax.scatter([_dt(leg["term_ts"])], [term], s=80, color=TERM_C,
               zorder=5, edgecolors="black", linewidths=0.8)
    ax.annotate("parent", xy=(_dt(leg["parent_ts"]), parent),
                color=PARENT_C, fontsize=8, xytext=(4, 6),
                textcoords="offset points")
    ax.annotate("term", xy=(_dt(leg["term_ts"]), term),
                color=TERM_C, fontsize=8, xytext=(4, 6),
                textcoords="offset points")

    # Execution events
    ev_colors = {
        "entry": ENTRY_C, "be_drag": BE_C,
        "tp1": TP_C, "tp2": TP_C, "tp3": TP_C, "sl": SL_C,
    }
    for ev in res.get("events", []):
        label, ts, price = ev[0], ev[1], ev[2]
        if ts not in idx:
            continue
        ev_color = ev_colors.get(label.lower().split()[0], "#94a3b8")
        ax.scatter([_dt(ts)], [price], s=60, color=ev_color, marker="X",
                   zorder=6, edgecolors="black", linewidths=0.6)
        ax.annotate(label, xy=(_dt(ts), price), color=ev_color, fontsize=8,
                    xytext=(4, -10), textcoords="offset points")

    # Axes / styling
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    for spine in ("bottom", "left"):
        ax.spines[spine].set_color(GRID)
    ax.tick_params(colors=FG, labelsize=8)
    ax.grid(True, color=GRID, linewidth=0.5, alpha=0.6)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))

    # Header
    # Convention: "up" leg = parent(low) -> term(high); we wait for a deep pullback
    # toward parent and go LONG for the continuation back to term. "down" leg is
    # the mirror -- SHORT the rebound after a down-swing's deep retrace up.
    direction = "LONG" if leg["direction"] == "up" else "SHORT"
    title = (f"[{card_id}] ADA-15m  {direction}  {leg['parent_ts']} -> {leg['term_ts']}  |  "
             f"cohort {cohort} ATR  |  outcome {outcome}  |  R = {res['r']:+.2f}")
    ax.set_title(title, color=FG, fontsize=11, pad=12)

    # Legend in the corner
    handles = [
        plt.Line2D([], [], marker="o", color=PARENT_C, linewidth=0, markersize=8,
                   label="parent (1.0)"),
        plt.Line2D([], [], marker="o", color=TERM_C, linewidth=0, markersize=8,
                   label="terminal (0.0)"),
        plt.Line2D([], [], marker="X", color=ENTRY_C, linewidth=0, markersize=8,
                   label="entry"),
        plt.Line2D([], [], marker="X", color=BE_C, linewidth=0, markersize=8,
                   label="BE drag"),
        plt.Line2D([], [], marker="X", color=TP_C, linewidth=0, markersize=8,
                   label="TP1/2/3"),
        plt.Line2D([], [], marker="X", color=SL_C, linewidth=0, markersize=8,
                   label="SL"),
    ]
    leg_box = ax.legend(handles=handles, loc="upper left", frameon=True,
                        facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=8)
    for txt in leg_box.get_texts():
        txt.set_color(FG)

    # Magnifier insets for any ambiguous bars
    if ambig_bars and candles_5m is not None and idx_5m is not None:
        total = len(ambig_bars)
        for slot, ambig in enumerate(ambig_bars):
            draw_magnifier(fig, ax, candles_5m, idx_5m, ambig, slot, total)
        # Add a small caption explaining the magnifier layout
        ax.text(0.99, -0.10,
                f"Yellow box(es) flag 15m bars where high>=TP1 AND low<=SL "
                f"-- intrabar order matters. Right-side insets show the 3x 5m "
                f"sub-bars so the order is observable.",
                transform=ax.transAxes, color=FG, fontsize=7,
                ha="right", va="top", alpha=0.7)

    # When ambig insets are present we already used subplots_adjust;
    # otherwise let tight_layout do its thing.
    if not ambig_bars:
        fig.tight_layout()
    fig.savefig(out_path, dpi=110, facecolor=BG)
    plt.close(fig)
    return len(ambig_bars)


def main() -> None:
    if not CSV_PATH.exists():
        print(f"missing {CSV_PATH}; acquire it first"); sys.exit(2)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("*.png"):
        stale.unlink()
    for stale in OUT_DIR.glob("*.csv"):
        stale.unlink()

    print(f"loading ADA 15m ({CSV_PATH.name}) ...", flush=True)
    candles = load_csv(CSV_PATH)
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    atr = calculate_atr14(candles)
    piv = detect_local_pivots(candles)
    legs = [l for l in _clean_legs(candles, atr, piv, min_bars=6, mult=2.0)
            if l["term_ts"] in idx]
    print(f"  detected {len(legs)} setups")

    # Load 5m sub-bars for magnifier insets (optional -- script still works without it)
    candles_5m = None; idx_5m = None
    if CSV_PATH_5M.exists():
        print(f"loading ADA 5m ({CSV_PATH_5M.name}) for magnifier insets ...", flush=True)
        candles_5m = load_csv(CSV_PATH_5M)
        idx_5m = {c.source_timestamp: i for i, c in enumerate(candles_5m)}
        print(f"  loaded {len(candles_5m)} 5m bars")
    else:
        print(f"[note] {CSV_PATH_5M.name} not found; rendering without 5m magnifiers")

    # Score each on the 0.941 regime; record cohort + outcome
    enriched = []
    for n, leg in enumerate(legs, start=1):
        atr_at_term = atr[idx[leg["term_ts"]]] or 1.0
        depth_atr = abs(leg["term_price"] - leg["parent_price"]) / atr_at_term
        cohort = cohort_label(depth_atr)
        if cohort is None:
            continue
        res = run_regime(candles, idx, leg, REG_941)
        outcome = KIND.get(res["status"], "open")
        if outcome == "shrug":
            continue  # never triggered; not interesting for visual review
        enriched.append({
            "n": n, "leg": leg, "res": res, "cohort": cohort,
            "outcome": outcome, "depth_atr": depth_atr,
        })

    # Stratified sample
    rng = random.Random(SAMPLE_SEED)
    buckets: dict[tuple[str, str], list] = defaultdict(list)
    for e in enriched:
        buckets[(e["cohort"], e["outcome"])].append(e)
    sample = []
    for (cohort, outcome), bucket in sorted(buckets.items()):
        rng.shuffle(bucket)
        sample.extend(bucket[:TARGET_PER_BUCKET])
    sample.sort(key=lambda e: e["leg"]["term_ts"])

    print(f"  sampling {len(sample)} setups across cohorts x outcomes")
    print(f"  per-bucket counts (cohort, outcome): "
          f"{ {k: len(v) for k, v in buckets.items()} }")

    # Write index CSV
    index_path = OUT_DIR / "00_index.csv"
    total_ambig = 0
    with index_path.open("w", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["card_id", "parent_ts", "term_ts", "direction",
                    "parent_price", "term_price", "depth_atr", "cohort",
                    "outcome", "r_0941", "ambig_bars", "note"])
        for k, e in enumerate(sample, start=1):
            card_id = f"R{k:02d}"
            leg = e["leg"]; res = e["res"]
            out_path = OUT_DIR / f"{card_id}_{e['outcome']}_{e['cohort']}.png"
            n_ambig = draw_card(candles, idx, atr, leg, res, card_id, e["outcome"],
                                e["cohort"], out_path,
                                candles_5m=candles_5m, idx_5m=idx_5m)
            total_ambig += n_ambig
            w.writerow([card_id, leg["parent_ts"], leg["term_ts"], leg["direction"],
                        f"{leg['parent_price']:.4f}", f"{leg['term_price']:.4f}",
                        f"{e['depth_atr']:.2f}", e["cohort"], e["outcome"],
                        f"{res['r']:+.3f}", n_ambig, ""])
            if k % 10 == 0:
                print(f"  rendered {k}/{len(sample)} (ambig insets so far: {total_ambig})...", flush=True)

    print(f"\nWROTE {len(sample)} cards + index to {OUT_DIR}")
    print(f"  open {OUT_DIR}  and flip through PNGs in order.")
    print(f"  add your notes in the 'note' column of 00_index.csv.")


if __name__ == "__main__":
    main()
