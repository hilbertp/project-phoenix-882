#!/usr/bin/env python
"""Detector-grid backtest for BTC 1H fib setups -- the standard results table.

Runs every (min-bars x ATR-mult) detector combination over a window, scores
each triggered setup with the human-validated executor (5m sub-bar
resolution), and prints the table used throughout the DB1 research:

  config  trig  TP3  TP2  TP1  LOSS  sumR  avgR  win%

Usage:
  PYTHONPATH=. .venv/bin/python scripts/backtest_grid.py --month 2026-05
  PYTHONPATH=. .venv/bin/python scripts/backtest_grid.py --last-days 92
  PYTHONPATH=. .venv/bin/python scripts/backtest_grid.py --month 2026-05 --exit-plan rest50
  PYTHONPATH=. .venv/bin/python scripts/backtest_grid.py --last-days 92 --veto

Options:
  --exit-plan runner  TP1 25% at 0.882 (SL->entry), TP2 60% at 0.5,
                      TP3 15% runner to 0.0            [default]
  --exit-plan rest50  TP1 25% at 0.882 (SL->entry), remaining 75% ALL out
                      at 0.5, no runner
  --veto              adds a second line per config applying the Ichimoku
                      26-bar two-sides regime veto (scripts/ichimoku_regime.py)
                      at the FILL bar -- trade only when the market is settled.

Data prerequisites (scripts/bootstrap.sh acquires both):
  data/discovery_bet_1/binance_btcusdt_1h_full_history.csv
  data/discovery_bet_1/binance_btcusdt_5m_full_history.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.swing_detector import clean_legs
from apps.worker.discovery_bet_1.types import Candle
from scripts.execute_fib_strategy import build_subbar_index, execute
from scripts.ichimoku_regime import SETTLED, IchimokuRegime

GRID = [(6, 2.0), (6, 3.0), (6, 4.0),
        (12, 2.0), (12, 3.0), (12, 4.0),
        (24, 2.0), (24, 3.0), (24, 4.0),
        (36, 2.0), (36, 3.0), (36, 4.0),
        (48, 2.0), (48, 3.0), (48, 4.0)]
CLS = {"tp1_then_scratch": "TP1", "tp2_then_scratch": "TP2", "tp3_full": "TP3",
       "wipeout": "LOSS", "open": "OPEN"}


def load_csv(path: Path) -> list[Candle]:
    out: list[Candle] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Candle(row["source_timestamp"], float(row["open"]),
                              float(row["high"]), float(row["low"]),
                              float(row["close"]), float(row["volume"])))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    win = ap.add_mutually_exclusive_group(required=True)
    win.add_argument("--month", help="YYYY-MM calendar month")
    win.add_argument("--last-days", type=int, help="trailing window in days")
    ap.add_argument("--exit-plan", choices=["runner", "rest50"], default="runner")
    ap.add_argument("--veto", action="store_true",
                    help="also show each config with the Ichimoku regime veto")
    args = ap.parse_args()

    c1h = load_csv(REPO_ROOT / "data/discovery_bet_1/binance_btcusdt_1h_full_history.csv")
    idx = {c.source_timestamp: i for i, c in enumerate(c1h)}
    sub5 = build_subbar_index(load_csv(
        REPO_ROOT / "data/discovery_bet_1/binance_btcusdt_5m_full_history.csv"))
    atr = calculate_atr14(c1h)
    piv = detect_local_pivots(c1h)
    ich = IchimokuRegime(c1h) if args.veto else None

    if args.month:
        y, m = map(int, args.month.split("-"))
        lo, hi = f"{y:04d}-{m:02d}-01T00:00:00", f"{y:04d}-{m:02d}-31T23:59:59"
        label = args.month
    else:
        last = c1h[-1].source_timestamp
        lo = (datetime.fromisoformat(last) - timedelta(days=args.last_days)).isoformat()
        hi = last
        label = f"last {args.last_days}d"

    exec_kwargs = {}
    if args.exit_plan == "rest50":
        exec_kwargs = {"p1": 0.25, "p2": 0.75, "p3": 0.0}

    print(f"BTC 1H · 0.941 entry · exit={args.exit_plan} · {label} "
          f"({lo[:10]} .. {hi[:10]}) · data through {c1h[-1].source_timestamp}")
    print(f"{'config':<11}{'trig':>5}{'TP3':>5}{'TP2':>5}{'TP1':>5}{'LOSS':>6}"
          f"{'sumR':>9}{'avgR':>9}{'win%':>7}")
    print("-" * 62)

    def line(tag, rows):
        tally, total_r = Counter(), 0.0
        for cls, r in rows:
            tally[cls] += 1
            total_r += r
        n = sum(tally.values())
        if n == 0:
            print(f"{tag:<11}{0:>5}    {'-':>4} {'-':>4} {'-':>4}  {'-':>4}"
                  f"{'-':>9}{'-':>9}{'-':>7}")
            return
        wr = (tally["TP1"] + tally["TP2"] + tally["TP3"]) / n * 100
        print(f"{tag:<11}{n:>5}{tally['TP3']:>5}{tally['TP2']:>5}{tally['TP1']:>5}"
              f"{tally['LOSS']:>6}{total_r:>+9.2f}{total_r/n:>+9.3f}{wr:>6.0f}%")

    for mb, mult in GRID:
        legs = [l for l in clean_legs(c1h, atr, piv, min_bars=mb, mult=mult)
                if l["term_ts"] in idx and lo <= l["parent_ts"] <= hi]
        rows, vrows = [], []
        for leg in legs:
            res = execute(c1h, idx, leg, subbars=sub5, **exec_kwargs)
            if res["status"] in ("no_entry", "no_trigger", "degenerate"):
                continue
            cls = CLS.get(res["status"], res["status"])
            rows.append((cls, res["r"]))
            if ich is not None and res["events"]:
                fi = idx.get(res["events"][0][1][:13] + ":00:00")
                if fi is not None and ich.classify(fi) in SETTLED:
                    vrows.append((cls, res["r"]))
        line(f"{mb}c/{mult:g}x", rows)
        if ich is not None:
            line(f"  +veto", vrows)


if __name__ == "__main__":
    main()
