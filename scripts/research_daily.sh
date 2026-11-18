#!/usr/bin/env bash
# Scheduled idea testing: runs the /research loop for ONE idea with Claude Code (print mode).
# Hermes cron: Mon-Fri 18:30 Asia/Kolkata (after the 16:30 paper run and its data refresh). Skips NSE holidays.
# All data lives in Postgres (POSTGRES_* in .env); each run is also stored in job_runs.
# Paper only. Promotion, retirement, pushes and order tools are blocked by the tool allowlist.
# Stdout is the Telegram message. Commits locally when something changed; never pushes.
# Set DRY_RUN=1 to print the command and prompt size without running Claude (no trial counted).
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOLIDAY_FILES=("$SCRIPT_DIR"/nse_holidays_*.txt)
[ -n "${TRADER_HOLIDAYS_FILE:-}" ] && HOLIDAY_FILES=("$TRADER_HOLIDAYS_FILE")
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${TRADER_LOG_DIR:-${TMPDIR:-/tmp}/trader-logs}"
# Guard policy (applied after the run). Tracked files are restored unless they match TRACKED_OK_RE.
TRACKED_OK_RE='^(research/backlog\.md|research/india_evidence\.md|research/journal/.*)$'
# Untracked files are kept (and committed) only if they match UNTRACKED_OK_RE.
UNTRACKED_OK_RE='^(research/journal/.*|src/trader/research/candidates/.*|tests/test_[^/]*\.py)$'

today_ist=$(TZ=Asia/Kolkata date +%Y-%m-%d)
if cat "${HOLIDAY_FILES[@]}" 2>/dev/null | grep -qx "$today_ist"; then
  exit 0   # NSE holiday: no new data, nothing to test; silent skip
fi

cd "$REPO" || { echo "FAILED: trader repo missing ($REPO)"; exit 1; }
mkdir -p "$LOG_DIR" reports/research
stamp="$(date -u +%Y%m%dT%H%M)"
out="$LOG_DIR/research_daily_${stamp}.json"
err="$LOG_DIR/research_daily_${stamp}.err"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Store the run's message and log in job_runs; a failure to log never changes the outcome.
log_run() {  # exit_code [message_file] [log_file]
  uv run trader db log-run --job research --exit "$1" ${2:+--message-file "$2"} ${3:+--log-file "$3"} --started "$started" \
    >/dev/null 2>&1 || echo "⚠️ run not logged to the database"
}


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

# Path rules use Claude Code's gitignore-style permission syntax, relative to the working directory
# (the repo root, we cd there above). Edit(...) rules cover all file-editing tools; Write(...) is listed too.
allowed="Read,WebSearch,WebFetch"
for pat in "research/**" "src/trader/research/candidates/**" "reports/research/**" "tests/test_*.py"; do
  allowed+=",Edit($pat),Write($pat)"
done
allowed+=",Bash(uv run pytest *),Bash(uv run trader research-eval *),Bash(uv run trader research-status *),Bash(uv run trader show *),Bash(uv run trader market-context *),Bash(uv run trader update *),Bash(uv run trader fundamentals-snapshot *),Bash(git status *),Bash(git diff *),Bash(git log *),Bash(sha256sum *)"
denied="Read(.env),Read(.env.*),Read(**/.env*),Edit(.env*),Write(.env*),Bash(cat *),Bash(ls *),Bash(head *),Bash(tail *),Bash(grep *),Bash(find *),Bash(env*),Bash(printenv*),Bash(uv run trader research-promote *),Bash(uv run trader research-retire *),Bash(uv run trader paper-*),Bash(uv run trader db migrate-local *),Bash(uv run trader daily *),Bash(git push *),Bash(git commit *),Bash(git reset *),Bash(git checkout *),Bash(rm *),mcp__dhan__*"

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "DRY RUN. prompt bytes: $(wc -c < "$prompt_file"), prompt file: $prompt_file"
  echo "claude version: $(claude --version 2>&1)"
  echo "allowed: $allowed"
  echo "denied: $denied"
  echo "guard keeps tracked changes only for: $TRACKED_OK_RE"
  echo "guard keeps untracked files only for: $UNTRACKED_OK_RE"
  exit 0
fi

rm -f reports/research/last_run.txt
# Run from the repo root without the Dhan credentials in the environment.
env -u DHAN_CLIENT_ID -u DHAN_ACCESS_TOKEN timeout 3000 claude -p "$(cat "$prompt_file")" \
  --allowedTools "$allowed" \
  --disallowedTools "$denied" \
  --max-turns 60 --output-format json >"$out" 2>"$err"
rc=$?
rm -f "$prompt_file"

# Guard (a): any change to a tracked file outside the allowed research notes is reverted.
# Covers evaluate.py, dsr.py, registry.py, metrics.py, momentum.py, walkforward.py, config.yaml,
# scripts/, tests/ and already-committed candidates.
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if ! [[ "$f" =~ $TRACKED_OK_RE ]]; then
    git checkout -- "$f"
    echo "WARNING: tracked file changed during the run and was restored from git: $f"
  fi
done < <(git diff --name-only)

# Guard (b): untracked files are kept only in allowed places; the rest are listed and not committed.
keep_untracked=()
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if [[ "$f" =~ $UNTRACKED_OK_RE ]]; then
    keep_untracked+=("$f")
  else
    echo "WARNING: unexpected untracked file left uncommitted: $f"
  fi
done < <(git ls-files --others --exclude-standard)

summary="reports/research/last_run.txt"
if [ "$rc" -ne 0 ] || [ ! -s "$summary" ]; then
  echo "FAILED: research run exit=$rc (no summary written). Log: $out / $err"
  [ -s "$err" ] && tail -n 20 "$err"
  log_run "${rc:-1}" "" "$out"
  exit 1
fi
# Telegram-ready summary (stdout is the message). Falls back to the raw summary if the formatter fails.
uv run python "$SCRIPT_DIR/format_research_message.py" "$summary" 2>/dev/null || cat "$summary"
log_run 0 "$summary" "$out"

# Guard (c): commit only explicitly allowed paths, never `git add -A`.
commit_paths=(${keep_untracked[@]+"${keep_untracked[@]}"})
while IFS= read -r f; do
  [ -n "$f" ] && commit_paths+=("$f")   # tracked leftovers all match TRACKED_OK_RE after guard (a)
done < <(git diff --name-only)
if [ "${#commit_paths[@]}" -gt 0 ]; then
  git add -- "${commit_paths[@]}"
  slug="$(sed -n 's/^Idea: \([^ ]*\).*/\1/p' "$summary" | head -n1)"
  verdict="$(sed -n 's/^Verdict: //p' "$summary" | head -n1)"
  git commit -q -m "research: scheduled trial ${slug:-unknown} (${verdict:-unknown})" \
    -m "Automated daily run (scripts/research_daily.sh). Not pushed." && echo "committed locally: $(git log --oneline -1)"
else
  echo "no repo changes to commit"
fi
echo "log: $out"
