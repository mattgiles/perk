---
title: Objective lifecycle — resumable-lease node states, classified selection, authoring loop
read_when: You are working on objective node status transitions, the objective-plan factory selection, the objective authoring/save loop, or debugging a node stuck in planning.
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

### Residual: objective_save is not an upsert

`create_objective_issue` is idempotent on `run_id` but on a hit **returns the existing issue without
updating it** — unlike `plan_save`'s in-place upsert. Re-running `objective_save` after editing the
prose/roadmap in the same run will **not** push the edits. A genuine follow-up gap (see
`plan-save-surfaces.md` for the symmetric-write discipline this violates).

## Cross-references

- `perk/objective.py` — `DependencyGraph` (`plannable_nodes`, `classify_for_planning`, `PlanSelection`)
- `extension/objectiveAuthor.ts` + `perk` objective-author/save stages — the authoring loop
- `docs/learned/workflow/plan-save-surfaces.md` — the node→plan link carrier + re-save discipline
- `docs/learned/pi/context-injection.md` — the `stage`-field disambiguation of shared-mode stages
- `docs/learned/workflow/plan-ref-lifecycle.md` — the fail-open on-land bookkeeping shape
