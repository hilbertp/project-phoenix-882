# COOP.md — Claude × Codex × Dev coordination

File-based, async coordination for the **DB1 BTC Fib discovery** work. This file
is both the **responsibilities charter** and the **live coordination log**.

> **How to use this file:** append to the **Log** at the bottom; never edit or
> delete another agent's entry. Keep **Open handoffs** current. Reference exact
> file paths, commands, and expected output. Route work by the responsibilities
> below: pure-Python → Claude; live browser / human judgement → Codex / Dev.

---

## Agents & responsibilities

### Claude — LEAD DEV (implementation, architecture; coordinates Cursor)
- **Owns:** implementation + architecture of the whole pipeline (detector, label
  store, Pine generator, analysis CLIs, review-controller code, demo data),
  pure-Python unit tests, docs, this file, and branch/integration decisions.
  Sets technical direction and breaks work down for Cursor.
- **Does NOT** drive the live Chrome/TradingView or run Selenium/browser tests —
  that's Codex. (Claude driving the live browser once crashed the debug session;
  see Log.) Hands such work to Codex with exact repro steps.

### Codex — TEST (live & integration testing)
- **Owns:** running the tools against real TradingView (Selenium), e2e /
  user-journey tests, browser-session management, integration verification.
- **Reports** RESULT/BLOCKER entries with enough detail for Claude to fix, and
  **commits & pushes** its tests to the canonical branch so they integrate.
- **Does NOT** redesign architecture; routes bugs to Claude.

### Cursor — HELPER to Claude (dev assist, under Claude's direction)
- **Owns:** the dev sub-tasks Claude assigns here — UI wiring, secondary
  implementation, refactors, docs — to Claude's spec / data contracts. Flags
  questions as QUESTION entries.
- **Does NOT** change architecture or core modules without a Claude DECISION
  entry, and does not fork the coordination files (one `AGENTS.md`, one `COOP.md`).

### Dev (Philipp) — product owner & human reviewer
- **Owns:** human-eyes review of fib setups (ground truth), final acceptance,
  product/strategy decisions, credentials, priorities.

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
- [ ] **(→ Cursor/Codex)** Commit & push your e2e Selenium tests
  (`tests/test_db1_user_journey_e2e.py`) and `requirements-dev.txt` ONTO
  `db1-s2-candidate-leg-scoring` (the canonical branch). They are uncommitted in
  the Cursor window, so the merge could not pull them in. When committing your
  `AGENTS.md` run-commands, fold them into the existing `AGENTS.md` — do not
  overwrite the COOP pointer or create a second one.
- [ ] **(→ Dev/Codex)** DEMO = the **TradingView review controller** (PO decided:
  rating must happen on the real chart with the Object Tree, prev/next visible).
  Prereq: debug Chrome logged into TradingView. Flow:
  `python scripts/place_fibs_tradingview.py login` (log in), then
  `python scripts/review_fibs_tradingview.py` — an in-chart panel steps setups,
  placing **prev / current / next** as named Object-Tree objects (current =
  "<< REVIEWING >>"); Accept/Reject/Save-edit feed the label store + recalibrate.
  (The standalone HTML demo `scripts/serve_review_demo.py` works but is NOT the
  rating surface — kept as a no-login fallback.)
- [ ] **(→ Claude)** Harden `_make_driver`: a failed attach must fail loudly, not
  launch a colliding second Chrome on the in-use profile. Lower priority (the demo
  path needs no Selenium). Needs Codex live-validation after.
- [x] **(→ Claude)** Roles updated (Claude=lead dev, Codex=test, Cursor=helper).
- [x] **(→ Claude)** Picked canonical branch (`db1-s2-candidate-leg-scoring`) and
  merged the Codex branch's committed infra (license + contributor workflow).

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

### [2026-05-25] Dev — DECISION
Roles set: Claude = lead dev (+ coordinates Cursor), Codex = test, Cursor =
helper to Claude, Dev = PO. Priority: the fib trade-plan demo, asap. Claude picks
the integration branch and merges.

### [2026-05-25] Claude — DECISION + STATUS
- Canonical branch = `db1-s2-candidate-leg-scoring` (it has the fib demo + COOP).
- Merged `origin/codex/add-apache-license` into it — committed content was infra
  only (LICENSE, CONTRIBUTING.md, `.github/pull_request_template.md`,
  `docs/github_workflow.md`, README +7). Clean merge, 26 DB1 tests still green.
- **Codex's e2e tests + `requirements-dev.txt` were NOT pulled in — they're
  uncommitted in the Cursor window.** Handoff above to commit & push them here.
- Discovered an existing API-backed review UI in `apps/ui` (review-surface,
  chart-truth, db1-s2-candidate-legs) — that is what Codex e2e-tested. It is the
  *leg-scoring* surface, separate from the fib trade-plan demo.
- Demo (fib): `scripts/export_db1_fib_review_pine.py` -> paste the `.pine` into
  TradingView. Also added `scripts/export_demo_data.py` -> `demo_data.json`
  (candles + setups + reach sequence + execution) as the data contract for a
  future self-contained web demo, if we want one instead of the TradingView paste.

### [2026-05-25] Claude — REQUEST (→ Cursor)
You are the dev helper. Next task, on the canonical branch: turn
`artifacts/discovery_bet_1/demo_data.json` (produced by `scripts/export_demo_data.py`)
into a single self-contained `artifacts/discovery_bet_1/demo.html` — a candlestick
chart with **Back/Next** through `setups`, the focused setup's Fib levels + trade
plan drawn, and its `reaches` sequence + `execution` outcome shown. CDN charting
lib is fine; one file, no build step. This gives a browser demo with real Back/Next
that needs no TradingView. Report DONE here with the path.
