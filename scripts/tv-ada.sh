#!/usr/bin/env bash
# tv-ada.sh -- one-command WSAD review for ADA 15m, last 3 months.
#
# Same UX as tv-go.sh but pointed at BITGET:ADAUSDT.P @ 15m timeframe with
# the 6c / 2.0x ATR detector (our long-horizon default for 15m).
#
# What this does:
#   1. Verify (or launch + wait for) debug Chrome on :9222.
#   2. Run tv_review_ada_15m.py:
#        - load binance_adausdt_15m_full_history.csv
#        - detect setups at 6c / 2.0x ATR in the last 3 months
#        - navigate Chrome to BITGET:ADAUSDT.P @ 15m
#        - inject WSAD review panel, walk through each setup
#        - verdicts append to data/discovery_bet_1/human_labels.jsonl
#          (tagged asset=ADA so we can filter the BTC vs ADA streams)
#        - on exit, write a Markdown session report to
#          artifacts/discovery_bet_1/manual_review_ada_15m/SESSION_<ts>.md
#
# Usage:
#   ./scripts/tv-ada.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

VENV_PY="$REPO_ROOT/.venv/bin/python"

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
echo "==> Refreshing ADA 15m data (Binance public REST)..."
echo "    Without this, the CSV's last bar can be days stale while TV shows"
echo "    today's bars, so the bar-range filter produces zero setups."
env PYTHONPATH="$REPO_ROOT" "$VENV_PY" "$SCRIPT_DIR/acquire_long_asset.py" \
  ADAUSDT 15m 2>&1 | tail -3 || \
  echo "    (warning: data refresh failed; continuing with whatever's on disk)"

echo
echo "==> Starting ADA 15m WSAD review (last 3 months)..."
echo "    Switch to your TradingView Chrome window. Use:"
echo "      W/Up=approve   S/Down=reject   A/Left=prev   D/Right=next   Enter=done"
echo "    Verdicts append to data/discovery_bet_1/human_labels.jsonl (tagged asset=ADA)."
echo "    Session report is written when you exit."
echo
exec env PYTHONPATH="$REPO_ROOT" PYTHONUNBUFFERED=1 "$VENV_PY" \
  "$SCRIPT_DIR/tv_review_ada_15m.py"
