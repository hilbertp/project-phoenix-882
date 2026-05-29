#!/usr/bin/env python
"""Monthly R per asset x per sniper entry.

For every long-history crypto asset (BTC, ETH, BNB, ADA, XRP, TRX, SOL) on
15m at 6c/2.0x ATR, score every triggered setup against all four regimes
(0.941, 0.882, 0.786, scaled 786/882/941) and bucket the outcomes by
calendar month.

Output:
  artifacts/discovery_bet_1/monthly_r_per_asset_entry.csv  (long format)
    columns: year_month, asset, entry, n_triggered, wins, losses, total_r,
             avg_r, total_r_net_taker, avg_r_net_taker
  artifacts/discovery_bet_1/monthly_r_per_asset_entry.gross.tsv  (wide pivot,
             rows = month, columns = asset_entry, values = total R)

Printed: per-asset rollup (across all months) and a recent-12-month table.

Fees: net columns use Hyperliquid taker round-trip (0.09%) computed per-trade
from each trade's actual entry-to-SL distance as a fraction of entry price.
"""
from __future__ import annotations
import csv, sys
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
ENTRY_LABELS = {"x941": "0.941", "x882": "0.882", "x786": "0.786", "scaled": "scaled"}

DATA_DIR = REPO_ROOT / "data" / "discovery_bet_1"
OUT_DIR = REPO_ROOT / "artifacts" / "discovery_bet_1"

ASSETS = {
    "BTC": "binance_btcusdt_15m_full_history.csv",
    "ETH": "binance_ethusdt_15m_full_history.csv",
    "BNB": "binance_bnbusdt_15m_full_history.csv",
    "ADA": "binance_adausdt_15m_full_history.csv",
    "XRP": "binance_xrpusdt_15m_full_history.csv",
    "TRX": "binance_trxusdt_15m_full_history.csv",
    "SOL": "binance_solusdt_15m_full_history.csv",
}
HL_TAKER_RT = 0.0009

# Entry coeffs per regime, for fee-burden math
ENTRY_COEFF = {"x941": 0.941, "x882": 0.882, "x786": 0.786}
# For scaled, fee burden is more complex; approximate with the average entry
# coeff (50% at 0.786, 25% at 0.882, 25% at 0.941 -> blended 0.84) and the
# 1.05 SL distance.
SCALED_BLENDED_ENTRY = 0.5 * 0.786 + 0.25 * 0.882 + 0.25 * 0.941


def load_csv(path):
    out = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Candle(row["source_timestamp"], float(row["open"]),
                              float(row["high"]), float(row["low"]),
                              float(row["close"]), float(row["volume"])))
    return out


def fee_per_r(parent_price, term_price, entry_coeff):
    """Fee burden per round-trip trade, expressed as a fraction of 1R.
    Both sides pay HL_TAKER_RT/2; total = HL_TAKER_RT * notional. As fraction
    of 1R = HL_TAKER_RT / (entry_to_SL_distance / entry_price)."""
    entry = term_price + entry_coeff * (parent_price - term_price)
    sl = term_price + 1.05 * (parent_price - term_price)
    e2sl = abs(entry - sl) / entry if entry else 0
    return HL_TAKER_RT / e2sl if e2sl else 0


