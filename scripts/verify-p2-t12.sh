#!/usr/bin/env bash
# Phase 2 · Turn 12 — the Phase-2 dogfood-gate preconditions (offline, uv-only).
# The *live* dogfood proof (an operator driving perk's full deepened workflow on perk's own repo:
# objective -> factory-emitted plan -> CI-executor iteration -> submit/ready -> /address -> land +
# node-done + reconcile -> learn) needs live GitHub + a model and cannot run in CI; it is recorded
# in docs/planning/phase-2-gate.md §"the live run". This script asserts the *automatable
# preconditions* (no network, no GitHub, no model). Checks from docs/planning/phase-2-turn-12.md §4:
#   1. scaffold + healthy: fresh repo -> init -> doctor --json healthy, exit 0
#   2. rpiv-todo retired: not in scaffolded packages nor in perk.init.BORROWED_PACKAGES;
#      surviving borrowed set + self entry present; settings-wiring ok
#   3. both new stages filled + self-check passes: `perk registry check` exit 0; address +
#      objective-plan have non-empty requires/reads/writes + complete doors; graph shape holds
#   4. checkpoints own implement-progress: extension/checkpoints.ts exports CHECKPOINT_TYPE
#   5. gate record present + asserts the gate met
#   6. retirement test green: tests/test_init_idempotent.py passes
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

echo "== Check 2: rpiv-todo retired =="
if py_run -c "
import json
from perk.init import BORROWED_PACKAGES
pkgs = json.load(open('$W/.pi/settings.json'))['packages']
assert 'npm:@juicesharp/rpiv-todo' not in pkgs, 'rpiv-todo still in scaffolded packages'
assert 'npm:@juicesharp/rpiv-todo' not in BORROWED_PACKAGES, 'rpiv-todo still in BORROWED_PACKAGES'
need = ['npm:@tombell/pi-diff', 'npm:@tombell/pi-status', 'npm:pi-subagents']
missing = [p for p in need if p not in pkgs]
assert not missing, f'surviving borrowed set missing {missing}'
self = [p for p in pkgs if p.startswith('npm:@perk/pi') or p == '..' or p.startswith('..')]
assert self, 'no @perk/pi self entry'
" 2>/dev/null \
   && echo "$J" | py_run -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if next(c for c in d['checks'] if c['name']=='settings-wiring')['status']=='ok' else 1)"; then
  pass "rpiv-todo absent (file + BORROWED_PACKAGES); surviving borrows + self present; settings-wiring ok"
else
  bad "rpiv-todo not cleanly retired / borrowed substrate not wired"
fi

echo "== Check 3: both new stages filled + self-check passes =="
if perk_in "$W" registry check >/dev/null 2>&1 \
   && py_run -c "
import yaml
r = yaml.safe_load(open('$ROOT/shared/registry.yaml'))
st = {s['id']: s for s in r['stages']}
for name in ('address', 'objective-plan'):
    s = st[name]
    for f in ('requires', 'reads', 'writes'):
        assert s.get(f), f'{name}.{f} empty'
    doors = s.get('doors') or {}
    for k in ('warm', 'cold_local', 'cold_remote'):
        assert k in doors, f'{name}.doors missing {k}'
op = st['objective-plan']
assert op['predecessors'] == [], 'objective-plan.predecessors not empty'
assert 'plan' in op['successors'], 'plan not in objective-plan.successors'
ad = st['address']
assert 'submit' in ad['predecessors'] and 'land' in ad['successors'], 'address not between submit and land'
"; then
  pass "perk registry check exit 0; address + objective-plan I/O + doors filled; graph shape holds"
else
  bad "registry self-check failed or new stages not fully filled"
fi

echo "== Check 4: checkpoints own implement-progress =="
C="extension/checkpoints.ts"
if [ -f "$C" ] && grep -qE 'export const CHECKPOINT_TYPE = "perk:checkpoint"' "$C"; then
  pass "extension/checkpoints.ts exports the perk:checkpoint entry (rpiv-todo's replacement)"
else
  bad "checkpoints.ts missing or does not export CHECKPOINT_TYPE"
fi

echo "== Check 5: gate record =="
G="docs/planning/phase-2-gate.md"
if [ -f "$G" ] && grep -qiE "Phase 2 gate met|gate.{0,3}met" "$G"; then
  pass "docs/planning/phase-2-gate.md present + asserts the gate met"
else
  bad "gate record missing or does not assert the gate"
fi

echo "== Check 6: retirement test green =="
if py_run -m pytest tests/test_init_idempotent.py -q >/tmp/perk-p2t12-pytest.log 2>&1; then
  pass "test_init_idempotent ($(grep -Eo '[0-9]+ passed' /tmp/perk-p2t12-pytest.log | head -1)); rpiv-todo-not-in-packages green"
else
  bad "test_init_idempotent failed (see /tmp/perk-p2t12-pytest.log)"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T12 dogfood-gate preconditions: ALL PASS\033[0m\n"; else printf "\033[31mP2.T12 dogfood-gate preconditions: FAILURES\033[0m\n"; fi
exit $fail
