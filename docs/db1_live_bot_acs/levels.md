# ACs — `apps/bot/strategy/levels.py`

Pure functions mapping a swing leg + StrategyConfig → entry/SL/TP prices
and R-ratios. The same math the FSM uses to plan an entry and to compute
realized R.

## AC-LVL-01: Up-leg level math

Given an up leg with `parent_price=100`, `term_price=110`, default strategy
coefficients (`entry=0.941, init_sl=1.05, tp1=0.882, tp2=0.5, tp3=0.0`)
When `compute_levels(...)` is called
Then:
- `entry ≈ 100.59`  (110 + (100-110) * 0.941)
- `init_sl == 99.5` (110 + (100-110) * 1.05)
- `tp1 == 101.18`   (110 + (100-110) * 0.882)
- `tp2 == 105.0`
- `tp3 == 110.0`
- `risk_per_unit == 1.09` (|entry - init_sl|)
- `degenerate == False`

## AC-LVL-02: Down-leg level math

Given a down leg with `parent_price=110`, `term_price=100`, same defaults
Then:
- `entry ≈ 109.41`  (mirror image of the up case)
- `init_sl == 110.5`
- `tp1 == 108.82`
- `tp2 == 105.0`
- `tp3 == 100.0`
- `risk_per_unit == 1.09`

## AC-LVL-03: Up-leg degeneracy (terminal not above parent)

Given an up leg with `parent_price=110, term_price=100` (inverted)
Then `degenerate == True` and the FSM must refuse to arm. Strict inequality:
`term == parent` is degenerate too.

## AC-LVL-04: Down-leg degeneracy (terminal not below parent)

Given a down leg with `parent_price=100, term_price=110` (inverted)
Then `degenerate == True`.

## AC-LVL-05: R-ratios are positive, monotone toward terminal

For a valid (non-degenerate) leg:
- `risk_to_tp1`, `risk_to_tp2`, `risk_to_tp3` are all `>= 0`.
- `risk_to_tp3 > risk_to_tp2 > risk_to_tp1` (deeper TP = larger R).

## AC-LVL-06: Zero-width risk handled gracefully

Given a leg where `entry == init_sl` (after rounding)
Then `risk_per_unit == 0`, `degenerate == True`, and all R-ratios are `0.0`
(no division-by-zero).
