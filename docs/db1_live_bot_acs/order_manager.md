# ACs — `apps/bot/strategy/order_manager.py`

Translates FSM events into signed exchange calls. The critical contracts
are **idempotency, write-ahead persistence, and refusal to act on stale
detections**.

## State vocabulary written

The OrderManager writes the following values to `setup_states.state`
(canonical for the system):

- `armed` — entry placed; awaiting trigger
- `entered` — entry filled; SL + TP1 placed
- `tp1_hit` — TP1 partial taken; SL dragged to BE in software
- `tp2_hit` — TP2 partial taken; runner active toward TP3
- `wipeout`, `tp1_then_scratch`, `tp2_then_scratch`, `tp3_full`,
  `no_trigger`, `no_entry`, `degenerate`, `open` — terminal statuses
- `missed` — detected with `reason=detection_gap`; never armed live

## AC-OM-01: Arming places entry-only

Given a non-degenerate setup, `equity > 0`, `ExchangeClient` recording calls
When `arm_setup(setup)` (no history) is called
Then EXACTLY one signed call is made: `place_limit_post_only(...)` on the
setup's asset, at the setup's entry price, sized to 1R of equity. No SL,
TP1, TP2, TP3 are placed yet.

## AC-OM-02: 1R sizing math

Given `equity=$100_000`, `account_risk_pct=1.0`, `risk_per_unit=$1.09`
When `arm_setup(setup)` is called
Then the placed entry qty is `≈ 1000 / 1.09 ≈ 917.4` (within `1e-6`).

## AC-OM-03: Entry-fill on a bar places SL + TP1

Given an active FSM in ARMED state
When `on_bar_close` delivers a bar that fills the entry (low<=entry for up,
high>=entry for down) without breaking terminal
Then the following signed calls fire (in order):
1. `place_stop_market(trigger_px=init_sl, is_buy=opposite, slippage_tolerance=0.05)`
2. `place_reduce_only_limit(price=tp1, qty=entry_qty*tp1_size, is_buy=opposite)`

The state store records both orders as pending → live.

## AC-OM-04: TP1-hit cancels SL and places TP2

Given an active FSM in ENTERED state
When a bar arrives that hits TP1
Then a `cancel` call is made (initial SL cloid) AND a
`place_reduce_only_limit(price=tp2, qty=entry_qty*tp2_size, ...)` is fired.
The state store records `setup_states.state == "tp1_hit"`.

## AC-OM-05: BE close fires a market_close at correct phase

Given an active FSM in TP1_HIT state
When a bar's close breaches the BE level
Then ONE `market_close(coin, qty=entry_qty*(1-tp1_size), cloid=...)` call
fires. The cloid is generated with `seq>=1` (distinct from any prior cloid
for this setup). State transitions to `tp1_then_scratch`.

For a TP2_HIT triggering BE: qty is `entry_qty*(1 - tp1_size - tp2_size)`,
state transitions to `tp2_then_scratch`.

## AC-OM-06: Terminal state name is the FSM's status, NOT "done"

Given an FSM that transitions to any terminal status
When `_dispatch` processes the `done` event
Then `setup_states.state` becomes the explicit terminal status string
(`wipeout`, `tp1_then_scratch`, `tp2_then_scratch`, `tp3_full`,
`no_trigger`, `no_entry`, `degenerate`, `open`) — NOT `"done"`.

Notes: regression bar. `tp3_hit` and `initial_sl_hit` are observational
events; the subsequent `done` carries the canonical terminal.

## AC-OM-07: Idempotent cloids per role

Given `arm_setup` is invoked for setup S
When the entry order is placed
Then the cloid equals `make_cloid(key(S), "entry")`. Re-issuing (e.g. via
the dry-walk + arm path) would produce the same cloid; HL's idempotency
prevents a duplicate live order.

## AC-OM-08: Write-ahead order persistence

