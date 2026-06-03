# Phase 2 — the gate record

> The explicit, visible boundary that closes **Phase 2** and opens **Phase 3**. It records the
> end-to-end demonstration of the ROADMAP's Phase-2 acceptance gate — **perk drives its *full*
> deepened workflow on itself** — on perk's own repo. Authored in T12 (see
> [phase-2-turn-12.md](./phase-2-turn-12.md)); the live-run evidence is filled after the operator run.

## The gate (verbatim, from [phase-2-plan.md](../phase-2-plan.md) §"Acceptance gate")

> **perk drives its *full* workflow on itself.** On a real perk change: an **objective selects the
> next plan** (the plan factory), the **read-only CI executor iterates** (Run→Report→Fix→Verify), a
> **review is classified and resolved** (`/address` in an isolated child), and **objective prose
> reconciles after landing** — end to end, on perk's own repo, with each stage's transitions gated
> structurally (read-only modes enforced by tool gating, not prompting). `rpiv-todo` checklists are
> retired in favor of perk-owned checkpoints; the borrow→own internalization is largely complete.

## How the gate maps onto what Phase 2 built

Each clause of the gate is built by a specific turn (the deepened stages, not just the spine):

| Gate clause | What built it | Turn |
| --- | --- | --- |
| An **objective selects the next plan** (the plan factory) | objective storage + dependency-graph `next` mechanics; the `/objective-plan` factory + completion-audit (new `objective-plan` stage, the new initial node) | T9 / T10 |
| The **read-only CI executor iterates** (Run→Report→Fix→Verify) | the perk-owned, in-process check runner backing `run_ci` — a stateless oracle (reports, never fixes/loops), on the in-process SDK isolation primitive | T5 (on T4) |
| A **review is classified and resolved** (`/address` in an isolated child) | the `/address` review loop (new `address` stage): classify-then-act, verbose feedback in a spawned read-only child, parent fixes + `resolve_review_threads` batches the resolves | T7 (on T6) |
| **Objective prose reconciles after landing** | Mechanical node-done on land + the `reconcile_objective` tool rewriting only the Reconcilable prose region | T11 |
| Transitions **gated structurally** (read-only enforced by tool gating, not prompting) | the tool-gating primitive + perk-owned plan mode | T1 / T2 |
| `rpiv-todo` **retired** in favor of perk-owned checkpoints | the `perk:checkpoint` seam (T2c) satisfies the conditional gate; the package is dropped from `BORROWED_PACKAGES` + `.pi/settings.json` (T12) | T2c / T12 |

GitHub mutations stay canonical in the Python gateway; the warm doors **delegate** to thin workers via
`pi.exec` (contracts §8.4).

## What was demonstrated

### Automatable preconditions — PASS (the cumulative gates)

The deepened loop is present, healthy, and launchable **fully offline** — proven by `just verify`
(all gates green, Phase 0 + Phase 1 + Phase 2 t1–t12), with the new **`scripts/verify-p2-t12.sh`**
asserting this turn's preconditions:

1. **scaffold + healthy** — fresh repo → `perk init` → `perk doctor --json healthy:true`, exit 0.
2. **`rpiv-todo` retired** — absent from the scaffolded `.pi/settings.json` **and** from
   `perk.init.BORROWED_PACKAGES`; the surviving borrowed set (`@tombell/pi-diff`,
   `@tombell/pi-status`, `pi-subagents`) + the `@perk/pi`/`..` self entry present; `settings-wiring` ok.
3. **both new stages filled + self-check passes** — `perk registry check` exit 0; `address` and
   `objective-plan` each have non-empty `requires`/`reads`/`writes` and a complete `doors` map;
   `objective-plan.predecessors == []` with `plan` in `successors`; `address` sits between `submit`
   and `land`.
4. **checkpoints own implement-progress** — `extension/checkpoints.ts` exports the `perk:checkpoint`
   entry (`CHECKPOINT_TYPE`), the perk-owned overlay `rpiv-todo` is retired *in favor of*.
