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


def fetch_chunk_retry(symbol, interval, start_ms, end_ms, attempts=5):
    """fetch_chunk with exponential backoff. A transient network blip or a
    Binance 429 rate-limit must NOT abort the whole multi-year walk -- that's
    what used to truncate the history mid-fetch and clobber the good CSV."""
    last_exc = None
    for attempt in range(attempts):
        try:
            return fetch_chunk(symbol, interval, start_ms, end_ms)
        except Exception as exc:  # noqa: BLE001 - network errors are varied
            last_exc = exc
            wait = 1.5 * (2 ** attempt)  # 1.5, 3, 6, 12, 24s
            print(f"  retry {attempt + 1}/{attempts} after {wait:.0f}s "
                  f"({exc})", file=sys.stderr, flush=True)
            time.sleep(wait)
    raise last_exc


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
    fetch_incomplete = False
    while cur < end:
        chunk_start = int(cur.timestamp() * 1000)
        chunk_end = int((cur + chunk_span).timestamp() * 1000)
        try:
            data = fetch_chunk_retry(symbol, interval, chunk_start, chunk_end)
        except Exception as exc:
            # Even retries exhausted -> mark the fetch incomplete so the write
            # step refuses to clobber a more-complete existing file.
            print(f"FETCH_ERROR {symbol} {interval} at {cur.date()}: {exc}", file=sys.stderr)
            fetch_incomplete = True
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
    if not total:
        print(f"NO_DATA {symbol} {interval}: nothing written")
        return

    new_last = rows[-1].split(",")[0]  # last timestamp we just fetched

    # ANTI-CLOBBER GUARD: never replace a more-complete existing history with a
    # shorter one. If the fetch ended early (FETCH_ERROR) and the new data does
    # NOT reach at least as far as the file already on disk, KEEP the old file.
    # This is the bug that wiped 77k rows (-> 2026) down to 34k (-> 2021) on a
    # mid-fetch network blip and made the backtest non-reproducible.
    if out.exists():
        try:
            existing_lines = out.read_text(encoding="utf-8").splitlines()
            old_last = existing_lines[-1].split(",")[0] if len(existing_lines) > 1 else ""
        except Exception:
            old_last = ""
        if old_last and new_last < old_last:
            print(f"REFUSING_TO_CLOBBER {out.name}: new data ends {new_last} but "
                  f"existing file already reaches {old_last}"
                  f"{' (fetch was incomplete)' if fetch_incomplete else ''}. "
                  f"Keeping the existing, more-complete file.", file=sys.stderr)
            print(f"KEPT existing {out}  (had a longer history than this fetch)")
            sys.exit(1)

    # Atomic write: build a temp file, then replace -- so an interrupted write
    # can never leave a half-written CSV in place of the real one.
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text("\n".join(rows) + "\n", encoding="utf-8")
    tmp.replace(out)

    first = rows[1].split(",")[0]; last = new_last
    days = (datetime.fromisoformat(last) - datetime.fromisoformat(first)).days
    status = " (INCOMPLETE - fetch errored, but extended the history)" if fetch_incomplete else ""
    print(f"WROTE {out}  symbol={symbol}  interval={interval}  "
          f"rows={total}  span={days} days ({days/365.25:.1f} years){status}")


if __name__ == "__main__":
    main()
