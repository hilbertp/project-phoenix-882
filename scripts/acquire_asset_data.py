#!/usr/bin/env python
"""Acquire a 1H / 12-month OHLCV series for any symbol via tvDatafeed (guest).

Mirrors acquire_db1_12mo_data.py but parameterized, so we can pull other assets
(e.g. ADAUSDT.P) for cross-asset backtests. Writes the source-truth CSV and its
provenance sidecar into data/discovery_bet_1/ using the same column + timestamp
contract the loader validates against.

Usage:
  acquire_asset_data.py [EXCHANGE] [SYMBOL]      # default BITGET ADAUSDT.P
"""
from __future__ import annotations

import hashlib
import json
import signal
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tvDatafeed import Interval, TvDatafeed

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "discovery_bet_1"
N_BARS = 9000  # buffer over 12mo (~8760h) to absorb gaps before trimming
WINDOW_DAYS = 366
COLUMNS = ["source_timestamp", "open", "high", "low", "close", "volume"]


def _timeout(*_: object) -> None:
    print("FETCH_TIMEOUT")
    sys.exit(4)


def csv_path_for(exchange: str, symbol: str) -> Path:
    slug = f"{exchange}_{symbol}".lower().replace(".", "_").replace(":", "_")
    return DATA_DIR / f"{slug}_1h_last_12_months.csv"


def main() -> None:
    exchange = sys.argv[1] if len(sys.argv) > 1 else "BITGET"
    symbol = sys.argv[2] if len(sys.argv) > 2 else "ADAUSDT.P"
    csv_path = csv_path_for(exchange, symbol)
    provenance_path = csv_path.with_suffix(".provenance.json")

    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(180)
    tv = TvDatafeed()
    df = tv.get_hist(symbol=symbol, exchange=exchange,
                     interval=Interval.in_1_hour, n_bars=N_BARS)
    signal.alarm(0)
    if df is None or len(df) == 0:
        print("FETCH_EMPTY")
        sys.exit(2)

    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    cutoff = df.index.max() - timedelta(days=WINDOW_DAYS)
    df = df[df.index > cutoff]

    rows = [",".join(COLUMNS)]
    for ts, row in df.iterrows():
        stamp = ts.strftime("%Y-%m-%dT%H:%M:%S")
        rows.append(f"{stamp},{row['open']},{row['high']},{row['low']},"
                    f"{row['close']},{row['volume']}")
    csv_text = "\n".join(rows) + "\n"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(csv_text, encoding="utf-8")
    sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    provenance_path.write_text(json.dumps({
        "acquisition_method": (
            f"tvDatafeed.get_hist(symbol='{symbol}', exchange='{exchange}', "
            f"interval='1H', n_bars={N_BARS}) sorted ascending, de-duplicated, "
            f"trimmed to last {WINDOW_DAYS} days"),
        "acquisition_operator_or_process": (
            "Claude Code automated acquisition workflow (tvDatafeed guest session)"),
        "acquisition_timestamp_utc": datetime.now(UTC).isoformat(),
        "source_file_sha256": sha256,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    span = df.index.max() - df.index.min()
    print(f"WROTE {csv_path}")
    print(f"rows={len(df)} span_days={span.days} first={df.index.min()} last={df.index.max()}")
    print(f"sha256={sha256}")


if __name__ == "__main__":
    main()
