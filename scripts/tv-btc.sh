#!/usr/bin/env bash
# tv-btc.sh -- SUPERVISED one-command WSAD review for BTC 1H setups.
#
# Usage:
#   ./scripts/tv-btc.sh 2026-05                              # calendar month
#   ./scripts/tv-btc.sh 2026-04 --min-bars 24 --mult 4.0     # month + detector gates
#   ./scripts/tv-btc.sh last92d --exit-plan rest50           # trailing window
#   ./scripts/tv-btc.sh                                      # current month
#
# This wrapper is a SUPERVISOR, not a launcher. It guarantees one of two
# outcomes: a working review panel, or a clear error after 3 remediation
# attempts. The remediation ladder (per attempt):
#   attempt 1: verify Chrome by a REAL selenium attach probe (curl lies --
#              zombie Chrome answers HTTP but refuses sessions). Stale
#              singleton locks removed. Launch if needed.
#   attempt 2: + kill Chrome, clear the profile's Cache/Code Cache
#              (poisoned cache broke TV's lazy tool modules twice).
#   attempt 3: same as 2 (last try).
# Mid-session: if the review exits with code 2 (browser died under the
# user), the supervisor restarts Chrome and RESUMES the session -- verdicts
# persist in human_labels.jsonl and the review reopens at the first
# unreviewed setup. User-finished sessions (Enter) exit 0 and stop the loop.
#
# The review itself (tv_review_btc_month.py) carries its own in-session
# self-healing: Alt+F pre-warm for TV's lazy fib module, history re-paging
# on eviction, full page reload + re-init ladder, ad-blocker-nag watchdog,
# symbol keylock, instant keypress acknowledgment.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Mirror ALL output to the troubleshooting log the runbook references, no
# matter how this script was invoked.
exec > >(tee /tmp/tv-btc.log) 2>&1

VENV_PY="$REPO_ROOT/.venv/bin/python"
PROFILE_DIR="$HOME/.phoenix-chrome-tv"

