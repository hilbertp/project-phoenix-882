# Project Phoenix

Project Phoenix is the central repository for the platform foundation. At the current stage, it provides the initial repository layout, ownership boundaries, and a small Python backend developer workflow baseline.

## Start Here

- Read [docs/repository_conventions.md](docs/repository_conventions.md) for canonical folder purpose, lane ownership, and placement rules.
- Use the root of the repo as the entry point for understanding where API, worker, UI, data, artifacts, infrastructure, and scripts belong.
- New here? Jump to the **[Tutorial](#tutorial--review-btc-fib-setups-for-new-users)** below.

## Tutorial — Review BTC Fib setups (for new users)

This walks you through the DB1 discovery tool: it auto-detects Bitcoin Fibonacci
setups on `BITGET:BTCUSDT.P` (1H), shows them to you one at a time on TradingView,
and **learns from your feedback** to detect better. No prior knowledge needed —
copy/paste each command.

> Prerequisites: **Python 3.12**, **git**, and a free **TradingView account**.
> All commands run from the repo root. macOS/Linux shown.

### 1. Get the code + a Python environment

```bash
git clone https://github.com/hilbertp/project-phoenix-882.git
cd project-phoenix-882
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install selenium pandas numpy matplotlib tvDatafeed
```

### 2. Download the market data (one command)

```bash
.venv/bin/python scripts/acquire_db1_12mo_data.py
```

Pulls 12 months of 1H candles into `data/discovery_bet_1/` (no login needed).

### 3. Open a TradingView window and log in

```bash
.venv/bin/python scripts/place_fibs_tradingview.py login
```

A Chrome window opens. **Log into TradingView** there and set the chart to
**`BITGET:BTCUSDT.P`, 1H**. Logging in matters — it loads full history (no rate
limit) and applies your own Fib drawing style.

### 4. Start the review panel

```bash
.venv/bin/python scripts/review_fibs_tradingview.py
```

A control panel appears top-right in that Chrome, showing **one setup at a time**
as a real Fib object. For each setup the panel shows its direction, dates,
**candle span**, **ATR depth**, whether it clears the detector's gates, and the
**trade outcome** (win / loss / miss).

### 5. Review each setup

| Do this | Click | or press |
|---|---|---|
| Approve (good setup) | `✓ exaaaactly (to the ms)` | **W** / **↑** |
| Reject (not a setup) | `✗ wtf` | **S** / **↓** |
| Previous / Next | `◀ Back` / `Next ▶` | **A**/**←** / **D**/**→** |
| Fix the anchors | drag the Fib's dots, then `✎ Save edit` | — |
| Add a missed setup | draw a Fib with TradingView's tool, then `+ Report missed setup` | — |
| Finish | `Done` | **Enter** |

Hover any button (or click **ⓘ Info**) to see what it does. When you save an edit
or report a missed setup, the panel **echoes back exactly what it captured** so
you can confirm it understood.

### 6. See your report

Press **Enter** (or click **Done**) → a report shows **every setup with your
feedback and its win/loss**, plus win rate and average R. It's also saved to
`artifacts/discovery_bet_1/review_report.html`.

### 7. Watch the engine learn (optional)

```bash
.venv/bin/python scripts/calibrate_detector.py
```

Reads your feedback and finds the detector settings (min-bars × ATR-multiple)
that best reproduce the setups you approved while avoiding the ones you rejected.

### Other tools

```bash
.venv/bin/python scripts/export_db1_fib_review_pine.py   # TradingView Pine indicator version
.venv/bin/python scripts/simulate_trade_plan.py 2026     # backtest the trade plan over all setups
.venv/bin/python scripts/plot_depth_histogram.py         # chart the setup depth distribution
```

> Troubleshooting: if a command says "No debug Chrome on 127.0.0.1:9222", re-run
> step 3 (the login command) and keep that Chrome window open.

## Top-Level Structure

```text
apps/
  api/              Backend API service lane
  worker/           Background worker lane
  ui/               Frontend application lane

data/               Non-Git analytical and source data
artifacts/          Generated outputs from runs
docs/               Repository documentation and conventions
infra/docker/       Container and runtime configuration area
scripts/            Developer helper scripts
```

## Current A1 Foundation Status

The repository currently includes:

- initial lane structure for `apps/api`, `apps/worker`, and `apps/ui`
- canonical repository conventions in [docs/repository_conventions.md](docs/repository_conventions.md)
- a repo-level Ruff baseline for the Python backend footprint
- minimal local environment file guidance via `.env.example`
- developer scripts for formatting and linting the backend Python paths in `scripts/`

## Not Fully Built Yet

The repository is still in foundation mode. It does not yet provide a fully built runtime, CI pipeline, Docker workflow, or substantive feature implementation across the application lanes.

## License

Project Phoenix is licensed under the [Apache License, Version 2.0](LICENSE).
This permissive license supports community contributions while allowing commercial use, private use, redistribution, modification, and proprietary products built from the project, subject to the license terms.

Contributions are accepted under the same Apache-2.0 terms unless explicitly stated otherwise. See [CONTRIBUTING.md](CONTRIBUTING.md) for the inbound contribution note.
