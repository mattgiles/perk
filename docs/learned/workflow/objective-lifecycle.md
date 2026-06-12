---
title: Objective lifecycle — resumable-lease node states, classified selection, authoring loop
read_when: You are working on objective node status transitions, the objective-plan factory selection, the objective authoring/save loop (the review-first objective-draft JSON artifact, render-at-the-door, the draft-module-leaf rule), the deterministic perk objective run supervisor loop, or debugging a node stuck in planning.
---

# Objective lifecycle

An objective is a roadmap of nodes that `objective-plan` plans one at a time. The node status machine
and the authoring loop both carry non-obvious design decisions worth preserving.

## The resumable-lease node state machine

### The bug class it fixes: eager mark + no compensating transition = one-way limbo

`objective-plan` marked a node `planning` **eagerly** before launching the read-only plan session,
but the only automatic exit from `planning` was armed by a **separate, skippable model step** (the
`pr`-only `objective_node` backlink *after* `plan_save`). Any interruption before that backlink
landed (session abandoned, plan never saved, step skipped) orphaned the node in `planning`+`pr=null`:
not `pending` (unselectable), not terminal (blocks the chain), never auto-recovered. With a
no-explicit-deps objective compiled into a strict sequential chain, **one stuck head node blocks the
entire objective** and the factory emits a misleading "all blocked or complete."

**Generalizable lesson:** any eager state mark needs either a compensating/idempotent re-entry path
or an atomic commit — never leave a transient state that only a skippable downstream step can exit.

### The two reusable fixes

1. **Resumable lease.** `planning` = a *claim* (re-selectable until a plan is committed);
   `in_progress` = a *committed plan*. The discriminator is **belt-and-suspenders on `node.pr`**: a
   `planning` node with `pr is None` is plannable/resumable; with a `pr` it's in-flight. An abandoned
   claim self-heals on the next `objective-plan` run with **zero migration** for pre-existing
   orphans. The `DependencyGraph` helpers `plannable_nodes()` / `next_plannable()` (unblocked ∧
   pending-or-resumable-planning) and `in_flight_nodes()` encode this.