5. **gate record present** — this file, asserting "Phase 2 gate met".
6. **retirement test green** — `tests/test_init_idempotent.py` passes (the new `rpiv-todo not in
   packages` assertion + the existing wiring assertions).

### The live run — perk drives its full deepened workflow on itself

> _Pending the live run — filled post-hoc (mirrors phase-1-gate.md)._
>
> The operator runs the [phase-2-turn-12.md](./phase-2-turn-12.md) §"Live dogfood runbook" on
> `github.com/mattgiles/perk`: **create a Phase-3 objective** → **`/objective-plan`** selects the next
> actionable node and emits a bounded plan → **`perk implement`** with the read-only CI executor
> iterating → **`/submit`** (HTML-enhanced draft PR) + **`/ready`** → **`/address`** classifies in the
> spawned child and `resolve_review_threads` resolves → **`/land`** squash-merges + marks the node done
> → **`/objective-reconcile`** reconciles the Reconcilable prose against the real diff → **`/learn`**
> captures. The objective issue #, plan issue #, PR #, merge commit, and reconciliation diff are
> recorded here and in the turn's outcomes after the run.

## Borrow → own status

Phase 2 largely completes the **borrow-then-own** internalization:

- **Owned now:** plan mode (retired `@tombell/pi-plan`, P2.T2a) + structural tool-gating;
  implement-progress checkpoints (retired `@juicesharp/rpiv-todo`, P2.T12); the CI executor; the
  `/address` review loop; objectives + reconciliation.
- **Still borrowed:** `@tombell/pi-diff` (diff review), the `@tombell/pi-status` statusline, and the
  **`pi-subagents` engine** — kept behind perk's thin seam (perk owns the agent definitions in
  `.pi/agents/`; the engine is the spawn/handoff machinery). Internalizing a minimal spawn primitive
  to replace it is deferred to the internalization schedule (Phase 3+), only if weight/determinism/
  headless costs prove out.
- **Forward-convergence boundary (flagged, not fixed):** `init`'s settings convergence is
  additive-only — it never strips a once-borrowed package. A consumer repo that already wired
  `rpiv-todo` keeps it; `doctor --fix` repairs oddities but does not remove it. This is the
  established boundary (mirrors the P2.T2a `pi-plan` retirement), **not** a regression — no
  package-removal logic was added to `init`.

## Phase 2 deferral boundary (what Phase 2 did *not* ship)

Quoted from [phase-2-plan.md](../phase-2-plan.md) §"Explicitly deferred (Phase 3+)", so the boundary
is a *choice*:

- **The headless worker + queue** — Phase 3. Phase 2's local-vs-remote target seam
  (`doors.cold_remote`, built in T8c) is in place; the process that *drives* the remote target is
  Phase 3.
- **End-to-end *worker* tests** (RPC/JSON mode) — Phase 3 (Phase 2 extends the command/extension test
  layer only).
- **Migration helpers** (import existing planned PRs, translate objective markers, map residual
  `.claude` references) — Phase 3.
- **`doctor workflow` GitHub-CI smoke test** — Phase 3 (needs the worker + queue).
- **Internalizing a minimal spawn primitive** to replace the `pi-subagents` engine — only if
  weight/determinism/headless costs prove out; Phase 2 keeps the engine behind its thin seam.

## Verdict

**Phase 2 gate met** (pending the recorded live run). The deepened loop is built, healthy, and
launchable offline — both new stages (`address`, `objective-plan`) have filled registry I/O + doors
and `perk registry check` passes; `rpiv-todo` is retired in favor of perk-owned checkpoints; the
docs reconcile to "Phase 2 complete." The automatable preconditions are green via the cumulative
`just verify` (including `verify-p2-t12.sh`); the live dogfood run is recorded above once the operator
drives perk's full workflow on itself. **Phase 3 may begin.**

**Verifying commands:** `just verify` (cumulative Phase-0 + Phase-1 + Phase-2 hard gates, ALL PASS) ·
`just ci` (lint + types + tests, both planes) · `perk registry check` (the stage-graph self-check) ·
`bash scripts/verify-p2-t12.sh` (this turn's six offline preconditions).
