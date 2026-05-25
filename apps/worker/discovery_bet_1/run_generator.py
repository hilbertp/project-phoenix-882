from __future__ import annotations

from pathlib import Path

from dataclasses import asdict

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.export import export_generation_artifacts
from apps.worker.discovery_bet_1.fib_structures import build_fib_candidates
from apps.worker.discovery_bet_1.lifecycle import materialize_fib_structures
from apps.worker.discovery_bet_1.market_contract import (
    LOCKED_MARKET_CONTRACT,
    MarketContract,
    validate_market_contract,
)
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.types import GenerationOutputs

DEFAULT_INPUT_PATH = Path("data/discovery_bet_1/bitget_btcusdt_p_1h_last_12_months.csv")
DEFAULT_ARTIFACTS_DIR = Path("artifacts/discovery_bet_1")


def run_generation(
    *,
    input_path: Path = DEFAULT_INPUT_PATH,
    artifacts_dir: Path = DEFAULT_ARTIFACTS_DIR,
    contract: MarketContract = LOCKED_MARKET_CONTRACT,
) -> GenerationOutputs:
    validated_contract = validate_market_contract(contract)
    loaded_input = load_candle_input(input_path)
    candles = loaded_input.candles
    atr_values = calculate_atr14(candles)
    pivots = detect_local_pivots(candles)
    candidates, rejected_anchors = build_fib_candidates(pivots, atr_values)
    fib_structures = materialize_fib_structures(candidates, candles)

    (
        manifest_path,
        structures_jsonl_path,
        structures_csv_path,
        rejected_anchors_csv_path,
    ) = export_generation_artifacts(
        artifacts_dir=artifacts_dir,
        input_path=input_path,
        contract=validated_contract,
        source_provenance=asdict(loaded_input.provenance),
        candle_count=len(candles),
        pivot_count=len(pivots),
        candidate_count=len(candidates),
        fib_structures=fib_structures,
        rejected_anchors=rejected_anchors,
    )

    return GenerationOutputs(
        manifest_path=manifest_path,
        structures_jsonl_path=structures_jsonl_path,
        structures_csv_path=structures_csv_path,
        rejected_anchors_csv_path=rejected_anchors_csv_path,
        market_symbol=validated_contract.tradingview_symbol,
        accepted_structure_count=len(fib_structures),
        rejected_anchor_count=len(rejected_anchors),
    )