# ---- window argument: YYYY-MM or lastNd ------------------------------------
WINDOW="${1:-$(date -u +%Y-%m)}"
shift $(( $# > 0 ? 1 : 0 ))
EXTRA_ARGS=("$@")
if [[ "$WINDOW" =~ ^[0-9]{4}-[0-9]{2}$ ]]; then
  WINDOW_ARGS=(--month "$WINDOW")
elif [[ "$WINDOW" =~ ^last([0-9]+)d$ ]]; then
  WINDOW_ARGS=(--last-days "${BASH_REMATCH[1]}")
else
  echo "ERROR: window must be YYYY-MM or lastNd (got: $WINDOW)" >&2
  exit 1
fi

# ---- helpers ----------------------------------------------------------------
kill_stale_reviews() {
  pgrep -f "tv_review_btc_month.py" >/dev/null 2>&1 && {
    echo "==> killing stale review process(es)"
    pkill -f "tv_review_btc_month.py" || true
    sleep 1
  } || true
}

chrome_attach_ok() {
  # The ONLY trustworthy health check: a real selenium attach + a trivial
  # script. Zombie Chrome answers /json/version but refuses sessions.
  env PYTHONPATH="$REPO_ROOT" "$VENV_PY" - <<'PY' >/dev/null 2>&1
import sys
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
o = Options()
o.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
try:
    d = webdriver.Chrome(options=o)
    d.execute_script("return 1")
except Exception:
    sys.exit(1)
sys.exit(0)
PY
}

launch_chrome() {
  local clear_cache="$1"
  pkill -f "user-data-dir=$PROFILE_DIR" 2>/dev/null || true
  sleep 2
  rm -f "$PROFILE_DIR/SingletonLock" "$PROFILE_DIR/SingletonSocket" \
        "$PROFILE_DIR/SingletonCookie" 2>/dev/null || true
  if [ "$clear_cache" = "yes" ]; then
    echo "==> clearing profile caches (login/cookies kept)"
    rm -rf "$PROFILE_DIR/Default/Cache" "$PROFILE_DIR/Default/Code Cache" \
           "$PROFILE_DIR/GrShaderCache" "$PROFILE_DIR/ShaderCache" 2>/dev/null || true
  fi
  echo "==> launching debug Chrome..."
  env PYTHONPATH="$REPO_ROOT" "$VENV_PY" "$SCRIPT_DIR/place_fibs_tradingview.py" login >/dev/null 2>&1
  for _ in $(seq 1 25); do
    sleep 1
    if curl -s --max-time 1 http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
      sleep 3   # let the chart tab boot before anyone attaches
      return 0
    fi
  done
  return 1
}

ensure_chrome() {
  local attempt="$1"
  if chrome_attach_ok; then
    echo "==> Chrome healthy (attach probe passed)."
    return 0
  fi
  echo "==> Chrome unhealthy or absent."
  local clear="no"
  [ "$attempt" -ge 2 ] && clear="yes"
  launch_chrome "$clear" || return 1
  chrome_attach_ok
}

# ---- data: 1H covers the window? 5m present? --------------------------------
CSV="$REPO_ROOT/data/discovery_bet_1/binance_btcusdt_1h_full_history.csv"
NEED_REFRESH=1
if [ -f "$CSV" ]; then
  LAST_BAR=$(tail -1 "$CSV" | cut -d, -f1 | cut -dT -f1)
  if [[ "$WINDOW" =~ ^[0-9]{4}-[0-9]{2}$ ]]; then
    NEXT_MONTH=$(env TZ=UTC "$VENV_PY" - "$WINDOW" <<'PY'
import sys, datetime
y, m = map(int, sys.argv[1].split("-"))
print(datetime.date(y + (m // 12), (m % 12) + 1, 1).isoformat())
PY
)
    if [[ -n "$LAST_BAR" && ( "$LAST_BAR" > "$NEXT_MONTH" || "$LAST_BAR" == "$NEXT_MONTH" ) ]]; then
      NEED_REFRESH=0
    fi
  else
    # trailing window: refresh only when the CSV is more than 2 days stale
    AGE_DAYS=$(env TZ=UTC "$VENV_PY" - "$LAST_BAR" <<'PY'
import sys, datetime
print((datetime.date.today() - datetime.date.fromisoformat(sys.argv[1])).days)
PY
)
    [ "$AGE_DAYS" -le 2 ] && NEED_REFRESH=0
  fi
fi
[ "${PHOENIX_FORCE_REFRESH:-0}" = "1" ] && NEED_REFRESH=1
if [ "$NEED_REFRESH" = "0" ]; then
  echo "==> 1H CSV covers $WINDOW (last bar $LAST_BAR) -- offline, reproducible."
else
  echo "==> refreshing BTC 1H data (window $WINDOW not covered)..."
  env PYTHONPATH="$REPO_ROOT" "$VENV_PY" "$SCRIPT_DIR/acquire_long_asset.py" \
    BTCUSDT 1h 2>&1 | tail -2 || echo "    (refresh failed; existing CSV kept)"
fi
CSV_5M="$REPO_ROOT/data/discovery_bet_1/binance_btcusdt_5m_full_history.csv"
if [ ! -f "$CSV_5M" ]; then
  echo "==> acquiring 5m history once (~6-10 min; intra-candle outcome resolution)..."
  env PYTHONPATH="$REPO_ROOT" "$VENV_PY" "$SCRIPT_DIR/acquire_long_asset.py" \
    BTCUSDT 5m 2>&1 | tail -2 || echo "    (5m acquire failed; 1H tie-breaks)"
fi

# ---- supervised run loop -----------------------------------------------------
kill_stale_reviews
for ATTEMPT in 1 2 3; do
  echo
  echo "==> attempt $ATTEMPT/3"
  if ! ensure_chrome "$ATTEMPT"; then
    echo "==> Chrome could not be made healthy on attempt $ATTEMPT."
    continue
  fi
  echo "==> starting review: window=$WINDOW ${EXTRA_ARGS[*]-}"
  echo "    keys: W=ok  S=wrong(R=setup/F=outcome->1/2/3/L/M)  A/D=nav  Enter=done"
  set +e
  env PYTHONPATH="$REPO_ROOT" PYTHONUNBUFFERED=1 "$VENV_PY" \
    "$SCRIPT_DIR/tv_review_btc_month.py" "${WINDOW_ARGS[@]}" \
    ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
  RC=$?
  set -e
  if [ "$RC" -eq 0 ]; then
    echo "==> session finished normally."
    exit 0
  elif [ "$RC" -eq 2 ]; then
    echo "==> browser died mid-session; restarting Chrome and RESUMING"
    echo "    (your verdicts are saved; the review reopens at the first"
    echo "    unreviewed setup)."
    continue
  else
    echo "==> review exited rc=$RC; see output above."
    exit "$RC"
  fi
done
echo "==> giving up after 3 attempts. Diagnostics:"
echo "    - profile: $PROFILE_DIR (is TradingView still logged in?)"
echo "    - try: rm -rf $PROFILE_DIR/Default/Cache && $0 $WINDOW"
exit 1
