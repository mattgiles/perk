#!/usr/bin/env bash
# Phase 0 · Turn 3 — hard-gate verification (uv-only + node:test).
# Runs the four checks from docs/phase-0-turn-3.md §10:
#   1. run_id round-trip + REAL 2-process reload (PERK_RUN_ID unset in P2)
#   2. REAL fork derives a child run_id <run_id>.<n>
#   3. both planes share .pi/workflow/ (Python writes handoff -> TS consumes; TS marker -> Python reads)
#   4. deterministic unit tests (pytest + node --test)
# Assumes: run from the repo; `uv`, `pi`, `node` available. No global `perk`/`python`.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
EXT="$ROOT/extension/index.ts"
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

perk_run() { uv run --project "$ROOT" perk "$@"; }
py_run()   { uv run --project "$ROOT" python "$@"; }

# Watchdog runner for `pi` only (it can hang); macOS has no `timeout`.
run_to() {
  local secs=$1; shift
  "$@" & local pid=$!
  ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null; sleep 1; kill -KILL "$pid" 2>/dev/null ) & local wd=$!
  wait "$pid" 2>/dev/null; local rc=$?
  kill -TERM "$wd" 2>/dev/null
  return $rc
}

# Dedicated working dir: the CLI writes the handoff and pi (ctx.cwd) reads it here.
T="$(mktemp -d)"
SDIR="$T/sessions"; mkdir -p "$SDIR"
trap 'rm -rf "$T"' EXIT
sentinel_field() { py_run - "$1" <<PY
import json, sys
print(json.load(open("$T/.pi/workflow/.perk-t3.json")).get(sys.argv[1]))
PY
}

echo "== Check 1: run_id round-trip + 2-process reload =="
cd "$T"
RID="$(perk_run state new-run --handoff '{"mode":"read-only"}' 2>/dev/null)"
cd "$ROOT"
HOFF="$T/.pi/workflow/handoff/$RID.json"
if [ -n "$RID" ] && [ -f "$HOFF" ] && py_run -c "import json,sys;sys.exit(0 if json.load(open('$HOFF'))['consumed'] is False else 1)"; then
  pass "minted $RID; fresh handoff written (consumed=false)"
else
  bad "perk state new-run did not write a fresh handoff"
fi

# P1: claim (PERK_RUN_ID set)
( cd "$T" && PERK_RUN_ID="$RID" PERK_SELFCHECK=1 run_to 45 pi --session-dir "$SDIR" --session-id perk-t3 \
    -e "$EXT" -p --no-tools "reply ok" ) >/tmp/perk-t3-p1.log 2>&1
SRC="$(sentinel_field source)"; SRID="$(sentinel_field run_id)"
CONSUMED="$(py_run -c "import json;print(json.load(open('$HOFF'))['consumed'])" 2>/dev/null)"
JSONL_OK=$(py_run - <<PY
import glob, json, sys
hit = False
for f in glob.glob("$SDIR/*.jsonl"):
    for line in open(f):
        try: e = json.loads(line)
        except Exception: continue
        if e.get("type")=="custom" and e.get("customType")=="perk:workflow-state" and e.get("data",{}).get("run_id")=="$RID":
            hit = True
print("ok" if hit else "miss")
PY
)
if [ "$SRC" = env ] && [ "$SRID" = "$RID" ] && [ "$CONSUMED" = True ] && [ "$JSONL_OK" = ok ]; then
  pass "P1 claimed: source=env run_id matches, handoff consumed, entry persisted to JSONL"
else
  bad "P1 claim failed (source=$SRC run_id=$SRID consumed=$CONSUMED jsonl=$JSONL_OK; see /tmp/perk-t3-p1.log)"
fi

# P2: reload, PERK_RUN_ID UNSET -> must restore from the session, not the env
( cd "$T" && PERK_SELFCHECK=1 run_to 45 pi --session-dir "$SDIR" --session-id perk-t3 \
    -e "$EXT" -p --no-tools "reply ok" ) >/tmp/perk-t3-p2.log 2>&1
SRC2="$(sentinel_field source)"; SRID2="$(sentinel_field run_id)"
if [ "$SRC2" = session ] && [ "$SRID2" = "$RID" ]; then
  pass "P2 reload restored run_id from session (source=session, PERK_RUN_ID was unset)"
else
  bad "P2 reload failed (source=$SRC2 run_id=$SRID2; see /tmp/perk-t3-p2.log)"
fi

echo "== Check 2: fork derives a child run_id =="
P1FILE="$(ls -1 "$SDIR"/*.jsonl 2>/dev/null | head -1)"
( cd "$T" && PERK_SELFCHECK=1 run_to 45 pi --session-dir "$SDIR" --fork "$P1FILE" \
    -e "$EXT" -p --no-tools "reply ok" ) >/tmp/perk-t3-p3.log 2>&1
FSRC="$(sentinel_field source)"; FRID="$(sentinel_field run_id)"; FPRED="$(sentinel_field predecessor)"
if [ "$FSRC" = fork ] && [ "$FRID" = "$RID.1" ] && [ "$FPRED" = "$RID" ] && [ -d "$T/.pi/workflow/scratch/runs/$RID.1" ]; then
  pass "fork derived child $FRID (predecessor=$FPRED), child scratch created"
else
  bad "fork derivation failed (source=$FSRC run_id=$FRID predecessor=$FPRED; see /tmp/perk-t3-p3.log)"
fi

echo "== Check 3: both planes share .pi/workflow/ =="
# Python wrote the handoff; the TS plane consumed it (Check 1, consumed=True). Now the reverse:
# the extension set a marker via cache.ts -> the Python cache helper must see it.
if py_run -c "import sys;from pathlib import Path;from perk.cache import has_marker;sys.exit(0 if has_marker(Path('$T'),'t3-extension-cache-write') else 1)"; then
  pass "TS-written marker visible to the Python cache helper (and Python-written handoff consumed by TS)"
else
  bad "cross-plane cache marker not visible to Python"
fi

echo "== Check 4: deterministic unit tests =="
if py_run -m pytest tests/test_run_id.py tests/test_cache.py -q >/tmp/perk-t3-pytest.log 2>&1; then
  pass "pytest run_id + cache ($(grep -Eo '[0-9]+ passed' /tmp/perk-t3-pytest.log | head -1))"
else
  bad "python unit tests failed (see /tmp/perk-t3-pytest.log)"
fi
if node --test "$ROOT"/extension/workflowState.test.ts "$ROOT"/extension/cache.test.ts \
    >/tmp/perk-t3-node.log 2>&1; then
  pass "node --test workflowState + cache ($(grep -E '^# pass' /tmp/perk-t3-node.log | head -1 | tr -d '#'))"
else
  bad "TS unit tests failed (see /tmp/perk-t3-node.log)"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mT3 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mT3 hard gate: FAILURES\033[0m\n"; fi
exit $fail
