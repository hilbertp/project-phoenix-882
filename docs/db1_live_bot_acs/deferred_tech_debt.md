# ACs — Deferred tech debt (contracts only; impl pending)

These ACs document contracts that **must hold once implemented**. Codex's
regression suite can encode them now and skip with a clear `pytest.skip`
reason; whoever lands the implementation makes the tests pass.

This file exists so the contracts are stable BEFORE the code change is
written — that way the implementer cannot accidentally drift from the
intended behavior.

---

## Log rotation — `apps/bot/logging_setup.py`

### AC-LOG-ROT-01: Size-based rotation

Given a configured log directory and a `max_bytes_per_file` setting (TBD;
default e.g. 100 MB)
When `bot.log` reaches `max_bytes_per_file`
Then it is rotated to `bot.log.1` (and `bot.log.1` rotates to `bot.log.2`,
etc.), up to a configurable `backup_count` (default 5). `bot.log` is then
truncated and writing resumes.

### AC-LOG-ROT-02: No log loss across rotation

Given a writer is actively logging
When rotation happens
Then no log line is lost or duplicated across the boundary.

### AC-LOG-ROT-03: Retention pruning

Given a backup count of N
When the (N+1)-th rotation occurs
Then the oldest `bot.log.N+1` is deleted.

---

## State store migration framework — `apps/bot/state.py`

### AC-MIG-01: Versioned migrations applied in order

Given a state DB at schema version `V_old`
And a target version `V_new > V_old`
When the StateStore is opened
Then every migration file with version in `(V_old, V_new]` is executed in
ascending order inside a single transaction; the version row is updated to
`V_new` only if all migrations succeed.

### AC-MIG-02: Failure rolls back the whole upgrade

Given a migration that raises mid-execution
Then the transaction is rolled back AND the StateStore constructor raises;
no partial schema state is persisted.

### AC-MIG-03: Migrations are forward-only

The framework does not support down-migrations. Once a schema reaches
`V_new` it stays there; rollback requires restoring a backup. This is a
deliberate constraint to keep the system simple in v1.

### AC-MIG-04: Idempotent re-application

Given a DB already at version `V_new`
When the StateStore is re-opened
Then no migration runs and no schema_meta row is added.

---

## Detector loop perf — `apps/bot/strategy/detector_loop.py`

### AC-DET-PERF-01: Cached previous result, only re-detect at the tail

Given the detector ran at bar `N` and produced legs `L_N`
When a new bar `N+1` arrives
Then the detector reuses the pivot sequence up to bar `N-K` (where `K` is
a small lookback window, e.g. 50 bars) and only recomputes the tail.

Output equivalence: the legs produced from the cached + tail run MUST
equal the legs that a from-scratch run on the full buffer would produce
(no semantic drift).

### AC-DET-PERF-02: Cache invalidates on detector-param change

Given the cached pivots were computed with `(min_bars, mult) = (6, 2.0)`
When the detector is called with different params
Then the cache is invalidated and a from-scratch run executes.

---

## Cancel-then-place atomicity — `apps/bot/strategy/order_manager.py`

### AC-OM-ATOMIC-01: Batched cancel+place at TP1 transition

Given the FSM transitions from ENTERED to TP1_HIT
Then the OrderManager sends a SINGLE batched signed request to HL that
both cancels the initial SL and places the TP2 limit. Either both succeed
or neither does.

Notes: this requires HL's batched-signing endpoint; currently we use the
non-atomic sequence with bounded cancel retries (AC-OM-13g). The atomic
version closes the bounded-loss window documented there.

---

## Fill stream WS subscription — `apps/bot/exchange/`

### AC-FILLS-01: Subscribe to user-fills WS channel

Given a constructed SignedHyperliquidClient
When `start_user_data_stream(on_fill)` is called
Then the bot opens a WS connection subscribed to the user's fill events
for the configured account. Each fill triggers `on_fill(Fill)`.

### AC-FILLS-02: Fill stream drives FSM transitions independently

Given an FSM at ENTERED state expecting a TP1 fill
When the WS reports a fill for the TP1 cloid
Then the OrderManager updates state IMMEDIATELY (does not wait for the
next bar close to observe TP1 via wick logic).

The FSM's wick-derived transitions become a backup signal; the exchange's
actual fill is the source of truth.

### AC-FILLS-03: Stream reconnect REST-fills missed fills

Given the user-data WS reconnects
Then `fills_since(last_seen_ms)` is called to backfill any fills that
arrived during the disconnect.
