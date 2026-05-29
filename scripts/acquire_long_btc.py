#!/usr/bin/env python
"""Acquire the full BTCUSDT 1H history from Binance public REST (~9 years).

tvDatafeed's guest cap (~12k bars / 1.4 years) is too tight for long-horizon
backtests, so this script chunks through Binance's public /klines endpoint
(1000 bars per call, no auth, no new deps). Output is a plain OHLCV CSV with
the same columns as the worker contract; the 12-month provenance/window check
in apps.worker.discovery_bet_1.candle_input does NOT apply here -- long-horizon
backtest scripts construct Candle objects directly.

Output: data/discovery_bet_1/binance_btcusdt_1h_full_history.csv
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "data" / "discovery_bet_1" / "binance_btcusdt_1h_full_history.csv"
URL = "https://api.binance.com/api/v3/klines"
START = datetime(2017, 8, 17, tzinfo=timezone.utc)   # Binance BTCUSDT spot listing
COLUMNS = ["source_timestamp", "open", "high", "low", "close", "volume"]


def fetch_chunk(start_ms: int, end_ms: int):
    params = (f"?symbol=BTCUSDT&interval=1h"
              f"&startTime={start_ms}&endTime={end_ms}&limit=1000")
    with urllib.request.urlopen(URL + params, timeout=30) as resp:
        return json.loads(resp.read())


def main() -> None:
    rows: list[str] = [",".join(COLUMNS)]
    cur = START
    end = datetime.now(timezone.utc)
    total = 0
    chunk_n = 0
    while cur < end:
        chunk_start = int(cur.timestamp() * 1000)
        chunk_end = int((cur + timedelta(hours=1000)).timestamp() * 1000)
        try:
            data = fetch_chunk(chunk_start, chunk_end)
        except Exception as exc:
            print(f"FETCH_ERROR at {cur.date()}: {exc}", file=sys.stderr)
            break
        if not data:
            cur = cur + timedelta(hours=1000)   # gap, skip ahead
            continue
        for d in data:
            ts = datetime.fromtimestamp(d[0] / 1000, tz=timezone.utc)
            rows.append(f"{ts.strftime('%Y-%m-%dT%H:%M:%S')},"
                        f"{d[1]},{d[2]},{d[3]},{d[4]},{d[5]}")
            total += 1
        cur = datetime.fromtimestamp(data[-1][0] / 1000, tz=timezone.utc) + timedelta(hours=1)
        chunk_n += 1
        if chunk_n % 10 == 0:
            print(f"  chunk {chunk_n}: {total} bars, at {cur.date()}")
        time.sleep(0.1)   # polite to the public endpoint
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(rows) + "\n", encoding="utf-8")
    span = (cur - START).days
    print(f"WROTE {OUT}  rows={total}  span~{span} days ({span/365.25:.1f} years)")


if __name__ == "__main__":
    main()
