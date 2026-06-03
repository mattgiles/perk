#!/usr/bin/env bash
# Phase 2 · Turn 8b — hard-gate verification (deep /land + /learn). Checks from
# docs/planning/phase-2-turn-8.md, run FULLY OFFLINE (no gh, no LLM, no network):
#   1. Python suite green for the touched modules
#   2. learn label/header + generalized extract_run_id in plan.py
#   3. find_learn_issue + create_learn_issue in the gateway (label-scoped)
#   4. learn-capture worker registered in cli.py
#   5. extension/learn.ts deepened (summary -> delegate) + tests green
#   6. registry github.learn + learn I/O filled + self-check passes
#   7. contract amendments present (§8.4 learn ops + reconciliation typing)
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

echo "== Check 1: Python suite green (github/plan/pr-land/learn-capture/registry) =="
if uv run pytest tests/test_github.py tests/test_plan.py tests/test_pr_land.py \
    tests/test_learn_capture_cmd.py tests/test_registry.py -q >/tmp/perk-p2t8b-py.log 2>&1; then
  pass "touched python suites green"
else
  bad "python suite failed (see /tmp/perk-p2t8b-py.log)"; tail -25 /tmp/perk-p2t8b-py.log
fi

echo "== Check 2: learn label/header + generalized extract_run_id =="
if grep -q 'LEARN_LABEL = "perk:learn"' perk/plan.py \
    && grep -q 'LEARN_HEADER_KEY' perk/plan.py \
    && grep -q 'def extract_run_id(issue_body: str, \*, header_key' perk/plan.py; then
  pass "perk:learn label + learn-header key + generalized extract_run_id"
else
  bad "plan.py learn vocabulary / generalized extract_run_id missing"
fi

echo "== Check 3: gateway learn ops (label-scoped) =="
if grep -q 'def find_learn_issue' perk/github.py && grep -q 'def create_learn_issue' perk/github.py; then
  pass "find_learn_issue + create_learn_issue in perk/github.py"
else
  bad "learn gateway ops missing"
fi

echo "== Check 4: learn-capture worker registered =="
if grep -q 'cli.add_command(learn_capture)' perk/cli/cli.py; then
  pass "learn-capture registered in cli.py"
else
  bad "learn-capture not registered in cli.py"
fi

echo "== Check 5: extension learn.ts deepened + tests green =="
if grep -q 'learn-capture' extension/learn.ts && grep -q 'summary' extension/learn.ts; then
  pass "learn.ts delegates to learn-capture with an optional summary"
else
  bad "learn.ts not deepened"
fi
if node --test extension/learn.test.ts >/tmp/perk-p2t8b-ts.log 2>&1; then
  pass "extension learn.test.ts green"
else
  bad "extension learn tests failed (see /tmp/perk-p2t8b-ts.log)"; tail -20 /tmp/perk-p2t8b-ts.log
fi

echo "== Check 6: registry github.learn + learn I/O + self-check =="
if uv run perk registry check >/dev/null 2>&1 && uv run python - <<'PY' >/tmp/perk-p2t8b-reg.log 2>&1; then
from perk.registry import load_registry
stages = {s.id: s for s in load_registry().stages}
learn = stages["learn"]
assert "github.learn" in load_registry().state_keys, "github.learn missing from vocabulary"
assert "github.learn" in learn.writes, learn.writes
assert "github.comments" in learn.writes, learn.writes
assert "cache.plan-ref" in learn.reads, learn.reads
print("ok")
PY
  pass "github.learn in vocabulary; learn writes github.learn+github.comments, reads plan-ref"
else
  bad "registry learn I/O not filled / self-check failed"; tail -10 /tmp/perk-p2t8b-reg.log
fi

echo "== Check 7: contract amendments present =="
if grep -q 'Authored (P2.T8b' shared/contracts.md \
    && grep -q 'find_learn_issue' shared/contracts.md \
    && grep -q 'Reconciliation typing' shared/contracts.md; then
  pass "contracts §8.4 learn ops + reconciliation-typing vocabulary"
else
  bad "contracts §8.4 P2.T8b amendments missing"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T8b hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T8b hard gate: FAILURES\033[0m\n"; fi
exit $fail
