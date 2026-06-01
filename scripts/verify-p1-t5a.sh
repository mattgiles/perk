#!/usr/bin/env bash
# Phase 1 · Turn 5a — hard-gate verification (the submit cold door + warm twin).
# Checks from docs/planning/phase-1-turn-5.md §1, run FULLY OFFLINE (no git push, no gh, no LLM):
#   1. `perk pr-submit --dry-run` (worktree w/ a plan-ref) composes the plan, exits 0, shells nothing
#   2. `--json --dry-run` emits one well-formed { success, pr, plan_header, dry_run } object
#   3. exit-code discipline: no plan-ref -> 1 (no_plan_ref); not-a-repo -> 2
#   4. registry `submit` I/O is filled and the self-check holds
#   5. the warm-door live suite passes offline (delegation faked via PERK_BIN)
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

perk_in() { ( cd "$1" && shift && uv run --project "$ROOT" perk "$@" ); }
py_run()  { uv run --project "$ROOT" python "$@"; }
node_offline() { env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY node "$@"; }

W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
( cd "$W" && git init -q && uv run --project "$ROOT" perk init >/dev/null 2>&1 )
py_run -c "
from pathlib import Path
from perk import cache
cache.write_plan_ref(Path('$W'), {'provider':'github','pr_id':'7','url':'https://gh/o/r/issues/7',
    'labels':['perk:plan'],'objective_id':None})"

echo "== Check 1: pr-submit --dry-run composes offline, exits 0 =="
OUT="$(perk_in "$W" pr-submit --dry-run 2>&1)"; rc=$?
if [ "$rc" = 0 ] && printf '%s' "$OUT" | grep -q "branch=plan-7"; then
  pass "dry-run derives branch plan-7 and composes the header update (no push, no gh)"
else
  bad "dry-run failed (rc=$rc): $OUT"
fi

echo "== Check 2: --json --dry-run well-formed =="
J="$(perk_in "$W" pr-submit --dry-run --json 2>/dev/null)"
if printf '%s' "$J" | py_run -c "
import json,sys
d=json.load(sys.stdin)
ok=(d['success'] is True and d['dry_run'] is True and d['branch']=='plan-7' and d['issue']==7
    and d['pr']['number']==0
    and d['plan_header']['fields_updated']==['branch','pr','lifecycle_stage'])
sys.exit(0 if ok else 1)"; then
  pass "supervisor --json surface well-formed (branch, issue, staged header fields)"
else
  bad "json surface malformed: $J"
fi

echo "== Check 3: exit-code discipline =="
N="$(mktemp -d)"; ( cd "$N" && git init -q && uv run --project "$ROOT" perk init >/dev/null 2>&1 )
rc_noref=$(perk_in "$N" pr-submit --dry-run >/dev/null 2>&1; echo $?)
et_noref="$(perk_in "$N" pr-submit --dry-run --json 2>/dev/null | py_run -c "import json,sys;print(json.load(sys.stdin)['error_type'])" 2>/dev/null)"
B="$(mktemp -d)"
rc_norepo=$(perk_in "$B" pr-submit --dry-run >/dev/null 2>&1; echo $?)
rm -rf "$N" "$B"
if [ "$rc_noref" = 1 ] && [ "$et_noref" = "no_plan_ref" ] && [ "$rc_norepo" = 2 ]; then
  pass "no plan-ref -> exit 1 (no_plan_ref); not-a-repo -> exit 2"
else
  bad "exit codes wrong (noref=$rc_noref et=$et_noref norepo=$rc_norepo)"
fi

echo "== Check 4: registry submit I/O filled + self-check =="
if perk_in "$W" registry check >/dev/null 2>&1 \
   && py_run -c "
from perk.registry import load_registry
s = next(x for x in load_registry().stages if x.id == 'submit')
import sys
ok = ('cache.plan-ref' in s.requires and 'github.pr' in s.writes and 'github.plan' in s.writes)
sys.exit(0 if ok else 1)"; then
  pass "registry self-check passes; submit writes github.pr + github.plan"
else
  bad "registry submit I/O not filled / self-check failed"
fi

echo "== Check 5: warm-door live suite (delegation faked via PERK_BIN) =="
if node_offline --test extension/submit.test.ts >/tmp/perk-p1t5a-node.log 2>&1; then
  pass "extension/submit.test.ts green offline ($(grep -E '^# pass' /tmp/perk-p1t5a-node.log | head -1))"
else
  bad "submit.test.ts failed (see /tmp/perk-p1t5a-node.log)"; tail -20 /tmp/perk-p1t5a-node.log
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP1.T5a hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP1.T5a hard gate: FAILURES\033[0m\n"; fi
exit $fail
