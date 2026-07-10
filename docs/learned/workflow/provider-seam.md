---
title: The provider seam — artifact seams, the askuser/footer/web interface seams, and the DISPATCH review seam; owned-surface deferral vs always-registered substrate
read_when: You are working on a provider seam (plan/todo/askuser/footer/web/review) — classifying a candidate seam, wiring or widening a provider, vacating a collision, or the cross-plane resolver.
---

# The provider seam

perk lets a repo select which **provider** owns each seam. The substrate is now **six seams** —
`plan`, `todo`, `askuser`, `footer`, `web`, and `review` (`SEAMS` in `perk/substrate/providers.py`
and `PROVIDER_SEAMS` in `extension/substrate/providers.ts` both carry all six) — and they span
three posture categories. The default for each is a behavior-preserving pick (perk's own reference
provider wherever perk owns the surface); selecting a foreign provider makes perk *yield* its owned
surface while keeping any produced-contract landing in place. This doc captures the non-obvious
shape of that substrate and the load-bearing rules a future foreign-adapter node must respect.

The categories across all six: **artifact seams** (`plan`, `todo`) bridge a durable contract
through an `adapter` shim; **interface seams** (`askuser`, `footer`, `web`) have no durable
artifact, so vacating perk's owned surface is the whole job (`adapter: null`, no shim); the
**DISPATCH seam** (`review`) has no adapter *and* nothing to vacate — the selection's job is
protocol dispatch inside a consumer door (see the taxonomy section).

## Artifact seams vs the interface seam (classify first)

`plan`/`todo` are **artifact seams** — their stable contract is a *durable boundary*
(`cache.plan-ref`; `perk:checkpoint` + the `## Steps`/`[DONE:n]` vocabulary) that an `adapter` shim
bridges **to**. `askuser` was the **first interface seam**, and `footer` + `web` joined it: an
interface seam's contract is the foreign **tool/surface itself** — the tool NAME
`ask_user_question` plus its non-terminating-answer semantics (askuser), the single last-wins
`setFooter` slot (footer), or the foreign web tools (web) — with **no durable state key, no
session-entry vocabulary, nothing to bridge**. Consequence: every interface-seam adapter is
**vacate-only** (`adapter: null`, no shim module, no injected context); the foreign surface
self-documents (e.g. askuser's foreign tool via its own `promptGuidelines`).

**Decision rule:** classify a proposed seam **artifact-vs-interface first** — it determines whether
you write an adapter at all. An artifact seam needs a bridge shim (the produced contract must reach
downstream consumers); an interface seam's contract *is* the foreign tool, so vacating is the whole
job. (Per-file mechanics of the askuser instance live in
`docs/design/provider-smoke-juicesharp-ask-user.md`.)

## The substrate is the third cross-plane parsed-YAML contract

`shared/providers.yaml` + `perk/substrate/providers.py` (`resolve_providers`, `ProvidersError`) +
`extension/substrate/providers.ts` (`resolveProviders`, `PERK_PLAN_PROVIDER_ID`) reuse the `bindings.yaml`
recipe **verbatim** with zero packaging changes: shape-only loaders on each plane, `Issue`/`Severity`
reused from `perk.substrate.registry`, and **no standalone CLI** — validation surfaces only through `doctor`.
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

- The field is the issue-backend string `"github"`. `perk/run/launch.py` branches on
  `provider == "github"`; all the Python and TS save surfaces stamp `"github"`; `shared/contracts.md`
  documents the shape as `provider: string  # e.g. "github"`.
- The deferral work deliberately did **not** restamp it with the seam id — that would break
  `launch.py`'s backend branching.

Anyone wiring a foreign plan adapter must not assume `provider-id == cache.plan-ref.provider`. They
are different namespaces today.

## Cross-plane mirror discipline

TS `resolveProviders` is a pure mirror of Python `resolve_providers`: same fallback semantics
(absent key → default silently; unknown id / seam mismatch → default + exactly one issue), verified
against `tests/test_providers.py` and `extension/substrate/providers.test.ts`. The one intentional divergence:
TS returns `issues: string[]` because the TS plane has no `Issue`/`Severity` (those live in
`perk/substrate/registry.py`). **Python stays the authoritative validator.**

## Runtime deferral vs. registration-time vacating — the two-node split

The central insight of the deferral work: *when* perk steps its owned surface aside depends on
whether a foreign package is actually loaded yet. There are two tiers, delivered by two different
kinds of node.

- A **reference-provider deferral node** (plan seam Node 2.2 / todo seam Node 3.1, the latter on
  `extension/checkpoints/checkpoints.ts`) defers at **runtime only** — per-event handler guards step the owned
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

### The collision *kind* picks the mechanism (command vs tool name)

The askuser interface seam confirmed the general decision rule across all three seams: **the kind of
name collision picks registration-time vacating vs runtime deferral.** Tools (unlike commands) are
**not `:N`-suffixed** — a same-named foreign tool replaces/warns by **non-deterministic extension
load order**. The foreign `ask_user_question` tool shares perk's exact tool name, so `askuser` mirrors
the **plan seam's registration-time vacating** (resolve once at factory-time `process.cwd()`,
early-return before `registerTool` under a foreign selection — `registerAskUser` wiring stays a single
unconditional call, gating lives inside, like `registerPlanMode`), **not** the todo seam's runtime
deferral. Generalized:

