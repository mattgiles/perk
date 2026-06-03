#!/usr/bin/env bash
# Phase 2 · Turn 6 — hard-gate verification (the spawned delegation engine seam). Checks from
# docs/planning/phase-2-turn-6.md, run FULLY OFFLINE (no LLM, no network, no live spawn):
#   1. Python suite green for the touched modules
#   2. Borrow wired in code (npm:pi-subagents + subagent-engine capability)
#   3. Convergence + defs location (a fresh init writes .pi/agents/.gitkeep + the package)
#   4. Standing signal offline-clean (subagent-engine `ok` pointer + subagent-agents `ok`)
#   5. perk's own dogfood converged (.pi/settings.json + .pi/agents/.gitkeep)
#   6. Contracts amendment present
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

echo "== Check 1: Python suite green (init/capabilities/doctor) =="
if uv run pytest tests/test_init_idempotent.py tests/test_capabilities.py tests/test_doctor.py -q \
    >/tmp/perk-p2t6-py.log 2>&1; then
  pass "init/capabilities/doctor suites green"
else
  bad "python suite failed (see /tmp/perk-p2t6-py.log)"; tail -25 /tmp/perk-p2t6-py.log
fi

echo "== Check 2: borrow wired in code =="
if grep -q 'npm:pi-subagents' perk/init.py && grep -q 'subagent-engine' perk/capabilities.py; then
  pass "npm:pi-subagents in BORROWED_PACKAGES + subagent-engine capability declared"
else
  bad "missing npm:pi-subagents wiring or subagent-engine capability"
fi

echo "== Check 3: convergence + defs location =="
if grep -q '_converge_subagent_agents' perk/init.py && grep -q 'subagent-agents' perk/init.py; then
  pass "subagent-agents convergence registered"
else
  bad "_converge_subagent_agents / subagent-agents convergence missing"
fi
if uv run python - <<'PY' >/tmp/perk-p2t6-init.log 2>&1; then
import json, tempfile
from pathlib import Path
from perk.init import run_init

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    assert run_init(root, verify=False).ok
    assert (root / ".pi" / "agents" / ".gitkeep").is_file(), "missing .pi/agents/.gitkeep"
    pkgs = json.loads((root / ".pi" / "settings.json").read_text())["packages"]
    assert "npm:pi-subagents" in pkgs, "npm:pi-subagents not written"
print("ok")
PY
  pass "fresh init writes .pi/agents/.gitkeep + npm:pi-subagents"
else
  bad "fresh-init convergence check failed"; tail -20 /tmp/perk-p2t6-init.log
fi

echo "== Check 4: standing signal offline-clean =="
if grep -q '_subagent_engine_check' perk/doctor.py; then
  pass "_subagent_engine_check present in doctor.py"
else
  bad "_subagent_engine_check missing in doctor.py"
fi
if uv run python - <<'PY' >/tmp/perk-p2t6-doctor.log 2>&1; then
import tempfile
from pathlib import Path
from perk.init import run_init
from perk.doctor import run_doctor

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    run_init(root, verify=False)
    checks = {c.name: c for c in run_doctor(root, verify=False).checks}
    engine = checks["subagent-engine"]
    assert engine.status == "ok", f"subagent-engine status {engine.status}"
    assert checks["subagent-agents"].status == "ok", "subagent-agents not ok"
print("ok")
PY
  pass "subagent-engine ok pointer + subagent-agents ok on fresh repo"
else
  bad "doctor offline signal check failed"; tail -20 /tmp/perk-p2t6-doctor.log
fi

echo "== Check 5: perk's own dogfood converged =="
if grep -q 'npm:pi-subagents' .pi/settings.json && test -f .pi/agents/.gitkeep; then
  pass "perk dogfood has npm:pi-subagents + .pi/agents/.gitkeep"
else
  bad "perk dogfood not converged (.pi/settings.json or .pi/agents/.gitkeep)"
fi

echo "== Check 6: contracts amendment present =="
if grep -q 'Spawned delegation engine seam (P2.T6)' shared/contracts.md; then
  pass "contracts documents the P2.T6 seam"
else
  bad "contracts missing the 'Spawned delegation engine seam (P2.T6)' amendment"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T6 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T6 hard gate: FAILURES\033[0m\n"; fi
exit $fail
