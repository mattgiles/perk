# Migration and verification

## Purpose

This document sequences the move from the current `extension/` topology to
the contracts in `memo.md` and `module-contracts.md`.

The order is intentionally vertical. Each phase migrates behavior behind a
typed seam, binds it back to Pi, proves parity, and deletes the superseded
path. A phase is not complete because new directories exist.

## Migration laws

These laws apply to every phase.

### Preserve behavior before improving it

Capture the current behavior in focused tests before changing ownership.
Behavior includes registration metadata, lifecycle ordering, prompt guidance,
availability, progress, headless output, persistence verification, and failure
semantics—not only the final successful value.

Do not mix decomposition with product redesign unless a current behavior is
unsafe or cannot be preserved. Such a change needs its own explicit contract
and documentation updates.

### Move complete vertical slices

A migrated slice contains:

1. a typed feature operation;
2. the stable mechanisms it uses;
3. explicit Pi input and lifecycle adapters;
4. progress and result translation;
5. direct feature tests and adapter tests; and
6. deletion of the old registration and policy path.

Moving helpers without moving their caller is not a slice.

### Introduce no universal scaffolding

Do not create a temporary application kernel, capability protocol, global
registry, contribution catalog, dependency bag, or generic result wrapper. These
structures are difficult to remove once several migrations depend on them.

Use ordinary construction and explicit imports. Extract a shared interface only
after two real implementations or consumers prove the same semantics.

### Keep one live behavior per host

Compatibility wrappers may exist inside an active phase, but only to bridge
that phase's tests. They are deleted before its dogfood gate. Do not keep old
and new registration paths selected by a long-lived flag.

The v1 bridge and application-host adapters may coexist in the npm package
because different Pi hosts load them. They must never bind the same behavior in
one host session.

### Delete continuously

Every phase names the old imports, registrations, helpers, or state it makes
obsolete. Deletion is part of the phase, not deferred to a final cleanup
project.

### Preserve package shape

The extension remains one npm package with `extension/index.ts` as the Pi
extension-v1 entrypoint and `extension/workerMain.ts` as the current worker
entrypoint. A future manifest entry is added only when Pi defines that package
contract. No workspace, code generation, or build-system migration is part of
this plan.

### Amend durable contracts when behavior changes

This proposal changes ownership, not cross-plane or user-facing behavior. If
implementation reveals a required behavior change:

- amend `shared/contracts.md` for cross-plane behavior;
- update the matching `docs/user-docs/` page for user-facing behavior;
- update the `perk-expert` reference for config, provider, or backend
  behavior; and
- record a durable design note only when the decision warrants one.

## Baseline before the first migration

Refresh the evidence in `current-system-map.md` against the implementation
commit. Record at least:

- production file and line counts;
- local graph edges and cycles;
- Pi importers;
- tool, command, flag, shortcut, and hook registrations;
- direct rich-UI and TUI guard results;
- npm package contents and entrypoints.

Freeze a binding inventory for every current registration:

| Binding fact | Why it must be captured |
| --- | --- |
| Host form and name | Prevents accidental rename or omission |
| Input schema or command parsing | Preserves the trust boundary |
| Prose units and Prompt assembly placement | Preserves model-visible behavior |
| Availability and execution mode | Preserves workflow gating |
| Progress behavior | Prevents final-result-only regressions |
| Final result and headless behavior | Preserves user and automation output |
| Hooks and lifecycle ordering | Preserves session correctness |
| Borrowed-tool access | Preserves read-only enforcement beyond Perk tools |
| Prompt-evidence audience, Session shape, and provenance | Prevents stale or quoted context from counting as live |

This is a verification inventory, not a target contribution catalog.

Run the existing focused TypeScript tests and source guards. Store no generated
baseline in production unless it becomes a maintained test input.

