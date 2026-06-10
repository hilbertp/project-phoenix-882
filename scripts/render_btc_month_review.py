#!/usr/bin/env python
"""Render per-setup PNG review cards for the BTC 1H monthly backtest.

One card per triggered setup. Each card shows:

  * TOP: the 1H context chart -- candles from before the parent pivot to past
    the trade's last event, all fib levels, the swing leg, and every executor
    event as a numbered marker: entry fill, TP1 partial (with the SL DRAGGED
    to entry drawn as a step-line), TP2, TP3, and stop-outs.
  * BOTTOM: one 5m zoom panel per DECISIVE HOUR (every 1H candle that contains
    an executor event). The zoom shows the timely price movement inside the
    ambiguous candle so the eye can follow the actual path -- the thing the
    user cannot do on TradingView (their plan can't load old intraday data).

Outcomes/events come from scripts.execute_fib_strategy.execute() with 5m
sub-bars -- the SAME engine the human-validated regression test locks down,
so what you see is exactly what the backtest scored.

Usage:
  PYTHONPATH=. .venv/bin/python scripts/render_btc_month_review.py --month 2026-05

Output:
  artifacts/discovery_bet_1/manual_review_btc_1h_month/cards_<month>/
    card_01_TP2.png ... card_27_LOSS.png   (DISPUTE_ in the name when the
                                            engine disagrees with the latest
                                            human label)
    index.html                              (scroll through all cards)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.swing_detector import clean_legs
from apps.worker.discovery_bet_1.types import Candle
from scripts.execute_fib_strategy import build_subbar_index, execute

# ---- appearance (matches manual_review_ada_15m.py conventions) ----
BG = "#0e1117"
PANEL = "#161b22"
FG = "#d0d4dc"
GRID = "#262d38"
UP = "#26a69a"
DOWN = "#ef5350"
# User-specified palette (2026-06-10): solid lines, white parent, green entry,
# red SL, TP1->TP3 in distinguishable shades of blue.
ENTRY_C = "#22c55e"
SL_C = "#ef4444"
PARENT_C = "#e5e7eb"
TP1_C = "#93c5fd"
TP2_C = "#60a5fa"
TP3_C = "#2563eb"
BE_C = "#f59e0b"          # break-even stop-out marker only
LEG_C = "#8b949e"
ZOOM_BOX_C = "#facc15"

LEVELS = [
    (0.0, TP3_C, "TP3 0.0"),
    (0.5, TP2_C, "TP2 0.5"),
    (0.882, TP1_C, "TP1/BE 0.882"),
    (0.941, ENTRY_C, "ENTRY 0.941"),
    (1.0, PARENT_C, "parent 1.0"),
    (1.05, SL_C, "SL 1.05"),
]

CSV_1H = REPO_ROOT / "data/discovery_bet_1/binance_btcusdt_1h_full_history.csv"
CSV_5M = REPO_ROOT / "data/discovery_bet_1/binance_btcusdt_5m_full_history.csv"
LABELS = REPO_ROOT / "data/discovery_bet_1/human_labels.jsonl"

STATUS_CLASS = {"tp1_then_scratch": "TP1", "tp2_then_scratch": "TP2",
                "tp3_full": "TP3", "wipeout": "LOSS", "open": "OPEN"}
SCORED_CLASS = {"scratch": "TP1", "partial": "TP2", "win": "TP3",
                "loss": "LOSS", "miss": "MISSED"}
CLASS_COLOR = {"TP1": TP1_C, "TP2": TP2_C, "TP3": TP3_C, "LOSS": SL_C, "OPEN": LEG_C}


def load_csv(path: Path) -> list[Candle]:
    out: list[Candle] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Candle(row["source_timestamp"], float(row["open"]),
                              float(row["high"]), float(row["low"]),
                              float(row["close"]), float(row["volume"])))
    return out


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def latest_human_labels() -> dict[str, str]:
    """parent_ts -> human outcome class (latest verdict wins; accepts use the
    scored class they endorsed)."""
    if not LABELS.exists():
        return {}
    latest: dict[str, dict] = {}
    for line in LABELS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        dp = rec.get("detector_params") or {}
        if dp.get("asset") == "BTC" and dp.get("interval") == "1h":
            latest[rec["parent_ts"]] = rec
    out: dict[str, str] = {}
    for pts, rec in latest.items():
        dp = rec.get("detector_params") or {}
        if rec.get("verdict") == "accept":
            cls = SCORED_CLASS.get(dp.get("scored_outcome"))
        elif dp.get("wrong_kind") == "outcome":
            cls = dp.get("expected_outcome")
        else:
            cls = None  # setup-wrong labels grade anchors, not outcomes
        if cls:
            out[pts] = cls
    return out


def _classify_event(label: str) -> tuple[str, str, str]:
    """Event label -> (short text, color, marker)."""
    if label.startswith("Entry"):
        return "FILL", ENTRY_C, "o"
    if label.startswith("TP1"):
        return "TP1 +25% · SL→entry", TP1_C, "^"
    if label.startswith("TP2"):
        return "TP2 +60%", TP2_C, "^"
    if label.startswith("TP3"):
        return "TP3 +15% (full)", TP3_C, "*"
    if "Initial SL" in label:
        return "STOP -1R", SL_C, "X"
    if "Break-even" in label:
        return "BE STOP 0R", BE_C, "X"
    return label[:18], FG, "."


def draw_candles_dates(ax, candles: list[Candle], width_days: float) -> None:
    for c in candles:
        x = mdates.date2num(_dt(c.source_timestamp))
        color = UP if c.close >= c.open else DOWN
        ax.plot([x, x], [c.low, c.high], color=color, linewidth=0.9, zorder=2)
        body_lo, body_hi = min(c.open, c.close), max(c.open, c.close)
        ax.add_patch(Rectangle((x - width_days / 2, body_lo), width_days,
                               max(body_hi - body_lo, 1e-9),
                               facecolor=color, edgecolor=color, zorder=3))


def draw_card(setup_no: int, total: int, leg: dict, res: dict,
              candles_1h: list[Candle], idx_1h: dict[str, int],
              candles_5m: list[Candle], idx_5m: dict[str, int],
              human: str | None, out_path: Path) -> None:
    parent, term = leg["parent_price"], leg["term_price"]
    lvl = lambda c: term + (parent - term) * c
    events = res["events"]
    engine_cls = STATUS_CLASS.get(res["status"], res["status"])

    # ---- figure & layout ----
    event_hours: list[str] = []
    for _, ts, _ in events:
        hk = ts[:13]
        if hk not in event_hours:
            event_hours.append(hk)
    n_zoom = max(1, min(len(event_hours), 4))
    zoom_hours = event_hours if len(event_hours) <= 4 else \
        [event_hours[0]] + event_hours[-3:]

    fig = plt.figure(figsize=(17, 10))
    fig.patch.set_facecolor(BG)
    gs = fig.add_gridspec(2, n_zoom, height_ratios=[2.1, 1.0],
                          hspace=0.18, wspace=0.14,
                          left=0.045, right=0.90, top=0.90, bottom=0.06)
    ax = fig.add_subplot(gs[0, :])
    ax.set_facecolor(BG)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=FG, labelsize=8)
    ax.grid(color=GRID, linewidth=0.4, alpha=0.5)

    # ---- 1H window: parent-16 .. last_event+14 bars ----
    pi = idx_1h[leg["parent_ts"]]
    last_ev_ts = events[-1][1] if events else leg["term_ts"]
    last_i = idx_1h.get(last_ev_ts[:13] + ":00:00", idx_1h[leg["term_ts"]])
    lo_i = max(0, pi - 16)
    hi_i = min(len(candles_1h) - 1, max(last_i, idx_1h[leg["term_ts"]]) + 14)
    window = candles_1h[lo_i:hi_i + 1]
    draw_candles_dates(ax, window, width_days=0.7 / 24)

    x_left = mdates.date2num(_dt(window[0].source_timestamp))
    x_right = mdates.date2num(_dt(window[-1].source_timestamp))

    # ---- fib levels (solid, thin -- user: 'no dashed lanes') ----
    for coeff, color, name in LEVELS:
        p = lvl(coeff)
        ax.hlines(p, x_left, x_right, colors=color, linewidth=0.9,
                  alpha=0.65, zorder=1)
        ax.annotate(f"{name}  {p:,.0f}", xy=(x_right, p), xytext=(4, 0),
                    textcoords="offset points", color=color, fontsize=8,
                    va="center", annotation_clip=False)

    # ---- the swing leg ----
    ax.plot([mdates.date2num(_dt(leg["parent_ts"])), mdates.date2num(_dt(leg["term_ts"]))],
            [parent, term], color=LEG_C, linewidth=1.4, linestyle=":",
            alpha=0.8, zorder=4)

    # ---- the ACTIVE-STOP step line (the "dragging") ----
    if events:
        fill_ts = events[0][1]
        stop_steps: list[tuple[float, float]] = [(mdates.date2num(_dt(fill_ts)), lvl(1.05))]
        exit_x = mdates.date2num(_dt(events[-1][1]))
        for label, ts, _ in events:
            if label.startswith("TP1"):
                x = mdates.date2num(_dt(ts))
                stop_steps.append((x, lvl(1.05)))    # up to TP1 moment
                stop_steps.append((x, lvl(0.941)))   # dragged to entry
        stop_steps.append((exit_x, stop_steps[-1][1]))
        xs = [p[0] for p in stop_steps]
        ys = [p[1] for p in stop_steps]
        ax.plot(xs, ys, color=SL_C, linewidth=2.2, alpha=0.95,
                solid_capstyle="butt", zorder=6, label="ACTIVE STOP (drag)")

    # ---- event markers, numbered chronologically ----
    legend_lines = []
    for n, (label, ts, price) in enumerate(events, start=1):
        short, color, marker = _classify_event(label)
        x = mdates.date2num(_dt(ts))
        ax.scatter([x], [price], s=130, color=color, marker=marker,
                   zorder=8, edgecolors="black", linewidths=0.6)
        ax.annotate(str(n), xy=(x, price), xytext=(0, 11),
                    textcoords="offset points", color=color, fontsize=10,
                    fontweight="bold", ha="center", zorder=9)
        loc = _dt(ts)
        legend_lines.append(
            f"{n}. {short}  ·  {ts[5:16]} UTC ({(loc.hour + 2) % 24:02d}:{loc.minute:02d} local)  ·  {price:,.1f}")

    # ---- yellow boxes marking the zoomed hours ----
    for hk in zoom_hours:
        hk_ts = hk + ":00:00"
        if hk_ts not in idx_1h:
            continue
        c = candles_1h[idx_1h[hk_ts]]
        x = mdates.date2num(_dt(c.source_timestamp))
        pad = (c.high - c.low) * 0.15
        ax.add_patch(Rectangle((x - 0.55 / 24, c.low - pad), 1.1 / 24,
                               (c.high - c.low) + 2 * pad, fill=False,
                               edgecolor=ZOOM_BOX_C, linewidth=1.4, zorder=10))

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
    ax.set_xlim(x_left - 0.05, x_right + 0.05)

    # ---- header ----
    match = (human == engine_cls) if human else None
    badge = ("MATCH" if match else f"DISPUTE (you: {human})") if human else "unreviewed"
    badge_c = UP if match else (SL_C if human else FG)
    fig.suptitle(
        f"setup {setup_no}/{total}   ·   BTC 1H {leg['direction'].upper()}   ·   "
        f"{leg['parent_ts'][:16]} → {leg['term_ts'][:16]}   ·   "
        f"ENGINE: {engine_cls}  ({res['r']:+.2f}R)   ·   {badge}",
        color=CLASS_COLOR.get(engine_cls, FG), fontsize=13, fontweight="bold", y=0.97)
    fig.text(0.045, 0.915, "   |   ".join(legend_lines), color=FG, fontsize=8.5)

    # ---- 5m zoom panels (one per decisive hour) ----
    for slot, hk in enumerate(zoom_hours[:n_zoom]):
        axz = fig.add_subplot(gs[1, slot])
        axz.set_facecolor(PANEL)
        for s in axz.spines.values():
            s.set_color(GRID)
        axz.tick_params(colors=FG, labelsize=7)

        hour_start = _dt(hk + ":00:00")
        w_lo, w_hi = hour_start - timedelta(minutes=30), hour_start + timedelta(minutes=90)
        sub = [c for c in candles_5m
               if w_lo <= _dt(c.source_timestamp) < w_hi]
        if not sub:
            axz.set_title(f"5m data missing for {hk}", color=SL_C, fontsize=8)
            continue
        for k, c in enumerate(sub):
            color = UP if c.close >= c.open else DOWN
            axz.plot([k, k], [c.low, c.high], color=color, linewidth=1.0, zorder=2)
            axz.plot([k, k], [c.open, c.close], color=color, linewidth=4.0, zorder=3)
        # highlight the decisive hour band
        in_hour = [k for k, c in enumerate(sub)
                   if c.source_timestamp[:13] == hk]
        if in_hour:
            axz.axvspan(min(in_hour) - 0.5, max(in_hour) + 0.5,
                        color=ZOOM_BOX_C, alpha=0.07, zorder=1)
        # levels within the visible price range
        v_lo = min(c.low for c in sub)
        v_hi = max(c.high for c in sub)
        v_pad = (v_hi - v_lo) * 0.08
        for coeff, color, name in LEVELS:
            p = lvl(coeff)
            if v_lo - v_pad <= p <= v_hi + v_pad:
                axz.hlines(p, -0.5, len(sub) - 0.5, colors=color,
                           linewidth=0.8, alpha=0.7)
                axz.annotate(name.split()[0], xy=(len(sub) - 0.4, p),
                             color=color, fontsize=6.5, va="center",
                             annotation_clip=False)
        # event markers inside this window
        ts_to_k = {c.source_timestamp: k for k, c in enumerate(sub)}
        for n, (label, ts, price) in enumerate(events, start=1):
            if ts in ts_to_k:
                short, color, marker = _classify_event(label)
                k = ts_to_k[ts]
                axz.scatter([k], [price], s=90, color=color, marker=marker,
                            zorder=8, edgecolors="black", linewidths=0.6)
                axz.annotate(str(n), xy=(k, price), xytext=(0, 9),
                             textcoords="offset points", color=color,
                             fontsize=9, fontweight="bold", ha="center")
        ticks = [k for k, c in enumerate(sub) if c.source_timestamp[14:16] in ("00", "30")]
        axz.set_xticks(ticks)
        axz.set_xticklabels([sub[k].source_timestamp[11:16] for k in ticks], fontsize=6.5)
        axz.set_xlim(-1, len(sub))
        loc_h = (int(hk[11:13]) + 2) % 24
        axz.set_title(f"5m zoom · {hk[:10]} {hk[11:13]}:00 UTC ({loc_h:02d}:00 local)",
                      color=ZOOM_BOX_C, fontsize=8.5, pad=4)

    fig.savefig(out_path, dpi=110, facecolor=BG)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    win = ap.add_mutually_exclusive_group(required=True)
    win.add_argument("--month", help="calendar month YYYY-MM, e.g. 2026-05")
    win.add_argument("--last-days", type=int,
                     help="trailing window in days (e.g. 92 for ~3 months)")
    ap.add_argument("--min-bars", type=int, default=6,
                    help="detector min bars per leg (default 6)")
    ap.add_argument("--mult", type=float, default=2.0,
                    help="detector min ATR multiple (default 2.0)")
    args = ap.parse_args()

    print("==> loading 1H + 5m candles...", flush=True)
    c1h = load_csv(CSV_1H)
    idx = {c.source_timestamp: i for i, c in enumerate(c1h)}
    c5 = load_csv(CSV_5M)
    idx5 = {c.source_timestamp: i for i, c in enumerate(c5)}
    sub5 = build_subbar_index(c5)

    if args.month:
        y, m = map(int, args.month.split("-"))
        cutoff_lo = f"{y:04d}-{m:02d}-01T00:00:00"
        cutoff_hi = f"{y:04d}-{m:02d}-31T23:59:59"
        window_tag = args.month
    else:
        last_dt = _dt(c1h[-1].source_timestamp)
        cutoff_lo = (last_dt - timedelta(days=args.last_days)).isoformat()
        cutoff_hi = c1h[-1].source_timestamp
        window_tag = f"last{args.last_days}d"
    params_tag = f"{args.min_bars}c{args.mult:g}x"

    print(f"==> detecting setups ({args.min_bars}c / {args.mult:g}x ATR) in "
          f"[{cutoff_lo[:10]} .. {cutoff_hi[:10]}]...", flush=True)
    atr = calculate_atr14(c1h)
    piv = detect_local_pivots(c1h)
    legs = [l for l in clean_legs(c1h, atr, piv,
                                  min_bars=args.min_bars, mult=args.mult)
            if l["term_ts"] in idx and cutoff_lo <= l["parent_ts"] <= cutoff_hi]
    print(f"==> {len(legs)} clean legs", flush=True)

    triggered = []
    for leg in legs:
        res = execute(c1h, idx, leg, subbars=sub5)
        if res["status"] in ("no_entry", "no_trigger", "degenerate"):
            continue
        triggered.append((leg, res))
    print(f"==> {len(triggered)} triggered setups (0.941 tagged)", flush=True)
    if not triggered:
        raise SystemExit("nothing to render.")

    human = latest_human_labels()
    out_dir = (REPO_ROOT / "artifacts/discovery_bet_1/manual_review_btc_1h_month"
               / f"cards_{window_tag}_{params_tag}")
    out_dir.mkdir(parents=True, exist_ok=True)

    cards = []
    for n, (leg, res) in enumerate(triggered, start=1):
        cls = STATUS_CLASS.get(res["status"], res["status"])
        hum = human.get(leg["parent_ts"])
        tag = "" if (hum is None or hum == cls) else f"_DISPUTE_vs_{hum}"
        name = f"card_{n:02d}_{cls}{tag}.png"
        draw_card(n, len(triggered), leg, res, c1h, idx, c5, idx5, hum,
                  out_dir / name)
        cards.append(name)
        print(f"  rendered {name}", flush=True)

    index = out_dir / "index.html"
    rows = "\n".join(
        f'<div class="card"><h3>{name}</h3><img src="{name}" loading="lazy"></div>'
        for name in cards)
    index.write_text(f"""<!doctype html><html><head><meta charset="utf-8">
<title>BTC 1H review cards {window_tag} {params_tag}</title>
<style>body{{background:{BG};color:{FG};font:14px -apple-system,sans-serif;margin:0;padding:16px}}
.card{{margin-bottom:28px}} img{{width:100%;max-width:1700px;border:1px solid {GRID};border-radius:6px}}
h3{{margin:6px 0;color:{ZOOM_BOX_C}}}</style></head><body>
<h1>BTC 1H review cards — {window_tag} · {params_tag} ({len(cards)} setups)</h1>
{rows}
</body></html>""", encoding="utf-8")
    print(f"==> wrote {len(cards)} cards + index: {index}", flush=True)


if __name__ == "__main__":
    main()
