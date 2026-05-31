#!/usr/bin/env bash
# Phase 0 · Turn 5 — hard-gate verification (uv-only).
# Checks from docs/planning/phase-0-turn-5.md §10:
#   1. full convergence on a fresh git repo (+ post-init handoff)
#   2. --json shape (supervisor surface)
#   3. idempotent re-run (no changes)
#   4. --force re-seeds config; managed blocks untouched
#   5. env-not-ready -> exit 2 + error_type + remediation
#   6. github gateway unit (faked gh) + require_github raises when unauthed
#   7. unit suites green
# CI-robust: GitHub verify is non-fatal, so checks assert the report *has* a github section.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
fail=0
pass() { printf "  \033[32mPASS\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mFAIL\033[0m %s\n" "$1"; fail=1; }

perk_in() { ( cd "$1" && shift && uv run --project "$ROOT" perk "$@" ); }
py_run()  { uv run --project "$ROOT" python "$@"; }

W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
( cd "$W" && git init -q ) >/dev/null 2>&1

echo "== Check 1: full convergence on a fresh repo =="
perk_in "$W" init >/dev/null 2>&1; rc=$?
if [ "$rc" = 0 ] \
   && [ -f "$W/.pi/settings.json" ] && [ -f "$W/.pi/perk.toml" ] && [ -f "$W/.pi/perk.local.toml" ] \
   && [ -f "$W/.pi/workflow/.gitkeep" ] && [ -f "$W/.pi/workflow/post-init.md" ] \
   && grep -q "perk conventions" "$W/AGENTS.md" \
   && grep -q "BEGIN perk managed" "$W/.gitignore"; then
  pass "perk init converged every managed piece + wrote post-init.md"
else
  bad "convergence incomplete (rc=$rc)"
fi

echo "== Check 2: --json shape =="
J="$(perk_in "$W" init --json 2>/dev/null)"
if echo "$J" | py_run -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['success'] and d['mode']=='consumer' and 'github' in d and isinstance(d['env'],list) and d['handoff'] else 1)"; then
  pass "init --json emits success/mode/env/github/handoff"
else
  bad "init --json malformed: $J"
fi

echo "== Check 3: idempotent re-run =="
J2="$(perk_in "$W" init --json 2>/dev/null)"
if echo "$J2" | py_run -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['success'] and d['changes']==[] else 1)"; then
  pass "second init is a no-op (changes == [])"
else
  bad "re-run not idempotent: $J2"
fi

echo "== Check 4: --force re-seeds config =="
printf "[worktree]\nroot = 'hacked'\n" > "$W/.pi/perk.toml"
GIBEFORE="$(sha1sum "$W/.gitignore" 2>/dev/null || shasum "$W/.gitignore")"
perk_in "$W" init --force --no-interactive >/dev/null 2>&1
GIAFTER="$(sha1sum "$W/.gitignore" 2>/dev/null || shasum "$W/.gitignore")"
if grep -q '.worktrees' "$W/.pi/perk.toml" && ! grep -q 'hacked' "$W/.pi/perk.toml" \
   && [ "$GIBEFORE" = "$GIAFTER" ]; then
  pass "--force restored perk.toml to template; .gitignore untouched"
else
  bad "--force did not re-seed cleanly"
fi

echo "== Check 5: env-not-ready (not a repo) -> exit 2 =="
N="$(mktemp -d)"
OUT="$(perk_in "$N" init --json 2>/dev/null)"; rc=$?
HUM="$(perk_in "$N" init 2>&1 >/dev/null)"
if [ "$rc" = 2 ] \
   && echo "$OUT" | py_run -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['success'] is False and d['error_type']=='not_a_repo' else 1)" \
   && echo "$HUM" | grep -qi "git repository"; then
  pass "non-repo init -> exit 2, error_type=not_a_repo, remediation present"
else
  bad "env-not-ready path wrong (rc=$rc out=$OUT)"
fi
rm -rf "$N"

echo "== Check 6: github gateway unit (faked gh) + require_github =="
if py_run -m pytest tests/test_github.py -q >/tmp/perk-t5-gh.log 2>&1; then
  pass "github gateway + require_github ($(grep -Eo '[0-9]+ passed' /tmp/perk-t5-gh.log | head -1))"
else
  bad "github unit failed (see /tmp/perk-t5-gh.log)"
fi

echo "== Check 7: unit suites =="
if py_run -m pytest tests/test_env.py tests/test_capabilities.py tests/test_init_t5.py tests/test_init_idempotent.py -q \
    >/tmp/perk-t5-pytest.log 2>&1; then
  pass "env/capabilities/init suites ($(grep -Eo '[0-9]+ passed' /tmp/perk-t5-pytest.log | head -1))"
else
  bad "unit suites failed (see /tmp/perk-t5-pytest.log)"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mT5 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mT5 hard gate: FAILURES\033[0m\n"; fi
exit $fail
