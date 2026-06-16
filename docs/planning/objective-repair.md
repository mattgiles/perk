# Objective-repair design — the manifest-based drift + repair architecture

**Part of Objective #548, Node 4.4.** This is a `docs/planning/` design/turn doc (same genus as
`docs/planning/node-3.1-architecture-correction.md` and `docs/planning/node-4.3-outcomes.md`).
A *future* implementing session reads it as the canonical spec for the manifest-based objective
drift-detection + repair surface. It is **not** executed, imported, or tested — it has no CI
surface beyond the repo's existing markdown/prose linting.

Node 4.4's roadmap description originally framed the node as *building* the drift surface. Per
operator direction the node is reframed to *authoring this design doc* for a **manifest-based**
version of that surface, because the manifest is a prerequisite the original framing omitted. The
single deliverable of node 4.4 is this file. The objective roadmap should be reconciled post-merge
to reflect that 4.4 delivered the design and that implementation is follow-up work (see §9).

> **The decisive commitment.** Drift detection and repair are only tractable against a *persisted,
> authoritative manifest* of the intended roadmap. A baseline-free "derive everything live from
> node-issues and guess at what's missing" approach is **more** complex — now and forever — than
> persisting an expected-state manifest and diffing observed-vs-expected. The manifest is the
> source of truth for **what should exist**; the live Linear project state (node-issues, blocking
> relations, milestones, overview) is **what does exist**; **drift = diff(expected manifest,
> observed state)**, and **repair = make the observed state match the manifest** for the safe,
> unambiguous cases only.

---

## §1 · Problem statement & decision

### Why baseline-free drift detection is intractable

`LinearProjectObjectiveStore.get_objective` (in `perk/backends/linear_backend.py`) reconstructs the
roadmap **live**: it reads the project's node-issues via `_LinearProjectOps.project_issues`, parses
each node-issue's inline-code `objective-node` block, sorts by `objective.node_sort_key`, and
rebuilds `depends_on` from the `blocks`/`blocked-by` relations (`_LinearProjectOps.issue_blocks` /
`issue_blocked_by`). There is **deliberately no stored roadmap table** on the project overview
(Node 3.2); the overview carries only the `objective-header` block plus the Reconcilable prose
region.

That design is correct for the *normal read* (the live state is the runtime roadmap), but it leaves
drift detection with **no authoritative reference for "what should exist."** Concretely, with no
baseline you cannot detect or repair:

- a **missing node-issue** (deleted, or moved out of the Project) — nothing tells you a node *was*
  supposed to be there;
- a **renamed / deleted phase milestone** — `enrich_phase_names` reads the milestone name live from
  the `### Phase N:` overview header, so there is no pinned canonical name to diff against;
- an **expected-vs-actual dependency edge** — `get_objective` *silently drops* any `blocked-by`
  target that doesn't resolve to an in-project node-issue, so a missing or spurious edge is
  invisible;
- a **moved node** — re-parented under a different phase milestone with no record of its intended
  phase.

Rejected baseline-free heuristics, and **why they are worse long-term**:

- **Sequence-gap inference** ("node 2.3 exists but 2.2 doesn't ⇒ 2.2 is missing"). Brittle: node
  ids are not guaranteed dense (skipped/merged nodes are legitimate), so a gap is ambiguous between
  "missing" and "never existed." It also cannot recover the missing node's slug/description/phase
  to *repair* it — only flag a guess. Every future condition added to the catalog would need its own
  bespoke heuristic, compounding the ambiguity.
- **Empty-milestone-only detection** ("a milestone with no node-issues is orphaned"). Cannot
  distinguish a deleted node from an intentionally-empty phase, and gives no canonical name to
  restore a *deleted* milestone — it can only observe what survives, never assert what should.

Both heuristics try to *infer intent from surviving observed state*. Intent that has been destroyed
cannot be inferred — it must have been **persisted ahead of time.** The cost of persisting a
manifest is one extra overview block written at create; the cost of *not* persisting it is an
ever-growing pile of lossy heuristics that still cannot repair.

