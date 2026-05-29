#!/usr/bin/env bash
# tv-go.sh -- one-command TV review journey.
#
# What it does, end-to-end, in one shell:
#   1. Verify (or launch + wait for) debug Chrome with the .chrome-tv-manual
#      profile bound to port 9222. If Chrome wasn't running, you'll need to
#      log into TradingView in the window that opens (one-time per profile).
#   2. Inject the floating WSAD review panel and walk through every setup
#      one at a time, auto-panning the chart to each one. Verdicts append
#      to data/discovery_bet_1/human_labels.jsonl.
#
# Note: a separate up-front "place 12 setups" step was removed -- the review
# panel wipes the chart anyway and places ONE setup at a time as you advance.
# Use ./scripts/tv-place.sh independently if you just want to visually preview
# N setups without committing to a full review.
#
# Usage:
#   ./scripts/tv-go.sh              # walk through the recent-3M setups (~35-40)
#   ./scripts/tv-go.sh manual       # walk through the 8 reference setups
#
# Keys (while the panel is active in TradingView):
#   W / Up      approve (✓ exaaactly to the ms)
#   S / Down    reject  (✗ wtf)
#   A / Left    previous setup
#   D / Right   next setup
#   Enter       end session

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

ARG="${1:-12}"
VENV_PY="$REPO_ROOT/.venv/bin/python"

# 1. Chrome check / launch
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
    echo "ERROR: Chrome failed to bind :9222 within 20s. Run ./scripts/tv-login.sh manually to diagnose." >&2
    exit 1
  fi
  echo "==> If this is your first run, log into TradingView in the Chrome window now."
  echo "    Sleeping 12s to give you time + let TV load bars..."
  sleep 12
fi

# 2. Review session (no separate placement step -- the review tool clears the
#    chart and places ONE fib at a time as you advance with W/S/A/D anyway).
echo
echo "==> Starting WSAD review panel..."
echo "    Switch to your TradingView Chrome window. Use:"
echo "      W/Up=approve   S/Down=reject   A/Left=prev   D/Right=next   Enter=done"
echo "    Verdicts append to data/discovery_bet_1/human_labels.jsonl."
echo "    NOTE: the Object Tree shows ONE fib at a time (the current setup),"
echo "          hidden behind the panel -- that is by design, not a bug."
echo
exec env PYTHONPATH="$REPO_ROOT" PYTHONUNBUFFERED=1 "$VENV_PY" \
  "$SCRIPT_DIR/review_fibs_tradingview.py" "$ARG"
