#!/usr/bin/env bash
# Preflight for a host that will run the Hermes jobs. Read-only; places no orders. Exit 0 = ready.
# Usage: scripts/handoff_check.sh [--quick]   (--quick skips the test suite)
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 1
fail=0
ok()   { echo "ok    $*"; }
bad()  { echo "FAIL  $*"; fail=1; }
warn() { echo "warn  $*"; }

command -v uv >/dev/null && ok "uv on PATH" || bad "uv not found (install from https://docs.astral.sh/uv/)"
command -v timeout >/dev/null && ok "timeout" || bad "coreutils timeout missing"
command -v claude >/dev/null && ok "claude CLI (needed only for research_daily.sh)" || warn "claude CLI missing: research_daily.sh cannot run"
command -v sqlite3 >/dev/null && ok "sqlite3 (needed only for handoff_pack.sh)" || warn "sqlite3 missing"
[ -f config.yaml ] && grep -qE '^mode:\s*paper' config.yaml && ok "config.yaml mode: paper" || bad "config.yaml missing or mode is not paper"
[ -f data/paper.db ] && ok "data/paper.db present" || bad "data/paper.db missing: restore the state pack (do NOT run paper-momentum --reset)"
[ -f data/research.db ] && ok "data/research.db present" || warn "data/research.db missing: trial count would restart (deflated-Sharpe bar resets)"
[ -f data/instruments.csv ] && ok "data/instruments.csv present" || bad "data/instruments.csv missing: uv run trader init"
msg="$(scripts/trial_guard.sh)" && ok "$msg" || bad "$msg"
ls data/candles/*.parquet >/dev/null 2>&1 && ok "candles present" || warn "no candles: first daily run will backfill 10y (slow)"
ls scripts/nse_holidays_"$(TZ=Asia/Kolkata date +%Y)".txt >/dev/null 2>&1 \
  && ok "holiday list for $(TZ=Asia/Kolkata date +%Y)" || bad "no scripts/nse_holidays_$(TZ=Asia/Kolkata date +%Y).txt"
[ -z "$(git status --porcelain)" ] && ok "git tree clean (research_daily.sh requires it)" || warn "git tree dirty: research_daily.sh will refuse to run"
[ -f .env ] && warn ".env present (only used by --source dhan; yfinance run does not need it)" || ok "no .env needed for the default yfinance source"
echo "tz: $(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M IST') (cron must be set to Asia/Kolkata)"

uv sync --quiet 2>&1 | tail -n 3
status="$(uv run trader research-status 2>&1)" && { ok "trader CLI runs"; echo "$status" | head -n 3; } || { bad "trader CLI failed"; echo "$status" | tail -n 5; }
if [ "${1:-}" != "--quick" ]; then
  uv run pytest -q 2>&1 | tail -n 3
  [ "${PIPESTATUS[0]}" -eq 0 ] && ok "tests pass" || bad "tests failing"
fi
[ "$fail" -eq 0 ] && echo "READY" || echo "NOT READY"
exit "$fail"
