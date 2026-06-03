#!/usr/bin/env bash
# Phase 2 · Turn 8a — hard-gate verification (PR-body craft). Checks from
# docs/planning/phase-2-turn-8.md, run FULLY OFFLINE (no gh, no LLM, no network):
#   1. Python suite green for the touched modules
#   2. gateway ops present (update_pr_body / validate_pr_body / get_pr_body)
#   3. pr-check + pr-ready workers registered in cli.py
#   4. _compose_pr_body deepened + stale docstring line deleted
#   5. extension/ready.ts wired in index.ts (+ the ready tool)
#   6. contract amendments present (§8.4 authored P2.T8a + the two-target split)
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

echo "== Check 1: Python suite green (github/pr-submit/pr-check/pr-ready) =="
if uv run pytest tests/test_github.py tests/test_pr_submit.py tests/test_pr_check_cmd.py \
    tests/test_pr_ready_cmd.py -q >/tmp/perk-p2t8a-py.log 2>&1; then
  pass "touched python suites green"
else
  bad "python suite failed (see /tmp/perk-p2t8a-py.log)"; tail -25 /tmp/perk-p2t8a-py.log
fi

echo "== Check 2: gateway ops present =="
if grep -q 'def update_pr_body' perk/github.py \
    && grep -q 'def validate_pr_body' perk/github.py \
    && grep -q 'def get_pr_body' perk/github.py; then
  pass "update_pr_body + validate_pr_body + get_pr_body in perk/github.py"
else
  bad "PR-body gateway ops missing"
fi

echo "== Check 3: workers registered =="
if grep -q 'cli.add_command(pr_check)' perk/cli/cli.py \
    && grep -q 'cli.add_command(pr_ready)' perk/cli/cli.py; then
  pass "pr-check + pr-ready registered in cli.py"
else
  bad "pr-check/pr-ready not registered in cli.py"
fi

echo "== Check 4: compose deepened + stale docstring removed =="
if grep -q '<details><summary>Plan #' perk/cli/commands/pr_submit_cmd.py \
    && ! grep -q 'No HTML .details. (erk tripwire' perk/cli/commands/pr_submit_cmd.py; then
  pass "_compose_pr_body embeds the plan + the false docstring line is gone"
else
  bad "_compose_pr_body not deepened or stale docstring line still present"
fi

echo "== Check 5: extension wired =="
if test -f extension/ready.ts \
    && grep -q 'registerReady' extension/index.ts \
    && grep -q 'name: "ready"' extension/ready.ts; then
  pass "ready.ts registered in index.ts (+ ready tool)"
else
  bad "extension/ready.ts not wired"
fi
if node --test extension/ready.test.ts extension/submit.test.ts >/tmp/perk-p2t8a-ts.log 2>&1; then
  pass "extension ready + submit tests green"
else
  bad "extension ready/submit tests failed (see /tmp/perk-p2t8a-ts.log)"; tail -20 /tmp/perk-p2t8a-ts.log
fi

echo "== Check 6: contract amendments present =="
if grep -q 'Authored (P2.T8a' shared/contracts.md \
    && grep -q 'update_pr_body' shared/contracts.md \
    && grep -q 'validate_pr_body' shared/contracts.md; then
  pass "contracts §8.4 authored the P2.T8a PR-body ops"
else
  bad "contracts §8.4 P2.T8a amendments missing"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T8a hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T8a hard gate: FAILURES\033[0m\n"; fi
exit $fail
