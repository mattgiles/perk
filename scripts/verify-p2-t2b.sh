#!/usr/bin/env bash
# Phase 2 · Turn 2b — hard-gate verification (deepen the warm `/implement` path).
# All checks run FULLY OFFLINE (no LLM, no network):
#   1. lifecycleGates.test.ts green (the T4b matrix + the T2b handoff: inside a clean impl worktree
#      `/implement` invokes a seeded ctx.newSession with plan-read priming, output capped; a dirty
#      tree refuses; outside an impl context it points at the cold door)
#   2. the handoff is wired: a `ctx.newSession` lossless fresh-context handoff seeded with the
#      plan-read priming (implementHandoffPrompt), gated manually on a dirty tree
#   3. D2 holds: no extension session API changes cwd — the cross-worktree jump stays the Python
#      cold door's job (the handler calls newSession, NOT a cwd change)
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }
node_offline() { env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY node "$@"; }

echo "== Check 1: lifecycleGates.test.ts green offline =="
if node_offline --test extension/lifecycleGates.test.ts >/tmp/perk-p2t2b-node.log 2>&1; then
  pass "lifecycleGates suite green ($(grep -E '^# pass' /tmp/perk-p2t2b-node.log | head -1))"
else
  bad "lifecycleGates suite failed (see /tmp/perk-p2t2b-node.log)"; tail -25 /tmp/perk-p2t2b-node.log
fi

echo "== Check 2: the in-worktree newSession handoff is wired + dirty-gated =="
if grep -q 'export function implementHandoffPrompt' extension/lifecycleGates.ts \
   && grep -q 'commandCtx.newSession({' extension/lifecycleGates.ts \
   && grep -q 'withSession' extension/lifecycleGates.ts \
   && grep -q 'HANDOFF_DIRTY_MESSAGE' extension/lifecycleGates.ts; then
  pass "/implement offers a seeded newSession handoff, manually gated on a dirty tree"
else
  bad "the /implement warm handoff is not wired as expected"
fi

echo "== Check 3: D2 — no cwd change in the extension (cross-worktree stays cold) =="
if ! grep -Eq 'process\.chdir|cwdOverride|chdir\(' extension/lifecycleGates.ts; then
  pass "no cwd mutation in the warm handoff (cross-worktree jump remains the cold door's job)"
else
  bad "the extension attempts to change cwd — D2 violated"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T2b hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T2b hard gate: FAILURES\033[0m\n"; fi
exit $fail