Given any signed-call path (entry, SL, TPs, BE close)
When the OrderManager dispatches the call
Then `OrderRecord` is upserted in the state store BEFORE the signed call is
made (status="pending"). After the call returns, the same row is updated
(via the same cloid) with `status` mapped from the exchange's response.

Status mapping:
- exchange `resting` → DB `live`
- exchange `filled` → DB `filled`
- exchange `rejected` → DB `rejected`

## AC-OM-09: Exchange exceptions don't crash dispatch

Given the ExchangeClient raises on any place_*/cancel/market_close call
When dispatch invokes that call
Then the exception is logged (with traceback) and the corresponding
OrderRecord is marked `status="rejected"`. The FSM continues running.

## AC-OM-10: History dry-walk refuses to arm if FSM left ARMED

Given a `Setup` with a history candle list
When `arm_setup(setup, history)` is called and any candle in `history`
causes the FSM to transition out of ARMED (terminal break OR entry fill)
Then:
- `arm_setup` returns `None`
- No signed calls are dispatched
- The setup is upserted to the store with `setup_states.state == "missed"`
  and `payload.reason == "detection_gap"`

## AC-OM-11: Empty history arms normally

Given `arm_setup(setup, ())` (or `arm_setup(setup)`)
When the FSM is in ARMED state after construction
Then the place_entry path fires exactly once (AC-OM-01 behavior).

## AC-OM-12: Quiet history (no fill / no break) arms live

Given `arm_setup(setup, history)` where every candle in history leaves the
FSM in ARMED
Then arming proceeds as in AC-OM-01.

## AC-OM-13: Refuse zero-sized positions

Given `equity > 0` but `risk_per_unit == 0` (degenerate handled earlier) or
a configured `account_risk_pct` so small that qty rounds to 0
When `arm_setup` is called
Then the manager refuses to arm (returns `None`), no signed calls dispatched.

## AC-OM-13b: Position qty truncated to HL szDecimals

