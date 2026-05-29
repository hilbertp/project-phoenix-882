# DB1 Live Bot — Acceptance Criteria

This directory is the **canonical contract** for the live bot's behavior. Each
file under `docs/db1_live_bot_acs/` lists numbered ACs (acceptance criteria) for
one module of `apps/bot/`. Every AC describes a property that **must hold at
all times** — the regression suite (owned by Codex) turns each AC into a test.

## How to read an AC

ACs are written in `Given / When / Then` form (or a "must" assertion when the
preconditions are obvious). They describe externally observable behavior, not
internal implementation, so the regression suite stays decoupled from
refactors.

```
AC-NN: Short title

Given <preconditions>
When  <action>
Then  <observable outcome>

Notes: <optional implementation hints, anti-patterns to avoid, etc.>
```

## How to extend

When a new module ships or behavior changes, update the relevant AC file in
the **same PR**. ACs land first; the regression suite catches up. If a test
ever fails, the AC is the source of truth — fix the code, not the AC, unless
the AC is being deliberately revised (call that out in the PR).

## Module index

| File | Module | Scope |
| --- | --- | --- |
| [`rabby_agent.md`](rabby_agent.md) | **trust model** | Rabby (master) + HL agent — the ONLY supported auth pattern |
| [`config.md`](config.md) | `apps/bot/config.py` | TOML loader, env secrets, validation |
| [`logging.md`](logging.md) | `apps/bot/logging_setup.py` | Console + JSON file logging, secret redaction |
| [`state.md`](state.md) | `apps/bot/state.py` | SQLite schema, FSM persistence, durability |
| [`marketdata.md`](marketdata.md) | `apps/bot/marketdata.py` | Backfill + WS feed, bar-close emission |
| [`hyperliquid_public.md`](hyperliquid_public.md) | `apps/bot/exchange/hyperliquid.py` | Public REST + WS client |
| [`signed_client.md`](signed_client.md) | `apps/bot/exchange/signed_client.py` | Signed trading surface |
| [`venue.md`](venue.md) | `apps/bot/exchange/venue.py` | HL qty/price rounding + min-notional |
| [`levels.md`](levels.md) | `apps/bot/strategy/levels.py` | Fib level math |
| [`fsm.md`](fsm.md) | `apps/bot/strategy/fsm.py` | Per-setup state machine |
| [`cloid.md`](cloid.md) | `apps/bot/strategy/cloid.py` | Deterministic client_order_id |
| [`order_manager.md`](order_manager.md) | `apps/bot/strategy/order_manager.py` | FSM events → signed calls |
| [`reconciler.md`](reconciler.md) | `apps/bot/strategy/reconciler.py` | Startup state reconciliation |
| [`risk_engine.md`](risk_engine.md) | `apps/bot/risk/engine.py` | §7.2 per-trade pre-flight |
| [`kill_switch.md`](kill_switch.md) | `apps/bot/risk/kill_switch.py` | §7.3 halt + flatten-all |
| [`detector_loop.md`](detector_loop.md) | `apps/bot/strategy/detector_loop.py` | Bar-close → detector → setup |
| [`paper_executor.md`](paper_executor.md) | `apps/bot/simulation/paper_executor.py` | Historical replay |
| [`cli.md`](cli.md) | `apps/bot/__main__.py` | CLI surface + safety gates |

## Deferred tech debt

[`deferred_tech_debt.md`](deferred_tech_debt.md) holds ACs for contracts
whose implementation is intentionally deferred (log rotation, schema
migrations, detector perf cache, batched cancel+place atomicity, fill-stream
WS). Codex's regression suite encodes them now and marks the tests as
`pytest.skip` until the implementation lands — the contract is locked in
ahead of the code.

## Canonical correctness anchor

[`fsm_parity.md`](fsm_parity.md) defines the trade-by-trade parity contract
against `scripts/execute_fib_strategy.execute()`. The existing
`tests/test_bot_fsm_parity.py` is **kept as part of the regression suite** —
it's the canonical proof that the live FSM matches the validated backtest,
running over 5325+ legs spanning 8.75 years of BTC history. Do not delete it.

## Test ownership

`tests/test_bot_fsm_parity.py` is canonical. The other `tests/test_bot_*.py`
files in the repo are **dev-only iteration aids** written during development —
each has a header comment to that effect. Codex's regression suite is the
authoritative coverage based on the ACs in this directory; dev tests may be
deleted or absorbed into the regression suite at any time without losing
contract coverage.
