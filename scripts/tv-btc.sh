#!/usr/bin/env bash
# tv-btc.sh -- one-command WSAD review for BTC 1H setups, one calendar month.
#
# Usage:
#   ./scripts/tv-btc.sh                # defaults to current month
#   ./scripts/tv-btc.sh 2026-05        # May 2026
#   ./scripts/tv-btc.sh 2026-06        # June 2026
#
# Detector: 6c minimum bars, 2.0x ATR minimum depth.
# Symbol:   BINANCE:BTCUSDT @ 1H.
#
# What this does:
#   1. Verify (or launch + wait for) debug Chrome on :9222.
#   2. Refresh binance_btcusdt_1h_full_history.csv (so it covers the month).
#   3. Run tv_review_btc_month.py --month YYYY-MM:
#        - detect setups at 6c / 2.0x ATR within the month
#        - navigate Chrome to BINANCE:BTCUSDT @ 1H
#        - inject WSAD review panel, walk through each setup
#        - verdicts append to data/discovery_bet_1/human_labels.jsonl
#          (tagged asset=BTC, month=YYYY-MM)
#        - on exit, write a Markdown session report to
#          artifacts/discovery_bet_1/manual_review_btc_1h_month/
#          SESSION_BTC_<month>_<ts>.md
#        - and render an HTML report overlay on the TV chart.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

VENV_PY="$REPO_ROOT/.venv/bin/python"

# Default month = current calendar month if not provided.
MONTH="${1:-$(date -u +%Y-%m)}"

# Sanity-check the format.
if ! [[ "$MONTH" =~ ^[0-9]{4}-[0-9]{2}$ ]]; then
  echo "ERROR: month must be YYYY-MM (got: $MONTH)" >&2
  echo "Usage: $0 [YYYY-MM]" >&2
  exit 1
fi

# Kill any stale review process from a previous run BEFORE we start. Two
# review processes attached to the same Chrome fight over the panel (the
# setup index jumps, drawings flicker). Matching the exact script name is
# safe -- it only ever targets this reviewer, never the user's other work.
STALE=$(pgrep -f "tv_review_btc_month.py" || true)
if [ -n "$STALE" ]; then
  echo "==> Killing stale review process(es): $STALE"
  pkill -f "tv_review_btc_month.py" || true
  sleep 1
fi

chrome_alive() {
  curl -s --max-time 1 http://127.0.0.1:9222/json/version >/dev/null 2>&1
}
if chrome_alive; then
  echo "==> Chrome already up on :9222, reusing it."
else
  echo "==> Chrome not running. Launching debug Chrome..."
  env PYTHONPATH="$REPO_ROOT" "$VENV_PY" "$SCRIPT_DIR/place_fibs_tradingview.py" login >/dev/null
  for i in $(seq 1 20); do
    sleep 1
    if chrome_alive; then
      echo "==> Chrome up on :9222 after ${i}s."
      break
    fi
  done
  if ! chrome_alive; then
    echo "ERROR: Chrome failed to bind :9222 within 20s." >&2
    exit 1
  fi
  echo "==> If this is the first run, log into TradingView in the Chrome window now."
  echo "    Sleeping 10s..."
  sleep 10
fi

echo
# Only refresh data when the CSV does NOT already cover the requested month.
# A past month's bars never change, so re-fetching 8+ years from Binance every
# run is both slow (~80s) and fragile (a mid-fetch network reset used to leave
# a short file). If the CSV's last bar is already past the end of MONTH, the
# month is fully covered -- skip the network entirely. This is what makes a
# past-month replay FAST and REPRODUCIBLE (no network dependency at all).
CSV="$REPO_ROOT/data/discovery_bet_1/binance_btcusdt_1h_full_history.csv"
# First day of the month AFTER the requested one (lexical YYYY-MM-DD compare).
NEXT_MONTH=$(env TZ=UTC "$VENV_PY" - "$MONTH" <<'PY'
import sys, datetime
y, m = map(int, sys.argv[1].split("-"))
nm = datetime.date(y + (m // 12), (m % 12) + 1, 1)
print(nm.isoformat())
PY
)
NEED_REFRESH=1
if [ -f "$CSV" ]; then
  LAST_BAR=$(tail -1 "$CSV" | cut -d, -f1 | cut -dT -f1)   # YYYY-MM-DD
  if [[ -n "$LAST_BAR" && "$LAST_BAR" > "$NEXT_MONTH" ]] || \
     [[ "$LAST_BAR" == "$NEXT_MONTH" ]]; then
    NEED_REFRESH=0
  fi
fi
if [ "${PHOENIX_FORCE_REFRESH:-0}" = "1" ]; then NEED_REFRESH=1; fi

if [ "$NEED_REFRESH" = "0" ]; then
  echo "==> CSV already covers $MONTH (last bar $LAST_BAR) -- skipping refresh."
  echo "    Past months are immutable; this run is offline + reproducible."
  echo "    (set PHOENIX_FORCE_REFRESH=1 to force a re-fetch.)"
else
  echo "==> Refreshing BTC 1H data (Binance public REST) -- $MONTH not yet covered..."
  echo "    The acquire step retries network blips and refuses to overwrite a"
  echo "    longer history with a shorter one, so it can't truncate the file."
  env PYTHONPATH="$REPO_ROOT" "$VENV_PY" "$SCRIPT_DIR/acquire_long_asset.py" \
    BTCUSDT 1h 2>&1 | tail -4 || \
    echo "    (refresh failed; the existing CSV was kept -- continuing with it)"
fi

echo
echo "==> Starting BTC 1H WSAD review for month $MONTH (6c / 2.0x ATR)..."
echo "    Switch to your TradingView Chrome window. Use:"
echo "      W/Up=approve   S/Down=reject path   A/Left=prev   D/Right=next   Enter=done"
echo "    Verdicts append to data/discovery_bet_1/human_labels.jsonl (tagged asset=BTC)."
echo "    Session report (markdown + chart overlay) is written when you exit."
echo
exec env PYTHONPATH="$REPO_ROOT" PYTHONUNBUFFERED=1 "$VENV_PY" \
  "$SCRIPT_DIR/tv_review_btc_month.py" --month "$MONTH"
