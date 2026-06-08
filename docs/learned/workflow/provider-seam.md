---
title: The provider seam — owned-surface deferral vs always-registered substrate
read_when: You are working on the plan/todo provider seam — the provider-selection substrate, deferring perk's own authoring surface under a foreign selection, the cross-plane resolver, wiring a foreign plan/todo adapter, registration-time vacating, the injection-only adapter shim, or `package_filter`.
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

## Runtime deferral vs. registration-time vacating — the two-node split

The central insight of the deferral work: *when* perk steps its owned surface aside depends on
whether a foreign package is actually loaded yet. There are two tiers, delivered by two different
kinds of node.

- A **reference-provider deferral node** (plan seam Node 2.2 / todo seam Node 3.1, the latter on
  `extension/checkpoints.ts`) defers at **runtime only** — per-event handler guards step the owned
  surface aside under a foreign selection. This suffices and is behavior-preserving **because no
  foreign package is loaded yet**: nothing else is competing for `/plan`, `Ctrl+Alt+P`, or the
  `--plan` entry, so a silent early-return inside each handler is enough.
- A **foreign-adapter node** (plan seam Node 2.3 with `@tombell/pi-plan`; the analogous todo seam
  Node 3.2 with `@juicesharp/rpiv-todo`) must **escalate to registration-time vacating**: resolve the
  selection **once at factory time** (`registerPlanMode` reads `resolvedPlanProviderId(process.cwd())`)
  and, under a foreign selection, **register nothing** — no flag, no command, no shortcut, no
  `session_start --plan` entry, no `before_agent_start` injection, no `context` strip. The whole
  registration body is gated once; the per-handler guards then become **redundant and are removed**.

**Why the escalation is forced:** once a foreign package that also registers `/plan` is loaded, Pi
**suffixes duplicate command/flag/shortcut names** (`/plan:1`, `/plan:2`; duplicate `registerFlag` /
`registerShortcut` is undocumented and potentially fatal). Handler-time deferral alone collides
because both surfaces still *register* — the foreign `/plan` and perk's deferring-but-present
`/plan` both exist and Pi disambiguates them with suffixes. Vacating at registration time is the only
way to leave exactly one surface standing.

**Generalize:** any perk surface a foreign package may also own must vacate at *registration* time,
not just defer inside handlers. Fail-safe holds in **both** modes: any config-read error → treat as
the reference id → register everything. The default path (reference provider) is the hard
zero-change guarantee, so the error branch must always fall toward full registration.

A future 3.2 agent should expect to (a) add registration-time vacating to `registerCheckpoints` and
(b) ship an injection-only adapter shim mirroring `planAdapterTombell.ts` — **not** re-litigate why
3.1 "only" did runtime deferral. The runtime tier was correct *for a node with no foreign package
loaded*; the escalation is what the foreign-adapter node adds.

## The reusable mirror shape (proven on both seams)

A reference provider defers by adding two exported helpers — `resolved<Seam>ProviderId(cwd)`
(resolves `[providers].<seam>.id` with a **try/catch fail-safe to the reference id**) and
`isPerk<X>ReferenceSelected(cwd)` — read **fresh per-event** (no static state). Event handlers
(`session_start` / `session_tree` / `turn_end`) early-return **silently**; the user-facing command
(`/plan`, `/checkpoints`) **announces** the deferral headless-safe (`ctx.ui.notify` else
`console.error`). The two instances are `extension/planMode.ts` (plan seam) and
`extension/checkpoints.ts` (todo seam) — the same shape on both, which is why a future seam can copy
it. (This is the concrete reuse of the per-event fail-safe consumption described below, not a
separate mechanism.)

## The adapter shim is injection-only (Invariant 1)

