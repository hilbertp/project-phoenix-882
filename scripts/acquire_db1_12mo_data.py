#!/usr/bin/env python
"""Acquire the DB1 locked market contract series: BITGET:BTCUSDT.P 1H, last 12 months.

Writes the source-truth CSV and its provenance sidecar into
data/discovery_bet_1/ using the exact column + timestamp contract the
generator validates against.
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
CSV_PATH = DATA_DIR / "bitget_btcusdt_p_1h_last_12_months.csv"
PROVENANCE_PATH = CSV_PATH.with_suffix(".provenance.json")

SYMBOL = "BTCUSDT.P"
EXCHANGE = "BITGET"
N_BARS = 9000  # buffer over 12mo (~8760h) to absorb gaps before trimming
WINDOW_DAYS = 366
COLUMNS = ["source_timestamp", "open", "high", "low", "close", "volume"]


def _timeout(*_: object) -> None:
    print("FETCH_TIMEOUT")
    sys.exit(4)


def main() -> None:
    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(180)

    tv = TvDatafeed()
    df = tv.get_hist(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        interval=Interval.in_1_hour,
        n_bars=N_BARS,
    )
    signal.alarm(0)
    if df is None or len(df) == 0:
        print("FETCH_EMPTY")
        sys.exit(2)

    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]

    # Trim to the last WINDOW_DAYS so the file is exactly "last 12 months".
    cutoff = df.index.max() - timedelta(days=WINDOW_DAYS)
    df = df[df.index > cutoff]

    rows: list[str] = [",".join(COLUMNS)]
    for ts, row in df.iterrows():
        stamp = ts.strftime("%Y-%m-%dT%H:%M:%S")
        rows.append(
            f"{stamp},{row['open']},{row['high']},{row['low']},"
            f"{row['close']},{row['volume']}"
        )
    csv_text = "\n".join(rows) + "\n"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CSV_PATH.write_text(csv_text, encoding="utf-8")

    sha256 = hashlib.sha256(CSV_PATH.read_bytes()).hexdigest()
    provenance = {
        "acquisition_method": (
            f"tvDatafeed.get_hist(symbol='{SYMBOL}', exchange='{EXCHANGE}', "
            f"interval='1H', n_bars={N_BARS}) sorted ascending, de-duplicated, "
            f"trimmed to last {WINDOW_DAYS} days"
        ),
        "acquisition_operator_or_process": (
            "Claude Code automated acquisition workflow (tvDatafeed guest session)"
        ),
        "acquisition_timestamp_utc": datetime.now(UTC).isoformat(),
        "source_file_sha256": sha256,
    }
    PROVENANCE_PATH.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    span = df.index.max() - df.index.min()
    print(f"WROTE {CSV_PATH}")
    print(f"rows={len(df)} span_days={span.days} ({span})")
    print(f"first={df.index.min()} last={df.index.max()}")
    print(f"sha256={sha256}")


if __name__ == "__main__":
    main()
