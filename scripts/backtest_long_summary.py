#!/usr/bin/env python
"""Compact cross-asset long-horizon summary.

For every asset whose binance_<symbol>_1h_full_history.csv exists, scores all
regimes (gross), prints a tight per-asset block (headline totals + 0.941 by
year + market-regime split + negative-month count + worst-3 months), and ends
with a cross-asset year-by-year avg-R heatmap for the 0.941 entry.

Usage: backtest_long_summary.py [min_bars] [mult]   (defaults 6 / 2.0)
"""
from __future__ import annotations

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

ASSETS = [
    ("BTC", "binance_btcusdt_1h_full_history.csv"),
    ("ETH", "binance_ethusdt_1h_full_history.csv"),
    ("BNB", "binance_bnbusdt_1h_full_history.csv"),
    ("ADA", "binance_adausdt_1h_full_history.csv"),
    ("XRP", "binance_xrpusdt_1h_full_history.csv"),
    ("TRX", "binance_trxusdt_1h_full_history.csv"),
    ("SOL", "binance_solusdt_1h_full_history.csv"),
]
DATA_DIR = REPO_ROOT / "data" / "discovery_bet_1"


def load_csv(path: Path) -> list[Candle]:
    out: list[Candle] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Candle(row["source_timestamp"], float(row["open"]),
                              float(row["high"]), float(row["low"]),
                              float(row["close"]), float(row["volume"])))
    return out


def is_win(kind, r): return kind in ("scratch", "partial", "win") or (kind == "open" and r > 0)


def analyze(candles, idx, atr, piv, mb, mult):
    legs = [l for l in _clean_legs(candles, atr, piv, min_bars=mb, mult=mult) if l["term_ts"] in idx]
    out = {}
    for reg in REGS:
        rows = []
        for leg in legs:
            res = run_regime(candles, idx, leg, reg)
            ts = res["events"][0][1] if res["events"] else leg["term_ts"]
            kind = KIND.get(res["status"], "open")
            rows.append((ts, kind, res["r"], leg["direction"]))
        out[reg["slug"]] = rows
    return len(legs), out


def main() -> None:
    mb = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    mult = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
    print(f"long-horizon summary  (detector {mb}c / {mult:.1f}x ATR, gross R, no fees)\n")

    year_rows: dict[str, dict[str, float]] = defaultdict(dict)
    for label, fname in ASSETS:
        path = DATA_DIR / fname
        if not path.exists():
            print(f"[skip] {label}: {fname} not found\n"); continue
        candles = load_csv(path)
        idx = {c.source_timestamp: i for i, c in enumerate(candles)}
        atr = calculate_atr14(candles); piv = detect_local_pivots(candles)
        n_legs, by_reg = analyze(candles, idx, atr, piv, mb, mult)
        years_span = len(candles) / 8760

        print(f"========== {label}  ({years_span:.1f} years, {n_legs} setups) ==========")
        # headline totals across regimes
        for reg in REGS:
            rs = [r for r in by_reg[reg["slug"]] if r[1] != "shrug"]
            if not rs: continue
            w = sum(1 for r in rs if is_win(r[1], r[2]))
            losses = sum(1 for r in rs if r[1] == "loss")
            tot = sum(r[2] for r in rs)
            print(f"  {reg['label']:<20}  N={len(rs):>4}  win={w/len(rs)*100:>3.0f}%  loss={losses/len(rs)*100:>3.0f}%  totR={tot:>+7.1f}  avgR={tot/len(rs):>+.3f}")

        # 0.941 by year + heatmap row
        rows = by_reg["x941"]
        by_year = defaultdict(lambda: [0, 0.0, 0])
        by_year_close = defaultdict(list)
        for c in candles: by_year_close[c.source_timestamp[:4]].append(c.close)
        for ts, kind, r, _ in rows:
            if kind == "shrug": continue
            y = ts[:4]
            by_year[y][0] += 1; by_year[y][1] += r
            if is_win(kind, r): by_year[y][2] += 1
        print(f"  --- 0.941 by year ---")
        print(f"  {'year':<6}{'asset%':>9}{'N':>5}{'win%':>6}{'totR':>9}{'avgR':>8}")
        for y in sorted(by_year):
            n, tot, w = by_year[y]
            px = by_year_close[y]
            chg = (px[-1] / px[0] - 1) * 100 if px else 0
            print(f"  {y:<6}{chg:>+8.0f}%{n:>5}{w/n*100:>5.0f}%{tot:>+9.1f}{tot/n:>+8.3f}")
            year_rows[y][label] = tot / n if n else None

        # market regime + negative months
        by_ym = defaultdict(list)
        for c in candles: by_ym[c.source_timestamp[:7]].append(c.close)
        month_chg = {ym: (p[-1] / p[0] - 1) * 100 if p else 0 for ym, p in by_ym.items()}
        bucket = {"bull": [0, 0.0], "bear": [0, 0.0], "range": [0, 0.0]}
        by_m = defaultdict(lambda: [0, 0.0])
        for ts, kind, r, _ in rows:
            if kind == "shrug": continue
            ym = ts[:7]; chg = month_chg.get(ym, 0)
            k = "bull" if chg > 10 else "bear" if chg < -10 else "range"
            bucket[k][0] += 1; bucket[k][1] += r
            by_m[ym][0] += 1; by_m[ym][1] += r
        neg = [(ym, n, tr) for ym, (n, tr) in by_m.items() if tr < 0]
        n_months = len(by_m)
        worst = sorted(neg, key=lambda x: x[2])[:3]
        print(f"  --- 0.941 regime split & tail ---")
        for k in ("bull", "bear", "range"):
            n, tot = bucket[k]
            if n: print(f"  {k:<6} N={n:>4}  avgR={tot/n:+.3f}")
        print(f"  neg months: {len(neg)}/{n_months} ({len(neg)/n_months*100:.0f}%)")
        for ym, n, tr in worst: print(f"    worst: {ym}  N={n:>3}  totR={tr:+5.1f}")
        print()

    # cross-asset year × asset heatmap (0.941 avg R/trade)
    cols = [a[0] for a in ASSETS if (DATA_DIR / a[1]).exists()]
    print("=" * 60)
    print(f"0.941 avg R/trade -- year x asset  (gross)")
    print(f"{'year':<6}" + "".join(f"{c:>8}" for c in cols))
    for y in sorted(year_rows):
        row = year_rows[y]
        print(f"{y:<6}" + "".join(
            (f"{row.get(c):+8.2f}" if row.get(c) is not None else f"{'-':>8}") for c in cols
        ))


if __name__ == "__main__":
    main()
