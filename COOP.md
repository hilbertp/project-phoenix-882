# COOP.md — Claude × Codex × Dev coordination

File-based, async coordination for the **DB1 BTC Fib discovery** work. This file
is both the **responsibilities charter** and the **live coordination log**.

> **How to use this file:** append to the **Log** at the bottom; never edit or
> delete another agent's entry. Keep **Open handoffs** current. Reference exact
> file paths, commands, and expected output. Route work by the responsibilities
> below: pure-Python → Claude; live browser / human judgement → Codex / Dev.

---

## Agents & responsibilities

### Claude — implementation & design (NO live browser)
- **Owns:** Python implementation (detector `_clean_legs`, label store, Pine
  generator, analysis CLIs, the review-controller *code*), pure-Python unit
  tests, architecture, docs, and this file.
- **Does NOT:** drive the live Chrome/TradingView, run Selenium/browser
  integration tests, or do human-eyes setup review. (Learned the hard way —
  Claude driving the live browser crashed the debug session; see Log.)
- Hands off anything needing the live browser or human judgement to Codex/Dev
  here, with exact repro steps and what to report back.

### Codex — live & integration testing, browser automation
- **Owns:** running the Selenium tools against the real logged-in TradingView;
  verifying panel injection, anchor read-back, Next/Back/Accept/Reject/Save;
  managing/recovering the Chrome debug session; integration testing.
- **Reports** results here as RESULT/BLOCKER entries with enough detail for
  Claude to fix the code (raw JS output, stack traces, the resulting
  `human_labels.jsonl`).
- **Does NOT** redesign architecture or rewrite Claude's modules without a
  DECISION entry agreed here.

### Dev (Philipp) — product owner & human reviewer
- **Owns:** human-eyes review of fib setups (the ground truth), final
  acceptance, product/strategy decisions, anything needing TradingView
  login/credentials, and pushes to shared branches.
- Decides priorities and resolves disagreements.

---

## Coordination protocol
- Append entries to **Log**. Header: `### [YYYY-MM-DD] <author> — <TYPE>` with
  TYPE ∈ {REQUEST, STATUS, RESULT, BLOCKER, DECISION, QUESTION}.
- A REQUEST should name the owner (`→ Codex` / `→ Dev` / `→ Claude`), give exact
  commands, and state what to report back.
- Live-test prerequisites: logged-in Chrome on **debug port 9222**
  (`--remote-debugging-port=9222 --user-data-dir=.chrome-tv-manual`), chart on
  **BITGET:BTCUSDT.P, 1H, timezone UTC**.

---

## Open handoffs
- [ ] **(→ Dev)** Recover the debug session: reopen the TradingView chart tab —
  Claude's smoke test left port 9222 with no page targets.
- [ ] **(→ Codex)** Live-test `scripts/review_fibs_tradingview.py` — see
  REQUEST 2026-05-25 below. Riskiest unknown: does `READBACK_FIB_JS` return the
  Fib anchor points in this TradingView build?
- [ ] **(→ Claude)** Harden `_make_driver` so a failed attach does **not** fall
  back to launching a second Chrome on the in-use profile (it collides and
  crashes). Make it fail loudly instead. Needs Codex live-validation after.

---

## Component status
| Component | File | Built | Unit-tested | Live-verified |
|---|---|---|---|---|
| Detector (ATR zigzag) | `scripts/place_fibs_tradingview.py` `_clean_legs` | yes | via sim | n/a |
| Label store + overrides | `apps/worker/discovery_bet_1/human_labels.py` | yes | yes (6) | n/a |
| Review controller | `scripts/review_fibs_tradingview.py` | yes | imports only | **NO — Codex/Dev** |
| Native placer | `scripts/place_fibs_tradingview.py` | yes | n/a | partial (dev) |
| Calibrate / retune | `scripts/calibrate_detector.py` | yes | yes (4) | needs labels first |
| Pine generator + reach tracker | `apps/api/db1_fib_review_pine_read/service.py` | yes | yes (16) | needs TV paste |
| Trade sim / track / execute | `scripts/simulate_trade_plan.py`, `track_fib_reaches.py`, `execute_fib_strategy.py` | yes | partial | n/a |

---

## Log

### [2026-05-25] Claude — STATUS
Built the human-in-the-loop review system:
- `apps/worker/discovery_bet_1/human_labels.py` — append-only JSONL label store
  (`accept`/`reject`/`adjust`), `apply_overrides(legs)` (the "remember" half),
  `truth_setups()` (the calibration target). Tracked at
  `data/discovery_bet_1/human_labels.jsonl` (gitignore exception added).
- `scripts/review_fibs_tradingview.py` — injects a control panel
  (Back/Next/Accept/Reject/Save edit/Done) into TradingView, steps setups one at
  a time, and on Save reads back the dragged anchors → corrected label (snapped
  to candle extremes).
- `scripts/calibrate_detector.py` — sweeps (min_bars × ATR-mult) to maximise
  reproduction of approved setups minus rejected ones (the "retune" half).
- Tests: `tests/test_db1_human_labels.py` (6), `tests/test_db1_calibrate_detector.py` (4).
  Full new+related suite green (26). `human_labels.py` passes ruff.

### [2026-05-25] Claude — REQUEST (→ Codex)
Live-test `scripts/review_fibs_tradingview.py`. Prereq: logged-in Chrome on 9222,
chart on BITGET:BTCUSDT.P 1H UTC.
1. Run `.venv/bin/python scripts/review_fibs_tradingview.py`.
2. Verify: (a) panel appears top-right; (b) setup 1 places as a Fib object;
   (c) Next/Back cycle through setups; (d) Accept/Reject append lines to
   `data/discovery_bet_1/human_labels.jsonl`; (e) drag the Fib's two anchors to
   the correct pivots, click **Save edit** → an `adjust` line is written with the
   corrected anchors.
**Report back here:** the raw return of `READBACK_FIB_JS` (does `fib.points()` or
`fib.state().points` yield the anchors?), any chromedriver errors, and the
`human_labels.jsonl` contents after a few actions. That read-back is the one part
Claude could not verify without the live chart.

### [2026-05-25] Claude — BLOCKER (self-inflicted)
A smoke test I ran attached-failed and fell back to launching a second Chrome on
the in-use `--user-data-dir=.chrome-tv-manual` profile; it crashed and left debug
port 9222 with **no page targets**. Dev: reopen the TradingView chart tab to
restore the session. Claude will not drive the live browser again — see the
`_make_driver` hardening handoff above.
