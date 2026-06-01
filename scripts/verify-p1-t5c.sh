#!/usr/bin/env bash
# Phase 1 · Turn 5c — hard-gate verification (`perk resume`).
# Checks from docs/planning/phase-1-turn-5.md §1, run FULLY OFFLINE (no gh, no LLM):
#   7. the pure stage-resolution matrix holds (planned->implement, open->submit,
#      merged+pending->learn, merged->none) and reconstruct_plan_ref is well-formed
#   8. exit-code discipline: not-a-repo -> 2; invalid plan id -> 1; plan-not-found -> 1
#      (plan-not-found via the CliRunner suite, get_plan stubbed)
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

py_run() { uv run --project "$ROOT" python "$@"; }

echo "== Check 7: pure resolution matrix + reconstruct (offline) =="
if py_run -c "
import sys
from perk import github, resume

def pr(state):
    return github.PullRequest(number=55, url='u', is_draft=False, state=state, existed=True)
def st(header=None, p=None):
    return github.PlanState(number=7, url='u/7', title='T', header=header or {}, pr=p)

cases = [
    (resume.resolve_resume_stage(st(header={'lifecycle_stage':'planned'}), has_pending_learn=False), 'implement'),
    (resume.resolve_resume_stage(st(p=pr('OPEN')), has_pending_learn=False), 'submit'),
    (resume.resolve_resume_stage(st(p=pr('MERGED')), has_pending_learn=True), 'learn'),
    (resume.resolve_resume_stage(st(p=pr('MERGED')), has_pending_learn=False), None),
]
ref = resume.reconstruct_plan_ref(st())
ok = all(a == b for a, b in cases) and ref['provider']=='github' and ref['pr_id']=='7' and ref['labels']==['perk:plan']
sys.exit(0 if ok else 1)"; then
  pass "resolve_resume_stage matrix + reconstruct_plan_ref correct"
else
  bad "resolution matrix / reconstruct wrong"
fi

echo "== Check 8: exit-code discipline (CliRunner suite + not-a-repo) =="
N="$(mktemp -d)"
rc_norepo=$( cd "$N" && uv run --project "$ROOT" perk resume 7 --dry-run --json >/dev/null 2>&1; echo $? )
rm -rf "$N"
if [ "$rc_norepo" = 2 ] && py_run -m pytest tests/test_resume.py -q >/tmp/perk-p1t5c-pytest.log 2>&1; then
  pass "not-a-repo -> exit 2; resume CliRunner suite green ($(grep -Eo '[0-9]+ passed' /tmp/perk-p1t5c-pytest.log | head -1))"
else
  bad "exit code / suite failed (norepo=$rc_norepo; see /tmp/perk-p1t5c-pytest.log)"; tail -20 /tmp/perk-p1t5c-pytest.log
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP1.T5c hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP1.T5c hard gate: FAILURES\033[0m\n"; fi
exit $fail
