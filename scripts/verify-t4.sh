#!/usr/bin/env bash
# Phase 0 · Turn 4 — hard-gate verification (uv-only + a real launch).
# Checks from docs/phase-0-turn-4.md §10:
#   1. registry-generated stage subcommands (+ --remote blocked)
#   2. worktree create/list/remove against a real git repo
#   3. the launch primitive closes the T3 loop (dry-run argv + a real `perk <stage>` claim)
#   4. `perk init` scaffolds config + converges .gitignore (idempotent)
#   5. unit tests
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
EXT="$ROOT/extension/index.ts"
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

perk_in() { ( cd "$1" && shift && uv run --project "$ROOT" perk "$@" ); }
py_run()  { uv run --project "$ROOT" python "$@"; }
run_to() {
  local secs=$1; shift; "$@" & local pid=$!
  ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null; sleep 1; kill -KILL "$pid" 2>/dev/null ) & local wd=$!
  wait "$pid" 2>/dev/null; local rc=$?; kill -TERM "$wd" 2>/dev/null; return $rc
}

W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
( cd "$W" && git init -q && git config user.email t@e && git config user.name t \
    && echo hi > f && git add . && git commit -qm init ) >/dev/null 2>&1

echo "== Check 1: registry-generated stage subcommands =="
HELP="$(perk_in "$W" --help 2>&1)"
if echo "$HELP" | grep -q plan && echo "$HELP" | grep -q implement && echo "$HELP" | grep -q learn \
   && perk_in "$W" implement --help >/dev/null 2>&1; then
  pass "perk --help lists stages; 'implement --help' works"
else
  bad "stage subcommands not generated"
fi
REMOTE="$(perk_in "$W" plan --remote 2>&1)"; rc=$?
if [ "$rc" != 0 ] && echo "$REMOTE" | grep -q "local-only"; then
  pass "perk plan --remote blocked ($(echo "$REMOTE" | head -1))"
else
  bad "perk plan --remote did not block (rc=$rc)"
fi

echo "== Check 2: worktree create/list/remove =="
perk_in "$W" worktree create wt1 >/dev/null 2>&1
L="$(perk_in "$W" worktree list 2>&1)"
perk_in "$W" worktree remove wt1 >/dev/null 2>&1
L2="$(perk_in "$W" worktree list 2>&1)"
if [ -d "$W/.worktrees" ] && echo "$L" | grep -q wt1 && ! echo "$L2" | grep -q wt1; then
  pass "worktree create -> list -> remove"
else
  bad "worktree lifecycle failed (list1='$L' list2='$L2')"
fi

echo "== Check 3: launch primitive closes the T3 loop =="
DRY="$(perk_in "$W" implement --worktree wtdry --dry-run 2>/dev/null)"
if echo "$DRY" | py_run -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['stage']=='implement' and d['argv']==['pi'] and d['run_id'] else 1)"; then
  pass "implement --dry-run emits a launch plan (run_id + argv)"
else
  bad "dry-run plan malformed: $DRY"
fi
mkdir -p "$W/sessions"
( cd "$W" && PERK_SELFCHECK=1 run_to 45 uv run --project "$ROOT" perk plan -- \
    -e "$EXT" --session-dir "$W/sessions" --session-id s4 -p --no-tools "reply ok" ) >/tmp/perk-t4-launch.log 2>&1
HOFF="$(ls "$W"/.pi/workflow/handoff/*.json 2>/dev/null | head -1)"
CLAIM=$(py_run - "$HOFF" "$W/.pi/workflow/.perk-t3.json" "$W/sessions" <<'PY'
import glob, json, sys
hoff, sentinel, sdir = sys.argv[1], sys.argv[2], sys.argv[3]
h = json.load(open(hoff)); s = json.load(open(sentinel))
rid = h["run_id"]
persisted = any(
    json.loads(line).get("customType") == "perk:workflow-state"
    and json.loads(line).get("data", {}).get("run_id") == rid
    for f in glob.glob(f"{sdir}/*.jsonl") for line in open(f)
    if line.strip().startswith("{")
)
ok = h["consumed"] is True and s["source"] == "env" and s["run_id"] == rid and persisted
print("ok" if ok else f"FAIL consumed={h.get('consumed')} src={s.get('source')} persisted={persisted}")
PY
)
if [ "$CLAIM" = ok ]; then
  pass "perk plan launched pi; the CLI-minted run_id was claimed (consumed + persisted, source=env)"
else
  bad "launch loop did not claim ($CLAIM; see /tmp/perk-t4-launch.log)"
fi

echo "== Check 4: perk init scaffolds config + converges .gitignore =="
I="$(mktemp -d)"; ( cd "$I" && git init -q ) >/dev/null 2>&1
perk_in "$I" init >/dev/null 2>&1
SECOND="$(perk_in "$I" init 2>&1)"
GI="$(sed -n '/BEGIN perk managed/,/END perk managed/p' "$I/.gitignore" 2>/dev/null)"
if [ -f "$I/.pi/perk.toml" ] && [ -f "$I/.pi/perk.local.toml" ] \
   && echo "$GI" | grep -q "perk.local.toml" && echo "$GI" | grep -q ".worktrees/" \
   && echo "$GI" | grep -q ".pi/workflow/markers/" \
   && echo "$SECOND" | grep -qi "already converged" \
   && ( cd "$I" && git check-ignore -q .pi/perk.local.toml ); then
  pass "init wrote perk.toml + perk.local.toml; managed .gitignore converged; re-run no-op; local ignored"
else
  bad "init config/gitignore convergence failed (second='$SECOND')"
fi
rm -rf "$I"

echo "== Check 5: unit tests =="
if py_run -m pytest tests/test_config.py tests/test_git.py tests/test_launch.py tests/test_cli_stages.py -q \
    >/tmp/perk-t4-pytest.log 2>&1; then
  pass "pytest config/git/launch/stages ($(grep -Eo '[0-9]+ passed' /tmp/perk-t4-pytest.log | head -1))"
else
  bad "unit tests failed (see /tmp/perk-t4-pytest.log)"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mT4 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mT4 hard gate: FAILURES\033[0m\n"; fi
exit $fail
