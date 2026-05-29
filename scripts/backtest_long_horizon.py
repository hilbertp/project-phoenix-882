#!/usr/bin/env python
"""Long-horizon BTC backtest: years of 1H data scored across every regime, with
year, month-of-year (seasonality), and market-regime (bull/bear/range) bucketing.

Bypasses the worker's 12-month candle contract -- reads the OHLCV CSV directly
and feeds Candle objects to the detector + executor.

Usage: backtest_long_horizon.py [csv_path] [min_bars] [mult]
       defaults: data/discovery_bet_1/binance_btcusdt_1h_full_history.csv, 6, 2.0
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


def load_csv(csv_path: Path) -> list[Candle]:
    out: list[Candle] = []
    with csv_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Candle(
                source_timestamp=row["source_timestamp"],
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
                volume=float(row["volume"]),
            ))
    return out


def is_win(kind, r): return kind in ("scratch", "partial", "win") or (kind == "open" and r > 0)


def main() -> None:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        REPO_ROOT / "data/discovery_bet_1/binance_btcusdt_1h_full_history.csv")
    mb = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    mult = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0

    candles = load_csv(csv_path)
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    print(f"loaded {len(candles)} candles  "
          f"{candles[0].source_timestamp} -> {candles[-1].source_timestamp}  "
          f"({(len(candles)/8760):.1f} years)")
    atr = calculate_atr14(candles)
    piv = detect_local_pivots(candles)
    legs = [leg for leg in _clean_legs(candles, atr, piv, min_bars=mb, mult=mult)
            if leg["term_ts"] in idx]
    print(f"detected {len(legs)} setups at {mb}c / {mult:.1f}x ATR\n")

    # 1) overall + per-regime summary (gross R)
    per_reg = {}
    print(f"{'regime':<22}{'N':>5}{'win%':>6}{'loss%':>6}{'totR':>9}{'avgR':>9}")
    for reg in REGS:
        rows = []
        for leg in legs:
            res = run_regime(candles, idx, leg, reg)
            entry_ts = res["events"][0][1] if res["events"] else leg["term_ts"]
            kind = KIND.get(res["status"], "open")
            rows.append({"ts": entry_ts, "kind": kind, "r": res["r"], "dir": leg["direction"]})
        trig = [r for r in rows if r["kind"] != "shrug"]
        n = len(trig)
        w = sum(1 for r in trig if is_win(r["kind"], r["r"]))
        l = sum(1 for r in trig if r["kind"] == "loss")
        tot = sum(r["r"] for r in trig)
        print(f"{reg['label']:<22}{n:>5}{w/n*100:>5.0f}%{l/n*100:>5.0f}%{tot:>+9.1f}{tot/n:>+9.3f}")
        per_reg[reg["slug"]] = rows

    # Drill-down focus regimes: the deep 0.941 (headline) and scaled (robust)
    for focus_slug, focus_label in [("x941", "0.941 ENTRY"), ("scaled", "SCALED")]:
        rows = per_reg[focus_slug]
        print(f"\n========== {focus_label} -- BY YEAR ==========")
        by_year = defaultdict(lambda: [0, 0.0, 0])  # n, totR, wins
        for r in rows:
            if r["kind"] == "shrug": continue
            y = r["ts"][:4]
            by_year[y][0] += 1; by_year[y][1] += r["r"]
            if is_win(r["kind"], r["r"]): by_year[y][2] += 1
        # also: BTC price change per year, for regime context
        by_year_close = defaultdict(list)
        for c in candles: by_year_close[c.source_timestamp[:4]].append(c.close)
        print(f"{'year':<6}{'BTC %':>8}{'N':>5}{'win%':>6}{'totR':>9}{'avgR':>9}")
        for y in sorted(by_year):
            n, tot, w = by_year[y]
            px = by_year_close[y]
            chg = (px[-1] / px[0] - 1) * 100 if px else 0
            print(f"{y:<6}{chg:>+7.0f}%{n:>5}{w/n*100:>5.0f}%{tot:>+9.1f}{tot/n:>+9.3f}")

        print(f"\n----- {focus_label} -- SEASONALITY (by month-of-year, all years pooled) -----")
        by_moy = defaultdict(lambda: [0, 0.0])
        for r in rows:
            if r["kind"] == "shrug": continue
            m = int(r["ts"][5:7])
            by_moy[m][0] += 1; by_moy[m][1] += r["r"]
        print(f"{'mon':<5}{'N':>5}{'totR':>9}{'avgR':>9}")
        for m in range(1, 13):
            n, tot = by_moy[m]
            if n: print(f"{m:<5}{n:>5}{tot:>+9.1f}{tot/n:>+9.3f}")

        print(f"\n----- {focus_label} -- BY MARKET REGIME (per-month classification) -----")
        # classify each calendar month by BTC's % change that month, then bucket trades
        by_ym = defaultdict(list)
        for c in candles: by_ym[c.source_timestamp[:7]].append(c.close)
        month_chg = {ym: (px[-1] / px[0] - 1) * 100 if px else 0 for ym, px in by_ym.items()}
        bucket = {"bull (>+10%)": [0, 0.0], "bear (<-10%)": [0, 0.0], "range (-10..+10%)": [0, 0.0]}
        for r in rows:
            if r["kind"] == "shrug": continue
            ym = r["ts"][:7]; chg = month_chg.get(ym, 0)
            k = "bull (>+10%)" if chg > 10 else "bear (<-10%)" if chg < -10 else "range (-10..+10%)"
            bucket[k][0] += 1; bucket[k][1] += r["r"]
        for k, (n, tot) in bucket.items():
            if n: print(f"  {k:<22} N={n:>4}  totR={tot:>+7.1f}  avgR={tot/n:+.3f}")

        # best / worst calendar months (top 5 and bottom 5)
        by_month_full = defaultdict(lambda: [0, 0.0])
        for r in rows:
            if r["kind"] == "shrug": continue
            ym = r["ts"][:7]
            by_month_full[ym][0] += 1; by_month_full[ym][1] += r["r"]
        ranked = sorted(by_month_full.items(), key=lambda kv: kv[1][1])
        print(f"\n----- {focus_label} -- worst 5 months -----")
        for ym, (n, tot) in ranked[:5]: print(f"  {ym}  N={n:>3}  totR={tot:+6.1f}  chg={month_chg.get(ym,0):+5.0f}%")
        print(f"----- {focus_label} -- best 5 months -----")
        for ym, (n, tot) in ranked[-5:][::-1]: print(f"  {ym}  N={n:>3}  totR={tot:+6.1f}  chg={month_chg.get(ym,0):+5.0f}%")


if __name__ == "__main__":
    main()