> **Status (Objective #2083):** the upstream maturity ledger is deferred to the
> follow-up application-host cutover objective — do not freeze it in this
> objective.

Freeze an upstream maturity ledger beside the implementation baseline. Record
the Pi commit, maturity label, public reachability, upstream CI state, and
supported-host status for values/lists, format-4 context, durable drive, usage,
lanes, services/facets, and views. The detailed evidence remains in
[`upcoming-pi-changes-memo.md`](../upcoming-pi-changes-memo.md); this plan keeps
only the decision inputs.

## Future-adapter gates

The following lane runs beside the numbered decomposition phases. It never
blocks work that uses the current adapters, but no future adapter enters the
production path without its own gate.

| Candidate | Required TypeScript proof |
| --- | --- |
| Format-4 context | Stable supported projection; v1 and `retainedTail` fixtures agree on live Prose units, order, and provenance |
| Values/lists | Supported application access and fork policy; one low-risk current-only field passes dual-read, reload, fork, and audit-behavior comparison |
| Durable drive | Public drive enabled, recovery paths complete, upstream CI green, crash/reopen proof at provider and tool effects, unsafe effects not replayed |
| Usage ledger | Stable complete query/events; totals agree through retries, deferred work, compaction, recovery, and late events |
| Pi lanes | Normative concurrent drive and isolation; two inspect-only assignments and one tool-using assignment preserve model, tool, context, worktree, cancellation, and result isolation |
| Services/facets | Normative manifest, lifecycle, reload-generation, service, state, event, cancellation, and package-entry contracts |
| Views/slots | Normative snapshot/update contract; interactive, headless, and late-attached client parity |

Admission is adapter-first: add the candidate behind an existing Perk
interface, run current and candidate implementations through equivalent tests,
dogfood the relevant Session shapes, switch the host, then delete the old
adapter only when support policy permits. Multiple format readers selected by
detected host format are compatibility adapters, not duplicate workflow paths.

This lane is TypeScript-only. It does not plan changes to the Python session
audit parser or any other cross-plane format reader.

## Phase 1: establish dependency rules and configuration ownership

### Objective

Make the desired import direction enforceable and break the current
`config.ts ↔ bindings.ts` cycle without inventing feature APIs prematurely.

### Changes

> **Status (Objective #2083, Node 1.2):** the "move configuration parsing …
> under `config/`" change is deferred by the objective roadmap until a feature
> slice needs narrow views — this node breaks the cycle in place (`bindings.ts`
> no longer imports config vocabulary) and lands the guards below via an
> activation ratchet; the registration-confinement guard activates when `pi/`
> appears.

- Add source guards for the target rules as target directories appear:
  - features cannot import Pi runtime or TUI APIs;
  - features cannot import RPC wire types;
  - stable modules cannot import Pi facet, service, value/list, Harness, lane,
    view, or slot types;
  - stable mechanisms cannot import features;
  - Pi registration occurs only in approved adapter or composition files.
- Move configuration parsing, defaults, and validated values under `config/`.
- Keep tool, command, flag, shortcut, and hook metadata with Pi bindings.
- Preserve current per-`cwd`, per-session-or-invocation loading and pass narrow
  configuration values to callers.
- Remove binding-to-config or config-to-binding knowledge that creates the
  cycle.

Do not introduce `PerkConfig` as a mutable manager or one activation-global
snapshot. It is a validated value loaded for the active repository context.

### Verification

- Existing configuration tests pass for defaults, overrides, invalid values,
  environment behavior, two different working directories, and a changed
  local overlay observed at the current lifecycle point.
- The import graph no longer contains the config/bindings cycle.
- Binding metadata is unchanged according to the baseline inventory.
- Package tests still prove zero runtime dependencies and the same entrypoints.

### Deletion

- Delete the old cycle-forming imports and duplicate parsing paths.
- Delete transitional re-exports once all current callers use `config/`.

### Dogfood gate

Use Perk to run a normal workflow with default and locally overridden
configuration. The next phase starts only after configuration, tool gating, and
provider selection behave as before.

## Phase 2: prove gist authoring with the smallest session seam

### Objective

Prove one complete typed feature before extracting session behavior for every
caller. Gist authoring exercises draft state, review, canonical save, a Pi tool
or command, Prompt assembly, and presentation without the broadest delivery
or worker concerns.

### Changes

> **Status (Objective #2083, Node 2.1):** implemented with context evidence kept
> NARROW, per the objective's accepted design rule — context evidence stays
> narrow until proven; the richer `PromptEvidence` value is admitted only when
> format-4 lands or a migrated flow demonstrably needs more than the narrow
> checks — which supersedes this section's `PromptEvidence` bullet (kept below
> as history). Outcomes recorded at implementation:
>
> - The prompt-evidence verification list below narrows accordingly for this
>   phase: direct provenance, quoted-summary rejection, and the fallback window
>   are covered by the active-window injection tests (`pi/v1/gist.test.ts`,
>   `adapters/planAdapterPlannotator.test.ts`); order, wrong-audience, and
>   explicit-unavailable projection are deferred WITH the `PromptEvidence`
>   value they describe (they verify fields only that value carries).
> - The node's "identity/kind" deliverable is realized as `runId` plus the
>   adapter-side stage routing; "verified state ops" is the strict pointer
>   append inside `WorkflowSession.writeArtifact`; the context-evidence
>   deliverable is realized as the inlined active-window marker-check
>   discipline in the injectors (no premature evidence module).
> - Two interior-only behavior deltas, both test-pinned: (1) the gist-owned
>   injections (the gist-authoring context and the plannotator GIST review
>   flavor) dedup on the compaction-active window, so they re-inject after a
>   compaction drops the prior copy; (2) byte-identical artifact rewrites
>   short-circuit as `unchanged` through the shared classified core — no fresh
>   pointer is appended — for all three draft tools.
> - The thin `writeSessionArtifact`/`readSessionArtifact` wrappers in
>   `substrate/sessionData.ts` survive this phase (the plan/objective draft
>   tools still call them); the phase that migrates the last caller deletes
>   them (last-caller-migrates).
> - Both guard rules Phase 1 deferred are activated here
>   (`extension/importDirectionGuard.test.ts` Rules D and E): `authoring/` and
>   `session/` never import Pi, the RPC wire, or `surfaces/`; Pi registration
>   is confined to `pi/`, the composition roots, and the frozen shrink-only
>   legacy census.

- Create `authoring/gist/` around one-entry typed use cases, beginning with the
  actual save/review path rather than an area-wide `GistAuthoring` object.
- Introduce a gist-specific reviewer role only if its production and
  deterministic implementations share recovery semantics.
- Extract only the `WorkflowSession` identity, state, and artifact operations
  the slice uses, over the current branch/file backing and an in-memory backing.
- Classify every migrated state field by authority, history, fork behavior,
  model visibility, verification tier, and artifact relationship.
- Add the v1 context adapter needed to produce `PromptEvidence` for the gist
  Session shape and Prompt concerns. *(Superseded — see this phase's status
  note above.)*
- Keep Prose-unit meaning and ordering in authoring; let the v1 adapter place
  those units in current Pi fields.
- Add a named v1 gist installer with the existing schema, execution policy,
  progress, result, UI, and headless behavior.

Do not move every `workflowState.ts` function or session lifecycle path. Do not
create `PiBinding[]`, a universal authoring interface, or a generic reviewer.

### Verification

- Direct gist tests cover opening or resuming a draft, revisions, review
  outcomes, direct edits, canonical save, unchanged/review-required results,
  failed save, and gate release only after verified success.
- Branch-backed and in-memory session tests share the migrated read, apply,
  artifact, and `unverified` cases.
- Prompt-evidence tests cover direct provenance, order, wrong audience, quoted
  summary prose, and explicit unavailable projection.
- Pi-harness tests preserve exact registration metadata, decoding, Prompt
  assembly, access policy, progress, rendering, UI, and headless behavior.

### Deletion

- Remove the old gist registration and Pi-shaped policy handler.
- Delete superseded gist helpers, result projection, provider coupling, and
  direct state/file access.
- Remove every compatibility wrapper introduced within the phase.

### Dogfood gate

Use the migrated flow to author, review, and save a real gist. Exactly one v1
binding may be active, and the resulting state and artifacts must read back
through `WorkflowSession`.

## Phase 3: isolate StageRunner behind the current SDK bridge

### Objective

Stabilize the Perk stage interface before Pi's durable drive changes the
execution substrate.

### Changes

> **Status (Objective #2083, Node 3.1):** the confinement landed as a **rename +
> private SDK adapter + drive-session handle**, not the `StageRunner` protocol
> this section sketches (the protocol stays deferred with the durable-drive
> adapter; the node is mechanism-confinement only — "no new runner protocol").
> The stamped current-system-map stays as-stamped; this note is the
> reconciliation. Outcomes recorded at implementation:
>
> - `worker/worker.ts` → `worker/stageExecution.ts` (`driveStage` → `runStage`;
>   `DriveStageOptions`/`DriveStageDeps` → `StageRunOptions`/`StageRunDeps`); the
>   caller surface carries no SDK shapes — the SDK-typed model triple collapsed
>   into one opaque nominal `WorkerModelSelection`, and every `@earendil-works`
>   import on the drive path (construction, raw events, prompt/abort, token
>   accumulation) lives in the private `worker/sdkAdapter.ts` (the bind manager
>   grew into its drive-session handle). `workerMain.ts` keeps its name (the
>   §8.14 cross-plane entry pin) and imports no SDK.
> - `workerMain.ts` is enforced as the only execution root by the new import
>   guard Rule F (exact-set inbound `worker/` edges + the SDK-specifier census);
>   the one `MECHANISM_EDGE_ALLOWLIST` entry died with the worker→doors edge —
>   `planReadInstruction` was absorbed into the `substrate/prompts.ts` render
>   seam.
> - The dead read-only runner (`readOnlySession.ts`) was deleted whole on
>   refreshed no-caller evidence; the model-visible capping helpers moved to
>   `substrate/modelVisible.ts`.
> - Observable behavior is byte-preserved (the kept fake-session policy suite +
>   six-scenario E2E + cross-plane lockstep/parity suites are the proof); three
>   test-pinned non-observable hardenings landed: abort-rejection ownership,
>   cleanup-error precedence under the seam's never-throws contract, and
>   dispose-time throwaway-agentDir removal.

- Define `StageRunner.run` around registered stage identity, Prompt assembly,
  terminating-tool requirements, budgets, workflow run events, pointers,
  cancellation, and `StageRunOutcome`.
- Put model/auth/session construction, raw SDK events, prompt/abort, token
  accumulation, and disposal in the current SDK adapter.
- Keep `workerMain.ts` as the only initial execution root.
- Preserve one `run_finished`, incremental events, fail-soft normalization, and
  every current terminal distinction.
- Treat `runReadOnlyChild()` as unproven dead-end behavior unless a real caller
  appears; do not create a shared child-run interface around it.

Do not expose SDK session shapes or predict the durable Harness interface in
feature types. Do not merge stage execution with report waves.

### Verification

- Policy tests use a scripted drive and cover model absence, missing
  terminating tools, natural completion, incomplete idle, budget exhaustion,
  external abort, model failure, pointer capture, exact event order, and
  disposal.
- Current SDK adapter tests retain auth/model resolution, extension binding,
  raw usage translation, cancellation, and session replacement behavior.
- Worker end-to-end tests prove the existing serialized Perk outcome and event
  stream.
- An import guard limits `StageRunner` to approved execution roots.

### Deletion

- Remove SDK-shaped seams from `StageRunner` callers and superseded worker
  wrappers after equivalent interface tests exist.
- Delete unused read-only runner behavior if refreshed evidence still finds no
  production caller and no contract requires it.

### Dogfood gate

Run a real worker-backed stage through the current SDK adapter and use its
resulting Pi session for the next ordinary workflow transition.

## Phase 4: migrate remaining authoring and grow session lifecycle

### Objective

Migrate plan and objective authoring from the gist evidence while moving only
the session lifecycle required by each new caller.

### Changes

Migrate in this order unless refreshed dependency evidence changes the graph:

1. plan authoring and replanning;
2. plan review variants;
3. objective authoring;
4. objective review and reconciliation;
5. objective planning.

For each vertical slice:

- define one-entry typed operations from current behavior;
- retain feature-specific reviewer semantics rather than a generic reviewer;
- keep Plannotator or Tombell events in v1 provider adapters;
- extend `WorkflowSession` only with proven changes, artifacts, fork/adoption,
  handoff, or reload behavior;
- preserve append/read-back and artifact digest ordering;
- extend `PromptEvidence` only for the slice's Prose units, Prompt concerns,
  audience, and Session shapes;
- bind tools and commands through named v1 installers;
- move physical files only with their policy.

After two real callers share an invariant, inspect whether a smaller shared
module earns extraction. No universal authoring protocol is introduced.

### Verification

- Direct tests no longer require Pi for migrated authoring policy.
- Provider-adapter tests retain browser decisions, direct edits, dismissal,
  unavailable-provider behavior, and headless results.
- The `planReview.ts ↔ planAdapterPlannotator.ts` cycle disappears with the
  first relevant slice.
- Session tests grow through the same branch-backed and in-memory interface for
  claim, mint, reload-generation reconstruction, fork, adoption, handoff,
  strict linkage, artifact digest, and `unverified` outcomes.
- Prompt-evidence tests cover every migrated Session shape, including
  compaction and reconstructed context.
- Gates release only after verified canonical save.

### Deletion

Delete each old registration, provider import, result projector, direct branch
or artifact access, and duplicated save path immediately after its
replacement. Remove lifecycle decisions from `index.ts` as their named session
operations take ownership. No authoring behavior remains in `factories/`
merely because it began there.

### Dogfood gate

Perk must use the migrated plan flow to drive the next slice, complete one
objective authoring or review path, then reload and fork the resulting session
without losing verified state or Prompt evidence.

## Phase 5: deepen ReportWave and migrate code review

### Objective

Hide execution vocabulary behind the already-proven report-wave mechanism and
move code-review policy behind typed operations.

### Changes

- Define the public `ReportWave.start`, `collect`, and `run` interface with
  opaque `ReportWaveRef` values.
- Rename logical `WaveLane` values to `ReportAssignment`; Pi Harness lanes are
  an adapter detail rather than the domain model.
- Keep typed assignment names, completeness, reports, failures, cancellation,
  ordering, and output-free receipts.
- Move workflow scripts, ping/event channels, async identifiers, directories,
  and raw RPC messages into the RPC adapter.
- Make pending wave state belong to a wave instance, never `WorkflowSession` or
  module-global process state.
- Test the public interface with deterministic memory execution and test the
  current RPC mechanics internally.
- Introduce code-review operations for one current review flow at a time.
- Supply `ChangeReviewer`, report waves, and exterior posting through narrow
  dependencies.
- Keep browser, terminal, annotations, and Pi rendering in adapters.

The order should follow a thin proving flow, then fixed and dynamic automated
review, then human and Delivery train review variants.

### Verification

- The public start/collect/run tests cover validation-before-preflight,
  completion races, cancellation, timeout cleanup, unreadable aggregates,
  incomplete coverage, ordering, and receipt hygiene.
- Current RPC integration proves real spawn, correlation, stop, and aggregate
  behavior; memory tests alone are insufficient.
- Two sessions can run waves without sharing pending state.
- Code-review feature tests call typed operations without Pi or RPC types.
- Pi adapter tests prove review registration, progress, annotations, and
  surface behavior.

### Deletion

- Delete transport types from report-wave callers.
- Delete old code-review registrations and Pi-shaped policy handlers slice by
  slice.
- Delete module-global wave state and forwarding wrappers.

### Dogfood gate

Run the repository's current automated review and one human review surface
through the new feature operations. Do not proceed on memory-adapter tests
alone.

## Phase 6: migrate learning

### Objective

Give learning one coherent home while reusing `ReportWave` only for execution
mechanics.

### Changes

Migrate one workflow at a time:

1. learn capture and its durable artifacts;
2. learn-code and learn-docs routing;
3. audit;
4. harvest;
5. dream.

Learning owns analyst roles, evidence validity, manifests, completeness,
consolidation, routing decisions, and its Prose units. Pi adapters own
registration, Prompt placement, progress rendering, and host lifecycle. Typed
exterior operations own cross-plane persistence.

Do not make learning the owner of generic report-wave execution or all
artifact storage.

### Verification

- Feature tests cover incomplete and untrusted evidence, run-bound manifests,
  deterministic reduction, artifact validation, and routing.
- Report-wave failures and receipts retain their meanings.
- Pi adapter tests cover all current tool and command metadata, progress, and
  headless output.
- Cross-plane payloads continue to validate against `shared/` contracts.

### Deletion

- Remove migrated policy from doors, factories, and wave-specific glue.
- Delete duplicate manifest, reduction, or artifact validation helpers after
  their last old caller moves.

### Dogfood gate

Run the current learning capture and one downstream learning workflow through
the migrated paths, producing and validating real artifacts.

## Phase 7: migrate delivery and exterior operations

### Objective

Concentrate session-interior delivery policy while keeping Git, GitHub, Linear,
and process mechanics in the Python exterior and adapters.

### Changes

Migrate in effect-sized slices:

1. read-only readiness and check summaries;
2. CI execution with typed incremental progress;
3. address and review-feedback transitions;
4. submit and publication;
5. ready and handoff;
6. Delivery train synchronization, cascade, recovery, and landing;
7. commit or compaction utilities that participate in workflow state.

For each slice:

- define the semantic operation and result the feature needs;
- adapt current `coldDoor` transport behind that operation;
- preserve cancellation, envelope validation, and version-skew diagnostics;
- translate feature progress and results in the Pi binding;
- update `WorkflowSession` only after verified exterior success.

Avoid a broad Git or Python service interface. “Publish change” and “read
checks” are useful roles; “run argv” is adapter vocabulary.

### Verification

- Direct feature tests prove transition ordering and failure atomicity with
  deterministic exterior implementations.
- Process-adapter tests retain scratch input, cancellation, exit handling,
  strict JSON, and version-skew behavior.
- `run_ci` continues to emit incremental progress rather than only a final
  result.
- Pi tests preserve tool gating, termination rules, and reporting.
- Cross-plane behavior remains consistent with `shared/contracts.md`.

### Deletion

- Remove raw argv and decoder construction from migrated delivery callers.
- Delete old registrations and result projection for each slice.
- Delete process helpers only if the private adapter no longer needs them.

### Dogfood gate

Perk must run its CI, publish or update the active change, and exercise the
relevant ready or handoff transition through the migrated delivery feature.

## Phase 8: add application-host adapters and finish composition

### Objective

Move the proven Perk interfaces onto the future Pi application host as each
upstream facility passes its admission gate, then retire the v1 bridge when
support policy allows.

### Changes

- Add application-host adapters only after the candidate-specific gates above
  pass. Keep all upstream value, operation, lane, service, registry, facet,
  view, and slot types inside `pi/application/`.
- Map eligible state fields to Pi values/lists according to the field
  classification; retain entries or files where history, context visibility,
  artifacts, or fork semantics require them.
- Replace the context adapter with the stable format-4 projection while
  preserving `PromptEvidence`.
- Replace SDK stage drive with durable operations and usage projection while
  preserving `StageRunner` budgets, events, and outcomes.
- Replace RPC report execution with Pi lanes while preserving
  `ReportAssignment`, completeness, cancellation, and receipts.
- Contribute tools, hooks, providers, and lifecycle through the normative
  manifest, service, and registry interfaces.
- Adapt surfaces to views/slots with standing-state reconstruction for a
  late-attached client.
- Keep strict JSON and remote cancellation in service codecs rather than
  feature types.
- Keep extension v1 as a bridge selected by its host, never a feature flag
  that double-registers behavior alongside the application adapter.
- Reduce `extension/index.ts` to per-`cwd` dependency loading and named v1
  installers while it remains supported. Add the future manifest root only
  when Pi defines its package entry contract.
- Move remaining files to target ownership directories only as their imports
  and tests confirm the move.

### Verification

- Current and future storage implementations pass the same `WorkflowSession`
  cases, including fork/adoption, history, verification, and artifacts.
- V1 and format-4 TypeScript context fixtures produce equivalent
  `PromptEvidence`, including `retainedTail` and quoted-summary rejection.
- Current SDK and durable-drive adapters agree on recovery, unsafe-effect
  non-replay, abort, terminal tools, budgets, usage, events, and outcome.
- Current RPC and Pi-lane adapters agree on role isolation, cancellation,
  recovery, bounded reports, order, completeness, and receipts.
- V1 and application-host integration agree on registration meaning, Prompt
  assembly, access, lifecycle ordering, progress, headless output, and
  standing presentation.
- Complete-generation reload leaves no stale wave, provider listener, status,
  view, or Agent scratch state.
- Exactly one adapter binds each behavior in a host.
- `index.ts` and the future manifest root contain composition, not workflow
  decisions.
- All import-direction guards pass.

### Deletion

- Delete each superseded state, context, drive, report, provider, or rendering
  adapter only after its replacement passes parity.
- Remove the v1 bridge only after the future host is primary and support policy
  permits it; until then it remains tested compatibility code.
- Remove remaining forwarding exports and obsolete compatibility directories.
- Delete empty current-topology directories.
- Delete the temporary baseline inventory if it has no maintained test role.

This final phase is cleanup only in the sense that all remaining deletion is
small. It must not conceal an unmigrated feature.

### Dogfood gate

Run a real workflow on the Pi application host through state, Prompt assembly,
one durable stage, one report wave, and one standing view. Detach and reattach a
client, reload a generation, and complete the next workflow transition without
falling back to v1.

## Verification pyramid

Each phase uses the narrowest useful checks while iterating:

1. pure feature tests;
2. seam contract tests;
3. Pi adapter or worker adapter tests;
4. import and source guards;
5. package, type, and lint checks;
6. existing framework suites;
7. a real dogfood workflow.

The repository's normal definitive gate remains the configured run-all CI
check immediately before submitting an implementation change. Do not replace
the repository gate with a decomposition-specific script.

## Phase acceptance record

Every implementation plan created from this proposal should record:

| Question | Required answer |
| --- | --- |
| Which current behavior is moving? | Named registrations, hooks, state, and tests |
| What is the typed feature operation? | Concrete input, result, and progress types |
| Which seam is introduced? | Its volatile detail and two implementations or callers |
| Which Pi facts remain at the edge? | Schema, prompt, gating, progress, rendering, lifecycle |
| Which Session shapes and Prompt concerns move? | Named current carriers and their parity proof |
| Which upstream facility is involved? | Frozen Pi commit, maturity, supported host, and admission result |
| What old path is deleted? | Files, exports, registrations, and wrappers |
| What proves parity? | Focused tests plus existing regression coverage |
| What is the dogfood gate? | A concrete real workflow |
| Did behavior change? | If yes, the required durable docs and contracts |

## Final acceptance criteria

### Architecture

- `authoring/`, `delivery/`, `codeReview/`, and `learning/` expose typed
  feature operations, not one common interface.
- There is no application kernel, global feature catalog, generic invocation,
  or universal result wrapper.
- `WorkflowSession` is authoritative for feature-facing state and artifacts.
- `PromptEvidence` is an explicit available/unavailable value derived at the Pi
  edge.
- `ReportWave` exposes report assignments and opaque references, not RPC or Pi
  lanes.
- `StageRunner` is stage-specific and used only by approved execution roots.
- Extension v1 and application facets are adapters, not domain dispatchers.

### Dependency direction

- Feature modules have no Pi runtime, TUI, RPC wire, raw branch, raw process,
  facet, service, value/list, Harness, lane, view, or slot dependencies.
- Stable mechanisms do not import features.
- Provider adapters depend on feature role interfaces, not the reverse.
- Rich UI calls remain confined to the sanctioned surfaces files.
- The two baseline import cycles are gone.

### Behavior

- All baseline tools, effective commands, flags, shortcuts, and hooks remain
  registered exactly once unless a separately documented product change
  removes one.
- The Perk and borrowed-tool access census retains read-only and stage coverage.
- Schemas, Prose-unit meaning and Prompt placement, gating, completion,
  lifecycle ordering, progress,
  rendering, and headless behavior retain coverage.
- Session writes retain verified read-back.
- Compaction cannot turn unavailable Prompt evidence into durable absence.
- Report waves do not leak pending state between sessions.
- Worker behavior retains budget, terminal, handoff, and disposal semantics.
- Host generation replacement reconstructs standing state and leaks no
  activation-owned resources.
- Exactly one adapter registers each behavior in a host.

### Tests and packaging

- Feature policy is tested without Pi.
- Each host seam has a production adapter and a useful deterministic test
  implementation.
- Current and future adapters pass equivalent observable interface cases before
  cutover.
- The existing framework suites and guards remain green.
- The npm tarball remains one package; current entrypoints remain until an
  intentional application-host entry is added under a normative Pi contract.
- Workspaces and the zero-runtime-dependency policy remain unchanged.
- No code generation or additional package is required.

### Deletion

- Old registration and policy paths are gone.
- Transitional wrappers and re-exports are gone.
- Removing one feature does not require editing a universal protocol.

## Application-host cutover rule

The future Pi application host becomes primary only when it:

1. calls the existing typed feature operations;
2. supplies `WorkflowSession`, `StageRunner`, `ReportWave`, provider, config,
   and surfaces adapters at the appropriate facets;
3. passes current-host parity for every supported Session shape;
4. reconstructs durable and standing state across process and generation
   replacement;
5. registers each behavior exactly once; and
6. adds no Pi application type to feature interfaces.

The v1 bridge remains supported until its removal policy is explicit. Shared
host-neutral composition is extracted only after repeated identical
composition exists; the application-host roadmap alone is not evidence for a
new Perk kernel.
