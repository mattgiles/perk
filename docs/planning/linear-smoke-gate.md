# The Linear live smoke gate (Objective #252, Node 4.1)

The manual runbook that validates perk's Linear issue backend against a **real** Linear
workspace. The offline regression surface is `tests/test_linear_lifecycle.py` (a stateful
`FakeLinearWorkspace` driving the real `LinearIssueBackend` through the real CLI commands); this
gate covers what no fake can prove: ProseMirror round-trip fidelity, Linear's actual error
shapes, rate-limit behavior, and the GitHub-integration automations.

Run **Mode 1 on a bare workspace first** (perk must stay correct with zero integration/automation
config), then Mode 2 if a GitHub-integration-installed workspace is available. Record what you
observe in the **Recorded observations** section at the bottom — each row feeds a documented
follow-up.

> **Caveat — GitHub Issues Sync.** If the scratch team has Linear's *GitHub Issues* two-way sync
> enabled, perk-created Linear issues will be mirrored into GitHub issues (and vice versa). Use a
> team without Issues Sync; this runbook does not cover sync interactions.

## Prerequisites

- A **scratch Linear team** you can freely pollute (e.g. key `ENG` in a test workspace).
- A personal API key: `export LINEAR_API_KEY=…` (linear.app → Settings → Security & access).
  Environment-only — never in config files (contracts §8.21).
- The committed selection in `.pi/perk.toml`:

  ```toml
  [issues]
  backend = "linear"
  team = "ENG"
  ```

- `perk init` green (converges `npm:pi-mono-linear`). **Note:** `init` has no `--verify` flag; the
  four perk labels (`perk:plan`, `perk:learn`, `perk:consolidated`, `perk:objective`) are ensured
  by `perk doctor --fix` (it creates any missing label).
- `perk doctor` green, including the verify-gated `linear` group (`linear-auth` /
  `linear-team` / `linear-labels`). **Note:** `linear-team` resolves the team by its **key**
  (e.g. `PER`), not its display name — set `[issues] team` to the key.

## Mode 1 — bare workspace (no GitHub integration)

Drive a throwaway plan through the full lifecycle. At each step, verify both the envelope (string
`ENG-*` ids everywhere — contracts §8.21) and the workspace state in the Linear UI.

1. **Plan-save.** `perk plan save --plan-file <plan.md> --run-id $(perk state run-id 2>/dev/null || echo 01SMOKE) --json`
   - The issue is created in the team with label `perk:plan`; `issue.id` is the identifier
     (`ENG-<n>`); `plan_ref.provider == "linear"`.
   - Open the issue in Linear: the description's `plan-header` block and the first comment's
     `plan-body` block use the inline-code sentinel encoding (`` `perk:metadata-block:…` ``) —
     **no** raw `<!-- … -->` or `<details>` artifacts.
2. **Re-save idempotency / ProseMirror round-trip.** Edit the plan file and re-run the same
   `plan-save` (same run id). Verify: same `ENG-<n>` (`existed: true`, `updated: true`), the
   plan-body comment patched in place (not duplicated), and the header block still parseable
   after Linear's ProseMirror re-encoding (the `find_metadata_block` round-trip — THE fidelity
   check this gate exists for).
3. **Implement.** `perk implement ENG-<n>` — worktree/branch `plan-ENG-<n>`; make a trivial
   committed change.
4. **Submit.** `/submit` (or `perk pr submit --json` in the worktree). Verify the PR opens as
   draft and the Linear description's `plan-header` gains `branch` / `pr` / `lifecycle_stage`.
5. **Land.** `/land` (or `perk pr land --json`). Verify:
   - the squash commit message footer is `Plan: ENG-<n> — <url>` (no `Closes #N`, no Linear
     magic words);
   - the plan issue is **explicitly closed** by perk (`plan_issue_closed: true` in the envelope;
     Done in Linear) — on a bare workspace nothing else would close it;
   - pending-learn set.
6. **Learn.** `/learn` with a summary. Verify the `perk:learn` issue (`ENG-<m>`) and the
   back-link comment on the plan issue.
7. **Objective loop.** `perk objective create` (with `--roadmap`), `objective show/next/node`,
   link a plan via the factory (or `plan-save --objective-id ENG-<o> --node-id 1.1`), land it,
   and verify the auto node-done + `perk objective reconcile`'s prose splice survive the
   ProseMirror round-trip (the roadmap table re-render in the body comment stays parseable).
8. **Error-shape capture.** `perk plan resume ENG-9999 --json` (a nonexistent issue): record the
   exact GraphQL error message and any `extensions.code` Linear returns for a missing entity —
   this feeds the `.codes` tightening of the `"not found"` substring tolerance in
   `LinearIssueBackend._issue_or_none` / `_comment_body_or_none`.
9. **Rate limits.** If any step trips RATELIMITED (HTTP 400, `extensions.code == "RATELIMITED"`),
   record the context + headers — this feeds the retry/backoff deferral.

## Mode 2 — GitHub integration installed

Repeat the lifecycle on a team with Linear's GitHub integration (pull-request linking +
workflow automations) and additionally verify:

> **Setup caveat — "installed" ≠ "connected".** The GitHub App being installed on the org/workspace
> is *not* sufficient: the specific repo must be connected to the integration **and mapped to the
> team** (Linear → Settings → Integrations → GitHub), and the GitHub App must have that repo in its
> `selected` repositories. Until that link exists, **zero** PR events reach Linear — no attachment,
> no automation, no linkback — regardless of branch name. Confirm a PR actually attaches before
> trusting a "not observed" result. (Node 1.3 burned ~40 min here: the org had the `linear` App
> installed but the repo↔workspace connection was broken; linking began only after an operator-side
> repair, and a control PR from Linear's own `username/identifier-title` branch format *also* failed
> to link until then — proving it was the connection, not the branch name.)

- **Branch-name auto-link.** Pushing `plan-ENG-<n>` attaches the PR to the Linear issue
  (PR + review state visible on the issue) — the D3 payoff of identifier-shaped worktree names.
  The identifier-shaped `plan-<id>` form auto-links directly; it does **not** need to match
  Linear's configured `username/identifier-title` branch template.
- **Automations coexist.** If the team automations move the issue In Progress on PR open and Done
  on merge, perk's explicit on-land close must be an idempotent no-op beside them (no error, no
  state flapping).
- **Linkback tolerance.** The integration links a PR to the issue as an **attachment** (the issue
  sidebar), **not** a comment, so perk's marker-keyed comment scans are inherently unperturbed —
  the comments surface stays purely perk's own. Verify perk's marker-keyed upserts (run-report
  notes, the objective body comment) still patch their OWN comments and `get_plan_body` still
  resolves (the offline twin `test_foreign_linkback_comment_does_not_perturb_marker_scans` injects
  a synthetic foreign *comment* — stricter than the live integration, which never touches the
  comment stream).
