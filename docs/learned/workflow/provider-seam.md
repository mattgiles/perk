---
title: The provider seam — owned-surface deferral vs always-registered substrate
read_when: You are working on the plan/todo provider seam — the provider-selection substrate, deferring perk's own authoring surface under a foreign selection, the cross-plane resolver, or wiring a foreign plan/todo adapter.
---

# The provider seam

perk lets a repo select which **provider** owns the plan seam and the todo seam. The default is
perk's own pair of reference providers (`perk-plan` + `perk-checkpoints`); selecting a foreign
provider makes perk *yield* its owned authoring surface while keeping the produced-contract landing
in place. This doc captures the non-obvious shape of that substrate and the load-bearing rules a
future foreign-adapter node must respect.

## The substrate is the third cross-plane parsed-YAML contract

`shared/providers.yaml` + `perk/providers.py` (`resolve_providers`, `ProvidersError`) +
`extension/providers.ts` (`resolveProviders`, `PERK_PLAN_PROVIDER_ID`) reuse the `bindings.yaml`
recipe **verbatim** with zero packaging changes: shape-only loaders on each plane, `Issue`/`Severity`
reused from `perk.registry`, and **no standalone CLI** — validation surfaces only through `doctor`.
See `docs/learned/workflow/shared-contracts.md` for the six-seam recipe; it is not re-explained here.

The bundled file ships both `perk-plan` and `perk-checkpoints` reference defaults and reads
`[providers] plan` + `[providers] todo`. `Config.providers` exposes the **raw** selection exactly
like `Config.user_bindings` — resolution/validation happens downstream, not at config load.

## The load-bearing distinction: owned surface defers, seam-shared substrate never does

When a foreign provider is selected, only the **owned authoring surface** steps aside; the
**produced-contract landing** stays always-registered. For the plan seam:

- **`planMode.ts` defers** — the `/plan` toggle, `Ctrl+Alt+P`, the `--plan` entry, and the
  `perk:plan-context` injection all guard on the selection.
- **`planSave.ts` never defers** — `savePlan`, the `plan_save` tool, `/plan-save`, and the read-only
  tool-gate are seam-shared substrate (see the SEAM-SHARED SUBSTRATE doc-comment at the top of
  `planSave.ts`).

The substrate is what a foreign adapter bridges **to**: a foreign plan surface produces a
decision-complete plan and hands it to `plan_save` → `cache.plan-ref`. Deferring the substrate would
break that bridge. The generalization for the todo seam: a future deferral must apply the same split
— defer the owned checkpoint authoring surface, keep the marker / `perk:checkpoint` substrate.

## Correction — `cache.plan-ref.provider` is the issue backend, NOT the seam id

`docs/design/provider-contract.md` frames `cache.plan-ref.provider` as "== the plan provider id".
That is **aspirational / false today**. The reality:

- The field is the issue-backend string `"github"`. `perk/launch.py` branches on
  `provider == "github"`; all the Python and TS save surfaces stamp `"github"`; `shared/contracts.md`
  documents the shape as `provider: string  # e.g. "github"`.
- The deferral work deliberately did **not** restamp it with the seam id — that would break
  `launch.py`'s backend branching.

Anyone wiring a foreign plan adapter must not assume `provider-id == cache.plan-ref.provider`. They
are different namespaces today.

## Cross-plane mirror discipline

TS `resolveProviders` is a pure mirror of Python `resolve_providers`: same fallback semantics
(absent key → default silently; unknown id / seam mismatch → default + exactly one issue), verified
against `tests/test_providers.py` and `extension/providers.test.ts`. The one intentional divergence:
TS returns `issues: string[]` because the TS plane has no `Issue`/`Severity` (those live in
`perk/registry.py`). **Python stays the authoritative validator.**

## Runtime config consumption is per-event and fail-safe

The deferral guards read config **per-event from `ctx.cwd`** (`resolvedPlanProviderId(cwd)` /
`isPerkPlanReferenceSelected(cwd)` in `planMode.ts`), with no static state — mirroring how
`planContextContent(ctx.cwd)` is read in `before_agent_start`. The whole resolve is wrapped in
try/catch returning `PERK_PLAN_PROVIDER_ID`, so a corrupt bundled provider set can **never** disable
perk's own plan mode. The injection guard stacks this as a *second* defer condition alongside the
pre-existing objective-author-stage check.

## Doctor wiring reused the managed-convergence SSOT

The add+remove provider-package wiring was folded **into the existing `settings-wiring`
`ManagedConvergence`** rather than minting a parallel check, so drift detection / `--fix` came for
free. The dedicated providers check only owns what convergence cannot repair: an invalid bundled
file, or a selection naming a non-existent / wrong-seam provider. See
`docs/learned/workflow/init-doctor.md` for the managed-convergence SSOT recipe (not duplicated here).

## The substrate landed seam-generic, not "plan seam first"

Even though the node was framed plan-first, a shared substrate node delivers all seams' plumbing at
once — the todo selection plumbing landed *with* the substrate. Lesson for sequenced objectives:
reconcile downstream per-seam node descriptions when the substrate node over-delivers.

## Residual / interim limitation

Selecting a foreign provider makes perk *yield* but is **not behavior-complete** until the foreign
adapter node lands — nothing yet replaces the authoring surface, and the todo seam still collides
until its own deferral node. The default path (both reference providers, `package: null`) is the
hard guarantee and is unaffected.

## Cross-references

- `extension/planMode.ts` — the owned plan-authoring surface that defers
- `extension/planSave.ts` — the seam-shared substrate that never defers
- `extension/providers.ts` — `resolveProviders`, `PERK_PLAN_PROVIDER_ID`
- `perk/providers.py` — `resolve_providers`, `ProvidersError`
- `perk/launch.py` — the `provider == "github"` backend branch
- `shared/providers.yaml` — the bundled reference defaults
- `shared/contracts.md` — the `cache.plan-ref` shape (`provider: string  # e.g. "github"`)
- `docs/learned/workflow/shared-contracts.md` — the cross-plane parsed-YAML recipe
- `docs/learned/workflow/init-doctor.md` — managed-convergence SSOT
- `docs/learned/workflow/plan-ref-lifecycle.md` — the `cache.plan-ref` lifecycle
