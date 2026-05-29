#!/usr/bin/env bash
# Spawn debug Chrome with the project-local profile + the TradingView chart.
# Bypasses selenium (which clobbers --remote-debugging-port=9222 with its own).
# Log into TradingView once in the window that opens; the session persists
# in .chrome-tv-manual/. Leave Chrome running, then run tv-place.sh.
#
# Usage:  ./scripts/tv-login.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"
exec env PYTHONPATH="$REPO_ROOT" "$REPO_ROOT/.venv/bin/python" \
  scripts/place_fibs_tradingview.py login
