#!/usr/bin/env bash
# Phase 2 · Turn 2c — hard-gate verification (perk-owned checkpoints).
# All checks run FULLY OFFLINE (no LLM, no network):
#   1. checkpoints.test.ts green (pure step/[DONE:n] helpers + scan-after-marker rebuild +
#      seed-from-`## Steps`, inert-on-prose, session_tree rebuild, headless /checkpoints)
#   2. checkpoints wired: registerCheckpoints in index.ts; a dedicated `perk:checkpoint` entry (D3);
#      rebuilt on session_start AND session_tree; advanced on turn_end
#   3. the `perk-plan` skill documents the optional `## Steps` list (so checkpoints have a format)
#   4. the data source is WIRED end-to-end: the Python cold door materializes the plan body into
#      the worktree's `cache.plan` (`.pi/workflow/plan.md`) that the TS reader seeds from
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

echo "== Check 4: the plan-body data source is wired end-to-end (cold door -> cache.plan) =="
if grep -q '_materialize_plan_body' perk/launch.py \
   && grep -q 'def get_plan_body' perk/github.py \
   && grep -q 'def write_plan_body' perk/cache.py \
   && grep -q 'def extract_plan_body' perk/plan.py \
   && grep -q 'readPlanBody(ctx.cwd)' extension/checkpoints.ts; then
  pass "launch materializes the plan body into cache.plan; checkpoints.ts seeds from it"
else
  bad "the plan-body data source is not wired (checkpoints would never seed in production)"
fi
if uv run pytest tests/test_launch.py -k plan_body -q >/tmp/perk-p2t2c-py.log 2>&1; then
  pass "launch plan-body materialization tests green ($(grep -Eo '[0-9]+ passed' /tmp/perk-p2t2c-py.log | head -1))"
else
  bad "launch plan-body tests failed (see /tmp/perk-p2t2c-py.log)"; tail -20 /tmp/perk-p2t2c-py.log
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T2c hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T2c hard gate: FAILURES\033[0m\n"; fi
exit $fail
