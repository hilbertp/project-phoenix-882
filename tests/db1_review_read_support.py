from __future__ import annotations

import json
from pathlib import Path

from apps.worker.discovery_bet_1.market_contract import LOCKED_MARKET_CONTRACT, market_contract_as_dict


def write_review_artifacts(
    artifacts_dir: Path,
    *,
    manifest_market_contract: dict[str, str] | None = None,
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "market_contract": manifest_market_contract
        or market_contract_as_dict(LOCKED_MARKET_CONTRACT),
        "input_path": "data/discovery_bet_1/bitget_btcusdt_p_1h_last_3_months.csv",
        "candle_count": 100,
        "pivot_count": 10,
        "candidate_count": 5,
        "accepted_structure_count": 3,
        "rejected_anchor_count": 7,
        "atr_period": 14,
        "atr_multiplier": 2.0,
        "pivot_rule": "2-left/2-right",
        "generated_at_utc": "2026-03-30T00:00:00+00:00",
    }
    (artifacts_dir / "db1_generation_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    structures = [
        {
            "structure_id": "db1-fib-0002",
            "market_symbol": "BITGET:BTCUSDT.P",
            "timeframe": "1H",
            "direction": "up",
            "parent_anchor_timestamp_utc": "2026-01-01T05:00:00+00:00",
            "parent_anchor_price": 90.0,
            "parent_anchor_kind": "low",
            "terminal_extreme_timestamp_utc": "2026-01-01T14:00:00+00:00",
            "terminal_extreme_price": 130.0,
            "terminal_extreme_kind": "high",
            "anchor_range_low": 90.0,
            "anchor_range_high": 100.0,
            "activated_at_utc": "2026-01-01T14:00:00+00:00",
            "invalidated_at_utc": "",
            "invalidation_reason": "",
            "source_candle_start_utc": "2026-01-01T00:00:00+00:00",
            "source_candle_end_utc": "2026-03-30T23:00:00+00:00",
        },
        {
            "structure_id": "db1-fib-0001",
            "market_symbol": "BITGET:BTCUSDT.P",
            "timeframe": "1H",
            "direction": "down",
            "parent_anchor_timestamp_utc": "2026-01-01T02:00:00+00:00",
            "parent_anchor_price": 120.0,
            "parent_anchor_kind": "high",
            "terminal_extreme_timestamp_utc": "2026-01-01T10:00:00+00:00",
            "terminal_extreme_price": 80.0,
            "terminal_extreme_kind": "low",
            "anchor_range_low": 118.0,
            "anchor_range_high": 120.0,
            "activated_at_utc": "2026-01-01T10:00:00+00:00",
            "invalidated_at_utc": "2026-01-01T12:00:00+00:00",
            "invalidation_reason": "anchor_range_breached",
            "source_candle_start_utc": "2026-01-01T00:00:00+00:00",
            "source_candle_end_utc": "2026-03-30T23:00:00+00:00",
        },
        {
            "structure_id": "db1-fib-0003",
            "market_symbol": "BITGET:BTCUSDT.P",
            "timeframe": "1H",
            "direction": "up",
            "parent_anchor_timestamp_utc": "2026-01-01T08:00:00+00:00",
            "parent_anchor_price": 95.0,
            "parent_anchor_kind": "low",
            "terminal_extreme_timestamp_utc": "2026-01-01T16:00:00+00:00",
            "terminal_extreme_price": 140.0,
            "terminal_extreme_kind": "high",
            "anchor_range_low": 95.0,
            "anchor_range_high": 102.0,
            "activated_at_utc": "2026-01-01T16:00:00+00:00",
            "invalidated_at_utc": "",
            "invalidation_reason": "",
            "source_candle_start_utc": "2026-01-01T00:00:00+00:00",
            "source_candle_end_utc": "2026-03-30T23:00:00+00:00",
        },
    ]
    (artifacts_dir / "db1_fib_structures.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in structures) + "\n",
        encoding="utf-8",
    )