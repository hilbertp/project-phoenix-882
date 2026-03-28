# Capability A3 Schema Translation Plan

## Planning Summary

The accepted A3 state model should move into schema work in a small number of reviewable steps.
The implementation sequence should establish stable reference entities first, then the run record that depends on them, then trade-level memory, and finally the minimal annotation model.

This keeps the first schema pass focused on the core operational backbone of A3 while deferring the higher-variance parts of the model into later, easier-to-review steps.

---

## Recommended Implementation Order

1. Market
2. Strategy Definition
3. Swing Model
4. Backtest Run
5. Trade Record
6. Review Annotation

This order should be followed because:

1. Market, Strategy Definition, and Swing Model are foundational reference entities
2. Backtest Run depends directly on those reference entities
3. Trade Record depends on Backtest Run and carries more nullability and state detail
4. Review Annotation should come last because it introduces target indirection and should stay minimal

---

## Proposed Grouping For Marek

### First Schema Pass

Implement together in the first schema pass:

1. Market
2. Strategy Definition
3. Swing Model
4. Backtest Run

This first pass should create the minimum relational backbone for A3 and establish the core run-level persistence boundary.

### Second Reviewable Step

Implement next, after the first pass is reviewed:

1. Trade Record

This should be isolated because it introduces trade-state handling, nullable lifecycle timestamps, and trade-level price fields.

### Third Reviewable Step

Implement last:

1. Review Annotation

This should remain separate because it adds polymorphic targeting behavior through `target_type` and `target_id`, even though the model itself stays minimal.

---

## What Marek Must Implement Next

The next implementation step should translate the first schema pass into actual schema and migration work for:

1. Market
2. Strategy Definition
3. Swing Model
4. Backtest Run

That next step should include only:

1. tables or equivalent schema structures for those entities
2. minimum approved fields from the A3 state model
3. primary keys and foreign keys required by the accepted relationships
4. nullability and status handling only where already implied by the approved model

---

## Explicit Out Of Scope For The Next Implementation Step

The following must stay out of the next implementation step:

1. Trade Record schema work
2. Review Annotation schema work
3. any schema expansion beyond approved minimum fields
4. migrations for deferred entities
5. ingestion logic
6. strategy logic
7. reporting or derived summary design
8. API behavior
9. worker behavior
10. analytical storage design
11. detailed parameter payload models
12. review-system expansion beyond the accepted minimal annotation model

---

## Readiness Statement For A3.W3

A3.W2 is sufficient to start A3.W3.
The next work item should implement the first schema pass only: Market, Strategy Definition, Swing Model, and Backtest Run.

Trade Record and Review Annotation should remain deferred until that first pass is complete and reviewed.