`extension/planAdapterTombell.ts` is **always registered** but inert unless `[providers] plan =
"tombell-plan"`. Its sole effect is to inject a hidden `perk:plan-adapter-tombell` context (mirroring
`planMode` / `objectiveAuthor` hygiene: inject on `before_agent_start`, strip the stale marker on
`context`). It **never** registers a `tool_call` handler, never calls `setActiveTools`, never touches
`toolGating`. The read-only tier it relies on comes from two places it does **not** own: (a) perk's
gate, already engaged by the cold-door launch (`session_start → syncFromState(handoff.mode=read-only)`),
and (b) the foreign package's own self-enforcement for ad-hoc `pi --plan`. The prose→plan-ref bridge
**reuses the existing `/plan-save` `extractPlanMarkdown` scrape** — no new save machinery; the shim
only *directs the flow* into the substrate that already exists. **Anti-pattern:** do **not** compose
`enter` / `exit` inside an adapter — double-`setActiveTools` creates a snapshot-ordering hazard.

## `package_filter` — verify the foreign manifest, don't trust an illustrative filter

The placeholder `package_filter: extensions: ["extensions/*.ts"]` was **fiction**: it matched nothing
for `@tombell/pi-plan`, whose sole extension is the **root `index.ts`**. Applying that filter loads
**zero** extensions and the foreign surface never registers. The correct choice is to **omit
`package_filter`** ("load all of that type") → loads exactly `index.ts`. The field stays in the
vocabulary for future providers that genuinely need to scope a multi-extension package. Lesson:
**verify a foreign package's actual manifest** (`pi.extensions`, skills) before trusting an
illustrative filter from a plan.

## Testing factory-time-cwd deferral — the chdir requirement

`registerPlanMode` reads `process.cwd()` **when the extension factory runs** (at bind). The
`loadPerkSession` harness takes a `cwd` option but **does not chdir the process** — so a scaffolded
temp repo carrying a foreign selection is invisible to factory-time resolution unless the test does
`const saved = process.cwd(); process.chdir(cwd)` *before* `loadPerkSession` and restores it in a
`finally` (see `planMode.test.ts`). By contrast, **runtime-guard deferral keyed off `ctx.cwd`** (the
shim's injection/strip, and `checkpoints.test.ts`) needs **no** chdir — the cwd flows through the
event `ctx`. That asymmetry is *why* runtime-guard deferral is the easier tier to test: pick the
chdir pattern only for factory-time-cwd resolution, and the `ctx.cwd` pattern for everything keyed
off the event.

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

The plan seam now has a **real foreign adapter** (`@tombell/pi-plan`, Node 2.3): selecting it vacates
perk's plan surface at registration time and bridges the foreign prose into the plan-ref substrate.
The **todo seam defers at runtime** (Node 3.1) but its foreign adapter — registration-time vacating
in `registerCheckpoints` + the `@juicesharp/rpiv-todo` injection-only shim — is still **Node 3.2**.
Until 3.2 lands, selecting a *foreign todo* provider still collides (both `/checkpoints` surfaces
register and Pi suffixes them). The default path (both reference providers, `package: null`) is the
hard guarantee and is unaffected in every mode.

## Cross-references

- `extension/planMode.ts` — the owned plan-authoring surface that defers
- `extension/checkpoints.ts` — the todo-seam owned surface (runtime deferral, Node 3.1; the mirror)
- `extension/planAdapterTombell.ts` — the injection-only adapter shim (always registered, inert by default)
- `extension/planSave.ts` — the seam-shared substrate that never defers
- `extension/providers.ts` — `resolveProviders`, `PERK_PLAN_PROVIDER_ID`
- `perk/providers.py` — `resolve_providers`, `ProvidersError`
- `perk/launch.py` — the `provider == "github"` backend branch
- `shared/providers.yaml` — the bundled reference defaults
- `shared/contracts.md` — the `cache.plan-ref` shape (`provider: string  # e.g. "github"`)
- `docs/learned/workflow/shared-contracts.md` — the cross-plane parsed-YAML recipe
- `docs/learned/workflow/init-doctor.md` — managed-convergence SSOT
- `docs/learned/workflow/plan-ref-lifecycle.md` — the `cache.plan-ref` lifecycle
- `docs/learned/toolchain/worktree-node-modules.md` — the stale-global-`perk` / self-converge smoke gotcha
