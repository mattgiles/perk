#!/usr/bin/env bash
# Phase 2 · Turn 8c — hard-gate verification (the CLI plumbing slice). Checks from
# docs/planning/phase-2-turn-8.md, run FULLY OFFLINE (no gh, no LLM, no network):
#   1. Python suite green (launch / cli-stages / implement / resume)
#   2. resolve_target + Target/RemoteTarget present in launch.py (the hard raise is gone)
#   3. registry cold_remote: implement+address true, the other five false; self-check passes
#   4. --remote help text reconciled in the three launchers
#   5. contract amendments present (cli-vs-pi §4.5 note + the doors constraint)
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

echo "== Check 1: Python suite green (launch/cli-stages/implement/resume) =="
if uv run pytest tests/test_launch.py tests/test_cli_stages.py tests/test_implement_cmd.py \
    tests/test_resume.py -q >/tmp/perk-p2t8c-py.log 2>&1; then
  pass "touched python suites green"
else
  bad "python suite failed (see /tmp/perk-p2t8c-py.log)"; tail -25 /tmp/perk-p2t8c-py.log
fi

echo "== Check 2: resolve_target + Target/RemoteTarget; hard raise gone =="
if grep -q 'def resolve_target' perk/launch.py \
    && grep -q 'class RemoteTarget' perk/launch.py \
    && ! grep -q 'remote target is Phase 3' perk/launch.py; then
  pass "resolve_target + RemoteTarget present; the hard 'remote is Phase 3' raise is gone"
else
  bad "launch resolver missing or the hard raise still present"
fi

echo "== Check 3: registry cold_remote flips + self-check =="
if uv run perk registry check >/dev/null 2>&1 && uv run python - <<'PY' >/tmp/perk-p2t8c-reg.log 2>&1; then
from perk.registry import load_registry
stages = {s.id: s for s in load_registry().stages}
remote_on = {sid for sid, s in stages.items() if s.doors.get("cold_remote") is True}
assert remote_on == {"implement", "address"}, remote_on
print("ok")
PY
  pass "cold_remote true on implement+address only; registry self-check passes"
else
  bad "registry cold_remote flips wrong / self-check failed"; tail -10 /tmp/perk-p2t8c-reg.log
fi

echo "== Check 4: --remote help text reconciled =="
if ! grep -rq 'Phase 3; currently blocked' perk/cli/stages.py perk/cli/commands/implement_cmd.py \
       perk/cli/commands/resume_cmd.py \
   && grep -q 'driven by the Phase-3 worker' perk/cli/stages.py; then
  pass "--remote help text updated in the three launchers"
else
  bad "--remote help text not reconciled"
fi

echo "== Check 5: contract amendments present =="
if grep -q 'P2.T8c' shared/contracts.md && grep -q 'P2.T8c' shared/registry.yaml; then
  pass "contracts §4.5/doors note + registry comment record the P2.T8c flip"
else
  bad "P2.T8c contract/registry amendments missing"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T8c hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T8c hard gate: FAILURES\033[0m\n"; fi
exit $fail