Given `qty_precision = {"BTC": 5}` (matching HL's BTC szDecimals)
When `_size_position(levels, "BTC")` would otherwise return e.g.
`917.4311926605505`
Then the returned value is `917.43119` — truncated (round-DOWN) to 5
decimals. Round-down so realized risk never exceeds the intended 1R from
over-rounding upward at the precision boundary.

For an asset NOT in `qty_precision`, default precision is 8 decimals
(effectively no rounding for normal sizes).

A computed raw qty smaller than `10^-precision` (e.g. equity so small that
qty rounds to 0) triggers AC-OM-13's refuse-to-arm path.

## AC-OM-13c: Live runner loads qty_precision from HL meta

Given `cmd_live` startup
When constructing the OrderManager
Then `signed.fetch_size_decimals()` is called once and the resulting
`coin -> szDecimals` map is passed as `qty_precision`. The signed client
sources the map from `Info.meta().universe[*].szDecimals`.

## AC-OM-13d: All placement prices pass through `round_price`

Given a setup whose strategy-computed prices are NOT on HL's tick grid
(e.g. entry=100.5912, init_sl=99.4995, tp1=101.183)
When the OrderManager dispatches place_entry / place_initial_sl /
place_tp1 / place_tp2 / place_tp3
Then the price passed to the signed client is `round_price(raw_price,
qty_precision[asset], is_perp=True)`. Both `OrderRecord.price` and the
signed-client call agree.

Notes: HL rejects orders whose price violates the 5-sig-fig / max-decimals
rules. Strategy code never produces guaranteed-valid prices; this layer is
the venue's contract.

## AC-OM-13e: Pre-flight min-notional refuses sub-min orders

Given `risk_cfg.min_notional_usd = 10.0` (HL's default)
And a setup whose `qty * round_price(entry)` is below `min_notional_usd`
When `arm_setup(setup)` is called
Then arming is refused (returns None), no signed calls dispatched, and the
log line includes `qty`, `entry_price`, `min_notional_usd`, and computed
`notional`.

## AC-OM-13f: TP partials re-rounded after fractional scaling

Given `entry_qty = 0.12345 BTC` (already at szDecimals=5)
And TP1 size_fraction = 0.25
Then the TP1 qty placed is `round_qty_down(0.12345 * 0.25, 5) == 0.03086`,
NOT `0.0308625` (which HL would reject for excess precision). Same applies
to TP2, TP3 partials, and the BE-close remainder.

If the rounded TP qty rounds to zero (very small position), the partial is
skipped with a warning, and the FSM continues. The remainder is still
exited at the next opportunity (TP3 or BE).

## AC-OM-13h: Refuse arms that exceed asset maxLeverage

Given `max_leverage = {"BTC": 40, ...}` (from HL meta)
And a setup whose `qty * round_price(entry)` exceeds `equity * 40`
When `arm_setup(setup)` is called
Then arming is refused (returns `None`), no signed calls dispatched, and
the log contains `notional`, `max_leverage`, `notional_cap`.

PRD §7.1 mandate: the strategy's 1.05 stop must sit INSIDE the
exchange-imposed liquidation. Without this cap, a tight-risk leg sizes a
position so large that HL would either reject the order outright or, if
accepted at lower leverage, liquidate before our SL fires.

An asset NOT present in `max_leverage` is treated as uncapped (no rejection
on this rule). The live runner always populates the map at startup.

## AC-OM-13i: Live runner loads max_leverage from HL meta

Given `cmd_live` startup
When constructing the OrderManager
Then `signed.fetch_max_leverage()` is called once and the resulting
`coin -> maxLeverage` map is passed as `max_leverage`. The signed client
sources the map from `Info.meta().universe[*].maxLeverage`.

## AC-OM-13g: Cancel retries with bounded backoff

Given `_cancel_if_known(...)` is called
Then the cancel is attempted up to `_CANCEL_MAX_ATTEMPTS = 3` times. Each
failed attempt sleeps `_CANCEL_BACKOFF_S * attempt` (0.5s, 1.0s) before
retrying. On success the helper returns `True`; after exhausting attempts
it logs ERROR with the last exception and returns `False`.

The dispatch path does NOT abort downstream actions on cancel failure
(documented bounded-loss risk: a wick to the original 1.05 SL between
TP1-fill and a successful future cancellation would flatten at -1R on the
remainder, capping loss at 1R worst case).

## AC-OM-14: `on_bar_close` skips unrelated assets

Given two active setups, one on BTC and one on ETH
When `on_bar_close(event)` is called with `event.asset == "BTC"`
Then the ETH FSM does not receive `on_bar(...)`.

## AC-OM-15: Equity refresh updates sizing for NEW arms only

Given `OrderManager(equity=E0)` with an active armed setup sized at `1R(E0)`
When `refresh_equity(E1)` is called
Then `self.equity == E1`. The existing setup's `entry_qty` is unchanged.
A subsequent `arm_setup` uses `E1` for sizing.

A non-positive `new_equity` is logged and ignored.

## AC-OM-RISK-01: arm_setup refuses on denied RiskDecision

Given an OrderManager with a `risk_engine`
And `risk_engine.can_arm(setup)` returns `allowed=False, reason=<X>,
payload=<P>`
When `arm_setup(setup)` is called
Then:
- No signed calls are dispatched
- The setup row is upserted
- `setup_states.state == "risk_blocked"` with payload
  `{"reason": <X>, "observation": <P>}`
- `arm_setup` returns `None`

The risk check runs FIRST (before FSM construction, sizing, etc.) so the
log line carries the same `reason` constant the operator sees in
`risk-status`.

When `risk_engine is None` (e.g. unit tests without one), no check runs
and arming proceeds as before.

## AC-OM-16: FSM removal from active dict after terminal

Given an active FSM that reaches a terminal state during `on_bar_close`
When the bar is processed
Then `active()` no longer contains that setup's key.
