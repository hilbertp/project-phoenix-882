# ACs — Rabby + Hyperliquid agent trust model

The bot trades on Hyperliquid via an **agent wallet** that the user's
**Rabby-controlled master wallet** has approved. This is the only supported
authentication pattern. PRD §9 mandates "trading permission only — never
withdrawal"; the HL agent mechanism is exactly that.

## Trust model (immutable)

- **Master wallet** = the user's funds-holding wallet, controlled by Rabby.
  Holds USDC on HL, signs deposits/withdrawals. The bot NEVER sees this key.
- **Agent wallet** = a separate keypair the user generates (via the HL web
  UI at `app.hyperliquid.xyz` while connected through Rabby). One-time
  approval signed by the master in Rabby grants the agent trading
  permission for the master account.
- Bot env:
  - `PHOENIX_HL_AGENT_PRIVATE_KEY` — the AGENT key (signs trades)
  - `PHOENIX_HL_ACCOUNT_ADDRESS` — the MASTER address (Rabby wallet)
- Revocation: the user revokes the agent in Rabby at any time. The bot
  detects this at next startup (AC-RABBY-04) and refuses to operate.

## User onboarding flow

1. Open https://app.hyperliquid.xyz in a browser with the Rabby extension.
2. Connect Rabby. The wallet you connect IS the master.
3. Navigate to API → Generate. A modal asks Rabby to sign an approve-agent
   action. Confirm in Rabby.
4. The UI displays the agent private key ONCE — copy it.
5. Set env vars before running the bot:
   ```
   export PHOENIX_HL_AGENT_PRIVATE_KEY=0x<agent-private-key>
   export PHOENIX_HL_ACCOUNT_ADDRESS=0x<master-rabby-address>
   ```
6. Run `python -m apps.bot live --yes-real-money` (with mode=live in config).

## AC-RABBY-01: Bot NEVER reads a master private key

Given any code path
When the bot runs
Then it does not call `Account.from_key(master_private_key)` or read any
env var named to suggest the master key. The single signing key loaded is
`PHOENIX_HL_AGENT_PRIVATE_KEY`.

## AC-RABBY-02: Env var deprecation back-compat

Given env `PHOENIX_HL_PRIVATE_KEY` (legacy name) is set
And `PHOENIX_HL_AGENT_PRIVATE_KEY` is NOT set
When `hl_agent_private_key()` is called
Then the legacy value is returned AND a deprecation warning is logged
naming the new variable.

If both are set, the canonical name (`PHOENIX_HL_AGENT_PRIVATE_KEY`) wins.

## AC-RABBY-03: SignedHyperliquidClient exposes agent_address

Given `SignedHyperliquidClient(agent_private_key=K, master_account_address=M)`
Then `client.agent_address` equals `eth_account.Account.from_key(K).address`
AND `client.master_address` equals `M`. The agent_address is computed once
at construction and reused (never re-derived from the key).

## AC-RABBY-04: Startup approval check (`agent_is_approved()`)

Given `SignedHyperliquidClient.agent_is_approved()` is called
Then it queries `Info.extra_agents(master_address)` and returns `True`
iff `agent_address` (case-insensitive) appears in the returned list.

Returns `False` (without raising) on any RPC error. The caller decides
how to act on a False result.

## AC-RABBY-05: `cmd live` refuses on unapproved agent

Given all four safety gates pass (mode=live, agent env, master env,
--yes-real-money) and reconciliation passes
When `signed.agent_is_approved()` returns False
Then the live runner exits with code `6` and a log line explaining the
user must re-approve the agent via Rabby.

## AC-RABBY-06: Agent key cannot withdraw

This is enforced by Hyperliquid, not the bot. Any code path that
constructs `SignedHyperliquidClient` MUST NOT also call HL methods
that the agent role cannot perform (withdrawals, transfers, agent
self-revocation). The bot's SignedHyperliquidClient surface explicitly
omits these methods — adding them would be a contract violation.

## AC-RABBY-07: Re-approval flow

Given the agent has been revoked OR expired
When the user re-approves via Rabby with the SAME agent key
Then no env vars need to change — the next bot start succeeds (AC-RABBY-04
returns True after the re-approval lands on-chain).

When the user generates a NEW agent key in HL's UI, they update
`PHOENIX_HL_AGENT_PRIVATE_KEY` and restart the bot.
