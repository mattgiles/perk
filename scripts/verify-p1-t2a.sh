#!/usr/bin/env bash
# Phase 1 · Turn 2a — hard-gate verification (the GitHub plan write, Python/worker half).
# Checks from docs/planning/phase-1-turn-2a.md §1, run FULLY OFFLINE (`gh` is never invoked):
#   1. `perk plan-save --dry-run --plan-file <tmp>` exits 0 and prints the composed header + body
#   2. `--json --dry-run` emits one well-formed { success, ... } object on stdout
#   3. exit-code discipline: missing plan-file -> 1; not-a-repo -> 2
#   4. the registry `save` stage declares writes:[github.plan] (self-check still passes)
#   5. the pytest suite (storage + mutations + command) is green
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
printf '# Sample plan\n\nDo the thing on a durable anchor (no line numbers).\n' > "$W/plan.md"

echo "== Check 1: --dry-run composes header + body, exits 0, no gh =="
OUT="$(perk_in "$W" plan-save --plan-file "$W/plan.md" --dry-run --run-id 01TESTRUN 2>&1)"; rc=$?
if [ "$rc" = 0 ] \
   && printf '%s' "$OUT" | grep -q "perk:metadata-block:plan-header" \
   && printf '%s' "$OUT" | grep -q "perk:metadata-block:plan-body" \
   && printf '%s' "$OUT" | grep -q "run_id: 01TESTRUN"; then
  pass "dry-run exits 0 and prints the composed plan header + body (offline)"
else
  bad "dry-run failed (rc=$rc): $OUT"
fi

echo "== Check 2: --json --dry-run emits a well-formed object =="
J="$(perk_in "$W" plan-save --plan-file "$W/plan.md" --dry-run --json 2>/dev/null)"
if printf '%s' "$J" | py_run -c "
import json,sys
d=json.load(sys.stdin)
ok = (d['success'] is True and d['dry_run'] is True
      and d['plan_ref']['provider']=='github'
      and isinstance(d['plan_ref']['pr_id'], str)
      and 'number' in d['issue'])
sys.exit(0 if ok else 1)"; then
  pass "supervisor --json surface well-formed (plan_ref emitted, pr_id is a string)"
else
  bad "json surface malformed: $J"
fi

echo "== Check 3: exit-code discipline (missing-file -> 1, not-a-repo -> 2) =="
rc_missing=$(perk_in "$W" plan-save --dry-run >/dev/null 2>&1; echo $?)
N="$(mktemp -d)"
rc_norepo=$(perk_in "$N" plan-save --plan-file "$W/plan.md" --dry-run >/dev/null 2>&1; echo $?)
et_norepo="$(perk_in "$N" plan-save --plan-file "$W/plan.md" --dry-run --json 2>/dev/null | py_run -c "import json,sys; print(json.load(sys.stdin)['error_type'])" 2>/dev/null)"
rm -rf "$N"
if [ "$rc_missing" = 1 ] && [ "$rc_norepo" = 2 ] && [ "$et_norepo" = "not_a_repo" ]; then
  pass "missing plan-file -> exit 1; not-a-repo -> exit 2 (error_type=not_a_repo)"
else
  bad "exit codes wrong (missing=$rc_missing norepo=$rc_norepo et=$et_norepo)"
fi

echo "== Check 4: registry save stage declares writes:[github.plan] =="
if perk_in "$W" registry check >/dev/null 2>&1 \
   && py_run -c "
from perk.registry import load_registry
save = next(s for s in load_registry().stages if s.id == 'save')
import sys; sys.exit(0 if save.writes == ['github.plan'] else 1)"; then
  pass "registry self-check passes; save.writes == [github.plan]"
else
  bad "registry save.writes not filled / self-check failed"
fi

echo "== Check 5: unit suite (storage + mutations + command) =="
if py_run -m pytest tests/test_plan.py tests/test_github.py tests/test_plan_save.py -q \
   >/tmp/perk-p1t2a-pytest.log 2>&1; then
  pass "pytest green ($(grep -Eo '[0-9]+ passed' /tmp/perk-p1t2a-pytest.log | head -1))"
else
  bad "pytest failed (see /tmp/perk-p1t2a-pytest.log)"; tail -20 /tmp/perk-p1t2a-pytest.log
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP1.T2a hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP1.T2a hard gate: FAILURES\033[0m\n"; fi
exit $fail
