# Capability A3 State Model

## A3 State Model Summary

Capability A3 defines the first minimum internal memory of Project Phoenix.

The purpose of this state model is to make later schema and migration work unambiguous by deciding what Phoenix must remember at the system level before implementation begins.

This document stays intentionally narrow.
It defines the first approved core entities, their meaning, their minimum fields, and their immediate relationships.
It does not define database schema, migrations, ingestion behavior, strategy behavior, API behavior, or analytical storage design.

---

## Approved Core Entities

### 1. Market

**Meaning**  
A tradable market Phoenix can run research against.

**Why it exists**  
Phoenix must know what instrument a run refers to and must not hardcode BTCUSD as a one-off case.

**Minimum fields**
- market_id
- symbol
- base_asset
- quote_asset
- asset_class
- is_active

---

### 2. Strategy Definition

**Meaning**  
A named research strategy Phoenix can evaluate.

**Why it exists**  
Runs must be tied to an explicit strategy identity rather than vague logic in code.

**Minimum fields**
- strategy_definition_id
- strategy_key
- strategy_name
- strategy_version
- is_active

---

### 3. Swing Model

**Meaning**  
A named method for selecting swing highs and swing lows.

**Why it exists**  
Swing selection is a first-class variable in Phoenix and must be recorded separately from the strategy itself.

**Minimum fields**
- swing_model_id
- swing_model_key
- swing_model_name
- swing_model_version
- is_active

---

### 4. Backtest Run

**Meaning**  
One complete historical research execution using a defined market, strategy, swing model, and configuration.

**Why it exists**  
The run is the main audit and reproducibility unit in Phoenix.

**Minimum fields**
- backtest_run_id
- market_id
- strategy_definition_id
- swing_model_id
- timeframe
- date_from
- date_to
- run_status
- config_snapshot
- created_at

---

### 5. Trade Record

**Meaning**  
One recorded qualified setup or trade outcome produced inside a backtest run.

**Why it exists**  
Phoenix must preserve trade-level evidence, not just run summaries.

**Minimum fields**
- trade_record_id
- backtest_run_id
- market_id
- trade_state
- direction
- setup_timestamp
- entry_timestamp
- exit_timestamp
- entry_price
- stop_price
- partial_price
- final_exit_price

**Notes**
- `trade_state` should support the approved minimum state model for Phoenix.
- Some fields may be null depending on state.

---

### 6. Review Annotation

**Meaning**  
A minimal human note attached to a run or trade record.

**Why it exists**  
Phoenix must leave room for human review without introducing a larger review system at this stage.

**Minimum fields**
- review_annotation_id
- target_type
- target_id
- note_text
- created_at

**Notes**
- `target_type` must support at least:
  - backtest_run
  - trade_record
- This entity is intentionally minimal in A3.W1.

---

## Important Relationships

The following relationships matter now:

1. A **Backtest Run** belongs to one **Market**
2. A **Backtest Run** belongs to one **Strategy Definition**
3. A **Backtest Run** belongs to one **Swing Model**
4. A **Backtest Run** has many **Trade Records**
5. A **Trade Record** belongs to one **Backtest Run**
6. A **Trade Record** refers to one **Market**
7. A **Review Annotation** belongs to either one **Backtest Run** or one **Trade Record**

---

## What Belongs in A3

A3 includes:

1. the first approved core entities Phoenix must remember
2. the minimum fields required to make those entities meaningful
3. the minimum relationships required for later schema work
4. the state boundary between run-level memory and trade-level memory
5. enough clarity to implement schema and migrations next

---

## Explicit Exclusions for Later Capabilities

The following do **not** belong in A3.W1:

1. database schema files
2. migrations
3. ingestion pipeline behavior
4. analytical storage structure
5. source-registry expansion
6. API contracts
7. worker execution behavior
8. detailed strategy parameter models
9. detailed swing-anchor payload structure
10. regime and market seasonality models
11. reporting summaries or derived reporting tables
12. DTO or UI-facing view models
13. anything beyond a minimal review-note model

These belong to later work once the state model baseline is approved.

---

## Reporting Boundary

A3 should define **canonical operational memory**, not reporting memory.

That means:

1. A3 defines source-of-truth entities such as market, run, trade record, and annotation
2. A3 does not define derived summary tables, dashboard views, or reporting aggregates
3. later reporting work must consume A3 entities, not reshape A3 around reporting convenience

This boundary should stay clean from the start.

---

## Readiness Statement for Schema Implementation

This state model is ready to be used as the baseline for:

1. schema design
2. migration planning
3. persistence boundary definition

It is intentionally minimal, but sufficient for A3 to move into implementation without introducing architecture drift.