#!/usr/bin/env python
"""Render one 5m-magnifier card for EVERY ambiguous ADA 15m setup (no sampling).

Output dir: artifacts/discovery_bet_1/ambig_intrabar_ada_15m/
Naming: A<NNNN>_<verdict>_<date>.png so the user can sort by verdict.
Index:  00_index.csv with executor_R, verdict, corrected_R (per-card delta).
"""
from __future__ import annotations
import csv, sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from scripts.build_dashboard import KIND
from scripts.execute_fib_strategy import REGIMES, run_regime
from scripts.place_fibs_tradingview import _clean_legs
from scripts.manual_review_ada_15m import (
    CSV_PATH, CSV_PATH_5M, load_csv, find_ambiguous_bars, draw_card,
    cohort_label,
)
from scripts.corrected_5m_aggregate_ada import resolve_5m

OUT_DIR = REPO_ROOT / "artifacts/discovery_bet_1/ambig_intrabar_ada_15m"
REG_941 = next(r for r in REGIMES if r["slug"] == "x941")

VERDICT_R = {     # given executor's R, what does the verdict say is the truth?
    "TP1": lambda r: r,             # executor was right
    "TP1_ONLY": lambda r: r,
    "SL":  lambda _: -1.0,          # executor overcounted -> -1R
    "SL_ONLY": lambda _: -1.0,
    "STILL_AMBIG": lambda r: r,     # leave at executor; mark for 1m followup
    "NEITHER": lambda r: r,
}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("A*.png"): stale.unlink()
    for stale in OUT_DIR.glob("*.csv"): stale.unlink()

    print("loading 15m + 5m + detecting legs...")
    candles = load_csv(CSV_PATH)
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    candles_5m = load_csv(CSV_PATH_5M)
    idx_5m = {c.source_timestamp: i for i, c in enumerate(candles_5m)}
    atr = calculate_atr14(candles)
    piv = detect_local_pivots(candles)
    legs = [l for l in _clean_legs(candles, atr, piv, min_bars=6, mult=2.0)
            if l["term_ts"] in idx]
    print(f"  {len(legs):,} legs total\n")

    # First pass: find every ambig setup, classify with 5m, collect for rendering
    ambig_records = []
    for leg in legs:
        res = run_regime(candles, idx, leg, REG_941)
        if res["status"] in ("no_trigger", "no_entry", "degenerate", "shrug"):
            continue
        ambig = find_ambiguous_bars(candles, idx, leg, res)
        if not ambig:
            continue
        a = ambig[0]
        verdict = "UNKNOWN"
        if a["bar_ts"] in idx_5m:
            base = idx_5m[a["bar_ts"]]
            sub = candles_5m[base:base+3]
            if len(sub) == 3:
                verdict = resolve_5m(sub, a["tp1"], a["sl"], a["up"])
        atr_at_term = atr[idx[leg["term_ts"]]] or 1.0
        depth = abs(leg["term_price"] - leg["parent_price"]) / atr_at_term
        cohort = cohort_label(depth) or f"{depth:.1f}+"
        ambig_records.append({
            "leg": leg, "res": res, "verdict": verdict,
            "depth": depth, "cohort": cohort, "ambig_bar": a,
        })
    print(f"{len(ambig_records):,} ambiguous setups to render\n")

    # Sort by term_ts for stable card numbering
    ambig_records.sort(key=lambda r: r["leg"]["term_ts"])

    # Render + write index
    index_path = OUT_DIR / "00_index.csv"
    with index_path.open("w", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["card_id", "term_ts", "direction", "cohort", "depth_atr",
                    "executor_outcome", "executor_R", "verdict_5m", "corrected_R",
                    "delta_R", "ambig_bar_ts"])
        for k, r in enumerate(ambig_records, start=1):
            card_id = f"A{k:04d}"
            leg = r["leg"]; res = r["res"]; verdict = r["verdict"]
            outcome = KIND.get(res["status"], "open")
            corrected_r = VERDICT_R.get(verdict, lambda x: x)(res["r"])
            delta = corrected_r - res["r"]
            verdict_short = verdict.replace("_", "-")
            png_name = f"{card_id}_{verdict_short}_{leg['term_ts'][:10]}.png"
            out_path = OUT_DIR / png_name
            draw_card(candles, idx, atr, leg, res, card_id, outcome,
                      r["cohort"], out_path,
                      candles_5m=candles_5m, idx_5m=idx_5m)
            w.writerow([card_id, leg["term_ts"], leg["direction"], r["cohort"],
                        f"{r['depth']:.2f}", outcome, f"{res['r']:+.3f}",
                        verdict, f"{corrected_r:+.3f}", f"{delta:+.3f}",
                        r["ambig_bar"]["bar_ts"]])
            if k % 200 == 0:
                print(f"  rendered {k:,}/{len(ambig_records):,} ...", flush=True)

    # Summary
    from collections import Counter
    verdicts = Counter(r["verdict"] for r in ambig_records)
    print(f"\nWROTE {len(ambig_records):,} cards to {OUT_DIR}")
    print(f"verdict distribution:")
    for v, c in verdicts.most_common():
        print(f"  {v:<14}  {c:>5}  ({c/len(ambig_records)*100:>4.1f}%)")


if __name__ == "__main__":
    main()
