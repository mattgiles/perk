#!/usr/bin/env bash
# Phase 2 · Turn 9 — hard-gate verification (objective storage + mechanics). Checks from
# docs/planning/phase-2-turn-9.md, run FULLY OFFLINE (no gh, no LLM, no network):
#   1. touched Python suites green (objective/github/objective_cmd/registry)
#   2. registry still valid + `perk objective --help` lists create/show/node/next
#   3. gateway ops present (create_objective_issue/get_objective/update_objective_node)
#   4. objective group registered in cli.py
#   5. extension/objective.ts + registerObjective in index.ts
#   6. extension/objective.test.ts green
#   7. contract amendments present (§8.3 budget + §8.4 objective subsection)
#   8. perk:objective label constant present in perk/objective.py
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

echo "== Check 1: Python suite green (objective/github/objective_cmd/registry) =="
if uv run pytest tests/test_objective.py tests/test_github.py tests/test_objective_cmd.py \
    tests/test_registry.py -q >/tmp/perk-p2t9-py.log 2>&1; then
  pass "touched python suites green"
else
  bad "python suite failed (see /tmp/perk-p2t9-py.log)"; tail -25 /tmp/perk-p2t9-py.log
fi

echo "== Check 2: registry valid + objective group help =="
if uv run perk registry check >/dev/null 2>&1 \
    && uv run perk objective --help 2>/dev/null | grep -q "create" \
    && uv run perk objective --help 2>/dev/null | grep -q "show" \
    && uv run perk objective --help 2>/dev/null | grep -q "node" \
    && uv run perk objective --help 2>/dev/null | grep -q "next"; then
  pass "registry OK + objective group lists create/show/node/next"
else
  bad "registry check failed or objective subcommands missing"
fi

echo "== Check 3: objective gateway ops present =="
if grep -q 'def create_objective_issue' perk/github.py \
    && grep -q 'def get_objective' perk/github.py \
    && grep -q 'def update_objective_node' perk/github.py \
    && grep -q 'def find_objective_issue' perk/github.py; then
  pass "find/create/get/update objective ops in perk/github.py"
else
  bad "objective gateway ops missing"
fi

echo "== Check 4: objective group registered =="
if grep -q 'cli.add_command(objective_group)' perk/cli/cli.py; then
  pass "objective group registered in cli.py"
else
  bad "objective group not registered in cli.py"
fi

echo "== Check 5: extension objective.ts + registerObjective =="
if [ -f extension/objective.ts ] && grep -q 'registerObjective' extension/index.ts; then
  pass "extension/objective.ts present + registered in index.ts"
else
  bad "extension/objective.ts missing or not registered"
fi

echo "== Check 6: extension objective.test.ts green =="
if node --test extension/objective.test.ts >/tmp/perk-p2t9-ts.log 2>&1; then
  pass "extension objective.test.ts green"
else
  bad "extension objective tests failed (see /tmp/perk-p2t9-ts.log)"; tail -20 /tmp/perk-p2t9-ts.log
fi

echo "== Check 7: contract amendments present =="
if grep -q 'Authored (P2.T9' shared/contracts.md \
    && grep -q 'Objective budget + compaction (P2.T9)' shared/contracts.md \
    && grep -q 'objective-roadmap' shared/contracts.md \
    && grep -qi 'explicit-status-only' shared/contracts.md; then
  pass "contracts §8.3 budget + §8.4 objective subsection present"
else
  bad "contracts P2.T9 amendments missing"
fi

echo "== Check 8: perk:objective label constant =="
if grep -q 'OBJECTIVE_LABEL = "perk:objective"' perk/objective.py; then
  pass "perk:objective label constant present"
else
  bad "perk:objective label constant missing"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T9 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T9 hard gate: FAILURES\033[0m\n"; fi
exit $fail