- **command-name collision ⇒ registration-time vacating** (plan: `/plan`; askuser: the
  `ask_user_question` tool — tools collide the same way commands do);
- **no name collision ⇒ runtime deferral suffices** (todo: `/checkpoints` has no foreign clash).

The fail-safe mirrors the plan seam: any config-read error → reference id → keep perk's own tool.

This forward-note was written plan-first and **partly mis-fired for the todo seam** — see "A sibling
seam's forward-note must be re-derived, not mirrored" below. The escalation to registration-time
vacating is forced **only when the foreign package registers a same-named command**; the plan seam
hit that (`/plan`), the todo seam did **not** (`/checkpoints` has no collision), so Node 3.2 shipped
an injection-only shim mirroring `planAdapterTombell.ts` but added **zero** registration-time
vacating. The general rule still holds — *any perk surface a foreign package may also own must vacate
at registration time* — but re-derive whether a collision actually exists before assuming it does.

### Unconditional install is decided by the same collision axis

Whether a package can be converged into `packages` **unconditionally** (for every repo, not just
under a selection) is decided by the collision kind of what it registers:

- plannotator unconditionally registers a `plan` **flag** + a `Ctrl+Alt+P` **shortcut** (verified
  in the installed package's `index.ts`) — there is no lazy/conditional registration to hide
  behind.
- pi resolves extension-**shortcut** conflicts **last-wins** with only a per-session diagnostic,
  and a **shared flag activates BOTH plan modes** (verified in pi's
  `dist/core/extensions/loader.js` / `runner.js`) — so an unconditional plannotator install
  collides in **every default (`perk-plan`) repo**, not just misconfigured ones.
- The settled posture: plannotator stays **selection-gated** (the desired-union convergence
  untouched); consumer doors that need the extension **fail fast with a helpful message** when it
  is absent. Only the hunk CLI went unconditional — an external binary with **no Pi registration
  surface** has no collision axis at all.

Generalization: external CLIs (no Pi registration) are collision-free; extensions with
unconditional flag/shortcut registration are not. This is the same axis that already picks
registration-time vacating vs runtime deferral above.

### The full taxonomy: three vacating mechanisms + the "nothing to vacate" and DISPATCH postures

The footer + web seams revealed that the decision rule is broader than "does a name collide." The
deeper rule is **where perk's surface is established** — that picks *how* perk vacates. There are
now three distinct vacating mechanisms plus two limit-case postures:

- **Registration-time vacating** (plan, askuser) — the surface is registered at *factory-bind*
  time. It collides **by name**: commands are `:N`-suffixed, tools replace by non-deterministic
  extension load order. perk must resolve the selection **once at factory time** and **register
  nothing** under a foreign selection (the whole registration body is gated; per-handler guards
  become redundant). See `registerPlanMode` / `registerAskUser`.
- **Install-site / runtime vacating, keyed off `ctx.cwd`** (footer — **the new third mechanism**) —
  perk installs its footer with `installPerkFooter` **inside the `session_start` event handler**
  (`extension/index.ts`), not at factory-bind. So the natural guard is a **runtime check at that
  single install site**: `index.ts` calls `installPerkFooter` only when
  `isPerkFooterReferenceSelected(ctx.cwd)`. There is **no name collision** (`setFooter` is a single
  last-wins slot, not a named registration), so the guard isn't about suffixing — it's about not
  clobbering the foreign footer's slot. **Easier test tier:** because `ctx.cwd` flows through the
  event, footer's helper + install-gating tests need **no `process.chdir`** (unlike the factory-time
  `process.cwd()` reads in `registerAskUser` / `registerPlanMode` tests, which must chdir into the
  scaffold before bind). The `ctx.cwd`-keyed tier is the easier one to test — see the chdir-requirement
  section.
