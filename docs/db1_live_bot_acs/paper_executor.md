# ACs — `apps/bot/simulation/paper_executor.py`

Thin driver around the FSM that produces `execute()`-shaped outcomes for
historical replay.

## AC-SIM-01: Output shape matches `execute()`

Given any setup + candle stream + `idx` (timestamp → index map)
When `simulate_setup(...)` is called
Then the result is a dict with keys `{status, events, r, levels, fsm_state}`.

`levels` includes the same keys execute() returns:
`entry, init_sl, be_trig, tp2, tp3, r_tp1, r_tp2, r_tp3`.

## AC-SIM-02: Trade-by-trade parity with `execute()`

Given the BTC long-history dataset (`binance_btcusdt_1h_full_history.csv`)
and the detector run at PRD defaults (`min_bars=6, mult=2.0`)
When every detected leg is simulated AND executed via execute()
Then for every leg:
- `sim["status"] == gold["status"]`
- `abs(sim["r"] - gold["r"]) <= 1e-9`

(The canonical regression for this is `tests/test_bot_fsm_parity.py`.)

## AC-SIM-03: Degenerate setups short-circuit

Given a setup whose levels are degenerate
When `simulate_setup(...)` is called
Then `result["status"] == "degenerate"`, `result["r"] == 0.0`, and no
bars are processed.

## AC-SIM-04: End-of-history maps to no_entry vs open

Given a setup whose entry never triggers in the candle stream
Then `result["status"] == "no_entry"` (FSM stayed in ARMED → mark_no_entry).

Given a setup that entered but did not resolve before end-of-history
Then `result["status"] == "open"`.

## AC-SIM-05: Candle window starts at `term_idx + 1`

Given a setup at `term_ts = T`, `idx[T] = i`
When `simulate_setup(...)` is called
Then the FSM is driven with `candles[i+1:]` and never bar `i` or earlier.
(Matches execute()'s `range(ti + 1, len(candles))`.)
