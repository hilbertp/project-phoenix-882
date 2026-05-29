# ACs — `apps/bot/marketdata.py`

Per-asset rolling buffer of **closed** candles + a separate **in-progress
snapshot** field. Emits `BarCloseEvent` on real rollovers only.

## AC-MD-01: Backfill loads only closed bars

Given the public client returns N candles ending at `current_bar_open - 1`
When `backfill()` is called
Then `buffer(asset)` returns those N candles in chronological order. No
in-progress bar is in the buffer.

## AC-MD-02: First WS message emits no spurious close

Given backfill completed
When the first WS message arrives for the current in-progress bar
(open_ms > last backfilled open_ms)
Then no `BarCloseEvent` is emitted. The closed bars are already in the
buffer from backfill; the freshly-arrived bar is in progress.

Notes: this is a regression bar. The earlier implementation emitted a close
for the last backfilled bar.

## AC-MD-03: Refresh of in-progress emits no event

Given an in-progress bar is being tracked
When subsequent WS messages arrive with the same `open_ms`
Then no `BarCloseEvent` is emitted. Each refresh updates an internal
snapshot only.

## AC-MD-04: Bar rollover emits close with the just-closed bar's freshest data

Given an in-progress bar with `(open_ms=T, high=H_max)` has been refreshed
several times
When a new WS message arrives with `open_ms = T + interval_ms`
Then a `BarCloseEvent` fires with:
- `closed_open_ms == T`
- `candles[-1].open_ms == T` AND `candles[-1].high == H_max` (the FINAL
  snapshot of the just-closed bar, NOT the new bar's first snapshot)
- `len(candles)` == prior `len(buffer(asset)) + 1`

## AC-MD-05: Subscribers receive every closed bar

Given two subscribers `cb1`, `cb2`
When a bar rolls over
Then both `cb1` and `cb2` are called exactly once with the same
`BarCloseEvent` object.

If `cb1` raises, `cb2` is still called.

## AC-MD-06: Buffer respects `buffer_size`

Given `buffer_size=N` and N+M bars (mix of backfill + rollovers) have been
absorbed
When `buffer(asset)` is called
Then it returns at most N candles (the most recent N).

## AC-MD-07: Wrong-interval messages are ignored

Given a feed configured for `interval="1h"`
When a WS message arrives with `interval="5m"`
Then no buffer mutation and no event.

## AC-MD-08: Wrong-asset messages are ignored

Given a feed configured for `assets=("BTC",)`
When a WS message arrives with `coin="ETH"`
Then no buffer mutation and no event.

## AC-MD-09: Stale message (older bar) is dropped

Given an in-progress bar tracked at `open_ms=T`
When a WS message arrives with `open_ms < T`
Then no buffer mutation and no event.

## AC-MD-10: HL→Candle timestamp formatting

Given an `HLCandle` with `open_ms=1779700000000`
When converted to the worker `Candle`
Then `source_timestamp` is the UTC ISO-8601 of `open_ms / 1000` formatted as
`YYYY-MM-DDTHH:MM:SS` (no timezone suffix, matching the existing CSV
convention).

## AC-MD-11: Locks held only around buffer mutation

When a subscriber callback runs, it does so OUTSIDE the per-asset lock so a
slow subscriber cannot block the WS thread.

## AC-MD-12: WS gap detection — REST-fill missed bars

Given an in-progress bar at `open_ms = T` with stored snapshot S
When a WS message arrives with `open_ms = T + 3 * interval_ms` (2 bars
were missed)
Then:
- The stored in-progress snapshot S is promoted to closed and a
  BarCloseEvent fires with `closed_open_ms = T`.
- `client.candle_snapshot(asset, interval, T + interval_ms, T + 3 * interval_ms - 1)`
  is called.
- Each returned bar appears in the buffer in chronological order.
- A BarCloseEvent fires for EACH missed bar's `open_ms`, in order.
- The current message's bar is set as the new in-progress (no event for it).

If the REST fill-in fails, the gap is logged but the live tracker resumes
on the current bar (no events for the missed bars; the next detector run
will operate on whatever bars are present).

## AC-MD-13: Single-bar rollover does NOT trigger gap path

Given an in-progress bar at `open_ms = T`
When the next WS message arrives with `open_ms = T + interval_ms` (exactly
one bar ahead)
Then NO `candle_snapshot` REST call is made — only the normal in-place
rollover with one BarCloseEvent.
