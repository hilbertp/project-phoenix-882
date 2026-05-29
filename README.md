# Project Phoenix

Project Phoenix is a research-and-engineering platform for **discovering and
backtesting Fibonacci-retracement swing setups on crypto perpetuals**. Its first
and current line of work is **Discovery Bet 1 (DB1)**: auto-detect swing legs on
1-hour candles, place them as Fibonacci retracements, let a human confirm/correct
them, score several entry strategies, and explore the results across assets in an
interactive dashboard.

This README is the entry point for engineers and contributors. For canonical
folder/lane rules see [docs/repository_conventions.md](docs/repository_conventions.md);
for inbound-contribution terms see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## What the system does

```
acquire 1H candles ──▶ detect swing legs ──▶ place as Fib retracements
   (tvDatafeed)         (ATR zigzag)            (TradingView, Selenium)
                                                       │
                                          human review / correct  ─┐
                                                       │           │ labels (JSONL)
                                          score entry strategies ◀─┘
                                          (single + scaled regimes)
                                                       │
                                   interactive multi-asset dashboard
                                   (KPIs, equity, charts, feedback)
```

The same fixed **execution engine** scores every strategy, so results are
comparable across entry levels and across assets (BTC, ADA, ETH, BNB, XRP, SOL,
HYPE, TRX). BTC has a human-reviewed setup set with an in-dashboard feedback loop;
the other assets are scored on raw detector output.

---

## Quickstart

Prerequisites: **Python 3.12+**, **git**. (Optional: Google Chrome, only
needed for the "Manual review in TradingView" dashboard button — see the
section below if you want it.)

**Two commands from a fresh clone to a running dashboard** — same on macOS,
WSL2 Ubuntu, and bare Linux:

```bash
git clone https://github.com/hilbertp/project-phoenix-882.git && cd project-phoenix-882
./scripts/setup_phoenix.sh && ./scripts/start_phoenix.sh
```

`setup_phoenix.sh` is idempotent — re-running it is safe. It:
- Verifies Python 3.12+.
- Creates `.venv` if missing; upgrades pip; installs runtime + dev deps.
- Detects Chrome (just notes if missing — not fatal for the backtest views).
- Downloads BTC 1H 12-month data so the dashboard isn't empty on first launch.

`start_phoenix.sh` brings up the dashboard at `http://127.0.0.1:8800` and
opens your browser. The dashboard surfaces every backtest we've shipped
(per-asset, per-regime KPIs, candlestick + fib level overlays, per-setup
feedback). Highlights:

- **WASD / arrow-key navigation** across the setup table:
  `W`/`↑` approve · `S`/`↓` reject · `A`/`←` previous · `D`/`→` next · `Enter` done.
  Visible hint in the filter row.
- **"Manual review in TradingView"** button (top-right) opens a modal that
  spawns Chrome with a dedicated debug profile, waits for you to log into
  TradingView, then draws the most recent setups onto a live BITGET BTCUSDT.P
  1H chart as native Fib retracement objects. You review on TV; you give
  feedback back in the dashboard.

If you want to skip the setup script and run things by hand, the long form is:

```bash
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install pandas numpy matplotlib selenium pytest ruff
.venv/bin/pip install "git+https://github.com/rongardF/tvdatafeed.git"
.venv/bin/python scripts/acquire_db1_12mo_data.py   # BTC 1H, 12 months
./scripts/start_phoenix.sh
```

(`tvDatafeed` is hosted on GitHub, not PyPI — that's a recent upstream change,
nothing to do with this project.)

The dashboard opens on BTC (human-reviewed setups). Use the **Asset** dropdown to
flick to other coins; for those, acquire data first, e.g.:

```bash
.venv/bin/python scripts/acquire_asset_data.py BITGET ADAUSDT.P
```

**Run a backtest from the CLI** (no browser):

