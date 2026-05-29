# PRD — DB1 Live Trading Bot (Hyperliquid)

**Owner:** TBD &nbsp;·&nbsp; **Status:** Draft v1 &nbsp;·&nbsp; **Depends on:** the DB1 strategy/executor in `apps/worker/discovery_bet_1` + `scripts/execute_fib_strategy.py`

---

## 1. Summary

Build an automated trading bot — internal codename **DB1-Sniper** — that executes
the validated DB1 Fibonacci **0.941 deep-entry** strategy on **Hyperliquid perps**
across a curated universe of top crypto majors. Goal: convert the backtested edge
(~+14 R/month median net at Hyperliquid maker fees, on 9 years × 7 assets) into
live PnL with strict risk management and full operational observability.

This is not a research framework — it's a production execution system that mirrors
the backtest as closely as possible, with safety, recovery, and monitoring as
first-class requirements.

---

## 2. Background

The DB1 strategy was developed and backtested across BTC, ETH, BNB, ADA, XRP, SOL,
HYPE, and TRX (BTCUSDT spot history 2017-08 → 2026-05; ~5.8–8.8 years per asset
via Binance public klines). At fine detection (6-candle minimum / 2.0× ATR-zigzag)
and the 0.941 sniper entry, gross results were:

- **Median +16.7 R/month, range +13.9 to +16.9** across 7 assets.
- **Every year, every market regime, every month-of-year positive** in 9 years.
- **Worst single month across all 7 assets × 9 years: −8.5R** (TRX, 2021-04).
- No losing-month streaks exceeded 1 month *anywhere* in the dataset.

Net of Hyperliquid maker fees (0.03% RT), median **+14.4 R/month** survives across
the same 7 assets. The 0.941 entry dominates 0.882 and 0.786 by 2–5× on net
R/month, so the bot focuses on 0.941 as its primary mode in v1.

Reference: `scripts/backtest_long_summary.py`, the long-history datasets in
`data/discovery_bet_1/binance_*_1h_full_history.csv`, and the dashboard at
`scripts/dashboard_server.py`.

---

## 3. Goals & non-goals

### Goals (v1)

- **G1.** Place and manage live 0.941-entry trades on HL perps for the configured
  universe, faithful to the backtest executor's semantics.
- **G2.** Enforce strict per-trade and account-level risk limits.
- **G3.** Resilient to crashes, restarts, exchange disconnects, and ambiguous
  exchange state — never double-enter, never orphan a stop.
- **G4.** Observable in real time: open positions, today's PnL, recent trades,
  health signals, alerts on anomalies.
- **G5.** Safe rollout path: paper → shadow → canary → full size.
- **G6.** Live PnL within ±15% of the backtested counterfactual over the first
  90 days (variance budget for fills/slippage/funding).

### Non-goals (v1)

- Multi-exchange (HL only). Spot markets. Cross-asset hedging.
- The scaled tranche strategy and the 0.882/0.786 regimes (v1 is **0.941 only**;
  the executor will keep them codified for v2).
- Discretionary overrides or operator manual trading via the bot.
- ML / regime-switching / adaptive parameters.
- End-user UI for non-operators.

---

## 4. Strategy specification

This is the formal contract the bot must implement. All semantics MUST match the
existing executor (`scripts/execute_fib_strategy.execute()`).

### 4.1 Universe (v1 default)

`BTC · ETH · BNB · ADA · XRP · SOL · HYPE` — the 7 majors that net-positive at HL
maker fees on the 8+ year backtest. TRX is excluded by default (marginal at
non-maker fees); operator may opt in via config.

### 4.2 Detector

Per-asset ATR-zigzag swing detector (`_clean_legs` in
`scripts/place_fibs_tradingview.py`), default config `min_bars=6, mult=2.0`. A
"setup" is a finalized leg with a parent anchor and a terminal extreme. Detector
runs on **1H bar close** and only on a fully-closed bar.

### 4.3 Phoenix Fib geometry

`1.0 = parent`, `0.0 = terminal`, `1.05 = stop`. Entries and TPs are linear in the
leg (`_lvl(terminal, parent, coeff)`).

