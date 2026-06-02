#!/usr/bin/env bash
# Phase 1 · Turn 3b — plan-save robustness (a corrective turn; dogfood-surfaced).
# The P1.T6 dogfood saved a conversational message as the "plan" and a TOML `# comment` became
# the title. This gate locks the three fixes (run FULLY OFFLINE):
#   1. derive_title ignores `#` inside fenced code blocks (the bad-title root cause) + prefers a real H1
#   2. the warm `/plan-save` refuses while plan mode is active, and isPlanModeActive reads the
#      borrowed `plan-mode-state` entry (node:test, offline)
#   3. the invented `<proposed_plan>` convention is gone from the code + skill
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }
py_run() { uv run --project "$ROOT" python "$@"; }
node_offline() { env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY node "$@"; }

echo "== Check 1: derive_title ignores fenced '#' and prefers a real H1 =="
if py_run -c "
from perk.plan import derive_title
import sys
fenced = 'intro\n\n\`\`\`toml\n# Add only if you want format-on-commit too:\nid = 1\n\`\`\`\n'
ok = (derive_title(fenced) == 'perk plan'                      # the dogfood failure -> fallback
      and derive_title('# Real Title\n\nbody') == 'Real Title' # a real H1 still wins
      and derive_title('# H1\n\`\`\`\n# fenced\n\`\`\`\n') == 'H1')
sys.exit(0 if ok else 1)"; then
  pass "fenced '#' is never the title; a real leading H1 is"
else
  bad "derive_title hardening missing"
fi

echo "== Check 2: plan-save fail-fast guard + isPlanModeActive (node, offline) =="
if node_offline --test extension/planSave.test.ts >/tmp/perk-p1t3b-node.log 2>&1; then
  pass "planSave suite green ($(grep -Eo '# pass [0-9]+' /tmp/perk-p1t3b-node.log | head -1))"
else
  bad "planSave node suite failed (see /tmp/perk-p1t3b-node.log)"; tail -20 /tmp/perk-p1t3b-node.log
fi

echo "== Check 3: the invented <proposed_plan> convention is gone =="
if ! grep -rq "proposed_plan" extension/planSave.ts skills/perk-plan/SKILL.md 2>/dev/null; then
  pass "no <proposed_plan> in planSave.ts or the perk-plan skill"
else
  bad "<proposed_plan> still referenced as a convention"
fi

echo "== Check 4: derive_title unit suite =="
if py_run -m pytest tests/test_plan.py -q >/tmp/perk-p1t3b-pytest.log 2>&1; then
  pass "pytest green ($(grep -Eo '[0-9]+ passed' /tmp/perk-p1t3b-pytest.log | head -1))"
else
  bad "pytest failed (see /tmp/perk-p1t3b-pytest.log)"; tail -20 /tmp/perk-p1t3b-pytest.log
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP1.T3b hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP1.T3b hard gate: FAILURES\033[0m\n"; fi
exit $fail
