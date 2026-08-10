# Dogfood: stacked publication end-to-end (Objective #1431, Node 2.4)

**Status:** validation record (the `remote-runner-e2e-dogfood` genre) for the stacked-delivery
publication pipeline — a real sacrificial **three-node** stacked objective driven end-to-end in
the designated dogfood repository (`mattgiles/perk` itself), through perk's own doors: §8.45
stacked authoring + capability preflight, §8.46 parent-aware layer execution, §8.47 layer
publication (native stack **create** at layer 2 and **append** at layer 3 — the two distinct REST
mutations in `src/perk/github/stacks.py`), and the §8.44 train read path. Part A is the
repeatable protocol; Part B is the dated captured evidence + defect log. This gate's pass is the
precondition for retiring the `PERK_DEV_STACKED_DELIVERY` development write gate.

**Why three layers, not the two-layer minimum:** a two-layer train registers a native stack once
(`create_stack`, at layer 2) and never exercises `append_to_stack` — the second, distinct REST
mutation (`POST .../stacks/{stack_number}/add`) would go live un-dogfooded. The third layer
strengthens the gate so both mutations are proven before the guard is removed.

**Scope notes (what this record does *not* prove):**

- **The live remote-runner arm is deferred to node 6.2** (whose text already includes "execution
  from a second clone or remote runner"). Pre-merge, the remote path structurally cannot cross
  the gate: `GitHubActionsRunner.dispatch` hardcodes the default branch, remote workers install
  main's perk, main carries the gate until this record's PR merges, and the managed
  `perk-run.yml` forwards no opt-in env. The required non-hermetic arm is satisfied here by the
  **fresh-clone layer-2 implementation** (a clone with no worktrees, no local stack metadata, no
  dispatch cache) plus a **pristine-clone train reconstruction** at the end.
- **Enrollment posture (the honest late gate):** Step 0 proves host schema, merge rules, remote
  base, and atomic-push capability ONLY. `stacks.stack_capability` is host-schema introspection;
  success does not prove per-repository preview enrollment, and the preflight-in-save prints
  nothing on success. Per-repository enrollment is proven by the **layer-2 stack-create mutation
  itself**; an enrollment failure there is a defined blocked outcome that still flows into the
  unconditional teardown.
- **Warm-envelope fields are never evidence.** `/submit`'s warm decoder (`extension/doors/
  submit.ts`) drops `operation_id` and discards raw stdout — operation ids and
  `prepared → completed` transitions are captured from the **journal comments** on the dogfood
  objective issue (the §8.43 marked, schema-versioned comments; `gh issue view <N> --comments`),
  never from the warm envelope.

## Part A — the repeatable protocol

**Execution arm note (first execution):** the authoring and planning saves run **fully scripted**
through the deterministic cold doors (`perk objective create --json --delivery stacked`,
`perk plan save --json --objective-id … --node-id …`) — the same §8.45/§8.35 save paths the warm
flows end in — and the three implement+publish drives run as **headless pi sessions**
(`perk implement <plan> -p`), whose in-session `/submit` is the real warm publication door (the
extension shells the `perk` binary on PATH). The warm *authoring UX* (the `objective_draft
delivery:"stacked"` review line and plannotator approval) is out of this gate's scope — the gate
under proof is publication. This mirrors the fully-scripted arm of
`remote-runner-e2e-dogfood.md`.

**Gate shells.** Every mutating drive runs in a shell with `export PERK_DEV_STACKED_DELIVERY=1`,
set ONLY in these shells and only in `mattgiles/perk` checkouts/clones. The one exception is the
Step-0 negative proof, which deliberately runs env-less.

**Pinned binary (executable provenance).** Every gate drive uses ONE binary installed from this
node's plan worktree at a recorded SHA:

```bash
uv tool install --force --from <node-2.4-worktree-path> perk
```

Record `which perk` + `git -C <worktree> rev-parse HEAD` at every phase boundary (a provenance
row in Part B). During all drives the branch still carries the guard — removal commits happen
only after Part B is complete — so the env opt-in stays required and the provenance claim
("branch @ SHA, guard intact") is exact. Evidence-capture commits (docs-only, Part B) may land on
the branch between phases without reinstalling; any **code** fix (decision-7 co-delivery)
requires reinstall + a fresh recorded SHA + a full restart from Step 0 with a fresh sacrificial
objective. After the gate (any outcome), teardown restores the operator's binary. Never drive
with an unpinned `perk`.

**Fresh clones** are switched to the node branch (`git switch <node-branch>`) and run `npm ci`
before driving (extension parity — the in-session doors run the checkout's extension source; the
worktree-node-modules trap). The pinned global binary serves the Python plane.

**The sacrificial fixture (pinned).** The train edits one throwaway file,
`dogfood/stacked-gate.txt`, never destined for main:

- Node 1.1 creates it containing exactly `stacked dogfood layer 1`.
- Node 1.2 rewrites that line to `stacked dogfood layer 1 -> extended by layer 2`.
- Node 1.3 rewrites it to
  `stacked dogfood layer 1 -> extended by layer 2 -> extended by layer 3`.

Each layer edits its predecessor's exact bytes, so no layer's change can apply from main alone —
parent-awareness is structurally proven, and each layer's recorded diff must show the
predecessor's line in its context.

**Evidence sources are pinned per fact:** PR facts from
`gh pr view <n> --json number,state,isDraft,baseRefName,headRefName,headRefOid`; operation ids +
`prepared → completed` transitions from the objective issue's journal comments; train facts from
`perk objective stack status <N> --json`. Publications go through the real warm `/submit` path;
no warm-envelope field is claimed as evidence.

### Step 0 — preconditions (host capability + guard-held proof; NOT an enrollment proof)

Record expected-vs-observed **verbatim** for the four §8.45 checks, via direct commands:

1. **native-stack (host schema):**
   `gh api graphql -f query='query { __type(name: "PullRequest") { fields { name } } }'` —
   expected: a `stack` field in the list.
2. **merge-rules:** `gh api repos/{owner}/{repo} --jq .allow_squash_merge` (expected `true`) and
   `gh api repos/{owner}/{repo}/rules/branches/main` (expected: no rule of type `merge_queue`).
3. **remote-base:** `git ls-remote origin refs/heads/main` — record the SHA.
4. **atomic-push:** the exact §8.45 probe argv against the observed SHA and the configured push
   URL (`git remote get-url --push origin`):

   ```bash
   git -c push.pushOption= push --atomic --dry-run --no-verify --no-signed \
     --no-follow-tags --recurse-submodules=no --porcelain <push-url> <sha>:refs/heads/main
   ```

Plus two more Step-0 rows:

5. **Informational `stack_for_pr` read (non-gating):** a best-effort REST read of
   `gh api 'repos/{owner}/{repo}/stacks?pull_request=<any-existing-pr>' --include` — response
   captured verbatim. Explicitly non-gating: the endpoint's not-in-a-stack vs not-enrolled
   semantics are undocumented.
6. **Negative proof (guard-held):** one stacked save attempt in an **env-less** shell must
   refuse with `error_type="stacked_delivery_gated"` — after roadmap validation, the adoption
   refusal, and the capability preflight all pass, and **before any store mutation** (no issue
   is created). This is the guard-held evidence for the whole record.

### Step 1 — author the sacrificial stacked objective

From the dev checkout (gate shell, pinned binary): save the three-node roadmap (the pinned
fixture; each node depends on its predecessor) with the explicit stacked choice through the
§8.45 cold door:

```bash
perk objective create --json --title "<sacrificial title>" --body <body.md> \
  --roadmap '<three-node JSON>' --delivery stacked
```

Record: the objective issue number, its `delivery_lineage` (from the issue's objective-header
block), and the roadmap. Enrollment risk note: the save's capability preflight still proves host
schema only — per-repository enrollment is proven at Step 8.

### Step 2 — plan node 1.1

Compose the bounded node-1.1 plan (edit the fixture per the pinned bytes; commit; `/submit`; ask
no questions) and save it linked to the node:

```bash
perk plan save --json --plan-file <plan-1.md> --objective-id <N> --node-id 1.1
```

Record: the plan issue number + the layer-identity header trio
(`objective`/`objective_node`/`delivery_lineage`) from the saved plan header.

### Step 3 — implement node 1.1 locally

From the dev checkout (gate shell): `perk implement <plan-1> -p` — `resolve_worktree` creates the
layer branch from the objective base. Record: the branch name + the operational
parent-checkpoint observation (the worktree's `.perk/workflow/layer-context.json`,
non-authoritative).

### Step 4 — publish layer 1 (inside the Step-3 drive)

The headless drive ends on the real warm `/submit`. Record per the pinned evidence sources: PR
facts via `gh pr view` (draft; base = the objective base), the journal's `prepared → completed`
records + operation id via `gh issue view <N> --comments`. Layer 1 creates no stack membership —
expected and recorded.

### Step 5 — successor readiness

`perk objective stack status <N> --json` → record a blocker-free `next_build_ready` for node
1.2 and layer 1 `publication: published`.

### Step 6 — plan node 1.2

As Step 2, for node 1.2.

### Step 7 — fresh-clone parent-aware implement (the required non-hermetic arm)

A fresh `git clone` of `mattgiles/perk` (no worktrees, no local stack metadata, no dispatch
cache), `git switch <node-branch>`, `npm ci`, gate env exported, pinned binary verified, then
`perk implement <plan-2> -p`. Record that `prepare_stacked_layer` derived the parent (the layer-1
branch) at the verified parent SHA from the reconstructed train (launch progress log + the clone
worktree's `layer-context.json`).

### Step 8 — publish layer 2: the stack CREATE + the enrollment proof

The clone drive's warm `/submit`. Record PR facts (base = the layer-1 branch), the journal
operation id, and the stack `{number, size, position}` observation via
`perk objective stack status <N> --json`. **If registration fails for enrollment/preview
reasons: this is the defined blocked outcome** — capture the failure + any unresolved prepared
operation, then go directly to Step 10 (teardown) and the blocked disposition (this node's PR is
not merged; the node is set `blocked`; no record file ships).

### Step 9 — layer 3: the APPEND proof + pristine-clone verification

Plan node 1.3 (as Step 2, readiness-checked as Step 5), implement locally
(`perk implement <plan-3> -p` from the dev checkout, gate shell), publish via the drive's warm
`/submit` — this exercises `append_to_stack` (the exact missing suffix). Record PR facts (base =
the layer-2 branch) + the journal operation id.

Then **verified registration from a pristine clone**: a THIRD pristine clone (also switched to
the node branch, `npm ci`, pinned binary), `perk objective stack status <N> --json` — record all
three layers `publication: published`, `membership: exact`, contiguous bottom-to-top order,
`published_prefix_len == 3`, no blockers. A publish response alone is never accepted as
membership evidence (an unavailable preview read degrades membership to `unknown`).

### Step 10 — teardown: unconditional, runs on EVERY outcome

Success, blocked halt, or abandoned attempt — no sacrificial residue may outlive the gate in the
production repo. `perk worktree wipe` cannot clean this up later (it requires a provably MERGED
PR; the gate's PRs close unmerged), so teardown owns all residue itself:

1. **Capture first:** every identity + any unresolved-operation state still uncaptured.
2. **Remote:** close all open sacrificial PRs; delete the three remote layer branches; close the
   three plan issues + the dogfood objective issue (each with a pointer to this record — or, if
   blocked, to the node's plan issue).
3. **Local (the dev checkout AND every clone):** `git worktree remove` each sacrificial
   `plan-<N>` worktree + `git worktree prune`; delete local `plan-<N>` branches; delete both
   clone directories; restore any dev-checkout cache state the drives rewrote (the active
   `cache.plan-ref`); restore the operator's `perk` binary.
4. **Census (all must pass and be recorded):** `gh pr view` shows every sacrificial PR CLOSED;
   `gh issue view` shows every sacrificial issue CLOSED;
   `git ls-remote origin 'refs/heads/plan-*'` lists no sacrificial branches; `git worktree list`
   shows no sacrificial worktrees; `git branch --list 'plan-*'` shows no sacrificial locals;
   clone directories absent.
5. **Post-teardown observation (informational):** one `perk objective stack status <N> --json`
   read (expected: closed-PR blockers / no usable train — the census, not this read, is the
   acceptance).

### Failure policy

Any defect at any step gets a defect-log row, then the decision-7 split: **co-deliverable** (the
fix touches only this node's blast radius and changes no cross-plane contract semantics beyond
the planned gate retirement) → fix on the plan branch, reinstall the pinned binary, record the
new SHA, restart the full gate from Step 0 with a fresh sacrificial objective (the failed attempt
stays in Part B as a dated attempt with its defect rows); **structural** → the blocked
disposition (PR not merged, node `blocked`, defect log + identities + teardown attestation posted
on the node's plan issue, no record file, guard stays). A drive that fails for non-perk reasons
(model flakiness, transient network) is re-run and recorded as a dated attempt — it is evidence,
not a defect. Teardown runs regardless.

## Part B — the captured evidence

Executed **2026-08-10** on `mattgiles/perk` (the self-repo). Sacrificial identities: objective
**#1542** (`delivery: stacked`, `delivery_lineage: 01KZP3KVDZCTZJMPE569DQ62ER`), plan issues
**#1543** (node 1.1), *(nodes 1.2/1.3 below)*. The authoring/planning saves ran through the
cold doors and the three drives ran headless (`perk implement <plan> -p`), per Part A's
execution-arm note.

**Provenance (phase boundary: Steps 0–5).** Pinned binary installed from the node-2.4 plan
worktree at `1b11580fb7cc09c496975cd9eddb13c09c51180e` (guard intact — Part A only):
`uv tool install --force --from …/.worktrees/plan-1539 perk` → `which perk` =
`/Users/mattgiles/.local/bin/perk` (`perk 2.3.0`, the uv tool shim).

### Step 0 — preconditions (2026-08-10, dev checkout)

| Check | Expected | Observed |
|---|---|---|
| native-stack (host schema) | `stack` field on `PullRequest` | `["stack","stackEntry"]` (GraphQL introspection, filtered) |
| merge-rules | squash allowed; no `merge_queue` rule | `{"allow_squash_merge":true}`; `gh api repos/mattgiles/perk/rules/branches/main` → `[]` |
| remote-base | a real `refs/heads/main` SHA | `dfa00172ec2d12809db50cab143b08f7edcc4048\trefs/heads/main` |
| atomic-push | no-op `--atomic --dry-run` accepted | `= dfa0017…:refs/heads/main [up to date]` + `Done`, exit 0 (push URL `git@github.com:mattgiles/perk`, exact §8.45 argv) |

- **Informational `stack_for_pr` read (non-gating):**
  `gh api 'repos/mattgiles/perk/stacks?pull_request=1534' --include` (a merged, unstacked PR) →
  `HTTP/2.0 200 OK`, body `[]` — the REST stacks endpoint answers 200 (not 404) for this
  repository; the empty array reads as "in no stack". Not treated as an enrollment proof.
- **Negative proof (guard-held):** the full Step-1 save command run **env-less** →
  `{"success": false, "error_type": "stacked_delivery_gated", "message": "stacked delivery is
  under development; the write path is gated until perk's two-layer publication dogfood gate
  passes."}`, exit 1; the open `perk:objective` list immediately after showed **no new issue**
  (the refusal is checked last, after validation + preflight, before the store mutation).

### Steps 1–5 — authoring, node 1.1, layer-1 publication

- **Step 1 (authoring, §8.45 cold door):** `PERK_DEV_STACKED_DELIVERY=1 perk objective create
  --json --delivery stacked --roadmap '<three-node JSON>' …` →
  `{"success": true, … "objective": {"id": "1542", …, "existed": false}}`. The created header:
  `delivery: stacked`, `delivery_lineage: 01KZP3KVDZCTZJMPE569DQ62ER`; the roadmap block carries
  the three pinned fixture nodes (1.1 → 1.2 → 1.3, each depending on its predecessor).
- **Step 2 (plan node 1.1):** `perk plan save --json --plan-file … --objective-id 1542
  --node-id 1.1` → plan issue **#1543**; envelope `objective_node: {"linked": true, "node":
  "1.1", "status": "in_progress"}`; the saved plan header carries the layer-identity trio
  `objective_id: '1542'`, `objective_node_id: '1.1'`,
  `delivery_lineage: 01KZP3KVDZCTZJMPE569DQ62ER`.
- **Step 3 (local implement):** `PERK_DEV_STACKED_DELIVERY=1 perk implement 1543 -p` (dev
  checkout). Launch progress (the §8.46 parent-aware path):

  ```text
  › reconstructing the delivery train
  ✓ layer 1.1 starts from main @ c7167d3a39c7
  › creating worktree plan-1543 from main @ c7167d3a39c7
  ```

  (main had advanced beyond the Step-0 SHA — PR #1536 merged mid-gate; the layer branches from
  the observed remote base, as designed.) The worktree's operational record
  (`.perk/workflow/layer-context.json`, non-authoritative): `parent_branch: "main"`,
  `parent_sha: "c7167d3a39c7794f6198e4ef14696f07acbc634a"`, `branch: "plan-1543"`,
  `predecessor_plan_id: null`. The drive created the fixture (`stacked dogfood layer 1\n`,
  byte-exact) and committed `68c76f2f Stacked dogfood layer 1: create fixture`.
- **Step 4 (publish layer 1, warm `/submit` inside the drive):**
  - PR facts: `gh pr view 1544` → `{"number": 1544, "state": "OPEN", "isDraft": true,
    "baseRefName": "main", "headRefName": "plan-1543",
    "headRefOid": "68c76f2fc3ee35b0431eb8cc84748848398197f8"}` (draft, base = objective base).
  - Journal (issue #1542 comments): operation **01KZP3RXPPAN8A84B8ZVN2Y4XB**, `prepared`
    (15:13:33Z; `after.pr.base: main`, `after.stack.not_applicable: true`) → `completed`
    (15:13:48Z; `observed: {branch_sha: 68c76f2f…, pr: 1544, stack: null}`). Layer 1 creates no
    stack membership — expected and recorded.
- **Step 5 (successor readiness):** `perk objective stack status 1542 --json` →
  `published_prefix_len: 1`; layer 1.1 `publication: "published"`, `membership:
  "not_applicable"`, `observed_pr_base: "main"` = `expected_pr_base`; `blockers: []`;
  `next_build_ready: {"node_id": "1.2", "ready": true, "reason": null}`.
