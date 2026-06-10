# TradingView Manual Review — Runbook

**This is the live, working tool for reviewing DB1 swing/Fib setups on a real
TradingView chart with W/S/A/D keys.** (Not the TamperMonkey overlay in
`CLAUDE.md` — that is an unbuilt design spec. This selenium-driven tool is what
actually runs today.)

---

## THE COMMAND

```bash
cd ~/project-phoenix-882 && ./scripts/tv-btc.sh 2026-05
```

That is the whole thing. `2026-05` = the calendar month to review (any `YYYY-MM`).

- **Do NOT prefix with `git pull`.** This repo IS the source of truth; pulling
  only fails on the modified `human_labels.jsonl` (your saved verdicts). Pull
  only if you are syncing a *different* clone.
- **Working dir is `~/project-phoenix-882`.** `~/project-phoenix` is a dead husk
  with no `.git` — do not use it.

---

## New machine / collaborator quickstart (macOS or WSL2 Ubuntu)

```bash
git clone https://github.com/hilbertp/project-phoenix-882.git ~/project-phoenix-882
cd ~/project-phoenix-882
./scripts/bootstrap.sh        # venv + deps + Chrome check + ALL market data (one-time, ~10 min)
PYTHONPATH=. .venv/bin/python scripts/place_fibs_tradingview.py login   # log into TV once (Email option)
./scripts/tv-btc.sh 2026-05 --min-bars 6 --mult 4.0                     # review May at 6c/4x
```

Existing clone instead: `git pull --rebase --autostash origin main` then the
same bootstrap (it only does what's missing). On WSL2, Chrome must be
installed INSIDE the distro (`sudo apt install ./google-chrome-stable_current_amd64.deb`);
WSLg puts its window on the Windows desktop. Each machine keeps its own
TradingView login in `~/.phoenix-chrome-tv` — log in once, it persists.
Verdicts append to `data/discovery_bet_1/human_labels.jsonl` (in git), so
commit + push after a review session to share your grades.

---

## Does it re-scrape / re-compute? (the FAQ)

| Step | Past month (e.g. 2026-05) | Current month (e.g. 2026-06) |
|---|---|---|
| **Scrape Binance** | **Skipped** — CSV already covers it, runs fully offline | Runs (needs latest bars) |
| **Detector compute** | Re-runs every time (~1s, deterministic) | same |
| **Setups** | Computed in memory, identical every run — **not** stored in a DB | same |

So a past-month replay is **fast and reproducible**: no network, and the same
27 setups every time (immutable history + deterministic 6c/2.0× detector).
The slow part is TradingView loading the chart + paging history (~30–60s),
not data or compute.

CSV: `data/discovery_bet_1/binance_btcusdt_1h_full_history.csv` (Binance spot).

---

## What you see / do

Chart loads on **`BINANCE:BTCUSDT` @ 1H**, setup 1 of N auto-zoomed with its fib
(1.05 stop / 1.0 parent / 0.941 entry / 0.882 BE / 0.5 / 0 terminal).

| Key | Action |
|---|---|
| **D** / → | next setup (auto-zooms) |
| **A** / ← | previous setup |
| **W** | accept (anchors + outcome correct) |
| **S** then **R** | setup wrong (bad anchors) |
| **S** then **F** then **1/2/3/L/M** | outcome wrong → TP1/TP2/TP3/Loss/Miss |
| **Enter** | end session → writes report + renders overlay on chart |

Click the **panel** (top-left box) once so it has keyboard focus — not the chart.

Verdicts append to `data/discovery_bet_1/human_labels.jsonl`
(tagged `asset=BTC, month=YYYY-MM`). Session report (markdown) lands in
`artifacts/discovery_bet_1/manual_review_btc_1h_month/`.

Detector: **6 bars min, 2.0× ATR min**. Miss-filter ON (only setups where the
0.941 entry was tagged). `PHOENIX_REVIEW_INCLUDE_MISSES=1` to keep misses.

---

## Hard constraints (why it broke before — do not relearn)

1. **Chrome debug profile, NOT your real profile.** Chrome 136+ silently ignores
   `--remote-debugging-port` on the OS-default profile (anti-automation
   hardening; confirmed on Chrome 148). The tool uses a dedicated profile at
   **`~/.phoenix-chrome-tv`** (outside the repo, so the TradingView login
   persists across clones — you log in there **once**). Override with
   `PHOENIX_CHROME_PROFILE=/abs/path`.

2. **Chart must stay `BINANCE:BTCUSDT`.** The CSV is Binance-spot OHLC. If the
   chart drifts to GOLD / `BITGET:BTCUSDT.P`, anchors land on wrong prices and
   the zoom dies. The launch swallows stray printable keys so TV's
   type-a-letter symbol-search popup can't open. The watchlist stays VISIBLE
   and usable — but clicking a symbol in it still switches the chart, so if you
   do, click `BTCUSDT` back and press A then D.

3. **Never attach a throwaway selenium session to the running debug Chrome.**
   When that script exits, its garbage-collected driver sends `quit`, which
   CLOSES the shared browser and kills the live review. Diagnose from the
   review's stdout (every `show()` logs `nav=<method>`), and use OS-level
   screenshots — never a second selenium connection.

4. **One reviewer at a time.** Two `tv_review_btc_month.py` processes on one
   Chrome fight over the panel (index jumps, drawings flicker). The wrapper
   `pkill`s any stale reviewer before launching.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `cannot pull with rebase: unstaged changes` | You don't need to pull. Just run `./scripts/tv-btc.sh 2026-05`. |
| `0 clean legs` / `no triggered setups` | CSV got truncated by a failed fetch. Restore: `PYTHONPATH=. .venv/bin/python scripts/acquire_long_asset.py BTCUSDT 1h` and confirm the last bar reaches ~today. (acquire now retries + refuses to clobber a longer file.) |
| Panel/fibs never appear | Debug Chrome didn't bind `:9222` — almost always the wrong profile. Confirm `~/.phoenix-chrome-tv` exists and you're logged into TV there. |
| Chart on GOLD/Bitget | You switched symbols. Click `BTCUSDT`, press A then D. |
| Next/Back don't zoom | You're not on `BINANCE:BTCUSDT` (bars not found). Switch back. |

Implementation: `scripts/tv-btc.sh` (wrapper) → `scripts/tv_review_btc_month.py`
(driver) → shared JS in `scripts/review_fibs_tradingview.py`,
`scripts/place_fibs_tradingview.py`.
