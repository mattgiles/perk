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

This forward-note was written plan-first and **partly mis-fired for the todo seam** — see "A sibling
seam's forward-note must be re-derived, not mirrored" below. The escalation to registration-time
vacating is forced **only when the foreign package registers a same-named command**; the plan seam
hit that (`/plan`), the todo seam did **not** (`/checkpoints` has no collision), so Node 3.2 shipped
an injection-only shim mirroring `planAdapterTombell.ts` but added **zero** registration-time
vacating. The general rule still holds — *any perk surface a foreign package may also own must vacate
at registration time* — but re-derive whether a collision actually exists before assuming it does.

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

## A sibling seam's forward-note must be re-derived, not mirrored

The Node 3.1 status note (`shared/contracts.md`) + `extension/checkpoints.ts` both forward-assumed
the todo adapter would add registration-time vacating "mirroring `registerPlanMode`." That was
**wrong for the todo seam.** The plan seam needed registration-time vacating *only* because perk and
`@tombell/pi-plan` both register the identically-named `/plan` command — Pi suffixes duplicate names
(`/plan:1`, `/plan:2`), so handler-time deferral alone is ambiguous once the foreign package loads.
The todo seam has **no command-name collision**: perk registers `/checkpoints`; the foreign overlay
(`@juicesharp/rpiv-todo`) registers its own differently-named command(s). With no clash there is no
suffixing, so Node 3.1's *runtime* deferral is already sufficient and the adapter adds **zero**
registration-time vacating.

**Lesson:** when a prior node leaves a "the concrete adapter handles X" assumption for a parallel
seam, **re-derive X from the new seam's actual mechanics** (here: is there a command-name collision?)
rather than copying the sibling's structure.

## The produced-contract tier sets the bridge weight

The two seams' produced contracts live in different tiers (`docs/design/provider-contract.md`
Generalization 1), and that tier decides how heavy the bridge is:

- **plan → `cache.plan-ref`** is a **durable cross-plane** artifact downstream stages
  (implement/submit/…) read, so a foreign plan **must** be bridged into it or it never reaches them.
  The plan adapter directs the foreign prose surface into perk's existing
  `plan_save` / `extractPlanMarkdown` → `cache.plan-ref`.
- **todo → `perk:checkpoint`** is a **transient TS-only** session entry that **nothing downstream
  consumes** (purely the in-session progress overlay), and under a foreign todo selection perk's
  render + marker-scanner already defer (Node 3.1). So the todo adapter deliberately does **NOT**
  write `perk:checkpoint` and does **NOT** revive the scanner — that would be dead duplication.
  Instead it carries perk's progress **discipline** (seed the foreign overlay from the plan body's
  `## Steps`, mark each item complete in order) onto the foreign surface via an injected
  `display:false` context — **prompting, not artifact population.**

**Lesson:** before building an adapter, check whether the produced contract has a real **downstream
consumer**. No consumer ⇒ the bridge is *lighter* — carry the discipline by prompting rather than
populating the entry.

## The substrate landed seam-generic, not "plan seam first"

Even though the node was framed plan-first, a shared substrate node delivers all seams' plumbing at
once — the todo selection plumbing landed *with* the substrate. Lesson for sequenced objectives:
reconcile downstream per-seam node descriptions when the substrate node over-delivers.

Because the substrate was built seam-generic, **"enable the first real foreign provider for seam N"
reduced to a shim + comment reframe**: the injection-only shim + its `index.ts` wiring + flipping
ILLUSTRATIVE→REAL comments across `providers.yaml` / `contracts.md` + provider/init tests asserting
the already-generic behavior. The todo adapter (Node 3.2, `@juicesharp/rpiv-todo`) needed **no**
changes to `perk/init.py` / `perk/providers.py` / `perk/config.py` / the TS resolver / the
`providers.yaml` entry's structural fields. The todo shim copied `planAdapterTombell.ts`'s shape
verbatim (always-registered + inert; a `before_agent_start` injector + a `context` stale-marker
strip — the strip's customType filter + user-role string/array marker removal is verbatim) plus one
extra gate unique to todo: **active-workflow scoping** (`rebuildWorkflowState(branch).active_plan_ref
!= null`, the same gate the reference checkpoints provider seeds on) so the bridge never reaches
planning/objective sessions. Invariant 1 held: never `setActiveTools`, never owns the read-only gate,
never restamps a provider field.

## Residual / interim limitation

Both seams now have **real foreign adapters**: the plan seam (`@tombell/pi-plan`, Node 2.3) vacates
perk's plan surface at registration time and bridges the foreign prose into the plan-ref substrate;
the todo seam (`@juicesharp/rpiv-todo`, Node 3.2, `extension/todoAdapterJuicesharp.ts`) carries
perk's progress discipline onto the foreign overlay via an injected context (no `perk:checkpoint`
population, no registration-time vacating — there is no `/checkpoints` command-name collision). The
default path (both reference providers, `package: null`) remains the hard zero-change guarantee in
every mode.

## Cross-references

- `extension/planMode.ts` — the owned plan-authoring surface that defers
- `extension/checkpoints.ts` — the todo-seam owned surface (runtime deferral, Node 3.1; the mirror)
- `extension/planAdapterTombell.ts` — the injection-only plan adapter shim (always registered, inert by default)
- `extension/todoAdapterJuicesharp.ts` — the injection-only todo adapter shim (Node 3.2; carries discipline by prompting)
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
