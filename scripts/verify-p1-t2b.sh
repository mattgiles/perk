#!/usr/bin/env bash
# Phase 1 · Turn 2b — hard-gate verification (plan-ref: cache.plan-ref + the session linkage).
# Checks from docs/planning/phase-1-turn-2b.md §1, run FULLY OFFLINE (no gh, no LLM, no network):
#   1. the TS live suite passes with API keys unset (the planRef.test.ts linkage cases)
#   2. the cache-file primitive round-trips in both planes (unit suites)
#   3. the cold door persists the ref on a real save, not on --dry-run (pytest subset)
#   4. the registry `save` stage declares writes:[github.plan, cache.plan-ref]
#   5. a fresh `perk init` gitignores /.pi/workflow/plan-ref.json (idempotent convergence)
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

py_run()  { uv run --project "$ROOT" python "$@"; }
node_offline() { env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY node "$@"; }

echo "== Check 1: TS live linkage suite passes offline =="
if node_offline --test extension/planRef.test.ts >/tmp/perk-p1t2b-node.log 2>&1; then
  pass "extension/planRef.test.ts green offline ($(grep -E '^# pass' /tmp/perk-p1t2b-node.log | head -1))"
else
  bad "planRef.test.ts failed (see /tmp/perk-p1t2b-node.log)"; tail -25 /tmp/perk-p1t2b-node.log
fi

echo "== Check 2: cache.plan-ref primitive round-trips in both planes =="
if node_offline --test extension/cache.test.ts extension/workflowState.test.ts \
     >/tmp/perk-p1t2b-unit.log 2>&1 \
   && py_run -m pytest tests/test_cache.py -q >/tmp/perk-p1t2b-pycache.log 2>&1; then
  pass "TS cache/workflowState units + Python tests/test_cache.py green"
else
  bad "cache primitive units failed"; tail -20 /tmp/perk-p1t2b-unit.log /tmp/perk-p1t2b-pycache.log
fi

echo "== Check 3: cold door persists the ref on save, not on --dry-run =="
if py_run -m pytest tests/test_plan_save.py -q >/tmp/perk-p1t2b-pysave.log 2>&1; then
  pass "tests/test_plan_save.py green (writes-cache + dry-run-no-cache assertions)"
else
  bad "plan-save cache assertions failed (see /tmp/perk-p1t2b-pysave.log)"; tail -20 /tmp/perk-p1t2b-pysave.log
fi

echo "== Check 4: registry save stage writes [github.plan, cache.plan-ref] =="
if py_run -c "
from perk.registry import load_registry
save = next(s for s in load_registry().stages if s.id == 'save')
import sys; sys.exit(0 if {'github.plan', 'cache.plan-ref'} <= set(save.writes) else 1)"; then
  pass "save.writes includes [github.plan, cache.plan-ref]; registry self-check holds"
else
  bad "registry save.writes missing github.plan/cache.plan-ref"
fi

echo "== Check 5: fresh init gitignores plan-ref.json (idempotent) =="
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
( cd "$W" && git init -q && uv run --project "$ROOT" perk init >/dev/null 2>&1 )
if grep -q "/.pi/workflow/plan-ref.json" "$W/.gitignore" \
   && py_run -m pytest tests/test_init_idempotent.py -q >/tmp/perk-p1t2b-init.log 2>&1; then
  pass "init lists /.pi/workflow/plan-ref.json; convergence idempotent"
else
  bad "init gitignore entry missing or not idempotent"; tail -20 /tmp/perk-p1t2b-init.log
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP1.T2b hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP1.T2b hard gate: FAILURES\033[0m\n"; fi
exit $fail
