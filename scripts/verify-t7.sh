#!/usr/bin/env bash
# Phase 0 · Turn 7 — the dogfood-gate preconditions (uv-only).
# The *interactive* proof (a human launching `pi`, observing read-only plan mode + the live todo
# overlay, authoring the Phase-1 plan) cannot run in CI; it is recorded in docs/planning/phase-0-gate.md.
# This script asserts the *automatable preconditions* that make that demonstration possible.
# Checks from docs/planning/phase-0-turn-7.md §7:
#   1. scaffold + healthy: fresh repo -> init -> doctor --json healthy, exit 0
#   2. borrowed substrate wired: all four borrowed packages + @perk/pi present; settings-wiring ok
#   3. pi launchable: `pi` on PATH; `perk plan --dry-run` resolves a primed launch (side-effect-free)
#   4. dogfood artifact: docs/phase-1-plan.md present + non-trivial
#   5. gate record: docs/planning/phase-0-gate.md present + asserts the gate met
#   6. T7 code change is green (the doctor no-silent-pass + is_self_repo rename)
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

perk_in() { ( cd "$1" && shift && uv run --project "$ROOT" perk "$@" ); }
py_run()  { uv run --project "$ROOT" python "$@"; }

W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
( cd "$W" && git init -q && uv run --project "$ROOT" perk init >/dev/null 2>&1 )

echo "== Check 1: scaffold + healthy =="
J="$(perk_in "$W" doctor --json 2>/dev/null)"; rc=$(perk_in "$W" doctor >/dev/null 2>&1; echo $?)
if [ "$rc" = 0 ] && echo "$J" | py_run -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['healthy'] and d['summary']['failed']==0 else 1)"; then
  pass "fresh repo -> init -> doctor healthy (exit 0)"
else
  bad "scaffold not healthy (rc=$rc): $J"
fi

echo "== Check 2: borrowed substrate wired =="
if py_run -c "
import json
pkgs = json.load(open('$W/.pi/settings.json'))['packages']
need = ['npm:@tombell/pi-plan', 'npm:@juicesharp/rpiv-todo', 'npm:@tombell/pi-diff', 'npm:@tombell/pi-status']
missing = [p for p in need if p not in pkgs]
self = [p for p in pkgs if p.startswith('npm:@perk/pi') or p == '..' or p.startswith('..')]
assert not missing, f'missing {missing}'
assert self, 'no @perk/pi self entry'
" 2>/dev/null \
   && echo "$J" | py_run -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if next(c for c in d['checks'] if c['name']=='settings-wiring')['status']=='ok' else 1)"; then
  pass "all four borrowed packages + @perk/pi present; settings-wiring ok"
else
  bad "borrowed substrate not fully wired"
fi

echo "== Check 3: pi launchable =="
DRY="$(perk_in "$W" plan --dry-run 2>/dev/null)"
if command -v pi >/dev/null 2>&1 \
   && echo "$DRY" | py_run -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['success'] and d['stage']=='plan' and d['argv'][0]=='pi' else 1)" \
   && [ ! -d "$W/.worktrees" ]; then
  pass "pi on PATH; 'perk plan --dry-run' resolves a primed launch with no side effects"
else
  bad "pi not launchable / dry-run not side-effect-free: $DRY"
fi

echo "== Check 4: dogfood artifact (Phase-1 plan) =="
P="docs/planning/phase-1-plan.md"
if [ -f "$P" ] && grep -qiE "phase 1" "$P" && grep -qiE "acceptance gate" "$P" && [ "$(wc -l < "$P")" -gt 40 ]; then
  pass "docs/planning/phase-1-plan.md present + non-trivial (objective + gate + decomposition)"
else
  bad "Phase-1 plan missing or trivial"
fi

echo "== Check 5: gate record =="
G="docs/planning/phase-0-gate.md"
if [ -f "$G" ] && grep -qiE "Phase 0 gate met|gate.{0,3}met" "$G"; then
  pass "docs/planning/phase-0-gate.md present + asserts the gate met"
else
  bad "gate record missing or does not assert the gate"
fi

echo "== Check 6: T7 code change is green =="
if py_run -m pytest tests/test_doctor.py -q >/tmp/perk-t7-pytest.log 2>&1; then
  pass "test_doctor ($(grep -Eo '[0-9]+ passed' /tmp/perk-t7-pytest.log | head -1)); no-silent-pass + is_self_repo green"
else
  bad "test_doctor failed (see /tmp/perk-t7-pytest.log)"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mT7 dogfood-gate preconditions: ALL PASS\033[0m\n"; else printf "\033[31mT7 dogfood-gate preconditions: FAILURES\033[0m\n"; fi
exit $fail
