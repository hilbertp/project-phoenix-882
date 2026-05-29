# ACs — `apps/bot/config.py`

The config layer is a pure dataclass tree loaded from TOML, with secrets
exclusively from env. Defaults mirror PRD §4 / §7.

## AC-CFG-01: Default config matches PRD

Given no config file and no env vars
When `load_config()` is called with no argument
Then the returned `BotConfig` has:
- `mode == "paper"`
- `universe == ("BTC", "ETH", "BNB", "ADA", "XRP", "SOL", "HYPE")`
- `detector.min_bars == 6`, `detector.mult == 2.0`, `detector.interval == "1h"`
- `strategy.entry_coeff == 0.941`, `init_sl_coeff == 1.05`,
  `tp1_coeff == 0.882`, `tp2_coeff == 0.5`, `tp3_coeff == 0.0`
- `strategy.tp1_size == 0.25`, `tp2_size == 0.60`, `tp3_size == 0.15`
- `risk.account_risk_pct == 1.0`
- `hyperliquid.testnet == False`
- `hyperliquid.rest_url == "https://api.hyperliquid.xyz"`
- `hyperliquid.account_address is None`

## AC-CFG-02: TOML overrides apply only where set

Given a TOML file that overrides `[detector] mult = 3.0`
When loaded
Then `cfg.detector.mult == 3.0` and every other field equals its default.

## AC-CFG-03: Unknown TOML keys are rejected

Given a TOML file with `[detector] unknown_key = 1`
When loaded
Then `ValueError` is raised and the message names the offending field.

## AC-CFG-04: Mode whitelist is `{paper, live}`

Given a TOML file with `[bot] mode = "shadow"` (or any string outside the
whitelist)
When loaded
Then `ValueError` is raised.

Notes: Shadow mode is on the roadmap (real orders at HL minimum notional) but
not implemented; validation must reject it until it is. The accepted values
are exactly `paper` and `live`.

## AC-CFG-05: TP sizes must sum to 1.0

Given a TOML file with `[strategy] tp1_size = 0.5, tp2_size = 0.3, tp3_size = 0.3`
When loaded
Then `ValueError` is raised.

## AC-CFG-06: `account_risk_pct` constrained to `(0, 100]`

Given a TOML file with `[risk] account_risk_pct = 0` (or negative, or > 100)
When loaded
Then `ValueError` is raised.

## AC-CFG-07: `entry_coeff < init_sl_coeff`

Given a TOML file with `[strategy] entry_coeff = 1.1, init_sl_coeff = 1.0`
When loaded
Then `ValueError` is raised. (Inverted strategy geometry must never load.)

## AC-CFG-08: Testnet URL substitution

Given `[hyperliquid] testnet = true` and no explicit `rest_url`/`ws_url`
override
When loaded
Then `cfg.hyperliquid.rest_url == "https://api.hyperliquid-testnet.xyz"` and
`cfg.hyperliquid.ws_url == "wss://api.hyperliquid-testnet.xyz/ws"`.

When `testnet = true` AND `rest_url` is explicitly set in the TOML, the
explicit value wins.

## AC-CFG-09: Account address from env, not TOML

Given env `PHOENIX_HL_ACCOUNT_ADDRESS=0xabc...`
When loaded
Then `cfg.hyperliquid.account_address == "0xabc..."`.

When no env var is set, `account_address is None` — even if a (rejected) TOML
config attempts to set it.

## AC-CFG-10: Agent key NEVER on `BotConfig`

Given env `PHOENIX_HL_AGENT_PRIVATE_KEY=...` (canonical) or
`PHOENIX_HL_PRIVATE_KEY=...` (deprecated)
When `load_config()` is called
Then no field of any returned dataclass (recursively) contains the key
string. The helper `hl_agent_private_key()` reads env on demand and is the
only path the signed client uses. The master private key is NEVER read
from anywhere — it lives in Rabby.

See `rabby_agent.md` (AC-RABBY-02) for the deprecation behavior of the
legacy var name.

Notes: defense in depth; combined with the secret-redacting log filter.

## AC-CFG-11: Missing config file raises `FileNotFoundError`

Given a `--config /does/not/exist.toml`
When `load_config(path)` is called
Then `FileNotFoundError` is raised (not silently ignored).

## AC-CFG-12: `BotConfig` is immutable

Given a loaded `BotConfig`
When code attempts `cfg.mode = "live"`
Then an attribute-error is raised. The dataclasses are `frozen=True` to
prevent late mutation that could silently change strategy at runtime.

## AC-CFG-13: `PHOENIX_BOT_CONFIG` env fallback

Given env `PHOENIX_BOT_CONFIG=/path/to/bot.toml`
When `load_config()` is called with no explicit path
Then the file at the env path is loaded.

Explicit `path` argument wins over the env var.
