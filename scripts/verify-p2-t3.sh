#!/usr/bin/env bash
# Phase 2 · Turn 3 — hard-gate verification (enforce formatting via a prek `ruff-format` hook).
# This turn DECLINES the proposed `tool_result` post-edit formatter middleware and instead meets
# its load-bearing goal (formatting never becomes a CI iteration) with a commit-time `ruff-format`
# prek hook. All checks run FULLY OFFLINE (no LLM, no network):
#   1. ruff-format hook present in prek.toml
#   2. ruff-check (lint) hook preserved (the format hook is added, not a replacement)
#   3. astral-sh/ruff-pre-commit rev pin intact (v0.15.15; lockstep with the dev-group ruff floor)
#   4. tree is format-clean: `ruff format --check perk tests` exits 0 (skipped-with-message if
#      uv/ruff is unavailable, mirroring how other gates degrade gracefully)
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

echo "== Check 1: ruff-format hook present in prek.toml =="
if grep -q 'id = "ruff-format"' prek.toml; then
  pass "prek.toml wires the ruff-format hook"
else
  bad "prek.toml is missing the ruff-format hook"
fi

echo "== Check 2: ruff-check (lint) hook preserved =="
if grep -q 'id = "ruff-check"' prek.toml; then
  pass "ruff-check lint hook still present (format hook is additive)"
else
  bad "ruff-check lint hook went missing"
fi

echo "== Check 3: astral-sh/ruff-pre-commit rev pin intact =="
if grep -q 'github.com/astral-sh/ruff-pre-commit' prek.toml \
   && grep -q 'rev = "v0.15.15"' prek.toml; then
  pass "ruff-pre-commit pinned at v0.15.15 (lockstep with pyproject ruff floor)"
else
  bad "ruff-pre-commit pin is missing or changed"
fi

echo "== Check 4: tree is format-clean (ruff format --check) =="
if command -v uv >/dev/null 2>&1; then
  if uv run ruff format --check perk tests >/tmp/perk-p2t3-fmt.log 2>&1; then
    pass "ruff format --check perk tests is clean (new hook will not block commits)"
  else
    bad "ruff format --check reports unformatted files (see /tmp/perk-p2t3-fmt.log)"; tail -25 /tmp/perk-p2t3-fmt.log
  fi
else
  printf "  \033[33mSKIP\033[0m uv/ruff unavailable — cannot run format --check\n"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mP2.T3 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mP2.T3 hard gate: FAILURES\033[0m\n"; fi
exit $fail
