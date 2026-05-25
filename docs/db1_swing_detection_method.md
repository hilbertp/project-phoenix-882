# DB1 Phoenix Swing Detection — Method (for human review & manual reproduction)

This describes exactly how the auto-detected Fib setups (`auto1`, `auto2`, …) are
found, so a reviewer can verify each one by eye and reproduce it manually if needed.

Market: `BITGET:BTCUSDT.P`, **1H** candles. Timezone of timestamps below is the
chart timezone (Asia/Nicosia in the current review); the same wall-clock the chart shows.

## What a swing is

A **swing** is one clean directional impulse leg between two **extreme local fractals**:

- **Bullish (up) leg:** from a swing **low** (parent) up to the swing **high** (terminal).
- **Bearish (down) leg:** from a swing **high** (parent) down to the swing **low** (terminal).

The parent is the leg's origin extreme; the terminal is the opposite extreme reached.

## Two tunable parameters

- **`min_bars`** — minimum number of 1H candles between parent and terminal (leg span).
- **`atr_multiple`** — minimum leg depth in ATR, *and* the retracement size that ends a leg.

Volatility is measured with the **hourly ATR(14)** (Wilder/RMA — the same as
TradingView's built-in `ATR(14)` on the 1H chart).

## Detection rule (ATR zigzag)

1. Compute hourly **ATR(14)**.
2. Track the running extreme in the current direction (highest high while going up,
   lowest low while going down).
3. A leg **ends** when price retraces from that running extreme by **≥ `atr_multiple` × ATR**.
   The running extreme becomes the leg's **terminal**; the previous opposite extreme is the **parent**.
4. Keep the leg only if **both** gates pass:
   - **Span:** `terminal_index − parent_index ≥ min_bars` candles.
   - **Depth:** `|terminal_price − parent_price| ÷ ATR(14)[at terminal] ≥ atr_multiple`.
5. **Clean check (no stragglers):** between parent and terminal, no candle high exceeds the
   terminal high and no candle low breaks the parent low. (The zigzag tolerance enforces this;
   verify by eye.)

Legs alternate (low→high→low…). A new leg's parent is the previous leg's terminal, unless a
sub-threshold (too shallow or too short) move sits between them — those are skipped.

## Fib mapping

For the drawn Fib retracement: **0.0 at the terminal** (the extreme just made),
**1.0 at the parent** (origin), **1.05 just beyond the parent** (invalidation / stop level).

## Label encoding (trackability)

Each setup is labelled:

```
autoN   DD-MM to DD-MM   {span}c   {depth}a
```

- **`DD-MM to DD-MM`** — parent date → terminal date.
- **`{span}c`** — candle count between the two anchors.
- **`{depth}a`** — depth in ATR = `|price range| ÷ ATR(14) at the terminal`.

Example: `auto4 11-05 to 13-05 45c 7.6a` = a leg from 11 May to 13 May, 45 candles, 7.6 ATR deep.

## Manual reproduction steps

1. Add **ATR(14)** to the 1H chart.
2. From a swing extreme, follow the impulse to the opposite extreme.
3. Confirm the leg is valid: price has reversed **≥ `atr_multiple` × ATR** from the extreme,
   the span is **≥ `min_bars`** candles, and **nothing between the anchors breaches either anchor**.
4. Read off the candle span and the ATR-depth; this gives you the `{span}c {depth}a` label.
5. Draw the Fib from parent (1.0) to terminal (0.0); the entry/stop/target plan hangs off these.

## Calibration note (honest state)

Across the hand-validated set `auto1`–`auto8`, legs ran roughly **25–75 candles** and
**~6–16 ATR** deep. A *single fixed* `atr_multiple` does **not** yet reproduce every
hand-validated swing — some deep, clean legs need a higher multiple to avoid being split at an
intermediate bounce, while shallow moves are skipped. The current selection takes the **cleanest
significant leg at each step**; the exact `(min_bars, atr_multiple)` that reproduces all
validated swings is still being calibrated. Until it is fixed, use the per-setup labels
(`{span}c {depth}a`) to verify each setup independently against this rule.
