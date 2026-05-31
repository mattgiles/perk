#!/usr/bin/env bash
# Phase 1 · Turn 1 — hard-gate verification (the session test harness).
# Checks from docs/planning/phase-1-turn-1.md §1/§8:
#   1. the live lifecycle suite passes OFFLINE (all provider API keys unset)
#   2. the existing extension unit suite still passes (live tests complement, not replace)
#   3. the harness + live test files exist
#   4. the harness drives a REAL bound session (greps createAgentSession + bindExtensions)
#   5. the dev-only harness is excluded from the published tarball (npm files)
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

# Offline proof: blind node to any real provider keys for the lifecycle run.
node_offline() { env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY node "$@"; }

echo "== Check 1: live lifecycle suite passes OFFLINE =="
if node_offline --test extension/sessionLifecycle.test.ts >/tmp/perk-p1t1-live.log 2>&1; then
  pass "sessionLifecycle.test.ts ($(grep -E '^# pass' /tmp/perk-p1t1-live.log | head -1 | tr -d '#'))"
else
  bad "live suite failed offline (see /tmp/perk-p1t1-live.log)"; tail -20 /tmp/perk-p1t1-live.log
fi

echo "== Check 2: existing extension unit suite still passes =="
if node --test extension/*.test.ts >/tmp/perk-p1t1-all.log 2>&1; then
  pass "all extension tests green ($(grep -E '^# pass' /tmp/perk-p1t1-all.log | head -1 | tr -d '#'))"
else
  bad "extension unit suite regressed (see /tmp/perk-p1t1-all.log)"
fi

echo "== Check 3: harness + live test files exist =="
if [ -f extension/testing/harness.ts ] && [ -f extension/sessionLifecycle.test.ts ]; then
  pass "extension/testing/harness.ts + extension/sessionLifecycle.test.ts present"
else
  bad "harness or live test file missing"
fi

echo "== Check 4: harness drives a REAL bound session =="
if grep -q "createAgentSession" extension/testing/harness.ts \
   && grep -q "bindExtensions(" extension/testing/harness.ts; then
  pass "harness uses createAgentSession + bindExtensions (real session, not a re-import)"
else
  bad "harness does not bind a real session"
fi

echo "== Check 5: dev-only harness excluded from the published tarball =="
if npm pack --dry-run --json 2>/dev/null | node -e "
const fs=require('fs');
let data='';process.stdin.on('data',d=>data+=d).on('end',()=>{
  const files=(JSON.parse(data)[0].files||[]).map(f=>f.path);
  const leaked=files.filter(f=>f.startsWith('extension/testing/')||f.endsWith('.test.ts'));
  process.exit(leaked.length===0?0:1);
});"; then
  pass "no extension/testing/ or *.test.ts in the npm tarball"
else
  bad "dev-only files would be published"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP1.T1 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP1.T1 hard gate: FAILURES\033[0m\n"; fi
exit $fail