- **Runtime deferral** (todo) — the surface is always *registered* but stands down at **handler**
  time (`/checkpoints` has no foreign clash, so registration is harmless; the handlers early-return
  under a foreign selection).
- **"Nothing to vacate at all"** (web — **a fourth posture, not a mechanism**) — perk registers
  **no web tools of its own** (it owns no native web implementation), so under a foreign web
  selection there is literally **no perk surface to vacate**. Selection merely swaps which web
  package the provider-convergence installs. State this explicitly as the limit case beyond the
  three vacating mechanisms: when perk never owned the surface, vacating is a no-op.
- **DISPATCH** (review — **a third posture *category*, beside artifact seams and vacate-only
  interface seams**) — no adapter shim (the seam produces no durable artifact, so there is nothing
  to bridge) *and* nothing to vacate (perk owned no prior guest-review surface — beyond even web's
  "nothing to vacate", where the selection at least swaps which package converges). The selection's
  whole job is **protocol dispatch inside a consumer door**: the forthcoming `/review` reads the
  resolved id to pick which review surface it drives (the `hunk` session-CLI handshake vs the
  plannotator code-review events bridge). See the review entries in `shared/providers.yaml`.

### footer is the SECOND interface seam (vacate-only, `adapter: null`)

Like askuser, footer produces **no durable artifact** → `adapter: null`, no shim module. The
no-bridge claim holds because of a **decoupling**: perk's composed `perk` `setStatus` slot (via
`createPerkStatus` / `extension/checkpoints/checkpoints.ts`) publishes progress **independently of
footer ownership** — the **powerline-class** foreign footers (`pi-powerline-footer`, `pi-bar`)
render extension statuses, so **footer ownership ≠ status publishing**. perk's objective/checkpoints
progress reaches *those* foreign footers automatically; the bridge is automatic, not authored. The
decoupling holds **only for footers that render extension statuses** — `@tombell/pi-status` is the
documented counterexample (it renders none; see the footer-catalog-widening subsection below), so
the "automatic bridge" is a property of the footer, not a guarantee of the seam. The config reader belongs
in **`extension/surfaces/footerProvider.ts`** (it reads config → not the dependency-free
`surfaces.ts`; it makes **no** rich-UI calls → passes `surfacesGuard.test.ts`), mirroring the
`askUser.ts` helper pair.

### web is the THIRD interface seam — the first non-null-`package` default (the durable test trap)

`web`'s `default: true` provider (`pi-web-access`) has a **non-null `package`** — the first seam
default that does, because perk owns no native web impl. This flips two long-standing invariants on
a **fresh** init (note: the committed repo's own `settings.json` stays a plain string — convergence
only *adds* a package when absent — but **fresh-init fixtures get object form** `{"source":
"npm:…"}`):

