#!/usr/bin/env bash
# Phase 1 · Turn 4c — hard-gate verification (implement priming + the plan positional).
# The dogfood run surfaced two bugs in the cold implement door; this gate locks the fixes.
# Checks (run FULLY OFFLINE — no pi launch, no gh):
#   1. Bug 1 — `perk implement --dry-run` (active ref) primes the session: argv carries the
#      "read the plan + /submit" prompt (so the launched pi starts working, not idle).
#   2. the `plan` stage is NOT primed (argv == ["pi", *pi_args]) — only implement is.
#   3. Bug 2 — `perk implement` is a dedicated command (skipped by the generic generator);
#      it still appears in --help and `implement 0` rejects a non-positive plan id.
#   4. the launch + implement-command unit suites are green.
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
py_run -c "
from pathlib import Path
from perk import cache
cache.write_plan_ref(Path('$W'), {
    'provider': 'github', 'pr_id': '7',
    'url': 'https://gh/o/r/issues/7', 'labels': ['perk:plan'], 'objective_id': None,
})"

echo "== Check 1: implement --dry-run primes the session (argv carries the prompt) =="
J="$(perk_in "$W" implement --dry-run 2>/dev/null)"
if printf '%s' "$J" | py_run -c "
import json,sys
d=json.load(sys.stdin)
argv=d['argv']
ok = (d['stage']=='implement' and argv[0]=='pi' and len(argv)==2
      and 'gh issue view 7 --comments' in argv[1] and '/submit' in argv[1])
sys.exit(0 if ok else 1)"; then
  pass "implement launch is primed (reads the plan, points at /submit)"
else
  bad "implement not primed: $J"
fi

echo "== Check 2: the plan stage is NOT primed (argv == [pi]) =="
JP="$(perk_in "$W" plan --dry-run 2>/dev/null)"
if printf '%s' "$JP" | py_run -c "
import json,sys
d=json.load(sys.stdin)
sys.exit(0 if d['stage']=='plan' and d['argv']==['pi'] else 1)"; then
  pass "plan launches unprimed (user-driven exploration)"
else
  bad "plan stage unexpectedly primed: $JP"
fi

echo "== Check 3: implement is a dedicated command (not generic) + rejects a bad plan id =="
HELP="$(perk_in "$W" --help 2>/dev/null)"
DEDICATED="$(py_run -c "from perk.cli.stages import DEDICATED_STAGES; print('implement' in DEDICATED_STAGES)")"
ERR="$(perk_in "$W" implement 0 2>&1 >/dev/null)"; rc=$?
if printf '%s' "$HELP" | grep -q "implement" && [ "$DEDICATED" = "True" ] \
   && [ "$rc" != 0 ] && printf '%s' "$ERR" | grep -qi "invalid plan id"; then
  pass "implement is dedicated (DEDICATED_STAGES), in --help, and rejects 'implement 0'"
else
  bad "implement command wiring wrong (dedicated=$DEDICATED rc=$rc): $ERR"
fi

echo "== Check 4: launch + implement-command unit suites =="
if py_run -m pytest tests/test_launch.py tests/test_implement_cmd.py tests/test_cli_stages.py -q \
     >/tmp/perk-p1t4c-pytest.log 2>&1; then
  pass "pytest green ($(grep -Eo '[0-9]+ passed' /tmp/perk-p1t4c-pytest.log | head -1))"
else
  bad "pytest failed (see /tmp/perk-p1t4c-pytest.log)"; tail -20 /tmp/perk-p1t4c-pytest.log
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP1.T4c hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP1.T4c hard gate: FAILURES\033[0m\n"; fi
exit $fail
