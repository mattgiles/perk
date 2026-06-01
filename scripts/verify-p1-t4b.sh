#!/usr/bin/env bash
# Phase 1 · Turn 4b — hard-gate verification (the session-lifecycle gates).
# Checks from docs/planning/phase-1-turn-4.md §1, run FULLY OFFLINE (real git, no LLM/network):
#   5. the lifecycle-gate live suite passes: dirty+active -> cancel; clean -> allow;
#      no-active-workflow -> allow; headless+dirty -> cancel; /implement guard both ways
#   6. the gate + guard are actually wired into the extension (index.ts)
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

node_offline() { env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY node "$@"; }

echo "== Check 5: lifecycle-gate live suite (dirty/clean/scope/headless + /implement) =="
if node_offline --test extension/lifecycleGates.test.ts >/tmp/perk-p1t4b-node.log 2>&1; then
  pass "extension/lifecycleGates.test.ts green offline ($(grep -E '^# pass' /tmp/perk-p1t4b-node.log | head -1))"
else
  bad "lifecycleGates.test.ts failed (see /tmp/perk-p1t4b-node.log)"; tail -25 /tmp/perk-p1t4b-node.log
fi

echo "== Check 6: the gate + guard are wired into the extension =="
if grep -q "registerLifecycleGates(pi)" extension/index.ts \
   && grep -q 'session_before_fork' extension/lifecycleGates.ts \
   && grep -q 'session_before_switch' extension/lifecycleGates.ts; then
  pass "index.ts calls registerLifecycleGates; both before_* hooks registered"
else
  bad "lifecycle gates not wired into index.ts"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP1.T4b hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP1.T4b hard gate: FAILURES\033[0m\n"; fi
exit $fail
