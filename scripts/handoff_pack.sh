#!/usr/bin/env bash
# Pack the gitignored state needed to run the trader on another host (Hermes).
# Usage: scripts/handoff_pack.sh [OUT_DIR] [--with-candles] [--force]   (--force packs despite a trial-guard mismatch)
# Produces OUT_DIR/trader-state-<UTC stamp>.tar.gz (default OUT_DIR: $TMPDIR or /tmp). Candles (~60 MB) are
# refetchable with `uv run trader update`, so they are left out unless --with-candles is given.
# SQLite files are copied with .backup (consistent even if a run is in progress). .env is NEVER packed.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
out_dir="${TMPDIR:-/tmp}"; with_candles=0
force=0
for a in "$@"; do case "$a" in --with-candles) with_candles=1 ;; --force) force=1 ;; *) out_dir="$a" ;; esac; done
cd "$REPO"
if ! "$SCRIPT_DIR/trial_guard.sh"; then
  [ "$force" = 1 ] && echo "--force given: packing anyway" || { echo "Refusing to pack a research.db that disagrees with the journals (override with --force)."; exit 1; }
fi
stage="$(mktemp -d)"; trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/data" "$out_dir"
for db in paper.db research.db; do
  [ -f "data/$db" ] && sqlite3 "data/$db" ".backup '$stage/data/$db'"
done
for f in params.json selector_stats.json instruments.csv; do [ -f "data/$f" ] && cp "data/$f" "$stage/data/"; done
for d in membership fundamentals; do [ -d "data/$d" ] && cp -r "data/$d" "$stage/data/"; done
[ "$with_candles" = 1 ] && [ -d data/candles ] && cp -r data/candles "$stage/data/"
cp config.yaml "$stage/"
git rev-parse HEAD > "$stage/GIT_HEAD"
tar="$out_dir/trader-state-$(date -u +%Y%m%dT%H%M%S).tar.gz"
tar -C "$stage" -czf "$tar" .
echo "$tar"
echo "Restore on the new host, from the repo root:  tar -xzf <file> -C . && scripts/handoff_check.sh"
echo "Then create .env by hand if --source dhan is wanted (token is not packed)."
