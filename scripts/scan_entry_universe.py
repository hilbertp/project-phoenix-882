#!/usr/bin/env python
"""From-scratch fib-entry universe scanner (running-extreme candidates).

WHY THIS EXISTS (PO ruling 2026-07-03): the ATR-zigzag only records a leg
terminal when a counter-move reaches mult*ATR. A retracement that tags a
shallower entry (0.882 / 0.786 -- and occasionally even 0.941) against the
leg's RUNNING extreme and then resumes the trend never flips the zigzag, so
that tradeable entry is invisible in the legs list -- the leg silently
extends past it. Deriving the 882/786 universes from the final legs
undercounts them.

THE UNIVERSE, built from scratch:
  1. Run the same refined ATR-zigzag walk as clean_legs (identical pivots).
  2. Each consecutive pivot pair (P -> final terminal) is a PHASE. Within a
     phase, every bar that sets a strictly deeper running extreme T defines
     a candidate sub-leg (P, T) -- the fib a trader could have drawn at that
     moment. The final terminal is always a candidate, so the classic
     zigzag legs are a strict subset (asserted below).
  3. Gates are checked per candidate snapshot: span >= min_bars and
     depth >= mult * ATR[terminal bar] ("6c/4x minimum" charts).
  4. execute() (human-validated engine, 5m sub-bars) decides per entry
     level whether the candidate actually filled before its extreme was
     replaced: no_trigger/no_entry/degenerate = miss (not a setup).
     Sequential fills on the same parent (deeper extreme -> new retracement)
     are distinct setups by design -- runner TP3 sits at the old extreme, so
     the prior trade is closed before the next candidate can fill.

Setups keep the same identity as everywhere else: setup_key = parent_ts|term_ts.

Usage:
  PYTHONPATH=. .venv/bin/python scripts/scan_entry_universe.py --month 2026-05 \
      --min-bars 6 --mult 4.0 [--exit-plan runner] [--json PATH]

Prints consolidated stats for all three entry levels (941/882/786), with and
without the Ichimoku two-sides veto (evaluated at the fill bar), plus the
delta vs the legs-only universe. --json dumps the triggered setups per entry
for downstream use (freeze / review).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.swing_detector import clean_legs
from apps.worker.discovery_bet_1.types import Candle
from scripts.execute_fib_strategy import REGIMES, build_subbar_index, execute
from scripts.ichimoku_regime import IchimokuRegime

CSV_1H = REPO_ROOT / "data/discovery_bet_1/binance_btcusdt_1h_full_history.csv"
CSV_5M = REPO_ROOT / "data/discovery_bet_1/binance_btcusdt_5m_full_history.csv"

WIN_CLASSES = ("tp1_then_scratch", "tp2_then_scratch", "tp3_full")
MISS_STATUSES = ("no_entry", "no_trigger", "degenerate")
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


def refined_pivots(candles: list[Candle], atr: list, mult: float) -> list[tuple]:
    """The exact walk + refinement from clean_legs, returning the PIVOTS
    (clean_legs only returns span-gated leg pairs; we need every pivot)."""
    n = len(candles)
    piv: list[tuple[int, float, str]] = []
    direction = 0
    cur_hi, cur_hi_i = candles[0].high, 0
    cur_lo, cur_lo_i = candles[0].low, 0
    for i in range(1, n):
        c = candles[i]
        thr = (atr[i] or 0.0) * mult
        if thr <= 0:
            if c.high > cur_hi:
                cur_hi, cur_hi_i = c.high, i
            if c.low < cur_lo:
                cur_lo, cur_lo_i = c.low, i
            continue
        if direction != -1 and c.high > cur_hi:
            cur_hi, cur_hi_i = c.high, i
        if direction != 1 and c.low < cur_lo:
            cur_lo, cur_lo_i = c.low, i
        if direction != -1 and (cur_hi - c.low) >= thr:
            piv.append((cur_hi_i, cur_hi, "high"))
            direction = -1
            cur_lo, cur_lo_i = c.low, i
        elif direction != 1 and (c.high - cur_lo) >= thr:
            piv.append((cur_lo_i, cur_lo, "low"))
            direction = 1
            cur_hi, cur_hi_i = c.high, i
    if len(piv) >= 2:
        refined: list[tuple[int, float, str]] = []
        for j, (pi, pp, pk) in enumerate(piv):
            lo = (refined[-1][0] + 1) if refined else 0
            hi = piv[j + 1][0] if j + 1 < len(piv) else min(pi + 1, n)
            if lo >= hi:
                refined.append((pi, pp, pk))
                continue
            if pk == "high":
                best_i, best_p = pi, pp
                for k in range(lo, hi):
                    if candles[k].high >= best_p:
                        best_p, best_i = candles[k].high, k
            else:
                best_i, best_p = pi, pp
                for k in range(lo, hi):
                    if candles[k].low <= best_p:
                        best_p, best_i = candles[k].low, k
            refined.append((best_i, best_p, pk))
        piv = refined
    return piv


def candidates_from_pivots(candles, atr, piv, min_bars, mult):
    """Every (parent, running-extreme) snapshot clearing the gates.

    For each pivot parent P, walk forward until the PARENT ANCHOR IS BREACHED
    (a candle beyond P's price) -- NOT merely until the next zigzag pivot.
    Each bar strictly deepening the running extreme yields a candidate
    (P, that bar). This lets terminals extend across micro-flips to later,
    truer extremes (PO ruling 2026-07-03: rejected setups were 'near-sighted'
    -- the second anchor belonged one or two extremes further out). The
    clean-leg invariant holds by construction: interior bars never breach the
    parent (window rule) nor the terminal (it is the running extreme).
    Gates: span >= min_bars, depth >= mult * atr[terminal bar]. Classic legs
    remain a strict subset (their terminals are running extremes within the
    window).
    """
    n = len(candles)
    out = []
    for j, (pi, pp, pk) in enumerate(piv):
        down = pk == "high"
        run_ext = None
        for k in range(pi + 1, n):
            c = candles[k]
            if (c.high > pp) if down else (c.low < pp):
                break  # parent breached -- the swing's origin is invalidated
            ext = c.low if down else c.high
            deeper = run_ext is None or (ext < run_ext if down else ext > run_ext)
            if not deeper:
                continue
            run_ext = ext
            span = k - pi
            depth_abs = (pp - ext) if down else (ext - pp)
            a = atr[k] or atr[pi] or 0.0
            if span < min_bars or a <= 0 or depth_abs < mult * a:
                continue
            out.append({
                "direction": "down" if down else "up",
                "size": depth_abs,
                "parent_idx": pi, "parent_price": pp,
                "parent_kind": pk,
                "parent_ts": candles[pi].source_timestamp,
                "term_idx": k, "term_price": ext,
                "term_kind": "low" if down else "high",
                "term_ts": candles[k].source_timestamp,
                "span": span, "depth": depth_abs / a,
            })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True, help="YYYY-MM (parent_ts filter)")
    ap.add_argument("--min-bars", type=int, default=6)
    ap.add_argument("--mult", type=float, default=4.0)
    ap.add_argument("--exit-plan", choices=["runner", "rest50"], default="runner")
    ap.add_argument("--max-fill-lag", type=int, default=None,
                    help="third gate (MISSION axis 5): drop fills where more "
                         "than N candles elapsed between the terminal anchor "
                         "and the entry fill. Live-implementable: at fill time "
                         "the bar index and terminal ts are both known.")
    ap.add_argument("--json", help="write triggered setups per entry to this path")
    args = ap.parse_args()
    lo = f"{args.month}-01T00:00:00"
    hi = f"{args.month}-31T23:59:59"

    candles = load_csv(CSV_1H)
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    atr = calculate_atr14(candles)
    sub5 = build_subbar_index(load_csv(CSV_5M))
    regime = IchimokuRegime(candles)

    piv = refined_pivots(candles, atr, args.mult)
    cands = [c for c in candidates_from_pivots(candles, atr, piv,
                                               args.min_bars, args.mult)
             if lo <= c["parent_ts"] <= hi]
    keys = [f"{c['parent_ts']}|{c['term_ts']}" for c in cands]
    assert len(keys) == len(set(keys)), "duplicate candidate keys"
    print(f"==> {args.month} @ {args.min_bars}c/{args.mult:g}x: "
          f"{len(cands)} gate-clearing candidates "
          f"(parents: {len({c['parent_ts'] for c in cands})})")

    # Cross-check: the classic legs universe must be a subset of candidates.
    legs = [l for l in clean_legs(candles, atr, None,
                                  min_bars=args.min_bars, mult=args.mult)
            if lo <= l["parent_ts"] <= hi and l["term_ts"] in idx]
    cand_keys = set(keys)
    missing = [l for l in legs
               if f"{l['parent_ts']}|{l['term_ts']}" not in cand_keys]
    if missing:
        print(f"    WARN: {len(missing)} classic legs NOT in candidate set "
              f"(depth-gate at terminal-bar ATR excluded them):")
        for l in missing:
            print(f"      {l['parent_ts']} -> {l['term_ts']}")
    else:
        print(f"    cross-check OK: all {len(legs)} classic legs are candidates.")

    def veto_class(res):
        ts = res["events"][0][1]
        i = idx.get(ts[:13] + ":00:00")
        return regime.classify(i) if i is not None else "n/a"

    rest50 = {"p1": 0.25, "p2": 0.75, "p3": 0.0} if args.exit_plan == "rest50" else {}
    results = {}
    for r in REGIMES:
        slug = r["slug"]
        kwargs = dict(r["params"], **rest50)
        trig = []
        for c in cands:
            res = execute(candles, idx, c, subbars=sub5, **kwargs)
            if res["status"] in MISS_STATUSES:
                continue
            fill_i = idx.get(res["events"][0][1][:13] + ":00:00")
            between = [p for p in piv
                       if fill_i is not None and c["term_idx"] < p[0] < fill_i]
            lag = (fill_i - c["term_idx"]) if fill_i is not None else None
            if (args.max_fill_lag is not None and lag is not None
                    and lag > args.max_fill_lag):
                continue
            trig.append({**c, "status": res["status"],
                         "class": CLS.get(res["status"], res["status"]),
                         "r": round(res["r"], 4),
                         "fill_ts": res["events"][0][1],
                         "fill_lag": lag,
                         "veto": veto_class(res) == "transition",
                         "stale_fill": bool(between),
                         "pivots_between": len(between),
                         "events": [(e[0], e[1], round(e[2], 2))
                                    for e in res["events"]]})
        # legs-only triggered set for the delta line
        legs_trig = set()
        for l in legs:
            res = execute(candles, idx, l, subbars=sub5, **kwargs)
            if res["status"] not in MISS_STATUSES:
                legs_trig.add(f"{l['parent_ts']}|{l['term_ts']}")
        results[slug] = (trig, legs_trig)

    print()
    hdr = (f"{'config':<6} {'trig':>4} {'new':>4} {'TP1':>4} {'TP2':>4} "
           f"{'TP3':>4} {'LOSS':>5} {'OPEN':>5} {'winrate':>8} {'totR':>8} "
           f"{'avgR':>6} | veto-kept {'totR':>8} {'avgR':>6}")
    print(hdr)
    for r in REGIMES:
        slug = r["slug"]
        trig, legs_trig = results[slug]
        cl = Counter(t["class"] for t in trig)
        wins = cl["TP1"] + cl["TP2"] + cl["TP3"]
        tot = sum(t["r"] for t in trig)
        kept = [t for t in trig if not t["veto"]]
        ktot = sum(t["r"] for t in kept)
        new = sum(1 for t in trig
                  if f"{t['parent_ts']}|{t['term_ts']}" not in legs_trig)
        wr = wins / len(trig) * 100 if trig else 0.0
        print(f"e{slug[1:]:<5} {len(trig):>4} {new:>4} {cl['TP1']:>4} "
              f"{cl['TP2']:>4} {cl['TP3']:>4} {cl['LOSS']:>5} {cl['OPEN']:>5} "
              f"{wr:>7.0f}% {tot:>+8.2f} "
              f"{(tot / len(trig)) if trig else 0.0:>+6.2f} |"
              f"  {len(kept):>3}/{len(trig):<3} {ktot:>+8.2f} "
              f"{(ktot / len(kept)) if kept else 0.0:>+6.2f}")

    print()
    for r in REGIMES:
        slug = r["slug"]
        trig, legs_trig = results[slug]
        print(f"--- e{slug[1:]} triggered setups ({len(trig)}) ---")
        for t in sorted(trig, key=lambda x: x["fill_ts"]):
            k = f"{t['parent_ts']}|{t['term_ts']}"
            star = "  *NEW*" if k not in legs_trig else ""
            v = " X" if t["veto"] else ""
            print(f"  {t['parent_ts'][5:16]} -> {t['term_ts'][5:16]}  "
                  f"{t['direction']:<4} {t['span']:>3}c {t['depth']:>4.1f}a  "
                  f"fill {t['fill_ts'][5:16]}  {t['class']:<4} "
                  f"{t['r']:+.2f}{v}{star}")
        print()

    if args.json:
        payload = {f"e{r['slug'][1:]}": results[r["slug"]][0] for r in REGIMES}
        Path(args.json).write_text(json.dumps(payload, indent=1),
                                   encoding="utf-8")
        print(f"==> wrote triggered universes to {args.json}")


if __name__ == "__main__":
    main()