2. **Classified selection beats a boolean `None`.** `classify_for_planning()` returns a
   `PlanSelection(kind, node)` with `kind ∈ {plannable, in_flight, blocked, complete}`, so the cold
   door gives *honest, targeted* guidance (a new `objective_in_flight` error → "implement it or reset
   to re-plan") instead of one canned error. **When a selector can fail for several distinct reasons,
   return the *reason*, not `None`.**

### Atomic commit detail

`github.update_objective_node` accepts `status` **and** `pr` in one call, so the backlink +
`planning → in_progress` advance is a **single write** inside `plan-save` (threaded via `--node-id` +
the warm tool's `node_id`). It is fail-open + non-fatal + idempotent on re-save — mirrors
`_reconcile_objective_on_land`'s fail-open posture (the durable artifact already exists, never raise
after it).

### Pending-first selection over live claims

`next_plannable()` prefers **pending** nodes over resumable `planning` claims (the claim set is
`resumable_claims()` in `perk/objective.py`), so parallel plan sessions don't steal each other's
claims while pending work exists. The fallback resume can still "steal" a live claim when it's the
*only* plannable node — `objective show`'s `claims:` line / the `resumable_claims` JSON field is
the coordination surface for humans running sessions in parallel. There are still **no lease
timestamps/heartbeats**: a live claim and an abandoned claim remain indistinguishable, and
pending-first ordering makes that acceptable only as long as implicit selection has pending work to
prefer.

**Accepted backlink race:** concurrent `update_objective_node` read-modify-writes can drop one
node's update; recovery is an idempotent `/plan-save` re-save or a manual `perk objective node`.
If parallel planning becomes heavy, this is the seam to harden first.

The race **has recurred in practice** (a plan saved with its objective/node ids whose `pr`
backlink never landed): a `planning`-stuck node with `pr: null` *after its plan's PR merged* is
now a **known signature** of this race, not an anomaly — the land-time mechanical done-mark only
marks the *backlinked* node, so it skips the racy one. `/objective-reconcile` is the working
safety net (sets `pr` + `done` with audit); expect reconcile passes to encounter this shape.

The `perk objective run` supervisor stays sequential but **inherits pending-first** — its
`plan_required` remediation points at a pending node, not a possibly-live claim; parallel dispatch
(concurrent runs, budget aggregation) is deferred.

### "JSON mode" ≠ "JSON payload emitted" in the objective-plan cold door

Only `--dry-run --json` emits a JSON payload from `objective-plan`; the launch path execs pi and
never returns, so `--json` *without* `--dry-run` still gets advisory stderr notes (e.g.
skipped-claims). Gate advisory stderr on "would a JSON payload be emitted", not on the `--json`
flag alone.

### Parallel-node rebase friction (generalizable)

When a convergence-sweep node runs in parallel with feature nodes, a mid-implementation rebase can
remove or rename exactly the kind of small seams plans anchor on — **re-read every plan-anchored
module after rebasing**; the first `edit` oldText mismatch is the tell. Relatedly, re-verify
roadmap scope counts (e.g. "~6 casts" vs an actual 9) against the tree at planning time rather
than trusting node prose. The mild common case is an import-list conflict — multi-line
one-import-per-line lists make those trivial (union both sides).

### Scoping that held: don't over-plumb

`node_id` is a **transient plan-save input only** — NOT persisted on `PlanHeader`/`PlanRef`. The land
path matches via `node.pr` (`nodes_for_pr`) and `/objective-reconcile` uses `objective_id`, so the
durable plan schema didn't need widening.

**Residual risk:** a transient link failure on save (issue created, `update_objective_node` fails)
leaves the node `planning`+`pr=null` → *resumable*, so a fresh run could author a **second** plan for
it. Mitigated by a loud stderr warning + idempotent re-save; the real fix (deterministic node-claim
via an `active_objective_node` workflow-state field) is deliberately out of scope. The cold
`objective-plan` door does **not** set `active_objective` in session today, which is why `node_id`
stays model-passed (symmetric with `objective_id`) rather than session-state-derived.

## The objective authoring loop mirrors plan → save

`objective-author` + `objective-save` are the in-session mirror of the `plan → save` loop: a new
objective + roadmap is drafted and saved from inside a session. When implementing such a loop, **the
sibling `plan`-loop implementation is the contract** — copy its shape (temp-file for prose, JSON arg
for structured data, delegate to the Python cold door, link the session, terminate).

### Two read-only authoring stages sharing a `mode` need a `stage` discriminator

Once `plan` and `objective-author` both run read-only, the interior must know *which* — context
injection can no longer key off the read-only gate alone. A `stage` field on `perk:workflow-state` is
persisted at **cold claim** from the handoff blob; `planMode` defers when `stage ===
"objective-author"` and `objectiveAuthor.ts` injects instead (exactly one authoring context present).
This stage-field disambiguation pattern is detailed in `pi/context-injection.md`.

### The review-first authoring loop's artifact mechanics

The objective authoring loop is review-first and file-first: `objective_draft` writes a session
artifact, `plan_review` renders + reviews it, and an APPROVED verdict auto-saves through the
`objectiveApprovalSave` seam. The artifact mechanics worth preserving:

- **Store-as-JSON, render-at-the-door.** `objective_draft` writes a JSON artifact
  (`{schema_version: 1, title?, prose, roadmap}`); the digest is computed over the **serialized
  JSON**, not the prose; and the roadmap rides verbatim as `unknown[]` — node-shape validation
  stays with the Python plane at save time. JSON is storage/transport only; the human review
  surface renders markdown from it.
- **Renderers live with the artifact owner, not the consumer.** `extension/objectiveDraft.ts`
  exports both the reader (`readObjectiveDraft` — fail-open validation, warn+null on bad
  JSON/shape/schema_version/blank prose) and the markdown renderer (`renderObjectiveDraft`).
  That keeps `planReview → objectiveDraft` cycle-free: the draft module never imports review
  modules. `schema_version` is the consumer branch point — consumers must validate/branch on it
  rather than assuming the shape.
- **Draft module = leaf.** When a save module needs to value-import the draft reader, move the
  shared param vocabulary INTO the draft module rather than extracting a third module — mirrors
  planDraft←planSave; the import direction is draft→save only, never the reverse. (An exported
  `as const` schema is accepted by tsc directly in `registerTool` parameters — no widening cast.)
- **The asymmetric objective failsafe.** `/objective-save` is artifact-first but keeps the
  drive-the-session injection as the **no-draft fallback** — objectives have no transcript scrape
  by design (a structured roadmap is unscrapeable), so unlike `/plan-save` (which warns and stops
  on no-plan) the objective command must still hand the save to the model. Its severity ladder is
  also simpler: no `warning` tier, because objective saves have no node-link sub-step.
- **Known wart: an approved empty-roadmap draft save-fails.** The draft reader accepts
  `roadmap: []`, so the review surface happily reviews a roadmap-less objective; the save then
  hits `perk objective create`'s `empty_roadmap` rejection. It degrades correctly
  (non-terminating save-failed result, gate stays read-only, the `/objective-save` failsafe is
  directed) — a pre-review/pre-save nudge would surface it earlier.

### Residual: objective_save is not an upsert

`create_objective_issue` is idempotent on `run_id` but on a hit **returns the existing issue without
updating it** — unlike `plan_save`'s in-place upsert. Re-running `objective_save` after editing the
prose/roadmap in the same run will **not** push the edits. A genuine follow-up gap (see
`plan-save-surfaces.md` for the symmetric-write discipline this violates).

## The `perk objective run` supervisor loop

`perk objective run` is a **deterministic, no-agentic-reasoning** supervisor that advances the
objective backlog **one safe step per invocation**, then pauses at the human land gate. The
composition + testing mechanics live in `cold-door-launch.md`; the design *semantics* are here.

### It never lands and never plans

These are deliberate corrections against the roadmap node's "→ plan → implement → … via the runner"
text, which was **fiction**:

- **Never lands.** Landing via a local stage launch would destroy the loop — a local stage
  `execvpe`s pi and never returns (see `cold-door-launch.md`). Landing stays the human/interactive
  `/land`, and a node reaches `done` only via that path's `_reconcile_objective_on_land`. The loop
  merely *observes* terminality (a MERGED PR → `merged_pending_reconcile`).
- **Never plans.** Planning cannot be dispatched remotely (`objective-plan` is `cold_remote:false`),
  so the supervisor emits a `plan_required` action + remediation string
  (`perk objective-plan <N> --node <id>`) rather than authoring a non-existent remote-plan path.

Frame both as the **"don't author fiction for an unbuilt path"** discipline applied to a supervisor.

### PR existence is the implement-done signal

A draft PR ≠ "keep implementing." Branch on `plan_state.pr`:

- `None` → dispatch implement
- OPEN + draft → `ready_for_review` and stop
- OPEN + non-draft → `needs_address` predicate (dispatch address | `awaiting_review`)
- MERGED → pending-reconcile
- CLOSED → `pr_closed`

### "Wait, then re-decide" must re-fetch the *whole* world it waited on

Under `--wait`, after a polled run settles you must re-fetch `github.get_objective` + rebuild the
dependency graph **before** classifying — a completed run can advance GitHub state, so classifying
against the pre-poll snapshot is a correctness bug (review-caught). General lesson for any
poll-then-act loop.

### The `needs_address` predicate

Latest-review-*per-author* tie-break via ISO-8601 string compare with `>=` (`None` sorts oldest).
`COMMENTED`/`APPROVED` reviews and discussion comments are **never** triggers — only an unresolved
thread or a latest-`CHANGES_REQUESTED` review.

### `--dry-run` short-circuits *before* `launch_stage`

The regression test asserts `launch_stage` is **not** called (no mint/write/trigger) rather than
relying on `launch_stage`'s own dry-run preview.

### Budget is report-only

By resolved decision: cumulative `{runs,turns,tokens,elapsed_ms}` summed across dispatch records
filtered by canonicalized `plan_ref.objective_id` (`str(...).lstrip("#")`). No thresholds, no
enforcement, no `budget_exhausted`.

### Defensive parse of `node.pr`

Guard `node.pr` with `.isdigit()` before `int(str(node.pr).lstrip("#"))` and fall through to the
existing `plan_required` fallback on a malformed/non-numeric id.

## Cross-references

- `perk/objective.py` — `DependencyGraph` (`plannable_nodes`, `next_plannable`, `resumable_claims`,
  `classify_for_planning`, `PlanSelection`)
- `perk/cli/commands/objective_cmd.py` — the `perk objective run` supervisor (`needs_address`, classification)
- `docs/learned/workflow/cold-door-launch.md` — the composition + testing mechanics the supervisor relies on
- `shared/contracts.md` §8.20 — the capstone supervisor loop contract
- `extension/objectiveAuthor.ts` + `perk` objective-author/save stages — the authoring loop
- `docs/learned/workflow/plan-save-surfaces.md` — the node→plan link carrier + re-save discipline
- `docs/learned/pi/context-injection.md` — the `stage`-field disambiguation of shared-mode stages
- `docs/learned/workflow/plan-ref-lifecycle.md` — the fail-open on-land bookkeeping shape
