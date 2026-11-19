#!/usr/bin/env bash
# Break ("mutation") checks for the shared-account arbitration in src/trader/ledger.py.
#
# Each mutation is applied to a TEMPORARY git worktree (HEAD), never to the real src/. The account tests must FAIL for
# every mutation; a mutation that passes them all "survives" and the script exits 1. The worktree is removed on exit.
#
# Database tests: they carry no marker; they use the `pg`/`lab`/`world` fixtures, which skip when POSTGRES_* is not
# configured. The worktree has no .env and the POSTGRES_* variables are blanked below, so they skip and nothing touches
# any database. (`-k "not db"` would not exclude them.)
#
# Usage: tests/mutation_check.sh        (from anywhere inside the repo)
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WT="$(mktemp -d)"
cleanup() { git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1; rm -rf "$WT"; git -C "$REPO" worktree prune; }
trap cleanup EXIT

git -C "$REPO" worktree add --detach "$WT" HEAD >/dev/null 2>&1 || { echo "cannot create worktree"; exit 2; }
for v in POSTGRES_HOST POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB POSTGRES_PORT POSTGRES_SCHEMA; do export "$v="; done

TESTS=(tests/test_account_budget.py tests/test_account_candidates.py tests/test_account.py)
LEDGER="$WT/src/trader/ledger.py"
ORIG="$(mktemp)"; cp "$LEDGER" "$ORIG"

run_tests() { (cd "$WT" && uv run pytest -q -x "${TESTS[@]}" >"$WT/.out" 2>&1); }

# mutate NAME OLD NEW : exact-string replace in the worktree's ledger.py (aborts if OLD is not found exactly once)
mutate() {
  MUT_OLD="$2" MUT_NEW="$3" MUT_FILE="$LEDGER" python3 - <<'PY' || return 1
import os
p = os.environ["MUT_FILE"]; s = open(p).read(); o = os.environ["MUT_OLD"]; n = os.environ["MUT_NEW"]
assert s.count(o) == 1, f"pattern found {s.count(o)} times"
open(p, "w").write(s.replace(o, n))
PY
}

M_BUYS_ORDER=$'    if mbook is not None:\n        mbook.buy_at_open(d, min_fraction, room(mbook))\n    if swing is not None:\n        swing.fills(d, min_fraction, room(swing))\n    for c in cands:\n        c.buy_at_open(d, min_fraction, room(c))\n'
M_SWING_FIRST=$'    if swing is not None:\n        swing.fills(d, min_fraction, room(swing))\n    if mbook is not None:\n        mbook.buy_at_open(d, min_fraction, room(mbook))\n    for c in cands:\n        c.buy_at_open(d, min_fraction, room(c))\n'
M_CANDS_FIRST=$'    if mbook is not None:\n        mbook.buy_at_open(d, min_fraction, room(mbook))\n    for c in cands:\n        c.buy_at_open(d, min_fraction, room(c))\n    if swing is not None:\n        swing.fills(d, min_fraction, room(swing))\n'

NAMES=("budget = equity/(N+1)" "swing buys before momentum" "candidates buy before swing" "no budget limit")
status=0; rows=()

# baseline: the unmutated code must pass, otherwise the table means nothing
if run_tests; then base="PASS (expected)"; else base="FAIL (unexpected)"; status=2; fi

if [ $status -eq 0 ]; then
  for i in 0 1 2 3; do
    cp "$ORIG" "$LEDGER"
    case $i in
      0) mutate x "budget = equity / len(books)" "budget = equity / (len(books) + 1)" ;;
      1) mutate x "$M_BUYS_ORDER" "$M_SWING_FIRST" ;;
      2) mutate x "$M_BUYS_ORDER" "$M_CANDS_FIRST" ;;
      3) mutate x "        return math.inf if len(books) == 1 else max(budget - b.value_at_open(d), 0.0)" "        return math.inf" ;;
    esac || { rows+=("${NAMES[$i]}|NOT APPLIED"); status=2; continue; }
    if run_tests; then rows+=("${NAMES[$i]}|SURVIVED (tests passed: gap!)"); status=1
    else rows+=("${NAMES[$i]}|KILLED ($(grep -m1 -E '^(FAILED|ERROR)' "$WT/.out" | cut -c1-90))"); fi
  done
fi

echo "unmutated baseline: ${base}"
printf '%-30s %s\n' "MUTATION" "RESULT"
for r in "${rows[@]:-}"; do [ -n "$r" ] && printf '%-30s %s\n' "${r%%|*}" "${r#*|}"; done
[ $status -eq 0 ] && echo "all mutations killed" || echo "mutation check FAILED (status $status)"
exit $status
