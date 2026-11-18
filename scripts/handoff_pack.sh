#!/usr/bin/env bash
# Pack what a new host needs besides the repo itself. All data (ledger, trials, candles, fundamentals, membership,
# reports) now lives in Postgres, so the pack is only config.yaml and the git HEAD. .env is NEVER packed: create it on
# the new host with the same POSTGRES_* values (and DHAN_* only if --source dhan is wanted).
# Usage: scripts/handoff_pack.sh [OUT_DIR] [--force]   (--force packs despite a trial-guard mismatch)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
out_dir="${TMPDIR:-/tmp}"; force=0
for a in "$@"; do case "$a" in --force) force=1 ;; *) out_dir="$a" ;; esac; done
cd "$REPO"
if ! "$SCRIPT_DIR/trial_guard.sh"; then
  [ "$force" = 1 ] && echo "--force given: packing anyway" || { echo "Refusing to pack: the trial guard failed (override with --force)."; exit 1; }
fi
stage="$(mktemp -d)"; trap 'rm -rf "$stage"' EXIT
mkdir -p "$out_dir"
cp config.yaml "$stage/"
git rev-parse HEAD > "$stage/GIT_HEAD"
tar="$out_dir/trader-state-$(date -u +%Y%m%dT%H%M%S).tar.gz"
tar -C "$stage" -czf "$tar" .
echo "$tar"
echo "Restore on the new host, from the repo root:  tar -xzf <file> -C . && create .env (POSTGRES_*) && scripts/handoff_check.sh"
