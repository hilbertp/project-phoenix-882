#!/usr/bin/env python
"""Export a self-contained data file for the standalone fib-setup demo UI.

Writes artifacts/discovery_bet_1/demo_data.json with everything the demo needs:
the recent candle window, the auto-detected setups (human overrides applied), and
per setup the Fib level prices, the ordered level-reach sequence, and the
theoretical trade-plan execution outcome.

This is the data contract for the demo. Cursor builds
artifacts/discovery_bet_1/demo.html against it (Back/Next through `setups`, draw
`candles` + the focused setup's `levels`/trade plan, show `reaches` + `execution`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.db1_fib_review_pine_read.service import PHOENIX_FIB_LEVELS
from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.human_labels import apply_overrides
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from scripts.execute_fib_strategy import (
    BE_TRIG_C,
    ENTRY_C,
    INIT_SL_C,
    P_TP1,
    P_TP2,
    P_TP3,
    TP2_C,
    TP3_C,
    execute,
)
from scripts.place_fibs_tradingview import MIN_BARS, RECENT_3M_FROM, _clean_legs
from scripts.track_fib_reaches import track_reaches

OUT = REPO_ROOT / "artifacts" / "discovery_bet_1" / "demo_data.json"


def _lvl(terminal: float, parent: float, coeff: float) -> float:
    return terminal + (parent - terminal) * coeff


def main() -> None:
    candles = load_candle_input(DEFAULT_INPUT_PATH).candles
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    atr = calculate_atr14(candles)
    pivots = detect_local_pivots(candles)
    legs = apply_overrides(
        [
            leg for leg in _clean_legs(candles, atr, pivots, min_bars=MIN_BARS, mult=4.0)
            if leg["parent_ts"] >= RECENT_3M_FROM
        ]
    )

    start_i = max(0, min(idx[leg["parent_ts"]] for leg in legs) - 30) if legs else 0
    window = candles[start_i:]
    out_candles = [
        {"t": c.source_timestamp, "o": c.open, "h": c.high, "l": c.low, "c": c.close}
        for c in window
    ]

    setups = []
    for n, leg in enumerate(legs, start=1):
        terminal, parent = leg["term_price"], leg["parent_price"]
        reaches = track_reaches(candles, idx, leg)
        execu = execute(candles, idx, leg)
        setups.append(
            {
                "id": f"auto{n}",
                "direction": leg["direction"],
                "parent_ts": leg["parent_ts"],
                "parent_price": parent,
                "term_ts": leg["term_ts"],
                "term_price": terminal,
                "levels": {f"{lv:.3f}": _lvl(terminal, parent, lv) for lv in PHOENIX_FIB_LEVELS},
                "entry": {
                    "price": reaches["entry_price"],
                    "ts": reaches["entry_ts"],
                    "filled": reaches["entered"],
                },
                "reaches": reaches["sequence"],
                "execution": {
                    "status": execu["status"],
                    "r": round(execu["r"], 3),
                    "events": [
                        {"label": label, "ts": ts, "price": price}
                        for (label, ts, price) in execu["events"]
                    ],
                },
            }
        )

    data = {
        "symbol": "BITGET:BTCUSDT.P",
        "timeframe": "1H",
        "trade_plan": {
            "entry": ENTRY_C,
            "initial_sl": INIT_SL_C,
            "tp1": BE_TRIG_C,
            "tp2": TP2_C,
            "tp3": TP3_C,
            "sizing": {"tp1": P_TP1, "tp2": P_TP2, "tp3": P_TP3},
        },
        "fib_levels": list(PHOENIX_FIB_LEVELS),
        "candles": out_candles,
        "setups": setups,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data), encoding="utf-8")
    print(f"WROTE {OUT}")
    print(f"setups={len(setups)} candles={len(out_candles)}")
    wins = sum(1 for s in setups if s["execution"]["status"] == "tp3_full")
    print(f"sample: setups with full TP3 = {wins}")


if __name__ == "__main__":
    main()
