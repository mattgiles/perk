#!/usr/bin/env bash
# Phase 0 · Turn 2 — hard-gate verification (uv-only).
# Runs the four checks from docs/phase-0-turn-2.md §10.
# Assumes: run from the repo; `uv`, `pi`, `npm` available. No global `perk`/`python`.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
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

echo "== Check 1: Python plane validates the bundled registry =="
OUT="$(perk_run registry check 2>&1)"; rc=$?
echo "  $OUT"
if [ "$rc" = 0 ] && echo "$OUT" | grep -q "6 stages" && echo "$OUT" | grep -q "graph consistent"; then
  pass "perk registry check OK"
else
  bad "perk registry check failed (rc=$rc)"
fi

echo "== Check 2: TS plane parses its bundled registry (scriptable proof) =="
SENT="$ROOT/.pi/workflow/.perk-loaded"
rm -f "$SENT"; mkdir -p "$ROOT/.pi/workflow"
PERK_SELFCHECK=1 run_to 30 pi -e ./extension/index.ts -p --no-session --no-tools "reply ok" >/dev/null 2>&1
if [ -f "$SENT" ] && grep -q "registry=ok stages=6" "$SENT"; then
  pass "extension parsed registry: $(cat "$SENT" | tr -d '\n')"
else
  bad "no registry parse proof (sentinel: $(cat "$SENT" 2>/dev/null | tr -d '\n'))"
fi
rm -f "$SENT"

echo "== Check 3: both build artifacts bundle registry.yaml + contracts.md =="
rm -rf dist *.tgz
uv build >/tmp/perk-t2-build.log 2>&1
WHL="$(ls dist/*.whl 2>/dev/null | head -1)"
if [ -n "$WHL" ] && py_run -c "
import sys,zipfile
n=set(zipfile.ZipFile(sys.argv[1]).namelist())
sys.exit(0 if {'perk/_shared/registry.yaml','perk/_shared/contracts.md'} <= n else 1)" "$WHL"; then
  pass "wheel bundles registry.yaml + contracts.md ($(basename "$WHL"))"
else
  bad "wheel missing contracts (see /tmp/perk-t2-build.log)"
fi
npm pack >/tmp/perk-t2-pack.log 2>&1
TGZ="$(ls perk-pi-*.tgz 2>/dev/null | head -1)"
if [ -n "$TGZ" ] && py_run -c "
import sys,tarfile
n=set(tarfile.open(sys.argv[1]).getnames())
sys.exit(0 if {'package/shared/registry.yaml','package/shared/contracts.md'} <= n else 1)" "$TGZ"; then
  pass "npm tarball bundles registry.yaml + contracts.md ($TGZ)"
else
  bad "npm tarball missing contracts (see /tmp/perk-t2-pack.log)"
fi
rm -rf dist *.tgz

echo "== Check 4: validator accepts the real registry and rejects bad ones =="
if py_run -m pytest tests/test_registry.py -q >/tmp/perk-t2-pytest.log 2>&1; then
  pass "tests/test_registry.py ($(grep -Eo '[0-9]+ passed' /tmp/perk-t2-pytest.log | head -1))"
else
  bad "registry tests failed (see /tmp/perk-t2-pytest.log)"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mT2 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mT2 hard gate: FAILURES\033[0m\n"; fi
exit $fail
