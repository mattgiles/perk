#!/usr/bin/env bash
# Phase 0 · Turn 6 — hard-gate verification (uv-only).
# Checks from docs/planning/phase-0-turn-6.md §10:
#   1. healthy report on a fresh init'd repo (+ all six groups, --json shape)
#   2. --fix round-trip on a deliberately-broken managed piece
#   3. dual-mode self vs consumer (self_repo flag)
#   4. exit codes + json error path (not_a_repo -> exit 2)
#   5. registry + cache integrity pass
#   6. config user-edit is not flagged as drift
#   7. unit suite (pure + engine + coherence guard)
#   8. doctor ships as a Click group (invoke_without_command=True)
# CI-robust: GitHub is non-fatal (warn), so checks assert healthy/exit, never gh `ok`.
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

echo "== Check 1: healthy report on a fresh init'd repo =="
J="$(perk_in "$W" doctor --json 2>/dev/null)"; rc_human=$(perk_in "$W" doctor >/dev/null 2>&1; echo $?)
if [ "$rc_human" = 0 ] && echo "$J" | py_run -c "
import json,sys
d=json.load(sys.stdin)
groups={c['group'] for c in d['checks']}
need={'environment','github','package','repository','registry','state'}
sys.exit(0 if d['success'] and d['healthy'] and d['self_repo'] is False
         and need<=groups and d['summary']['failed']==0 else 1)"; then
  pass "perk doctor healthy (exit 0); all six groups present; --json well-formed"
else
  bad "fresh-init doctor not healthy (rc=$rc_human): $J"
fi

echo "== Check 2: --fix round-trip on a broken managed piece =="
printf 'node_modules/\n' > "$W/.gitignore"   # clobber the managed gitignore block
BEFORE="$(perk_in "$W" doctor --json 2>/dev/null)"; rc_bad=$(perk_in "$W" doctor >/dev/null 2>&1; echo $?)
perk_in "$W" doctor --fix >/dev/null 2>&1
AFTER="$(perk_in "$W" doctor --json 2>/dev/null)"; rc_fixed=$(perk_in "$W" doctor >/dev/null 2>&1; echo $?)
if [ "$rc_bad" = 1 ] && [ "$rc_fixed" = 0 ] \
   && echo "$BEFORE" | py_run -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if not d['healthy'] and any(c['name']=='gitignore-block' and c['status']=='fail' for c in d['checks']) else 1)" \
   && echo "$AFTER" | py_run -c "import json,sys; sys.exit(0 if json.load(sys.stdin)['healthy'] else 1)" \
   && grep -q 'BEGIN perk managed' "$W/.gitignore"; then
  pass "broken managed block -> exit 1 -> --fix repairs -> exit 0"
else
  bad "--fix round-trip failed (bad=$rc_bad fixed=$rc_fixed)"
fi

echo "== Check 3: dual-mode self vs consumer =="
CONSUMER="$(perk_in "$W" doctor --json 2>/dev/null | py_run -c "import json,sys; print(json.load(sys.stdin)['self_repo'])")"
SELF="$(perk_in "$ROOT" doctor --json 2>/dev/null | py_run -c "import json,sys; print(json.load(sys.stdin)['self_repo'])")"
if [ "$CONSUMER" = "False" ] && [ "$SELF" = "True" ]; then
  pass "self_repo distinguishes perk's own repo (True) from a consumer (False)"
else
  bad "dual-mode wrong (consumer=$CONSUMER self=$SELF)"
fi

echo "== Check 4: not-a-repo -> exit 2 + json error =="
N="$(mktemp -d)"
OUT="$(perk_in "$N" doctor --json 2>/dev/null)"; rc=$(perk_in "$N" doctor >/dev/null 2>&1; echo $?)
if [ "$rc" = 2 ] && echo "$OUT" | py_run -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['success'] is False and d['error_type']=='not_a_repo' else 1)"; then
  pass "non-repo doctor -> exit 2, error_type=not_a_repo, json error object"
else
  bad "not-a-repo path wrong (rc=$rc out=$OUT)"
fi
rm -rf "$N"

echo "== Check 5: registry + cache integrity pass =="
if perk_in "$W" doctor --json 2>/dev/null | py_run -c "
import json,sys
d=json.load(sys.stdin)
by={c['name']:c['status'] for c in d['checks']}
sys.exit(0 if by.get('registry')=='ok' and by.get('cache-handoff')=='ok' else 1)"; then
  pass "registry self-check + cache-handoff integrity ok"
else
  bad "registry/cache integrity not ok"
fi

echo "== Check 6: config user-edit is not drift =="
printf "[worktree]\nroot = 'custom-wt'\n" > "$W/.pi/perk.toml"
if perk_in "$W" doctor --json 2>/dev/null | py_run -c "
import json,sys
d=json.load(sys.stdin)
cfg=next(c for c in d['checks'] if c['name']=='config')
sys.exit(0 if cfg['status']=='ok' else 1)"; then
  pass "edited .pi/perk.toml stays ok (user edits are not drift)"
else
  bad "config user-edit wrongly flagged as drift"
fi

echo "== Check 7: unit suite =="
if py_run -m pytest tests/test_doctor.py -q >/tmp/perk-t6-pytest.log 2>&1; then
  pass "test_doctor ($(grep -Eo '[0-9]+ passed' /tmp/perk-t6-pytest.log | head -1))"
else
  bad "test_doctor failed (see /tmp/perk-t6-pytest.log)"
fi

echo "== Check 8: doctor is a Click group =="
if perk_in "$W" doctor --help 2>&1 | grep -q "COMMAND \[ARGS\]"; then
  pass "perk doctor is a group (invoke_without_command=True); Phase-3 'doctor workflow' slots in"
else
  bad "doctor is not a group (subcommand seam missing)"
fi

echo
if [ "$fail" = 0 ]; then printf "\033[32mT6 hard gate: ALL PASS\033[0m\n"; else printf "\033[31mT6 hard gate: FAILURES\033[0m\n"; fi
exit $fail
