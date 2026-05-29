#!/usr/bin/env python
"""Definitive 5m+1m resolution of every ambiguous ADA 15m setup.

For each phase-1 ambiguous 15m bar:
  1. Try resolving with the 3 underlying 5m sub-bars.
  2. If the winning 5m sub-bar is itself ambiguous (spans both TP1 and SL),
     drill into its 5 underlying 1m sub-bars to find the true first-touched
     level.
  3. The vanishingly rare case where a 1m bar still spans both falls back
     to the executor's nearest-first outcome and is reported as a residual
     "TRUE_AMBIG_AT_1M" bucket.

Outputs:
  - artifacts/discovery_bet_1/ambig_intrabar_ada_15m/00_definitive.csv
    (one row per ambiguous setup with executor_R, verdict, corrected_R)
  - printed aggregate: definitive win%, gross totR, net totR (HL fees)
"""
from __future__ import annotations
import csv, sys, statistics
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from scripts.build_dashboard import KIND
from scripts.execute_fib_strategy import REGIMES, run_regime
from scripts.place_fibs_tradingview import _clean_legs
from scripts.manual_review_ada_15m import (
    CSV_PATH, CSV_PATH_5M, load_csv, find_ambiguous_bars, fib_price,
)

CSV_PATH_1M = REPO_ROOT / "data/discovery_bet_1/binance_adausdt_1m_full_history.csv"
OUT_CSV = REPO_ROOT / "artifacts/discovery_bet_1/ambig_intrabar_ada_15m/00_definitive.csv"
REG_941 = next(r for r in REGIMES if r["slug"] == "x941")
HL_TAKER_RT = 0.0009


def first_touch(bars, tp1, sl, up):
    """Walk bars in time order; return ('TP1', idx) or ('SL', idx) or ('AMBIG_AT_THIS_GRANULARITY', None)
    or ('NEITHER', None). 'AMBIG_AT_THIS_GRANULARITY' means a single bar in this
    granularity hit BOTH levels and we cannot resolve further at this scale."""
    for k, b in enumerate(bars):
        hit_tp1 = (b.high >= tp1) if up else (b.low <= tp1)
        hit_sl  = (b.low <= sl)   if up else (b.high >= sl)
        if hit_tp1 and hit_sl:
            return ("AMBIG", k)   # this bar is itself ambig at this granularity
        if hit_tp1:
            return ("TP1", k)
        if hit_sl:
            return ("SL", k)
    return ("NEITHER", None)


def resolve_definitive(c5m, idx_5m, c1m, idx_1m, ambig_bar_ts, tp1, sl, up):
    """Two-stage resolution. Returns the final verdict string."""
    if ambig_bar_ts not in idx_5m:
        return "MISSING_5M"
    base5 = idx_5m[ambig_bar_ts]
    sub5 = c5m[base5:base5+3]
    if len(sub5) < 3:
        return "MISSING_5M"

    result5, idx5_hit = first_touch(sub5, tp1, sl, up)
    if result5 in ("TP1", "SL"):
        return result5    # 5m resolved it cleanly
    if result5 == "NEITHER":
        return "NEITHER"  # didn't actually hit either (shouldn't happen given parent bar was ambig)
    # result5 == "AMBIG" -- the idx5_hit'th 5m bar hits both. Drill to 1m.
    ambig5_ts = sub5[idx5_hit].source_timestamp
    if ambig5_ts not in idx_1m:
        return "MISSING_1M"
    base1 = idx_1m[ambig5_ts]
    sub1 = c1m[base1:base1+5]
    if len(sub1) < 5:
        return "MISSING_1M"
    result1, _ = first_touch(sub1, tp1, sl, up)
    if result1 in ("TP1", "SL"):
        return result1
    if result1 == "AMBIG":
        return "TRUE_AMBIG_AT_1M"   # vanishingly rare
    return "NEITHER"


