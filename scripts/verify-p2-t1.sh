#!/usr/bin/env bash
# Phase 2 · Turn 1 — hard-gate verification (the tool-gating primitive / keystone).
# Checks from docs/planning/phase-2-turn-1.md §5, run FULLY OFFLINE (no LLM, no network):
#   1. toolGating.test.ts green offline (pure policy matrix + the live read-only round-trip:
#      gate on -> blocked write/edit -> blocked unsafe bash -> safe bash allowed -> off -> write ok)
#   2. the primitive is wired into index.ts (registerToolGating) and synced on BOTH
#      session_start AND session_tree
#   3. shared/contracts.md §8.3 documents mode as a structural tool gate
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }
node_offline() { env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY node "$@"; }

echo "== Check 1: toolGating.test.ts green offline =="
if node_offline --test extension/toolGating.test.ts >/tmp/perk-p2t1-node.log 2>&1; then
  pass "toolGating.test.ts green offline ($(grep -E '^# pass' /tmp/perk-p2t1-node.log | head -1))"
else
  bad "toolGating suite failed (see /tmp/perk-p2t1-node.log)"; tail -25 /tmp/perk-p2t1-node.log
fi

echo "== Check 2: primitive wired + synced on session_start AND session_tree =="
if grep -q 'registerToolGating(pi)' extension/index.ts \
   && grep -q 'export function registerToolGating' extension/toolGating.ts \
   && [ "$(grep -c 'gating.syncFromState' extension/index.ts)" -ge 2 ]; then
  pass "registerToolGating wired; syncFromState called on both rebuild points"
else
  bad "tool-gating not wired into index.ts on both session_start and session_tree"
fi

echo "== Check 3: contracts §8.3 documents mode as a structural tool gate =="
if grep -q 'Tool-gating (P2.T1)' shared/contracts.md \
   && grep -q 'structurally gates tools' shared/contracts.md; then
  pass "contracts §8.3 amended (mode structurally gates tools)"
else
  bad "contracts §8.3 missing the tool-gating amendment"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T1 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T1 hard gate: FAILURES\033[0m\n"; fi
exit $fail
