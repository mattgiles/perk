#!/usr/bin/env bash
# Phase 0 · Turn 1 — hard-gate verification (uv-only).
# Runs the five hard-gate checks from docs/phase-0-turn-1.md §9.
# Assumes: run from the repo; `uv`, `pi`, `npm` available. No global `perk`/`python`.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

# Run perk / python from the project env, regardless of the current directory.
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

echo "== Check 1: CLI installs & versions are lockstep =="
PERK_V="$(perk_run --version 2>/dev/null | awk '{print $2}')"
PKG_V="$(node -e 'process.stdout.write(require("./package.json").version)' 2>/dev/null)"
PY_V="$(py_run -c 'import perk; print(perk.__version__)' 2>/dev/null)"
echo "  perk=$PERK_V  package.json=$PKG_V  perk.__version__=$PY_V"
[ -n "$PERK_V" ] && [ "$PERK_V" = "$PKG_V" ] && [ "$PERK_V" = "$PY_V" ] \
  && pass "versions match ($PERK_V)" || bad "version mismatch / perk not installed"

echo "== Check 2: perk init converges a consumer repo =="
TMP="$(mktemp -d)"
( cd "$TMP" && git init -q && perk_run init >/dev/null 2>&1 )
S="$TMP/.pi/settings.json"
if [ -f "$S" ] \
  && grep -q '@perk/pi' "$S" \
  && grep -q '@tombell/pi-plan' "$S" \
  && [ -f "$TMP/.pi/workflow/.gitkeep" ] \
  && grep -q '/.pi/npm/' "$TMP/.gitignore" \
  && grep -q 'perk conventions' "$TMP/AGENTS.md"; then
  pass "init wired settings/workflow/gitignore/AGENTS"
else
  bad "init did not produce expected files"
fi
rm -rf "$TMP"

echo "== Check 3: the extension provably loads (scriptable proof) =="
SENT="$ROOT/.pi/workflow/.perk-loaded"
rm -f "$SENT"; mkdir -p "$ROOT/.pi/workflow"
PERK_SELFCHECK=1 run_to 30 pi -e ./extension/index.ts -p --no-session --no-tools "reply ok" >/dev/null 2>&1
if [ -f "$SENT" ] && grep -q "shared=ok" "$SENT"; then
  pass "session_start fired; sentinel: $(cat "$SENT" | tr -d '\n')"
else
  bad "no load sentinel (extension did not load or shared/ unresolved)"
fi
rm -f "$SENT"

echo "== Check 4: perk init is idempotent (re-run = no-op) =="
TMP="$(mktemp -d)"
( cd "$TMP" && git init -q && perk_run init >/dev/null 2>&1 )
B="$(cd "$TMP" && find . -type f -not -path './.git/*' | sort | xargs shasum 2>/dev/null)"
OUT="$(cd "$TMP" && perk_run init 2>&1)"
A="$(cd "$TMP" && find . -type f -not -path './.git/*' | sort | xargs shasum 2>/dev/null)"
if [ "$B" = "$A" ] && echo "$OUT" | grep -qi "already converged"; then
  pass "second run changed nothing and reported 'already converged'"
else
  bad "init was not idempotent"
fi
rm -rf "$TMP"

echo "== Check 5: both build artifacts bundle shared/ =="
rm -rf dist *.tgz
# Membership via Python zipfile/tarfile (atomic, no pipe nondeterminism).
uv build >/tmp/perk-build.log 2>&1
WHL="$(ls dist/*.whl 2>/dev/null | head -1)"
if [ -n "$WHL" ] && py_run -c "import sys,zipfile; sys.exit(0 if 'perk/_shared/README.md' in zipfile.ZipFile(sys.argv[1]).namelist() else 1)" "$WHL"; then
  pass "wheel bundles perk/_shared/ ($(basename "$WHL"))"
else
  bad "wheel missing perk/_shared/ (see /tmp/perk-build.log)"
fi
npm pack >/tmp/perk-pack.log 2>&1
TGZ="$(ls perk-pi-*.tgz 2>/dev/null | head -1)"
if [ -n "$TGZ" ] && py_run -c "import sys,tarfile; n=set(tarfile.open(sys.argv[1]).getnames()); sys.exit(0 if {'package/shared/README.md','package/extension/index.ts'} <= n else 1)" "$TGZ"; then
  pass "npm tarball bundles shared/ + extension/ ($TGZ)"
else
  bad "npm tarball missing shared/ or extension/ (see /tmp/perk-pack.log)"
fi
rm -rf dist *.tgz

echo
if [ "$fail" = 0 ]; then printf "\033[32mT1 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mT1 hard gate: FAILURES\033[0m\n"; fi
exit $fail
