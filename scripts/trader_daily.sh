#!/usr/bin/env bash
# Paper-trading daily routine (NSE). Paper only: never places orders.
# Scheduled by Hermes cron at 16:30 Asia/Kolkata, Mon-Fri (after the 16:00 data cutoff, so today's bar is final). Skips NSE equity holidays
# (lists: scripts/nse_holidays_<year>.txt next to this script; add one per year).
# Empty stdout = nothing delivered. Stdout is the Telegram message, so keep it short.
# All data lives in Postgres (POSTGRES_* in .env). Each run's message and log are also stored in the job_runs table.
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
# Holiday lists: every scripts/nse_holidays_<year>.txt, or just TRADER_HOLIDAYS_FILE when set.
HOLIDAY_FILES=("$SCRIPT_DIR"/nse_holidays_*.txt)
[ -n "${TRADER_HOLIDAYS_FILE:-}" ] && HOLIDAY_FILES=("$TRADER_HOLIDAYS_FILE")
LOG_DIR="${TRADER_LOG_DIR:-${TMPDIR:-/tmp}/trader-logs}"

today_ist=$(TZ=Asia/Kolkata date +%Y-%m-%d)
if cat "${HOLIDAY_FILES[@]}" 2>/dev/null | grep -qx "$today_ist"; then
  exit 0   # NSE holiday: silent skip
fi

cd "$REPO" || { echo "FAILED: trader repo missing ($REPO)"; exit 1; }
mkdir -p "$LOG_DIR"
log="$LOG_DIR/trader_daily_$(date -u +%Y%m%dT%H%M).log"
msg="$(mktemp "$LOG_DIR/trader_daily_msg_XXXX")"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
rc=1

{
  echo "Trader daily paper run $(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M IST')"

  year_ist="${today_ist%%-*}"
  if ! ls "$SCRIPT_DIR"/nse_holidays_"$year_ist".txt >/dev/null 2>&1 && [ -z "${TRADER_HOLIDAYS_FILE:-}" ]; then
    echo "⚠️ No scripts/nse_holidays_${year_ist}.txt: holidays are not being skipped this year"
  fi

  if timeout 1500 uv run trader daily >"$log" 2>&1; then
    rc=0
    # Keep collecting dated fundamentals (stored in Postgres). Skips itself unless the newest snapshot is 7+ days old;
    # a failure here never fails the run.
    timeout 900 uv run trader fundamentals-snapshot --if-stale-days 7 >>"$log" 2>&1 \
      || echo "⚠️ fundamentals snapshot failed (see log)"
    # Telegram-ready summary: labelled sections, built from the lines `trader daily` echoes.
    if uv run python "$SCRIPT_DIR/format_daily_message.py" "$log"; then
      echo "✅ Run OK · log: $log"
    else
      echo "⚠️ message formatter failed; raw summary below"
      grep -E '^(WARNING|account \||momentum sleeve|swing sleeve|candidate |report: |orders: |[0-9]{4}-[0-9]{2}-[0-9]{2} \|)' "$log"
      echo "✅ Run OK · log: $log"
    fi
    # Ledger chart (PNG in charts/, path echoed to the message). A failure here never fails the run.
    if chart=$(timeout 300 uv run python "$SCRIPT_DIR/paper_report_chart.py" 2>>"$log"); then
      echo "📈 Chart: $chart"
      # Deliver the image to the Telegram home channel (one attempt; a failure only adds a warning).
      if bash "$SCRIPT_DIR/send_telegram_photo.sh" "$chart" "Paper ledger $(basename "$chart" .png | sed 's/^paper_report_//') (paper only)" >>"$log" 2>&1; then
        echo "📨 Chart sent to Telegram"
      else
        echo "⚠️ chart not sent to Telegram (see log)"
      fi
    else
      echo "⚠️ chart not generated (see log)"
    fi
  else
    echo "❌ Trader daily run FAILED (exit non-zero). Last 40 log lines:"
    tail -n 40 "$log"
  fi
} >"$msg"

# Store the message and full log in the database; a failure to log never changes the run's outcome.
uv run trader db log-run --job daily --exit "$rc" --message-file "$msg" --log-file "$log" --started "$started" >>"$log" 2>&1 \
  || echo "⚠️ run not logged to the database (see $log)" >>"$msg"
cat "$msg"
rm -f "$msg"
