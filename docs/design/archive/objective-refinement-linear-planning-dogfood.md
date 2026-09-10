# Gate record: objective-node refinement — the authenticated Linear refine→plan run

**Status:** validation record (the archive gate/evidence genre) for Objective *Consume node
refinements in planning and enable the GitHub carrier*, Phase 1 — the authenticated Linear
refine→plan gate over the shipped doors (§8.68) + consumption (§8.26).

**Gate verdict:** _pending — Part B not yet executed_

**What this record proves and what it does not.** The offline persistence gate
([objective-refinement-linear-persistence.md](objective-refinement-linear-persistence.md)) proved
the Linear refinement carrier over `FakeLinearWorkspace`; this record is the **one authenticated
run** it deferred: a real Linear Project with real node-issues, one refinement authored through
the cold `perk objective refine` door and approved on the operator's review surface, then read
back by a real `perk objective plan` session that saves a real plan. Every criterion is
classified **observed-live** (with the named evidence excerpt), **offline-pinned** (a named test,
shown green at the record's SHA), or **unobserved — NOT PASSED**. A PASS is a point-in-time proof
of the persistence + consumption path against one disposable Project, never a per-workspace
guarantee.

## Context

| item | value |
|---|---|
| record date | 2026-09-10 |
| gate host | the operator's `savant` checkout (`/Users/mattgiles/dev/roivant/savant`, Linear team `SAV`, review provider `plannotator-plan`) — branch `staging`, HEAD _(Part B)_ |
| `PERK_SRC` (the implementation worktree; THE provenance value) | HEAD _(Part B)_ · `git status --porcelain` _(Part B)_ |
| code under test | byte-identical to `main` at `5150771066986218ccd3d61e8a255d9035ad15d8` (#2346; contains #2344 `5c392fa5`) in `src/`, `extension/`, `prompts/`, `shared/`, `skills/perk-objective-*` and `tests/` — this node is docs-only |
| spoof tarball SHA-256 | _(Part B)_ |
| `"$PERK_BIN" --version` | `perk 3.2.0` (== savant's `.perk/required-perk-version`) |
| `pi --version` | `0.85.1` |
| Node / uv / jq | `v26.3.0` / `uv 0.12.3` / `jq-1.7.1-apple` |
| operator confirmation | _(Part B, quoted verbatim)_ |
| deviations | (1) the gate host is the operator's Linear consumer repo with a two-plane spoof, not a clone; (2) prose-map routing already landed in #2346 — see Deviations for the one-line regeneration this node performed |

## Part A — the procedure (pre-committed before execution)

Conventions: every executor block runs in a fresh tool shell and begins with
`source "$EVID/env.sh"` (the literal `EVID` path is known after step 1); the Linear key is never
exported or written — `linear_gql` reads it in-process per call from savant's gitignored
`.perk/local.toml`. Every command below is copy-paste-complete. The **executor** is the implement
session; the **operator** runs the two interactive pi doors in their own terminal.

### Step 1 — variables + drivers (executor; nothing mutated yet)

```bash
PERK_SRC="$(git rev-parse --show-toplevel)"
git -C "$PERK_SRC" merge-base --is-ancestor 5c392fa5 HEAD && echo "contains #2344"
TS=$(date -u +%Y%m%dT%H%M%SZ); EVID=/tmp/perk-linear-gate-evidence-$TS
mkdir -p "$EVID/backup/skills" "$EVID/spoof"
cat > "$EVID/env.sh" <<EOF
PERK_SRC="$PERK_SRC"
PERK_BIN="$PERK_SRC/.venv/bin/perk"
PY="$PERK_SRC/.venv/bin/python"
SAVANT="/Users/mattgiles/dev/roivant/savant"
PKG="/Users/mattgiles/dev/roivant/savant/.pi/npm/node_modules/@mgiles/perk"
EVID="$EVID"
TS="$TS"
linear_gql() { curl -sS https://api.linear.app/graphql -H 'Content-Type: application/json' -H "Authorization: \$("\$PY" -c 'import tomllib,pathlib;print(tomllib.loads(pathlib.Path("/Users/mattgiles/dev/roivant/savant/.perk/local.toml").read_text())["linear"]["api_key"])')" --data @"\$1"; }
EOF
source "$EVID/env.sh"; "$PERK_BIN" --version; "$PERK_BIN" objective refine --help >/dev/null && echo "refine door present"
git -C "$PERK_SRC" rev-parse HEAD; git -C "$PERK_SRC" status --porcelain
```

`snapshot-savant.sh` (usage: `bash "$EVID/snapshot-savant.sh" before|after`):

```bash
#!/bin/bash
set -u; source "$(dirname "$0")/env.sh"
out="$EVID/snapshot-$1.txt"; : > "$out"
for p in ".pi/npm/node_modules/@mgiles/perk" ".agents/skills/perk-objective-refine" ".agents/skills/perk-objective-plan" ".perk/workflow/plan-ref.json" "sandbox-refinement-gate"; do
  if [ -e "$SAVANT/$p" ]; then (cd "$SAVANT" && find "$p" -type f -print0 | sort -z | xargs -0 shasum -a 256) >> "$out"; else echo "ABSENT $p" >> "$out"; fi
done
git -C "$SAVANT" status --porcelain >> "$out"
echo "snapshot $1: $(wc -l < "$out") lines"
```

`restore-savant.sh` (idempotent; safe from every partial state; re-runnable):

```bash
#!/bin/bash
set -u; source "$(dirname "$0")/env.sh"
rm -rf "$SAVANT/sandbox-refinement-gate"
if [ -d "$EVID/backup/perk-npm-3.2.0" ]; then rm -rf "$PKG"; mv "$EVID/backup/perk-npm-3.2.0" "$PKG"; fi
for s in perk-objective-refine perk-objective-plan; do
  if [ -d "$EVID/backup/skills/$s" ]; then rm -rf "$SAVANT/.agents/skills/$s"; mv "$EVID/backup/skills/$s" "$SAVANT/.agents/skills/$s"
  elif [ -f "$EVID/backup/skills/$s.ABSENT" ]; then rm -rf "$SAVANT/.agents/skills/$s"; fi
done
if [ -f "$EVID/backup/plan-ref.json" ]; then cp "$EVID/backup/plan-ref.json" "$SAVANT/.perk/workflow/plan-ref.json"
elif [ -f "$EVID/backup/plan-ref.ABSENT" ]; then rm -f "$SAVANT/.perk/workflow/plan-ref.json"; fi
echo "restore-savant: done"
```

`teardown-linear.sh` (idempotent; no objective ⇒ no-op):

```bash
#!/bin/bash
set -u; source "$(dirname "$0")/env.sh"
[ -f "$EVID/create.json" ] || { echo "teardown-linear: no objective was created"; exit 0; }
OBJ_ID=$(jq -r .objective.id "$EVID/create.json")
jq -n --arg id "$OBJ_ID" '{query:"query($id:String!){ project(id:$id){ id name url trashed issues{ nodes{ id identifier title trashed } } } }",variables:{id:$id}}' > "$EVID/q-project.json"
linear_gql "$EVID/q-project.json" > "$EVID/inventory-final.json"
: > "$EVID/teardown.json"
for iid in $(jq -r '.data.project.issues.nodes[].id' "$EVID/inventory-final.json"); do
  jq -n --arg id "$iid" '{query:"mutation($id:String!){ issueDelete(id:$id){ success } }",variables:{id:$id}}' > "$EVID/m-issue-delete.json"
  linear_gql "$EVID/m-issue-delete.json" >> "$EVID/teardown.json"; echo >> "$EVID/teardown.json"
done
jq -n --arg id "$OBJ_ID" '{query:"mutation($id:String!){ projectDelete(id:$id){ success } }",variables:{id:$id}}' > "$EVID/m-project-delete.json"
linear_gql "$EVID/m-project-delete.json" >> "$EVID/teardown.json"; echo >> "$EVID/teardown.json"
for iid in $(jq -r '.data.project.issues.nodes[].id' "$EVID/inventory-final.json"); do
  jq -n --arg id "$iid" '{query:"query($id:String!){ issue(id:$id){ identifier trashed } }",variables:{id:$id}}' > "$EVID/q-issue.json"
  linear_gql "$EVID/q-issue.json" >> "$EVID/teardown-verify.json"; echo >> "$EVID/teardown-verify.json"
done
linear_gql "$EVID/q-project.json" >> "$EVID/teardown-verify.json"; echo >> "$EVID/teardown-verify.json"
cat "$EVID/teardown.json" "$EVID/teardown-verify.json"
```

Write the three scripts with `cat > "$EVID/<name>.sh" <<'EOF' … EOF` (single-quoted heredocs — no
expansion), `chmod +x`, then `bash "$EVID/restore-savant.sh"` once (a no-op on the untouched
state — proves idempotency before anything is at stake) and `bash "$EVID/teardown-linear.sh"`
once ("no objective was created").

### Step 2 — snapshot + backup (executor)

```bash
source "$EVID/env.sh"
git -C "$SAVANT" rev-parse --abbrev-ref HEAD; git -C "$SAVANT" rev-parse HEAD
bash "$EVID/snapshot-savant.sh" before
[ -f "$SAVANT/.perk/workflow/plan-ref.json" ] && cp "$SAVANT/.perk/workflow/plan-ref.json" "$EVID/backup/plan-ref.json" || : > "$EVID/backup/plan-ref.ABSENT"
ls -t "$SAVANT/.perk/workflow/scratch/runs" | head -5 > "$EVID/runs-before.txt"
```

### Step 3 — spoof the extension + skills (executor)

```bash
source "$EVID/env.sh"
(cd "$PERK_SRC" && npm pack --pack-destination "$EVID/spoof")
shasum -a 256 "$EVID/spoof/mgiles-perk-3.2.0.tgz" | tee "$EVID/spoof/tarball.sha256"
mv "$PKG" "$EVID/backup/perk-npm-3.2.0"; mkdir -p "$PKG"
tar -xzf "$EVID/spoof/mgiles-perk-3.2.0.tgz" -C "$PKG" --strip-components=1
grep -c '"version": "3.2.0"' "$PKG/package.json"; test -f "$PKG/extension/pi/v1/objectiveRefinement.ts" && echo "refine extension present"; grep -c node_context_reference "$PKG/prompts/stages/objective-plan/seed.md"
for s in perk-objective-refine perk-objective-plan; do
  if [ -d "$SAVANT/.agents/skills/$s" ]; then mv "$SAVANT/.agents/skills/$s" "$EVID/backup/skills/$s"; else : > "$EVID/backup/skills/$s.ABSENT"; fi
  cp -R "$PERK_SRC/skills/$s" "$SAVANT/.agents/skills/$s"
done
ls "$EVID/backup/skills"
```

(The released 3.2.0 package has neither `objectiveRefinement.ts` nor `node_context_reference` —
the three greps prove the swap took.)

### Step 4 — fixture + readiness + confirmation (executor)

```bash
source "$EVID/env.sh"
mkdir -p "$SAVANT/sandbox-refinement-gate"
cat > "$SAVANT/sandbox-refinement-gate/fixture.py" <<'EOF'
"""SANDBOX fixture for the perk refinement live gate — disposable, not savant code."""


def greet(name: str) -> str:
    return f"hello, {name}"
EOF
shasum -a 256 "$SAVANT/sandbox-refinement-gate/fixture.py"
(cd "$SAVANT" && "$PERK_BIN" doctor --verify) 2>&1 | tee "$EVID/doctor.txt"
```

Expect Linear auth/team/labels/scopes/states OK, `extension-install` present, `cli-version` OK,
and a `skills-manifest` drift line (expected under the spoof; recorded; never `--fix`). Then the
**operator workspace confirmation** (quoted verbatim in the record): "`perk doctor --verify` in
savant reports Linear user `<user>`, team `SAV`. perk will create one Project
(`SANDBOX perk refinement gate $TS — delete me`), two node-issues, one metadata sentinel issue and
comments in that team, and trash them at teardown. Confirm." No confirmation ⇒ INCOMPLETE path
(`restore-savant.sh` first).

### Step 5 — create + claim + inventory (executor)

```bash
source "$EVID/env.sh"; cd "$SAVANT"
cat > "$EVID/objective-body.md" <<EOF
# SANDBOX perk refinement gate $TS — delete me

Disposable dogfood objective for the perk objective-refinement live gate. Not savant work. Trash after the run.
EOF
ROADMAP='[{"id":"1.1","slug":"sandbox-greet","description":"SANDBOX: add sandbox-refinement-gate/fixture.py exposing greet(name: str) -> str returning hello, <name>.","depends_on":[]},{"id":"1.2","slug":"sandbox-farewell","description":"SANDBOX: add farewell(name: str) -> str beside greet in sandbox-refinement-gate/fixture.py, mirroring greet'"'"'s signature and return shape.","depends_on":["1.1"]}]'
"$PERK_BIN" objective create --body "$EVID/objective-body.md" --title "SANDBOX perk refinement gate $TS — delete me" --roadmap "$ROADMAP" --json | tee "$EVID/create.json"
echo "OBJ=\"$(jq -r .objective.id "$EVID/create.json")\"" >> "$EVID/env.sh"; source "$EVID/env.sh"
"$PERK_BIN" objective node "$OBJ" --node 1.1 --status planning --json | tee "$EVID/claim-1.1.json"
"$PERK_BIN" objective show "$OBJ" --json | tee "$EVID/show-before.json"
jq -n --arg id "$OBJ" '{query:"query($id:String!){ project(id:$id){ id name url issues{ nodes{ id identifier title } } } }",variables:{id:$id}}' > "$EVID/q-project.json"
linear_gql "$EVID/q-project.json" | tee "$EVID/inventory-before.json"
echo "NODE12=\"$(jq -r '.data.project.issues.nodes[] | select(.title | test("1\\.2")) | .identifier' "$EVID/inventory-before.json")\"" >> "$EVID/env.sh"; source "$EVID/env.sh"; echo "$NODE12"
```

(If the `1.2` node-issue title does not carry `1.2`, pick it from `show-before.json`'s node order
against the inventory titles and record the choice.) Expect `show-before.json`: 1.1 `planning`,
1.2 `pending`.

### Step 6 — the operator leg scripts (executor writes; literals substituted at write time)

```bash
source "$EVID/env.sh"
cat > "$EVID/leg-refine.sh" <<EOF
#!/bin/bash
cd "$SAVANT"
export PERK_BIN="$PERK_BIN"
exec "\$PERK_BIN" objective refine "$OBJ" --node 1.2 --no-sync 2> >(tee "$EVID/refine-launch.stderr" >&2)
EOF
cat > "$EVID/leg-plan.sh" <<EOF
#!/bin/bash
cd "$SAVANT"
export PERK_BIN="$PERK_BIN"
exec "\$PERK_BIN" objective plan "$OBJ" --no-sync 2> >(tee "$EVID/plan-launch.stderr" >&2)
EOF
cat "$EVID/leg-refine.sh" "$EVID/leg-plan.sh"
```

The executor prints the exact launch line for the operator:
`bash /tmp/perk-linear-gate-evidence-<TS>/leg-refine.sh`.

**Leg L1–L2 (operator, own terminal):** run `bash <EVID>/leg-refine.sh`. In the session: let the
model ground and draft; when it grills, steer with: "Record explicitly, as an assumption a later
plan must re-verify, that `sandbox-refinement-gate/fixture.py` defines `greet(name: str) -> str`
and that 1.2's `farewell` mirrors that signature. Keep it short." Approve in Plannotator. Exit pi
after the turn ends. (A save through the wrong CLI fails loudly — the released 3.2.0 has no
`refinement-save` worker — so a successful save is also spoof-effectiveness evidence.)

### Step 7 — E1/E2 (executor)

```bash
source "$EVID/env.sh"
RID=$(cd "$SAVANT/.perk/workflow/scratch/runs" && ls -t | while read -r d; do [ -f "$d/objective-refinement-context.json" ] && jq -e --arg o "$OBJ" '.target.identity.objective_id == $o' "$d/objective-refinement-context.json" >/dev/null && { echo "$d"; break; }; done)
echo "REFINE_RID=\"$RID\"" >> "$EVID/env.sh"; source "$EVID/env.sh"; echo "$REFINE_RID"
cp "$SAVANT/.perk/workflow/scratch/runs/$REFINE_RID/data/objective-refinement-draft.json" "$EVID/"
jq -n --arg id "$NODE12" '{query:"query($id:String!){ issue(id:$id){ id identifier url comments{ nodes{ id createdAt body } } } }",variables:{id:$id}}' > "$EVID/q-comments.json"
linear_gql "$EVID/q-comments.json" > "$EVID/comments-after-refine.json"
"$PY" - "$EVID/comments-after-refine.json" <<'PY'
import json, sys
nodes = json.load(open(sys.argv[1]))["data"]["issue"]["comments"]["nodes"]
first = lambda c: c["body"].split("\n", 1)[0]
ref = [c["id"] for c in nodes if first(c).startswith(("`perk:objective-refinement:v1:", "<!-- perk:objective-refinement:v1:"))]
plan = [c["id"] for c in nodes if "perk:metadata-block:plan-body" in first(c)]
print("comments:", len(nodes), "refinement:", ref, "plan-body:", plan)
PY
```

E1 passes when `refinement:` lists exactly one id and `plan-body:` is empty; append
`REFINE_COMMENT="<that id>"` to `env.sh`. Then:

```bash
source "$EVID/env.sh"; cd "$SAVANT"
"$PERK_BIN" objective refine-context "$OBJ" --node 1.2 --run-id "$REFINE_RID" --json > "$EVID/refine-context-readback.json"
"$PY" - "$EVID/refine-context-readback.json" "$EVID/objective-refinement-draft.json" <<'PY'
import hashlib, json, sys
prior = json.loads(json.load(open(sys.argv[1]))["context_json"])["prior"]["markdown"]
draft = json.load(open(sys.argv[2]))["markdown"]
h = lambda s: hashlib.sha256(s.encode()).hexdigest()
print("EQUAL" if prior == draft else "DIFFERENT", "readback", h(prior), "reviewed", h(draft))
PY
```

E2 passes on `EQUAL` (both lines recorded verbatim).

### Step 8 — setup for the plan leg (executor)

```bash
source "$EVID/env.sh"; cd "$SAVANT"
"$PY" - "$SAVANT/sandbox-refinement-gate/fixture.py" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); p.write_text(p.read_text().replace("def greet(", "def salute("))
PY
shasum -a 256 "$SAVANT/sandbox-refinement-gate/fixture.py"; grep -n "def " "$SAVANT/sandbox-refinement-gate/fixture.py"
"$PERK_BIN" objective node "$OBJ" --node 1.2 --description "SANDBOX: add farewell(name: str) -> str beside salute in sandbox-refinement-gate/fixture.py (greet was renamed to salute), mirroring salute's signature and return shape." --json | tee "$EVID/describe-1.2.json"
"$PERK_BIN" objective node "$OBJ" --node 1.1 --status done --json | tee "$EVID/done-1.1.json"
"$PERK_BIN" objective next "$OBJ" --json | tee "$EVID/next.json"
"$PERK_BIN" objective node-engagement "$OBJ" --node 1.2 --json > "$EVID/node-engagement-pre-plan.json"
jq -r '.refinement.status, .refinement.file.path' "$EVID/node-engagement-pre-plan.json"
cp "$(jq -r .refinement.file.path "$EVID/node-engagement-pre-plan.json")" "$EVID/refinement-pre-plan.md"; grep -n "source_changed:" "$EVID/refinement-pre-plan.md"
```

Expect `next.json` → `1.2`; E3a: `present` + the `source_changed: yes —` line.

**Leg L3–L8 (operator, own terminal):** run `bash <EVID>/leg-plan.sh` (default selection). In the
session (savant's `[workflow] plan_authoring` grill applies — answer briefly): the model pages
`refinement.md` and plans 1.2; if its Assumptions do not explicitly say the `greet` assumption is
obsolete (the live tree has `salute`), nudge once: "State explicitly which refinement assumption
you discard and why." Approve in Plannotator → the plan saves. Exit pi.

### Step 9 — E3b/E5–E9 (executor)

```bash
source "$EVID/env.sh"; cd "$SAVANT"
RID=$(cd "$SAVANT/.perk/workflow/scratch/runs" && ls -t | while read -r d; do [ -f "$d/node-context/$OBJ/1.2/refinement.md" ] && { echo "$d"; break; }; done)
echo "PLAN_RID=\"$RID\"" >> "$EVID/env.sh"; source "$EVID/env.sh"; echo "$PLAN_RID"
grep -n "marking node 1.2 planning\|reading node context\|read node context" "$EVID/plan-launch.stderr"
cp "$SAVANT/.perk/workflow/scratch/runs/$PLAN_RID/node-context/$OBJ/1.2/refinement.md" "$EVID/refinement-plan-run.md"; grep -n "source_changed:" "$EVID/refinement-plan-run.md"
cp "$SAVANT/.perk/workflow/scratch/runs/$PLAN_RID/data/plan-draft.md" "$EVID/plan-draft.md"; grep -n -i "greet\|salute\|obsolete\|discard" "$EVID/plan-draft.md"
"$PERK_BIN" objective show "$OBJ" --json > "$EVID/show-after.json"; jq '.nodes[] | {id, status, pr}' "$EVID/show-after.json"
linear_gql "$EVID/q-comments.json" > "$EVID/comments-after-plan.json"
"$PY" - "$EVID/comments-after-plan.json" <<'PY'
import json, sys
nodes = json.load(open(sys.argv[1]))["data"]["issue"]["comments"]["nodes"]
first = lambda c: c["body"].split("\n", 1)[0]
ref = [c["id"] for c in nodes if first(c).startswith(("`perk:objective-refinement:v1:", "<!-- perk:objective-refinement:v1:"))]
plan = [c["id"] for c in nodes if "perk:metadata-block:plan-body" in first(c)]
print("comments:", len(nodes), "refinement:", ref, "plan-body:", plan, "distinct:", bool(ref and plan and set(ref).isdisjoint(plan)))
PY
"$PERK_BIN" objective node-engagement "$OBJ" --node 1.2 --json > "$EVID/node-engagement-post-claim.json"; jq -r .refinement.status "$EVID/node-engagement-post-claim.json"
```

E5: the `marking node 1.2 planning` line number precedes the `reading node context` line. E3b:
`source_changed: yes —`. E6: the Assumptions sentence discarding the `greet` assumption, quoted
verbatim. E7: 1.2 `in_progress` with a non-null `pr`. E8: `refinement:` is exactly
`[REFINE_COMMENT]`, `plan-body:` exactly one id, `distinct: True`. E9: `present`.

### Step 10 — teardown + restore + proof (executor; run on EVERY path, and immediately after any failed step)

```bash
source "$EVID/env.sh"
bash "$EVID/teardown-linear.sh"
bash "$EVID/restore-savant.sh"
bash "$EVID/snapshot-savant.sh" after
diff "$EVID/snapshot-before.txt" "$EVID/snapshot-after.txt" && echo "savant restored: snapshots identical"
ls -t "$SAVANT/.perk/workflow/scratch/runs" | head -5 > "$EVID/runs-after.txt"; diff "$EVID/runs-before.txt" "$EVID/runs-after.txt" || echo "(retained run-scratch dirs above — inventoried, regenerable)"
```

L10 passes when `teardown-verify.json` shows `trashed: true` for every node-issue, the sentinel,
and the project (or an entity-not-found error, recorded verbatim), AND the snapshot diff is
empty. Then every excerpt the classification table cites is transcribed into Part B; the record
must stand without `$EVID` (deleted after the record's commit).

## Part B — evidence

_Not yet executed. Filled per leg (verbatim excerpts) after the live gate runs._

## Criteria classification

| id | criterion | classification | evidence pointer / named test |
|---|---|---|---|
| L1 | cold `perk objective refine --node 1.2` → approve → exactly one refinement comment | unobserved — NOT PASSED (provisional) | E1 |
| L2 | full read-back equals the reviewed Markdown | unobserved — NOT PASSED (provisional) | E2 |
| L3 | node description changed → `source_changed: yes` rendered | unobserved — NOT PASSED (provisional) | E3a / E3b |
| L4 | node made plannable through `perk objective node` (human surface); default selection picks 1.2 | unobserved — NOT PASSED (provisional) | step 8 `next.json` + E5 |
| L5 | planning transition observed before the advisory read | unobserved — NOT PASSED (provisional) | E5 |
| L6 | the planner explicitly discards the planted obsolete assumption | unobserved — NOT PASSED (provisional) | E6 |
| L7 | real `plan_draft` → `plan_review` → save | unobserved — NOT PASSED (provisional) | E7 |
| L8 | distinct plan and refinement comments | unobserved — NOT PASSED (provisional) | E8 |
| L9 | refinement still readable after the claim | unobserved — NOT PASSED (provisional) | E9 |
| L10 | teardown with inventory: every created Linear entity trashed; the four restored savant surfaces + the fixture dir hash-identical to the pre-gate snapshot; retained run-scratch dirs inventoried | unobserved — NOT PASSED (provisional) | step 10 |
| O1 | denial saves nothing | offline-pinned | `objectiveRefinement.test.ts` "plannotator arm: a denial saves nothing and redirects to the draft tool", "plan_review first-party approval saves the artifact bytes through the worker and terminates; deny/skip never save" |
| O2 | encodings / fences / long lines | offline-pinned | `test_select_save_read_replace_and_retry`, `test_phase1_gate_linear_refinement_persistence`, `test_canonical_json_escapes_non_ascii_and_line_separators`, `test_round_trip_html_and_inline_forms_with_full_field_conversion`, `TestSnapshotRefinement::{test_reports_a_line_above_the_pi_bound, test_multibyte_block_is_byte_exact, test_unicode_encode_error_arm_downgrades_the_same_way}`, `test_paged_files.py::test_measure_text_reports_a_line_above_the_pi_bound`, `test_perk_objective_plan_sole_carried_detail` |
| O3 | warm re-refinement + stale-candidate refusal | offline-pinned | `objectiveRefinement.test.ts` "/objective-refine (warm): unbound session …", "…draft rewritten while the review is pending … stale-approval", "…context re-prepared … blocks the late approval"; `TestGuardedUpsert::test_stale_expectations_refuse_without_writing`; `TestServiceOverLinear::test_pre_write_changes_refuse_without_mutation`; `test_precheck_precedence_identity_then_eligibility_then_source`; `test_guarded_upsert_codes_pass_through`; `test_default_selection_skips_valid_and_stale_records_and_orders_1_2_before_1_10` |
| O4 | stacked neutrality | offline-pinned | `test_phase1_gate_linear_refinement_persistence[stacked]`, `test_selection_is_delivery_independent_and_never_reconstructs_the_train`, `test_cold_ordering_stacked_positioned_pointer_is_absolute_invoking_root_path` |
| O5 | post-claim `node_ineligible` refusal | offline-pinned | `test_phase1_gate_linear_refinement_persistence` (final step), `test_reads_survive_done_and_skipped_while_authoring_refuses`, `test_refinement_save_worker_refuses_missing_mismatched_and_ineligible_inputs` |
| O6 | plan/refinement interleaving | offline-pinned | `test_coexistence_with_real_plan_and_plan_comment_exclusion`, `test_adoption_never_overwrites_a_refinement_carrying_a_plan_example`, `test_planning_after_the_final_check_leaves_an_inert_late_refinement` |
| O7 | warm consumption path | offline-pinned | `prose.test.ts` "factoryGuidance instructs the node-context read (backend-neutral, both backends)", `objectivePlanning.test.ts` "/objective-plan (github) injects no linear clause, runs no fetch, and carries the node-context read", `test_present_arm_writes_the_file_under_the_live_run`, `test_detail_contract_present`, `test_perk_objective_plan_sole_carried_detail` |
| U | GitHub carrier; `RATELIMITED`; live warm refine; live denial / Direct Edits; live long-line paging; the attachment lifecycle beyond this run's writes; a released-artifact (non-spoofed) consumer install | unobserved — NOT PASSED | named residuals (see Unobserved / residuals) |

### The offline rows, shown green

Re-run in `PERK_SRC` (whose code equals `main` `51507710` — see Context) with `-n0`; the O-row
ids above map onto these cases:

```
$ uv run pytest -n0 -v <the 23 ids below>
tests/test_linear_refinement.py::test_phase1_gate_linear_refinement_persistence[incremental] PASSED
tests/test_linear_refinement.py::test_phase1_gate_linear_refinement_persistence[stacked] PASSED
tests/test_linear_refinement.py::TestServiceOverLinear::test_select_save_read_replace_and_retry PASSED
tests/test_linear_refinement.py::TestServiceOverLinear::test_pre_write_changes_refuse_without_mutation PASSED
tests/test_linear_refinement.py::TestServiceOverLinear::test_coexistence_with_real_plan_and_plan_comment_exclusion PASSED
tests/test_linear_refinement.py::TestServiceOverLinear::test_reads_survive_done_and_skipped_while_authoring_refuses PASSED
tests/test_linear_refinement.py::TestServiceOverLinear::test_adoption_never_overwrites_a_refinement_carrying_a_plan_example PASSED
tests/test_linear_refinement.py::TestServiceOverLinear::test_planning_after_the_final_check_leaves_an_inert_late_refinement PASSED
tests/test_linear_refinement.py::TestGuardedUpsert::test_stale_expectations_refuse_without_writing PASSED
tests/test_objective_refinement.py::TestCanonicalEncodings::test_canonical_json_escapes_non_ascii_and_line_separators PASSED
tests/test_objective_refinement.py::TestRenderAndParse::test_round_trip_html_and_inline_forms_with_full_field_conversion PASSED
tests/test_objective_refinement.py::TestSelectRefinementTarget::test_default_selection_skips_valid_and_stale_records_and_orders_1_2_before_1_10 PASSED
tests/test_objective_refinement.py::TestSaveNodeRefinement::test_precheck_precedence_identity_then_eligibility_then_source PASSED
tests/test_objective_refinement.py::TestSaveNodeRefinement::test_guarded_upsert_codes_pass_through[unsupported_backend-unsupported_backend] PASSED
tests/test_objective_refinement.py::TestSaveNodeRefinement::test_guarded_upsert_codes_pass_through[invalid_input-invalid_input] PASSED
tests/test_objective_refinement.py::TestSaveNodeRefinement::test_guarded_upsert_codes_pass_through[malformed_comment-malformed_refinement] PASSED
tests/test_objective_refinement.py::TestSaveNodeRefinement::test_guarded_upsert_codes_pass_through[ambiguous_comment-ambiguous_refinement] PASSED
tests/test_objective_refinement.py::TestSaveNodeRefinement::test_guarded_upsert_codes_pass_through[stale_comment-stale_refinement] PASSED
tests/test_objective_refinement.py::TestSaveNodeRefinement::test_guarded_upsert_codes_pass_through[backend_error-backend_error] PASSED
tests/test_objective_refinement.py::TestSaveNodeRefinement::test_guarded_upsert_codes_pass_through[write_unverified-write_unverified] PASSED
tests/test_objective_refine_cmd.py::test_selection_is_delivery_independent_and_never_reconstructs_the_train[None] PASSED
tests/test_objective_refine_cmd.py::test_selection_is_delivery_independent_and_never_reconstructs_the_train[stacked] PASSED
tests/test_objective_refine_cmd.py::test_refinement_save_worker_refuses_missing_mismatched_and_ineligible_inputs PASSED
tests/test_objective_node_context.py::TestSnapshotRefinement::test_reports_a_line_above_the_pi_bound PASSED
tests/test_objective_node_context.py::TestSnapshotRefinement::test_multibyte_block_is_byte_exact PASSED
tests/test_objective_node_context.py::TestSnapshotRefinement::test_unicode_encode_error_arm_downgrades_the_same_way PASSED
tests/test_paged_files.py::test_measure_text_reports_a_line_above_the_pi_bound PASSED
tests/test_objective_node_engagement_cmd.py::test_present_arm_writes_the_file_under_the_live_run PASSED
tests/test_objective_node_engagement_cmd.py::test_detail_contract_present PASSED
tests/test_objective_plan_cmd.py::test_cold_ordering_stacked_positioned_pointer_is_absolute_invoking_root_path PASSED
tests/test_skill_semantic_contracts.py::test_perk_objective_plan_sole_carried_detail PASSED
============================== 31 passed in 3.51s ==============================
```

```
$ node --test extension/pi/v1/objectiveRefinement.test.ts extension/authoring/objective/prose.test.ts extension/pi/v1/objectivePlanning.test.ts
✔ factoryGuidance instructs the node-context read (backend-neutral, both backends)
✔ /objective-plan (github) injects no linear clause, runs no fetch, and carries the node-context read
✔ plan_review first-party approval saves the artifact bytes through the worker and terminates; deny/skip never save
✔ plannotator arm: a denial saves nothing and redirects to the draft tool
✔ plannotator arm: a draft rewritten while the review is pending blocks the late approval — stale-approval, worker never invoked
✔ plannotator arm: a context re-prepared while the review is pending blocks the late approval — the context digest, worker never invoked
✔ /objective-refine (warm): unbound session → worker context imported byte-exact, stage entered, gate scoped, guidance driven
✔ /objective-refine (warm): refusals leave state untouched — bad args, objective_required, bound_session, busy, worker failure, digest mismatch
ℹ tests 101
ℹ pass 101
ℹ fail 0
```

## Inventory + teardown proof

_Filled by Part B: Linear entities with `trashed` flags; the `snapshot-before` / `snapshot-after`
diff result; retained run-scratch dirs by path._

## Deviations

- **Gate host.** The objective's node text asked for "a separate clone configured for Linear";
  the gate ran in the operator's real Linear consumer repo (`savant`, team `SAV`) with a
  two-plane spoof from the implementation worktree — the CLI as `PERK_BIN`, the extension as an
  `npm pack` of the worktree swapped into the gitignored package dir, the two door skills copied
  into the gitignored skills dir — never a release, a clone, or a change to savant's tracked
  tree. Every version comparison is satisfied because the checkout and the released package are
  both `3.2.0`; the provenance value is therefore the `PERK_SRC` HEAD SHA + the tarball SHA-256,
  never the version string.
- **Prose-map carve-out.** The node text asked to route the refine-door units so the opt-in
  carve-out is green again; #2346 landed that routing before this node was planned. At this
  node's start the carve-out was nonetheless red by exactly one *generated* line:
  `docs/design/prose-prompt-map.md` lagged `prose-prompt-map.yaml` by the
  `render_node_refinement` relation (#2344 added the yaml relation; #2346 regenerated the
  Markdown from a base that lacked it — a merge skew, not a routing gap). This node ran the
  deterministic `perk-dev prose-map sync` (one line added; no yaml, taxonomy or pin change) and
  then recorded `just prose-review-test` (553 passed) + `just prose-review-check` (exit 0) green.
- _(further deviations filled by Part B — e.g. whether the one permitted planner nudge was used)_

## Unobserved / residuals

- The GitHub refinement carrier (Phase 2) — `unsupported_backend` at every door remains the
  contract.
- Linear `RATELIMITED` behavior under refinement traffic.
- A live **warm** refine pass (`/objective-refine`) — offline-pinned only (O3).
- A live denial or a Plannotator Direct-Edits approval on a refinement — offline-pinned only
  (O1).
- Live long-line paging of a refinement above the pi read bound — offline-pinned only (O2).
- The attachment lifecycle beyond this run's own writes, and `project_issues_for_refinement`'s
  `pageInfo` selection under more than one page of node-issues.
- A released-artifact (non-spoofed) consumer install of this code.

## Recovery

If the implement session dies mid-gate, the operator runs, by hand and in either order as
needed:

```bash
bash /tmp/perk-linear-gate-evidence-<TS>/teardown-linear.sh && bash /tmp/perk-linear-gate-evidence-<TS>/restore-savant.sh
```

Both drivers are idempotent and safe from every partial state (no `create.json` ⇒ nothing to
trash; no backup ⇒ nothing to restore).
