#!/usr/bin/env python
"""Compute the 5m-resolved win rate and net R for the FULL ADA 15m population.

For every triggered setup at 6c / 2.0x, run the executor to get the headline
outcome, then check each phase-1 ambiguous bar against the underlying 5m
sub-bars to determine the true intrabar order. Re-score the trade if 5m says
SL fired before TP1.

Reports three views:
  - executor_default     -- current code path (nearest-first)
  - corrected_optimistic -- 5m where resolvable, keep executor where 5m is itself ambiguous
  - corrected_pessimistic-- 5m where resolvable, assume SL-first where 5m is still ambig
"""
from __future__ import annotations
import csv, sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.types import Candle
from scripts.build_dashboard import KIND
from scripts.execute_fib_strategy import REGIMES, run_regime
from scripts.place_fibs_tradingview import _clean_legs
from scripts.manual_review_ada_15m import (
    CSV_PATH, CSV_PATH_5M, load_csv, find_ambiguous_bars,
)
REG_941 = next(r for r in REGIMES if r["slug"] == "x941")


def resolve_5m(c5m_window, tp1, sl, up):
    """Return one of: 'TP1', 'SL', 'TP1_ONLY', 'SL_ONLY', 'STILL_AMBIG', 'NEITHER'."""
    tp1_at = sl_at = None
    sub_ambig = False
    for k, sc in enumerate(c5m_window):
        hit_tp1 = (sc.high >= tp1) if up else (sc.low <= tp1)
        hit_sl  = (sc.low <= sl)   if up else (sc.high >= sl)
        if hit_tp1 and hit_sl:
            sub_ambig = True
            if tp1_at is None: tp1_at = k
            if sl_at is None: sl_at = k
        elif hit_tp1 and tp1_at is None: tp1_at = k
        elif hit_sl and sl_at is None: sl_at = k
    if sub_ambig and (tp1_at == sl_at):
        return "STILL_AMBIG"
    if tp1_at is not None and sl_at is not None:
        return "TP1" if tp1_at < sl_at else "SL"
    if tp1_at is not None: return "TP1_ONLY"
    if sl_at is not None:  return "SL_ONLY"
    return "NEITHER"


def is_win(outcome): return outcome == "tp3_full"
def is_partial(outcome): return outcome == "tp2_then_scratch"
def is_scratch(outcome): return outcome == "tp1_then_scratch"
def is_loss(outcome): return outcome == "wipeout"


def main():
    print("loading data...");
    candles = load_csv(CSV_PATH)
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    candles_5m = load_csv(CSV_PATH_5M)
    idx_5m = {c.source_timestamp: i for i, c in enumerate(candles_5m)}
    atr = calculate_atr14(candles)
    piv = detect_local_pivots(candles)
    legs = [l for l in _clean_legs(candles, atr, piv, min_bars=6, mult=2.0)
            if l["term_ts"] in idx]
    print(f"  {len(candles):,} 15m bars, {len(candles_5m):,} 5m bars, {len(legs):,} legs\n")

    # Per-trade record
    records = []
    for leg in legs:
        res = run_regime(candles, idx, leg, REG_941)
        st = res["status"]
        if st in ("no_trigger", "no_entry", "degenerate", "shrug"):
            continue
        ambig = find_ambiguous_bars(candles, idx, leg, res)
        verdict = None
        if ambig:
            a = ambig[0]
            if a["bar_ts"] in idx_5m:
                base = idx_5m[a["bar_ts"]]
                sub = candles_5m[base:base+3]
                if len(sub) == 3:
                    verdict = resolve_5m(sub, a["tp1"], a["sl"], a["up"])
        records.append({
            "exec_status": st, "exec_r": res["r"],
            "had_ambig": bool(ambig), "verdict": verdict,
            "leg": leg,
        })

    # Three scoring views
    def view(name, decide):
        wins = partials = scratches = losses = 0
        tot_r = 0.0
        for r in records:
            st, rval = decide(r)
            tot_r += rval
            if is_win(st): wins += 1
            elif is_partial(st): partials += 1
            elif is_scratch(st): scratches += 1
            elif is_loss(st): losses += 1
        n = len(records)
        winners = wins + partials + scratches  # ALL non-losses
        wr = winners / n * 100 if n else 0
        avgr = tot_r / n if n else 0
        print(f"  {name:<32} N={n}  wins={wins:>4}  partial={partials:>4}  "
              f"scratch={scratches:>4}  losses={losses:>4}  "
              f"win%={wr:>4.1f}  totR={tot_r:>+9.1f}  avgR={avgr:>+.3f}")

    def exec_decide(r):  return (r["exec_status"], r["exec_r"])
    def opt_decide(r):
        if not r["had_ambig"]: return (r["exec_status"], r["exec_r"])
        if r["verdict"] == "SL": return ("wipeout", -1.0)
        return (r["exec_status"], r["exec_r"])    # TP1 first, TP1_ONLY, STILL_AMBIG, etc.
    def pess_decide(r):
        if not r["had_ambig"]: return (r["exec_status"], r["exec_r"])
        if r["verdict"] in ("TP1", "TP1_ONLY"): return (r["exec_status"], r["exec_r"])
        return ("wipeout", -1.0)   # SL, SL_ONLY, STILL_AMBIG, NEITHER -> assume SL first

    print(f"{'view':<32}{'N':<6}{'wins':<7}{'partials':<10}{'scratches':<11}{'losses':<8}{'win%':<7}{'totR':<10}{'avgR'}")
    view("executor (nearest-first)", exec_decide)
    view("5m-corrected (optimistic)", opt_decide)
    view("5m-corrected (pessimistic)", pess_decide)

    # Verdict distribution among ambig trades
    print()
    ambig = [r for r in records if r["had_ambig"]]
    from collections import Counter
    counts = Counter(r["verdict"] for r in ambig)
    print(f"verdict distribution across {len(ambig):,} ambiguous trades:")
    for v in ("TP1", "TP1_ONLY", "SL", "SL_ONLY", "STILL_AMBIG", "NEITHER", None):
        c = counts.get(v, 0)
        pct = c / len(ambig) * 100 if ambig else 0
        print(f"  {str(v):<14}{c:>6}  ({pct:>5.1f}%)")


if __name__ == "__main__":
    main()
