# ACs — `apps/bot/strategy/cloid.py`

Deterministic client_order_id generation. Drives F-12 idempotency: the same
intent always produces the same cloid; the exchange rejects duplicates.

## AC-CLOID-01: Determinism

Given the same `(setup_key, level_role, seq)` triple
When `make_cloid(...)` is called twice
Then both calls return the exact same string.

## AC-CLOID-02: Distinct triples yield distinct cloids

Given any two distinct `(setup_key, level_role, seq)` triples
When `make_cloid(...)` is called on each
Then the two results differ.

The regression test should verify across all role values: `entry`,
`init_sl`, `tp1`, `tp2`, `tp3`, `be_close`. Different `seq` and different
setup_keys must all produce different cloids.

## AC-CLOID-03: Hyperliquid format

Given any inputs
When `make_cloid(...)` returns
Then the result:
- has length 34 (`0x` + 32 hex chars = 16 bytes)
- starts with `0x`
- parses as a hex int (no `int(result, 16)` exception)

## AC-CLOID-04: Default sequence is 0

Given `make_cloid(key, role)` (no seq) and `make_cloid(key, role, 0)`
Then both return the same value.