```bash
.venv/bin/python scripts/backtest_asset.py "ADA" data/discovery_bet_1/bitget_adausdt_p_1h_last_12_months.csv
.venv/bin/python scripts/score_labeled_setups.py        # BTC, scored vs human labels
```

> All commands run from the repo root and use `.venv/bin/python` (not a bare
> `python`). Data CSVs and `artifacts/` are gitignored.

### Optional: review setups directly in TradingView

The default `manual_review_*.py` scripts render PNG cards locally — no browser
needed, works the same everywhere. If you'd rather see the setups drawn as
native TradingView Fibonacci Retracement objects on a live chart,
`scripts/place_fibs_tradingview.py` automates that via a controlled Chrome
session. macOS runs it directly; Windows runs it inside WSL.

#### Windows users: get a working WSL environment first

WSL ("Windows Subsystem for Linux") is the official Microsoft way to run a
Linux distro inside Windows. Phoenix runs inside that Linux distro exactly the
same way it runs on a Mac.

**One-time WSL setup (PowerShell as Administrator):**

```powershell
wsl --install               # installs WSL2 + Ubuntu by default; reboot when prompted
wsl --update                # make sure WSLg (GUI support) is current
```

After reboot, launch **"Ubuntu"** from the Start menu. You're now at a Linux
shell. Everything below runs in that shell, not in PowerShell. WSLg (default
on Windows 11) means GUI apps you launch from this Linux shell — including
Chrome — appear as normal windows on your Windows desktop.

(Windows 10 users: WSL works the same but you need an X server like VcXsrv
plus `export DISPLAY=:0` in your `~/.bashrc`. Recommend upgrading to Windows
11 if you can — WSLg is much smoother.)

#### Set up the project + Chrome (macOS and WSL — identical commands)

```bash
# macOS only: brew install --cask google-chrome      (if not already installed)

# WSL only: install Chrome INSIDE the Linux distro (not Windows Chrome --
# the script attaches to a local debug port that has to be on WSL's localhost)
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt update
sudo apt install -y ./google-chrome-stable_current_amd64.deb
google-chrome --version    # auto-detected path is /usr/bin/google-chrome

# everyone, first time: clone + venv (skip if you already did the Quickstart above)
git clone https://github.com/hilbertp/project-phoenix-882.git
cd project-phoenix-882
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install tvDatafeed pandas numpy matplotlib selenium pytest ruff

# everyone, every time you want the latest updates: pull and refresh deps.
# Run this from inside the WSL Ubuntu shell (or your macOS terminal), NOT
# from PowerShell -- PowerShell can't see the WSL filesystem cleanly.
cd ~/project-phoenix-882            # or wherever you cloned it
git pull origin main                # gets the latest commits from GitHub
.venv/bin/pip install --upgrade -r requirements.txt 2>/dev/null || \
  .venv/bin/pip install --upgrade tvDatafeed pandas numpy matplotlib selenium pytest ruff
```

The script auto-detects Chrome via `_find_chrome_binary()`. Override with
`export PHOENIX_CHROME_BINARY=/path/to/chrome` if needed.

#### Run the workflow (one canonical command — macOS and WSL identical)

```bash
./scripts/tv-go.sh              # default: 12 setups, recent-3M
./scripts/tv-go.sh 24           # 24 setups
./scripts/tv-go.sh manual       # the 8 hand-picked reference setups
```

`tv-go.sh` does the full journey in one shell:

1. **Checks Chrome on port 9222.** If not running, spawns debug Chrome with
   the project-local profile (`.chrome-tv-manual/`) on the right chart URL,
   waits up to 20s for the port to bind, then sleeps 12s so TradingView
   can load its initial bars.
2. **Places N setups** on the live chart as native Fib Retracement objects.
3. **Reads TV's actual loaded bar range** and filters setups to those that
   fall inside it (so the auto-pan never lands on an unplaceable timestamp).
