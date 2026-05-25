# AGENTS.md

This repo is worked by multiple agents. **Before doing anything, read
[COOP.md](COOP.md)** — it defines who owns what and is the live, file-based
coordination channel.

**Canonical branch: `db1-s2-candidate-leg-scoring`.** Land work there.

## TL;DR roles
- **Claude** — LEAD DEV: Python implementation, architecture, docs, unit tests,
  branch/integration decisions; coordinates Cursor. Does NOT drive the live browser.
- **Codex** — TEST: live & integration testing against real TradingView (Selenium),
  e2e tests, browser-session management. **You're likely Codex if you can run the
  live browser.** Commit & push your tests to the canonical branch so they integrate.
- **Cursor** — HELPER to Claude: the dev sub-tasks Claude assigns in `COOP.md`
  (UI wiring, refactors, docs). Don't fork the coordination files.
- **Dev (Philipp)** — PO: human-eyes review, decisions, credentials, priorities.

## Active coordination
- Append progress/requests/results to the **Log** in `COOP.md`. Never edit
  another agent's entry.
- Check **Open handoffs** in `COOP.md` for work routed to you; there is an open
  REQUEST for Codex to live-test `scripts/review_fibs_tradingview.py`.
- Live tests need: logged-in Chrome on debug port 9222
  (`--remote-debugging-port=9222 --user-data-dir=.chrome-tv-manual`), chart on
  BITGET:BTCUSDT.P, 1H, UTC.

## Setup
See [ONBOARDING.md](ONBOARDING.md) for clone/config/run. Use `.venv/bin/python`.
