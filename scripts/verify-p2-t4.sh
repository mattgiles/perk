#!/usr/bin/env bash
# Phase 2 · Turn 4 — hard-gate verification (in-process read-only SDK session; context-isolation
# primitive #1). Checks from docs/planning/phase-2-turn-4.md, run FULLY OFFLINE (no LLM, no
# network — API-key envs unset):
#   1. readOnlySession.test.ts green offline (pure cap/extract helpers + the structural read-only
#      proof via getActiveToolNames with no prompt + the double-delivery/verify/fail-closed handoff)
#   2. createReadOnlySession uses createAgentSession with the read-only allowlist + the loader
#      lock-down flags; SDK_READ_ONLY_TOOLS excludes bash/edit/write
#   3. shared/contracts.md documents the "In-process read-only child sessions (P2.T4)" amendment
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }
node_offline() { env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY node "$@"; }

echo "== Check 1: readOnlySession.test.ts green offline =="
if node_offline --test extension/readOnlySession.test.ts >/tmp/perk-p2t4-node.log 2>&1; then
  pass "readOnlySession.test.ts green offline ($(grep -E '^# pass' /tmp/perk-p2t4-node.log | head -1))"
else
  bad "readOnlySession suite failed (see /tmp/perk-p2t4-node.log)"; tail -25 /tmp/perk-p2t4-node.log
fi

echo "== Check 2: createAgentSession + read-only allowlist + loader lock-down =="
F=extension/readOnlySession.ts
if grep -q 'createAgentSession' "$F" \
   && grep -q 'SDK_READ_ONLY_TOOLS' "$F" \
   && grep -q 'noExtensions' "$F" \
   && grep -q 'loader.reload' "$F"; then
  pass "createReadOnlySession wires createAgentSession + lock-down flags + loader.reload"
else
  bad "readOnlySession.ts missing createAgentSession / SDK_READ_ONLY_TOOLS / noExtensions / loader.reload"
fi
if node_offline --input-type=module -e '
  import { SDK_READ_ONLY_TOOLS } from "./extension/readOnlySession.ts";
  for (const banned of ["bash","edit","write"]) {
    if (SDK_READ_ONLY_TOOLS.includes(banned)) { console.error("includes "+banned); process.exit(1); }
  }
' >/tmp/perk-p2t4-tools.log 2>&1; then
  pass "SDK_READ_ONLY_TOOLS excludes bash/edit/write"
else
  bad "SDK_READ_ONLY_TOOLS must exclude bash/edit/write (see /tmp/perk-p2t4-tools.log)"
fi

echo "== Check 3: contracts amendment present =="
if grep -q 'In-process read-only child sessions (P2.T4)' shared/contracts.md; then
  pass "contracts documents the P2.T4 handoff contract"
else
  bad "contracts missing the 'In-process read-only child sessions (P2.T4)' amendment"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T4 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T4 hard gate: FAILURES\033[0m\n"; fi
exit $fail
