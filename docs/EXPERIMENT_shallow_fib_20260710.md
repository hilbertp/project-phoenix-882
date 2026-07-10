# Pre-registered experiment: shallow-zone fib continuation (2026-07-10)

Sources: community fib playbook (golden-zone entries, confirmation, level-based
stops, measured-move targets) vs. our falsified deep-entry family (0.786-0.941
passive limits, 1.05 stop). Registered BEFORE any cell is computed; anything
outside this grid is exploratory, not confirmatory.

## Hypotheses under test
H1 (zone): entries in the 0.382-0.618 retracement band with level-based stops
    and old-extreme / extension targets have positive expectancy, unlike the
    deep 0.786-0.941 family.
H2 (staleness, prior evidence): the validated fill-lag gate (<=12 bars from
    terminal anchor to fill) improves any surviving config.
H3 (video-2 claim): "every new rally travels >= 0.618 of the previous rally"
    — to be falsified with exact frequencies.
H4 (spectrum): shallow pullbacks (holding above 0.5) precede continuation
    beyond the old extreme more often than deep pullbacks (Lance's framing).

## Discovery / validation split
Discovery: BTCUSDT 1H, 2021-01-01..2026-07-01 (11 half-years, 5m sub-bars).
Validation (untouched until a config survives discovery hurdles):
ETHUSDT, BNBUSDT, XRPUSDT, SOLUSDT, same window, same rules.

## Fixed machinery (human-validated engine, no changes)
Universe: candidates_from_pivots, min_bars=6, mult=4.0 (unchanged).
execute() with parameterized coefficients; extensions = negative coefficients.
Strict causality: all filters computed from completed bars at or before fill.

## The grid (36 cells, all pre-registered)
entry_c    in {0.382, 0.5, 0.618}
init_sl_c  in {entry+0.15 (below-the-level stop), entry+0.30 (wide), 1.05 (legacy)}
ladders:
  L1 "runner":   tp1 = entry-0.15 (25%, BE-drag), tp2 = 0.0 (60%), tp3 = -0.618 (15%)
  L2 "measured": tp1 = 0.0 (50%, BE-drag),        tp2 = -0.618 (50%), no tp3
lag gate   in {off, <=12}  (post-filter, no extra passes)

## Hurdles (identical to the stacked-levers adjudication)
(i) >= 100 fills; (ii) R/trade >= +0.05 after fee floor considerations
(iii) positive in >= 6/11 half-years; (iv) survives dropping its best
half-year; (v) effective-trials argument: 36 correlated cells ~ a handful of
independent claims — a lone marginal passer is noise; (vi) any survivor must
then pass on >= 3 of 4 validation assets without re-tuning.

## Outcome commitments
If no cell survives: the zone hypothesis joins the deep-entry family as
falsified, and the residual explanation for discretionary fib profitability
shifts fully to selection/management/survivorship.
If cells survive discovery but die on alts: overfitting, treat as falsified.
If cells survive both: proceed to confirmation-triggered entries (v2) and
paper-freeze forward test before any capital.
