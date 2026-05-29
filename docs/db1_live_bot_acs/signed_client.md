# ACs — `apps/bot/exchange/signed_client.py`

Signed trading surface for HL. **Real money** — every contract here is a
safety bar.

## AC-SIGN-01: Construction requires agent key + master address

Given either `agent_private_key=""` or `master_account_address=""`
When `SignedHyperliquidClient(...)` is constructed
Then `ValueError` is raised. The error message names the env vars
(`PHOENIX_HL_AGENT_PRIVATE_KEY`, `PHOENIX_HL_ACCOUNT_ADDRESS`) so the
operator can fix the gap.

Notes: silent construction with empty creds is a footgun; trading methods
must be unreachable without an explicit credential pair. Only agent keys
ever flow here — see `rabby_agent.md`.

## AC-SIGN-01b: Construction exposes agent and master addresses

Given a valid construction
Then `client.agent_address` equals the public address derived from the
agent key AND `client.master_address` equals the constructor argument.
Both are public information and safe to log.

## AC-SIGN-02: Agent key never logged

Given `SignedHyperliquidClient(agent_private_key=K, ...)`
When ANY method is called (with default INFO/DEBUG logging enabled)
Then the literal `K` does not appear in any log line (console or JSON file).

Combined with the redacting log filter (AC-LOG-05), this is enforced by both
the client (no log.info containing the key) AND the formatter.

## AC-SIGN-03: Caller-supplied cloid is used verbatim

Given `cloid="0x0123..."` (valid HL format, 34 chars)
When `place_limit_post_only(..., cloid=cloid)` is called
Then the underlying `Exchange.order` is called with `Cloid.from_str(cloid)`.
The client must NOT generate cloids — caller idempotency depends on it.

## AC-SIGN-04: `place_limit_post_only` uses `tif=Alo`

Given any call to `place_limit_post_only`
Then the SDK is invoked with `order_type == {"limit": {"tif": "Alo"}}`
and `reduce_only=False`. Alo = Add Liquidity Only = post-only maker; HL
rejects with `PostOnly` if the price would cross.

## AC-SIGN-05: `place_reduce_only_limit` uses `reduce_only=True, tif=Gtc`

Given any call to `place_reduce_only_limit`
Then the SDK is invoked with `order_type == {"limit": {"tif": "Gtc"}}` AND
`reduce_only=True`. Reduce-only guarantees TPs never accidentally grow the
position.

## AC-SIGN-06: `place_stop_market` `limit_px` aims through trigger

Given `place_stop_market(coin, is_buy, qty, trigger_px=T, cloid, slippage_tolerance=s)`
When the SDK is invoked
Then the `limit_px` passed is:
- `T * (1 + s)` when `is_buy == True` (buy-stop, market is above trigger)
- `T * (1 - s)` when `is_buy == False` (sell-stop, market is below trigger)

The order_type has `triggerPx == T, isMarket == True, tpsl == "sl"`.

Notes: regression bar — earlier code set `limit_px == trigger_px`, which
on HL means "won't fill at a worse price" and breaks sell-stops because the
market is by definition below trigger when they fire.

## AC-SIGN-07: `market_close` passes through cloid + slippage

Given `market_close(coin, qty, cloid, slippage=0.05)`
Then `Exchange.market_close` is invoked with the cloid and slippage; the
returned `PlacedOrder` reports `status` ∈ {`resting`, `filled`, `rejected`,
`unknown`}.

## AC-SIGN-08: `cancel` is by cloid

Given `cancel(coin, cloid)`
Then `Exchange.cancel_by_cloid(coin, Cloid.from_str(cloid))` is invoked.
Cancelling by oid is NOT in this surface — the strategy only knows cloids.

## AC-SIGN-09: `open_orders()` returns a list of `OpenOrder`

Given the SDK's `Info.open_orders(address)` returns a list of raw dicts
When `open_orders()` is called
Then each raw dict is converted into a typed `OpenOrder` with non-None
`cloid` preserved as a string.

## AC-SIGN-10: `positions()` filters zero-size

Given the SDK's `Info.user_state(address)` returns asset positions some of
which have `szi == "0"`
When `positions()` is called
Then only non-zero positions are returned.

## AC-SIGN-11: `fills_since(start_ms)` filters by time

Given `Info.user_fills_by_time(address)` returns fills at times `t1 < t2 < t3`
When `fills_since(t2)` is called
Then only fills with `time_ms >= t2` are returned.

## AC-SIGN-12a: `fetch_size_decimals()` returns coin→szDecimals from meta

Given `Info.meta().universe` contains `[{"name":"BTC","szDecimals":5}, ...]`
When `fetch_size_decimals()` is called
Then the result is `{"BTC": 5, ...}` covering every entry that has both
`name` and `szDecimals` set. Missing/None szDecimals entries are omitted.

## AC-SIGN-12b: `fetch_max_leverage()` returns coin→maxLeverage from meta

Given `Info.meta().universe` contains
`[{"name":"BTC","maxLeverage":40}, {"name":"ATOM","maxLeverage":5}, ...]`
When `fetch_max_leverage()` is called
Then the result is `{"BTC": 40, "ATOM": 5, ...}` covering every entry that
has both `name` and `maxLeverage` set.

## AC-SIGN-12: Order response parsing

Given the SDK returns `{"status": "ok", "response": {"data": {"statuses":
[{"resting": {"oid": 1234}}]}}}`
When `_parse_order_response(raw, cloid)` is called
Then the result is `PlacedOrder(cloid=cloid, exchange_order_id=1234,
status="resting", raw=raw)`.

A `"filled"` status carries the oid the same way. `"error"` returns
status="rejected". An overall `"err"` returns status="rejected".
