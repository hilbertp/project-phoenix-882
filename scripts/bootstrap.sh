#!/usr/bin/env bash
# bootstrap.sh -- one-time machine setup for the BTC review/backtest tooling.
# Idempotent: safe to re-run any time; it only does what's missing.
#
# Works on macOS and WSL2 Ubuntu (bash). What it does:
#   1. Verify python3 >= 3.11; create .venv if missing.
#   2. pip install -r requirements.txt (selenium, matplotlib).
#   3. Verify a Chrome binary exists (apt instructions printed on Linux).
#   4. Acquire market data NOT in the repo (data/ is gitignored except
#      human_labels.jsonl):
#        - BTC 1H full history  (~77k rows,  ~1 min)
#        - BTC 5m full history  (~925k rows, ~6-10 min, one-time)
#      Already-present files are kept (the acquirer never truncates).
#
# After this, the daily driver is just:
#   ./scripts/tv-btc.sh 2026-05 --min-bars 6 --mult 4.0

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "==> [1/4] Python + venv"
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. WSL: sudo apt install python3 python3-venv" >&2
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "    creating .venv..."
  python3 -m venv .venv
fi
echo "    $(.venv/bin/python --version)"

echo "==> [2/4] Python packages"
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo "    selenium + matplotlib installed."

echo "==> [3/4] Chrome"
CHROME_FOUND=""
for p in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
         /usr/bin/google-chrome-stable /usr/bin/google-chrome \
         /usr/bin/chromium-browser /usr/bin/chromium /snap/bin/chromium; do
  if [ -x "$p" ]; then CHROME_FOUND="$p"; break; fi
done
if [ -n "$CHROME_FOUND" ]; then
  echo "    found: $CHROME_FOUND"
else
  echo "    NOT FOUND. On WSL2 Ubuntu install Chrome INSIDE the distro:"
  echo "      wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"
  echo "      sudo apt install ./google-chrome-stable_current_amd64.deb"
  echo "    (WSLg shows its window on the Windows desktop automatically.)"
  echo "    Re-run this script afterwards."
  exit 1
fi

echo "==> [4/4] Market data (skips anything already on disk)"
DATA="$REPO_ROOT/data/discovery_bet_1"
if [ -f "$DATA/binance_btcusdt_1h_full_history.csv" ]; then
  echo "    1H history present ($(wc -l < "$DATA/binance_btcusdt_1h_full_history.csv" | tr -d ' ') rows) -- kept."
else
  echo "    acquiring BTC 1H full history (~1 min)..."
  env PYTHONPATH="$REPO_ROOT" .venv/bin/python "$SCRIPT_DIR/acquire_long_asset.py" BTCUSDT 1h 2>&1 | tail -2
fi
if [ -f "$DATA/binance_btcusdt_5m_full_history.csv" ]; then
  echo "    5m history present ($(wc -l < "$DATA/binance_btcusdt_5m_full_history.csv" | tr -d ' ') rows) -- kept."
else
  echo "    acquiring BTC 5m full history (~6-10 min, one-time; needed for"
  echo "    honest intra-candle outcome resolution)..."
  env PYTHONPATH="$REPO_ROOT" .venv/bin/python "$SCRIPT_DIR/acquire_long_asset.py" BTCUSDT 5m 2>&1 | tail -2
fi

echo
echo "==> Bootstrap complete. Next steps:"
echo "    1. ONE-TIME TradingView login (opens Chrome; use the Email option):"
echo "         PYTHONPATH=. .venv/bin/python scripts/place_fibs_tradingview.py login"
echo "    2. Run a review (regime-tagged cards land in artifacts/...):"
echo "         ./scripts/tv-btc.sh 2026-05 --min-bars 6 --mult 4.0"
