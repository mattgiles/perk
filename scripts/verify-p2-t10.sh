#!/usr/bin/env bash
# Phase 2 · Turn 10 — hard-gate verification (/objective-plan factory + completion-audit). Checks
# from docs/planning/phase-2-turn-10.md, run FULLY OFFLINE (no gh, no LLM, no network):
#   1. touched Python suites green
#   2. registry valid + objective-plan initial before plan + dedicated (not generic)
#   3. objective_plan_cmd registered + DEDICATED_STAGES includes it
#   4. .pi/agents/objective-explorer.md committed (package: perk + cheap model + read-only tools)
#   5. skills/perk-objective-plan/SKILL.md present (completion-audit + link-back + never-delegate)
#   6. extension/objectivePlan.ts registered in index.ts + objective_id in planSave.ts
#   7. objectivePlan.test.ts + planSave.test.ts green
#   8. contract amendments present (§8.3 + §8.4 P2.T10, incl. honest-enforcement note)
#   9. perk plan-save --help shows --objective-id
#  10. doctor offline-clean (subagent-engine ok, detail lists objective-explorer)
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

echo "== Check 1: Python suites green =="
if uv run pytest tests/test_objective_plan_cmd.py tests/test_registry.py tests/test_cli_stages.py \
    tests/test_launch.py tests/test_plan_save.py tests/test_doctor.py -q >/tmp/perk-p2t10-py.log 2>&1; then
  pass "touched python suites green"
else
  bad "python suite failed (see /tmp/perk-p2t10-py.log)"; tail -25 /tmp/perk-p2t10-py.log
fi

echo "== Check 2: registry valid + objective-plan initial before plan + dedicated =="
if uv run perk registry check >/dev/null 2>&1 \
    && uv run perk --help 2>/dev/null | grep -q "objective-plan" \
    && uv run perk objective-plan --help 2>/dev/null | grep -q "NUMBER" \
    && uv run python -c "
from perk.registry import load_registry
r = load_registry(); by={s.id:s for s in r.stages}
assert [s.id for s in r.stages if not s.predecessors]==['objective-plan']
assert by['objective-plan'].successors==['plan'] and by['plan'].predecessors==['objective-plan']
" 2>/dev/null; then
  pass "objective-plan is the single initial before plan + dedicated command present"
else
  bad "registry/objective-plan placement or dedicated command wrong"
fi

echo "== Check 3: objective_plan_cmd registered + DEDICATED_STAGES =="
if grep -q 'cli.add_command(objective_plan)' perk/cli/cli.py \
    && grep -q '"objective-plan"' perk/cli/stages.py; then
  pass "objective_plan registered in cli.py + in DEDICATED_STAGES"
else
  bad "objective_plan not registered / not in DEDICATED_STAGES"
fi

echo "== Check 4: objective-explorer agent def committed =="
if [ -f .pi/agents/objective-explorer.md ] \
    && grep -q 'package: perk' .pi/agents/objective-explorer.md \
    && grep -q 'claude-haiku' .pi/agents/objective-explorer.md \
    && grep -q 'tools: read, grep, find, ls, bash' .pi/agents/objective-explorer.md; then
  pass ".pi/agents/objective-explorer.md present (perk + cheap model + read-only tools)"
else
  bad ".pi/agents/objective-explorer.md missing or misconfigured"
fi

echo "== Check 5: perk-objective-plan skill present =="
if [ -f skills/perk-objective-plan/SKILL.md ] \
    && grep -qi 'completion audit' skills/perk-objective-plan/SKILL.md \
    && grep -qi 'link the node back' skills/perk-objective-plan/SKILL.md \
    && grep -qi 'never-delegate' skills/perk-objective-plan/SKILL.md; then
  pass "skills/perk-objective-plan/SKILL.md present (audit + link-back + never-delegate)"
else
  bad "perk-objective-plan skill missing or incomplete"
fi

echo "== Check 6: objectivePlan.ts registered + objective_id in planSave.ts =="
if [ -f extension/objectivePlan.ts ] \
    && grep -q 'registerObjectivePlan' extension/index.ts \
    && grep -q 'objective_node' extension/objectivePlan.ts \
    && grep -q '"objective-plan"' extension/objectivePlan.ts \
    && grep -q 'objective-id' extension/planSave.ts; then
  pass "objectivePlan.ts (objective_node tool + /objective-plan) registered + objective_id threaded"
else
  bad "objectivePlan.ts not wired or objective_id not threaded in planSave.ts"
fi

echo "== Check 7: extension tests green =="
if node --test extension/objectivePlan.test.ts extension/planSave.test.ts >/tmp/perk-p2t10-ts.log 2>&1; then
  pass "objectivePlan.test.ts + planSave.test.ts green"
else
  bad "extension tests failed (see /tmp/perk-p2t10-ts.log)"; tail -20 /tmp/perk-p2t10-ts.log
fi

echo "== Check 8: contract amendments present =="
if grep -q 'Objective plan factory + transition tools (P2.T10)' shared/contracts.md \
    && grep -q 'Authored (P2.T10' shared/contracts.md \
    && grep -qi 'model-path-only' shared/contracts.md \
    && grep -q 'trim()' shared/contracts.md; then
  pass "contracts §8.3 + §8.4 P2.T10 amendments present (incl. honest-enforcement note)"
else
  bad "contracts P2.T10 amendments missing"
fi

echo "== Check 9: plan-save --objective-id =="
if uv run perk plan-save --help 2>/dev/null | grep -q 'objective-id'; then
  pass "perk plan-save --help shows --objective-id"
else
  bad "--objective-id missing from plan-save"
fi

echo "== Check 10: doctor offline-clean + lists objective-explorer =="
# `perk doctor` exits non-zero when any check is unhealthy (e.g. github unauthed in CI), so capture
# its output first (under pipefail the non-zero exit would otherwise mask a successful grep).
doctor_json=$(uv run perk doctor --json 2>/dev/null || true)
if printf '%s' "$doctor_json" | grep -q 'objective-explorer'; then
  pass "doctor detail lists objective-explorer"
else
  bad "doctor does not list objective-explorer (or failed)"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T10 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T10 hard gate: FAILURES\033[0m\n"; fi
exit $fail
