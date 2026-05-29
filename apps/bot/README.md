# apps/bot — DB1-Sniper live trading bot

Production execution system for the DB1 0.941 deep-entry Fibonacci strategy on
Hyperliquid perps. See [`docs/db1_live_bot_prd.md`](../../docs/db1_live_bot_prd.md)
for the full PRD (universe, FSM, risk limits, rollout phases, success metrics).

## Status

**M3 — Live order placement + reconciliation (code complete).** Signed
Hyperliquid client, FSM-driven OrderManager, deterministic cloid scheme,
software-side BE-drag close, startup reconciler, and a gated `live` CLI
command have all landed. The full live trading loop is wired end-to-end;
real-money execution requires `mode=live`, both HL env vars, AND a
`--yes-real-money` flag. **No live trading has been exercised yet** — the
intended rollout is paper → shadow → canary per PRD §10.

| Milestone | Scope | Status |
| --- | --- | --- |
| M1 | HL public client, market-data feed, detector loop emitting setups | done |
| M2 | Strategy Engine FSM + paper-trading simulator (full backtest parity) | done |
| M3 | Live order placement + BE-drag-in-software + reconciliation | done |
| M4 | Risk engine + kill switch + observability + Live dashboard tab | pending |
| M5 | Phase 1-2 (paper + shadow) | pending |
| M6 | Phase 3 canary | pending |
| M7 | Full ramp + ongoing operations | pending |

## Package layout

```
apps/bot/
├── __init__.py              # version string
├── __main__.py              # CLI: python -m apps.bot {detect,status,init-db,simulate}
├── config.py                # BotConfig + TOML loader + env secrets
├── logging_setup.py         # console + JSON-per-line file logging
├── state.py                 # SQLite state store: setups, FSM, orders, fills
├── marketdata.py            # MarketDataFeed (REST backfill + WS live updates)
├── exchange/
│   ├── __init__.py
│   ├── hyperliquid.py       # HyperliquidPublicClient (REST + WS, public only)
│   └── signed_client.py     # SignedHyperliquidClient (orders, cancels, fills)
├── strategy/
│   ├── __init__.py
│   ├── levels.py            # entry/SL/TP price math + R-ratios
│   ├── fsm.py               # FibFSM: armed → entered → tp1 → tp2 → done
│   ├── cloid.py             # deterministic client_order_id for idempotency
│   ├── detector_loop.py     # bar-close → swing_detector → state
│   ├── order_manager.py     # FsmEvents → signed exchange calls
│   └── reconciler.py        # startup: verify exchange ⇔ state.db agree
└── simulation/
    ├── __init__.py
    └── paper_executor.py    # drives FibFSM over historical candles
```

## Runtime dependencies

- `requests`, `websocket-client` — public HL market-data (M1).
- `hyperliquid-python-sdk` — signing & exchange surface (M3+). Brings in
  `eth-account` + friends. Read-only commands (`detect`, `status`, `simulate`)
  don't construct the signed client and work without HL credentials.

The ATR-zigzag swing detector lives in
[`apps/worker/discovery_bet_1/swing_detector.py`](../worker/discovery_bet_1/swing_detector.py)
and is shared with the backtest scripts. The script
[`scripts/place_fibs_tradingview.py`](../../scripts/place_fibs_tradingview.py)
re-exports it under the legacy `_clean_legs` name for backward compatibility.

## Run it

```bash
# One-shot: backfill 500 bars, run detector, persist setups, exit.
PYTHONPATH=. .venv/bin/python -m apps.bot detect --asset BTC --buffer-size 500 --once

# Continuous: open WS, log/persist new setups on every bar close.
PYTHONPATH=. .venv/bin/python -m apps.bot detect

# Inspect the state store.
PYTHONPATH=. .venv/bin/python -m apps.bot status --asset BTC --limit 20

# Replay history through the FSM and print a summary (paper backtest).
PYTHONPATH=. .venv/bin/python -m apps.bot simulate --asset BTC --buffer-size 5000

# Real-money trading. Refuses to start unless ALL gates pass:
#   1. config.mode == "live"
#   2. PHOENIX_HL_PRIVATE_KEY env set
#   3. PHOENIX_HL_ACCOUNT_ADDRESS env set
#   4. --yes-real-money flag
#   5. Startup reconciler returns CLEAN or RESUMABLE (not AMBIGUOUS)
PYTHONPATH=. .venv/bin/python -m apps.bot --config bot.toml live --yes-real-money
```

State DB lives at `data/bot/state.db` by default; structured JSON logs at
`data/bot/logs/bot.log` (console also shows a compact human-readable line).

## Configuration

Defaults match the PRD; no config file required to run the M1 detect loop.
Override with a TOML file via `--config path/to/bot.toml` or the
`PHOENIX_BOT_CONFIG` environment variable.

