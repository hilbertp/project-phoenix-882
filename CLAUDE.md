# project-phoenix

> ## ⚡ START HERE — BTC backtesting & TradingView review
> **Main goal ([docs/MISSION.md](docs/MISSION.md)):** a reliable fib-entry
> detector with quickly-swappable variables — timeframe, min pivot candles,
> entry level (786/882/941), SL/TP strategy incl. trailing — to find the most
> lucrative tradable setup.
> **The complete, current operating manual is
> [docs/TV_REVIEW_RUNBOOK.md](docs/TV_REVIEW_RUNBOOK.md)**, and the engine's
> human-learned rule set (with provenance + reproduction protocol) is
> **[docs/ENGINE_RULES.md](docs/ENGINE_RULES.md)**. Read it before
> touching anything in this area. The three working commands:
>
> ```bash
> ./scripts/tv-btc.sh last92d --exit-plan rest50    # supervised manual review on TV (self-healing)
> PYTHONPATH=. .venv/bin/python scripts/backtest_grid.py --last-days 92 --veto   # results table
> PYTHONPATH=. .venv/bin/python scripts/render_btc_month_review.py --month 2026-05 --min-bars 6 --mult 4.0  # PNG cards
> ```
>
> New machine: `./scripts/bootstrap.sh` then TV login once. NEVER attach a
> second selenium session to the running debug Chrome (kills the live review);
> full-screen overlay / yellow panel text = wait, it self-heals. The full
> never-do list and troubleshooting live in the runbook.
>
> (The TamperMonkey overlay described in the rest of THIS file is an unbuilt
> design spec — NOT the tool that runs today.)

## What this is

DB1 review panel — a compact floating overlay injected into TradingView via
TamperMonkey. Used for manually reviewing DB1 swing/Fib setups and labelling
them (accept / reject with reason / anchor correction).

---

## Files

| Path | Role |
|---|---|
| `docs/db1_review_overlay_design.html` | Canonical design spec, interactive prototype, and DOM contract |
| `docs/db1_review_panel_prd.md` | UI requirements PRD |
| `.claude/launch.json` | Static server config — serves `docs/` on port 7331 |
| `apps/review/db1_review_panel.user.js` | TamperMonkey userscript (**not yet created**) |

---

## Previewing the design file

Start the server via the `db1-review-panel` launch config (port 7331), then
open `http://localhost:7331/db1_review_overlay_design.html`.

The body simulates a TradingView chart canvas (dark grid). The overlay is
`position: fixed; top: 110px; right: 6px; width: 340px` — matching the actual
overlay position on a live TV chart.

---

## TV chrome avoidance constants

| Constant | Value | Reason |
|---|---|---|
| `top` | 110px | Clears TV global nav (~60px) + chart toolbar strip (~45px) |
| `right` | 6px | TV has no mandatory right chrome when the watchlist is closed |
| `width` | 340px | Fits all six rejection reason buttons; leaves ~65% of a 1440px chart visible |
| `z-index` | 9999 | Above TV UI; below browser chrome |

---

## DOM contract

External code (the TM userscript, tests) must use these IDs — do not rename them.

| ID | Element |
|---|---|
| `db1-review-overlay-root` | Root container |
| `db1-review-chart` | Hidden slot for canvas injection by caller |
| `db1-review-meta` | Metadata row (setup index, symbol, time, status) |
| `db1-review-list` | Setup chips list |
| `db1-review-export-state` | Export / status line |
| `db1-review-prev` | Previous setup button |
| `db1-review-next` | Next setup button |
| `db1-review-export` | Copy reviews button |
| `db1-review-close` | Close button |

Machine-readable contract at `#db1-review-overlay-contract` (`data-version="2"`).

---

## Keyboard map

| Key | Action | Condition |
|---|---|---|
| `W` | Accept | always |
| `S` | Enter reject mode | always |
| `Esc` | Exit reject mode / dismiss anchor panel | always |
| `A` / ← | Previous setup | always |
| `D` / → | Next setup | always |
| `1` `2` `3` | Woulda TP1 / TP2 / TP3 | reject mode only |
| `L` | Woulda Loss | reject mode only |
| `N` | Never Came | reject mode only |
| `F` | Bad Fib → opens anchor correction sub-panel | reject mode only |
| `Enter` | Save anchor correction & next | anchor correction open |

All handled keys call `stopImmediatePropagation` (capture phase) so TV never
receives them.

---

## Rejection reasons

| Key | Label | Color | Meaning |
|---|---|---|---|
| `1` | 1 Woulda TP1 | yellow | Setup valid, would have hit TP1 |
| `2` | 2 Woulda TP2 | yellow | Setup valid, would have hit TP2 |
| `3` | 3 Woulda TP3 | yellow | Setup valid, would have hit TP3 |
| `L` | L Woulda Loss | yellow | Setup valid, would have hit stop |
| `N` | N Never Came | yellow | Setup valid, price never triggered |
| `F` | F Bad Fib | violet (#a78bfa) | Setup invalid — Fib anchors are wrong |

`F Bad Fib` is violet because it flags setup quality, not outcome prediction.
Selecting it opens the anchor correction sub-panel (see below).

---

## Anchor correction flow

Triggered by selecting `F Bad Fib`. The panel shows two price inputs (High,
Low) and `Save & Next` / `Skip`.

On save, a correction record is pushed to `window.db1AnchorCorrections`:

```json
{
  "setupId": "3 / 12",
  "symbol": "BTCUSDT",
  "time": "2026-05-15 14:30",
  "correctHigh": 67450,
  "correctLow": 65200,
  "savedAt": "2026-06-07T..."
}
```

The TM userscript is responsible for flushing this array to disk (append to a
corrections JSONL file). The design file does not persist across reloads.

---

## TamperMonkey deployment (planned)

1. `apps/review/db1_review_panel.user.js` — extract panel HTML/CSS/JS from the
   design file into a `@userscript` wrapper.
2. Match: `https://www.tradingview.com/*`
3. Trigger: `Ctrl+Shift+R` to show/hide the panel.
4. Setup data: support both a `Load setups` file-picker (JSON) and a
   `fetch('http://localhost:PORT/pending-reviews')` for when the DB1 bot is
   running.
5. Install once; TamperMonkey auto-reloads from the local file path.