4. **Injects the WSAD review panel** and immediately drops you into the
   first setup, with the chart auto-panned to it.

If this is the first run on a machine, you'll see the Chrome window open
to TradingView's login screen — log in with Email (Google SSO can stall
in a fresh profile) and the script proceeds automatically.

Three smaller scripts are also there if you want them callable individually:

```bash
./scripts/tv-login.sh           # just spawn Chrome (no placement, no review)
./scripts/tv-place.sh [N|dry]   # just place setups
./scripts/tv-review.sh [mode]   # just start the review panel
```

The WSAD overlay appears on the TradingView chart (NOT in the dashboard):

```
W / ↑      approve  (✓ exaaactly to the ms)
S / ↓      reject   (✗ wtf - not a real setup)
A / ←      back     (previous setup)
D / →      next     (next setup)
Enter      done     (end the review session)
```

When you press W or S, the current setup gets a verdict in
`data/discovery_bet_1/human_labels.jsonl`. The detector picks those up
on the next backtest run, so labels you give today shape tomorrow's
scoring. Dragging the Fib's anchors in TradingView + clicking "Save edit"
captures corrected anchors and writes them as a VERDICT_ADJUST entry.

The login session persists in `.chrome-tv-manual/` (project-local, gitignored)
— each contributor has their own. **Don't copy it between machines.**

#### Common failure modes

- `"No debug Chrome on 127.0.0.1:9222"` → Step 1 never ran, or the Chrome
  window from Step 1 got closed. Rerun Step 1.
- `"No Chrome binary found"` → install Chrome (see above) or set
  `PHOENIX_CHROME_BINARY` to the full path.
- WSL: Chrome window doesn't appear at all → WSLg is missing or stale. Run
  `wsl --update` in PowerShell, restart WSL (`wsl --shutdown`), retry.
- TradingView shows "checking your browser" forever → fresh-profile bot
  detection. Close all `chrome-tv-manual` Chrome windows, wait 30s, retry
  Step 1. Use the Email login (Google SSO can stall in a fresh profile).
- Setups appear but visually misaligned → chart drifted off 1H or off the
  right symbol. Open the URL in `LAYOUT_URL` (inside the script) to reset
  to a clean 1H `BITGET:BTCUSDT.P` layout, then rerun Step 2.

If you skip this section entirely, you still get the same setups as static
PNGs from `scripts/manual_review_ada_15m.py` (or `render_db1_fib_review_proof.py`
for BTC). The TradingView path is purely a "review in your normal charting
tool" quality-of-life upgrade.

---

## Repository layout

```text
apps/
  worker/discovery_bet_1/   Core generation engine (detection, fib geometry, lifecycle, labels)
  worker/main.py            Offline generation entry point
  api/                      HTTP read/write services over generated artifacts
  api/main.py               Review-read API server (default :8000)
  ui/                       Frontend application lane (reserved)
scripts/                    Operational toolbelt: data, placement, backtest, dashboard, exports
data/discovery_bet_1/       Source candle CSVs (+ provenance) and human_labels.jsonl  (gitignored)
artifacts/discovery_bet_1/  Generated outputs: reports, dashboard.html, Pine, proofs   (gitignored)
docs/                       Conventions, capability reviews, method notes
infra/docker/               Container stack
tests/                      pytest suite (apps/* coverage)
```

### Core engine — `apps/worker/discovery_bet_1/`

| Module | Responsibility |
|---|---|
| `market_contract.py` | The locked source contract (symbol/interval) and its validation. |
| `candle_input.py` | Load + validate the source CSV against the column/timestamp/provenance contract. |
| `atr.py` | `calculate_atr14` — hourly ATR(14). |
| `pivots.py` | `detect_local_pivots` — local swing pivots. |
| `fib_structures.py` | Build candidate Fibonacci structures from pivots/legs. |
| `lifecycle.py` | Materialize fib structures and apply invalidation rules. |
| `anchor_selection.py` | Choose the parent/terminal anchors for a leg. |
| `human_labels.py` | Append-only review labels (accept/reject/adjust/add); `truth_setups`, `apply_overrides`. |
| `export.py` | Write generation artifacts. |
| `run_generator.py` | `run_generation()` pipeline; `DEFAULT_INPUT_PATH`, `DEFAULT_ARTIFACTS_DIR`. |
| `types.py` | `Candle`, `GenerationOutputs`, and friends. |

