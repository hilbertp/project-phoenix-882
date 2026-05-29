#!/usr/bin/env bash
# Place the N most recent clean setups (from RECENT_3M_FROM forward) on the
# BITGET:BTCUSDT.P 1H TradingView chart as native Fib Retracement objects.
# Requires that ./scripts/tv-login.sh was run first AND that Chrome is still
# open with the debug port bound (the port check returns immediately).
#
# Usage:
#   ./scripts/tv-place.sh           # default 12 setups
#   ./scripts/tv-place.sh 24        # 24 setups
#   ./scripts/tv-place.sh dry       # print the leg list, no browser action
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"
ARG="${1:-12}"
exec env PYTHONPATH="$REPO_ROOT" "$REPO_ROOT/.venv/bin/python" \
  scripts/place_fibs_tradingview.py "$ARG"
