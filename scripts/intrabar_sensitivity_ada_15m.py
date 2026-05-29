#!/usr/bin/env python
"""Intrabar-ambiguity stress test for ADA 15m 0.941 setups.

Re-scores every triggered setup under three conventions, on phase 1 only (the
period between entry and TP1), where the ambiguity bites hardest:

  1) executor_default  -- nearest-first; TP1 wins when a single bar's range
                          spans both TP1 and SL. This is what the backtest uses.
  2) pessimistic       -- SL wins ties.
  3) open_direction    -- if a bar opens above entry (LONG), assume it touched
                          TP1 first then dipped to SL. If it opens below entry,
                          assume it touched SL first then bounced up to TP1.
                          A coarse intra-bar path heuristic.

Reports per-convention: triggered N, wins, losses, total R, and the magnitude
of disagreement (how many trades flip outcome under each alternative).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.types import Candle
from scripts.execute_fib_strategy import REGIMES, run_regime
from scripts.build_dashboard import KIND
from scripts.place_fibs_tradingview import _clean_legs

PATH = REPO_ROOT / "data/discovery_bet_1/binance_adausdt_15m_full_history.csv"
REG_941 = next(r for r in REGIMES if r["slug"] == "x941")


def load_csv(p):
    out = []
    with p.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Candle(row["source_timestamp"], float(row["open"]),
                              float(row["high"]), float(row["low"]),
                              float(row["close"]), float(row["volume"])))
    return out


def fib_price(parent, term, c):
    return term + c * (parent - term)


def score_one(candles, idx, leg, convention):
    """Re-score a single setup under a chosen tie-breaking convention.

    Returns (status, r, ambiguous_bars).

    Statuses: no_trigger | wipeout | tp1_then_scratch | tp2_then_scratch |
              tp3_full | open | degenerate
    R-multiples and partial sizing match execute(): p1=0.25, p2=0.60, p3=0.15.
    """
    parent = leg["parent_price"]; term = leg["term_price"]
    up = leg["direction"] == "up"
    entry = fib_price(parent, term, 0.941)
    tp1   = fib_price(parent, term, 0.882)
    tp2   = fib_price(parent, term, 0.5)
    tp3   = fib_price(parent, term, 0.0)
    init_sl = fib_price(parent, term, 1.05)
    p1, p2, p3 = 0.25, 0.60, 0.15
    risk = abs(entry - init_sl)
    if risk <= 0:
        return ("degenerate", 0.0, 0)
    if (up and term <= parent) or (not up and term >= parent):
        return ("degenerate", 0.0, 0)
    r_tp1 = abs(entry - tp1) / risk
    r_tp2 = abs(entry - tp2) / risk
    r_tp3 = abs(entry - tp3) / risk

    ti = idx[leg["term_ts"]]
    # find entry bar (skip-entry-bar convention afterwards)
    entry_bar = None
    for j in range(ti + 1, len(candles)):
        c = candles[j]
        if up:
            if c.high > term:
                return ("no_trigger", 0.0, 0)
            if c.low <= entry:
                entry_bar = j; break
        else:
            if c.low < term:
                return ("no_trigger", 0.0, 0)
            if c.high >= entry:
                entry_bar = j; break
    if entry_bar is None:
        return ("no_entry", 0.0, 0)

    phase = 1
    sl = init_sl
    realized = 0.0
    ambiguous = 0
    for j in range(entry_bar + 1, len(candles)):
        c = candles[j]
        if phase == 1:
            hit_tp1 = (c.high >= tp1) if up else (c.low <= tp1)
            hit_sl  = (c.low <= sl)  if up else (c.high >= sl)
            if hit_tp1 and hit_sl:
                ambiguous += 1
                if convention == "executor_default":
                    tp1_first = True
                elif convention == "pessimistic":
                    tp1_first = False
                elif convention == "open_direction":
                    # LONG: if open >= entry, the bar arguably moved up first.
                    # If open < entry, it likely dipped first.
                    if up:
                        tp1_first = c.open >= entry
                    else:
                        tp1_first = c.open <= entry
                else:
                    raise ValueError(convention)
                if tp1_first:
                    phase, sl = 2, entry
                    realized += p1 * r_tp1
                else:
                    return ("wipeout", -1.0, ambiguous)
            elif hit_tp1:
                phase, sl = 2, entry
                realized += p1 * r_tp1
            elif hit_sl:
                return ("wipeout", -1.0, ambiguous)
        elif phase == 2:
            # Same hierarchy as executor: intrabar TP2 wick before close-based BE
            if (up and c.high >= tp2) or (not up and c.low <= tp2):
                phase = 3
                realized += p2 * r_tp2
            elif (up and c.close <= sl) or (not up and c.close >= sl):
                return ("tp1_then_scratch", realized, ambiguous)
        else:  # phase 3
            if (up and c.high >= tp3) or (not up and c.low <= tp3):
                realized += p3 * r_tp3
                return ("tp3_full", realized, ambiguous)
            elif (up and c.close <= sl) or (not up and c.close >= sl):
                return ("tp2_then_scratch", realized, ambiguous)
    return ("open", realized, ambiguous)


def main():
    print(f"loading ADA 15m ({PATH.name})...");
    candles = load_csv(PATH)
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    atr = calculate_atr14(candles)
    piv = detect_local_pivots(candles)
    legs = [l for l in _clean_legs(candles, atr, piv, min_bars=6, mult=2.0)
            if l["term_ts"] in idx]
    print(f"  {len(legs)} legs detected\n")

    summary = {}
    flip_counts = {"to_loss": 0, "to_win": 0}
    ambig_bars_total = 0
    ambig_trades = 0

    # Score under all three conventions in parallel
    per_setup = []
    for leg in legs:
        results = {conv: score_one(candles, idx, leg, conv) for conv in
                   ("executor_default", "pessimistic", "open_direction")}
        per_setup.append((leg, results))
        if results["executor_default"][2] > 0:
            ambig_trades += 1
            ambig_bars_total += results["executor_default"][2]

    print(f"setups with at least one TP1/SL-ambiguity bar in phase 1: "
          f"{ambig_trades:,} / {len(legs):,}  "
          f"({ambig_trades/len(legs)*100:.1f}%)")
    print(f"  total ambiguous bars encountered: {ambig_bars_total:,}\n")

    # Per-convention totals
    print(f"{'convention':<22}{'triggered':>10}{'wins':>8}{'partial':>9}{'scratch':>9}{'losses':>8}{'totR':>10}{'avgR':>9}")
    for conv in ("executor_default", "pessimistic", "open_direction"):
        rows = []
        for _, results in per_setup:
            st, r, _ = results[conv]
            if st in ("no_trigger", "no_entry", "degenerate"):
                continue
            rows.append((st, r))
        n = len(rows)
        wins = sum(1 for s, _ in rows if s == "tp3_full")
        partial = sum(1 for s, _ in rows if s == "tp2_then_scratch")
        scratch = sum(1 for s, _ in rows if s == "tp1_then_scratch")
        losses = sum(1 for s, _ in rows if s == "wipeout")
        totr = sum(r for _, r in rows)
        print(f"{conv:<22}{n:>10}{wins:>8}{partial:>9}{scratch:>9}{losses:>8}{totr:>+10.1f}{totr/n if n else 0:>+9.3f}")
    print()

    # How many outcomes flip from executor_default to pessimistic?
    flipped_to_loss = 0
    delta_r = 0.0
    for _, results in per_setup:
        d_st, d_r, _ = results["executor_default"]
        p_st, p_r, _ = results["pessimistic"]
        if d_st in ("no_trigger", "no_entry", "degenerate"):
            continue
        if d_st != "wipeout" and p_st == "wipeout":
            flipped_to_loss += 1
            delta_r += (p_r - d_r)
    print(f"outcomes that FLIP from executor's win/scratch/partial to pessimistic '-1R loss': "
          f"{flipped_to_loss:,}")
    print(f"  cumulative R impact: {delta_r:+.1f}R "
          f"(executor's R - pessimistic R for those trades)")


if __name__ == "__main__":
    main()