### Service lane — `apps/api/`

Read/write HTTP services exposing the generated review artifacts (swing read,
leg read, review read/summary/writeback, TradingView/Pine exports, chart-truth
verdicts). Served by `apps/api/main.py` (`--host/--port/--artifacts-dir`, default
`127.0.0.1:8000`). These back the supervised review/capability stages and are the
durable, tested surface of the platform.

---

## Core concepts

**Phoenix Fibonacci geometry.** A leg runs from a **parent** anchor to a
**terminal** extreme. Levels are mapped so that **1.0 = parent**, **0.0 = terminal**,
and **1.05 = the stop** (just beyond the parent). Retracement entries sit between
(e.g. 0.786, 0.882, 0.941); take-profits run toward 0.0. Helper:
`scripts/execute_fib_strategy._lvl(terminal, parent, coeff)`.

**ATR-zigzag detector.** `_clean_legs(candles, atr, pivots, min_bars, mult)`
(in `scripts/place_fibs_tradingview.py`) walks the series and closes a leg only
when price retraces ≥ `ATR × mult`, gated by a `min_bars` minimum length. The
config is **per-asset**: BTC's human set uses `24c / 4×`; the alts farm finer
swings (e.g. `6c / 2.0×`) — see `scripts/sweep_asset_detector.py` to retune.

**Entry regimes.** Defined in one catalog, `scripts/execute_fib_strategy.REGIMES`:
the single-entry plans (0.786 / 0.882 / 0.941, each entry | SL 1.05 | TP1=break-even
| TP2 | TP3) and the **scaled** strategy (tranche in 50/25/25 at 0.786/0.882/0.941,
shared 1.05 stop, blended break-even, one 25% partial then a lagging stop). The
first catalog entry is the live default for the CLI and review panel. Dispatch via
`run_regime(candles, idx, swing, regime)`.

**Scoring & R.** `execute()` / `execute_scaled()` return a bar-by-bar outcome and a
blended **R** (1R = entry→stop risk). Win rate is counted over **triggered trades
only** (no-entry "shrugs" excluded): `win rate = (TP1+TP2+TP3)/N`, `loss = wipeouts/N`.
Intrabar resolution is nearest-first and the entry bar is skipped, matching the
Fib-level reach engine (`scripts/track_fib_reaches.py`).

**Human-in-the-loop labels.** Review verdicts append to
`data/discovery_bet_1/human_labels.jsonl` (latest-by-key wins). `truth_setups()`
yields the de-duplicated ground-truth set (accept + adjust-corrected + add, rejects
excluded) that feeds calibration (`scripts/calibrate_detector.py`) and the BTC
dashboard.

---

## The toolbelt — `scripts/`

