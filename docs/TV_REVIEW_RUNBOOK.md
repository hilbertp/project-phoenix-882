# DB1 BTC Backtesting & TradingView Review — Operating Manual

**Audience: any agent or human with fresh context.** Everything here is
current as of 2026-07-03 and verified working. If you follow only one rule:
run the commands below from `~/project-phoenix-882` and trust the supervisor —
it self-heals. A full-screen overlay or yellow panel text means WAIT; only a
missing overlay + missing panel for >2 minutes means something is wrong.

---

## The three commands

All from `cd ~/project-phoenix-882`. Working clone is **`project-phoenix-882`**
(`~/project-phoenix` is a dead husk with no `.git` — never use it).

### 1. Manual review on TradingView (the WSAD panel)

```bash
./scripts/tv-btc.sh last92d --exit-plan rest50          # trailing 92 days
./scripts/tv-btc.sh 2026-05                             # calendar month
./scripts/tv-btc.sh 2026-04 --min-bars 24 --mult 4.0    # custom detector gates
```

This is a SUPERVISOR: it health-checks Chrome with a real attach probe,
remediates automatically (stale locks → poisoned cache → full relaunch, 3
attempts), restarts + RESUMES if the browser dies mid-session, and the review
itself self-heals TradingView wedges (lazy fib-module via the Alt+F pre-warm,
history eviction via re-paging, broken pages via reload + re-init, the
ad-blocker nag modal via a 2s watchdog). Verdicts persist in
`data/discovery_bet_1/human_labels.jsonl` (in git — commit + push after a
session); a relaunch resumes at the first unreviewed setup.

Panel keys: **W**=setup+outcome correct · **S→R**=not a real swing ·
**S→F→1/2/3/L/M**=real setup, corrected outcome · **A/D**=prev/next ·
**Enter**=finish (writes a markdown report + on-chart overlay).

### 2. Backtest grid (the standard results table, no browser)

```bash
PYTHONPATH=. .venv/bin/python scripts/backtest_grid.py --month 2026-05
PYTHONPATH=. .venv/bin/python scripts/backtest_grid.py --last-days 92 --exit-plan rest50 --veto
```

Every (min-bars × ATR-mult) detector combo; `--veto` adds the Ichimoku
regime-filtered line per config. Runs in ~1-2 min, fully offline for past
windows.

### 3. Rendered review cards (PNGs with 5m zooms, no browser)

```bash
PYTHONPATH=. .venv/bin/python scripts/render_btc_month_review.py --month 2026-05 --min-bars 6 --mult 4.0
open artifacts/discovery_bet_1/manual_review_btc_1h_month/cards_2026-05_6c4x/index.html
```

One PNG per setup: 1H context, all fib levels, numbered executor events, the
active-stop drag line, one 5m zoom per decisive hour, regime VETO/trade badge,
and DISPUTE tags where the engine disagrees with the latest human label.

---

## New machine (macOS or WSL2 Ubuntu) — one-time, ~10 min

```bash
git clone https://github.com/hilbertp/project-phoenix-882.git ~/project-phoenix-882
cd ~/project-phoenix-882
./scripts/bootstrap.sh     # venv + deps + Chrome check + 1H & 5m market data
PYTHONPATH=. .venv/bin/python scripts/place_fibs_tradingview.py login   # TV login ONCE (Email option)
```

Existing clone: `git pull --rebase --autostash origin main`, then bootstrap
(idempotent — only does what's missing). WSL2: Chrome must be installed INSIDE
the distro; WSLg shows the window on the Windows desktop. Each machine keeps
its own TradingView login in `~/.phoenix-chrome-tv` (persists across clones).

---

## The strategy & engine (what the numbers mean)

- **Setup**: ATR-zigzag swing legs on BINANCE:BTCUSDT 1H (CSV = Binance spot).
  Detector gates are MINIMUMS: `--min-bars 6 --mult 2.0` = every leg with ≥6
  candles and ≥2× ATR depth (raising `mult` changes the zigzag walk, not just
  a filter).
- **Trade**: enter 0.941 retrace · SL 1.05 (FIXED — never widen) ·
  exit plans: `runner` = TP1 25% at 0.882 (SL→entry) / TP2 60% at 0.5 / TP3
  15% at 0.0; `rest50` = TP1 25% at 0.882 (SL→entry) / remaining 75% at 0.5.
- **Outcome engine** (`scripts/execute_fib_strategy.py::execute`) is
  HUMAN-VALIDATED (26/27 against the user's graded May-2026 review) and locked
  by `tests/test_execute_outcome_ground_truth.py` — run it after ANY executor
  change. Rules: stop live from the fill bar; fill bar can kill but never
  credit; same-bar ambiguity resolves unfavorably; touch-based BE stop;
  micro-graze rule; 5m sub-bars resolve intra-candle order (5m > 15m > 1H).
- **Regime detector** (`scripts/ichimoku_regime.py`): the 26-bar two-sides
  rule — if price closed above AND below the Ichimoku cloud within the last
  26 bars, the market is repricing → no trades. Measured effect over 12
  months: −35.8R unfiltered → +3.2R with veto (6c/4x).

Research state in one line: no detector-parameter pair wins across months;
the regime veto improved every single month tested; exit-plan choice is
second-order. Labels: `accept`=engine correct, `wrong_kind=setup`=not a real
swing, `wrong_kind=outcome`+expected=corrected class. Win rate =
(TP1+TP2+TP3)/triggered.

---

## Hard constraints (violating these cost hours — do not relearn)

1. **NEVER attach a second selenium session to the running debug Chrome** —
   its teardown kills the shared browser and the live review. Diagnose from
   `/tmp/tv-btc.log` (every show() logs nav method + placement result) and
   OS-level screenshots only.
2. **Chrome debug requires the dedicated profile** `~/.phoenix-chrome-tv` —
   Chrome 136+ silently refuses `--remote-debugging-port` on the OS-default
   profile. Never point the tooling at the user's real profile.
3. **Chart symbol must stay BINANCE:BTCUSDT** (spot, matches the CSV). The
   launch enforces this; a watchlist click can still switch it — recovery is
   click BTCUSDT, then press A.
4. **Only one review process at a time** (the wrapper enforces this; two
   fight over the panel).
5. **curl on :9222 is not a health check** — zombie Chrome answers HTTP but
   refuses sessions. Only a real attach probe counts (the wrapper does this).
6. **`data/` is gitignored except `human_labels.jsonl`** — market data comes
   from bootstrap/acquire, never from git; the acquirer refuses to truncate.

## Troubleshooting (rarely needed now)

| Symptom | Action |
|---|---|
| Full-screen overlay or yellow "loading" text | WAIT — self-heal in progress (30-90s) |
| No overlay, no panel, >2 min | check `/tmp/tv-btc.log`; worst case `rm -rf ~/.phoenix-chrome-tv/Default/Cache` and rerun |
| "0 clean legs" / "no triggered setups" | CSV truncated or window wrong — rerun `scripts/acquire_long_asset.py BTCUSDT 1h` |
| TV asks for login | log in once in the opened window (Email option); it persists |
| Engine outcome disputed by eye | that's data: grade it S→F in the review; the ground-truth test absorbs it |

Implementation map: `scripts/tv-btc.sh` (supervisor) →
`scripts/tv_review_btc_month.py` (review driver) → shared JS in
`scripts/place_fibs_tradingview.py` + `scripts/review_fibs_tradingview.py`;
engine `scripts/execute_fib_strategy.py`; regime `scripts/ichimoku_regime.py`;
grid `scripts/backtest_grid.py`; cards `scripts/render_btc_month_review.py`.
