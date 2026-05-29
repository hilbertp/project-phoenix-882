#!/usr/bin/env python
"""Net R for the 5m-corrected ADA 15m backtest, computed PROPERLY.

Per-trade fee = 0.09% of position notional value (HL taker round-trip).
In R-multiples: fee_R = 0.0009 / (entry_to_SL / entry_price)
i.e. fee burden is bigger when the entry-to-SL band is a smaller % of price.

Computes:
  - distribution of entry-to-SL distance as % of entry price across the population
  - fees-as-fraction-of-1R distribution
  - net R for each of the three views (executor / opt / pess)
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
from scripts.corrected_5m_aggregate_ada import resolve_5m

REG_941 = next(r for r in REGIMES if r["slug"] == "x941")
HL_TAKER_RT = 0.0009  # 0.045% per side, 0.09% round trip


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
    print(f"  {len(legs):,} legs total\n")

    # Per-trade record (only triggered trades)
    rows = []
    fee_R_list = []
    e2sl_pct_list = []
    for leg in legs:
        res = run_regime(candles, idx, leg, REG_941)
        if res["status"] in ("no_trigger", "no_entry", "degenerate", "shrug"):
            continue
        parent = leg["parent_price"]; term = leg["term_price"]
        entry = fib_price(parent, term, 0.941)
        sl = fib_price(parent, term, 1.05)
        e2sl_pct = abs(entry - sl) / entry   # e.g. 0.013 = 1.3%
        fee_R = HL_TAKER_RT / e2sl_pct       # 0.0009 / 0.013 = 0.069R
        fee_R_list.append(fee_R)
        e2sl_pct_list.append(e2sl_pct * 100)

        ambig = find_ambiguous_bars(candles, idx, leg, res)
        verdict = None
        if ambig:
            a = ambig[0]
            if a["bar_ts"] in idx_5m:
                base = idx_5m[a["bar_ts"]]
                sub = candles_5m[base:base+3]
                if len(sub) == 3:
                    verdict = resolve_5m(sub, a["tp1"], a["sl"], a["up"])
        rows.append({
            "exec_status": res["status"], "exec_r": res["r"],
            "had_ambig": bool(ambig), "verdict": verdict, "fee_r": fee_R,
        })

    # Distribution stats
    e2sl_pct_list.sort(); fee_R_list.sort()
    print("entry-to-SL distance as % of entry price (population stats):")
    print(f"  p10={e2sl_pct_list[len(e2sl_pct_list)*10//100]:.3f}%   "
          f"p25={e2sl_pct_list[len(e2sl_pct_list)*25//100]:.3f}%   "
          f"p50={statistics.median(e2sl_pct_list):.3f}%   "
          f"p75={e2sl_pct_list[len(e2sl_pct_list)*75//100]:.3f}%   "
          f"p90={e2sl_pct_list[len(e2sl_pct_list)*90//100]:.3f}%")
    print(f"\nfee burden per trade (HL 0.09% RT) as fraction of 1R:")
    print(f"  p10={fee_R_list[len(fee_R_list)*10//100]:.3f}R   "
          f"p25={fee_R_list[len(fee_R_list)*25//100]:.3f}R   "
          f"p50={statistics.median(fee_R_list):.3f}R   "
          f"p75={fee_R_list[len(fee_R_list)*75//100]:.3f}R   "
          f"p90={fee_R_list[len(fee_R_list)*90//100]:.3f}R")
    print(f"  mean fee burden: {statistics.mean(fee_R_list):.3f}R per trade\n")

    # Three views, gross and net
    def is_loss(s): return s == "wipeout"
    def is_winning(s): return s in ("tp3_full", "tp2_then_scratch", "tp1_then_scratch")
    def view(name, decide):
        n = len(rows)
        wins = 0; tot_g = 0.0; tot_n = 0.0
        for r in rows:
            st, gross = decide(r)
            net = gross - r["fee_r"]
            tot_g += gross; tot_n += net
            if is_winning(st): wins += 1
        wr = wins / n * 100
        print(f"  {name:<32} N={n}  win%={wr:>4.1f}  "
              f"gross_totR={tot_g:>+9.1f}  net_totR={tot_n:>+9.1f}  "
              f"gross_avgR={tot_g/n:>+.3f}  net_avgR={tot_n/n:>+.3f}")

    def exec_decide(r):  return (r["exec_status"], r["exec_r"])
    def opt_decide(r):
        if not r["had_ambig"]: return (r["exec_status"], r["exec_r"])
        if r["verdict"] == "SL": return ("wipeout", -1.0)
        return (r["exec_status"], r["exec_r"])
    def pess_decide(r):
        if not r["had_ambig"]: return (r["exec_status"], r["exec_r"])
        if r["verdict"] in ("TP1", "TP1_ONLY"): return (r["exec_status"], r["exec_r"])
        return ("wipeout", -1.0)

    print("Three R views, GROSS and NET of HL 0.09% RT fees:")
    print(f"{'view':<32}{'N':<6}{'win%':<7}{'gross_totR':<14}{'net_totR':<14}{'gross_avgR':<13}{'net_avgR'}")
    view("executor (nearest-first)", exec_decide)
    view("5m-corrected (optimistic)", opt_decide)
    view("5m-corrected (pessimistic)", pess_decide)


if __name__ == "__main__":
    main()