```toml
[bot]
mode = "paper"                 # paper | shadow | live (only "paper" honored in M1)
state_db_path = "data/bot/state.db"
log_dir = "data/bot/logs"

[universe]
assets = ["BTC", "ETH", "BNB", "ADA", "XRP", "SOL", "HYPE"]

[detector]
min_bars = 6
mult = 2.0
interval = "1h"

[strategy]
entry_coeff = 0.941
init_sl_coeff = 1.05
tp1_coeff = 0.882
tp2_coeff = 0.5
tp3_coeff = 0.0
tp1_size = 0.25
tp2_size = 0.60
tp3_size = 0.15

[risk]
account_risk_pct = 1.0
max_concurrent_positions = 4
max_trades_per_asset_per_day = 6
daily_loss_r_limit = -3.0
weekly_loss_r_limit = -8.0
consecutive_loss_limit = 5
slippage_alert_pct = 0.3
adverse_funding_apy_skip = 100.0

[hyperliquid]
testnet = false                # set true to flip REST/WS to the HL testnet URLs
```

Secrets live in env, never in TOML:

- `PHOENIX_HL_ACCOUNT_ADDRESS` — your MASTER (Rabby-controlled) wallet
  address on Hyperliquid
- `PHOENIX_HL_AGENT_PRIVATE_KEY` — the AGENT key Rabby approved for
  trading. Never the master key. See "Wallet / Rabby setup" below.

## Wallet / Rabby setup

The bot uses Hyperliquid's **agent wallet** mechanism exclusively:

1. Your funds stay in your Rabby-controlled wallet (the "master"). Rabby
   is the only path to deposit/withdraw.
2. You generate an "agent" keypair via HL's web UI (one-time approval
   signed in Rabby). The agent can sign trades for the master account but
   **cannot withdraw**.
3. The bot loads the agent key from env. The master key never touches the
   bot.

### One-time setup

1. Open https://app.hyperliquid.xyz with Rabby installed.
2. Connect Rabby (this wallet is your master).
3. Navigate to **API** → **Generate**. Sign the approval action in Rabby
   when prompted.
4. Copy the agent private key from the HL UI (shown only once).
5. Set both env vars before running the bot:
   ```bash
   export PHOENIX_HL_AGENT_PRIVATE_KEY=0x<agent-private-key>
   export PHOENIX_HL_ACCOUNT_ADDRESS=0x<master-rabby-address>
   ```

The bot validates at startup that the loaded agent is still approved on
HL for your master account; if you revoke the agent in Rabby, the bot
exits cleanly on the next start. See
[`docs/db1_live_bot_acs/rabby_agent.md`](../../docs/db1_live_bot_acs/rabby_agent.md)
for the full trust-model contract.

## Tests

The **regression suite is owned by Codex** and is driven by the Acceptance
Criteria in [`docs/db1_live_bot_acs/`](../../docs/db1_live_bot_acs/). Those
ACs are the canonical contract that must hold at all times; if a test fails,
the AC is the source of truth.

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_bot_*.py -v
```

In this repo, only one bot test is canonical — kept as a regression bar:

- [`tests/test_bot_fsm_parity.py`](../../tests/test_bot_fsm_parity.py) —
  the FSM/simulator reproduces `scripts/execute_fib_strategy.execute()`
  trade-by-trade across the corrected swings, every detected leg on the
  12-month BTC dataset (both detector configurations), and 5325+ legs across
  8.75 years of BTC long-history (PRD §10 Phase 0 exit criterion). See
  [`docs/db1_live_bot_acs/fsm_parity.md`](../../docs/db1_live_bot_acs/fsm_parity.md).

The other `tests/test_bot_*.py` files are **DEV-ONLY iteration aids** kept
for fast feedback during development. Each carries a header comment to that
effect; Codex's regression suite is the authoritative coverage.

## What's deliberately NOT here yet

- **No risk-engine enforcement.** Limits from PRD §7 are in config but no code
  refuses to arm a setup when, say, daily_loss_r_limit would be breached. M4.
- **No live dashboard tab.** The "Live" tab on `scripts/dashboard_server.py`
  arrives with M4.
- **No fill-stream subscription.** M3 trusts the FSM's bar-derived view of when
  TPs fire. M4 will subscribe to the HL user-data WS channel and reconcile
  fills as they arrive — important for partial-fill handling and slippage
  accounting.
- **No automated FSM rehydration.** The reconciler categorizes mid-flight
  setups but does not auto-rebuild a paused FSM at the correct state on
  restart. AMBIGUOUS halts; RESUMABLE prints a summary and the operator can
  proceed (the active FSM dict is empty so no new actions fire, but resting
  orders remain on the exchange).
