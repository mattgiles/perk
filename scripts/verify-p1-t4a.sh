#!/usr/bin/env bash
# Phase 1 · Turn 4a — hard-gate verification (the cold door: plan-ref-aware launcher).
# Checks from docs/planning/phase-1-turn-4.md §1, run FULLY OFFLINE (no pi launch, no gh):
#   1. `perk implement --dry-run` after a saved plan-ref derives `plan-<pr_id>` (no --worktree)
#   2. with no plan-ref, `perk implement` exits non-zero with a loud "needs a saved plan" message
#   3. registry `implement` I/O is filled (requires/reads/writes) and the self-check holds
#   4. the launch unit + real-git integration suite is green
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

perk_in() { ( cd "$1" && shift && uv run --project "$ROOT" perk "$@" ); }
py_run()  { uv run --project "$ROOT" python "$@"; }

W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
( cd "$W" && git init -q && uv run --project "$ROOT" perk init >/dev/null 2>&1 )
# Write an active plan-ref (pr_id=7) without a GitHub round-trip — the cold door's input.
py_run -c "
from pathlib import Path
from perk import cache
cache.write_plan_ref(Path('$W'), {
    'provider': 'github', 'pr_id': '7',
    'url': 'https://gh/o/r/issues/7', 'labels': ['perk:plan'], 'objective_id': None,
})"

echo "== Check 1: implement --dry-run derives plan-<pr_id> from the active ref (no --worktree) =="
J="$(perk_in "$W" implement --dry-run 2>/dev/null)"
if printf '%s' "$J" | py_run -c "
import json,sys
d=json.load(sys.stdin)
ok = (d['success'] is True and d['stage']=='implement'
      and d['worktree'].endswith('/plan-7')
      and d['plan_ref']['pr_id']=='7')
sys.exit(0 if ok else 1)"; then
  pass "dry-run derives worktree plan-7 + carries the plan_ref (offline, no --worktree)"
else
  bad "dry-run derivation failed: $J"
fi

echo "== Check 2: no plan-ref -> non-zero + 'needs a saved plan' =="
N="$(mktemp -d)"; ( cd "$N" && git init -q && uv run --project "$ROOT" perk init >/dev/null 2>&1 )
ERR="$(perk_in "$N" implement --dry-run 2>&1 >/dev/null)"; rc=$?
rm -rf "$N"
if [ "$rc" != 0 ] && printf '%s' "$ERR" | grep -q "needs a saved plan"; then
  pass "missing plan-ref -> exit $rc with a loud 'needs a saved plan' message"
else
  bad "no-plan-ref behavior wrong (rc=$rc): $ERR"
fi

echo "== Check 3: registry implement I/O filled + self-check holds =="
if perk_in "$W" registry check >/dev/null 2>&1 \
   && py_run -c "
from perk.registry import load_registry
impl = next(s for s in load_registry().stages if s.id == 'implement')
import sys
ok = (impl.requires == ['cache.plan-ref'] and impl.reads == ['cache.plan-ref']
      and impl.writes == ['session.workflow-state'] and impl.doors.get('warm') is False)
sys.exit(0 if ok else 1)"; then
  pass "registry self-check passes; implement reads cache.plan-ref, writes session.workflow-state, warm:false"
else
  bad "registry implement I/O not filled / self-check failed"
fi

echo "== Check 4: launch unit + real-git integration suite =="
if py_run -m pytest tests/test_launch.py -q >/tmp/perk-p1t4a-pytest.log 2>&1; then
  pass "pytest green ($(grep -Eo '[0-9]+ passed' /tmp/perk-p1t4a-pytest.log | head -1))"
else
  bad "pytest failed (see /tmp/perk-p1t4a-pytest.log)"; tail -20 /tmp/perk-p1t4a-pytest.log
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP1.T4a hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP1.T4a hard gate: FAILURES\033[0m\n"; fi
exit $fail