### The decision

**Persist an authoritative `objective-manifest`** of the intended roadmap on the Linear Project.

- **Detection** = `diff(manifest, observed)`.
- **Repair** = converge `observed → manifest` for the safe, unambiguous cases (§4).

### GitHub symmetry note (the manifest unifies the two backends)

The GitHub objective store already persists the **full roadmap** as the `objective-roadmap` YAML
block in the issue body (`OBJECTIVE_ROADMAP_KEY = "objective-roadmap"` in `perk/objective.py`;
`render_roadmap_block` / `parse_roadmap_nodes`). **GitHub already has an authoritative manifest** —
its own issue body. The manifest concept therefore *unifies* the two backends rather than bolting a
Linear-only thing on:

- Drift is only meaningful where observed state can **diverge** from the manifest. On Linear the
  node-issues, blocking relations, and milestones are **independently editable** in the Linear UI,
  so observed state drifts from intent. On GitHub the roadmap block is **edited atomically** with
  the rest of the issue body — there is no independent divergence surface, so a GitHub drift report
  is **trivially empty**.
- This justifies the protocol design in §5: `detect_objective_drift` / `repair_objective_drift`
  become no-ops on the GitHub and issue-backed-Linear stores (no divergence surface), and carry
  real behavior only on `LinearProjectObjectiveStore`.

---

## §2 · The manifest: storage, schema, encoding

### Storage location (Linear): a new overview inline-code block

The manifest lands as a **new inline-code metadata block in the project overview**, beside the
existing `objective-header` block, transcoded via `to_linear_markdown` (the same
dual-encoding / form-preserving discipline every other block already uses — see the module docstring
of `perk/backends/linear_backend.py` and `to_linear_markdown`).

Propose the key:

```python
OBJECTIVE_MANIFEST_KEY = "objective-manifest"   # add beside OBJECTIVE_HEADER_KEY in perk/objective.py
```

**Hidden-storage investigation (recorded so it is not re-litigated):**