- `validate()` never required a default to be `package: null`, and the package-convergence /
  managed-identity machinery already builds from every truthy/non-null `package`, so **no substrate
  change was needed** — only the census widening + the read-only allowlist union.
- **The trap:** any test iterating the desired `packages` with `.startswith(…)` / `in packages`
  string-membership **breaks** with `AttributeError: 'dict' object has no attribute 'startswith'`
  on the default path (the legacy-npm-migration + self-mode-local-path tests both hit this).
  **Lesson:** for the next non-null-`package` default (or any change converging an object-form entry
  on the default path), **grep every test that does string-membership over `packages`** and guard
  with `isinstance(p, str)` or route through the identity helper.

Contrast: the review seam's default (`hunk`) is the first seam default whose substrate is an
**external CLI** — installed via `npm i -g hunkdiff` (see `shared/providers.yaml`), not a Pi
package — so it keeps `package: null` and the string-membership fixture trap does **not** fire on
that default path (nothing object-form converges). Non-null-`package` defaults and external-CLI
defaults are independent axes; only the former trips the trap.

### review shares its package across two seams — the desired-union guarantee (zero convergence change)

`npm:@plannotator/pi-extension` is the **first package shared across two seams**: it serves both
`plannotator-plan` (plan seam) and `plannotator-review` (review seam). The desired-**union** loop in
`_converge_provider_packages` builds a dict keyed by package spec — two selections of the same spec
collapse to one desired entry — so **deselecting one seam never strips the other seam's package**.
The widening needed **zero convergence-code change**: only the catalog entry + tests
(`tests/test_init_idempotent.py::test_init_shared_package_survives_cross_seam_deselect`).

### Widening the footer catalog — `pi-status-footer` + `pi-default` (the cleanest seam-widening shape yet)

Adding two footer providers (`pi-status-footer` = `@tombell/pi-status`; `pi-default` = leave pi's
stock footer) closed the catalog gap that had forced a downstream repo to hand-edit
`.pi/settings.json` `packages`. The footer is now governed **exclusively** by `[providers] footer`.
What the widening confirms about the substrate:

- **A new footer provider is PURELY declarative** — one catalog row in `shared/providers.yaml` + one
  TS id constant in `extension/substrate/providers.ts` + tests + docs. **Zero runtime/convergence
  code change.** The Python `_converge_provider_packages` is fully generic, and the TS
  `resolveProviders` / `byId` / `defaultFor` are generic, so there is **no census beyond the
  test/doc surfaces**. This is the cleanest seam-widening shape yet.
- **The footer install gate vacates for free.** `isPerkFooterReferenceSelected(cwd)`
  (`extension/surfaces/footerProvider.ts`) is true ONLY when the resolved id === `perk-footer`, so
  *every* non-default footer selection — **including the null-package `pi-default`** — makes perk
  skip `installPerkFooter` with no per-provider gate logic.
- **`pi-default` is the first `package: null` NON-default provider** ("install nothing / leave pi's
  stock footer"), distinct from the seam DEFAULT reference (`perk-footer`, also null-package). A
  null-package *non-default* means convergence adds nothing AND perk vacates its own install —
  confirming **`package: null` is orthogonal to `default: true`**.
- **A catalogued foreign package becomes a MANAGED IDENTITY.** `perk init` now two-directionally
  *removes* a hand-added `@tombell/pi-status` `packages` entry from any repo that does **not** select
  it via `[providers] footer` (the "revert the manual edit" guarantee, D5), pinned by the 4-case
  idempotency test in `tests/test_init_idempotent.py` (add object-form / `pi-default` adds nothing /
  deselect removes / hand-added-unselected removed).
- **`pi-status` is an interface seam with an ACCEPTED LIMITATION.** Unlike `pi-powerline-footer` /
  `pi-bar`, `@tombell/pi-status` does **not** render extension statuses, so perk's
  objective/checkpoints progress is invisible under it — accepted, documented, **no status-bridge
  adapter built**. It is the **first foreign footer that breaks** the "both foreign footers render
  extension statuses → bridge automatic" assumption baked into the seam (reconciled in the
  footer-is-the-SECOND-interface-seam subsection above). The durable process lesson: **when you add
  a counterexample, reconcile the whole adjacent region, don't just append** — a new catalog row
  next to a pre-existing seam comment leaves the old comment stale.

