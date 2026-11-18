#!/usr/bin/env bash
# Scheduled idea testing: runs the /research loop for ONE idea with Claude Code (print mode).
# Hermes cron: Mon-Fri 18:30 Asia/Kolkata (after the 16:30 paper run and its data refresh). Skips NSE holidays.
# Paper only. Promotion, retirement, pushes and order tools are blocked by the tool allowlist.
# Stdout is the Telegram message. Commits locally when something changed; never pushes.
# Set DRY_RUN=1 to print the command and prompt size without running Claude (no trial counted).
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOLIDAYS="${TRADER_HOLIDAYS_FILE:-$SCRIPT_DIR/nse_holidays_2026.txt}"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${TRADER_LOG_DIR:-${TMPDIR:-/tmp}/trader-logs}"
GUARDED=(src/trader/research/evaluate.py src/trader/research/dsr.py)

today_ist=$(TZ=Asia/Kolkata date +%Y-%m-%d)
if grep -qx "$today_ist" "$HOLIDAYS" 2>/dev/null; then
  exit 0   # NSE holiday: no new data, nothing to test; silent skip
fi

cd "$REPO" || { echo "FAILED: trader repo missing ($REPO)"; exit 1; }
mkdir -p "$LOG_DIR" reports/research
stamp="$(date -u +%Y%m%dT%H%M)"
out="$LOG_DIR/research_daily_${stamp}.json"
err="$LOG_DIR/research_daily_${stamp}.err"


if [ -n "$(git status --porcelain)" ]; then
  echo "FAILED: repo has uncommitted changes, research run skipped. Commit or stash them first."
  exit 1
fi

prompt_file="$(mktemp "$LOG_DIR/research_prompt_XXXX.md")"
{
  # /research command body without its frontmatter, with $ARGUMENTS fixed to 1
  awk 'BEGIN{c=0} /^---$/ && c<2 {c++; next} c>=2' .claude/commands/research.md | sed 's/\$ARGUMENTS/1/g'
  cat "$SCRIPT_DIR/research_daily_prompt.md"
} > "$prompt_file"

allowed="Read,Write,Edit,WebSearch,WebFetch,Bash(uv run pytest *),Bash(uv run trader research-eval *),Bash(uv run trader research-status *),Bash(uv run trader market-context *),Bash(uv run trader update *),Bash(uv run trader fundamentals-snapshot *),Bash(git status *),Bash(git diff *),Bash(git log *),Bash(ls *),Bash(cat *),Bash(sha256sum *)"
denied="Bash(uv run trader research-promote *),Bash(uv run trader research-retire *),Bash(uv run trader paper-*),Bash(uv run trader daily *),Bash(git push *),Bash(git commit *),Bash(git reset *),Bash(git checkout *),Bash(rm *),mcp__dhan__*"

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "DRY RUN. prompt bytes: $(wc -c < "$prompt_file"), prompt file: $prompt_file"
  echo "claude version: $(claude --version 2>&1)"
  echo "allowed: $allowed"
  echo "denied: $denied"
  exit 0
fi

rm -f reports/research/last_run.txt
before="$(sha256sum "${GUARDED[@]}" | sha256sum)"
timeout 3000 claude -p "$(cat "$prompt_file")" \
  --allowedTools "$allowed" \
  --disallowedTools "$denied" \
  --max-turns 60 --output-format json >"$out" 2>"$err"
rc=$?
rm -f "$prompt_file"

# Guard: the gates must not change during a run. Restore them and report if they did.
after="$(sha256sum "${GUARDED[@]}" | sha256sum)"
if [ "$before" != "$after" ]; then
  git checkout -- "${GUARDED[@]}"
  echo "WARNING: gate files changed during the run and were restored from git. Investigate before trusting this run."
fi

summary="reports/research/last_run.txt"
if [ "$rc" -ne 0 ] || [ ! -s "$summary" ]; then
  echo "FAILED: research run exit=$rc (no summary written). Log: $out / $err"
  [ -s "$err" ] && tail -n 20 "$err"
  exit 1
fi
cat "$summary"

if [ -n "$(git status --porcelain -- research src/trader/research tests)" ]; then
  git add research src/trader/research tests
  slug="$(sed -n 's/^Idea: \([^ ]*\).*/\1/p' "$summary" | head -n1)"
  verdict="$(sed -n 's/^Verdict: //p' "$summary" | head -n1)"
  git commit -q -m "research: scheduled trial ${slug:-unknown} (${verdict:-unknown})" \
    -m "Automated daily run (scripts/research_daily.sh). Not pushed." && echo "committed locally: $(git log --oneline -1)"
else
  echo "no repo changes to commit"
fi
echo "log: $out"
