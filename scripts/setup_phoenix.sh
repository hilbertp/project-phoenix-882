#!/usr/bin/env bash
# One-shot Phoenix setup. Reproducible on macOS AND inside WSL2 Ubuntu.
#
# What it does, in order:
#   1. Verifies Python 3.12+ is on PATH.
#   2. Creates the .venv if missing.
#   3. Installs runtime + dev pip deps.
#   4. Verifies Chrome is installed (or tells you how to install it).
#   5. Acquires BTC 1H 12-month data so the dashboard has something to render.
#   6. Prints the next command to run (./scripts/start_phoenix.sh).
#
# Run from anywhere; the script always operates from the repo root.
# Re-run anytime: it's idempotent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Phoenix setup at $REPO_ROOT"
echo "==> OS: $(uname -s) / arch: $(uname -m)"
echo

# 1. Python check
if command -v python3.12 >/dev/null 2>&1; then
  PY=python3.12
elif command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,12) else 1)'; then
  PY=python3
else
  echo "ERROR: Python 3.12+ not found. Install it:"
  echo "  macOS:  brew install python@3.12"
  echo "  WSL/Ubuntu: sudo apt install python3.12 python3.12-venv"
  exit 1
fi
echo "==> Python: $($PY --version) at $($PY -c 'import sys; print(sys.executable)')"

# 2. venv
if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
  echo "==> Creating .venv ..."
  $PY -m venv .venv
fi
VENV_PY="$REPO_ROOT/.venv/bin/python"

# 3. deps. tvDatafeed isn't on PyPI any more; install from upstream git.
echo "==> Installing/upgrading runtime + dev deps ..."
"$VENV_PY" -m pip install --upgrade --quiet pip
"$VENV_PY" -m pip install --upgrade --quiet \
  pandas numpy matplotlib selenium pytest ruff
"$VENV_PY" -m pip install --upgrade --quiet \
  "git+https://github.com/rongardF/tvdatafeed.git"

# 4. Chrome check
CHROME_FOUND=""
for p in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/usr/bin/google-chrome-stable" \
  "/usr/bin/google-chrome" \
  "/usr/bin/chromium-browser" \
  "/usr/bin/chromium" \
  "/snap/bin/chromium" \
  ; do
  if [[ -x "$p" ]]; then CHROME_FOUND="$p"; break; fi
done
if [[ -n "$CHROME_FOUND" ]]; then
  echo "==> Chrome: $CHROME_FOUND"
else
  echo "==> NOTE: Google Chrome not installed yet."
  echo "    Required only for the 'Manual review in TradingView' dashboard button."
  echo "    Install:"
  echo "      macOS:  brew install --cask google-chrome"
  echo "      WSL/Ubuntu:  wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && sudo apt install -y ./google-chrome-stable_current_amd64.deb"
  echo "    Then re-run this script. (The dashboard backtest views work without Chrome.)"
fi

# 5. BTC 1H 12-month data (so the dashboard isn't empty)
BTC_CSV="$REPO_ROOT/data/discovery_bet_1/bitget_btcusdt_p_1h_last_12_months.csv"
if [[ -f "$BTC_CSV" ]]; then
  echo "==> BTC 1H data present ($BTC_CSV)"
else
  echo "==> Fetching BTC 1H 12-month data (one-time, ~30s) ..."
  PYTHONPATH="$REPO_ROOT" "$VENV_PY" scripts/acquire_db1_12mo_data.py
fi

echo
echo "==> Done. Next step:"
echo "    ./scripts/start_phoenix.sh"
echo
echo "    That launches the dashboard at http://127.0.0.1:8800 and opens your browser."
echo "    Use the 'Manual review in TradingView' button (top-right) to draw the latest"
echo "    setups onto a live TV chart. WASD/arrow keys navigate the setup table."