### Contract reconciliation: the borrow-ban vs a selected footer provider

The `BORROWED_PACKAGES` footer-clobber rule ("a *borrowed* package must never own the footer —
`setFooter` is last-wins") is **reconciled, not contradicted** here: a *selected* footer provider
legitimately owns the footer because the seam is the **sanctioned hand-off** and perk deliberately
vacates `installPerkFooter`. A borrow is an unsanctioned co-tenant; a selected provider is the
intended owner. See `docs/learned/workflow/borrowed-packages.md`.

### Process notes (footer/web): `package_filter` omitted, read-only allowlist, retired `docs/planning/`

- **`package_filter` omitted for single-root extensions.** `npm view <pkg> pi` confirmed all the
  foreign footer/web packages are single-root `./index.ts` extensions, so `package_filter` is
  **omitted** ("load all of that type" — the tombell/juicesharp precedent). The field stays in the
  vocabulary for genuinely multi-extension packages.
- **`SDK_READ_ONLY_TOOLS` stays strict.** The web seam unions the known web tool names into
  `READ_ONLY_TOOLS` (so a foreign web tool is allowlisted by shared name), but
  `SDK_READ_ONLY_TOOLS` (`extension/worker/readOnlySession.ts`) is **deliberately unchanged** —
  headless children never run foreign web tools.
- **`docs/planning/` was retired → `docs/design/`.** Any plan still referencing `docs/planning/`
  should redirect to `docs/design/` (provider census docs now live as
  `docs/design/provider-smoke-*.md`).

## The reusable mirror shape (proven on both seams)

A reference provider defers by adding two exported helpers — `resolved<Seam>ProviderId(cwd)`
(resolves `[providers].<seam>.id` with a **try/catch fail-safe to the reference id**) and
`isPerk<X>ReferenceSelected(cwd)` — read **fresh per-event** (no static state). Event handlers
(`session_start` / `session_tree` / `turn_end`) early-return **silently**; the user-facing command
(`/plan`, `/checkpoints`) **announces** the deferral headless-safe (`ctx.ui.notify` else
`console.error`). The two instances are `extension/factories/planMode.ts` (plan seam) and
`extension/checkpoints/checkpoints.ts` (todo seam) — the same shape on both, which is why a future seam can copy
it. (This is the concrete reuse of the per-event fail-safe consumption described below, not a
separate mechanism.)

## The adapter shim is injection-only (Invariant 1)

`extension/adapters/planAdapterTombell.ts` is **always registered** but inert unless `[providers] plan =
"tombell-plan"`. Its sole effect is to inject a hidden `perk:plan-adapter-tombell` context (mirroring
`planMode` / `objectiveAuthor` hygiene: inject on `before_agent_start`, strip the stale marker on
`context`). It **never** registers a `tool_call` handler, never calls `setActiveTools`, never touches
`toolGating`. The read-only tier it relies on comes from two places it does **not** own: (a) perk's
gate, already engaged by the cold-door launch (`session_start → syncFromState(handoff.mode=read-only)`),
and (b) the foreign package's own self-enforcement for ad-hoc `pi --plan`. The prose→plan-ref bridge
**reuses the existing `/plan-save` `extractPlanMarkdown` scrape** — no new save machinery; the shim
only *directs the flow* into the substrate that already exists. **Anti-pattern:** do **not** compose
`enter` / `exit` inside an adapter — double-`setActiveTools` creates a snapshot-ordering hazard.

## The tombell review-first re-aim — generalizable adapter patterns

Re-aiming the tombell adapter's injected prompt from harmless prose to action-directing prose
(review-first: `plan_review` approval saves an issue + exits the gate) surfaced four patterns any
foreign-adapter work should reuse:

- **Foreign-package persisted state as a gating signal (the state-twin read).** An adapter can
  condition behavior on a foreign extension's persisted session state by scanning the branch for
  its custom entries — `isTombellPlanModeEnabled` (`extension/adapters/planAdapterTombell.ts`) reads
  `@tombell/pi-plan`'s `plan-mode-state` entries: latest-wins (a later `enabled: false` defeats an
  earlier `true`, mirroring tombell's own `session_start` rebuild), defensive false on
  missing/malformed. This extends the gate's state-twin doctrine (read the persisted
  `perk:workflow-state.mode`, never the gate object) to foreign packages. Risk: the entry shape is
  pinned by convention only — if tombell renames it, the adapter degrades to silently-not-injecting
  (fail-open, invisible; the harness `planMode` fixture would mask the drift).
