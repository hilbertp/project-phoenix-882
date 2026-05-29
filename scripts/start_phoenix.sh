#!/usr/bin/env bash
# Start the Phoenix interactive dashboard. One canonical entrypoint to bring
# up the review + backtest + TradingView-launcher UI in your browser.
#
# Usage:
#   ./scripts/start_phoenix.sh                  # default port 8800, opens browser
#   ./scripts/start_phoenix.sh --port 8900      # different port
#   ./scripts/start_phoenix.sh --no-open        # don't auto-open the browser
#
# This is what `start_phoenix.sh` does end-to-end:
#   1. Make sure we're at the repo root (so relative paths resolve correctly).
#   2. Activate the project venv (.venv).
#   3. Launch scripts/dashboard_server.py with PYTHONPATH=.
#
# The dashboard surfaces:
#   - Multi-asset BTC/ETH/ADA/SOL/BNB/XRP/TRX/HYPE backtests w/ per-regime KPIs.
#   - Click any setup -> candlestick + fib level overlay + execution events.
#   - Per-setup feedback ("exaaactly to the ms" / "wtf" / "adjust").
#   - "Manual review in TradingView" button (top-right) -> launches Chrome with
#     the BTC chart, places live Fib retracement objects for the most recent
#     setups, and you give feedback in the dashboard while reviewing on TV.

set -euo pipefail

# repo root = parent of this script's dir
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$REPO_ROOT"

if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
  echo "error: $REPO_ROOT/.venv not found. Run the Quickstart in README.md first."
  exit 1
fi

OPEN_FLAG="--open"
PORT_FLAG=""
for arg in "$@"; do
  case "$arg" in
    --no-open) OPEN_FLAG="" ;;
    *) PORT_FLAG="$PORT_FLAG $arg" ;;
  esac
done

echo "starting Phoenix dashboard..."
exec env PYTHONPATH="$REPO_ROOT" "$REPO_ROOT/.venv/bin/python" \
  "$REPO_ROOT/scripts/dashboard_server.py" $OPEN_FLAG $PORT_FLAG
