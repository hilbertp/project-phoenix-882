# ACs — `apps/bot/strategy/reconciler.py`

Startup-only contract: classify the state (DB ⇔ exchange agreement) before
the live runner accepts new bars.

## AC-REC-01: CLEAN when everything is empty

Given no in-flight setups in the store, no open orders, no positions
When `reconcile(client, store)` is called
Then `result.category == "CLEAN"`, `result.ok == True`, `result.issues == []`.

## AC-REC-02: AMBIGUOUS on orphan position

Given a non-zero position on coin X
But no in-flight setup with `asset==X` in the store
When `reconcile(...)` is called
Then `result.category == "AMBIGUOUS"` and `issues` contains a string
beginning with `"orphan position"`.

## AC-REC-03: AMBIGUOUS on entered setup with no matching position

Given a setup in store with `setup_states.state == "entered"`
But no position on the setup's asset
When `reconcile(...)` is called
Then AMBIGUOUS with an issue containing `"no position exists"`.

Same for `tp1_hit`, `tp2_hit`.

## AC-REC-04: AMBIGUOUS on missing expected order

Given an in-flight setup with an OrderRecord in the store whose
`status in {pending, live}`
But the exchange's `open_orders()` does not return that cloid
When `reconcile(...)` is called
Then AMBIGUOUS with an issue containing `"missing order"`.

## AC-REC-05: AMBIGUOUS on surplus open order

Given an open order on the exchange with a cloid that does NOT match any
order in the state store
When `reconcile(...)` is called
Then AMBIGUOUS with an issue containing `"surplus open order"`.

## AC-REC-06: RESUMABLE when state and exchange agree

Given an in-flight setup (e.g. `entered`) whose expected orders exactly
match the exchange's open orders, AND the position exists with matching
asset
When `reconcile(...)` is called
Then `result.category == "RESUMABLE"`, `result.ok == True`,
`result.issues == []`.

## AC-REC-07: `IN_FLIGHT_STATES` constant

Given the reconciler module
Then `IN_FLIGHT_STATES == {"entered", "tp1_hit", "tp2_hit", "armed"}`.
`"detected"` is NOT in-flight (the cmd_live pickup path handles it
separately).

## AC-REC-08: `format_summary` includes every category line

Given a `ReconciliationResult`
When `format_summary(result)` is called
Then the string contains: `category:`, `in-flight setups:`, `open orders:`,
`positions:`. If issues exist, an `issues:` block follows with one bullet
per issue.

## AC-REC-09: Single read of each exchange endpoint

Given any `reconcile(...)` call
Then `client.open_orders()` and `client.positions()` are each called
exactly once (avoid hammering the exchange on startup).

Notes: a regression test can assert call counts on a fake client.
