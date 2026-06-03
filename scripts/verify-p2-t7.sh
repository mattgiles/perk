#!/usr/bin/env bash
# Phase 2 · Turn 7 — hard-gate verification (the `/address` review loop). Checks from
# docs/planning/phase-2-turn-7.md, run FULLY OFFLINE (no LLM, no network, no live spawn):
#   1. Python suite green for the touched modules
#   2. Registry validates with `address` (submit -> address -> land) + the generated launcher
#   3. get_pr_feedback / resolve_review_threads present in the gateway
#   4. the two cold workers registered in cli.py
#   5. the perk.review-classifier agent def committed (package: perk + cheap model)
#   6. the perk-address skill present
#   7. extension/address.ts registered in index.ts (+ the resolve_review_threads tool)
#   8. contract amendments present (§8.3 Review loop + §8.4 authored resolve_review_threads)
#   9. doctor offline-clean (subagent-engine stays ok with the benign-stray note)
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

echo "== Check 1: Python suite green (github/feedback/resolve/registry/launch/cli-stages/doctor) =="
if uv run pytest tests/test_github.py tests/test_pr_feedback_cmd.py \
    tests/test_pr_resolve_threads_cmd.py tests/test_registry.py tests/test_launch.py \
    tests/test_cli_stages.py tests/test_doctor.py -q >/tmp/perk-p2t7-py.log 2>&1; then
  pass "touched python suites green"
else
  bad "python suite failed (see /tmp/perk-p2t7-py.log)"; tail -25 /tmp/perk-p2t7-py.log
fi

echo "== Check 2: registry validates with address + generated launcher =="
if uv run perk registry check >/tmp/perk-p2t7-reg.log 2>&1 \
    && uv run perk --help 2>/dev/null | grep -q '  address '; then
  pass "registry valid + 'perk address' launcher generated"
else
  bad "registry invalid or 'perk address' launcher missing"; tail -10 /tmp/perk-p2t7-reg.log
fi
if grep -q 'id: address' shared/registry.yaml \
    && grep -q 'successors: \[address\]' shared/registry.yaml \
    && grep -q 'predecessors: \[address\]' shared/registry.yaml; then
  pass "submit -> address -> land edges present in registry"
else
  bad "submit -> address -> land edges missing in registry"
fi

echo "== Check 3: gateway ops present =="
if grep -q 'def get_pr_feedback' perk/github.py && grep -q 'def resolve_review_threads' perk/github.py; then
  pass "get_pr_feedback + resolve_review_threads in perk/github.py"
else
  bad "review-feedback gateway ops missing"
fi

echo "== Check 4: cold workers registered =="
if grep -q 'cli.add_command(pr_feedback)' perk/cli/cli.py \
    && grep -q 'cli.add_command(pr_resolve_threads)' perk/cli/cli.py; then
  pass "pr-feedback + pr-resolve-threads registered in cli.py"
else
  bad "cold workers not registered in cli.py"
fi

echo "== Check 5: agent def committed =="
if test -f .pi/agents/review-classifier.md \
    && grep -q 'package: perk' .pi/agents/review-classifier.md \
    && grep -q 'claude-haiku-4-5' .pi/agents/review-classifier.md; then
  pass "perk.review-classifier agent def present (package: perk + cheap model)"
else
  bad ".pi/agents/review-classifier.md missing or malformed"
fi

echo "== Check 6: perk-address skill present =="
if test -f skills/perk-address/SKILL.md && grep -q 'name: perk-address' skills/perk-address/SKILL.md; then
  pass "skills/perk-address/SKILL.md present"
else
  bad "skills/perk-address/SKILL.md missing"
fi

echo "== Check 7: extension wired =="
if test -f extension/address.ts \
    && grep -q 'registerAddress' extension/index.ts \
    && grep -q 'resolve_review_threads' extension/address.ts; then
  pass "address.ts registered in index.ts (+ resolve_review_threads tool)"
else
  bad "extension/address.ts not wired"
fi
if node --test extension/address.test.ts >/tmp/perk-p2t7-ts.log 2>&1; then
  pass "extension address.test.ts green"
else
  bad "extension address tests failed (see /tmp/perk-p2t7-ts.log)"; tail -20 /tmp/perk-p2t7-ts.log
fi

echo "== Check 8: contract amendments present =="
if grep -q 'Review loop (`/address`, P2.T7)' shared/contracts.md \
    && grep -q 'Authored (P2.T7 — the `/address` review loop)' shared/contracts.md; then
  pass "contracts §8.3 Review loop + §8.4 authored resolve_review_threads"
else
  bad "contracts amendments missing"
fi

echo "== Check 9: doctor offline-clean =="
if uv run python - <<'PY' >/tmp/perk-p2t7-doctor.log 2>&1; then
import tempfile
from pathlib import Path
from perk.init import run_init
from perk.doctor import run_doctor

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    run_init(root, verify=False)
    checks = {c.name: c for c in run_doctor(root, verify=False).checks}
    assert checks["subagent-engine"].status == "ok", checks["subagent-engine"].status
    assert "review-classifier" in checks["subagent-engine"].detail or "perk.*" in checks["subagent-engine"].detail
print("ok")
PY
  pass "doctor subagent-engine ok with the benign-stray note"
else
  bad "doctor offline check failed"; tail -20 /tmp/perk-p2t7-doctor.log
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T7 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T7 hard gate: FAILURES\033[0m\n"; fi
exit $fail
