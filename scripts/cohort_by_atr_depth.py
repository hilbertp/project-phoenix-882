#!/usr/bin/env python
"""Cohort backtest by leg depth (× hourly ATR14).

Two jobs:
  1) Verify the previously reported retrace-depth distribution per asset --
     median retrace, % of setups that reach 0.786, % that reach 0.941. Output
     each asset's numbers SIDE-BY-SIDE so the reader can see whether any
     "identical to two decimals" claim across assets is real or arithmetic.
  2) Cohort every detected setup by its leg depth in ATR units
     (4-6, 6-8, 8-10, 10-12, 12-16, 16+) and report N / win% / total R / avg R
     per regime per cohort, so we can answer: which depth range pays best.

R is gross (no fees). Detector defaults match the rest of the long-horizon
scripts: min_bars=6, mult=2.0. Override via CLI.

Usage:
  cohort_by_atr_depth.py                       # all crypto long-history assets
  cohort_by_atr_depth.py --assets BTC ETH ADA  # subset
  cohort_by_atr_depth.py --min-bars 6 --mult 2.0
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.types import Candle
from scripts.build_dashboard import KIND
from scripts.execute_fib_strategy import REGIMES, run_regime
from scripts.place_fibs_tradingview import _clean_legs

SCALED = {"slug": "scaled", "label": "Scaled", "scaled": True}
REGS = [{"slug": r["slug"], "label": r["label"], "params": r["params"]} for r in REGIMES]
REGS.append(SCALED)

DATA_DIR = REPO_ROOT / "data" / "discovery_bet_1"

# Per-interval CSV catalogs. For each --interval the script picks the matching
# dict; crypto has long-history files for 1h and 15m, equities/metals only 1h.
ASSET_CATALOG_1H = {
    "BTC": "binance_btcusdt_1h_full_history.csv",
    "ETH": "binance_ethusdt_1h_full_history.csv",
    "BNB": "binance_bnbusdt_1h_full_history.csv",
    "ADA": "binance_adausdt_1h_full_history.csv",
    "XRP": "binance_xrpusdt_1h_full_history.csv",
    "TRX": "binance_trxusdt_1h_full_history.csv",
    "SOL": "binance_solusdt_1h_full_history.csv",
    "XAU": "oanda_xauusd_1h_last_12_months.csv",
    "XAG": "oanda_xagusd_1h_last_12_months.csv",
    "AAPL": "nasdaq_aapl_1h_last_12_months.csv",
    "MSFT": "nasdaq_msft_1h_last_12_months.csv",
    "NVDA": "nasdaq_nvda_1h_last_12_months.csv",
}
ASSET_CATALOG_15M = {
    "BTC": "binance_btcusdt_15m_full_history.csv",
    "ETH": "binance_ethusdt_15m_full_history.csv",
    "BNB": "binance_bnbusdt_15m_full_history.csv",
    "ADA": "binance_adausdt_15m_full_history.csv",
    "XRP": "binance_xrpusdt_15m_full_history.csv",
    "TRX": "binance_trxusdt_15m_full_history.csv",
    "SOL": "binance_solusdt_15m_full_history.csv",
}
ASSET_CATALOG_BY_INTERVAL = {"1h": ASSET_CATALOG_1H, "15m": ASSET_CATALOG_15M}
# Bars per "year" used purely for the loading-progress span estimate.
BARS_PER_YEAR = {"1h": 8760, "15m": 35040}

# Cohort edges in ATR units. Below 4 is impossible (detector floor at 2.0× and
# realised legs run higher); 16+ is the long tail.
COHORTS = [(4, 6), (6, 8), (8, 10), (10, 12), (12, 16), (16, 999)]


def load_csv(path: Path) -> list[Candle]:
    out: list[Candle] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Candle(row["source_timestamp"], float(row["open"]),
                              float(row["high"]), float(row["low"]),
                              float(row["close"]), float(row["volume"])))
    return out


def is_win(kind, r):
    return kind in ("scratch", "partial", "win") or (kind == "open" and r > 0)


def fib_price(parent: float, term: float, coeff: float) -> float:
    """In phoenix-fib coords coeff=1.0 is parent and coeff=0.0 is term.
    price = term + coeff*(parent - term)."""
    return term + coeff * (parent - term)


def reaches_after_term(candles, idx, leg, coeff) -> bool:
    """Did price reach fib level `coeff` between term_ts (exclusive) and the
    point where the swing gets extended back through term (= setup invalid)?

    Detector direction is "up"/"down" (NOT "long"/"short").
    "up"  leg: parent<term (price ran UP); retrace is a SHORT trade -- level
              sits below term, watch LOW; invalidation = HIGH > term.
    "down" leg: parent>term (price ran DOWN); retrace is a LONG trade -- level
              sits above term, watch HIGH; invalidation = LOW < term.
    """
    parent = leg["parent_price"]; term = leg["term_price"]
    level = fib_price(parent, term, coeff)
    j = idx[leg["term_ts"]] + 1
    if leg["direction"] == "up":
        while j < len(candles):
            c = candles[j]
            if c.low <= level:
                return True
            if c.high > term:
                return False
            j += 1
    else:  # "down"
        while j < len(candles):
            c = candles[j]
            if c.high >= level:
                return True
            if c.low < term:
                return False
            j += 1
    return False


def deepest_after_term(candles, idx, leg) -> float:
    """Deepest fib coefficient reached after term_ts (before the swing extends
    back through term). 0.0 = no retrace, 1.0 = full retrace back to parent.

    Detector direction is "up"/"down".
    "up"  leg (parent<term): retrace pushes LOW down toward parent.
    "down" leg (parent>term): retrace pushes HIGH up toward parent.
    """
    parent = leg["parent_price"]; term = leg["term_price"]
    denom = parent - term  # signed
    if denom == 0:
        return 0.0
    deepest = 0.0
    j = idx[leg["term_ts"]] + 1
    if leg["direction"] == "up":
        while j < len(candles):
            c = candles[j]
            coef = (c.low - term) / denom
            if coef > deepest:
                deepest = coef
            if c.high > term:
                return deepest
            j += 1
    else:  # "down"
        while j < len(candles):
            c = candles[j]
            coef = (c.high - term) / denom
            if coef > deepest:
                deepest = coef
            if c.low < term:
                return deepest
            j += 1
    return deepest


def analyze_asset(label, candles, mb, mult):
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    atr = calculate_atr14(candles)
    piv = detect_local_pivots(candles)
    legs_raw = [l for l in _clean_legs(candles, atr, piv, min_bars=mb, mult=mult)
                if l["term_ts"] in idx]

    # Compute per-leg metrics
    enriched = []
    for leg in legs_raw:
        atr_at_term = atr[idx[leg["term_ts"]]] or 1.0
        depth_atr = abs(leg["term_price"] - leg["parent_price"]) / atr_at_term
        # what was the deepest fib coefficient reached after term
        deepest = deepest_after_term(candles, idx, leg)
        # discrete reach flags
        r786 = reaches_after_term(candles, idx, leg, 0.786)
        r882 = reaches_after_term(candles, idx, leg, 0.882)
        r941 = reaches_after_term(candles, idx, leg, 0.941)
        # cohort
        coh = next(((lo, hi) for lo, hi in COHORTS if lo <= depth_atr < hi), None)
        # regime scores
        scores = {}
        for reg in REGS:
            res = run_regime(candles, idx, leg, reg)
            kind = KIND.get(res["status"], "open")
            scores[reg["slug"]] = (kind, res["r"])
        enriched.append({
            "leg": leg, "depth_atr": depth_atr, "deepest": deepest,
            "r786": r786, "r882": r882, "r941": r941,
            "cohort": coh, "scores": scores,
        })
    return enriched, candles, idx


def percentile(xs, p):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo = int(k); hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def print_depth_distribution(rows):
    """Side-by-side per-asset distribution table. The point: if two assets
    show *identical* p25/p50/p75 + identical %reach, we should see it here."""
    print("=" * 84)
    print("DEPTH DISTRIBUTION -- retrace depth reached after term_ts (fib coeff)")
    print("  coeff=0.0 means no retrace; 1.0 means broke parent.")
    print()
    print(f"{'asset':<8}{'N':>5}  {'p25':>6}{'p50':>6}{'p75':>6}  "
          f"{'%>=0.786':>9}{'%>=0.882':>9}{'%>=0.941':>9}")
    for label, enriched in rows:
        depths = [r["deepest"] for r in enriched]
        n = len(depths)
        if n == 0:
            print(f"{label:<8}{0:>5}"); continue
        p25, p50, p75 = percentile(depths, 0.25), percentile(depths, 0.5), percentile(depths, 0.75)
        p786 = sum(1 for r in enriched if r["r786"]) / n * 100
        p882 = sum(1 for r in enriched if r["r882"]) / n * 100
        p941 = sum(1 for r in enriched if r["r941"]) / n * 100
        print(f"{label:<8}{n:>5}  {p50:>6.3f}{p50:>6.3f}{p75:>6.3f}  "
              f"{p786:>8.1f}%{p882:>8.1f}%{p941:>8.1f}%")
        # Print actual p25/p50/p75 (fix the format above):
    print()


def print_depth_distribution_v2(rows):
    """Clean table -- p25/p50/p75 then %reach.  Same per-asset rows, side by side."""
    print("=" * 96)
    print("RETRACE DEPTH DISTRIBUTION (post-terminal, fib coeff: 0=term, 1=parent)")
    print()
    print(f"  {'asset':<8}{'N':>6}  {'p25':>7}{'p50':>7}{'p75':>7}  "
          f"{'%reach 0.786':>13}{'%reach 0.882':>13}{'%reach 0.941':>13}")
    for label, enriched in rows:
        n = len(enriched)
        if n == 0:
            print(f"  {label:<8}{n:>6}  (no setups)"); continue
        depths = [r["deepest"] for r in enriched]
        p25 = percentile(depths, 0.25)
        p50 = percentile(depths, 0.5)
        p75 = percentile(depths, 0.75)
        p786 = sum(1 for r in enriched if r["r786"]) / n * 100
        p882 = sum(1 for r in enriched if r["r882"]) / n * 100
        p941 = sum(1 for r in enriched if r["r941"]) / n * 100
        print(f"  {label:<8}{n:>6}  {p25:>7.3f}{p50:>7.3f}{p75:>7.3f}  "
              f"{p786:>12.1f}%{p882:>12.1f}%{p941:>12.1f}%")
    print()


def print_atr_depth_distribution(rows):
    """ATR-depth of the LEG (how big was the swing in volatility units)."""
    print("=" * 84)
    print("LEG DEPTH IN ATR UNITS  (size of the parent->term move in hourly ATR14)")
    print()
    print(f"  {'asset':<8}{'N':>6}  {'p25':>7}{'p50':>7}{'p75':>7}{'mean':>7}{'max':>7}")
    for label, enriched in rows:
        n = len(enriched)
        if n == 0:
            print(f"  {label:<8}{n:>6}  (no setups)"); continue
        atrs = [r["depth_atr"] for r in enriched]
        p25 = percentile(atrs, 0.25)
        p50 = percentile(atrs, 0.5)
        p75 = percentile(atrs, 0.75)
        mean = sum(atrs) / n
        mx = max(atrs)
        print(f"  {label:<8}{n:>6}  {p25:>7.2f}{p50:>7.2f}{p75:>7.2f}{mean:>7.2f}{mx:>7.1f}")
    print()


def print_cohort_table(label, enriched):
    """Per-asset cohort table: cohort × regime."""
    print(f"  --- {label}: net R by leg-depth cohort × regime ---")
    # header
    head = f"  {'cohort (ATR)':<14}{'N':>5}"
    for reg in REGS:
        head += f"  {reg['label'][:8]:>8}{'win%':>5}{'avgR':>7}{'totR':>7}"
    print(head)
    # rows
    by_cohort: dict[tuple[int,int], list] = defaultdict(list)
    for r in enriched:
        if r["cohort"]:
            by_cohort[r["cohort"]].append(r)
    for lo, hi in COHORTS:
        bucket = by_cohort[(lo, hi)]
        n = len(bucket)
        if n == 0:
            continue
        cohort_label = f"{lo}-{hi}" if hi < 999 else f"{lo}+"
        line = f"  {cohort_label:<14}{n:>5}"
        for reg in REGS:
            slug = reg["slug"]
            scores = [b["scores"][slug] for b in bucket]
            trig = [(k, rv) for (k, rv) in scores if k != "shrug"]
            if not trig:
                line += f"  {'-':>8}{'-':>5}{'-':>7}{'-':>7}"
                continue
            nt = len(trig)
            wins = sum(1 for (k, rv) in trig if is_win(k, rv))
            tot = sum(rv for (_, rv) in trig)
            avgR = tot / nt
            line += f"  {f'N={nt}':>8}{int(wins/nt*100):>5}{avgR:>+7.2f}{tot:>+7.1f}"
        print(line)
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", nargs="*", default=None)
    ap.add_argument("--interval", choices=list(ASSET_CATALOG_BY_INTERVAL.keys()), default="1h")
    ap.add_argument("--min-bars", type=int, default=6)
    ap.add_argument("--mult", type=float, default=2.0)
    args = ap.parse_args()

    catalog = ASSET_CATALOG_BY_INTERVAL[args.interval]
    bars_per_year = BARS_PER_YEAR[args.interval]
    requested = args.assets or list(catalog.keys())
    print(f"cohort analysis  (interval={args.interval}, detector {args.min_bars}c / "
          f"{args.mult:.1f}x ATR, gross R)\n")

    rows = []
    for label in requested:
        if label not in catalog:
            print(f"[skip] {label}: not in {args.interval} catalog"); continue
        path = DATA_DIR / catalog[label]
        if not path.exists():
            print(f"[skip] {label}: {path.name} not found"); continue
        candles = load_csv(path)
        years_span = len(candles) / bars_per_year
        print(f"  loading {label} ({years_span:.1f}y, {len(candles)} bars)...", flush=True)
        enriched, _, _ = analyze_asset(label, candles, args.min_bars, args.mult)
        rows.append((label, enriched))
    print()

    # Job 1: depth distribution side by side (verify the "identical" claim)
    print_depth_distribution_v2(rows)
    print_atr_depth_distribution(rows)

    # Job 2: cohort × regime per asset
    print("=" * 96)
    print("NET R BY LEG-DEPTH COHORT (×ATR) × REGIME, PER ASSET (gross R)")
    print()
    for label, enriched in rows:
        print_cohort_table(label, enriched)

    # Cross-asset cohort roll-up: pool all assets, depth cohort × regime
    print("=" * 96)
    print("CROSS-ASSET POOLED: leg-depth cohort × regime (all assets combined)")
    print()
    pooled = [r for _, e in rows for r in e]
    print_cohort_table("POOLED", pooled)


if __name__ == "__main__":
    main()
