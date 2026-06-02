#!/usr/bin/env bash
# Phase 2 · Turn 2a — hard-gate verification (perk-owned plan mode; retire @tombell/pi-plan).
# All checks run FULLY OFFLINE (no LLM, no network):
#   1. planMode.test.ts + config.test.ts green (/plan round-trip + --plan cold start + plan-context
#      inject/strip; the TOML-subset config overlay + addendum injection)
#   2. perk-owned plan mode wired: registerPlanMode(pi, gating) in index.ts; registerFlag("plan")
#      + a Ctrl+Alt+P shortcut in planMode.ts
#   3. pi-plan retired: no `@tombell/pi-plan` token in extension/, perk/, or .pi/settings.json;
#      isPlanModeActive reads perk's read-only `mode` (not the `plan-mode-state` entry)
#   4. D1a: the `/plan-save` command auto-exits the gate on success; the plan_save tool does NOT
#      (it is structurally unreachable while read-only)
#   5. launch.py plan-stage continuity: the launcher drives read-only via the handoff `mode`, not a
#      `--plan` flag (removing pi-plan removes the flag's only prior owner with no launcher reliance)
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }
node_offline() { env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY node "$@"; }

echo "== Check 1: planMode.test.ts + config.test.ts green offline =="
if node_offline --test extension/planMode.test.ts extension/config.test.ts >/tmp/perk-p2t2a-node.log 2>&1; then
  pass "planMode + config suites green ($(grep -E '^# pass' /tmp/perk-p2t2a-node.log | head -1))"
else
  bad "planMode/config suite failed (see /tmp/perk-p2t2a-node.log)"; tail -25 /tmp/perk-p2t2a-node.log
fi

echo "== Check 2: perk-owned plan mode wired (command + flag + shortcut) =="
if grep -q 'registerPlanMode(pi, gating)' extension/index.ts \
   && grep -q 'export function registerPlanMode' extension/planMode.ts \
   && grep -q 'registerFlag("plan"' extension/planMode.ts \
   && grep -q 'registerCommand("plan"' extension/planMode.ts \
   && grep -q 'Key.ctrlAlt("p")' extension/planMode.ts; then
  pass "registerPlanMode wired; /plan command + --plan flag + Ctrl+Alt+P shortcut registered"
else
  bad "perk-owned plan mode not fully wired (command/flag/shortcut)"
fi

echo "== Check 3: @tombell/pi-plan retired (no package spec / import) =="
# The retired package must not appear as a package spec (settings/init) or an import anywhere —
# narrative mentions of the retirement in comments are fine.
if ! grep -rq '"npm:@tombell/pi-plan"' .pi/settings.json perk/ \
   && ! grep -rq 'from "@tombell/pi-plan"' extension/ \
   && ! grep -rq "from '@tombell/pi-plan'" extension/; then
  pass "no @tombell/pi-plan package spec or import in settings/init/extension"
else
  bad "@tombell/pi-plan still wired as a package/import"
fi
if grep -q 'rebuildWorkflowState(branch).mode === "read-only"' extension/planSave.ts \
   && ! grep -q 'customType === "plan-mode-state"' extension/planSave.ts; then
  pass "isPlanModeActive reads perk read-only mode (plan-mode-state scan removed)"
else
  bad "isPlanModeActive still couples to the plan-mode-state entry"
fi

echo "== Check 4: D1a — command-path auto-exit, tool path unchanged =="
if grep -q 'gating.exit(ctx)' extension/planSave.ts \
   && grep -q 'wasReadOnly' extension/planSave.ts; then
  pass "/plan-save command exits the gate on a successful save (D1a)"
else
  bad "the /plan-save command does not auto-exit on success"
fi
# The plan_save TOOL must NOT be on the read-only allowlist (structurally unreachable while read-only).
if ! grep -q 'plan_save' <(grep 'READ_ONLY_TOOLS =' extension/toolGating.ts); then
  pass "plan_save is not on READ_ONLY_TOOLS (tool unreachable while read-only — no auto-exit needed)"
else
  bad "plan_save leaked onto the read-only allowlist"
fi

echo "== Check 5: launch.py plan-stage continuity (no --plan reliance) =="
if ! grep -q '\-\-plan' perk/launch.py \
   && grep -q '"mode": stage.mode' perk/launch.py; then
  pass "launcher drives read-only via the handoff mode, not a --plan flag"
else
  bad "launch.py unexpectedly depends on a --plan flag"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T2a hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T2a hard gate: FAILURES\033[0m\n"; fi
exit $fail
