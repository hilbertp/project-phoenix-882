# Pre-registered experiment v3: LSOB-primary sweep entries (2026-07-10)

PO hypothesis (Philipp, 2026-07-10): "liquidation clusters get swept at or
around deep entries (0.786-0.941). Invert the confluence: one side's
liquidity swept while the other side is still intact = entry signal; being
inside 0.786-0.941 = confluence." The claim under test, verbatim: THE SWEEP
SELECTS THE BOUNCERS. Registered before computation; the commit is the seal.

## Data
Liquidity pools proxied from price (fractal extremes) — liquidations and
stops co-locate at structural extremes. Paid heatmap data (CoinGlass, 2019+)
only if the proxy version survives. Discovery: BTCUSDT 1H 2021-01..2026-07.
Validation (untouched): ETH/BNB/XRP/SOL, same window.

## Mechanical definitions (all causal; completed 1H bars only)
- Active legs: scan-universe candidates (candidates_from_pivots, 6c/4x),
  parent_ts in window. Direction below described for up-legs (long); shorts
  mirror on down-legs.
- Pool (sell-side, longs): a 2/2 fractal low formed in [bar-150, bar-3].
  Pool level L qualifies for a leg if L lies inside the leg's sweep zone.
- Sweep zones (2 declared variants):
    Z1 strict:   [level(0.941), level(0.786)]
    Z2 extended: [level(1.05),  level(0.786)]  (allows overshoot to invalidation)
- SWEEP EVENT (bar B): low(B) < L, close(B) > L, and low(B) inside the zone;
  terminal T not exceeded since the terminal bar (execute-inherent).
- ASYMMETRY (intact other side): at bar B there exists a fractal high in
  [B-150, B-3] above close(B) (an untouched buy-side magnet), and T itself
  is untouched.
- ENTRY: next bar open after B. One signal per (direction, entry bar); among
  overlapping legs choose the LATEST terminal (freshest anchor, per the
  anchor-correction ruling). Portfolio accounting: sequential (skip signals
  while a same-direction position is open); raw also reported.
- STOPS (2 variants): S1 = sweep low - 0.25*ATR(fill bar);
  S2 = leg level(1.05) (house rule).
- LADDERS (2 variants), coefficients on the leg:
  L1 runner:   TP1 0.618 (25%, stop->entry after touch), TP2 0.0 (60%), TP3 -0.618 (15%)
  L2 measured: TP1 0.0 (50%, stop->entry), TP2 -0.618 (50%)
- Executor: new (entry at open, not at a fib limit). 1H bars, conservative
  same-bar tie (stop before target), touch-based fills, BE stop after TP1
  touch. MUST be hand-validated on >=3 printed event tapes before the grid.

## Grid (8 cells) + controls (pre-declared, canonical config Z1/S1/L1)
- 2 zones x 2 stops x 2 ladders = 8 cells, each with sequential + raw accounting.
- CONTROL A (zone-only): same zone entry, same asymmetry, NO sweep required
  (enter on first bar CLOSING inside the zone). Isolates the sweep's value.
- CONTROL B (sweep-only): sweep event anywhere outside the zone requirement.
  Isolates the zone's value.
- MECHANISM METRIC: bounce rate = share of signals reaching TP1 level and
  terminal level before stop, for signal cells vs Control A. The PO claim is
  TRUE iff sweep-selected bounce rate materially exceeds zone-only bounce
  rate (pre-set: >= +10 percentage points at TP1).

## Hurdles (unchanged from v2)
(i) n>=100 (discovery); (ii) R/trade >= +0.05 with fee floor in mind;
(iii) >=6/11 half-years positive; (iv) drop-best-half-year still positive;
(v) effective-trials honesty across the 8 correlated cells;
(vi) survivors must pass >=3 of 4 validation alts without re-tuning.

## Outcome commitments
- No cell survives AND bounce-rate delta < +10pp: hypothesis falsified; the
  sweep does not select bouncers; fib-zone trading closes entirely.
- Bounce-rate delta confirmed but P&L fails: mechanism real, monetization
  wrong -- iterate exits ONLY via new pre-registration.
- Cells survive + controls beaten + alts pass: first live candidate;
  proceed to CoinGlass real-liquidation validation and forward freeze.

---

## OUTCOME (recorded 2026-07-11, after computation)

FALSIFIED per the first outcome commitment. Three independent
implementations agree to the unit.

- P&L: 0 of 8 cells survive hurdles, under BOTH signal readings
  (first-sweep-per-leg and doc-literal all-sweeps). Best cell
  Z2/S2/L2 sequential: +0.015..+0.027 R/trade, t~0.2, drop-best
  negative. No alt validation owed.
- Mechanism (">= +10pp TP1 bounce vs zone-only"): FAILS on the
  governing per-signal basis: -5.6pp (NEGATIVE, z=-5.1). Sequential
  basis +9.93pp -- under the bar.
- Honest post-hoc observation (exploratory, NOT sealed): the FIRST
  sweep of a leg does select bouncers (+18.3pp TP1, z=+9.0; terminal
  reach 12.1% vs 6.8%) -- but re-sweeps dominate the signal count and
  bounce far less (grinding trends re-sweep and serially stop out).
  Even on the first-sweep basis all 8 P&L cells fail: the selected
  bounces (to 0.618) cannot pay for the -1R stops. Mechanism partially
  real at best; monetization fails everywhere.
- Control B: removing the zone is catastrophic (-0.46 R/trade,
  t=-11.5). The deep zone has selection value; nothing built on it
  has positive expectancy.

Per the commitments: fib-zone trading CLOSES entirely. Remaining
sanctioned work: Phoenix-Trend v1 (portfolio trend-following) and the
prospective freeze of the mentor's live setups.
