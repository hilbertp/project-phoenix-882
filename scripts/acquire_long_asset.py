#!/usr/bin/env python
"""Acquire the full Binance USDT-spot history at a given interval (no auth).

Generalized from acquire_long_btc.py: chunks through /klines (1000 bars/call),
walks from 2017-08 forward, and skips empty pre-listing windows automatically.

Usage:  acquire_long_asset.py SYMBOL [INTERVAL]
        e.g. acquire_long_asset.py ETHUSDT       -> 1h (default)
             acquire_long_asset.py ETHUSDT 15m   -> 15-minute bars
Output: data/discovery_bet_1/binance_<symbol_lower>_<interval>_full_history.csv
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "discovery_bet_1"
URL = "https://api.binance.com/api/v3/klines"
START = datetime(2017, 8, 17, tzinfo=timezone.utc)
COLUMNS = ["source_timestamp", "open", "high", "low", "close", "volume"]

# Binance interval -> bar duration in minutes
INTERVALS = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "12h": 720,
    "1d": 1440,
}


def fetch_chunk(symbol: str, interval: str, start_ms: int, end_ms: int):
    params = (f"?symbol={symbol}&interval={interval}"
              f"&startTime={start_ms}&endTime={end_ms}&limit=1000")
    with urllib.request.urlopen(URL + params, timeout=30) as resp:
        return json.loads(resp.read())


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: acquire_long_asset.py SYMBOL [INTERVAL]"); sys.exit(2)
    symbol = sys.argv[1].upper()
    interval = sys.argv[2] if len(sys.argv) > 2 else "1h"
    if interval not in INTERVALS:
        print(f"unsupported interval {interval!r}; pick from {list(INTERVALS)}")
        sys.exit(2)
    bar_minutes = INTERVALS[interval]
    chunk_span = timedelta(minutes=bar_minutes * 1000)  # 1000 bars per call
    advance_after_chunk = timedelta(minutes=bar_minutes)
    # Empty-window cap: roughly ~15 years' worth of empty chunks
    empty_cap = max(130, int(15 * 365 * 1440 / (bar_minutes * 1000)))
    out = DATA_DIR / f"binance_{symbol.lower()}_{interval}_full_history.csv"

    rows: list[str] = [",".join(COLUMNS)]
    cur = START
    end = datetime.now(timezone.utc)
    total = 0
    chunk_n = 0
    consecutive_empty = 0
    while cur < end:
        chunk_start = int(cur.timestamp() * 1000)
        chunk_end = int((cur + chunk_span).timestamp() * 1000)
        try:
            data = fetch_chunk(symbol, interval, chunk_start, chunk_end)
        except Exception as exc:
            print(f"FETCH_ERROR {symbol} {interval} at {cur.date()}: {exc}", file=sys.stderr)
            break
        if not data:
            cur = cur + chunk_span
            consecutive_empty += 1
            if consecutive_empty > empty_cap:
                print(f"NO_DATA {symbol} after {consecutive_empty} empty chunks"); break
            continue
        consecutive_empty = 0
        for d in data:
            ts = datetime.fromtimestamp(d[0] / 1000, tz=timezone.utc)
            rows.append(f"{ts.strftime('%Y-%m-%dT%H:%M:%S')},"
                        f"{d[1]},{d[2]},{d[3]},{d[4]},{d[5]}")
            total += 1
        cur = datetime.fromtimestamp(data[-1][0] / 1000, tz=timezone.utc) + advance_after_chunk
        chunk_n += 1
        if chunk_n % 20 == 0:
            print(f"  {symbol} {interval} chunk {chunk_n}: {total} bars, at {cur.date()}", flush=True)
        time.sleep(0.1)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    if total:
        first = rows[1].split(",")[0]; last = rows[-1].split(",")[0]
        days = (datetime.fromisoformat(last) - datetime.fromisoformat(first)).days
        print(f"WROTE {out}  symbol={symbol}  interval={interval}  "
              f"rows={total}  span={days} days ({days/365.25:.1f} years)")
    else:
        print(f"NO_DATA {symbol} {interval}: nothing written")


if __name__ == "__main__":
    main()