def is_winning(status):
    return status in ("tp3_full", "tp2_then_scratch", "tp1_then_scratch")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    long_rows = []
    # bucket structure: (year_month, asset, entry_slug) -> {"n":int, "wins":int, "losses":int, "tot_r":float, "tot_fee_r":float}
    bucket = defaultdict(lambda: {"n": 0, "wins": 0, "losses": 0,
                                  "tot_r": 0.0, "tot_fee_r": 0.0})

    for asset, fname in ASSETS.items():
        path = DATA_DIR / fname
        if not path.exists():
            print(f"[skip] {asset}: {fname} not found"); continue
        print(f"loading {asset} ({fname})...", flush=True)
        candles = load_csv(path)
        idx = {c.source_timestamp: i for i, c in enumerate(candles)}
        atr = calculate_atr14(candles)
        piv = detect_local_pivots(candles)
        legs = [l for l in _clean_legs(candles, atr, piv, min_bars=6, mult=2.0)
                if l["term_ts"] in idx]
        print(f"  {len(legs):,} legs", flush=True)

        for n, leg in enumerate(legs, start=1):
            for reg in REGS:
                slug = reg["slug"]
                res = run_regime(candles, idx, leg, reg)
                status = res["status"]
                if status in ("no_trigger", "no_entry", "degenerate", "shrug"):
                    continue
                rval = res["r"]
                # entry timestamp from events
                ev_ts = res["events"][0][1] if res["events"] else leg["term_ts"]
                ym = ev_ts[:7]  # YYYY-MM

                # fee for this trade
                if slug == "scaled":
                    fr = fee_per_r(leg["parent_price"], leg["term_price"],
                                   SCALED_BLENDED_ENTRY)
                else:
                    fr = fee_per_r(leg["parent_price"], leg["term_price"],
                                   ENTRY_COEFF[slug])

                k = (ym, asset, slug)
                b = bucket[k]
                b["n"] += 1
                b["tot_r"] += rval
                b["tot_fee_r"] += fr
                if status == "wipeout":
                    b["losses"] += 1
                if is_winning(status):
                    b["wins"] += 1
            if n % 5000 == 0:
                print(f"    scored {n:,}/{len(legs):,}", flush=True)

    # Materialize long-format rows
    for (ym, asset, slug), b in sorted(bucket.items()):
        tot_r = b["tot_r"]
        net_r = tot_r - b["tot_fee_r"]
        long_rows.append({
            "year_month": ym, "asset": asset, "entry": ENTRY_LABELS[slug],
            "n_triggered": b["n"], "wins": b["wins"], "losses": b["losses"],
            "total_r_gross": round(tot_r, 3),
            "avg_r_gross": round(tot_r / b["n"], 4) if b["n"] else 0,
            "total_r_net_taker": round(net_r, 3),
            "avg_r_net_taker": round(net_r / b["n"], 4) if b["n"] else 0,
        })

    # Long-format CSV
    long_path = OUT_DIR / "monthly_r_per_asset_entry.csv"
    with long_path.open("w", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(long_rows[0].keys()))
        w.writeheader()
        for r in long_rows:
            w.writerow(r)
    print(f"\nWROTE {long_path}  ({len(long_rows):,} rows)")

    # Wide pivot: rows = month, cols = asset_entry, values = gross total_r
    pivot = defaultdict(dict)
    for r in long_rows:
        pivot[r["year_month"]][f"{r['asset']}_{r['entry']}"] = r["total_r_gross"]
    cols = sorted({k for v in pivot.values() for k in v.keys()})
    wide_path = OUT_DIR / "monthly_r_per_asset_entry.gross.tsv"
    with wide_path.open("w", encoding="utf-8") as fh:
        fh.write("year_month\t" + "\t".join(cols) + "\n")
        for ym in sorted(pivot):
            row = [f"{pivot[ym].get(c, 0):+.1f}" if pivot[ym].get(c) is not None
                   else "" for c in cols]
            fh.write(ym + "\t" + "\t".join(row) + "\n")
    print(f"WROTE {wide_path}  ({len(pivot)} months x {len(cols)} asset/entry cols)")

    # Per-asset cross-time rollup (printed)
    print(f"\n{'='*80}\nPER-ASSET ROLLUP (gross R across all months)\n{'='*80}")
    print(f"  {'asset':<6}{'entry':<8}{'months':>8}{'N trades':>10}{'win%':>7}"
          f"{'totR':>10}{'avgR':>9}{'netR/trade':>13}")
    by_ae = defaultdict(lambda: {"months": set(), "n": 0, "wins": 0, "tr": 0.0, "fr": 0.0})
    for r in long_rows:
        k = (r["asset"], r["entry"])
        b = by_ae[k]
        b["months"].add(r["year_month"])
        b["n"] += r["n_triggered"]
        b["wins"] += r["wins"]
        b["tr"] += r["total_r_gross"]
        # back out fee burden: total_fee = total_r_gross - total_r_net_taker
        b["fr"] += r["total_r_gross"] - r["total_r_net_taker"]
    for (asset, entry), b in sorted(by_ae.items()):
        m = len(b["months"]); n = b["n"]
        if n == 0: continue
        wr = b["wins"] / n * 100
        avg = b["tr"] / n
        net_avg = (b["tr"] - b["fr"]) / n
        print(f"  {asset:<6}{entry:<8}{m:>8}{n:>10}{wr:>6.1f}%"
              f"{b['tr']:>+10.1f}{avg:>+9.3f}{net_avg:>+13.3f}")

    # Recent 12 months table (gross R) -- compact view
    months = sorted({r["year_month"] for r in long_rows})
    recent = months[-12:]
    print(f"\n{'='*80}\nLAST 12 MONTHS, gross total R per asset x entry\n{'='*80}")
    for asset in ASSETS:
        print(f"\n  {asset}")
        print(f"  {'month':<10}" + "".join(f"{ENTRY_LABELS[s]:>9}" for s in ("x941", "x882", "x786", "scaled")))
        for ym in recent:
            cells = []
            for s in ("x941", "x882", "x786", "scaled"):
                v = bucket.get((ym, asset, s))
                cells.append(f"{v['tot_r']:>+9.1f}" if v else f"{'-':>9}")
            print(f"  {ym:<10}" + "".join(cells))


if __name__ == "__main__":
    main()
