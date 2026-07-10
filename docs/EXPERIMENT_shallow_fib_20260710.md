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

---

## OUTCOME (recorded 2026-07-10, same day, after computation)

H1 FALSIFIED. 0 of 36 cells survive hurdles (i)-(v) on BTC discovery data.
33/36 negative before fees. The lone hurdle-(i)-(iv) passer
(e0.618 / sl0.768 / L2 / lag<=12: +0.052 R/trade, t=0.65, 842 fills)
reproduced exactly under independent re-run but is disqualified by (v):
weaker than the expected family-max under pure noise, lottery-shaped
(94 extension winners vs 679 wipeouts), uncorroborated by neighbors,
and ~+0.002 R/trade net of fees. No alt validation owed.

H3 FALSIFIED: new rallies reach >=0.618 of the prior one 73.8% of the
time (920/1247), not 100% — the guru line sits at the ~25th percentile
of the ratio distribution.

H2 directionally supported (lag gate improves 13/18 pairs) but never
flips a cell positive.

H4 CONFIRMED: continuation beyond the old extreme after pullbacks of
depth <=0.382 / 0.382-0.5 / 0.5-0.618 / 0.618-0.786 / >0.786 =
83.2% / 72.5% / 71.8% / 57.7% / 36.2% (z=9.7 shallow-vs-deep,
direction-symmetric). KEY RECONCILIATION: depth is future information
at fill time — a resting limit at a fib level systematically fills on
pullbacks still deepening (median terminal depth 0.925; only 13.9%
hold above 0.5), so the 78%-continuation cohort is unreachable by
passive level entries. The statistic is real; the entry mechanic
cannot monetize it. This is why the fib-level myth persists.

Sanctioned next step per commitments: v2 confirmation-triggered entry
inside shallow pullbacks (new pre-registration), and prospective freeze
of the mentor's live setups. Both fib-level families (deep 0.786-0.941
and shallow 0.382-0.618) are now falsified on 5.5y BTC 1H.
