#!/usr/bin/env bash
# Phase 1 · Turn 6 — hard-gate verification (the prek pre-commit ruff hook).
# Checks run FULLY OFFLINE (no network clone of ruff-pre-commit):
#   1. prek.toml exists and `prek validate-config` accepts it
#   2. the ruff hook is pinned in lockstep with the pyproject dev-group ruff floor
#   3. `just setup` wires `prek install` (the `hooks` recipe is a setup dependency)
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

echo "== Check 1: prek.toml present + valid =="
if [ -f prek.toml ] && prek validate-config prek.toml >/tmp/perk-p1t6-validate.log 2>&1; then
  pass "prek.toml validates ($(grep -c 'ruff-check' prek.toml) ruff-check hook)"
else
  bad "prek.toml missing or invalid"; cat /tmp/perk-p1t6-validate.log 2>/dev/null
fi

echo "== Check 2: ruff hook rev aligned to pyproject dev-group ruff floor =="
rev="$(grep -oE 'rev = "v[0-9.]+"' prek.toml | grep -oE '[0-9.]+' | head -1)"
floor="$(grep -oE 'ruff>=[0-9.]+' pyproject.toml | grep -oE '[0-9.]+' | head -1)"
if [ -n "$rev" ] && [ "$rev" = "$floor" ]; then
  pass "prek rev v$rev == pyproject ruff floor $floor"
else
  bad "prek rev (v$rev) and pyproject ruff floor ($floor) drifted"
fi

echo "== Check 3: just setup wires prek install via the hooks recipe =="
if grep -qE '^setup:.*hooks' justfile && grep -qE '^hooks:' justfile && grep -qE 'prek install' justfile; then
  pass "setup depends on hooks; hooks runs prek install"
else
  bad "justfile setup/hooks wiring missing"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP1.T6 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP1.T6 hard gate: FAILURES\033[0m\n"; fi
exit $fail
