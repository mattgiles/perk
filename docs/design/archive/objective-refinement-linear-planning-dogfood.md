# Gate record: objective-node refinement — the authenticated Linear refine→plan run

**Status:** validation record (the archive gate/evidence genre) for Objective *Consume node
refinements in planning and enable the GitHub carrier*, Phase 1 — the authenticated Linear
refine→plan gate over the shipped doors (§8.68) + consumption (§8.26).

**Gate verdict:** **PASS** — every L-criterion observed live (Part B) and every O-criterion's named
tests green at the record's tree (below); executed 2026-09-10 (UTC 01:40–02:05).

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
| gate host | the operator's `savant` checkout (`/Users/mattgiles/dev/roivant/savant`, Linear team `SAV`, review provider `plannotator-plan`) — branch `staging`, HEAD `42fb989c1cac872771321f88bf6eb401bf19f886`, `git status --porcelain` empty before and after |
| `PERK_SRC` (the implementation worktree; THE provenance value) | `.worktrees/plan-2347` at HEAD `5aaecdabc017501706ef59bb9acc80c5bbdd3760` (this record's Part-A commit) · `git status --porcelain` empty · `merge-base --is-ancestor 5c392fa5 HEAD` → `contains #2344` |
| code under test | byte-identical to `main` at `5150771066986218ccd3d61e8a255d9035ad15d8` (#2346; contains #2344 `5c392fa5`) in `src/`, `extension/`, `prompts/`, `tests/`, `skills/perk-objective-*`, `shared/{registry,bindings,providers}.yaml`, `shared/schemas/`, `shared/fixtures/`, `package.json`, `pyproject.toml` (`git diff --stat 51507710 -- <those paths>` empty at commit A and at this record's commit) — this node is docs-only |
| spoof tarball SHA-256 | `12dcf7c54ee4f54bbaba65bb8eb195877e98db722dcdde3ab1f0f4da45c31d90  mgiles-perk-3.2.0.tgz` (`npm pack` of `PERK_SRC`) |
| evidence dir | `/tmp/perk-linear-gate-evidence-20260910T014041Z` (`TS=20260910T014041Z`; deleted after this record's commit — every cited excerpt is transcribed below) |
| sandbox objective | Linear Project `f61dd894-d891-4c7d-9ee0-b9978a5c4233` “SANDBOX perk refinement gate 20260910T014041Z — delete me”; node-issues `SAV-581` (1.1), `SAV-582` (1.2), sentinel `SAV-580` — all trashed at teardown |
| `"$PERK_BIN" --version` | `perk 3.2.0` (== savant's `.perk/required-perk-version`) |
| `pi --version` | `0.85.1` |
| Node / uv / jq | `v26.3.0` / `uv 0.12.3` / `jq-1.7.1-apple` |
| operator confirmation | asked before `perk objective create` with the Part-A wording (user `Matt Giles`, team `SAV`, the entities to be created and trashed); answered verbatim: “Confirm — create in SAV (Recommended)” |
| deviations | (1) the gate host is the operator's Linear consumer repo with a two-plane spoof, not a clone; (2) prose-map routing already landed in #2346 — the one-line regeneration this node performed; (3) `doctor --verbose` in place of the nonexistent `--verify`; (4) the skill symlink, the executor run-id inheritance, the abandoned first refine launch — all in Deviations |

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

Executed 2026-09-10 exactly as Part A (deviations listed in their own section). Every excerpt
below is verbatim from the evidence dir; secrets appear only as the `linear_gql` function name.

### Steps 1–4 — drivers, snapshot, spoof, readiness

```
$ source "$EVID/env.sh"; "$PERK_BIN" --version; "$PERK_BIN" objective refine --help >/dev/null && echo "refine door present"
perk 3.2.0
refine door present
$ git -C "$PERK_SRC" rev-parse HEAD; git -C "$PERK_SRC" status --porcelain
5aaecdabc017501706ef59bb9acc80c5bbdd3760
$ bash "$EVID/restore-savant.sh"; bash "$EVID/teardown-linear.sh"      # smoke on the untouched state
restore-savant: done
teardown-linear: no objective was created
$ git -C "$SAVANT" rev-parse --abbrev-ref HEAD; git -C "$SAVANT" rev-parse HEAD
staging
42fb989c1cac872771321f88bf6eb401bf19f886
$ bash "$EVID/snapshot-savant.sh" before
snapshot before:      222 lines
$ tail -3 "$EVID/snapshot-before.txt"
ABSENT .agents/skills/perk-objective-refine
4084c9ee12ca14b1022d5063a20ff05e7beac104d424c2ff66d9b34f67a4a9d9  .perk/workflow/plan-ref.json
ABSENT sandbox-refinement-gate
$ shasum -a 256 "$EVID/spoof/mgiles-perk-3.2.0.tgz"
12dcf7c54ee4f54bbaba65bb8eb195877e98db722dcdde3ab1f0f4da45c31d90  .../spoof/mgiles-perk-3.2.0.tgz
$ grep -c '"version": "3.2.0"' "$PKG/package.json"; test -f "$PKG/extension/pi/v1/objectiveRefinement.ts" && echo "refine extension present"; grep -c node_context_reference "$PKG/prompts/stages/objective-plan/seed.md"
1
refine extension present
2
$ # the backed-up released package, for contrast:
$ test -f "$EVID/backup/perk-npm-3.2.0/extension/pi/v1/objectiveRefinement.ts" || echo "objectiveRefinement.ts ABSENT in released"; grep -c node_context_reference "$EVID/backup/perk-npm-3.2.0/prompts/stages/objective-plan/seed.md"
objectiveRefinement.ts ABSENT in released
0
$ ls "$EVID/backup/skills"
perk-objective-plan            # a symlink into .agents/cache/worktrees/savant-51f1a9872a34/perk/59f0f724…/skills/perk-objective-plan (moved as a link)
perk-objective-refine.ABSENT
$ shasum -a 256 "$SAVANT/sandbox-refinement-gate/fixture.py"
53c82331dadbdaedf2b05c4461ffe384226ac083b20e59d1b48776c39374cbaa  .../sandbox-refinement-gate/fixture.py
$ (cd "$SAVANT" && "$PERK_BIN" doctor --verbose)      # read-only; --verify is not a flag (see Deviations)
   ✓ linear-auth: authenticated as Matt Giles
   ✓ linear-team: team SAV found
   ✓ linear-labels: perk labels present
   ✓ linear-project-scopes: Linear Projects accessible
   ✓ linear-workflow-states: workflow states cover the node-status mirror
   ✓ extension-install: @mgiles/perk installed at the pinned version
   ✓ cli-version: perk CLI 3.2.0 matches the repo's required version
   ✗ subagent-agents: subagent-agents drift — .pi/agents/perk/…: updated; …review-angle-selector.md: removed
   ✗ gitignore-block: gitignore-block drift — .gitignore: updated
   ✗ skills-manifest: skills-manifest drift — .agents/manifest.d/perk.yaml: updated
✗ 3 check(s) failed
```

(The three drift lines are the unreleased tree's managed artifacts differing from the released
3.2.0 materialization in savant — expected under the spoof, recorded, never `--fix`ed; both door
stages run at the repo root with `worktree == "none"`, so no launch re-converges them.)

### Step 5 — create + claim + inventory

```
$ "$PERK_BIN" objective create --body "$EVID/objective-body.md" --title "SANDBOX perk refinement gate $TS — delete me" --roadmap "$ROADMAP" --json
{"success": true, "error_type": null, "objective": {"id": "f61dd894-d891-4c7d-9ee0-b9978a5c4233", "url": "https://linear.app/savantbio/project/sandbox-perk-refinement-gate-20260910t014041z-delete-me-2323330610dc", "existed": false}, "dry_run": false}
$ "$PERK_BIN" objective node "$OBJ" --node 1.1 --status planning --json
{"success": true, "error_type": null, "objective": "f61dd894-d891-4c7d-9ee0-b9978a5c4233", "node": "1.1", "comment_updated": false, "dry_run": false}
$ "$PERK_BIN" objective show "$OBJ" --json | jq -c '.nodes[] | {id, status, pr}'
{"id":"1.1","status":"planning","pr":null}
{"id":"1.2","status":"pending","pr":null}
$ linear_gql "$EVID/q-project.json"
{"data":{"project":{"id":"f61dd894-d891-4c7d-9ee0-b9978a5c4233","name":"SANDBOX perk refinement gate 20260910T014041Z — delete me","url":"…","issues":{"nodes":[{"id":"21170789-d411-45ff-890b-d30fb425c44a","identifier":"SAV-582","title":"1.2: sandbox-farewell"},{"id":"f607b831-84bb-4f91-884d-032cadf00b14","identifier":"SAV-581","title":"1.1: sandbox-greet"},{"id":"7d6c3f93-bc2f-4b41-bf03-b8965abece68","identifier":"SAV-580","title":"Perk: objective metadata"}]}}}}
NODE12=SAV-582
$ "$PERK_BIN" objective refine "$OBJ" --node 1.2 --dry-run --json      # preview only (extra, read-only)
{"success": true, "error_type": null, "objective_id": "f61dd894-d891-4c7d-9ee0-b9978a5c4233", "objective_run_id": "01M24EEC3Z2H8T3MJ7NABHF8RN", "node_id": "1.2", "node_status": "pending", "carrier_identifier": "SAV-582", "carrier_url": "https://linear.app/savantbio/issue/SAV-582/12-sandbox-farewell", "has_prior_refinement": false, "source_changed": false, "advisory": true, "checkout": {"path": "/Users/mattgiles/dev/roivant/savant", "head_sha": "42fb989c1cac872771321f88bf6eb401bf19f886", "dirty": true}, "backend": "linear", "dry_run": true}
```

### Leg L1–L2 — the cold refine door (operator) + E1/E2

`leg-refine.sh` as written (literals substituted):

```bash
#!/bin/bash
cd "/Users/mattgiles/dev/roivant/savant"
export PERK_BIN="/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2347/.venv/bin/perk"
exec "$PERK_BIN" objective refine "f61dd894-d891-4c7d-9ee0-b9978a5c4233" --node 1.2 --no-sync 2> >(tee "/tmp/perk-linear-gate-evidence-20260910T014041Z/refine-launch.stderr" >&2)
```

`refine-launch.stderr` (the saving launch):

```
 ┌─┐┌─┐┬─┐┬┌─
 ├─┘├┤ ├┬┘├┴┐
 ┴  └─┘┴└─┴ ┴   perk v3.2.0
 39 skills · 10 extensions ready
  › preparing refinement context for objective f61dd894-d891-4c7d-9ee0-b9978a5c4233
  ✓ prepared node 1.2 → objective-refinement-context.json
```

The operator steered the planted assumption in with the Part-A sentence, approved in
Plannotator (plain approve), and the session saved. `REFINE_RID=01M24G8SYTV75RFYV4P3KBGQR2`
(`data/objective-refinement-draft.json` present).

**E1** (one `linear_gql` read of `SAV-582`'s comments, filtered by the Part-A snippet):

```
comments: 1 refinement: ['e2d7ad68-e105-4b7b-b082-f09e2116e40c'] plan-body: []
2026-09-10T01:54:34.594Z e2d7ad68-e105-4b7b-b082-f09e2116e40c :: `perk:objective-refinement:v1:af2d5b08b17d8922da7035748dc248641d927e969eede4562803c81e39fa…
```

`REFINE_COMMENT=e2d7ad68-e105-4b7b-b082-f09e2116e40c`.

**E2** (`refine-context` `prior.markdown` vs the reviewed draft artifact's `.markdown`):

```
$ "$PERK_BIN" objective refine-context "$OBJ" --node 1.2 --run-id "$REFINE_RID" --json > "$EVID/refine-context-readback.json"   # exit 0
EQUAL readback b5ddc541ae90b9a8d0eb0be8c775795ebaa26f46a094e0ff180dcccd2e720527 reviewed b5ddc541ae90b9a8d0eb0be8c775795ebaa26f46a094e0ff180dcccd2e720527
```

The planted assumption as saved (the reviewed Markdown's “Assumptions a later plan must
re-verify”, first bullet, verbatim):

> **`sandbox-refinement-gate/fixture.py` still defines `greet(name: str) -> str`, and `farewell`
> mirrors that exact signature** — the file was uncommitted at capture, so 1.1's landed version
> may differ from what was observed here.

### Step 8 — setup for the plan leg + E3a

```
$ shasum -a 256 "$SAVANT/sandbox-refinement-gate/fixture.py"; grep -n "def " "$SAVANT/sandbox-refinement-gate/fixture.py"
f6725e55a6bc494d2bb5fd6460502f63dd687d586d189a18e825f986e84d2113  .../sandbox-refinement-gate/fixture.py
4:def salute(name: str) -> str:
$ "$PERK_BIN" objective node "$OBJ" --node 1.2 --description "SANDBOX: add farewell(name: str) -> str beside salute …" --json
{"success": true, "error_type": null, "objective": "f61dd894-d891-4c7d-9ee0-b9978a5c4233", "node": "1.2", "comment_updated": false, "dry_run": false}
$ "$PERK_BIN" objective node "$OBJ" --node 1.1 --status done --json
{"success": true, "error_type": null, "objective": "f61dd894-d891-4c7d-9ee0-b9978a5c4233", "node": "1.1", "comment_updated": false, "dry_run": false}
$ "$PERK_BIN" objective next "$OBJ" --json
{"success":true,"error_type":null,"next_node":{"id":"1.2","description":"SANDBOX: add farewell(name: str) -> str beside salute in sandbox-refinement-gate/fixture.py (greet was renamed to salute), mirroring salute's signature and return shape.","status":"pending","pr":null,"phase":"Phase 1"}}
$ "$PERK_BIN" objective node-engagement "$OBJ" --node 1.2 --json | jq -c '{engagement_status, refinement, warnings}'
{"engagement_status":"absent","refinement":{"status":"present","file":{"path":"…/.perk/workflow/scratch/runs/01M24EEC3Z2H8T3MJ7NABHF8RN/node-context/f61dd894-d891-4c7d-9ee0-b9978a5c4233/1.2/refinement.md","bytes":3440,"lines":38,"max_line_bytes":574}},"warnings":[]}
$ grep -n "source_changed:\|source_digest:\|saved_at:\|authored:" "$EVID/refinement-pre-plan.md"
6:saved_at: 2026-09-10T01:54:34.594Z (the backend's native last-write time)
7:authored: run 01M24G8SYTV75RFYV4P3KBGQR2 at 2026-09-10T01:52:45Z
9:source_digest: stored f835beeb1080cbfa3eeb514e4e5ac6c537d0fd62e8c4d496643e3288a1b6567a · current 7f7a8f9548f77979400e4834501e4ac639136c5765dc5f537ab7381de57edcef
10:source_changed: yes — the node's fenced source (description/slug/comment/dependencies) changed after this refinement was authored; parts of the advice may be obsolete (it is still delivered in full)
```

### Leg L3–L8 — the cold plan door (operator, default selection) + E3b/E5–E9

`leg-plan.sh` as written:

```bash
#!/bin/bash
cd "/Users/mattgiles/dev/roivant/savant"
export PERK_BIN="/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2347/.venv/bin/perk"
exec "$PERK_BIN" objective plan "f61dd894-d891-4c7d-9ee0-b9978a5c4233" --no-sync 2> >(tee "/tmp/perk-linear-gate-evidence-20260910T014041Z/plan-launch.stderr" >&2)
```

`plan-launch.stderr` (numbered; **E5** = line 7 precedes line 9):

```
     1	 ┌─┐┌─┐┬─┐┬┌─
     2	 ├─┘├┤ ├┬┘├┴┐
     3	 ┴  └─┘┴└─┴ ┴   perk v3.2.0
     4	 39 skills · 10 extensions ready
     5	  › looking up objective #f61dd894-d891-4c7d-9ee0-b9978a5c4233
     6	  ✓ found objective #f61dd894-d891-4c7d-9ee0-b9978a5c4233 — node 1.2
     7	  › marking node 1.2 planning
     8	  ✓ marked node 1.2 planning
     9	  › reading node context
    10	  ✓ read node context — refinement present
```

The operator answered savant's `plan_authoring` grill briefly, approved in Plannotator, and the
plan saved. The one permitted nudge was **not used**: the planner discarded the `greet`
assumption unprompted. `PLAN_RID=01M24GGZ1QEMG2GW985536STJK` (files: `plan.md`,
`session-pointers.json`, `node-context/<obj>/1.2/refinement.md`, `data/plan-draft.md`).

**E3b** (the snapshot the plan run itself minted):

```
$ grep -n "source_changed:" "$EVID/refinement-plan-run.md"
10:source_changed: yes — the node's fenced source (description/slug/comment/dependencies) changed after this refinement was authored; parts of the advice may be obsolete (it is still delivered in full)
```

**E6** — the saved plan (`data/plan-draft.md`, titled “SANDBOX: add `farewell` beside `salute`
in `sandbox-refinement-gate/fixture.py`”), verbatim:

> - The node's advisory refinement (saved 2026-09-10T01:54Z) was authored against the pre-rename
>   shape (`greet`); its `source_changed: yes` flag is confirmed — **the live function is
>   `salute`, not `greet`**. All other refinement claims re-verified below.

and its `## Assumptions / advisory-input status`:

> - The node refinement was fully paged and read (single block, boundary token
>   `b5ddc541ae90b9a8`, no over-limit lines); no advisory warnings were reported. Its
>   `greet`-era observations were discarded as obsolete per its own `source_changed` flag; its
>   remaining claims (file shape, lint scope, unlanded 1.1) were each re-verified against the
>   live tree and configs above.
> - The Linear node-issue (SAV-582) carries no pre-planning human comments beyond the refinement
>   carrier itself.

**E7 / E8 / E9:**

```
$ "$PERK_BIN" objective show "$OBJ" --json | jq -c '.nodes[] | {id, status, pr}'
{"id":"1.1","status":"done","pr":null}
{"id":"1.2","status":"in_progress","pr":"#SAV-582"}
$ linear_gql "$EVID/q-comments.json" > "$EVID/comments-after-plan.json"; "$PY" - … (the Part-A snippet)
comments: 2 refinement: ['e2d7ad68-e105-4b7b-b082-f09e2116e40c'] plan-body: ['7581564c-538a-45b6-b44a-2bbf9a603b6f'] distinct: True
$ "$PERK_BIN" objective node-engagement "$OBJ" --node 1.2 --json | jq -r .refinement.status
present
```

### Step 10 — teardown + restore + proof (L10)

```
$ bash "$EVID/teardown-linear.sh"
{"data":{"issueDelete":{"success":true}}}
{"data":{"issueDelete":{"success":true}}}
{"data":{"issueDelete":{"success":true}}}
{"data":{"projectDelete":{"success":true}}}
{"data":{"issue":{"identifier":"SAV-582","trashed":true}}}
{"data":{"issue":{"identifier":"SAV-581","trashed":true}}}
{"data":{"issue":{"identifier":"SAV-580","trashed":true}}}
{"data":{"project":{"id":"f61dd894-d891-4c7d-9ee0-b9978a5c4233","name":"SANDBOX perk refinement gate 20260910T014041Z — delete me","url":"…","trashed":true,"issues":{"nodes":[]}}}}
$ bash "$EVID/restore-savant.sh"
restore-savant: done
$ bash "$EVID/snapshot-savant.sh" after
snapshot after:      222 lines
$ diff "$EVID/snapshot-before.txt" "$EVID/snapshot-after.txt" && echo "savant restored: snapshots identical"
savant restored: snapshots identical
$ test -f "$PKG/extension/pi/v1/objectiveRefinement.ts" || echo "released package restored (no objectiveRefinement.ts)"; ls "$SAVANT/sandbox-refinement-gate"
released package restored (no objectiveRefinement.ts)
ls: .../sandbox-refinement-gate: No such file or directory
$ git -C "$SAVANT" status --porcelain | wc -l
       0
```

`plan-ref.json` had been rewritten by the plan save (`cmp` against the backup differed) and was
restored from the backup — its pre-gate hash `4084c9ee…` reappears in `snapshot-after.txt`.

## Criteria classification

| id | criterion | classification | evidence pointer / named test |
|---|---|---|---|
| L1 | cold `perk objective refine --node 1.2` → approve → exactly one refinement comment | **observed-live** | E1: `comments: 1 refinement: ['e2d7ad68-…'] plan-body: []` |
| L2 | full read-back equals the reviewed Markdown | **observed-live** | E2: `EQUAL readback b5ddc541… reviewed b5ddc541…` |
| L3 | node description changed → `source_changed: yes` rendered | **observed-live** | E3a (node-engagement before the plan leg) and E3b (the plan run's own snapshot): `source_changed: yes — …` |
| L4 | node made plannable through `perk objective node` (human surface); default selection picks 1.2 | **observed-live** | step 8: `--status done` on 1.1 → `next.json` → `1.2`; `plan-launch.stderr` line 6 `found objective … — node 1.2` with no `--node` |
| L5 | planning transition observed before the advisory read | **observed-live** | E5: line 7 `marking node 1.2 planning` precedes line 9 `reading node context` |
| L6 | the planner explicitly discards the planted obsolete assumption | **observed-live** (no nudge) | E6: “Its `greet`-era observations were discarded as obsolete per its own `source_changed` flag … **the live function is `salute`, not `greet`**” |
| L7 | real `plan_draft` → `plan_review` → save | **observed-live** | E7: 1.2 `in_progress`, `pr: "#SAV-582"`; `data/plan-draft.md` present |
| L8 | distinct plan and refinement comments | **observed-live** | E8: `refinement: ['e2d7ad68-…'] plan-body: ['7581564c-…'] distinct: True` |
| L9 | refinement still readable after the claim | **observed-live** | E9: `present`, `warnings: []` |
| L10 | teardown with inventory: every created Linear entity trashed; the four restored savant surfaces + the fixture dir hash-identical to the pre-gate snapshot; retained run-scratch dirs inventoried | **observed-live** | step 10: four `trashed: true`; `savant restored: snapshots identical`; inventory below |
| O1 | denial saves nothing | offline-pinned | `objectiveRefinement.test.ts` "plannotator arm: a denial saves nothing and redirects to the draft tool", "plan_review first-party approval saves the artifact bytes through the worker and terminates; deny/skip never save" |
| O2 | encodings / fences / long lines | offline-pinned | `test_select_save_read_replace_and_retry`, `test_phase1_gate_linear_refinement_persistence`, `test_canonical_json_escapes_non_ascii_and_line_separators`, `test_round_trip_html_and_inline_forms_with_full_field_conversion`, `TestSnapshotRefinement::{test_reports_a_line_above_the_pi_bound, test_multibyte_block_is_byte_exact, test_unicode_encode_error_arm_downgrades_the_same_way}`, `test_paged_files.py::test_measure_text_reports_a_line_above_the_pi_bound`, `test_perk_objective_plan_sole_carried_detail` |
| O3 | warm re-refinement + stale-candidate refusal | offline-pinned | `objectiveRefinement.test.ts` "/objective-refine (warm): unbound session …", "…draft rewritten while the review is pending … stale-approval", "…context re-prepared … blocks the late approval"; `TestGuardedUpsert::test_stale_expectations_refuse_without_writing`; `TestServiceOverLinear::test_pre_write_changes_refuse_without_mutation`; `test_precheck_precedence_identity_then_eligibility_then_source`; `test_guarded_upsert_codes_pass_through`; `test_default_selection_skips_valid_and_stale_records_and_orders_1_2_before_1_10` |
| O4 | stacked neutrality | offline-pinned | `test_phase1_gate_linear_refinement_persistence[stacked]`, `test_selection_is_delivery_independent_and_never_reconstructs_the_train`, `test_cold_ordering_stacked_positioned_pointer_is_absolute_invoking_root_path` |
| O5 | post-claim `node_ineligible` refusal | offline-pinned | `test_phase1_gate_linear_refinement_persistence` (final step), `test_reads_survive_done_and_skipped_while_authoring_refuses`, `test_refinement_save_worker_refuses_missing_mismatched_and_ineligible_inputs` |
| O6 | plan/refinement interleaving | offline-pinned | `test_coexistence_with_real_plan_and_plan_comment_exclusion`, `test_adoption_never_overwrites_a_refinement_carrying_a_plan_example`, `test_planning_after_the_final_check_leaves_an_inert_late_refinement` |
| O7 | warm consumption path | offline-pinned | `prose.test.ts` "factoryGuidance instructs the node-context read (backend-neutral, both backends)", `objectivePlanning.test.ts` "/objective-plan (github) injects no linear clause, runs no fetch, and carries the node-context read", `test_present_arm_writes_the_file_under_the_live_run`, `test_detail_contract_present`, `test_perk_objective_plan_sole_carried_detail` |
| U | GitHub carrier; `RATELIMITED`; live warm refine; live denial / Direct Edits; live long-line paging; the attachment lifecycle beyond this run's writes; a released-artifact (non-spoofed) consumer install | unobserved — NOT PASSED | named residuals (see Unobserved / residuals) |

### The offline rows, shown green

Run in `PERK_SRC` on the exact tree this record's commit snapshots (code byte-identical to `main`
`51507710` — see Context) with `-n0`; the O-row ids above map onto these cases:

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
============================== 31 passed in 3.93s ==============================
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

**Linear entities created → trashed** (`teardown-verify.json`, re-read independently after the
mutations): Project `f61dd894-d891-4c7d-9ee0-b9978a5c4233` `trashed: true` (its `issues.nodes`
empty); `SAV-582` (1.2) `trashed: true`; `SAV-581` (1.1) `trashed: true`; `SAV-580` (metadata
sentinel) `trashed: true`. Comments written during the run: `e2d7ad68-…` (refinement) and
`7581564c-…` (plan body) on `SAV-582` — gone with the issue.

**Restored savant surfaces** (`diff snapshot-before.txt snapshot-after.txt` empty, 222 lines
each): `.pi/npm/node_modules/@mgiles/perk/` (219 file hashes — the released 3.2.0 package),
`.agents/skills/perk-objective-refine` (`ABSENT` before and after), `.agents/skills/perk-objective-plan`
(a symlink — see Deviations; `readlink` + `SKILL.md` hash identical before/after),
`.perk/workflow/plan-ref.json` (hash `4084c9ee…` before and after), `sandbox-refinement-gate/`
(`ABSENT` before and after); `git status --porcelain` empty before and after.

**Retained (regenerable, gitignored) run-scratch dirs** under
`savant/.perk/workflow/scratch/runs/`, newer than the pre-gate newest (`01M1QBE4NYX8DXY454V271RD6J`):

| dir | files | origin |
|---|---|---|
| `01M24G6KSVH30GW5G57K63MQX2` | 2 | a first refine-door launch (21:51:33Z) that prepared a grounding context and was closed before drafting — no draft, no save (E1 shows one comment) |
| `01M24G8SYTV75RFYV4P3KBGQR2` (+ `.1`) | 4 (+0) | the saving refine-door run (`REFINE_RID`) |
| `01M24EEC3Z2H8T3MJ7NABHF8RN` | 1 | the executor's `node-engagement` read before the plan leg (the run id inherited from the executor's shell — see Deviations) |
| `01M24GGZ1QEMG2GW985536STJK` (+ `.1`) | 4 (+0) | the plan-door run (`PLAN_RID`) |

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
- **`perk doctor --verify` does not exist.** Part A named a `--verify` flag; the CLI runs the
  verify-gated live checks by default (`run_doctor(verify=True)`), so the readiness read was
  `perk doctor --verbose` — read-only, same evidence, never `--fix`.
- **The `perk-objective-plan` skill in savant is a symlink** into `.agents/cache/worktrees/…`
  (delivered by the skills CLI), so the snapshot's `find -type f` records nothing for that
  surface before or after. The spoof moved the link aside and restore moved it back; an
  out-of-script `readlink` + `SKILL.md` hash before/after (identical) strengthens that row.
- **Executor run-id inheritance.** The executor's tool shells run inside a perk session whose
  `PERK_RUN_ID` is `01M24EEC3Z2H8T3MJ7NABHF8RN`; `perk objective create` therefore recorded that
  as the sandbox objective's `objective_run_id`, and the executor's `node-engagement` read wrote
  its snapshot under a scratch dir of that name in savant. An environment artifact of running
  the executor in-session, not a behavior of the code under test; the door legs ran in the
  operator's own terminal with fresh run ids.
- **Two refine launches.** The operator launched `leg-refine.sh` twice about a minute apart
  (the first closed before drafting, after unclear hand-off directions). The abandoned run wrote
  nothing (E1: exactly one comment); it is inventoried above.
- **Contracts name this record by stem, not filename.** `tests/test_contracts_anchors.py::test_no_provenance_vocabulary`
  bans the word “dogfood” anywhere in `shared/contracts.md` (no allowlist), so §8.67 points at
  “the `objective-refinement-linear-planning-*` gate record under `docs/design/archive/`” rather
  than at this file's literal name.
- **No planner nudge.** The one permitted nudge (“State explicitly which refinement assumption
  you discard and why”) was not needed — the plan discarded the `greet` assumption unprompted.

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
