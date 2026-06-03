#!/usr/bin/env bash
# Phase 2 · Turn 5 — hard-gate verification (the read-only CI executor). Checks from
# docs/planning/phase-2-turn-5.md, run FULLY OFFLINE (no LLM, no network — API-key envs unset):
#   1. ciExecutor.test.ts green offline (pure scope gate + injected-exec runner + route-don't-relay
#      + scratch + fail-closed + harness wiring of the run_ci tool / `/ci` command)
#   2. ciExecutor.ts runs checks via pi.exec + reuses capForModel, and does NOT import the T4
#      session runner (createReadOnlySession / runReadOnlyChild) in the run path
#   3. registerCiExecutor is wired in index.ts
#   4. shared/contracts.md documents the "Read-only CI executor (P2.T5)" amendment
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }
node_offline() { env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY node "$@"; }

echo "== Check 1: ciExecutor.test.ts green offline =="
if node_offline --test extension/ciExecutor.test.ts >/tmp/perk-p2t5-node.log 2>&1; then
  pass "ciExecutor.test.ts green offline ($(grep -E '^# pass' /tmp/perk-p2t5-node.log | head -1))"
else
  bad "ciExecutor suite failed (see /tmp/perk-p2t5-node.log)"; tail -25 /tmp/perk-p2t5-node.log
fi

echo "== Check 2: deterministic exec + reuses capForModel + no T4 session runner =="
F=extension/ciExecutor.ts
if grep -q 'pi.exec' "$F" && grep -q 'capForModel' "$F"; then
  pass "ciExecutor.ts runs checks via pi.exec and reuses capForModel"
else
  bad "ciExecutor.ts must run checks via pi.exec and reuse capForModel"
fi
# grep-absence on the IMPORT line only (the module's prose may name the runner to explain why it
# is NOT used) — the run path must not import the T4 session runner.
if grep -E '^import .* from "\./readOnlySession\.ts"' "$F" | grep -q 'createReadOnlySession\|runReadOnlyChild'; then
  bad "ciExecutor.ts must NOT import the T4 session runner (createReadOnlySession/runReadOnlyChild)"
else
  pass "ciExecutor.ts does not spin a T4 read-only session (deterministic, no LLM turn)"
fi

echo "== Check 3: registerCiExecutor wired in index.ts =="
if grep -q 'registerCiExecutor' extension/index.ts; then
  pass "registerCiExecutor wired in index.ts"
else
  bad "registerCiExecutor not wired in index.ts"
fi

echo "== Check 4: contracts amendment present =="
if grep -q 'Read-only CI executor (P2.T5)' shared/contracts.md; then
  pass "contracts documents the P2.T5 executor"
else
  bad "contracts missing the 'Read-only CI executor (P2.T5)' amendment"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T5 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T5 hard gate: FAILURES\033[0m\n"; fi
exit $fail