| Script | Purpose |
|---|---|
| `acquire_db1_12mo_data.py` | Pull BITGET:BTCUSDT.P 1H, 12 months → source CSV + provenance. |
| `acquire_asset_data.py EXCHANGE SYMBOL` | Same, for any symbol (ADA/ETH/BNB/XRP/SOL/HYPE/TRX…). |
| `execute_fib_strategy.py [name]` | Run one setup through a regime and narrate it; home of `REGIMES`, `execute*`. |
| `backtest_asset.py LABEL CSV` | Detector setups → score every regime for an asset. |
| `sweep_asset_detector.py CSV` | Sweep min-bars × ATR-mult and score, to retune detection per asset. |
| `score_labeled_setups.py` | Score the BTC human truth set under each regime. |
| `dashboard_server.py [--port N] [--open]` | Interactive multi-asset dashboard server (stdlib `http.server`, no web framework). |
| `build_dashboard.py` | Static self-contained `dashboard.html` (BTC regimes). |
| `track_fib_reaches.py` | Deterministic Fib-level reach sequence (the reach-order ground truth). |
| `simulate_trade_plan.py`, `plot_depth_histogram.py` | Plan backtest over auto setups; setup-depth distribution. |
| `place_fibs_tradingview.py`, `review_fibs_tradingview.py` | Selenium: place/redraw setups on TradingView; human review panel. |
| `export_*`, `render_db1_fib_review_proof.py` | Pine-indicator and proof-image exports. |
| `format.sh`, `lint.sh`, `stack_up.sh`/`stack_down.sh`, `runtime_verify.sh` | Dev/ops helpers. |

### Interactive dashboard

`scripts/dashboard_server.py` serves `scripts/dashboard_app.html` (single-page app,
no build step) plus a small JSON API:

- `GET /api/state?asset=<key>&min_bars=<n>&mult=<x>` — regimes, every setup with its
  per-regime outcome (status, R, fib levels, bar-by-bar events), windowed candles,
  and aggregates.
- `POST /api/feedback` — append a verdict to `human_labels.jsonl` (BTC only).

Per asset it shows KPI cards, an equity curve (adaptive, comparable scale, overlay-all),
a reward:risk/expectancy card, a filterable setup table, and a click-to-inspect
candlestick chart with the fib levels and the execution log. BTC additionally
exposes the feedback loop (confirm / wtf / fix-anchors). **Adding an asset** = one
`acquire_asset_data.py` run + one line in the `ASSETS` catalog in `dashboard_server.py`.

---

## Development

```bash
.venv/bin/python -m pytest            # run the test suite (tests/)
sh scripts/lint.sh                    # ruff check apps/api apps/worker
sh scripts/format.sh                  # ruff format
sh scripts/stack_up.sh                # docker compose up (infra/docker)
.venv/bin/python -m apps.api.main     # review-read API on :8000
.venv/bin/python -m apps.worker.main --input <csv>   # offline generation
```

Ruff config lives in `pyproject.toml` (line length 88; `E`/`F`/`I`; lint scope is
`apps/api` and `apps/worker`). Tests are plain `pytest` under `tests/`.

**Conventions & coordination.** Folder/lane ownership and placement rules are in
[docs/repository_conventions.md](docs/repository_conventions.md). Multi-agent
working agreements (lead dev / test / helper roles) are in [AGENTS.md](AGENTS.md)
and [COOP.md](COOP.md). [ONBOARDING.md](ONBOARDING.md) is a machine-readable setup
guide for handing the repo to another agent.

---

## Status and honest caveats

The platform foundation (worker generation, api review services, tests, Docker,
lint) is the stable core. The strategy/backtest/dashboard layer in `scripts/` is
active research, and its numbers should be read with care:

- Backtests are **in-sample** (one ~12-month window per asset) and the dashboard
  reports **gross R (no fees/slippage)**. Net of realistic costs, edges shrink
  substantially, especially high-frequency / many-fill variants.
- Fine detector configs (e.g. `6c/2.0×`) are powerful but easy to **overfit**; a
  walk-forward split + cost model is required before treating any result as real.
- Non-BTC setups are **raw detector output** (no human review). BTC is the only
  asset with a curated, labeled ground-truth set.

Treat the dashboard as an exploration surface, not a verified trading signal.

---

## License

Project Phoenix is licensed under the [Apache License, Version 2.0](LICENSE):
commercial use, modification, redistribution, and private/proprietary use are
permitted under the license terms. Contributions are accepted under the same
Apache-2.0 terms unless explicitly stated otherwise — see [CONTRIBUTING.md](CONTRIBUTING.md).
```
