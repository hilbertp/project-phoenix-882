# ACs — `apps/bot/strategy/fsm.py`

The per-setup FSM. **Backtest parity is the most important contract in the
whole system.**

## AC-FSM-01: Trade-by-trade parity with `execute()`

Given any setup the detector produces from any candle stream
When the setup is run through both `scripts/execute_fib_strategy.execute()`
(canonical reference) and `FibFSM` (driven by the same candles)
Then both return:
- the same terminal status (`no_trigger`, `no_entry`, `wipeout`,
  `tp1_then_scratch`, `tp2_then_scratch`, `tp3_full`, `degenerate`, `open`)
- the same realized R within `1e-9` rounding tolerance

This is the M2 exit criterion (PRD §10 Phase 0). The corresponding test
(`tests/test_bot_fsm_parity.py`) MUST be preserved. It exercises the
4 hand-validated `CORRECTED_SWINGS`, every detected leg on the recent
12-month BTC dataset (both `24/4.0` and `6/2.0` detector params), and 5325+
legs across 8.75 years of Binance BTC long-history.

## AC-FSM-02: Initial state

Given a non-degenerate setup
When `FibFSM(setup, cfg)` is constructed
Then `state == ARMED`, one `place_entry` event has been emitted, and
`finished == False`.

## AC-FSM-03: Degenerate setup is terminal at construction

Given a setup with inverted or zero-width geometry
When the FSM is constructed
Then `state == DEGENERATE`, `status == "degenerate"`, `finished == True`,
no events emitted.

## AC-FSM-04: Terminal-break aborts before entry-fill on the same bar

Given an up leg with terminal=110, entry≈100.59
When a bar arrives with `high=111` AND `low=100`
Then `state == ABORTED`, `status == "no_trigger"`, NOT `entered`. The
terminal-break check fires first in `_step_armed`.

## AC-FSM-05: Entry fill on bar T; phase-1 evaluation starts on bar T+1

Given an up-leg setup
When a bar arrives whose low touches entry without breaking terminal
Then on that bar `state == ENTERED`, TP/SL are NOT evaluated on the entry
bar, AND the following bar evaluates phase-1 logic.

## AC-FSM-06: Nearest-first within a bar (TP1 over initial SL)

Given an up-leg setup in ENTERED state
When a bar arrives with `low <= init_sl AND high >= tp1`
Then `state == TP1_HIT` (TP1 wins). Realized R increments by
`tp1_size * risk_to_tp1`. SL drags to entry (break-even).

## AC-FSM-07: Initial SL wipeout

Given an ENTERED FSM
When a bar arrives with the SL hit and TP1 not hit
Then `state == DONE`, `status == "wipeout"`, `realized_r == -1.0`.

## AC-FSM-08: Close-based BE stop after TP1

Given an FSM in TP1_HIT state, SL dragged to entry
When a bar arrives whose CLOSE breaches entry but TP2 not hit
Then `status == "tp1_then_scratch"`, FSM done.

Notes: a WICK through entry that does not close past entry must NOT
trigger the BE stop. This is the close-based break-even rule that the live
bot must emulate in software (PRD §6.1).

## AC-FSM-09: TP2 wick takes precedence over close-based BE in the same bar

Given an FSM in TP1_HIT state
When a bar arrives with `high >= tp2` (up) AND `close < entry`
Then TP2 is taken first; `state == TP2_HIT`. The bar's close does NOT
trigger BE stop, because the intrabar wick to TP2 precedes the bar's close.

## AC-FSM-10: TP3 full takeout

Given an FSM in TP2_HIT state
When a bar arrives with `high >= tp3` (or `low <= tp3` for down)
Then `status == "tp3_full"`, `realized_r` adds `tp3_size * risk_to_tp3`,
done.

## AC-FSM-11: BE stop after TP2 carries payload phase="tp2_hit"

Given an FSM in TP2_HIT state
When a close-based BE stop fires
Then a `be_stop_close` event is emitted with `payload["phase"] == "tp2_hit"`.
(The OrderManager uses this to size the remaining position correctly.)

## AC-FSM-12: No-entry at end-of-history (caller signals)

Given an FSM in ARMED state
When `mark_no_entry()` is called (after the bar stream is exhausted)
Then `status == "no_entry"`, `state == ABORTED`, a `done` event with
status="no_entry" is emitted.

## AC-FSM-13: Idempotency under repeated `on_bar`

Given a FINISHED FSM
When `on_bar(c)` is called
Then no state change, no new events emitted (the FSM is inert after
terminal).

## AC-FSM-14: Direction inference

Given `setup.direction == "up"` → FSM treats long-side semantics
(buy-on-fill, low <= entry to trigger, etc.).
Given `setup.direction == "down"` → short-side semantics
(sell-on-fill, high >= entry to trigger, etc.).
