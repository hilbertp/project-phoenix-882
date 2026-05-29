# ACs — `apps/bot/risk/kill_switch.py`

PRD §7.3 contract: the kill switch cancels every open order, market-flats
every position, sets a halt flag, and refuses every subsequent `can_arm`
until the operator clears it.

## AC-KILL-01: `is_halted()` reads the halt flag

Given `runtime_flags.halt` is non-null
Then `KillSwitch.is_halted()` returns `True`.

When the flag is unset, returns `False`.

## AC-KILL-02: `halt_reason()` exposes the reason string

Given `runtime_flags.halt = "operator_command"`
Then `KillSwitch.halt_reason() == "operator_command"`.

When unset, returns `None`.

## AC-KILL-03: `fire(reason)` sets the halt flag with the reason

Given `kill.fire("daily_loss_limit_breach")`
Then `runtime_flags.halt == "daily_loss_limit_breach"` AND the returned
`KillSwitchSummary.reason == "daily_loss_limit_breach"`.

## AC-KILL-04: `fire()` cancels every open order

Given the exchange has N open orders, each with a cloid
When `kill.fire(reason)` is called
Then `client.cancel(coin, cloid)` is invoked for each. Successes appear
in `summary.cancelled_orders`; failures in `summary.cancel_failures` with
log lines.

An order without a cloid cannot be cancelled via our API; it lands in
`summary.cancel_failures` as `unknown-cloid:<oid>` and an ERROR log is
emitted (operator MUST inspect).

## AC-KILL-05: `fire()` market-closes every open position

Given the exchange reports positions with non-zero `size`
When `kill.fire(reason)` is called
Then `client.market_close(coin, qty=abs(size), cloid=fresh_cloid)` is
invoked for each. Successes append to `summary.closed_positions`;
failures to `summary.close_failures` with log lines.

Each market-close uses a fresh deterministic cloid derived from
`(setup_key="kill|<coin>|<halted_at>", role="flatten", seq=<epoch_ms>)`
so retries don't conflict with prior fire() attempts.

## AC-KILL-06: `fire()` is idempotent — first reason wins

Given a previous `fire("reason_A")` left `runtime_flags.halt = "reason_A"`
When `fire("reason_B")` is called
Then the flag value is unchanged (still `reason_A`), a warning logs
`new_reason=reason_B, original_reason=reason_A`, AND the flatten pass
runs again (capturing any residual orders/positions that appeared since).

`summary.reason == "reason_A"` (the original) for audit traceability.

## AC-KILL-07: `re_arm()` clears the halt flag

Given `kill.fire(...)` was called
When `kill.re_arm()` is called
Then `runtime_flags.halt` is cleared. Subsequent `is_halted() == False`.

`re_arm()` on a non-halted bot is a no-op.

## AC-KILL-08: `summary.ok()` is True iff no failures

Given `cancel_failures == []` AND `close_failures == []`
Then `summary.ok() == True`.

Otherwise `False`. The CLI uses this to set exit code (0 vs 8).

## AC-KILL-09: Exchange RPC errors during fire don't crash

Given `client.open_orders()` or `client.positions()` raises an exception
When `fire(reason)` is called
Then the exception is logged via `log.exception(...)` and the function
continues — the halt flag IS still set, but the corresponding flatten
loop sees an empty list. The operator can re-run `fire` once the RPC
recovers.

## AC-KILL-10: `risk-status` CLI surfaces halt state

(See `cli.md` AC-CLI-RISK-01.)

When the operator runs `python -m apps.bot risk-status`, the printed
snapshot includes the `halted` and `halt_reason` fields from
`RiskEngine.status_snapshot()`.