- **Mutation identifier acceptance.** Optionally probe whether mutations (`issueUpdate`,
  `commentCreate.issueId`) accept the human identifier directly — if they reliably do, record
  it: that would let `_uuid_for` simplify to a pass-through. **Resolved (#562, 2026-06-16):** the
  Mode 2 probe came back positive and `_uuid_for` was deleted outright (not a pass-through) — the
  verified mutations take the identifier directly; `issueRelationCreate` keeps UUIDs captured at
  issue-create time.

## Mode 3 — Projects API spike (Objective #548, Node 1.4)

A **measurement** layer (not part of the issue lifecycle): prove the exact Linear **Project**
GraphQL operations the future project-backed `ObjectiveStore` (Phase 3) will depend on, and record
their fidelity, error shapes, and the decisive overview-vs-document storage decision. No production
code — the proven GraphQL documents + observations are the whole deliverable (node 3.1 copies the
documents verbatim; node 3.2 consumes the storage decision; node 3.3 the blocking-relation
symmetry).

**Firing mechanism = inline `LinearClient.request` snippets, no committed script.** Each snippet is
`client = client_from_env(); data = client.request(QUERY, VARS)`; the inline-code markers come from
`perk.plan.render_metadata_block(key, payload, style="inline-code")` and are parsed back with
`perk.plan.find_metadata_block(content, key)` (the same ProseMirror fidelity check Modes 1/2 run for
issue bodies, extended to the Project `content` surface). Resolve the `PER` team UUID via
`teams(filter:{ key:{ eq:"PER" } }){ nodes { id } }` (mirrors `LinearIssueBackend._team_id`). Project
ids are opaque UUIDs — use the UUIDs returned by `projectCreate`/`issueCreate` for all follow-ups.

1. **Project create + overview round-trip (decisive).** `projectCreate(input:{ teamIds, name,
   content })`; record whether `content` is accepted at create (the historical 2024 wrinkle). Build
   an objective-header marker block via `render_metadata_block("perk:objective-header", {…},
   style="inline-code")`, write it through `projectUpdate(id, input:{ content })`, read back via
   `project(id){ content }`, and assert `find_metadata_block(content, "perk:objective-header")`
   returns the original dict. Record **CLEAN** or **MANGLED** (exactly how).
2. **Project document round-trip (unconditional fallback proof).** `documentCreate(input:{
   projectId, title, content })`, read back via `document(id){ content }`, run `find_metadata_block`.
   Record CLEAN/MANGLED identically, then record the recommended storage decision for node 3.2
   (overview if its round-trip is clean; Project document otherwise).
3. **Milestones.** `projectMilestoneCreate(input:{ projectId, name })` twice; list via
   `project(id){ projectMilestones { nodes { id name } } }` (node 4.3 maps phases → milestones).
4. **Issue↔project attachment.** `issueUpdate(id, input:{ projectId })` to attach an existing issue,
   `issueCreate(input:{ teamId, title, projectId })` to create directly in the project; read back via
   `issue(id){ project { id } }` and `project(id){ issues { nodes { id identifier } } }`.
5. **Issue blocking relation.** `issueRelationCreate(input:{ issueId, relatedIssueId, type:
   "blocks" })`; read back via `issue(id){ relations { nodes { type relatedIssue { identifier } } } }`
   (A **blocks** B) and `issue(id){ inverseRelations { nodes { type issue { identifier } } } }`
   (B **blockedBy** A) — the symmetry node 3.3 reconstructs `depends_on` from.
6. **Error-shape capture.** Fire one bogus-id call per operation class (bad `project(id)`,
   `projectMilestoneCreate` with a bad `projectId`, `issueRelationCreate` with a nonexistent
   `relatedIssueId`, bad `document(id)`); record the exact `message` + `extensions.code` and whether
   it matches the issue not-found shape (`INPUT_ERROR` + `"Entity not found:"`) `_is_entity_not_found`
   keys on, or differs. Record any RATELIMITED context if tripped.

Append a dated **Recorded observations** block with one row per operation; record the proven working
GraphQL documents verbatim, and the decisive overview-vs-document storage decision with its evidence.

## Mode 4 — project-backed objective lifecycle (Objective #548, Node 5.1)

A **measurement** layer that drives a real objective **Project** end-to-end against the live Linear
API and proves the project-backed `ObjectiveStore` (`LinearProjectObjectiveStore`, Nodes 3.2–4.3)
**plus** the four Project ops the Mode 3 spike left **not-live-proven** (`set_project_state`,
`list_projects`, `create_project_update`, `_workflow_state_id`). No production code change is
expected — the runbook section + the dated observation block are the whole deliverable (the #562
precedent: a substantive defect is recorded + deferred to a follow-up issue, **not** fixed in-node).

**Prerequisites** are Mode 1's, plus the project readiness probes added in Node 4.2:

- `export LINEAR_API_KEY=…` (environment-only).
- Committed `.pi/perk.toml`: `[issues] backend = "linear"`, `team = "PER"` (the team **key**, never
  the display name).
- `perk init` green, `perk doctor` green — **including** the project readiness probes
  `linear-project-scopes` and `linear-workflow-states` (Node 4.2). If either fails, the project ops
  below will not work (the API key lacks Project scopes, or the team has no started/completed
  workflow states for the `_workflow_state_id` mirror).
- Scratch workspace `Perk-testing`, team key **`PER`**, team UUID
  `2f933a7e-0d05-4424-bea2-0bc79a4c54c9`.

**Smoke roadmap shape** (specify it so the run is reproducible): a **2-phase** roadmap with **≥4
nodes**, including (i) at least one **explicit `depends_on`** edge (to materialize a blocking
relation) and (ii) node ids authored into the `--roadmap` JSON in an order that **differs** from
`node_sort_key` order (so gate 2's deterministic-ordering check is observable). Use this node set,
authored in **scrambled** order (`2.1, 1.1, 2.2, 1.2`):

```json
[
  {"id": "2.1", "description": "Phase 2 first node", "depends_on": ["1.2"]},
  {"id": "1.1", "description": "Phase 1 first node"},
  {"id": "2.2", "description": "Phase 2 second node"},
  {"id": "1.2", "description": "Phase 1 second node", "depends_on": ["1.1"]}
]
```

The throwaway objective markdown (`obj.md`) only needs a `### Phase 1:` / `### Phase 2:` heading
pair so the milestone names enrich, plus a short Reconcilable prose paragraph. Pick a fresh
`--run-id` (`RID`) per full run so idempotency (gate 3) and find-by-run-id are exercised cleanly.

Drive these numbered gates in order. Each gate states the command **and** the exact thing to verify
in the Linear UI + the `--json` envelope.

1. **Create the objective Project.**
   `perk objective create --body obj.md --roadmap '<json above>' --run-id <RID> --json`.
   Verify: `objective.id` is an **opaque Project UUID** (not `PER-*`); `objective.existed == false`.
   In Linear a **Project** is created whose **overview** carries the `objective-header` inline-code
   block + the Reconcilable prose region (`` `perk:objective-reconcilable` `` sentinels), **no**
   roadmap table, and **zero** raw `<!-- … -->` / `<details>` artifacts. There is **one Milestone
   per phase** (enriched `### Phase N:` names), **one node-issue per roadmap node** (each carrying
   an `objective-node` block, attached to its phase milestone), and a **blocking relation** for
   every explicit `depends_on` (dep **blocks** node — check `relations` / `inverseRelations` in the
   UI: `1.1 blocks 1.2`, `1.2 blocks 2.1`). Note the fresh-create **Project Update** posted to the
   project's Updates feed (**live-proves `create_project_update`**).
2. **Deterministic node ordering.** `perk objective show <PROJECT_UUID> --json`. Verify the `nodes`
   array is in **`node_sort_key` order** (`1.1, 1.2, 2.1, 2.2`) — **NOT** Linear's
   connection/reverse-insertion order — even though the roadmap was authored scrambled. Each node's
   `status` and `description` round-trip; `perk objective next <PROJECT_UUID> --json` returns the
   expected next plannable node (`1.1`, the only node with no unmet dependency). **Note:**
   `objective show --json` does **not** serialize `depends_on` (node keys are
   `id`/`description`/`status`/`pr`/`phase`, and `phase` is **derived from the node id**, not read
   from the milestone) — `depends_on` **is** reconstructed from the blocking relations at the store
   level (`get_objective`), so verify the dependency graph via the store or via `next`'s selection
   behavior, not the show envelope.
3. **`list_projects` find-scan (idempotency).** Re-run the **same**
   `perk objective create --body obj.md --roadmap '…' --run-id <RID> --json`. Verify
   `objective.existed == true` and the **same** Project UUID — proving the `list_projects`
   find-by-run-id scan resolves the existing Project (**live-proves `list_projects`**). No second
   Project, no duplicate milestones/node-issues.
4. **Node↔plan unification (the `objective-plan` step).** Pick node `1.1`. Write a trivial
   `plan.md` and run
   `perk plan save --objective-id <PROJECT_UUID> --node-id 1.1 --plan-file plan.md --run-id <RID> --json`.
   Verify: **no new `perk:plan` issue is created** (the node-issue count is unchanged); the
   **node-issue's own description** gains the `plan-header` inline-code block; the plan body lands
   as a **single node-issue comment** (inline-code, **patched in place** on re-save, not
   duplicated); `cache.plan-ref` is stamped at the node-issue; `perk objective show` reports the
   node advanced **`planning → in_progress`**. (The warm `/objective-plan` factory wraps this exact
   save.)
5. **Implement + submit.** `perk implement <node-issue-identifier>` (worktree/branch
   `plan-<identifier>`); make a trivial committed change; `perk pr submit --json`. Verify the draft
   PR opens and the node-issue `plan-header` gains `branch` / `pr` / `lifecycle_stage` (the
   inline-code sentinel intact after the ProseMirror re-encode).
6. **Land (node-done + Project Update + close).** `perk pr land --json`. Verify: the node
   **auto-marks `done`** (`nodes_marked` includes the node id; the backlink `pr` is the
   **node-issue's own identifier**, the self-referential land-time backlink, stable); a **"plan
   landed" Project Update** posts to the feed (**`post_status_update`**); and — when this was the
   **last** open node — `close_objective` marks the **Project `completed`** via
   `projectUpdate(state:"completed")` (**live-proves `set_project_state`**; confirm "Objective
   complete." in the landed update body). The squash footer carries `Plan: <identifier> — <url>`.
   (With the smoke roadmap, other nodes remain open, so `close_objective` will **not** fire on this
   land — to observe the close, either drive every node to land or note that the close path is
   exercised only when the final node lands; record which.)
7. **`update_objective_node` workflow-state mirror.** Confirm (when the node moved to
   `in_progress` at gate 4 / `done` at gate 6) that the **Linear node-issue's workflow state**
   best-effort mirrors the perk status (`_workflow_state_id` map: `in_progress → started`,
   `done → completed`). Record whether the mirror **fired** or **fell open** — a missing state type
   or a Linear hiccup is **non-fatal by design**, so record either outcome
   (**exercises `_workflow_state_id`**).
8. **Reconcile (Reconcilable splice ProseMirror round-trip — the headline fidelity check).**
   `perk objective reconcile <PROJECT_UUID> --json` with edited Reconcilable prose. Verify the
   overview's Reconcilable region is **spliced in place** (form-preserving), the `objective-header`
   block stays parseable after Linear's re-encode (`find_metadata_block` round-trip **CLEAN**),
   **zero** HTML artifacts, and a reconciled **Project Update** posts.
9. **Deliberate-perturbation observation (drift-doctor proxy).** *(Replaces the unrunnable "run the
   4.4 drift doctor" clause — the `perk objective doctor` drift surface is **not yet built**; Node
   4.4 delivered the design only, see `docs/planning/objective-repair.md`.)* In the Linear UI,
   deliberately perturb the live Project, and after **each** perturbation run
   `perk objective show <PROJECT_UUID> --json` and record **how `get_objective` behaves today**:
   - (a) **Remove a node-issue from the Project** (un-assign its project) → the removed node
     **silently disappears** from the reconstructed roadmap (`get_objective` rebuilds from
     surviving node-issues only).
   - (b) **Add a spurious `blocks` relation** from an unrelated / cross-project issue → the unknown
     blocker target is **silently dropped** from `depends_on` (only in-objective node identifiers
     reconstruct).
   - (c) **Rename a phase milestone** → **invisible** to `get_objective` — the roadmap
     reconstruction is milestone-name-independent (node `phase` derives from the node id via
     `derive_phase`; `get_objective` never reads milestone names), so the renamed value surfaces
     only in the Linear UI grouping, not in `objective show`.
   State explicitly that these are the **empirical baseline** the future drift-detection node will
   formalize — there is no doctor to flag the drift today.
10. **Rate limits / error shapes.** Note any RATELIMITED context (still unobserved at low volume)
    and any unexpected error shape from the Project ops.

Append the run's findings to the **Recorded observations** section (a new dated **Fourth live run**
block, one row per gate). If a gate trips a backend defect, record it as a dated observation **and
open a follow-up issue** (the #562 precedent) — do **not** fix substantive code in this node;
correct only stale command references / runbook drift inline.

## Mode 5 — idiomatic Linear footprint (#669)

Validates the additive, **Linear-only** native-footprint changes (#669): attribution, project
start date + lifecycle, workspace-scoped labels, the `perk:objective-node` label, PR attachments,
prose-first metadata, and — the one genuinely undocumented mechanism — whether Linear's
**collapsible-toggle markdown round-trips** so the metadata sentinels survive. The offline suite
(`tests/test_linear.py`, `tests/test_linear_backend.py`, `tests/test_linear_lifecycle.py`) already
pins request composition and prose-first ordering; this gate covers what no fake can prove.

Run against team `PER` from perk's own repo (the documented firing mechanism), with
`[issues] backend = "linear"`, `team = "PER"`, and `LINEAR_API_KEY` exported.

Run a full project-backed objective lifecycle (Mode 4's setup) and additionally verify:

1. **Workspace-label permission (gate 5.1).** `perk doctor --fix` (or `perk init --verify`) creates
   any missing perk labels with **no `teamId`** (workspace-scoped). Confirm the create succeeds for
   the API-key user; if Linear rejects a workspace-level label create, record it and the fallback
   is a one-line re-add of `teamId` in `_ensure_label_id`.
2. **The five labels incl. `perk:objective-node` (gate 5.2).** After convergence, all five
   `perk:*` labels exist; roadmap node-issues carry `perk:objective-node`.
3. **Lead / assignee / startDate (gate 5.3).** The objective **Project** shows the API-key user as
   **lead** and a **start date**; every perk-created issue (plan, learn, objective, node) is
   **assigned** to that user (appears in *My Issues*).
4. **Project status transitions (gate 5.4).** The Project shows **In Progress** after a node
   enters a started-type status, and **Completed** after the objective lands.
5. **PR attachment (gate 5.5).** After `/submit`, the node-issue (or standalone plan issue) shows a
   native sidebar **attachment** card titled `GitHub PR #N`. Re-stamp (`/land` re-runs the
   header stamp) and confirm the card **updates in place** (idempotent by URL — no duplicate).
6. **Prose-first metadata (gate 5.6).** The project overview leads with the human prose; the
   `objective-header`/`objective-manifest` blocks follow. Node-issue bodies lead with the node
   prose, the `objective-node` block after. No `<!-- … -->` or `<details>` artifacts.
7. **THE collapsible round-trip — the keep/drop decision (gate 5.7).** *Currently deferred — the
   #669 implementation shipped prose-first only and did **not** wire a collapsible toggle, because
   no live key was available to probe the round-trip.* When run: on a throwaway Linear issue,
   write a metadata block wrapped in a candidate collapsible markdown form (starting hypothesis:
   the `+++`/`>>>`-prefixed collapsible-section syntax), then **read it back** and check (a) the
   Linear UI renders it **collapsed** AND (b) `plan.find_metadata_block` still parses the block
   (the inline-code sentinels survived the ProseMirror round-trip). **If a lossless form exists**,
   wire it into `render_metadata_block` + `to_linear_markdown` in lockstep (preserving the
   renderer↔transcoder byte-identity invariant) and ship it. **If no lossless form exists**, leave
   prose-first as the final design and record the drop. Record the exact markdown probed and the
   verdict here.

Append the run's findings to **Recorded observations** as a dated **Fifth live run** block (one row
per gate). Record any backend defect as a dated observation and open a follow-up — do not fix
substantive code at the gate.

## Agent session emission (Objective #252, Node 5.1 — stretch)

The opt-in Linear Agents-UI mirror of an implement run (`perk/linear_agent.py`, contracts §8.22).
Offline fakes pin request *composition* only — this live smoke is the only surface that can prove
Linear actually **accepts** the agent mutations (`agentSessionCreateOnIssue`,
`agentActivityCreate`, `agentSessionUpdate`).

### One-time setup

1. Create a **Linear OAuth application with agent capability** (linear.app → Settings → API →
   OAuth applications → enable "Agent" / `app:assignable`+`app:mentionable` as documented).
2. Install it into the scratch workspace and complete the OAuth flow with **`actor=app`** — the
   resulting access token acts *as the app*, which is what the AgentSession API requires (a
   personal `LINEAR_API_KEY` is rejected).
3. `export LINEAR_AGENT_TOKEN=<that access token>` (environment-only; without it the emission
   layer is fully dormant).

### Smoke script

On a Linear-backed plan (the `[issues] backend = "linear"` setup above):

1. `perk implement ENG-<n>` — verify in Linear's Agents UI: an **AgentSession** appears on the
   plan issue with a `thought` activity ("Starting implement run …") and that
   `.pi/workflow/agent-session.json` was written into the worktree. For a remote drive
   (`perk implement --remote …`), the session's external links include the GitHub Actions run.
2. `/submit` (or `perk pr submit --json`) — verify an `action` activity ("Opened pull request",
   parameter = branch, result = PR URL) and the **PR link attached** to the session
   (`addedExternalUrls`).
3. `/land` (or `perk pr land --json`) — verify a `response` activity ("PR #n squash-merged." +
   the objective-node summary when linked) and that the session's derived status settles.
4. **Failed remote drive** (optional): force a remote implement to fail and verify the `error`
   activity lands beside the terminal run-report note.
5. Re-run any step **without** `LINEAR_AGENT_TOKEN` and verify zero agent-API traffic
   (byte-identical behavior — the dormant guarantee).

### Deferral register (agent emission)

- **Exact mutation signatures unverified offline** — the GraphQL documents are substring-pinned
  in `tests/test_linear_agent.py`; record any live schema rejection here.
- **Staleness** — Linear marks sessions `stale` ~30 min after the last activity; long implement
  runs show stale until the submit/land activity refreshes them (accepted, not mitigated).
- **`perk address` emission** — deferred (no activity on the address stage).
- **Agent plan checklist** (`agentSessionUpdate.plan`; Agent Plan API is a technology preview) —
  deferred.
- **Remote-created session invisible to a local land** — `agent-session.json` stays in the
  runner's checkout; a later local land skips its emission (stderr note).

## Recorded observations

> Append dated entries after each live run. Each observation feeds the named follow-up.

> **First live run: 2026-06-15** (Objective #548, Node 1.1), workspace `Perk-testing` (team key
> `PER`), bare workspace (no GitHub integration / no Issues Sync). Mode 1 + the issue-backed
> objective loop ran **green** end-to-end; every `--json` envelope carried string `PER-*` ids. The
> headline ProseMirror `find_metadata_block` round-trip was **clean** for the plan header, the
> plan-body comment, and the objective-body re-render (roadmap table + reconcilable splice). No
> trivial backend defect was tripped (the one run-1 close miss was a test-config team-key error,
> not a backend bug — see the land row).

| Date | Mode | Observation | Feeds |
|---|---|---|---|
| 2026-06-15 | 1 (gate 1, plan-save) | `perk plan save --plan-file … --json` created **PER-5** (string id), `plan_ref.provider == "linear"`, label `perk:plan`. The description `plan-header` and first comment `plan-body` stored as the **inline-code sentinel** (`` `perk:metadata-block:…` `` … `` `/perk:metadata-block:…` ``) — **zero** raw `<!-- … -->` / `<details>` artifacts. | ProseMirror round-trip fidelity (proven) |
| 2026-06-15 | 1 (gate 2, re-save round-trip) | Edited plan, re-ran same run-id → same **PER-5** (`existed: true`, `updated: true`); comment count stayed **1** (patched in place, not duplicated); header still parseable after Linear's re-encode; edit reflected in the body. **Round-trip CLEAN** — the headline fidelity check passes. | ProseMirror round-trip fidelity (proven — headline) |
| 2026-06-15 | 1 (gate 3, implement) | Worktree/branch resolved to **`plan-PER-5`** (identifier-shaped, string id); trivial committed change. | lifecycle composition |
| 2026-06-15 | 1 (gate 4, submit) | `perk pr submit --json` opened a **draft** PR; the Linear `plan-header` gained `branch` / `pr` / `lifecycle_stage` (e.g. `lifecycle_stage: impl`, `branch: plan-PER-6`, `pr: '2'`); header sentinel intact after the update. | ProseMirror round-trip fidelity (proven) |
| 2026-06-15 | 1 (gate 5, land) | Clean run (**PER-6**, correct team key): squash footer `Plan: PER-6 — <url>` (no `Closes #N`, no Linear magic words); `plan_issue_closed: true` (issue → **Done**, `completed`); pending-learn set. **NOTE:** the first run (PER-5) reported `plan issue close skipped (non-fatal): Linear team 'perk-testing' not found` → `plan_issue_closed: false` — caused by the committed `[issues] team` being the team **name** (`perk-testing`) not the **key** (`PER`); the backend resolves the team by `key`. Test-config error, **not** a backend defect; corrected and re-verified green. | team-key resolution (config, not 1.2); close-path fidelity (proven) |
| 2026-06-15 | 1 (gate 6, learn) | `perk learn capture --json` created `perk:learn` issue **PER-7** (string id) + back-link comment `Learnings captured in #PER-7.` on the plan issue; `pending_cleared: true`. | lifecycle composition |
| 2026-06-15 | 1 (gate 7, objective loop) | `perk objective create --roadmap` → **PER-8**; `show`/`next` round-tripped the roadmap (node 1.1 parsed back). Linked plan **PER-9** via `plan save --objective-id PER-8 --node-id 1.1` (node → `in_progress`); on land the node **auto-marked done** (`nodes_marked: ["1.1"]`, `pr: #PER-9`) and the objective closed. `objective reconcile` spliced the **Reconcilable** prose in place (same comment id). Objective body uses `` `perk:roadmap-table` `` + `` `perk:objective-reconcilable` `` sentinels; roadmap table re-render parseable, **zero** HTML artifacts. **Round-trip CLEAN.** | ProseMirror round-trip fidelity (objective body — proven) |
| 2026-06-15 | 1 (gate 8, error shape) | `issue(id: "PER-9999")` (missing entity) → GraphQL `message: "Entity not found: Issue"`, `extensions.code: "INPUT_ERROR"`, `type: "invalid input"`, `statusCode: 400`, `userError: true`, `userPresentableMessage: "Could not find referenced Issue."`. perk surfaces it cleanly as `*_not_found` (the current `"not found"` substring tolerance matches). **Caveat for 1.2:** `INPUT_ERROR` is a **generic** input-error code (not a dedicated NOT_FOUND), so a `.codes`-only tightening would be too broad — pair `code == "INPUT_ERROR"` with the `"Entity not found:"` message prefix. | `.codes` tightening (`_issue_or_none`) — **observed** |
| 2026-06-15 | 1 (gate 9, rate limits) | **No RATELIMITED tripped** at this (low) request volume across the full lifecycle + objective loop. No HTTP-400 `extensions.code == "RATELIMITED"` observed. | RATELIMITED retry/backoff posture — still **unobserved** |
| 2026-06-15 | 1 (mutation identifier) | **Not probed** (Mode 2 / Node 1.3 — out of scope here). All mutations (`issueUpdate`, `commentCreate`, issue close) worked via the `_uuid_for` `PER-<n>` → UUID resolution; direct-identifier acceptance unverified. **Resolved (#562, 2026-06-16):** the Mode 2 positive probe (below) settled it — `_uuid_for` + its cache were **deleted** (not pass-through'd); verified mutations take the identifier directly, `issueRelationCreate` keeps create-time UUIDs. | `_uuid_for` pass-through simplification — **resolved** (#562 landed the collapse) |
| 2026-06-15 | 1 (runbook drift) | Three command references in this runbook are stale against the current CLI: `perk init --verify` → no such flag (labels are ensured by `perk doctor --fix`); `perk plan-save` → `perk plan save` (no flat alias); `perk resume ENG-<n>` → `perk plan resume`. `perk pr submit`/`perk pr land` (and the `perk submit`/`perk land` flat aliases) are valid; `land` is idempotent on an already-merged PR. Corrected inline above (Prerequisites + Mode 1 steps). | runbook accuracy (this doc) |

> **Second live run: 2026-06-15** (Objective #548, Node 1.3), workspace `Perk-testing` (team key
> `PER`), **GitHub integration installed** (org `roivant-health`, repo `perk-testing`) with both
> workflow automations enabled (`start → In Progress`, `merge → Done`; plus `review → In Review`)
> and Linear's *GitHub Issues* two-way Sync **OFF**. Mode 2 ran **green**: all three coexistence
> behaviors confirmed via perk's real CLI (`plan save` → `pr submit` → `pr land` → `learn capture`,
> `--json` throughout, plan **PER-10** / PR #1 / branch `plan-PER-10`), and the `_uuid_for`
> mutation-identifier probe came back **positive**. **No backend defect tripped** (no code change
> this node — measurement only). **Setup note:** linking worked only after an operator-side repair
> of the Linear↔GitHub *repository* connection — the App being installed on the org was not enough
> (see the "installed ≠ connected" caveat in Mode 2 above); a control PR from Linear's own
> `username/identifier-title` branch format *also* failed to link until the repair, proving it was
> the connection, not perk's branch name.

| Date | Mode | Observation | Feeds |
|---|---|---|---|
| 2026-06-15 | 2 (branch auto-link) | After `pr submit` pushed **`plan-PER-10`**, Linear's GitHub integration attached PR #1 to **PER-10** as a `github` **attachment** (`linkKind: closes`, `targetBranch: main`, carrying the PR's review-state fields — empty here, no review occurred). perk's identifier-shaped **`plan-PER-<n>`** branch auto-links **directly** — it does **not** need to match Linear's configured `username/identifier-title` template (a control PR from that exact template format linked identically). The D3 payoff of identifier-shaped worktree names is **proven** live. | D3 branch auto-link (proven) |
| 2026-06-15 | 2 (automation ↔ close idempotency) | The `start → In Progress` automation fired on PR open (Backlog → In Progress); perk's submit-time `plan-header` write (`branch`/`pr`/`lifecycle_stage`, at `pr submit`) did **not** flap the state. On `pr land`, PR #1 merged → the `merge → Done` automation completed the issue, and perk's explicit `close_issue` was a clean **idempotent no-op** beside it: envelope `plan_issue_closed: true`, **no error**, and the same-state Done write only refreshed `completedAt` — it created **no new state transition** (history = Backlog→In Progress→Done, monotonic, **no flap**). Final state **Done**. | automation coexistence (proven) |
| 2026-06-15 | 2 (linkback tolerance) | The integration links PRs as **attachments** (issue sidebar), **not** comments. PER-10's comments surface stayed purely perk's own — the `plan-body` block + the `Learnings captured in #PER-12.` marker-keyed upsert — while both PR links (PR #1 merged, PR #2 closed) sat in the **attachments** surface. `get_plan_body` resolved throughout (`pr land` embedded the `Plan:` footer; `learn capture` read the plan-ref); the marker-keyed upsert patched perk's OWN comment cleanly. The live integration never touches the comment stream, so the offline twin (`test_foreign_linkback_comment_does_not_perturb_marker_scans`, a synthetic foreign *comment*) is **stricter** than reality — tolerance holds for a structurally stronger reason. | linkback tolerance (proven — attachment surface) |
| 2026-06-15 | 2 (mutation identifier) | **Probed positive.** `issueUpdate(id: "PER-10", …)` and `commentCreate(input: {issueId: "PER-10", …})` both **succeed with the bare `PER-<n>` identifier** (no UUID resolution); a bogus `PER-99999` still errors `code: INPUT_ERROR` / `message: "Entity not found: Issue"` (same shape as Mode-1 gate 8). Linear accepts the human identifier everywhere the `_uuid_for` UUID is currently used, so `_uuid_for` could reliably simplify to a **pass-through**. Substantive (no roadmap node owns it) → recorded as a **deferred follow-up** ([#562](https://github.com/mattgiles/perk/issues/562)); `_uuid_for` is unchanged this node. **Resolved (#562, 2026-06-16):** the follow-up landed the full collapse — `_uuid_for` + the `_uuid_cache` + every `cache_uuid` seed were deleted; `issueUpdate`/`commentCreate` now pass the bare identifier, and `issueRelationCreate` (only ever probed with UUIDs) receives the issue UUID captured from the `issueCreate` response. | `_uuid_for` pass-through simplification — **resolved** (#562 landed the collapse) |
| 2026-06-15 | 2 (runbook drift) | The Mode 2 "Linkback tolerance" bullet's premise that the integration "posts linkback comments on linked issues" is **inaccurate** against the current Linear GitHub integration — PR links arrive as **attachments**, not comments. Corrected inline (Mode 2 section), the "In Progress on push" trigger phrasing aligned to the observed "on PR open", and an "installed ≠ connected" setup caveat added (the operator-side repository-connection gotcha this run hit). | runbook accuracy (this doc) |

> **Third live run: 2026-06-15** (Objective #548, Node 1.4 — **Mode 3, Projects API spike**),
> workspace `Perk-testing` (team key `PER`, UUID `2f933a7e-0d05-4424-bea2-0bc79a4c54c9`), bare run
> (Projects are not PR-linked, so the GitHub integration is irrelevant here). All five Project
> operation classes fired **green** against the live API via inline `LinearClient.request` snippets
> (no committed script). **Project `content` IS accepted directly at `projectCreate`** — the
> historical 2024 create-time limitation no longer applies, so no create-then-`projectUpdate`
> adaptation is needed. The **overview round-trip is CLEAN** (and the Project-document round-trip is
> CLEAN too), so the decisive storage decision lands on the **overview**. No production code,
> contract, or user-doc surface changed (measurement node). No `LinearClient` substrate defect was
> tripped. Spike project: `https://linear.app/perk-testing/project/perk-spike-2026-06-15-676e664a8497`
> (project UUID `a2ab46dc-e6e2-4787-97e0-959873209e85`).
>
> **Decisive overview-vs-document storage decision (for node 3.2): store the objective machine
> markers in the Project _overview_ (`content`).** Evidence: the inline-code marker block
> (`render_metadata_block(..., style="inline-code")`) round-tripped **byte-faithfully** through the
> overview — written via `projectCreate(input:{content})` and patched via `projectUpdate` — and
> `find_metadata_block` recovered the exact original dict. A `documentCreate` content round-trip was
> _also_ CLEAN (it remains a viable fallback), but the overview is the simpler single-surface home
> (no second entity to create/track, shown in the main detail panel), so node 3.2 should use the
> overview unless a future constraint forces the document branch.

| Date | Operation | Observation | Feeds |
|---|---|---|---|
| 2026-06-15 | project create | `projectCreate(input:{ teamIds, name, content })` → `success: true`; returned `project.id` (UUID `a2ab46dc-…`), `url`. **`content` accepted at create** (the returned `project.content` carried the full inline-code marker block) — the 2024 create-time wrinkle does **not** apply; no create-then-`projectUpdate` needed. `description` defaulted to `''`. | node 3.1 (LinearClient `projectCreate`) |
| 2026-06-15 | overview round-trip (decisive) | Wrote the `perk:objective-header` inline-code block + Reconcilable prose via `projectUpdate(id, input:{ content })`; read back `project(id){ content }`. `find_metadata_block(content, "perk:objective-header")` returned the **exact** original dict (`{run_id, status, node, objective}`). **CLEAN** — byte-faithful (backticks, ```` ```yaml ```` fence, sentinel all preserved; ProseMirror did not reflow the inline-code block). | node 3.2 (**storage decision = overview**) |
| 2026-06-15 | document round-trip (fallback) | `documentCreate(input:{ projectId, title, content })` → `success: true`, doc UUID `d133dafa-…`; read back `document(id){ content }`. `find_metadata_block` returned the **exact** original dict. **CLEAN** — the Project-document surface is an equally faithful fallback, recorded for node 3.2's alternate branch. | node 3.2 (overview fallback) |
| 2026-06-15 | milestone create + list | `projectMilestoneCreate(input:{ projectId, name })` ×2 (`Phase 1`, `Phase 2`) → `success: true`, ids `81457502-…` / `5a0e928a-…`. `project(id){ projectMilestones { nodes { id name } } }` listed **both** with stable ids + names (order was reverse-insertion: `Phase 2`, `Phase 1` — **name** is the deterministic key, not list position). | node 4.3 (phase → milestone map) |
| 2026-06-15 | issue↔project attachment | Created `PER-13` (`issueCreate{teamId,title}`) then attached via `issueUpdate(id, input:{ projectId })` → `issue.project.id` set. Direct `issueCreate(input:{ teamId, title, projectId })` created `PER-14` already in the project. Visible **both** directions: `issue(id){ project { id } }` and `project(id){ issues { nodes { id identifier } } }` (listed `PER-14`, `PER-13`). | node 3.2 (one node-issue per roadmap node in the project) |
| 2026-06-15 | blocking relation create + read | `issueRelationCreate(input:{ issueId: PER-13.uuid, relatedIssueId: PER-14.uuid, type: "blocks" })` → `success: true`, relation id `800fe05d-…`, `type: "blocks"`. **Forward:** `issue(PER-13){ relations { nodes { type relatedIssue { identifier } } } }` → `{type:"blocks", relatedIssue:"PER-14"}`. **Inverse:** `issue(PER-14){ inverseRelations { nodes { type issue { identifier } } } }` → `{type:"blocks", issue:"PER-13"}` (the `type` enum stays `"blocks"` on the inverse; the **direction** is carried by `relations` vs `inverseRelations`, not by a `"blockedBy"` enum value). Both directions readable. | node 3.3 (reconstruct `depends_on` from inverseRelations) |
| 2026-06-15 | error shapes (bogus id) | `project(id:"00000000-…")` → `message: "Entity not found: Project"`, `extensions.code: "INPUT_ERROR"`. `projectMilestoneCreate(input:{projectId: bad})` → `"Entity not found: Project"` / `INPUT_ERROR`. `document(id: bad)` → `"Entity not found: Document"` / `INPUT_ERROR`. **All three MATCH the issue not-found shape** (`INPUT_ERROR` + `"Entity not found:"` prefix that `_is_entity_not_found` keys on). **`issueRelationCreate` with a nonexistent `relatedIssueId` DIFFERS:** `message: "Argument Validation Error"`, `extensions.code: "INVALID_INPUT"` (argument validation fails *before* entity lookup — neither the `INPUT_ERROR` code nor the `"Entity not found:"` prefix). | node 3.1 (GraphQLClient fake) / Project not-found handling |
| 2026-06-15 | rate limits | **No RATELIMITED tripped** across the full spike (project + overview/document + 2 milestones + 2 issues + relation + 4 error probes). No HTTP-400 `extensions.code == "RATELIMITED"` observed. | RATELIMITED retry/backoff posture — still **unobserved** |

### Proven GraphQL documents (Mode 3 — copy verbatim into node 3.1's `LinearClient`)

The working variants, exactly as fired (all green; `content` accepted at create so **no**
create-then-`projectUpdate` adaptation was required):

```graphql
# projectCreate — content accepted at create (overview written directly)
mutation($input: ProjectCreateInput!) {
  projectCreate(input: $input) { success project { id url name content description } }
}
# variables: { input: { teamIds: ["<TEAM_UUID>"], name: "<name>", content: "<overview markdown>" } }

# projectUpdate — patch the overview content (used for later writes)
mutation($id: String!, $input: ProjectUpdateInput!) {
  projectUpdate(id: $id, input: $input) { success project { id content } }
}
# variables: { id: "<PROJECT_UUID>", input: { content: "<overview markdown>" } }

# project read — overview + milestones + issues
query($id: String!) {
  project(id: $id) {
    id content
    projectMilestones { nodes { id name } }
    issues { nodes { id identifier } }
  }
}

# documentCreate — overview fallback surface
mutation($input: DocumentCreateInput!) {
  documentCreate(input: $input) { success document { id title content } }
}
# variables: { input: { projectId: "<PROJECT_UUID>", title: "<title>", content: "<markdown>" } }
# read back: query($id: String!) { document(id: $id) { id content } }

# projectMilestoneCreate
mutation($input: ProjectMilestoneCreateInput!) {
  projectMilestoneCreate(input: $input) { success projectMilestone { id name } }
}
# variables: { input: { projectId: "<PROJECT_UUID>", name: "<phase name>" } }

# issue↔project attachment (existing issue) + direct create-in-project
mutation($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) { success issue { id identifier project { id } } }
}
# variables: { id: "<ISSUE_UUID>", input: { projectId: "<PROJECT_UUID>" } }
mutation($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { id identifier project { id } } }
}
# variables: { input: { teamId: "<TEAM_UUID>", title: "<title>", projectId: "<PROJECT_UUID>" } }

# issueRelationCreate (blocks) + read back both directions
mutation($input: IssueRelationCreateInput!) {
  issueRelationCreate(input: $input) { success issueRelation { id type } }
}
# variables: { input: { issueId: "<A_UUID>", relatedIssueId: "<B_UUID>", type: "blocks" } }
query($id: String!) {  # A blocks B
  issue(id: $id) { identifier relations { nodes { type relatedIssue { identifier } } } }
}
query($id: String!) {  # B blockedBy A (carried by inverseRelations, type stays "blocks")
  issue(id: $id) { identifier inverseRelations { nodes { type issue { identifier } } } }
}
```

### Not-yet-live-proven Project ops (verified at Node 5.1 — Mode 4)

These Project ops are **offline-covered** (scripted-fake tests) but were **not** exercised by the
Mode 3 spike, so they were flagged not-live-proven in `_LinearProjectOps` and are exercised by
**Mode 4** above — see the **Fourth live run** observation block for each op's live result:

- `set_project_state` — `projectUpdate(id, input:{ state })` (mark the Project complete on land) —
  **Mode 4 gate 6** (the `close_objective` close path).
- `list_projects` — `team(id){ projects { nodes { id url content } } }` (the find-by-run-id scan) —
  **Mode 4 gate 3** (idempotent re-create).
- `_workflow_state_id` — `update_objective_node`'s best-effort Linear workflow-state mirror
  (`in_progress → started`, `done → completed`; fail-open) — **Mode 4 gate 7**.
- `create_project_update` (Node 4.3) — the **Project Update** status feed, posted fail-open on
  objective-created / plan-landed / reconciled transitions (**Mode 4 gates 1 / 6 / 8**):

```graphql
# projectUpdateCreate — post a Project Update (the status-report feed); `health` omitted (D3)
mutation($input: ProjectUpdateCreateInput!) {
  projectUpdateCreate(input: $input) { success projectUpdate { id } }
}
# variables: { input: { projectId: "<PROJECT_UUID>", body: "<markdown>" } }
```

> **Fourth live run: 2026-06-16** (Objective #548, Node 5.1 — **Mode 4, project-backed objective
> lifecycle**), workspace `Perk-testing` (team key `PER`, UUID
> `2f933a7e-0d05-4424-bea2-0bc79a4c54c9`), bare run (Projects are not PR-linked, so the GitHub
> integration is irrelevant). The **project-backed objective lifecycle ran green** end-to-end
> against the live Linear API, and **all four not-yet-live-proven Project ops are now proven live**:
> `list_projects` (find-by-run-id idempotency), `create_project_update` (3 updates across
> created/landed/reconciled), `set_project_state` (Project → `completed` on close), and
> `_workflow_state_id` (node workflow-state mirror, both `in_progress → started` and
> `done → completed`). The headline ProseMirror `find_metadata_block` round-trip was **CLEAN** for
> the overview `objective-header` through create → reconcile (zero HTML artifacts). The node↔plan
> unification created **no** new `perk:plan` issue (the plan-header merged into the node-issue
> description + the plan body landed as a single node-issue comment). **No production code,
> contract, or user-doc surface changed** (measurement node); **no backend defect was tripped**.
> Project: `https://linear.app/perk-testing/project/mode-4-smoke-objective-project-backed-lifecycle-node-51-eccec242e70e`
> (UUID `54143ab9-bb04-4885-96ca-0dc7651185bf`, run_id `01SMOKE5A180030`); node-issues **PER-15**
> (1.1) / **PER-16** (1.2) / **PER-17** (2.1) / **PER-18** (2.2); milestones `Foundations` (1.x) /
> `Extensions` (2.x); blocking relations `PER-15 blocks PER-16`, `PER-16 blocks PER-17`.
>
> **Scoped deferral — the git+GitHub `pr submit` / `pr land` orchestration (gates 5–6) was NOT run
> in this session.** This smoke was driven from perk's own dev repo, whose git remote is the real
> `mattgiles/perk` (no separate scratch GitHub repo wired to Linear was available, unlike Mode 1/2's
> `perk-testing` repo). Running `pr submit` / `pr land` here would push branches to `mattgiles/perk`
> and **squash-merge a throwaway change into perk's `main`** — unacceptable. The git orchestration
> is unchanged this node and is already offline-covered + Mode-1/2-proven for the GitHub backend;
> Node 5.1's actual targets are the **Linear Project ops** those land/submit paths call, which were
> live-proven by exercising `LinearProjectObjectiveStore.update_objective_node` /
> `close_objective` / `post_status_update` **directly** against the live Project (the exact calls
> `_reconcile_objective_on_land` makes), faithfully reproducing the land-side Linear effects.

| Date | Gate | Observation | Feeds |
|---|---|---|---|
| 2026-06-16 | 4.1 (create) | `perk objective create --body … --roadmap '<scrambled 2.1,1.1,2.2,1.2>' --run-id … --json` → `objective.id` an **opaque Project UUID** (`54143ab9-…`, NOT `PER-*`), `existed: false`. Overview carried the `objective-header` inline-code block + the `` `perk:objective-reconcilable` `` region, **no** roadmap table, **zero** `<!-- … -->` / `<details>` artifacts. **One milestone per phase** (`Foundations`/`Extensions`, enriched `### Phase N:` names); **one node-issue per node** (PER-15..18) each attached to its phase milestone; **blocking relations** materialized for every explicit `depends_on` (`PER-15 blocks PER-16`, `PER-16 blocks PER-17` — dep blocks node). A fresh-create **Project Update** posted (`**Objective created** — … 4 nodes across 2 phases.`). | `create_project_update` (**proven live**); project-backed composition |
| 2026-06-16 | 4.2 (ordering) | `perk objective show <UUID> --json` returned `nodes` in **`node_sort_key` order** (`1.1, 1.2, 2.1, 2.2`) despite the **scrambled** authoring order and despite Linear's reverse-insertion connection order (`PER-18,17,16,15`). `objective next` → `1.1`. `depends_on` **reconstructs at the store level** (`get_objective`: `1.2←(1.1)`, `2.1←(1.2)`), but **`objective show --json` does not serialize `depends_on`** (node keys = `id/description/status/pr/phase`; `phase` is **derived from the node id** via `derive_phase`, not read from the milestone) — verify the dep graph via the store or `next` selection, not the show envelope. | deterministic ordering (**proven**); runbook accuracy (show omits `depends_on`) |
| 2026-06-16 | 4.3 (idempotency) | Re-running the **same** `objective create … --run-id …` → `existed: true` and the **same** Project UUID; milestone count stayed **2**, issue count stayed **4** (no duplicates). The `list_projects` find-by-run-id scan resolved the existing Project. | `list_projects` (**proven live**) |
| 2026-06-16 | 4.4 (node↔plan unification) | `perk plan save --objective-id <UUID> --node-id 1.1 --plan-file … --json` → `issue.id == PER-15` (the **node-issue's own** ref), `plan_ref.pr_id == PER-15` + `objective_id` set, `objective_node.linked/status == in_progress`. **No new `perk:plan` issue** (team `perk:plan` count unchanged at 5). PER-15's **description** gained the `plan-header` inline-code block (beside its `objective-node` block); the plan **body** landed as a **single** node-issue comment (`plan-body` block). The node-issue's Linear workflow state mirrored to **In Progress (started)**. | node↔plan unification (**proven**); `_workflow_state_id` in_progress→started (**proven live**) |
| 2026-06-16 | 4.5 (implement+submit) | **Deferred — git orchestration not run here** (see the scoped-deferral note above). The submit-time `plan-header` `branch`/`pr`/`lifecycle_stage` write to the node-issue is the same Linear write path proven in Mode 1 gate 4; only the GitHub PR open differs, and that requires a Linear-wired scratch repo. | git orchestration (offline + Mode-1/2 covered) |
| 2026-06-16 | 4.6 (land: node-done + close + update) | Reproduced the land-side Linear effects directly (the calls `_reconcile_objective_on_land` makes): marking node 1.1 `done` mirrored PER-15 to **Done (completed)** and posted `**Plan landed** — node(s) 1.1 (PR #PER-15) marked done.`; driving the remaining nodes done → `close_objective` set the **Project state to `completed`** (`projectUpdate(state:"completed")`) and posted `**Plan landed** — node(s) 2.2 (PR #PER-18) marked done.\n\nObjective complete.`. The backlink `pr` is the **node-issue's own identifier** (self-referential, stable). | `set_project_state` (**proven live**); `create_project_update`/`post_status_update` (**proven live**) |
| 2026-06-16 | 4.7 (workflow-state mirror) | The `_workflow_state_id` mirror **fired** both directions: `in_progress → started` (gate 4, node 1.1 → In Progress) and `done → completed` (gate 6, **all four** node-issues → Done). No fail-open fallback was needed — team `PER` has both a `started` and a `completed` workflow state (the `linear-workflow-states` doctor probe is green). | `_workflow_state_id` (**proven live, both directions**) |
| 2026-06-16 | 4.8 (reconcile splice) | `perk objective reconcile <UUID> --body … --json` → `updated: true`; the overview's Reconcilable region was **spliced in place** (form-preserving), the `objective-header` block stayed **parseable** after Linear's re-encode (`find_metadata_block` **CLEAN**, exact dict recovered), the reconcilable sentinels survived (2), **zero** HTML artifacts, and a reconciled **Project Update** posted (`**Roadmap reconciled** — …`). The headline fidelity check passes. | ProseMirror round-trip fidelity (**proven** — overview reconcile) |
| 2026-06-16 | 4.9 (perturbation baseline) | Deliberate live perturbations + re-read of `get_objective` (the **drift-doctor proxy** — `perk objective doctor` is **not built**; Node 4.4 delivered the design only, see `docs/planning/objective-repair.md`): (a) **un-assigning PER-18 (2.2) from the project** → the node **silently disappeared** from the reconstructed roadmap (4→3 nodes, no error/flag — `get_objective` rebuilds from surviving node-issues only); (b) adding a **spurious cross-project `blocks`** (`PER-5 blocks PER-15`) → the raw `inverseRelations` carried it (`project: null`), but `get_objective`'s `1.1.depends_on` stayed **`None`** — the unknown blocker target was **silently dropped** (only in-objective identifiers reconstruct); (c) **renaming milestone `Foundations` → `Foundations RENAMED`** → **invisible** to `get_objective` (node `phase` derives from the node id, not the milestone name; the roadmap reconstruction is milestone-name-independent). These are the **empirical baseline** the future drift-detection node will formalize. | drift-surface baseline (empirical — Node 4.4 design only) |
| 2026-06-16 | 4.10 (rate limits / error shapes) | **No RATELIMITED tripped** across the full Mode 4 run (create ×2, show ×3, plan-save, 4 node updates, close, 2 status updates, reconcile, perturbations). No HTTP-400 `extensions.code == "RATELIMITED"`. No unexpected error shape from the Project ops; the only error encountered was operator-side (an inline `issueRelationCreate` with a quoted `type:"blocks"` enum → `GRAPHQL_VALIDATION_FAILED`, a curl-quoting mistake, not a perk/Project-op shape — the store passes the enum via typed variables). | RATELIMITED posture — still **unobserved**; no Project-op defect |

**Summary — GREEN.** The project-backed objective lifecycle and all four previously-not-live-proven
Project ops (`list_projects`, `create_project_update`, `set_project_state`, `_workflow_state_id`)
work against the real Linear API; the overview ProseMirror round-trip is CLEAN through
create → reconcile; node↔plan unification creates no new issue and patches the body comment in
place; and the deliberate-perturbation pass records the empirical baseline the unbuilt
`perk objective doctor` drift surface will formalize. The only non-code findings are runbook-accuracy
nuances (`objective show --json` omits `depends_on`; milestone rename is invisible to the roadmap
reconstruction because `phase` derives from the node id) — recorded above, no follow-up issue
warranted. The git+GitHub `pr submit`/`pr land` orchestration (gates 5–6) was deferred (not run in
perk's own repo to avoid a throwaway merge into `main`); its Linear-side Project-op targets were
live-proven directly.
