#!/usr/bin/env bash
# Phase 2 · Turn 2c — hard-gate verification (perk-owned checkpoints).
# All checks run FULLY OFFLINE (no LLM, no network):
#   1. checkpoints.test.ts green (pure step/[DONE:n] helpers + scan-after-marker rebuild +
#      seed-from-`## Steps`, inert-on-prose, session_tree rebuild, headless /checkpoints)
#   2. checkpoints wired: registerCheckpoints in index.ts; a dedicated `perk:checkpoint` entry (D3);
#      rebuilt on session_start AND session_tree; advanced on turn_end
#   3. the `perk-plan` skill documents the optional `## Steps` list (so checkpoints have a format)
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }
node_offline() { env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY node "$@"; }

echo "== Check 1: checkpoints.test.ts green offline =="
if node_offline --test extension/checkpoints.test.ts >/tmp/perk-p2t2c-node.log 2>&1; then
  pass "checkpoints suite green ($(grep -E '^# pass' /tmp/perk-p2t2c-node.log | head -1))"
else
  bad "checkpoints suite failed (see /tmp/perk-p2t2c-node.log)"; tail -25 /tmp/perk-p2t2c-node.log
fi

echo "== Check 2: checkpoints wired (dedicated entry + rebuild points + turn_end) =="
if grep -q 'registerCheckpoints(pi)' extension/index.ts \
   && grep -q 'export function registerCheckpoints' extension/checkpoints.ts \
   && grep -q 'CHECKPOINT_TYPE = "perk:checkpoint"' extension/checkpoints.ts \
   && grep -q 'pi.on("session_start"' extension/checkpoints.ts \
   && grep -q 'pi.on("session_tree"' extension/checkpoints.ts \
   && grep -q 'pi.on("turn_end"' extension/checkpoints.ts; then
  pass "registerCheckpoints wired; perk:checkpoint entry; session_start + session_tree + turn_end"
else
  bad "checkpoints not fully wired"
fi

echo "== Check 3: the perk-plan skill documents the optional `## Steps` list =="
if grep -q '## Steps' skills/perk-plan/SKILL.md \
   && grep -qi 'checkpoint' skills/perk-plan/SKILL.md; then
  pass "perk-plan skill documents `## Steps` as the checkpoint format"
else
  bad "perk-plan skill missing the `## Steps` documentation"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T2c hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T2c hard gate: FAILURES\033[0m\n"; fi
exit $fail