- **OR-shaped injection condition when an adapter serves two entry paths.** The injection fires
  when (perk gate read-only) OR (tombell's own plan mode enabled), objective-author excepted — the
  OR-arm serves ad-hoc interactive `pi` + tombell `/plan` with the perk gate off. When re-aiming an
  adapter from harmless prose to action-directing prose, an unconditional-on-selection injection
  becomes unsafe and must gain the gate condition.
- **Injected prompts need a tools-may-be-hidden branch under foreign tool restrictions.**
  tombell's `enable()` calls `setActiveTools` with a read-only set that excludes
  `plan_draft`/`plan_review`, and an injection-only adapter can't fix that (Invariant 1: it never
  touches gating/`setActiveTools`). So the prompt itself must carry an explicit "tools not in your
  tool set → present the complete plan; the human runs /plan-save" arm — or the model wedges
  trying to call invisible tools. Generalizable to any injected discipline that directs tool calls
  under a foreign surface that restricts tools.
- **Offline test recipe for the ad-hoc arm.** `plantSession(..., { planMode: true })` plants
  exactly tombell's `plan-mode-state` entry shape; combined with `SessionManager.open` +
  `loadPerkSession` it exercises "perk gate off, foreign mode on" fully offline.

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

The Node 3.1 status note (`shared/contracts.md`) + `extension/checkpoints/checkpoints.ts` both forward-assumed
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
changes to `perk/convergence/init.py` / `perk/substrate/providers.py` / `perk/substrate/config.py` / the TS resolver / the
`providers.yaml` entry's structural fields. The todo shim copied `planAdapterTombell.ts`'s shape
verbatim (always-registered + inert; a `before_agent_start` injector + a `context` stale-marker
strip — the strip's customType filter + user-role string/array marker removal is verbatim) plus one
extra gate unique to todo: **active-workflow scoping** (`rebuildWorkflowState(branch).active_plan_ref
!= null`, the same gate the reference checkpoints provider seeds on) so the bridge never reaches
planning/objective sessions. Invariant 1 held: never `setActiveTools`, never owns the read-only gate,
never restamps a provider field.

## The augment-posture provider (plannotator-plan)

The third real provider, `plannotator-plan`, introduced a posture the catalog had not needed:
**augment** — perk's plan surface stays live and the provider adds a human review step
(`plan_review`, bridged to the plannotator browser UI). Mechanics worth keeping:

- `registerPlanMode` now has a **three-tier branch**: full (perk's own provider), **partial-vacate**
  (augment — perk keeps the surface, drops only the pieces the provider replaces), and full-vacate
  (a replace-posture foreign provider). Augment-vs-replace posture is **per-provider judgment keyed
  on the id constant inside `registerPlanMode`**, not new catalog vocabulary — generalize the
  posture into `providers.yaml` only when a third augment-style provider appears.
- **An always-registered shim can key behavior off the gate without holding the controller** by
  reading the persisted workflow-state mode (`rebuildWorkflowState(branchOf(ctx)).mode ===
  "read-only"`) — the gate's state twin. The gating argument never reaches adapter wiring
  (Invariant 1), so the persisted mode is the sanctioned read.
- **The present-for-review save-discipline split:** interactive plan surfaces *present* the plan for
  review and leave the save to the human `/plan-save`; factory flows (objective-plan, learn-docs,
  replan) keep the autonomous `plan_save` tool call. The two disciplines coexist deliberately.

Residuals: the plannotator event envelope is pinned at the installed version and degrades to a
fail-open skip on upstream change (silently losing the review step); there is **no decision
timeout by design** (interactive-only path — headless soft-skips; an unanswered review hangs until
turn abort); upstream npm install breakage is possible and perk's wiring is correct independent of
it.

## The 2→N widening census (both planes, byte-mirrored)

The substrate is seam-generic in structure but hardcodes the seam tuple in several spots. The
census is a **checklist to enumerate, not a pattern to re-derive**: adding a seam touches ~12
lockstep surfaces across both planes, and the site list below has held verbatim on every widening
so far (`askuser`, `footer`, `web`, and — the latest confirmation — `review`), so the next author
has the checklist:

- the `SEAMS` / `PROVIDER_SEAMS` tuples;
- the `ResolvedProviders` field + `resolve_providers` / `resolveProviders` return + the inner
  `resolveSeam` signature union (now `"plan"|"todo"|"askuser"|"footer"|"web"|"review"`);
- the new id constants in `extension/substrate/providers.ts` (e.g. `PERK_FOOTER_PROVIDER_ID`,
  `PI_WEB_ACCESS_PROVIDER_ID`, and each foreign provider id);
- the config readers (`_parse_providers_selection` / `parseProvidersSelection`) + the `providers`
  field type;
- `init`'s `_converge_provider_packages` provider loop;
- `doctor`'s `_providers_check` ok-summary string.

**Two test-fixture census items both new seams confirmed:**

- The **`GOOD` / base fixture in `tests/test_providers.py` must gain a default entry for each new
  seam** — otherwise every *negative* `validate()` test breaks with "seam `X` must have exactly one
  default" (the validator counts defaults across the whole supported set).
- (web-specific) the **`.startswith(…)` / `in packages` string-membership fixture sweep** above —
  any test iterating the desired `packages` must `isinstance(p, str)`-guard once a non-null-`package`
  default converges an object-form entry on the default path.

Sites that need **no** change because they already iterate `SEAMS` / the whole supported set:
`validate` (exactly-one-default), `_managed_identities`, `by_id` / `default_for`. State such "no
change needed" conclusions explicitly so a future reader doesn't re-derive them. (Watch ruff E501: a
widened tuple inside a docstring can push the summary line past 100 cols.)

## Read-only gating: a shared tool name is free allowlisting

`ask_user_question` is already in `READ_ONLY_TOOLS` (`extension/substrate/toolGating.ts`), so the
foreign tool sharing the **exact** name is allowlisted automatically (same "foreign tool names
inert/allowlisted by shared name" precedent as `plan_review` / `linear_*`). The read-only notice
interpolates `READ_ONLY_TOOLS`, so it self-updates. `SDK_READ_ONLY_TOOLS`
(`extension/worker/readOnlySession.ts`) deliberately **omits** it (headless children never prompt a
human). No code change — state the conclusion explicitly.

## Testing a vacate-only seam without a `registeredTools()` accessor

The harness exposes `registeredCommands()` but **not** `registeredTools()`. Since `registerAskUser`
only calls `pi.registerTool`, the clean test is a minimal recording fake `pi`
(`{ registerTool(t){ names.push(t.name) } }`) driven with the chdir-before-bind pattern from
`planMode.test.ts`: write `.pi/perk.toml`, save + `process.chdir(cwd)`, assert `[]` (foreign selected)
vs `["ask_user_question"]` (reference), restore cwd in `finally`.

## Residual / interim limitation

Both artifact seams now have **real foreign adapters**: the plan seam (`@tombell/pi-plan`, Node 2.3)
vacates perk's plan surface at registration time and bridges the foreign prose into the plan-ref
substrate; the todo seam (`@juicesharp/rpiv-todo`, Node 3.2, `extension/adapters/todoAdapterJuicesharp.ts`)
carries perk's progress discipline onto the foreign overlay via an injected context (no
`perk:checkpoint` population, no registration-time vacating — there is no `/checkpoints`
command-name collision). The three **interface** seams are all **vacate-only** (no adapter, no
bridge): askuser (`@juicesharp/rpiv-ask-user-question`) early-returns before registering its
`ask_user_question` tool; footer (`pi-powerline-footer` / `pi-bar` / `pi-status-footer` /
`pi-default`) skips `installPerkFooter` at the `session_start` install site (the config reader is
`extension/surfaces/footerProvider.ts`); and web
(`pi-web-access` default — itself foreign — / `@ollama/pi-web-search` / `@juicesharp/rpiv-web-tools`)
has **nothing to vacate** because perk registers no web tools. The **review** seam (`hunk` default /
`plannotator-review`) is the DISPATCH posture: no adapter, nothing to vacate, and its consumer door
(`/review`) is forthcoming — until it lands, the selection's only effect is package convergence;
the best-effort hunk-CLI install/verify gesture runs unconditionally, decoupled from the
selection (see `docs/learned/workflow/init-external-cli.md`). The default path remains the hard zero-change
guarantee in every mode — with the one novelty that the **web default's `package` is non-null**
(perk owns no native web impl), the first seam default that is not `package: null`.

## Cross-references

- `extension/factories/planMode.ts` — the owned plan-authoring surface that defers
- `extension/checkpoints/checkpoints.ts` — the todo-seam owned surface (runtime deferral, Node 3.1; the mirror)
- `extension/adapters/planAdapterTombell.ts` — the injection-only plan adapter shim (always registered, inert by default)
- `extension/adapters/todoAdapterJuicesharp.ts` — the injection-only todo adapter shim (Node 3.2; carries discipline by prompting)
- `extension/factories/planSave.ts` — the seam-shared substrate that never defers
- `extension/doors/askUser.ts` — `registerAskUser`, `resolvedAskUserProviderId` (the vacate-only askuser interface seam)
- `extension/surfaces/footerProvider.ts` — `isPerkFooterReferenceSelected` (the install-site/runtime footer vacating, keyed off `ctx.cwd`)
- `extension/index.ts` — the `session_start` install site that gates `installPerkFooter` on `isPerkFooterReferenceSelected(ctx.cwd)`
- `docs/learned/workflow/borrowed-packages.md` — the borrow-ban footer-clobber rule reconciled vs a selected footer provider
- `docs/design/provider-smoke-juicesharp-ask-user.md` — the askuser per-file mechanics + recorded select/deselect smoke
- `extension/substrate/providers.ts` — `resolveProviders`, `PERK_PLAN_PROVIDER_ID`, `PERK_ASK_USER_PROVIDER_ID`
- `perk/substrate/providers.py` — `resolve_providers`, `ProvidersError`
- `perk/run/launch.py` — the `provider == "github"` backend branch
- `shared/providers.yaml` — the bundled reference defaults
- `shared/contracts.md` — the `cache.plan-ref` shape (`provider: string  # e.g. "github"`)
- `docs/learned/workflow/shared-contracts.md` — the cross-plane parsed-YAML recipe
- `docs/learned/workflow/init-doctor.md` — managed-convergence SSOT
- `docs/learned/workflow/plan-ref-lifecycle.md` — the `cache.plan-ref` lifecycle
- `docs/learned/toolchain/worktree-node-modules.md` — the stale-global-`perk` / self-converge smoke gotcha
