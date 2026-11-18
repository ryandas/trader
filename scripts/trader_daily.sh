#!/usr/bin/env bash
# Paper-trading daily routine (NSE). Paper only: never places orders.
# Scheduled by Hermes cron at 16:30 Asia/Kolkata, Mon-Fri (after the 16:00 data cutoff, so today's bar is final). Skips NSE equity holidays
# (list: scripts/nse_holidays_2026.txt next to this script; 2026 only).
# Empty stdout = nothing delivered. Stdout is the Telegram message, so keep it short.
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
HOLIDAYS="${TRADER_HOLIDAYS_FILE:-$SCRIPT_DIR/nse_holidays_2026.txt}"
LOG_DIR="${TRADER_LOG_DIR:-${TMPDIR:-/tmp}/trader-logs}"

today_ist=$(TZ=Asia/Kolkata date +%Y-%m-%d)
if grep -qx "$today_ist" "$HOLIDAYS" 2>/dev/null; then
  exit 0   # NSE holiday: silent skip
fi

cd "$REPO" || { echo "FAILED: trader repo missing ($REPO)"; exit 1; }
mkdir -p "$LOG_DIR"
log="$LOG_DIR/trader_daily_$(date -u +%Y%m%dT%H%M).log"
echo "Trader daily paper run $(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M IST')"

if timeout 1500 uv run trader daily >"$log" 2>&1; then
  # Keep only the summary lines `trader daily` echoes (date/regime, sleeves, candidates, report path, warnings).
  grep -E '^(swing sleeve|momentum sleeve|candidate |report:|WARNING)|^[0-9]{4}-[0-9]{2}-[0-9]{2} \| regime' "$log"
  echo "OK (exit 0). Log: $log"
else
  echo "FAILED: trader daily exited non-zero. Last 40 log lines:"
  tail -n 40 "$log"
fi
