# ACs — `apps/bot/state.py`

SQLite store with WAL + FK on. The contract is **durability + idempotency**:
re-running the same operation must be safe across crashes.

## State vocabulary (canonical)

`setup_states.state` ∈ {
  `detected`, `armed`, `entered`, `tp1_hit`, `tp2_hit`,
  `wipeout`, `tp1_then_scratch`, `tp2_then_scratch`, `tp3_full`,
  `no_trigger`, `no_entry`, `degenerate`, `open`, `missed`
}.

In-flight = `{armed, entered, tp1_hit, tp2_hit}` (and `detected` is pickup
candidate). Everything else is terminal.

## AC-STATE-01: Schema migrations apply at startup

Given a fresh database file
When `StateStore(path)` is constructed
Then all tables (`setups`, `setup_states`, `state_transitions`, `orders`,
`fills`, `schema_meta`) exist and a row is present in `schema_meta`
recording the current version.

## AC-STATE-02: Re-opening preserves data

Given a `StateStore` that wrote a setup + a state transition
When the store is closed and a new `StateStore` is constructed at the same path
Then `get_setup(key)` and `get_state(key)` return the previously-written
values.

## AC-STATE-03: `upsert_setup` is idempotent

Given a `SetupRecord` with `setup_key=K` already inserted
When `upsert_setup(rec)` is called again with the same `rec`
Then no new row is written; the call returns `False`.

The FIRST insert returns `True`.

## AC-STATE-04: Setup key format

Given `setup_key_for(asset, direction, parent_ts, term_ts)`
Then the result is the four parts joined by `|` in that order with no
escaping. The format is the canonical setup-key everywhere else uses for
joins.

## AC-STATE-05: `set_state` is transactional with transition log

Given a setup exists
When `set_state(key, "armed", payload)` then `set_state(key, "entered", …)`
Then:
- `setup_states.state` == "entered" (latest wins)
- `state_transitions` has 2 rows with `from_state` chaining:
  row 1: `from_state=None, to_state="armed"`,
  row 2: `from_state="armed", to_state="entered"`
- Both rows AND the `setup_states` upsert land or fail atomically.

## AC-STATE-06: FK from `orders` → `setups`

Given no `setups` row with `setup_key=K`
When `upsert_order(OrderRecord(..., setup_key=K, ...))` is called
Then a `sqlite3.IntegrityError` is raised (FK constraint).

## AC-STATE-07: `open_orders_for` filters by status ∈ {pending, live}

Given setups with orders in statuses `pending`, `live`, `filled`,
`cancelled`, `rejected`
When `open_orders_for(key)` is called
Then only the `pending` and `live` rows are returned.

## AC-STATE-08: `get_order` lookup by cloid

Given an upserted `OrderRecord` with `client_order_id=X`
When `get_order(X)` is called
Then the record is returned. `get_order("unknown")` returns `None`.

## AC-STATE-09: `upsert_order` updates status without erasing immutable fields

Given an order has been upserted with status="pending"
When the same cloid is re-upserted with status="live" and a new exchange_id
Then status becomes "live", exchange_order_id is set, and the other fields
(asset, side, qty, price, level_role, setup_key, created_at) are unchanged.

`exchange_order_id` is `COALESCE`d so a later upsert with `None` does not
clobber a previously-set value.

## AC-STATE-10: WAL mode active

Given a freshly constructed `StateStore`
When `PRAGMA journal_mode;` is queried
Then the result is `wal`.

## AC-STATE-11: FK enforcement enabled

Given a freshly constructed `StateStore`
When `PRAGMA foreign_keys;` is queried
Then the result is `1`.

## AC-STATE-12: `list_setups` filter + ordering

Given setups for assets BTC, ETH, BTC inserted at times t1 < t2 < t3
When `list_setups(asset="BTC", limit=10)` is called
Then 2 rows are returned, newest first.
