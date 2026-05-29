# ACs — `apps/bot/strategy/detector_loop.py`

Bar-close subscriber that runs the ATR-zigzag detector and persists newly-
discovered legs.

## AC-DET-01: Idempotency across re-runs

Given the same candle stream replayed multiple times
When `on_bar_close` is invoked for each bar
Then the set of setups persisted is identical on every replay (same
`setup_key` values; `upsert_setup` reports `False` for already-known legs).

## AC-DET-02: ATR-warmup guard

Given a bar where `len(candles) < detector.min_bars + 14`
When `on_bar_close` is invoked
Then no detector run is attempted (no setups produced).

## AC-DET-03: Each new setup is persisted with `state="detected"`

Given a previously-unseen leg
When the detector emits it
Then:
- `setups` table has a row with the leg's metadata
- `setup_states.state == "detected"` with `payload.source == "detector_loop"`

## AC-DET-04: `on_new_setup` hook is called per new setup

Given a `DetectorLoop` constructed with an `on_new_setup` callback
When the detector finds a new leg
Then the callback is called exactly once with:
- the `Setup` dataclass (asset, direction, parent_ts, parent_price,
  term_ts, term_price)
- a `history: tuple[Candle, ...]` containing every candle from the leg's
  `term_idx + 1` through the just-closed bar (inclusive)

## AC-DET-05: Hook is NOT called for already-known legs

Given a leg whose `setup_key` is already in the store
When the detector re-emits it on a later bar
Then `on_new_setup` is NOT invoked.

## AC-DET-06: Hook exceptions don't crash the loop

Given `on_new_setup` raises
When the detector emits a new setup
Then the exception is logged and the loop continues (other setups in the
same bar are still processed; subsequent bars still run).

## AC-DET-07: Detector params used = config values

Given `DetectorConfig(min_bars=6, mult=2.0)`
When the detector runs
Then `clean_legs(..., min_bars=6, mult=2.0)` is called (not the defaults
baked into the script wrappers).