def main():
    if not CSV_PATH_1M.exists():
        print(f"missing {CSV_PATH_1M.name}; acquire it first."); sys.exit(2)
    print(f"loading 15m + 5m + 1m...")
    candles = load_csv(CSV_PATH)
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    c5m = load_csv(CSV_PATH_5M)
    idx_5m = {c.source_timestamp: i for i, c in enumerate(c5m)}
    c1m = load_csv(CSV_PATH_1M)
    idx_1m = {c.source_timestamp: i for i, c in enumerate(c1m)}
    print(f"  15m: {len(candles):,}  5m: {len(c5m):,}  1m: {len(c1m):,}\n")

    atr = calculate_atr14(candles)
    piv = detect_local_pivots(candles)
    legs = [l for l in _clean_legs(candles, atr, piv, min_bars=6, mult=2.0)
            if l["term_ts"] in idx]

    rows = []
    for leg in legs:
        res = run_regime(candles, idx, leg, REG_941)
        if res["status"] in ("no_trigger", "no_entry", "degenerate", "shrug"):
            continue
        parent = leg["parent_price"]; term = leg["term_price"]
        entry = fib_price(parent, term, 0.941)
        sl_price = fib_price(parent, term, 1.05)
        e2sl_pct = abs(entry - sl_price) / entry
        fee_r = HL_TAKER_RT / e2sl_pct

        ambig = find_ambiguous_bars(candles, idx, leg, res)
        verdict = None
        if ambig:
            a = ambig[0]
            verdict = resolve_definitive(c5m, idx_5m, c1m, idx_1m,
                                         a["bar_ts"], a["tp1"], a["sl"], a["up"])
        rows.append({
            "exec_status": res["status"], "exec_r": res["r"],
            "had_ambig": bool(ambig), "verdict": verdict, "fee_r": fee_r,
            "term_ts": leg["term_ts"], "direction": leg["direction"],
            "ambig_bar_ts": ambig[0]["bar_ts"] if ambig else "",
        })

    # Write the definitive per-card CSV
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w") as fh:
        w = csv.writer(fh)
        w.writerow(["term_ts", "direction", "exec_status", "exec_R",
                    "had_ambig", "verdict_1m_resolved", "corrected_R",
                    "fee_R", "ambig_bar_ts"])
        for r in rows:
            corrected = r["exec_r"]
            if r["verdict"] == "SL":
                corrected = -1.0
            w.writerow([r["term_ts"], r["direction"], r["exec_status"],
                        f"{r['exec_r']:+.3f}", int(r["had_ambig"]),
                        r["verdict"] or "", f"{corrected:+.3f}",
                        f"{r['fee_r']:.3f}", r["ambig_bar_ts"]])

    # Aggregate verdict distribution
    from collections import Counter
    ambig_rows = [r for r in rows if r["had_ambig"]]
    counts = Counter(r["verdict"] for r in ambig_rows)
    print(f"DEFINITIVE 1m-resolved verdict distribution across "
          f"{len(ambig_rows):,} ambiguous trades:")
    for v, c in counts.most_common():
        print(f"  {v:<22}  {c:>5}  ({c/len(ambig_rows)*100:>5.1f}%)")
    print()

    # Definitive scoring
    def decide(r):
        if not r["had_ambig"]: return (r["exec_status"], r["exec_r"])
        if r["verdict"] == "SL": return ("wipeout", -1.0)
        return (r["exec_status"], r["exec_r"])

    def is_winning(s): return s in ("tp3_full", "tp2_then_scratch", "tp1_then_scratch")
    n = len(rows)
    wins = 0; tot_g = 0.0; tot_n = 0.0
    for r in rows:
        st, gross = decide(r)
        net = gross - r["fee_r"]
        tot_g += gross; tot_n += net
        if is_winning(st): wins += 1
    wr = wins / n * 100
    print(f"DEFINITIVE (5m+1m resolved):")
    print(f"  N={n:,}  win%={wr:.1f}%  gross_totR={tot_g:+.1f}  net_totR={tot_n:+.1f}  "
          f"gross_avgR={tot_g/n:+.3f}  net_avgR={tot_n/n:+.3f}")
    print(f"  WROTE per-card CSV: {OUT_CSV}")


if __name__ == "__main__":
    main()
