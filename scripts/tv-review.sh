#!/usr/bin/env bash
# Start a WSAD-driven review session on TradingView.
#
# Prerequisites:
#   1. ./scripts/tv-login.sh  has been run and Chrome is still alive on :9222.
#   2. ./scripts/tv-place.sh  has placed the setups on the chart you want to
#      review (or run them in any order -- the review tool finds whatever's
#      drawn on the chart).
#
# What this does:
#   - Connects to the running Chrome via the debug port.
#   - Injects a small floating panel onto the TradingView chart with:
#       W / Up        approve (write VERDICT_ACCEPT to human_labels.jsonl)
#       S / Down      reject  (write VERDICT_REJECT)
#       A / Left      back (re-focus the previous setup)
#       D / Right     next (re-focus the next setup)
#       Enter         done (end the review session)
#       Save edit     after dragging the Fib anchors to the right pivots
#       + Report      add a missed setup (draw a Fib first, then click)
#   - Steps through setups one focused object at a time so each one is the
#     center of attention.
#   - On exit, every verdict is durable in data/discovery_bet_1/human_labels.jsonl.
#
# Usage:
#   ./scripts/tv-review.sh           # review the recent-3M setups (default)
#   ./scripts/tv-review.sh manual    # review the 8 hand-picked reference setups
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"
exec env PYTHONPATH="$REPO_ROOT" "$REPO_ROOT/.venv/bin/python" \
  scripts/review_fibs_tradingview.py "$@"
