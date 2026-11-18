#!/usr/bin/env bash
# Guard: does the trials table in Postgres agree with the committed research journals?
# Journals say "(trial N)" / "N trials" in their first lines; the newest trial number must equal the number of
# counted trials in the db. A mismatch means the database is missing trials or a journal is missing.
# Exit 0 = consistent (or nothing to compare), 1 = mismatch. Prints one line.
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.." || exit 1
db="the trials table"
db_n="$(uv run trader db trial-count 2>/dev/null)" && [[ "$db_n" =~ ^[0-9]+$ ]] \
  || { echo "trial guard: cannot read $db (is Postgres reachable? see POSTGRES_* in .env)"; exit 1; }
j_n=0; j_f=""
for f in research/journal/*.md; do
  [ -f "$f" ] || continue
  n="$(head -n 30 "$f" | grep -oiE '\(trial [0-9]+\)|after [0-9]+ trials|; [0-9]+ trials\)' | grep -oE '[0-9]+' | sort -n | tail -n1)"
  if [ -n "$n" ] && [ "$n" -gt "$j_n" ]; then j_n="$n"; j_f="$f"; fi
done
if [ "$j_n" -eq 0 ]; then echo "trial guard: no trial numbers in journals (db has $db_n counted)"; exit 0; fi
if [ "$db_n" -ne "$j_n" ]; then
  echo "trial guard: MISMATCH. $db has $db_n counted trials but the newest journal ($j_f) says $j_n. Check that POSTGRES_* in .env points at the database the research job writes to."
  exit 1
fi
echo "trial guard: ok ($db_n counted trials match $j_f)"