- Linear has **no invisible project-level metadata field** equivalent to GitHub's `<!-- -->` HTML
  comments. ProseMirror (Linear's editor) does **not** preserve HTML comments — which is exactly why
  perk transcodes all markers to **inline code** via `to_linear_markdown` rather than HTML comments.
- The only API-only (UI-hidden) store Linear documents is **attachment `metadata`** — but an
  attachment renders a *visible card* and is documented as **issue-scoped**, not project-scoped. It
  is the wrong shape for a project-level manifest.
- **Decision: the overview inline-code block wins**, for three reasons: (1) **consistency** with
  the established `objective-header` pattern; (2) an **idempotent content-write path already exists**
  — `_LinearProjectOps.update_project_content` (used by `create_objective` and the reconcile pass);
  (3) it **survives the ProseMirror round-trip**, proven at Node 1.4. The block is
  "visible-but-unobtrusive": rendered as inline code in the overview, like `objective-header`.

### Schema (propose `schema_version: 1`)

The manifest captures the **expected structural roadmap** — *which nodes exist, their phase
membership, their canonical slug/description for recreation, and their explicit dependency edges* —
plus the **pinned canonical phase names**:

```jsonc
{
  "schema_version": 1,
  "nodes": [
    { "id": "1.1", "phase": "1", "slug": "scaffold", "description": "…", "depends_on": [] },
    { "id": "1.2", "phase": "1", "slug": "wire-loader", "description": "…", "depends_on": ["1.1"] }
  ],
  "phases": { "1": "Phase 1: Foundations", "2": "Phase 2: …" }
}
```

- **`status` is deliberately excluded.** Status is *live, editable, observed* state owned by each
  node-issue's `objective-node` block (`NodeStatus` in `perk/objective.py`). The manifest owns
  *structural identity*, never live status. (This is the load-bearing split that makes repair safe —
  see §4: recreating a missing node-issue restores its structure but **cannot** invent its status.)
- **`phases: {phase_key: milestone_name}`** pins the canonical milestone name, **decoupling** it
  from the drift-prone `### Phase N:` overview header that `enrich_phase_names` reads today. Once a
  manifest exists, the pin is the milestone-name authority (§5).

### Pure helpers to add to `perk/objective.py`

Mirror the existing `render_node_block` / `render_roadmap_block` / `parse_roadmap_nodes` family.
All **offline + deterministic** (no network, no clock):

- `render_manifest_block(nodes: list[ObjectiveNode], phase_names: Mapping[...]) -> dict` — produces
  the structured block payload (consumed by `to_linear_markdown` at the call site, same as
  `render_node_block`).
- `parse_manifest(overview: str) -> tuple[Manifest, list[str]]` — extract + validate the
  `objective-manifest` block from the overview text; returns the parsed manifest plus a list of
  structural errors (mirrors `validate_roadmap` / `parse_roadmap_nodes` returning `(nodes, errors)`).
- A `Manifest` dataclass holding `schema_version`, the node entries (reuse `ObjectiveNode` for each
  entry, with `depends_on` populated and `status` left at its default/ignored), and the
  `phase_names` map. Reusing `ObjectiveNode` keeps the render/parse path uniform with the rest of
  the module; the *only* manifest-specific addition is the `phase_names` map.

---

## §3 · Observed-vs-expected model (the diff engine)

### The observed snapshot

A pure data structure capturing **what does exist**, built from the live Linear project:

- **node-issues**: for each, the parsed `objective-node` block (id/status/etc.), the raw issue
  body, its **milestone membership**, and whether it carries a `plan-header` (i.e. has a saved
  plan — affects the duplicate-id severity in §4).
- **blocking relations** per node-issue, including targets that **don't** resolve to an in-project
  node-issue (the unknown/cross-project blockers — `get_objective` silently drops these today; the
  snapshot must *retain* them so §4 can disclose the reinterpretation).
- **milestones**: `{id, name}` (order ≠ insertion order — name is the key, per Node 4.3).
- **overview**: the integrity of the `objective-header` / `objective-manifest` blocks and the
  Reconcilable markers (`OBJECTIVE_RECONCILABLE_MARKER_START/END`).

**Snapshot query change (named explicitly).** `_LinearProjectOps.project_issues` today returns
`{id, identifier, url, description}` and carries **no milestone membership**. The snapshot needs
milestone membership per node-issue. The doc mandates this is a **new** op (or an explicitly
separate selection) — e.g. `project_issues_with_milestones` selecting `projectMilestone { id name }`
— and **must not perturb** `get_objective`'s existing byte-stable `project_issues` query or its
pinned tests. Do not extend the existing query in place; add a sibling.

### The diff engine: a pure module

A new module `perk/objective_drift.py` with a **pure** entrypoint:

```python
def detect_drift(manifest: Manifest, observed: ObservedSnapshot) -> DriftReport: ...
```

The diff is **pure and fully offline-testable**. Only the snapshot *build* and the repair
*execution* touch the network — keep them out of `detect_drift` so the condition catalog (§4) is
unit-tested without a fake Linear. (`DriftReport` is a list of typed conditions; see §6 for its
JSON shape.)

---

## §4 · The full condition catalog (honoring Node 4.4's list)

Every condition is expressed as **manifest ⨯ observed**, with a severity and a **repair
classification**: `--fix` only for the **safe, unambiguous** cases; everything else is
**report-only-by-hand**. perk **never silently reinterprets** — it reports.

| Condition | Detection (manifest ⨯ observed) | `--fix`? |
|---|---|---|
| **missing node-issue** (incl. *moved out of Project*) | id in `manifest.nodes`, no observed node-issue with that id | **REPAIRABLE** — recreate the node-issue from the manifest entry (id/phase/slug/description → `_LinearProjectOps._create_issue` + an `objective-node` block via `render_node_block` + attach to the phase milestone via `ensure_phase_milestone` + `attach_issue_to_project`). The single biggest manifest win. Status is **not** restored (the recreated node carries a default/blank status — the human re-sets it; auto-restoring would invent live state). |
| **duplicate node ids** | ≥2 observed node-issues share an id the manifest has once | **report-only** — which to keep is ambiguous; **both may carry a plan** (the `has-plan-header` snapshot field), so deleting either risks losing work. |
| **missing / malformed node status block** | observed node-issue (id in manifest) has an absent or invalid `objective-node` block | **report-only** — cannot infer the intended live status; restoring a default would **invent state**. |
| **blocking-relation cycle** | observed `blocks` graph among node-issues is cyclic | **report-only**, **manifest-enriched** — name the observed edges *not in* `manifest.depends_on` (the human-added ones) to guide the fix. perk does not pick an edge to cut. |
| **unknown / cross-project blocker reference** | observed `blocked-by` target is **not** an in-objective node-issue | **report-only / informational** — a legitimate external dependency is **NOT drift** (operator correction). The only thing surfaced is the **silent-reinterpretation disclosure**: perk's roadmap graph (and the manifest) cannot represent the edge, so `next` / selection ignores it. **Never repairable, never "this belongs in the objective."** |
| **inferred-vs-Linear-visible dependency mismatch** | `manifest.depends_on` (expected) ⨯ observed `blocks` relations | edge **in manifest, absent in Linear** → **REPAIRABLE** (create the relation via `create_issue_relation`; the manifest is authoritative). Edge **in Linear, absent from manifest** (both endpoints nodes) → **report-only** (intentional human edit; deleting is a judgment call). |
| **deleted phase milestone** | a phase in `manifest.phases` has no milestone matching its **pinned** canonical name | **REPAIRABLE** — recreate via `ensure_phase_milestone(name=<manifest pinned name>)` + reattach the phase's node-issues. Also resolves the Node 4.3 **rename-orphan**: a milestone whose name ≠ the manifest's pinned name is **reported** (report-only delete) while the canonical one is restored. |
| **node-issue moved out of Project** | folds into *missing node-issue* | **REPAIRABLE** — recreate/reattach from the manifest. |
| **overview / document Reconcilable-marker damage** | the overview's `objective-header` / `objective-manifest` block or the Reconcilable markers are absent / malformed / unclosed | **report-only** — re-wrapping prose is ambiguous; a **damaged manifest block disables detection entirely** and must **fail loud**, never silently proceed. |

**The never-silently-reinterpret principle (restated).** Each report-only condition is report-only
*because auto-repair would invent information*:

- *duplicate ids* — choosing a survivor invents a preference (and may discard a plan);
- *missing status block* — a default status invents live state;
- *cycle* — cutting an edge invents intent;
- *unknown blocker* — claiming the edge "belongs" invents a relationship; ignoring it silently
  would hide a real external dependency, so perk **discloses** the reinterpretation instead;
- *Linear-only dependency edge* — deleting it invents that the human's edit was a mistake;
- *marker damage* — re-wrapping prose invents structure, and a damaged manifest **must** halt
  detection loudly rather than diff against a corrupt baseline.

The REPAIRABLE cases are safe precisely because the manifest **already records the exact intended
structure** — recreation copies a persisted fact, it does not guess.

---

## §5 · Manifest-awareness across the codebase (operator mandate #3)

Every site that must become manifest-aware, with exact behavior:

- **`LinearProjectObjectiveStore.create_objective`** (`perk/backends/linear_backend.py`) — write the
  `objective-manifest` block into the overview **at create**, capturing every node's
  id/phase/slug/description/depends_on **plus the pinned phase names** from `enrich_phase_names`
  (the seed). This goes alongside the existing `objective-header` write through
  `update_project_content`.
- **`objective.add_node`** (`perk/objective.py`) — **dormant / caller-less today, but explicitly in
  scope** (operator mandate: dormant funcs are manifest-aware too). When a node is added it must
  **update the manifest**: append the node entry, and **pin a new phase name** if it introduces a
  new phase. Document this even though no live caller exists yet, so the function is correct the day
  a caller appears.
- **`LinearProjectObjectiveStore.update_objective_node`** — a **status** change does **not** touch
  the manifest (status is observed-only). A **`description` / `slug`** change **does** sync the
  manifest entry, because the manifest owns *structural identity* and must stay authoritative.
- **`objective-reconcile`** (`reconcile_cmd.reconcile_objective`, `perk/cli/commands/objective/
  reconcile_cmd.py`) — **manifest-aware (mandate #2)**. After a merge, reconcile refreshes the
  manifest's node descriptions / phase-name pins to match the reconciled roadmap, and **MAY** run
  the drift diff to surface conditions it cannot itself fix. **Ordering:** reconcile updates the
  Reconcilable prose **and** the manifest in the **same pass** (one `update_project_content`-class
  write), so the prose and the manifest never diverge mid-reconcile.
- **`get_objective`** — stays **observation-based**. The live read is the runtime roadmap; the
  manifest is the *expected* baseline used **only** by drift, never by the normal read. Document the
  **two-sources model** unambiguously so a future reader does not fuse them: `get_objective` answers
  *what is*; the manifest answers *what should be*; only `detect_drift` compares them.
- **Phase-name authority** — once a manifest exists, the **pin supersedes** `enrich_phase_names` as
  the milestone-name authority (resolving the Node 4.3-flagged rename-orphan). `enrich_phase_names`
  remains the **seed** at create time only.

### Backend-neutral protocol surface

Add two methods to the `ObjectiveStore` `Protocol` (`perk/backends/objective_store.py`):

- `detect_objective_drift(*, objective_id) -> DriftReport`
- `repair_objective_drift(*, objective_id, dry_run=False) -> RepairResult`

`GitHubObjectiveStore` (in `perk/backends/objective_stores.py`) and the issue-backed
`LinearObjectiveStore` return an **empty / no-op** result — mirroring the established
`save_node_plan → None` / `post_status_update → False` "no surface, no-op" precedent (Node 4.3
added `post_status_update` as the 9th method; these are the 10th and 11th). Only
`LinearProjectObjectiveStore` carries real behavior, since only the project-backed store has a
divergence surface (§1's GitHub symmetry note).

**Rejected alternative:** branching on `backend_id` inside the `doctor` command to special-case the
project-backed store. Rejected because **protocol uniformity wins** — the command resolves one
`ObjectiveStore` through `resolve_objective_store` and calls one method; the "which backend has a
surface" decision lives in each store's conformance, exactly like `post_status_update`. A
`backend_id` branch in the command would re-introduce the type-switching the protocol exists to
delete.

---

## §6 · The CLI surface

A new worker command in the objective group (`perk/cli/commands/objective/`, registered on the
`SectionedAliasGroup` beside `show` / `node` / `next` / `reconcile` / `create` / `run`):

```
perk objective doctor <id> [--json] [--fix]
```

- Resolves the store through `resolve_objective_store(repo_root)` — **fully backend-neutral**.
- `--json` → the machine drift report to **stdout**; human-readable summary to **stderr** (the
  supervisor CLI shape every worker follows: `--json` to stdout, human to stderr,
  `ObjectiveStoreError → fail`).
- `--fix` → apply the **safe** repairs (the REPAIRABLE rows of §4) via `repair_objective_drift`,
  then **re-report** the remaining conditions.

**JSON report schema** (a list of conditions plus a `--fix` summary):

```jsonc
{
  "objective_id": "548",
  "conditions": [
    {
      "code": "missing_node_issue",      // stable machine code per §4 row
      "severity": "error" | "warning" | "info",
      "node_id": "2.3",                   // optional — present when node-scoped
      "target": "…",                      // optional — e.g. the unknown blocker identifier
      "message": "human-readable description",
      "repairable": true
    }
  ],
  "fix": {                                // present only under --fix
    "applied": [ { "code": "...", "node_id": "..." } ],
    "remaining": [ { "code": "...", "node_id": "..." } ]
  }
}
```

A clean objective reports `conditions: []`. A GitHub-backed objective always reports `[]` (no
divergence surface — §1). The `doctor` worker is the **only** consumer that builds the observed
snapshot + runs `detect_drift` + (optionally) `repair_objective_drift`; `reconcile` MAY run the
diff for surfacing but does not own the surface.

---

## §7 · Migration / backfill

Existing project-backed objectives created **before** the manifest landed have **no**
`objective-manifest` block.

**Decision: backfill from observed, as a one-time repairable condition** (option (a), not an
explicit `--init-manifest` gesture). `perk objective doctor` detects "no manifest block in the
overview" and, under `--fix`, **backfills the manifest from the current observed node-issues**,
treating present state as intended (capturing each node's id/phase/slug/description/depends_on and
pinning the current phase-milestone names).

**Justification.** Backfill-from-observed is safe **precisely because it asserts "current =
intended" at a known-good moment** — the operator runs `doctor --fix` deliberately, against an
objective they have just inspected, so snapshotting the present as the baseline is an *intentional*
assertion, not a guess. It also reuses the same render path as create (`render_manifest_block`), so
there is no second code path. A dedicated `--init-manifest` flag is rejected as redundant: it is the
same operation as repairing the "no manifest" condition, and folding it into `--fix` keeps one
gesture. (Detection of "no manifest" without `--fix` reports it as a repairable condition so the
operator sees it before acting.)

---

## §8 · Contracts & docs follow-up (deferred, but named)

The **implementation** nodes (not node 4.4) must — in the *same arc as the code*, per the "amend the
contract / update the docs, don't drift" discipline:

- Amend `shared/contracts.md` **§8.24** (the objective-storage tier): the `objective-manifest` as a
  **third overview block** beside `objective-header` and the Reconcilable region; the
  observed-vs-expected drift model; the `perk objective doctor` worker + its JSON report schema; and
  the two new protocol methods (`detect_objective_drift` / `repair_objective_drift`, taking the
  method count 9 → 11).
- Update `docs/user-docs` with a **how-to** for `perk objective doctor` (the Divio how-to quadrant),
  covering the report, `--fix`, and the backfill posture.

These do **not** land in node 4.4 (design-only).

---

## §9 · Scope boundary for node 4.4

Node 4.4 delivers **only** `docs/planning/objective-repair.md` (this file). Out of scope here,
explicitly named as **follow-up implementation work** (candidate new objective nodes):

- the manifest storage (`OBJECTIVE_MANIFEST_KEY` block + `render_manifest_block` / `parse_manifest`
  / `Manifest` in `perk/objective.py`);
- the `perk/objective_drift.py` module (`detect_drift`, `DriftReport`, the observed snapshot);
- the snapshot query change (the new milestone-membership op beside `project_issues`);
- the `perk objective doctor` worker + `--fix`;
- the manifest-awareness wiring across `create_objective` / `add_node` / `update_objective_node` /
  `reconcile` and the two new protocol methods;
- the `shared/contracts.md` §8.24 + `docs/user-docs` amendments (§8).

### Testing posture (recorded for the implementation nodes)

Node 4.4 carries **no test surface** (a planning doc; only existing markdown/prose linting applies).
The *implementation* nodes carry the coverage:

- a **pure `detect_drift` unit suite** over `perk/objective_drift.py` (offline, no fake Linear) —
  one case per §4 condition, both the report-only and the repairable classifications;
- **manifest render/parse round-trip** tests (`render_manifest_block` → `to_linear_markdown` →
  `parse_manifest`), proving ProseMirror-round-trip stability like the Node 1.4 marker tests;
- a **`doctor` / `--fix` CLI test** through the `FakeLinearWorkspace` substrate, asserting the JSON
  report schema (§6), the applied/remaining split, and the backfill-from-observed path (§7).
