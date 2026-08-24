# Checkpoints vs. `@juicesharp/rpiv-todo`: a candidate-by-candidate adoption survey

**Status:** superseded (Objective #1416) — the survey's subject (first-party checkpoints) is
deleted; `rpiv-todo` was adopted as a **required borrow**, and the P2.T2c
passive/plan-derived/never-model-mutated decision is superseded by the dynamic, model-owned
checklist (see the checkpoints-successor block in `shared/contracts.md`). The evaluation record
itself stays — it documents *why* the foreign design won. Originally: durable evaluation record
(plan #502). Surveys `@juicesharp/rpiv-todo`'s
implementation against perk's first-party "todo" surface — the **checkpoints** system — and records
the one charter-compatible robustness idea adopted plus the rejected ideas, so this evaluation does
not get re-litigated. See also `docs/design/archive/provider-smoke-juicesharp-todo.md` (the foreign-adapter
coexistence smoke) and the P2.T2c checkpoints block in `shared/contracts.md`.

## The two designs

**perk's checkpoints** (provider id `perk-checkpoints`, `extension/checkpoints/checkpoints.ts`,
registered by `registerCheckpoints(pi, status)`) are **passive, plan-derived, and linear by
deliberate charter decision (P2.T2c)**:

- State is parsed from `[WIP:n]`/`[DONE:n]` markers the assistant emits in its prose, seeded from
  the plan body's `## Steps` numbered list (or an LLM-generated checklist for prose plans, #342).
- State lives in a dedicated `perk:checkpoint` session entry, rebuilt from the branch with the
  **scan-after-marker** discipline (stale `[DONE:n]` from a previous execution cannot resurrect a
  step).
- It is **never model-mutated** — there is no model-callable tool; the model only emits markers.
- It is surfaced as the `📋` segment of the composed `perk` status slot, a `belowEditor` themed
  widget (`renderProgressLines`/`windowProgress`), and the `/checkpoints` command.

**`@juicesharp/rpiv-todo`** is the opposite design: a **model-driven `todo` tool**
(create/update/list/get/delete/clear) with a 4-state machine + `VALID_TRANSITIONS` table
(`state/invariants.ts`), a `blockedBy` dependency graph with DFS cycle detection
(`state/task-graph.ts`), `activeForm` present-continuous labels, a pure reducer/store/replay seam
split (`state/state-reducer.ts`, `state/store.ts`, `state/replay.ts`), and an `aboveEditor` overlay
(`todo-overlay.ts`) where completed tasks fall away after the next agent turn.

perk already knows this package intimately: perk **borrowed** it, then **retired** it in P2.T12 in
favor of the perk-owned `perk:checkpoint` seam, then re-adopted it as an **optional foreign todo
provider** in Node 3.2 via the injection-only `extension/adapters/todoAdapterJuicesharp.ts` shim.
The two designs are divergent **by charter**.

## Candidate-by-candidate verdict (verified against our code)

| rpiv-todo idea | Verdict | Rationale |
| --- | --- | --- |
| Model-driven `todo` tool / `blockedBy` graph / dynamic create-update-delete | **REJECTED** | Explicit non-goal. perk separates plan (read-only) from implement; checkpoints derive from the plan's `## Steps`, are linear/ordered, and are never model-mutated. Adopting these would reverse the P2.T2c design. |
| `activeForm` present-continuous label | **REJECTED** | Doesn't fit. checkpoints are marker-driven (`[WIP:n]`/`[DONE:n]`); there is no channel for the model to supply a label, and the step *text* already serves as the in-progress label (`▸n <text>`). Adopting it would require expanding the marker grammar — a protocol change, not polish. |
| Completed-fall-away overlay | **REJECTED** | Our widget already does richer overflow handling: `windowProgress(state, cap)` slides a window anchored on the current step with `… +N earlier`/`… +N later` elision. rpiv's "completed drop after the next turn" is a *different* philosophy, not clearly better for an ordered linear checklist. |
| `session_compact` re-render + stale-`ctx` guard | **ADOPT (narrow)** | rpiv subscribes to `session_compact` and wraps the replay in a guard that swallows pi-core's `/stale after session replacement/` proxy error (the extension runner is invalidated mid-compaction while the event still fires), rethrowing only genuine replay bugs (`index.ts` `isStaleCtxError`). perk's checkpoints did **not** subscribe to `session_compact` at all. Our state is largely robust already (the replacement session's `session_start` rebuilds, and completion is persisted into `perk:checkpoint` marker entries carried forward), so the win is modest — but the stale-`ctx` race is a real, hard-won pi gotcha and the cheapest charter-compatible adoption. |

## What was adopted (plan #502)

A `session_compact` handler in `registerCheckpoints`, placed immediately after the `session_tree`
handler and **mirroring it exactly** (guard on `isPerkCheckpointsReferenceSelected(ctx.cwd)`, then
`renderStatus(ctx, status, rebuildCheckpoint(branchOf(ctx)), branchOf(ctx))`) — rebuild + render
only, **no re-seed**. The `catch` arm diverges from the other handlers: it **silently `return`s when
`isStaleCtxError(error)`** (the dying session is discarded and the replacement session's
`session_start` re-renders), otherwise logs per the log-not-throw convention. `isStaleCtxError(e)`
returns `/stale after session replacement/.test(String(e))`, adapted from rpiv-todo's `index.ts`.

This is **narrow, polish/robustness-only**. perk's checkpoints stay passive, plan-derived, and
linear — none of rpiv-todo's substance (the model-mutable tool, dependency tracking, dynamic
create/delete) is adopted.
