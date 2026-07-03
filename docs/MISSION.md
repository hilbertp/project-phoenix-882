# Project Main Goal

**Develop a reliable fib-level entry detector whose variables can be changed
quickly, to find the most lucrative setup for trading.** Everything in this
repo serves that search. The four variable axes:

| Axis | Values to explore | Status (2026-07-03) |
|---|---|---|
| **Timeframe** | 15min · hourly · daily | 1H fully operational (BTC). 15m data + partial ADA tooling exists. Daily = data only (resample). **Gap: tooling is 1H-hardcoded** (CSV paths, TV interval, hour-keyed sub-bars). |
| **Min candles between pivots** | any (6, 12, 24, 36, 48 tested) | ✅ `--min-bars` everywhere. ATR-depth minimum (`--mult`) is the sister gate. |
| **Entry level** | 0.786 · 0.882 · 0.941 | ✅ `--entry` in the grid backtest (regime catalog: entry→BE-trigger→TPs). Review/cards still default 0.941 — thread next. |
| **SL/TP strategy** | fixed SL 1.05 + exit plans; **trailing SL** | `runner` (25/60/15 to 0.0) and `rest50` (25% then all out at 0.5) ✅. **Trailing SL: not built** — design: after TP1, trail the stop level-by-level as price tags successive fib levels. |
| **Max candles term→entry** (added 2026-07-03) | e.g. ≤24, ≤48, ≤96 bars | **Not built.** Thesis: the more candles between the second anchor (terminal extreme) and the 0.941 fill, the weaker the signal. Cheap to implement: fill_ts − term_ts is already in the executor's event tape; becomes a `--max-entry-delay` filter. |
| **Prior fib-level bounces** (added 2026-07-03) | count of 0.618 / 0.786 / 0.882 already played out with wins before the entry fills | **Not built.** Thesis: the more levels already bounced, the LESS likely the 0.941 plays out too (the retrace has spent its buyers/sellers). Needs path tracking between terminal and fill: which levels were tagged and rejected before the entry level traded. |

## The method (non-negotiable, learned the hard way)

1. **Outcomes must be human-validated before parameter sweeps mean anything.**
   The executor's rules were wrong for months and made every backtest lie
   (12/27 vs the user's eyes). Now: `tests/test_execute_outcome_ground_truth.py`
   replays every hand-graded verdict; it must stay green after ANY engine
   change. New axis values (a new timeframe, a new entry level, trailing SL)
   need their own manual-review pass on TradingView before their numbers are
   trusted.
2. **Regime beats parameters — and regimes are an OPEN research question.**
   We do not yet know which market regimes exist or how many there are. What
   we have is a standing thesis: there are conditions under which
   ranging-type trading (fib retracements) works poorly or not at all
   compared to other regimes — and five months of grids support it (no
   bars × ATR × entry combination wins across months). The Ichimoku 26-bar
   two-sides veto (`scripts/ichimoku_regime.py`) is our v1 regime hypothesis,
   not the answer: it improved every month tested (12-month 6c/4x: −35.8R →
   +3.2R), but discovering the true regime taxonomy — what to measure, how
   many states, where fibs earn and where they die — is itself a core
   backtesting mission. Any "most lucrative setup" claim must be reported
   with and without the current veto.
3. **Sub-bar resolution is required.** Intra-candle event order (SL vs TP
   first) decides half the outcomes; the finest available data wins
   (5m > 15m > native ties). A new timeframe needs its sub-bar feed.

## Roadmap to full axis coverage

1. **Entry level through the review + cards** (small): thread `--entry` from
   `tv_review_btc_month.py` / `render_btc_month_review.py` into the executor
   the way the grid already does; labels must carry the entry level.
2. **Trailing SL as exit plan `trail`** (medium): generalize `execute()`'s
   phase ladder to a level-to-level trail (long from 0.941: tag 0.786 → SL
   0.882; tag 0.618 → SL 0.786; … tag 0.0 → full win). Must not disturb the
   validated `runner`/`rest50` paths (fixture green).
3. **Timeframe generalization** (large): parameterize symbol/interval across
   data paths, TV interval, and sub-bar keying (currently hour-keyed
   `ts[:13]`); 15m review needs 1m sub-bars (partially acquired for ADA);
   daily needs 1H sub-bars (already have). Then re-run the whole method
   (manual validation → grids → regime) per timeframe.

Operating manual: [TV_REVIEW_RUNBOOK.md](TV_REVIEW_RUNBOOK.md).
