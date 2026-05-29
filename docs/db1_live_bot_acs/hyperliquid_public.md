# ACs — `apps/bot/exchange/hyperliquid.py`

Read-only HL client: REST `candle_snapshot`, `meta`, plus a WS subscriber
with reconnect/backoff. **No signing** — that surface lives in
`signed_client.py`.

## AC-HLPUB-01: `meta()` returns the perp universe

Given a constructed `HyperliquidPublicClient` pointed at mainnet
When `meta()` is called
Then the response is a dict with key `"universe"` (a list); each entry has a
`"name"` field.

Notes: this is a live-API contract test. The regression suite should either
run against a recorded fixture OR mark this as a `@network` test that runs
in a separate stage.

## AC-HLPUB-02: `candle_snapshot` returns ordered closed candles

Given `coin="BTC"`, `interval="1h"`, a 24-hour `[start_ms, end_ms]` window
ending in the past
When `candle_snapshot(...)` is called
Then the result is a list of `HLCandle` ordered ascending by `open_ms`.
Each candle has `close_ms > open_ms` and `interval == "1h"`.

## AC-HLPUB-03: WS subscriptions are deduplicated

Given `subscribe_candle("BTC", "1h")` has been called
When `subscribe_candle("BTC", "1h")` is called again
Then `_pending_subs` contains only ONE entry for that (coin, interval) pair.

## AC-HLPUB-04: WS subscriptions are flushed on connect

Given `subscribe_candle("BTC", "1h")` was called BEFORE `start(...)`
When the WS connects
Then a subscribe message for `(BTC, 1h)` is sent on the socket.

## AC-HLPUB-05: WS reconnect with exponential backoff up to 30s

Given the WS disconnects with backoff currently at 4s
When the reconnect loop iterates without a stable connection
Then `time.sleep` is called with a value `min(prev_backoff, 30.0)` and the
NEXT iteration's backoff doubles up to a cap of 30s.

## AC-HLPUB-06: Backoff resets after a stable connection

Given a WS connection has stayed open for ≥ 60 seconds
When it then disconnects
Then the next reconnect attempt waits ~1s (backoff reset), not 30s.

Notes: this is a regression bar — the earlier implementation never reset
backoff, so any long-lived bot waited 30s on every brief disconnect.

## AC-HLPUB-07: Candle message dispatch

Given the WS is connected with `on_candle` registered
When a `{channel: "candle", data: {...}}` message arrives
Then `on_candle` is called with an `HLCandle` constructed from `data`. A
malformed `data` does NOT crash the loop (it logs and continues).

## AC-HLPUB-08: REST timeout is bounded

Given `request_timeout_s=5.0`
When the underlying `requests.post` exceeds the timeout
Then the call raises a `requests.exceptions.Timeout` (the client does not
wait indefinitely).

## AC-HLPUB-09: `stop()` is idempotent and joins the WS thread

Given `start(...)` then `stop()`
Then the WS thread terminates within `timeout_s` seconds. Calling `stop()`
a second time is a no-op.

## AC-HLPUB-10: `start()` is idempotent

Given `start(...)` has already been called once
When `start(...)` is called again
Then no second thread is spawned (the existing one is reused).
