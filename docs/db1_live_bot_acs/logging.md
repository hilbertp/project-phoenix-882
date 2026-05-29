# ACs — `apps/bot/logging_setup.py`

Structured logging with two sinks (compact console + JSON file). Secret
redaction is non-negotiable.

## AC-LOG-01: Configure is idempotent

Given `configure_logging()` has already been called once
When it is called again
Then it is a no-op (no duplicate handlers attached to the root logger).

## AC-LOG-02: Console format is `HH:MM:SS LEVEL logger event extras`

Given `configure_logging()` followed by `log.info("hello", extra={"k": "v"})`
Then the stderr output contains the message and `k=v`.

## AC-LOG-03: JSON file emits one JSON object per line

Given `configure_logging(log_dir)` followed by `log.info("event", extra=…)`
Then `<log_dir>/bot.log` contains a single JSON line with fields:
- `ts` (ISO-8601 UTC)
- `level`
- `logger`
- `event` (the message string)
- every key from `extra` (after redaction; see AC-LOG-05)

## AC-LOG-04: Exception `exc` field

Given `log.exception("boom")` inside an `except` block
Then the JSON file's record contains an `exc` field with the formatted
traceback.

## AC-LOG-05: Secret redaction in BOTH formatters

Given `log.info("...", extra={"private_key": "abc", "api_token": "xyz",
"password": "p"})`
Then both the console line and the JSON record show `***REDACTED***` for
each of `private_key`, `api_token`, `password`.

The pattern matches case-insensitively against these substrings in the
extra-field NAME (not value): `private`, `secret`, `password` (or `passwd`),
`token`, `api_key` / `api-key`, `wallet_key` / `wallet-key`,
`signing_key` / `signing-key`, `mnemonic`, `seed`.

Notes: defense in depth even though `hl_private_key()` should never be
passed through `extra=`.

## AC-LOG-06: Non-secret fields pass through unchanged

Given `log.info("...", extra={"asset": "BTC", "qty": 1.5, "address": "0xabc"})`
Then those keys appear verbatim in both formatters (no false-positive
redaction). In particular `address` and `asset` and price/quantity fields
must remain readable for debugging.

## AC-LOG-07: Log directory created on demand

Given `log_dir=/tmp/nonexistent-X` (parent exists, leaf does not)
When `configure_logging(log_dir)`
Then `/tmp/nonexistent-X` is created with `parents=True, exist_ok=True`.

## AC-LOG-08: Console-only mode

Given `configure_logging(log_dir=None)`
Then a console handler is attached but no file handler is created.