### 4.4 Entry / SL / TP plan (the "sniper")

| level | coeff | action | size |
|---|---|---|---|
| entry | 0.941 | open position | 100% |
| initial SL | 1.05 | flat the position | — |
| TP1 / BE drag | 0.882 | take partial + drag SL to entry (close-based) | 25% |
| TP2 | 0.5 | take partial | 60% |
| TP3 (runner) | 0.0 | flat the runner | 15% |

Direction follows the leg: an **up-leg** (low→high) is a **LONG** setup; a
**down-leg** (high→low) is a **SHORT** setup.

### 4.5 Trigger and abort

- A new setup is **armed** the bar after the leg terminal is finalized.
- If price breaks the terminal extreme before reaching 0.941, the setup is
  **aborted** (canceled, never opened).
- Entry order is a **limit at the 0.941 price**, post-only (maker), GTC until
  aborted or filled.

### 4.6 Intrabar semantics (match the backtest)

- The **entry bar is skipped** for stop/TP evaluation (no entry-bar liquidation,
  no entry-bar TP1).
- Subsequent bars are evaluated **nearest-first** for intrabar wick races (matches
  `track_fib_reaches.py` and the executor's post-fix behavior).
- The **BE-drag stop is close-based** (a wick through entry does not stop you;
  only a bar closing past entry does).

### 4.7 Risk sizing

`1R = |entry − stop| × position notional`. Position notional sized so that
`1R = account_risk_pct × equity`. Default `account_risk_pct = 1.0%` of trading
equity per trade, configurable. Leverage is whatever HL requires to express the
target notional (isolated margin per position).

---

## 5. Architecture

```
                   ┌───────────────────────────────────────────────┐
                   │  Hyperliquid (perps)                          │
                   │   ws: prices, fills, order updates            │
                   │   rest: place/cancel/modify orders, balances  │
                   └────────────┬──────────────────────┬───────────┘
                                │ ws                   │ rest
                                ▼                      ▼
   ┌──────────────────┐   ┌──────────────┐    ┌──────────────────┐
   │ Market Data Feed │──▶│ Detector Loop│    │ Order Executor   │
   │ (1H candles +    │   │ (per asset,  │    │ (idempotent      │
   │  tick / fill ws) │   │  on bar close)│   │  REST client)    │
   └──────────────────┘   └──────┬───────┘    └─────────▲────────┘
                                  │                      │
                                  ▼                      │
                          ┌──────────────────┐           │
                          │ Strategy Engine  │───────────┘
                          │ (per-symbol FSM, │
                          │  matches executor)│
                          └──────┬───────────┘
                                 │
                  ┌──────────────┼──────────────┐
                  ▼              ▼              ▼
            ┌──────────┐   ┌──────────┐   ┌────────────┐
            │ Risk     │   │ State    │   │ Observability│
            │ Engine   │   │ Store    │   │ (logs/metrics│
            │          │   │ (sqlite/ │   │  alerts/UI)  │
            │          │   │  postgres)│   │              │
            └──────────┘   └──────────┘   └────────────┘
```

Strategy Engine is the heart: one finite-state machine per (asset, active setup),
states = `armed → entered → tp1_hit → tp2_hit → tp3_or_stopped`. Each state
transition is a single transactional update to the State Store; all order
placements through the Risk Engine and the Order Executor are idempotent.

---

## 6. Functional requirements

| # | Requirement |
|---|---|
| F-01 | Subscribe to HL 1H candles and order/fill WS streams for the universe. |
| F-02 | On each 1H bar close: run detector per asset; emit "new finalized leg" events. |
| F-03 | When a new leg is emitted and price is between terminal and 0.941, place a **post-only limit** at the 0.941 price (maker). Record `client_order_id` linked to the setup. |
| F-04 | If price breaks the terminal extreme before fill, **cancel the entry order** (abort). |
| F-05 | On entry fill: place a **stop-market at 1.05** (initial SL). Place a **limit at 0.882** sized to 25% (TP1). |
| F-06 | When TP1 limit fills: place a remainder-sized limit at 0.5 (TP2) for 60% of the original position. **Replace the SL** with a close-based BE stop at the entry price (see §6.1). |
| F-07 | When TP2 limit fills: place a final limit at 0.0 (TP3) for the remaining 15%. |
| F-08 | When TP3 fills or SL fires: flatten any residual, close the FSM. |
| F-09 | At startup, **reconcile**: pull open orders & positions from HL, rebuild the FSM state, recover from any mid-trade crash. |
| F-10 | Persist the FSM after every transition (write-ahead, then act). |
| F-11 | Expose a `pause` (stop arming new entries, keep managing open) and `kill` (cancel all orders, flat all positions) control. |
| F-12 | All order placements use **client-supplied IDs** so retries are idempotent. |

### 6.1 BE-drag implementation note

Because HL stops fire on last-traded price (wick-sensitive), and the backtest
uses *close-based* BE stops, the bot must implement the BE stop in software:

- After TP1 fills, the bot watches the live 1H candle close.
- At each 1H close, if `close ≤ entry` (long) / `close ≥ entry` (short), the bot
  fires a **market close** for the remainder.
- The exchange-side initial 1.05 SL is **cancelled** at this point so it can't
  also fire on a wick.

This is the one place the bot must hold protection in software; everything else
lives as resting exchange orders.

---

## 7. Risk management

### 7.1 Per-trade

- **Sizing.** `1R = account_risk_pct × equity`; default 1%.
- **Stop must sit inside liquidation.** Reject any sizing that would place the
  exchange's liquidation price tighter than the strategy's 1.05 stop.
  Use isolated margin per position.

### 7.2 Account-level (configurable, hard stops)

| limit | default | action on breach |
|---|---|---|
| Max concurrent open positions | 4 | refuse to arm new entries |
| Max trades per asset / day | 6 | refuse to arm on that asset |
| Daily realized loss | −3R | pause for the rest of the UTC day |
| Rolling 7-day realized loss | −8R | pause + page operator |
| Consecutive losses (any asset) | 5 | pause + page operator |
| Slippage per fill | > 0.3% | cancel & retry as limit; alert |
| Adverse funding rate (per-asset, annualized) | > 100% | skip new entries on that asset |

### 7.3 Kill switch

- Triggered by: operator command, account-level breach, or repeated WS/REST
  errors (> 10 consecutive in 60s).
- Action: cancel all open orders, market-flat all open positions, halt.
  All future entries blocked until operator explicitly re-arms.

---

## 8. Observability

### 8.1 Logs

JSON-structured, levelled. Every state transition, every order
placement/fill/cancel, every risk decision is logged with the setup key and
client_order_id.

### 8.2 Metrics (Prometheus-style)

- `bot_open_positions{asset}`, `bot_armed_entries{asset}`
- `bot_trades_total{asset,outcome}` (outcome ∈ tp1/tp2/tp3/scratch/wipeout)
- `bot_realized_r{asset}` (counter)
- `bot_ws_latency_ms`, `bot_rest_latency_ms`
- `bot_errors_total{kind}` (rest, ws, parse, risk, …)
- `bot_funding_rate{asset}`

### 8.3 Alerts

- Page (urgent): kill switch fired, account-level limit breach, sustained WS
  outage, position drift detected at reconciliation.
- Notify (Slack/Discord): TP3 hit, big single-trade win/loss, paused/resumed,
  daily summary at UTC close.

### 8.4 Live dashboard (extension to the existing one)

Add a **"Live" tab** to `scripts/dashboard_server.py` showing: current open
positions, day-so-far PnL, last 20 trades, system health (WS up, last bar
ingested per asset), the active armed entries, and a kill-switch button (operator
auth required).

---

## 9. Integrations

- **Hyperliquid:** REST + WebSocket. Read-only metadata + signed trading
  endpoints. API key has **trading permission only — never withdrawal**.
- **State store:** SQLite for v1 (single-node operator), upgradable to
  Postgres for HA.
- **Secrets:** environment variables only; never in repo; rotated quarterly.
- **Alerting:** Slack/Discord webhook + PagerDuty (operator pager).

---

## 10. Testing & rollout

| Phase | What | Exit criteria |
|---|---|---|
| **0. Backtest parity** | Run bot in pure simulation against historical candles; output must reproduce the backtest's per-trade outcome list within rounding. | Trade-by-trade match to `backtest_long_horizon.py` |
| **1. Paper trading** | Live data, simulated fills using HL's actual order book mid + spread modeling; no real orders. Two weeks minimum. | Win-rate, avg-R within ±10% of backtest; zero state-machine bugs |
| **2. Shadow / minimum size** | Real orders at HL minimum notional (~$10); two weeks. | All FSM paths exercised; reconciliation works after at least one forced restart |
| **3. Canary** | 0.1% equity risk per trade; two weeks. | Realized R/month within ±25% of backtest counterfactual (variance budget) |
| **4. Ramp** | 0.5% → 1% over four weeks, weekly check-ins. | Drawdown < 1.5× backtested max-drawdown |
| **Continuous** | Per-trade reconciliation: log live PnL vs the executor's counterfactual on the same setup; drift alert if > 0.2R/trade systematic gap. | — |

### Specific tests required

- Restart mid-fill: kill the process between entry fill and SL placement; verify
  reconciliation places the SL.
- WS disconnect ≥ 5 min: verify orders persist on exchange, bot recovers, no
  duplicate fills.
- Detector idempotency: same candle stream produces same setups across restarts.
- Wick through entry (no close): verify BE stop does NOT fire.
- Close through entry: verify BE stop fires market-close within X seconds.

---

## 11. Deployment & operations

- **Single-node operator deployment** in v1 (a small VPS in low-latency region;
  Tokyo or Singapore for HL).
- **systemd** unit, logs to journald + shipped to remote.
- **Config:** YAML file checked into ops repo (not main repo); secrets via env.
- **Runbook:** pause/resume/kill, key rotation, force-close, recovering from a
  bad fill, draining (close all positions then halt).

---

## 12. Open questions

1. **Funding-rate handling.** Hard skip on > 100% annualized adverse, or
   continuous adjustment (size down)? V1 proposes hard skip; revisit after data.
2. **Per-asset detector params.** Lock all to `6/2.0` or run `sweep_asset_detector.py`
   per asset and lock at each asset's best? V1 proposes uniform 6/2.0 for
   simplicity; revisit if any asset underperforms.
3. **0.882 / 0.786 / Scaled support.** When do we enable these in addition to
   0.941? V1 says never (0.941 only). Likely v2 once 0.941 is proven.
4. **Operator UI.** Pure dashboard view + kill button, or fuller controls
   (per-asset pause, manual close, parameter hot-swap)? V1: view + kill only.
5. **Equity definition.** Trade off Hyperliquid wallet balance, or a fixed
   allocation? V1: a *dedicated subaccount* with fixed allocation, so live PnL
   doesn't move 1R sizing around between trades.

---

## 13. Out of scope (v1)

- Multi-exchange routing.
- Spot or options markets.
- ML-driven parameter adaptation.
- Cross-asset hedging or portfolio-level optimization.
- Automated capital ramp based on rolling PnL.

---

## 14. Milestones

| M | Deliverable | Target |
|---|---|---|
| **M1** | HL client (read + signed write) + market data feed + detector loop emitting setups (no orders) | wk 1–2 |
| **M2** | Strategy Engine FSM + paper-trading executor in full simulation | wk 3–4 |
| **M3** | Live order placement + BE-drag-in-software + reconciliation | wk 5–6 |
| **M4** | Risk engine + kill switch + observability/alerts + Live dashboard tab | wk 7 |
| **M5** | Phase 1–2 (paper + shadow) | wk 8–11 |
| **M6** | Phase 3 canary | wk 12–13 |
| **M7** | Full ramp + ongoing operations | wk 14+ |

---

## 15. Success metrics (90-day window post-canary)

- **Primary:** realized R/month within ±20% of backtest counterfactual at the
  same fee tier.
- **Reliability:** zero double-entries; zero orphaned stops; ≤ 1 unplanned
  pause event/month.
- **Safety:** no daily loss exceeds the configured limit; no liquidation event.
- **Health:** ≥ 99.5% uptime on the strategy loop; ≤ 1s p95 order-placement
  latency.
