# AGENTS.md

This repo is worked by multiple agents. **Before doing anything, read
[COOP.md](COOP.md)** — it defines who owns what and is the live, file-based
coordination channel.

## TL;DR roles
- **Claude** — Python implementation, design, docs, pure-Python unit tests. Does
  NOT drive the live browser.
- **Codex** — live & integration testing against the real logged-in TradingView
  (Selenium), browser-session management. **You are most likely Codex if you can
  run the live browser.**
- **Dev (Philipp)** — human-eyes setup review, product decisions, credentials,
  shared-branch pushes.

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
