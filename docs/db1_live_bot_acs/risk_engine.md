# ACs — `apps/bot/risk/engine.py`

Per-trade pre-flight enforcing PRD §7.2 account-level limits. The
`RiskEngine.can_arm(setup)` decision is pure (no side-effects); the
OrderManager calls it before constructing the FSM.

## Reason vocabulary (stable string identifiers)

`RiskDecision.reason` ∈ {
  `ok`, `halted`, `max_concurrent_positions`,
  `max_trades_per_asset_per_day`, `daily_loss_r_limit`,
  `weekly_loss_r_limit`, `consecutive_loss_limit`, `adverse_funding`
}.

## AC-RISK-01: Clean state allows the arm

Given no halt, no in-flight setups, no recent terminal setups, no funding
pause flags
When `engine.can_arm(setup)` is called
Then `decision.allowed == True` AND `decision.reason == "ok"`.

## AC-RISK-02: Halt flag refuses everything

Given `runtime_flags.halt` is set to any non-null value
When `engine.can_arm(setup)` is called for any asset
Then `decision.allowed == False` AND `decision.reason == "halted"`.

## AC-RISK-03: Funding-skip pauses only the named asset

Given `runtime_flags['pause_asset:BTC'] = "..."`
When `engine.can_arm(setup)` is called
Then:
- For setup.asset == "BTC": refused with reason `adverse_funding`,
  payload `{"asset": "BTC"}`.
- For setup.asset == "ETH" (or any other): allowed.

## AC-RISK-04: Max concurrent positions

Given `risk_cfg.max_concurrent_positions == N`
And N setups exist in any state from `{armed, entered, tp1_hit, tp2_hit}`
When `engine.can_arm(setup)` is called for ANY asset
Then refused with reason `max_concurrent_positions`,
payload `{"current": N, "limit": N}`.

`tp3_full`, `wipeout`, terminal-scratch, `no_trigger`, `no_entry`,
`degenerate`, `missed`, `risk_blocked` do NOT count as in-flight.

## AC-RISK-05: Max trades per asset per UTC day

Given `risk_cfg.max_trades_per_asset_per_day == M`
And M `setups` rows exist for asset X with `detected_at >= today_utc_00`
When `engine.can_arm(setup_for_X)` is called
Then refused with reason `max_trades_per_asset_per_day`,
payload includes `today` (count), `limit`, `day_start_utc`.

Setups detected before today's UTC midnight do NOT count.

## AC-RISK-06: Daily realized loss limit (UTC day boundary)

Given `risk_cfg.daily_loss_r_limit == -3.0`
And the sum of `realized_r` payloads on terminal setups since today's UTC
midnight is `<= -3.0`
When `engine.can_arm(setup)` is called for any asset
Then refused with reason `daily_loss_r_limit`,
payload includes `daily_r`, `limit`, `day_start_utc`.

Sum window resets every UTC midnight.

## AC-RISK-07: Weekly realized loss limit (rolling 7 days)

Given `risk_cfg.weekly_loss_r_limit == -8.0`
And the sum of `realized_r` over terminal setups in the last 7 days is
`<= -8.0`
When `engine.can_arm(setup)` is called
Then refused with reason `weekly_loss_r_limit`,
payload includes `week_r`, `limit`, `week_start_utc`.

Window is rolling (now - 7 days), not calendar.

## AC-RISK-08: Consecutive losses

Given `risk_cfg.consecutive_loss_limit == 5`
And the most-recent 5 terminal setups (by `updated_at` desc) are ALL
`state == "wipeout"`
When `engine.can_arm(setup)` is called
Then refused with reason `consecutive_loss_limit`,
payload `{"consecutive_losses": 5, "limit": 5}`.

A non-wipeout terminal at the head resets the streak (counted as zero).

Notes: this overlaps with the daily/weekly R limits; both may match. The
engine returns the FIRST matching reason in its check order:
`halted → funding → max_concurrent → max_per_asset_day → daily_loss →
weekly_loss → consec_loss`.

## AC-RISK-09: status_snapshot includes every counter

Given any state
When `engine.status_snapshot()` is called
Then the returned dict has keys: `halted`, `halt_reason`,
`concurrent_positions`, `max_concurrent_positions`, `daily_realized_r`,
`daily_loss_r_limit`, `weekly_realized_r`, `weekly_loss_r_limit`,
`consecutive_losses`, `consecutive_loss_limit`, `paused_assets`
(sorted list of asset symbols).

## AC-RISK-10: pause_asset_funding / resume_asset_funding

Given `engine.pause_asset_funding("BTC", apy=120.5)`
Then `runtime_flags['pause_asset:BTC']` is set with the apy embedded in
the value (for visibility from `risk-status`). Subsequent
`can_arm(setup_for_BTC)` refuses with reason `adverse_funding`.

Given `engine.resume_asset_funding("BTC")`
Then the flag is cleared.

## AC-RISK-11: Refused arm writes state="risk_blocked"

(See `order_manager.md` AC-OM-RISK-01.)

When the OrderManager receives a denied RiskDecision in `arm_setup`, it
upserts the setup AND writes `setup_states.state = "risk_blocked"` with
payload `{"reason": decision.reason, "observation": decision.payload}`.
This makes a denial discoverable in `risk-status` and the dashboard.
