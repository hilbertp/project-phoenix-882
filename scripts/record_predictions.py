#!/usr/bin/env python
"""Freeze the engine's outcome predictions BEFORE a human review session.

Writes one JSONL record per triggered setup to
data/discovery_bet_1/engine_predictions.jsonl (tracked in git), tagged with a
run id. This pre-registers what the engine claims so the later comparison
against human verdicts (scripts/compare_predictions.py) is honest -- the
engine cannot be quietly re-run after the fact.

Usage (mirror the review session's parameters exactly):
  PYTHONPATH=. .venv/bin/python scripts/record_predictions.py --month 2026-05 --min-bars 6 --mult 4.0
  PYTHONPATH=. .venv/bin/python scripts/record_predictions.py --last-days 92 --exit-plan rest50
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.swing_detector import clean_legs
from apps.worker.discovery_bet_1.types import Candle
from scripts.execute_fib_strategy import REGIMES, build_subbar_index, execute

OUT = REPO_ROOT / "data/discovery_bet_1/engine_predictions.jsonl"
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
    win.add_argument("--month")
    win.add_argument("--last-days", type=int)
    ap.add_argument("--min-bars", type=int, default=6)
    ap.add_argument("--mult", type=float, default=2.0)
    ap.add_argument("--entry", choices=["941", "882", "786"], default="941")
    ap.add_argument("--exit-plan", choices=["runner", "rest50"], default="runner")
    args = ap.parse_args()

    c1h = load_csv(REPO_ROOT / "data/discovery_bet_1/binance_btcusdt_1h_full_history.csv")
    idx = {c.source_timestamp: i for i, c in enumerate(c1h)}
    sub5 = build_subbar_index(load_csv(
        REPO_ROOT / "data/discovery_bet_1/binance_btcusdt_5m_full_history.csv"))
    atr = calculate_atr14(c1h)
    piv = detect_local_pivots(c1h)

    if args.month:
        y, m = map(int, args.month.split("-"))
        lo, hi = f"{y:04d}-{m:02d}-01T00:00:00", f"{y:04d}-{m:02d}-31T23:59:59"
        window = args.month
    else:
        last = c1h[-1].source_timestamp
        lo = (datetime.fromisoformat(last) - timedelta(days=args.last_days)).isoformat()
        hi = last
        window = f"last{args.last_days}d"

    regime = next(r for r in REGIMES if r["slug"] == f"x{args.entry}")
    exec_kwargs = dict(regime["params"])
    if args.exit_plan == "rest50":
        exec_kwargs.update({"p1": 0.25, "p2": 0.75, "p3": 0.0})

    now = datetime.now(timezone.utc).isoformat()
    run_id = (f"{window}_{args.min_bars}c{args.mult:g}x_e{args.entry}"
              f"_{args.exit_plan}")
    legs = [l for l in clean_legs(c1h, atr, piv,
                                  min_bars=args.min_bars, mult=args.mult)
            if l["term_ts"] in idx and lo <= l["parent_ts"] <= hi]
    n = 0
    with OUT.open("a", encoding="utf-8") as fh:
        for leg in legs:
            res = execute(c1h, idx, leg, subbars=sub5, **exec_kwargs)
            if res["status"] in ("no_entry", "no_trigger", "degenerate"):
                continue
            n += 1
            fh.write(json.dumps({
                "run_id": run_id,
                "recorded_at": now,
                "setup_key": f"{leg['parent_ts']}|{leg['term_ts']}",
                "parent_ts": leg["parent_ts"], "term_ts": leg["term_ts"],
                "direction": leg["direction"],
                "parent_price": leg["parent_price"],
                "term_price": leg["term_price"],
                "engine_class": CLS.get(res["status"], res["status"]),
                "engine_status": res["status"],
                "engine_r": round(res["r"], 4),
                "events": [(e[0], e[1], round(e[2], 2)) for e in res["events"]],
            }) + "\n")
    print(f"recorded {n} predictions under run_id={run_id} -> {OUT}")


if __name__ == "__main__":
    main()
