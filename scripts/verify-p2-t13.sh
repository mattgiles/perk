#!/usr/bin/env bash
# Phase 2 · Turn 13 — hard-gate verification (fix `/plan-save` no-op on re-save; cold-door upsert).
# All checks run FULLY OFFLINE (no LLM, no network):
#   1. `perk plan-save --dry-run --json` on a fresh repo reports updated == false (create path)
#   2. test_plan.py + test_github.py + test_plan_save.py green (the upsert primitives + cmd branch)
#   3. github.update_plan_issue / _find_plan_body_comment_id exist; PlanUpdate carries
#      body_updated/title_updated/dry_run (the cold-door upsert API)
#   4. planSave.test.ts green (the warm door surfaces Updated + details.updated)
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }
node_offline() { env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY node "$@"; }

echo "== Check 1: plan-save --dry-run --json reports updated == false (create path) =="
tmp=$(mktemp -d)
(
  cd "$tmp"
  git init -q
  printf '# Demo plan\n\nDo the thing.\n' >plan.md
)
if out=$(cd "$tmp" && uv run --project "$OLDPWD" perk plan-save --plan-file plan.md --dry-run --json 2>/dev/null) \
   && printf '%s' "$out" | uv run python -c \
      'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("updated") is False else 1)'; then
  pass "fresh-repo dry-run reports updated == false"
else
  bad "dry-run --json did not report updated == false (got: ${out:-<none>})"
fi
rm -rf "$tmp"

echo "== Check 2: test_plan.py + test_github.py + test_plan_save.py green =="
if uv run pytest tests/test_plan.py tests/test_github.py tests/test_plan_save.py -q \
     >/tmp/perk-p2t13-pytest.log 2>&1; then
  pass "pytest green ($(grep -E '[0-9]+ passed' /tmp/perk-p2t13-pytest.log | tail -1))"
else
  bad "pytest failed (see /tmp/perk-p2t13-pytest.log)"; tail -25 /tmp/perk-p2t13-pytest.log
fi

echo "== Check 3: cold-door upsert API present (update_plan_issue + finder + PlanUpdate) =="
if uv run python -c '
import dataclasses
from perk import github
assert callable(github.update_plan_issue)
assert callable(github._find_plan_body_comment_id)
names = {f.name for f in dataclasses.fields(github.PlanUpdate)}
assert {"body_updated", "title_updated", "dry_run"} <= names, names
'; then
  pass "update_plan_issue / _find_plan_body_comment_id / PlanUpdate fields present"
else
  bad "the cold-door upsert API is missing or mis-shaped"
fi

echo "== Check 4: planSave.test.ts green offline (warm door surfaces Updated) =="
if node_offline --test extension/planSave.test.ts >/tmp/perk-p2t13-node.log 2>&1; then
  pass "planSave suite green ($(grep -E '^# pass' /tmp/perk-p2t13-node.log | head -1))"
else
  bad "planSave suite failed (see /tmp/perk-p2t13-node.log)"; tail -25 /tmp/perk-p2t13-node.log
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T13 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T13 hard gate: FAILURES\033[0m\n"; fi
exit $fail
