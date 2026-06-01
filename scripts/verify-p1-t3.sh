#!/usr/bin/env bash
# Phase 1 · Turn 3 — hard-gate verification (/plan-save warm door + the planning skill).
# Checks from docs/planning/phase-1-turn-3.md §1, run FULLY OFFLINE (no gh, no LLM, no network,
# no Python GitHub write — the cold door is faked through PERK_BIN):
#   1. the warm-door live suite passes offline (delegate + link + terminate + loud failures)
#   2. the planning skill is shipped + declared (pi.skills, files, the line-numbers rule)
#   3. the registry `save` stage writes [github.plan, cache.plan-ref, session.workflow-state]
#   4. extractPlanMarkdown + the Python plan-save suite are green
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

py_run()  { uv run --project "$ROOT" python "$@"; }
node_offline() { env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY node "$@"; }

echo "== Check 1: warm-door live suite passes offline (faked via PERK_BIN) =="
if node_offline --test extension/planSave.test.ts >/tmp/perk-p1t3-node.log 2>&1; then
  pass "extension/planSave.test.ts green offline ($(grep -E '^# pass' /tmp/perk-p1t3-node.log | head -1))"
else
  bad "planSave.test.ts failed (see /tmp/perk-p1t3-node.log)"; tail -25 /tmp/perk-p1t3-node.log
fi

echo "== Check 2: the planning skill is shipped + declared =="
skill_ok=1
[ -f skills/perk-plan/SKILL.md ] || skill_ok=0
grep -q "^description:" skills/perk-plan/SKILL.md 2>/dev/null || skill_ok=0
grep -qi "DISALLOWED" skills/perk-plan/SKILL.md 2>/dev/null || skill_ok=0
py_run -c "
import json
d = json.load(open('package.json'))
assert d['pi'].get('skills') == ['./skills'], 'pi.skills not declared'
assert 'skills/' in d['files'], 'files missing skills/'
" >/tmp/perk-p1t3-pkg.log 2>&1 || skill_ok=0
if [ "$skill_ok" = 1 ]; then
  pass "skills/perk-plan/SKILL.md present (description + line-numbers rule); package.json declares pi.skills + files"
else
  bad "planning skill missing/undeclared"; cat /tmp/perk-p1t3-pkg.log 2>/dev/null
fi

echo "== Check 3: registry save.writes [github.plan, cache.plan-ref, session.workflow-state] =="
if py_run -c "
from perk.registry import load_registry
save = next(s for s in load_registry().stages if s.id == 'save')
import sys; sys.exit(0 if save.writes == ['github.plan', 'cache.plan-ref', 'session.workflow-state'] else 1)"; then
  pass "save.writes is the full warm-door list; registry self-check holds"
else
  bad "registry save.writes not the expected list"
fi

echo "== Check 4: extractPlanMarkdown unit + Python plan-save suite green =="
if node_offline --test extension/planSave.test.ts >/dev/null 2>&1 \
   && py_run -m pytest tests/test_plan_save.py -q >/tmp/perk-p1t3-pysave.log 2>&1; then
  pass "extractPlanMarkdown unit + tests/test_plan_save.py green"
else
  bad "extractPlanMarkdown or plan-save suite failed (see /tmp/perk-p1t3-pysave.log)"; tail -20 /tmp/perk-p1t3-pysave.log
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP1.T3 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP1.T3 hard gate: FAILURES\033[0m\n"; fi
exit $fail
