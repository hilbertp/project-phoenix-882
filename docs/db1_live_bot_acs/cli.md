# ACs — `apps/bot/__main__.py`

CLI surface + the live-mode safety gates. These ACs are the **last line of
defense before real money** — every gate must refuse to start when its
precondition is not met.

## AC-CLI-01: Subcommands available

Given `python -m apps.bot --help`
Then the help text lists subcommands: `init-db`, `status`, `detect`,
`simulate`, `live`.

## AC-CLI-02: `init-db` creates the schema

Given `cfg.state_db_path` does not yet exist
When `python -m apps.bot init-db` runs
Then the file is created and `schema_meta` has a row.

## AC-CLI-03: `status` lists recent setups

Given the state store has at least one setup
When `python -m apps.bot status` runs
Then stdout contains an ASCII table of recent setups with columns asset,
dir, parent_ts, term_ts, parent, term, state.

`--asset BTC --limit 5` filters and limits.

## AC-CLI-04: `detect --once` exits after one pass

Given any universe
When `python -m apps.bot detect --asset BTC --buffer-size 100 --once` runs
Then it backfills, runs the detector once on the buffer, persists new setups,
and exits with code 0 (no live WS subscription).

## AC-CLI-05: `simulate` produces a summary

Given any asset
When `python -m apps.bot simulate --asset BTC --buffer-size 2000` runs
Then stdout contains lines: `legs detected:`, `triggered (filled):`,
`total R:`, `avg R per trade:`, `win rate (TP1+):`, and a `by outcome:`
breakdown.

## AC-CLI-06: `live` refuses without `mode==live`

Given `cfg.mode == "paper"`
When `python -m apps.bot live --yes-real-money` runs
Then it prints `REFUSING to start live trading. Missing requirements:`
followed by `config.mode must be "live"`. Exit code is non-zero (specifically
`2`).

## AC-CLI-07: `live` refuses without `--yes-real-money`

Given `cfg.mode == "live"` AND both env vars present
When `python -m apps.bot live` runs (no `--yes-real-money`)
Then it refuses with the missing-flag message. Exit code `2`.

## AC-CLI-08: `live` refuses without both env vars

Given `cfg.mode == "live"` AND `--yes-real-money` AND only ONE of
`PHOENIX_HL_AGENT_PRIVATE_KEY` / `PHOENIX_HL_ACCOUNT_ADDRESS` set
When `python -m apps.bot live --yes-real-money` runs
Then it refuses with the missing-env message. Exit code `2`. The message
names the canonical `PHOENIX_HL_AGENT_PRIVATE_KEY` (NOT the deprecated
`PHOENIX_HL_PRIVATE_KEY`).

## AC-CLI-09: `live` refuses on AMBIGUOUS reconciliation

Given all four gates pass
When the reconciler returns `category=AMBIGUOUS`
Then the runner refuses with exit code `3` and prints the reconciliation
summary including issues.

## AC-CLI-10: `live` refuses RESUMABLE with in-flight setups unless --accept-orphan-positions

Given all four gates pass AND reconciler returns `category=RESUMABLE`
with `in_flight_setups != []`
When the runner is invoked WITHOUT `--accept-orphan-positions`
Then it refuses with exit code `5` and a message explaining that BE-drag
will not run for orphan in-flight setups.

When `--accept-orphan-positions` is passed, the runner proceeds with a
prominent warning logged.

## AC-CLI-10b: `live` refuses unapproved agent

Given all four prior gates pass AND reconciliation passes (CLEAN /
RESUMABLE)
When `signed.agent_is_approved()` returns `False`
Then the runner exits with code `6` and logs a message instructing the
operator to re-approve the agent via Rabby on app.hyperliquid.xyz. See
`rabby_agent.md` AC-RABBY-04 / AC-RABBY-05.

## AC-CLI-11: `live` refuses zero or negative equity

Given all four gates pass AND reconciler passes
When `Info.user_state(address)` returns `marginSummary.accountValue <= 0`
Then the runner refuses with exit code `4`.

## AC-CLI-12: `live` picks up stranded `detected` setups at startup

Given the state store contains setups with `setup_states.state == "detected"`
that the OrderManager has not yet armed
When `live` starts (after backfill, before going into the loop)
Then `OrderManager.arm_setup(...)` is invoked for each such setup with the
appropriate history slice from the backfilled buffer.

## AC-CLI-13: Read-only commands work without HL credentials

Given no `PHOENIX_HL_AGENT_PRIVATE_KEY` / `PHOENIX_HL_ACCOUNT_ADDRESS` env
When `python -m apps.bot {detect,status,simulate,init-db,risk-status,re-arm}`
runs
Then the command succeeds. (None of these construct
`SignedHyperliquidClient`.)

## AC-CLI-14: `live` refuses on halt flag without --rearm-on-start

Given the kill switch was fired previously (`runtime_flags.halt` set)
When `python -m apps.bot live --yes-real-money` runs WITHOUT
`--rearm-on-start`
Then the runner exits with code `7` and logs `halt_reason` along with the
remediation hint.

With `--rearm-on-start`, the runner clears the flag with a warning and
proceeds (subject to the other gates).

## AC-CLI-RISK-01: `risk-status` prints engine snapshot

Given the state DB exists
When `python -m apps.bot risk-status` runs
Then stdout contains the lines: `halted`, `halt_reason`,
`concurrent_positions`, `max_concurrent_positions`, `daily_realized_r`,
`daily_loss_r_limit`, `weekly_realized_r`, `weekly_loss_r_limit`,
`consecutive_losses`, `consecutive_loss_limit`, `paused_assets`. Exit
code `0`.

## AC-CLI-RISK-02: `re-arm` clears the halt flag

Given `runtime_flags.halt` is set to "test_reason"
When `python -m apps.bot re-arm` runs
Then stdout includes `cleared halt flag (was: 'test_reason')`. Exit
code `0`. Subsequent `risk-status` shows `halted: False`.

When `halt` is unset, stdout is `not halted; nothing to do`. Exit code `0`.

## AC-CLI-KILL-01: `kill` requires the same gates as `live`

Given missing any of:
  - `PHOENIX_HL_AGENT_PRIVATE_KEY` env
  - `PHOENIX_HL_ACCOUNT_ADDRESS` env
  - `--yes-real-money` flag
  - `--reason` (required argparse arg)
When `python -m apps.bot kill --reason ...` runs
Then it refuses with the same message style as `live` and exit code `2`
(or argparse error for missing `--reason`).

## AC-CLI-KILL-02: `kill --reason "X"` fires the kill switch

Given all four gates pass AND a valid `--reason`
When `python -m apps.bot kill --reason "manual_operator" --yes-real-money`
runs
Then `KillSwitch.fire("manual_operator")` is called, summary fields are
printed (`halted_at`, `reason`, counts, `ok`), and exit code is `0` if
`summary.ok() == True` else `8`.
