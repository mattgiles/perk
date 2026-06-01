#!/usr/bin/env bash
# Phase 1 · Turn 5b — hard-gate verification (the land path + thin learn).
# Checks from docs/planning/phase-1-turn-5.md §1, run FULLY OFFLINE (no gh, no LLM):
#   5. `perk pr-land --dry-run` composes the merge plan, exits 0; --json well-formed;
#      pending-learn is NOT set on a dry run
#   6. exit-code discipline (no plan-ref -> 1; not-a-repo -> 2)
#   7. registry land/learn I/O filled + self-check
#   8. the TS live suite passes offline: /land sets pending-learn; /learn clears it
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

echo "== Check 5: pr-land --dry-run composes offline, sets no marker =="
J="$(perk_in "$W" pr-land --dry-run --json 2>/dev/null)"; rc=$?
if [ "$rc" = 0 ] && printf '%s' "$J" | py_run -c "
import json,sys
d=json.load(sys.stdin)
ok=(d['success'] is True and d['dry_run'] is True and d['branch']=='plan-7'
    and d['pending_learn'] is False)
sys.exit(0 if ok else 1)" && [ ! -f "$W/.pi/workflow/markers/pending-learn" ]; then
  pass "dry-run well-formed; no pending-learn marker written"
else
  bad "dry-run wrong (rc=$rc): $J  (marker present? $( [ -f "$W/.pi/workflow/markers/pending-learn" ] && echo yes || echo no ))"
fi

echo "== Check 6: exit-code discipline =="
N="$(mktemp -d)"; ( cd "$N" && git init -q && uv run --project "$ROOT" perk init >/dev/null 2>&1 )
rc_noref=$(perk_in "$N" pr-land --dry-run >/dev/null 2>&1; echo $?)
et_noref="$(perk_in "$N" pr-land --dry-run --json 2>/dev/null | py_run -c "import json,sys;print(json.load(sys.stdin)['error_type'])" 2>/dev/null)"
B="$(mktemp -d)"; rc_norepo=$(perk_in "$B" pr-land --dry-run >/dev/null 2>&1; echo $?)
rm -rf "$N" "$B"
if [ "$rc_noref" = 1 ] && [ "$et_noref" = "no_plan_ref" ] && [ "$rc_norepo" = 2 ]; then
  pass "no plan-ref -> exit 1 (no_plan_ref); not-a-repo -> exit 2"
else
  bad "exit codes wrong (noref=$rc_noref et=$et_noref norepo=$rc_norepo)"
fi

echo "== Check 7: registry land/learn I/O filled + self-check =="
if perk_in "$W" registry check >/dev/null 2>&1 \
   && py_run -c "
from perk.registry import load_registry
stages = {s.id: s for s in load_registry().stages}
land, learn = stages['land'], stages['learn']
import sys
ok = ('github.pr' in land.writes and 'cache.markers' in land.writes
      and learn.writes == ['cache.markers'] and 'cache.markers' in learn.requires)
sys.exit(0 if ok else 1)"; then
  pass "registry self-check passes; land writes github.pr+cache.markers, learn writes cache.markers"
else
  bad "registry land/learn I/O not filled / self-check failed"
fi

echo "== Check 8: TS live suite (/land sets, /learn clears pending-learn) =="
if node_offline --test extension/land.test.ts extension/learn.test.ts >/tmp/perk-p1t5b-node.log 2>&1; then
  pass "land.test.ts + learn.test.ts green offline ($(grep -E '^# pass' /tmp/perk-p1t5b-node.log | head -1))"
else
  bad "land/learn suite failed (see /tmp/perk-p1t5b-node.log)"; tail -20 /tmp/perk-p1t5b-node.log
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP1.T5b hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP1.T5b hard gate: FAILURES\033[0m\n"; fi
exit $fail
