# The Learned Rule Set — DB1 Outcome Engine

**This document is the transferable knowledge.** Every rule was learned from
the user's manual chart reviews and then turned into fixed code. It is
written so a TRADER can read it — plain sentence first, technical detail in
*(italics)* after. A fresh agent must be able to understand the engine from
this page and reproduce any recorded run exactly (protocol at the bottom).

No rule may change unless `tests/test_execute_outcome_ground_truth.py` stays
green — that test replays every verdict the user ever gave.

## Small glossary

- **candle / bar** — one time slice of price (a 1-hour candle, a 5-minute candle).
- **touch** — price reached a level at any moment, even briefly (a wick counts).
- **fill** — the moment your entry order executes; **the fill bar** is the
  candle during which that happened.
- **BE (break-even)** — moving your stop to your own entry price, so the rest
  of the trade can no longer lose.
- **R** — profit/loss measured in units of your initial risk. Losing the full
  stop distance = −1R.

---

## A. Which swings count as setups

- **A1.** A swing leg only counts when the market really reversed: price must
  retrace at least *N × the average candle size* (ATR) from the extreme.
  That N (`--mult`) is a MINIMUM — a "2×" run includes every deeper swing too.
  *(swing_detector.py::clean_legs — raising mult changes the whole zigzag
  walk, not just a filter.)*
- **A2.** Swings with fewer than `--min-bars` candles between their high and
  low are ignored (too small/fast).
- **A3.** The anchor points snap to the actual highest/lowest candle of the
  swing — and if several candles share that extreme, the latest one is used.
  *(Added because the drawn anchors sat "a few candles left of the visual
  extreme" — user complaint, May 2026.)*

## B. The trade itself (0.941 entry plan)

- **B1.** All levels are drawn on the swing: enter at the 0.941 retrace,
  stop-loss at 1.05 (**fixed, never widened — user law**), first target 0.882,
  second target 0.5, final target 0.0. Other entries (0.882 / 0.786) shift
  the whole ladder accordingly. *(execute_fib_strategy.py::REGIMES)*
- **B2.** If price makes a new extreme beyond the swing before reaching the
  entry, the setup is dead. If the entry price is simply never reached, the
  setup is a MISS — misses are excluded from all statistics ("only when 941
  hit" — user rule).
- **B3.** Profit-taking plan "runner": 25% off at the first target, 60% at
  the second, 15% rides to the final target. (Alternative "rest50": 25% at
  the first target, then everything out at 0.5.)

## C. How the outcome is decided — the eight human-taught rules

- **C1. Read the fine print of each hour.** Whether the stop or the target was
  hit FIRST inside a candle is decided by looking at the 5-minute candles
  inside it — never guessed when finer data exists. *(Why: on one setup even
  the 15-minute view gave the wrong order; only 5m agreed with the user's
  reading. 5m > 15m > coarser.)*
- **C2. The candle that fills your entry can stop you out.** If the same
  candle that triggers your entry also reaches the stop price, that is a real
  −1R loss. This is certain, not guessed: price beyond your entry can only
  have traded AFTER you were in (before the fill, the market hadn't fallen
  that far yet). *(Why: the old engine skipped the entry candle entirely, so
  same-candle stop-outs were silently counted as surviving trades — the
  single biggest source of fake wins in the May audit.)*
- **C3. But the fill candle can never give you profit.** A touch of the
  target inside the fill candle doesn't count — that touch may have happened
  BEFORE your entry executed, and we can't know. Profit needs a later candle.
  *(Why: the user rejected entry-candle target credits on review.)*
- **C4. One candle poking both entry and first target = nothing happened.**
  When a single 5-minute candle touches the first target AND dips back to the
  entry price, that's noise, not a real move: no profit is taken, the stop
  stays at 1.05, the trade continues as if untouched. *(Why: every such
  "graze" the user graded had behaved as if the target was never really
  reached.)*
- **C5. A clean touch of the first target arms the protection.** When a
  candle reaches the first target WITHOUT dipping back to entry, 25% profit
  is banked and the stop moves up to the entry price.
- **C6. After that, one wick back to your entry ends the trade.** The moved
  stop is touch-based: any brief dip back to the entry price closes the rest
  at break-even — no candle close needed. *(User's explicit choice: "Touch —
  any wick through entry.")*
- **C7. When one candle is ambiguous, assume the worse outcome.** If a candle
  touches both the stop and a target and even the 5-minute data can't order
  them: the stop wins. *(User's explicit choice: "SL wins — conservative.")*
- **C8. Every event is stamped with its exact 5-minute candle**, so chart
  markers sit on the right candle.

Outcome names: **TP1** = banked 25% then break-even (≈ +0.14R) · **TP2** =
also banked the 0.5 target · **TP3** = full winner · **LOSS** = −1R ·
misses excluded. Win rate = (TP1+TP2+TP3) / triggered trades.

## D. Why results are trustworthy and repeatable

- **D1.** Price data comes from Binance's official records, saved as files.
  Old candles never change, so past months give the same result forever.
- **D2.** The engine is a fixed calculation, not an AI. Same data in → same
  result out, on any computer, run by anyone.
- **D3.** It cannot peek at your grades: every line of the scoring code was
  audited (2026-07-03) — it never opens the file your verdicts live in
  (`human_labels.jsonl`). Your feedback improves the RULES (this document);
  it is never available as answers at runtime.
- **D4.** Warning for future developers: `CORRECTED_SWINGS` (in
  place_fibs_tradingview.py) is a leftover list of hand-corrected chart
  anchors. Scoring does not use it today. Never feed it into the scoring
  path — that would be copying human answers and would fake accuracy.

---

## Reproduction protocol (for litmus tests)

A fresh agent proves the engine is context-free like this:

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
recs = runs["2026-05_6c4x_e941_runner"]
ref, new = recs[:11], recs[-11:]
strip = lambda r: {k: v for k, v in r.items() if k != "recorded_at"}
print("REPRODUCTION:", "IDENTICAL" if [strip(a) for a in ref] == [strip(b) for b in new] else "DIVERGED")
PY
```

Expected: 11 predictions, in order **LOSS · TP3 · TP2 · LOSS · TP1 · LOSS ·
TP1 · TP1 · TP3 · TP1 · TP1** (+7.96R total), identical to the frozen
reference apart from the timestamp of the run itself. If it ever says
DIVERGED: either the data files changed (check the CSV's last candle) or the
engine code changed (the ground-truth test will be failing). Both are
findable; neither is mysterious.
