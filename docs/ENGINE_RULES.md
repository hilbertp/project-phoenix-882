# The Learned Rule Set — DB1 Outcome Engine

**Purpose: this document IS the transferable knowledge.** Every rule below was
learned from the user's manual chart reviews (May 2026 audits, 15m/5m
re-checks) and then encoded as deterministic Python. A fresh agent must be
able to (a) understand the engine's behavior from this page alone and
(b) reproduce any frozen run bit-for-bit via the protocol at the bottom.
No rule may be changed without `tests/test_execute_outcome_ground_truth.py`
staying green — that fixture replays every human verdict ever given.

Provenance format: each rule cites WHY (the human correction that created it)
and WHERE (code anchor).

---

## A. Setup detection — which legs exist

- **A1. ATR-zigzag walk.** A leg reverses only when price retraces ≥
  ATR(14) × `mult` from the running extreme. `mult` is a MINIMUM depth gate —
  a 2.0× run contains every deeper leg; raising it changes the walk itself,
  not just a filter. *(swing_detector.py::clean_legs)*
- **A2. Min-bars gate.** Legs spanning fewer than `min_bars` candles between
  the two pivots are dropped.
- **A3. Pivot refinement (swing-correction).** After the walk, each pivot
  snaps to the true extreme bar within its neighbor window; among TIED
  extremes the LATEST bar wins. *(Why: the raw walk anchored "a few candles
  left of the visual extreme" — user complaint, May 2026.)*

## B. Trade geometry — the 0.941 regime (REGIMES catalog)

- **B1. Levels.** `level(c) = terminal + (parent − terminal) × c`. Entry
  0.941 · initial SL 1.05 (**FIXED — never widen**, user law) · TP1/BE-trigger
  0.882 · TP2 0.5 · TP3 0.0. Entries 0.882/0.786 shift the ladder per the
  catalog. *(execute_fib_strategy.py::REGIMES)*
- **B2. Trigger validity.** Walking 1H bars after the terminal: a new extreme
  beyond the terminal before the entry touches → `no_trigger`; entry never
  touched → `no_entry`. Both are MISSES — excluded from review and stats
  ("only when 941 hit", user rule).
- **B3. Exit plan `runner`.** TP1 25% · TP2 60% · TP3 15%. (`rest50`: TP1 25%
  then remaining 75% out at 0.5.)

## C. Outcome scoring — the human-validated core

- **C1. Sub-bar resolution is canonical: 5m > 15m > native ties.** Intra-candle
  event ORDER is read from the finest data available, never guessed when data
  exists. *(Why: setup 13 — the 15m tape mis-ordered SL-before-TP1; 5m showed
  TP1 first; the user's eyeball beat both coarser views.)*
- **C2. The stop is LIVE from the fill: the fill bar can KILL.** An SL touch
  on the bar that fills the entry is a real stop-out (for a long, price below
  entry exists only post-fill — geometrically provable). *(Why: 8 of the 10
  false wins in the first May audit were entry-bar stop-outs the old engine
  exempted.)*
- **C3. The fill bar can never CREDIT.** TP touches on the fill bar don't
  count — the bar's high/low may predate the fill within the bar. *(Why: the
  user explicitly refused entry-bar TP1 credit on setups 05-12/05-20.)*
- **C4. Micro-graze rule.** A single bar spanning the WHOLE entry↔TP1 band
  (touches both) is noise: no partial, break-even NOT armed, position stays
  in phase 1 under the 1.05 hard stop. *(Why: every same-bar graze the user
  graded was LOSS/TP2 — unmanaged; every separate-bar tag-then-return was
  TP1.)*
- **C5. Separate-bar TP1 touch arms management.** 25% banked at 0.882, stop
  dragged to entry.
- **C6. Break-even stop is TOUCH-based.** ANY wick back to entry scratches the
  remainder — no close required. *(Why: user's answer "Touch — any wick
  through entry"; their TP2→TP1 corrections demanded it.)*
- **C7. Same-bar ambiguity resolves UNFAVORABLY** at whatever granularity is
  still ambiguous: SL beats TP1; BE-touch beats TP2/TP3. *(Why: user chose
  "SL wins — conservative" for spanning bars.)*
- **C8. Event timestamps are fill-bar precise** (5m when sub-bars exist) so
  renderers place markers on the correct candle.

Outcome classes: `tp1_then_scratch`→TP1 (≈+0.14R) · `tp2_then_scratch`→TP2 ·
`tp3_full`→TP3 · `wipeout`→LOSS (−1R) · misses excluded. Win rate =
(TP1+TP2+TP3)/triggered.

## D. Determinism & data

- **D1.** Binance SPOT BTCUSDT CSVs (1H + 5m); past windows immutable; the
  acquirer retries and refuses to truncate.
- **D2.** No randomness, no model, no label access at runtime (audited
  2026-07-03: the scoring path never reads `human_labels.jsonl`). Same inputs
  → identical outputs, any machine, any agent.

---

## Reproduction protocol (for litmus tests)

A fresh agent reproduces the May-2026 reference run like this:

```bash
cd ~/project-phoenix-882
PYTHONPATH=. .venv/bin/python scripts/record_predictions.py --month 2026-05 --min-bars 6 --mult 4.0
PYTHONPATH=. .venv/bin/python - <<'PY'
import json
from pathlib import Path
runs = {}
for line in Path("data/discovery_bet_1/engine_predictions.jsonl").read_text().splitlines():
    r = json.loads(line)
    runs.setdefault(r["run_id"], []).append(r)
ref, new = runs["2026-05_6c4x_e941_runner"][:11], runs["2026-05_6c4x_e941_runner"][-11:]
strip = lambda r: {k: v for k, v in r.items() if k != "recorded_at"}
same = [strip(a) for a in ref] == [strip(b) for b in new]
print("REPRODUCTION:", "IDENTICAL" if same else "DIVERGED")
PY
```

Expected: 11 predictions, classes in chronological order
**LOSS · TP3 · TP2 · LOSS · TP1 · LOSS · TP1 · TP1 · TP3 · TP1 · TP1**
(+7.96R total), byte-identical to the frozen run apart from `recorded_at`.
The engine has no memory — identity is guaranteed by determinism (D2), not by
context. If a reproduction DIVERGES, either the data files changed (check the
CSV last bar) or someone edited the engine (the ground-truth test will be
red); both are diagnosable, neither is mysterious.
