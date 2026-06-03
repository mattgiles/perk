#!/usr/bin/env bash
# Phase 2 · Turn 11 — hard-gate verification (objective reconciliation after landing). Checks from
# docs/planning/phase-2-turn-11.md, run FULLY OFFLINE (no gh, no LLM, no network):
#   1. touched Python suites green
#   2. perk objective reconcile --help present
#   3. _reconcile_objective_on_land fail-open asserted; objective in pr-land --json
#   4. nodes_for_pr + replace_reconcilable_section present
#   5. extension tests green
#   6. skills/perk-objective-reconcile/SKILL.md present (section-boundary + never-delegate)
#   7. /objective-reconcile + reconcile_objective wired
#   8. registry land I/O includes github.objective
#   9. contracts §8.3/§8.4 P2.T11 amendments present + no stale "deferred to T11" in §8.4
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

echo "== Check 1: Python suites green =="
if uv run pytest tests/test_objective.py tests/test_github.py tests/test_pr_land.py \
    tests/test_objective_cmd.py tests/test_registry.py -q >/tmp/perk-p2t11-py.log 2>&1; then
  pass "touched python suites green"
else
  bad "python suite failed (see /tmp/perk-p2t11-py.log)"; tail -25 /tmp/perk-p2t11-py.log
fi

echo "== Check 2: perk objective reconcile --help =="
if uv run perk objective reconcile --help 2>/dev/null | grep -q "Reconcilable"; then
  pass "perk objective reconcile --help present"
else
  bad "perk objective reconcile --help missing"
fi

echo "== Check 3: land mechanical node-done fail-open + objective in --json =="
if grep -q 'def _reconcile_objective_on_land' perk/cli/commands/pr_land_cmd.py \
    && grep -q 'fail-open' perk/cli/commands/pr_land_cmd.py \
    && grep -q '"objective":' perk/cli/commands/pr_land_cmd.py \
    && uv run python -c "
from pathlib import Path
from perk.cli.commands.pr_land_cmd import _reconcile_objective_on_land, ObjectiveLandUpdate
from perk import github
# a gateway raise inside reconcile must NOT propagate (fail-open).
def boom(**k): raise github.GitHubError('boom')
github.get_objective = boom
out = _reconcile_objective_on_land(plan_ref={'objective_id':'5','pr_id':'7'}, repo_root=Path('.'))
assert out.nodes_marked == () and out.skipped_reason.startswith('error:')
assert _reconcile_objective_on_land(plan_ref={'objective_id':None,'pr_id':'7'}, repo_root=Path('.')) \
    == ObjectiveLandUpdate(None, (), 'no_objective_link')
" 2>/dev/null; then
  pass "_reconcile_objective_on_land fail-open + objective in --json"
else
  bad "land mechanical node-done not fail-open / not surfaced"
fi

echo "== Check 4: pure helpers present =="
if grep -q 'def nodes_for_pr' perk/objective.py \
    && grep -q 'def replace_reconcilable_section' perk/objective.py \
    && grep -q 'OBJECTIVE_RECONCILABLE_MARKER_START' perk/objective.py \
    && grep -q 'def update_objective_body' perk/github.py; then
  pass "nodes_for_pr + replace_reconcilable_section + update_objective_body present"
else
  bad "pure helpers / gateway op missing"
fi

echo "== Check 5: extension tests green =="
if node --test extension/objectivePlan.test.ts extension/land.test.ts \
    >/tmp/perk-p2t11-ts.log 2>&1; then
  pass "objectivePlan.test.ts + land.test.ts green"
else
  bad "extension tests failed (see /tmp/perk-p2t11-ts.log)"; tail -20 /tmp/perk-p2t11-ts.log
fi

echo "== Check 6: perk-objective-reconcile skill present =="
if [ -f skills/perk-objective-reconcile/SKILL.md ] \
    && grep -qi 'Mechanical' skills/perk-objective-reconcile/SKILL.md \
    && grep -qi 'Reconcilable' skills/perk-objective-reconcile/SKILL.md \
    && grep -qi 'Immutable' skills/perk-objective-reconcile/SKILL.md \
    && grep -qi 'never-delegate' skills/perk-objective-reconcile/SKILL.md; then
  pass "skills/perk-objective-reconcile/SKILL.md present (section-boundary + never-delegate)"
else
  bad "perk-objective-reconcile skill missing or incomplete"
fi

echo "== Check 7: /objective-reconcile + reconcile_objective wired =="
if grep -q '"objective-reconcile"' extension/objectivePlan.ts \
    && grep -q 'reconcile_objective' extension/objectivePlan.ts \
    && grep -q 'resolveReconcileObjective' extension/objectivePlan.ts \
    && grep -q 'objective-reconcile #' extension/land.ts; then
  pass "/objective-reconcile + reconcile_objective + land nudge wired"
else
  bad "warm reconcile surface not fully wired"
fi

echo "== Check 8: registry land I/O includes github.objective =="
if uv run python -c "
from perk.registry import load_registry
land = {s.id: s for s in load_registry().stages}['land']
assert 'github.objective' in land.reads and 'github.objective' in land.writes
" 2>/dev/null; then
  pass "land reads + writes include github.objective"
else
  bad "land I/O does not include github.objective"
fi

echo "== Check 9: contract amendments present + no stale deferral =="
if grep -q 'Objective reconciliation after landing (P2.T11)' shared/contracts.md \
    && grep -q 'Authored (P2.T11' shared/contracts.md \
    && ! grep -q 'deferred to T11' shared/contracts.md; then
  pass "contracts §8.3 + §8.4 P2.T11 amendments present; no stale 'deferred to T11'"
else
  bad "contracts P2.T11 amendments missing or stale 'deferred to T11' remains"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T11 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T11 hard gate: FAILURES\033[0m\n"; fi
exit $fail
