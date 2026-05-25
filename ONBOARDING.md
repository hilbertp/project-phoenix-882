# Project Phoenix — DB1 BTC Fib Discovery — Onboarding

> **If you are Claude Code, read this top to bottom and execute the steps.** This
> sets up a local environment to detect Bitcoin Fibonacci swing setups, view them
> in TradingView, and run the theoretical trade-plan analysis. Commands assume
> macOS/Linux + `bash`/`zsh`. Run everything from the repo root. Use the project
> virtualenv binary `.venv/bin/python` (NOT a global `python`).

## What this app does

DB1 is a discovery experiment on **`BITGET:BTCUSDT.P`, 1H candles, last 12 months**.
It auto-detects clean directional swing legs (an ATR zigzag), draws a Phoenix Fib
retracement on each (0.0 at the impulse extreme → 1.0 at the origin → 1.05 stop),
and evaluates a fixed theoretical trade plan:

- **Entry** 0.786 · **Initial SL** 1.05
- **TP1** 0.618 → take 25%, move SL to entry (break-even)
- **TP2** 0.382 → take 60%
- **TP3 / runner** 0.0 → take final 15%

It is a **review / discovery aid, not a trading signal** and computes no live orders.

## Prerequisites

- **Python 3.12** (`python3.12 --version`)
- **git**
- A **TradingView account** — only needed for the optional native-object placer
  (Step 5). Viewing via the Pine script (Step 3) needs no login.

## 1. Clone and create the environment

```bash
git clone https://github.com/hilbertp/project-phoenix-882.git
cd project-phoenix-882
git checkout db1-s2-candidate-leg-scoring   # branch with the DB1 fib work

python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install selenium pandas numpy pytest ruff tvDatafeed
```

There is no dependency lockfile; `pyproject.toml` holds only Ruff config. The
packages above are the full set the scripts import (websocket deps come in
transitively with `selenium` / `tvDatafeed`).

## 2. Get the market data (required — data is gitignored)

The candle CSV is **not** in git. Regenerate it (tvDatafeed guest session, no
login):

```bash
.venv/bin/python scripts/acquire_db1_12mo_data.py
```

Expected: writes `data/discovery_bet_1/bitget_btcusdt_p_1h_last_12_months.csv`
(+ a `.provenance.json` sidecar) and prints `WROTE ... rows=~8700 span_days=366`.

> **Reproducibility caveat:** this fetches the *last 12 months relative to today*,
> so your detected setups will differ from the reference review set (which ends
> 2026-05-24). To see the exact same setups, obtain that specific CSV from the
> repo owner and drop it at the path above (the filename/columns must match).
> If `tvDatafeed` fails to connect, retry, or install from source:
> `pip install git+https://github.com/rongardF/tvdatafeed.git`.

## 3. View the Fib setups — easiest path (TradingView Pine)

Generate the indicator, then paste it into TradingView. No browser automation,
no login.

```bash
.venv/bin/python scripts/export_db1_fib_review_pine.py
# -> artifacts/discovery_bet_1/db1_auto_fib_review.pine  (prints accepted_structures=N)
```

In TradingView:

1. Open a chart, set symbol **`BITGET:BTCUSDT.P`**, interval **1H**, timezone **UTC**
   (timezone matters — anchors are placed by bar time).
2. **Pine Editor** → paste the full contents of the `.pine` file → **Add to chart**.
3. Use the **"Focus structure"** input (`1..N`) to isolate one setup. Toggles:
   - *Show Phoenix Fib levels*, *Show theoretical trade plan*,
   - *Show Fib level reach tracker* — after the 0.786 entry it labels every level
     price moves to, in order (turnarounds included), until the 1.05 stop or 0.0
     target. Focused-structure only (label budget).

## 4. Analysis tools (CLI, no browser)

```bash
# Portfolio stats for the theoretical plan (trigger/win/wipeout/TP2/TP3 + avg R)
.venv/bin/python scripts/simulate_trade_plan.py 2026     # all 2026 auto setups
.venv/bin/python scripts/simulate_trade_plan.py manual   # 8 hand-validated setups

# Deterministic ordered level-reach sequence for one setup (turnaround-aware)
.venv/bin/python scripts/track_fib_reaches.py auto14     # also: auto5, auto12

# Execute the trade plan on one setup and narrate it (entry/TPs/SL, blended R)
.venv/bin/python scripts/execute_fib_strategy.py auto14
```

## 5. (Optional, advanced) Place native TradingView Fib objects

`scripts/place_fibs_tradingview.py` draws *real* Fib Retracement objects in your
own TradingView via Selenium attached to a Chrome debug session. Requires your
TradingView login.

```bash
# 1) Launch a login window controlled by the script (first run only):
.venv/bin/python scripts/place_fibs_tradingview.py login   # log in via Email in that window
# 2) Place setups (re-uses the logged-in session over debug port 9222):
.venv/bin/python scripts/place_fibs_tradingview.py 2026    # recent 3-month chunk, all visible
.venv/bin/python scripts/place_fibs_tradingview.py dry 12  # print legs only, no browser
```

Each setup becomes a named object in the Object Tree (`autoN DD-MM to DD-MM {span}c {depth}a`).

## 6. Verify the install

```bash
.venv/bin/python -m pytest tests/test_db1_fib_review_pine.py -q   # tracker + pine tests
.venv/bin/python -m pytest tests/ -q                              # full suite
```

## Key concepts & gotchas

- **Two lanes, same anchors-from-Python idea.** Detection (`_clean_legs`, an ATR
  zigzag) runs in Python on the CSV. The **Pine** lane redraws structures as an
  indicator (Step 3). The **native placer** (Step 5) drops real Fib objects via
  TradingView's chart API. The Pine lane currently uses an older detection path,
  so its anchors can differ from the placer's.
- **Timezone:** source timestamps are chart wall-clock (Asia/Nicosia, UTC+3);
  chart epochs are UTC. Set the TradingView chart to UTC when viewing the Pine.
- **Data + artifacts are gitignored** (`/data/**`, `/artifacts/**`). Regenerate
  with the acquire (Step 2) and export (Step 3) scripts.
- **Reach tracker rule:** records a level each time price touches one *different*
  from the last recorded (consecutive repeats collapsed) — so a 0.618↔0.5 chop is
  captured, not flattened. `scripts/track_fib_reaches.py` is the authoritative
  record; the Pine draws one level-change per bar to bound labels.

## File map

```text
data/discovery_bet_1/                         locked market CSV (gitignored; regenerate)
apps/worker/discovery_bet_1/                  detection: atr, pivots, candle_input, run_generator
apps/api/db1_fib_review_pine_read/service.py  Pine generator (fib levels, trade plan, reach tracker)
scripts/acquire_db1_12mo_data.py              fetch the 12-month CSV (tvDatafeed)
scripts/export_db1_fib_review_pine.py         write the .pine artifact
scripts/place_fibs_tradingview.py             native Fib placement (Selenium + TV chart API)
scripts/simulate_trade_plan.py                portfolio-level plan stats
scripts/track_fib_reaches.py                  per-setup ordered level-reach record
scripts/execute_fib_strategy.py              per-setup trade execution + blended R
docs/db1_swing_detection_method.md            how swings are detected (for manual reproduction)
tests/test_db1_fib_review_pine.py             tests for the Pine service + reach tracker
```
