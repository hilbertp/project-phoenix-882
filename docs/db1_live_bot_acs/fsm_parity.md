# ACs — FSM parity (canonical correctness anchor)

This is the **single most important contract** for the live bot. The FSM
behavior must be indistinguishable from `scripts/execute_fib_strategy.execute()`
on every detected setup. The test `tests/test_bot_fsm_parity.py` is part of
the regression suite and must remain green.

## AC-PARITY-01: Status + R match on every detected leg

Given any candle dataset and any detector params
When the detector emits a leg AND both:
- `execute(candles, idx, leg)` returns `{status, r, ...}` (gold)
- `simulate_setup(leg, candles, idx, StrategyConfig())` returns
  `{status, r, ...}` (bot FSM)
Then `sim["status"] == gold["status"]` AND
`abs(sim["r"] - gold["r"]) <= 1e-9`.

## AC-PARITY-02: 4-corrected-swings dataset

The four hand-validated `CORRECTED_SWINGS` in
`scripts/place_fibs_tradingview.py` (`auto5`, `auto12`, `auto14`, plus the
`also_remove`-augmented variant) MUST all pass parity.

## AC-PARITY-03: 12-month BTC dataset (both detector params)

Every leg detected on `bitget_btcusdt_p_1h_last_12_months.csv` at:
- `min_bars=24, mult=4.0` (~30 legs)
- `min_bars=6, mult=2.0` (~700+ legs)
MUST pass parity.

## AC-PARITY-04: Long-history BTC dataset

Every leg detected on `binance_btcusdt_1h_full_history.csv` (8.75 years,
76 770 candles) at the PRD detector defaults (`min_bars=6, mult=2.0`,
producing 5 300+ legs) MUST pass parity. Total failures across the dataset:
zero.

Notes: this is the M2 exit criterion. Any drop from 100% parity on this
dataset is a P0 blocker.

## AC-PARITY-05: Parity holds across detector parameter sweeps

Given `min_bars in {6, 12, 18, 24}` and `mult in {1.5, 2.0, 3.0, 4.0}`
When the parity test runs on the 12-month BTC dataset for each pair
Then every (min_bars, mult) yields 100% parity.

This protects against an FSM bug that only manifests at uncommon detector
parameters.
