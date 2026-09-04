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

> **Status (Objective #2083, Node 4.1):** the plan flow (items 1–2) landed as one slice —
> `extension/authoring/plan/{draft,source,save,review,prose}.ts` (Pi-free feature ops) +
> `extension/pi/v1/{plan,planReview,planTitle,review,objectiveReview}.ts` and
> `extension/pi/v1/providers/{selection,plannotator,tombell}.ts` (named installers + provider
> adapters + the shared review-surface machinery); `factories/plan*.ts`,
> `factories/implementHere.ts`, and the whole `adapters/` directory were deleted with the slice.
> Realized-shape notes against this spec:
>
> - **The session grew `apply(WorkflowChange)` WITHOUT snapshot payloads** on the
>   `applied`/`unchanged` arms (nothing consumes them — narrow until proven), a closed
>   2-variant union (`link-plan-ref`, `clear-node-claim`) plus the `nodeClaim()` read; identity
>   became optional (`runId: string | null`, the open-result union deleted) because the
>   identity-less save legally links `active_plan_ref` on branch-backed appends.
> - **`pi/v1/objectiveReview.ts` is the objective review arm's stable adapter home** (relocated
>   intact ahead of items 3–5; its transitional imports from `factories/` were the sanctioned
>   pi/v1 → factories direction until node 4.2 — realized: node 4.2 reshaped it into a thin
>   adapter over the feature ops and the direction closed with `factories/`' deletion).
> - **Replanning migrated by construction** — `perk plan replan` launches an ordinary
>   `stage: plan` session; no replan-specific TS path exists.
> - **Five declared interior deltas** (test-pinned, contracts amended same-turn): plan-owned
>   injections dedup over the compaction-active window; dead exports deleted
>   (`isPlanModeActive`, `isPerkPlanReferenceSelected`); claim-clear matches the full claim
>   identity (objective + node); plannotator bridge payload narrowing + emit-throw containment;
>   `extractPlanMarkdown` record-guard narrowing (fail-open null, never a throw).
> - **Registration prose stays inline at the `pi/v1/plan.ts` registration sites** (not
>   `prose.ts` constants): the prose-review workbench's TypeScript source adapter needs literal
>   in-place arrays (identifier indirection is an unsupported source shape), and the
>   `/implement-here` handler body lives in `planReview.ts` so the installer file stays fully
>   fragment-resolvable (the workbench's editable exemplar).
>
> **Status (Objective #2083, Node 4.2):** the three objective flows (items 3–5) landed as one
> slice — `extension/authoring/objective/{draft,save,review,planning,prose,dreamReportGate}.ts`
> (Pi-free feature ops with their own result unions + reviewer/backend ports; no shared
> authoring protocol) + `extension/pi/v1/{objective,objectiveAuthoring,objectivePlanning}.ts`
> (named installers + cold-door backend adapters + decode/render), and `pi/v1/objectiveReview.ts`
> reshaped into a thin adapter over `reviewObjectiveDraft`; **`extension/factories/` was deleted
> whole** (the two non-flow stragglers rode along: `objective.ts` → `pi/v1/objective.ts`,
> `objectiveDreamReport.ts` → `authoring/objective/dreamReportGate.ts`). Realized-shape notes:
>
> - **The session identity lifecycle extracted** as `session/lifecycle.ts::establishSessionIdentity`
>   (the claim/fork/adopt/mint/keep arms as one named Pi-free operation over `SessionStateStore`
>   + `SessionIdentityPorts`, two backings; `decideClaim`/`deriveForkRunId`/`resolveRunStage`
>   moved in from `substrate/workflowState.ts`); `index.ts` keeps adapter wiring (input
>   gathering, per-arm report rendering, downstream gate/stage sync) — the outcome union carries
>   the arm + decision + problems/warnings. The pre-existing harness suite
>   (`extension/sessionLifecycle.test.ts`) stayed assertion-identical as the extraction parity
>   proof. A full `installSessionLifecycle` hook installer was deliberately NOT built.
> - **The change union grew two proven variants** (`record-node-claim` — idempotent, an equal
>   re-claim short-circuits `unchanged`; `link-objective`) plus the `activeObjective()` read
>   (retiring two duplicate private helpers).
> - **`explore_objective_node` stayed adapter-tier** (wave mechanics + Result rendering, no
>   feature policy — it lives in `pi/v1/objectivePlanning.ts`, not `authoring/`); its planned
>   injected `WaveAdapter` seam was subsequently DELETED under review (one caller, no alternate
>   adapter ever bound — tests drive the registered tool over a fake RPC responder), so the
>   flow is a private function over the production RPC adapter.
> - **Reconciliation stayed adapter-tier — a deliberate review-driven deviation** from the
>   planned `reconcileObjective`/`addObjectiveNode` feature ops + `ObjectiveReconcileBackend`
>   port + pure `resolveReconcileObjective`: as built, those were zero-policy passthroughs over
>   a single production adapter (the planned "thin typed ops" carried NO feature decisions once
>   decode-once typed the inputs), and the first review round deleted them as unearned
>   abstraction. The reconcile/add-node writes are two private cold-door functions in
>   `pi/v1/objectivePlanning.ts`, and the three-tier resolution is lazy null-coalescing at the
>   `/objective-reconcile` handler. The feature-tier policy that DID earn `authoring/` — the
>   node-transition audit gate + claim semantics (`objectiveNodeTransition`) — lives there.
>   Should a second reconcile backend appear, the port earns its way back per the plan's own
>   "after two real callers share an invariant" rule.
> - **Six declared interior deltas** (test-pinned, contracts amended same-turn): objective-owned
>   injections joined the compaction-active window; idempotent re-claims; seam-owned
>   claim/linkage warning strings; `writeSessionArtifact` deleted (last caller migrated;
>   `readSessionArtifact` survives for the browser doors' raw baselines); whitespace-only
>   `title`/`base` trim-or-omit on the direct save path; `isObjectiveAuthoring` fail-open
>   hardening.
> - **Decode-once-at-the-edge realized**: typed feature inputs deleted the census'd redundant
>   re-validations and the `addObjectiveNode` decoder/core asymmetry; dead public types did not
>   re-emerge.
> - **Still no `PromptEvidence` module** (the 2.1 narrow-until-proven rule): context-evidence
>   coverage (live-copy suppression / post-compaction re-injection / quoting-summary /
>   reconstructed-context) is realized as inlined marker checks per migrated injection.
> - **The Phase-4 dogfood gate is CLOSED** — the evidence record is committed at
>   `docs/design/archive/ts-decomposition-phase4-dogfood.md` (`f03ee7ff`), complete with no
>   skipped arms; it also set the closing precedent later phases reuse (the evidence record
>   lands on the train tip as one docs-only commit with only the tip's handoff-ready stamp
>   re-run).

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

> **Status (Objective #2083, Node 5.1):** the transport-confinement half landed — realized-shape
> notes against the sketch below:
>
> - **The `ReportWave.start/collect/run` + opaque `ReportWaveRef` interface is SUPERSEDED, not
>   built** — the kept public shape is `startReportWave`/`runReportWave` over the `WaveAdapter`
>   seam (handle + never-rejecting `result` promise). Confinement was realized as a two-tier
>   module split instead: `waves/transport.ts` owns the adapter seam, script tier, and receipt
>   primitives; `waves/reportWave.ts` keeps the logical tier (`ReportAssignment`, normalization,
>   the runner) with ONE sanctioned `WaveAdapter` type re-export; `renderWaveScript`/validation
>   went module-private. Guard Rule G (`extension/importDirectionGuard.test.ts`) enforces the
>   exact ten rpcAdapter importers, bans outside edges into `waves/transport.ts` +
>   `waves/memoryAdapter.ts`, and censuses raw `WAVE_RPC_`/channel tokens (tests included).
> - **Adapter construction stays at the ten execute sites** — composition-root threading was
>   considered and dropped at review (churn without operational gain); the confinement proof is
>   the guard's exact-set pin, not construction placement.
> - **The rename is core-scoped**: `WaveLane` → `ReportAssignment` (`WaveSpec.assignments`) plus
>   caller identifiers that directly name the report-wave unit; the harvest/audit/dream flow
>   vocabulary ("lane" as the §8.48/§8.50/§8.59–8.61 persisted-schema term) is deferred to
>   nodes 5.2/6.x, and every runtime literal stayed byte-identical.
> - **Pending state is per-registration**, not per wave instance: plain state objects owned by
>   registration closures (`doors/pendingWave.ts`'s `PendingWaveState` + one shared
>   `collectPending` with the identity-guarded clear), threaded as explicit parameters. The
>   draft door's module-global `context` slot rode the same fix (`DraftReviewWaveState`).
> - **The transport failure vocabulary settled as a subset union**: transport-tier
>   `WaveRunFailureReason` (the six wave-level reasons) ⊆ logical-tier `WaveFailureReason` —
>   structurally assignable, zero runtime mapping, and a lane-level reason on a script-run
>   failure is now unrepresentable.
> - Node 5.2 owns the rest: code-review typed operations, the post-state machines
>   (the automated post state, the annotation-push state), and the phase dogfood gate (the live
>   pi-subagents leg — the offline runner-over-real-RPC integration landed in 5.1).
>
> **Update (Objective #2130, Node 1.1, 2026-09-02):** the first bullet's SUPERSEDED
> disposition of the opaque `ReportWaveRef` lifecycle is **reversed** — the seam is owed
> by objective #2130 node 2.1 (see `module-contracts.md` § ReportWave for the canonical
> reversal rationale); the docs and the #2130 roadmap now agree. The original note above
> is byte-preserved as history (its superseded phrase wraps across two source lines, so a
> single-line grep for the phrase does not match it — verify with a multiline search).
>
> **Status (Objective #2083, Node 5.2):** the code-review half landed — realized-shape notes:
>
> - **The code-review flows sit behind typed feature operations** in the Pi-free
>   `extension/codeReview/` home: `submission.ts` (the curated-submission op over
>   `ReviewSubmitter` + the discriminated `FormalEventGate` + `WorkflowSession`) and
>   `automated.ts` (`runAutomatedReview`/`publishAutomatedReview` over `ReviewTargetResolver` +
>   `ChangeReviewer` + `ReviewPublisher`). `ChangeReviewOutcome` is a type-only alias of
>   `PrReviewWaveOutcome` — never a second hand-mirrored vocabulary — and the finding shapes
>   stay deliberately distinct per flow (no lossy generic finding).
> - **The nine door modules moved wholesale**: six `pi/v1/codeReview/` installers
>   (`automated.ts`, `submit.ts`, `reviewWave.ts`, `terminal.ts`, `browser.ts`, `stack.ts`) +
>   the checkout helper (`checkout.ts`) + one provider (`pi/v1/providers/annotations.ts`).
>   Rule E's census burned down by all eight door registrants; Rule G swapped the door entries
>   for their successors (net 10 → 9). Adapter construction stays at execute sites (the 5.1
>   precedent).
> - **The last two module-global post-state machines became per-activation state**: the
>   automated review-pass state is a plain `ReviewPassHolder` owned by the installer (the two
>   feature ops own every transition); the annotation-push surface/ledger/held/alternates
>   became `createAnnotationState()`, created once in `index.ts` and threaded to the installer
>   and every priming door (`waveIsolation.test.ts` pins two-activation isolation for both).
> - **Session records ride the seam**: `WorkflowSession` grew three ordinary single-append
>   changes (`record-pr-review`/`record-review`/`append-review-post`) plus the fail-open
>   `reviewPosts()` read; the seam owns the record types and the read-back loudness; the review
>   posting paths and the stack door's two reads lost all direct `workflowState.ts` access.
> - **The experimental `/pr-review-dynamic` flow was retired wholesale** (operator-approved
>   deviation from the node text, settled at plan time): the command, tool, selector agent,
>   skill, config key, and binding row are gone across both planes; the canonical `/pr-review`
>   is unchanged. `waves/prReviewWave.test.ts` stayed byte-untouched (the wave-policy parity
>   proof).
> - **The Phase-5 dogfood gate is PENDING at this layer's review** (not silently omitted) — the
>   plan's own closing sequence runs the live arms (`/pr-review` + `/pr-review-terminal`,
>   through the migrated operations) post-review from the train worktree (a fresh session must
>   load this branch's extension), then lands the evidence record at
>   `docs/design/archive/ts-decomposition-phase5-dogfood.md` as one docs-only commit with only
>   the tip's handoff-ready stamp re-run — the Phase-4 closing precedent. The evidence binds to
>   the final tested SHA, so the arms deliberately follow the review-fix commits, never precede
>   them. Phase 6 must not start before that record exists.

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

> **Status (Objective #2083, Node 6.1):** learn capture + the learn-docs/learn-code routing
> landed — realized-shape notes:
>
> - **Behavior moved**: `learn`, `run_learn_wave`, `/learn`, `/learn-docs`, `/learn-code` —
>   registrations, prompts, guards, the marker mirror, and the wave policy — behavior-preserving
>   against the frozen binding inventory. The three old modules (`doors/learn.ts`,
>   `doors/learnFactory.ts`, `waves/learnWave.ts`) + five test files were deleted whole in the
>   same change (index imports and guard census entries included).
> - **Typed feature operations** in the Pi-free `extension/learning/` home: `finishLearn`
>   (capture.ts — the capture/skip state policy; marker cleared only on verified backend
>   success), `runLearnAnalystWave` + `parseAngleSelections` (analystWave.ts — angle policy,
>   report schema with enums DERIVED from `LEARN_ANGLES`/`CAPTURED_DECISIONS`, assignment
>   composition, best-effort outcome mapping), `decideLearnLaunch` + the factory-kind vocabulary
>   (routing.ts — the `factory_common.py` twin), and the guidance renders (prose.ts).
> - **Seams introduced**: `LearnBackend` + `PendingLearnMarker` (production adapters over
>   `runColdDoor`/cache markers in `pi/v1/learning/learn.ts`; deterministic fakes in the feature
>   suite). `WaveAdapter` reused, not introduced; `decideLearnLaunch` stays a concrete function
>   (no speculative gather port). `activePlanRef` moved to `substrate/workflowState.ts` as the
>   shared structural seam — `doors/address.ts`'s duplicate died two nodes early.
> - **Pi adapters** (`pi/v1/learning/learn.ts` + `factory.ts`): registrations with COMPLETE
>   frozen-baseline deepEqual pins, strict tool-boundary decodes, the planning-stage +
>   `plan_save` host guards, `subagentModel` resolution, RPC adapter construction at the execute
>   site, prompt placement + binding suffixes, Result rendering, headless stderr arms.
>   Cancellation is unchanged and now feature-pinned: the tool signal threads into the wave; an
>   abort settles `cancelled` (normalized, never a throw).
> - **WorkflowSession / PromptEvidence changes**: NONE — learn state stays plan-header (§8.36)
>   + the local marker. No upstream facility admitted.
> - **Dogfood**: none for this node — the Phase-6 gate rides node 6.3. The Phase-5 dogfood
>   record was this node's start precondition; the operator waived it explicitly on the plan
>   issue (the 5.1 precedent) — the record remains owed on the train before 6.3's gate.

> **Status (Objective #2083, Node 6.2):** the session-audit judgment workflow landed —
> realized-shape notes:
>
> - **Behavior moved**: the `run_audit_wave` registration, the pre-launch `bad_state` arms,
>   the zero-lane short-circuit, the sanitize-before-write discipline, the `io_error` arm, and
>   the result renders — behavior-preserving against contracts §8.50 (semantic JSON parity for
>   verdicts.json; exact-text parity for the rendered result + details). The two old modules
>   (`waves/auditWave.ts`, `doors/auditWaveTools.ts`) + their test files were deleted whole in
>   the same change (index import and guard census entries included).
> - **The typed feature op** in the Pi-free `extension/learning/audit.ts` home (one flow = one
>   module): `judgeAuditBundle` — the one entry op owning schema → decode → lane plan → wave →
>   sanitize → reduce → persist — with the **relocated** function-shaped `writeVerdicts`
>   capability (the write the door's execute core already injected) and the **correlated**
>   `AuditWaveStatus` (incomplete ⇔ the wave-level failure rides the status — the
>   incomplete-but-unexplained state is unrepresentable). The export surface is deliberately
>   narrow: lane planners and sanitizers stay module-private; `AuditVerdictLane` became a
>   wire-identical discriminated union with type-predicate narrowing (no casts).
> - **The zero-lane receipt fabrication was deleted deliberately**: the old wave entrypoint
>   synthesized a `complete` receipt solely to satisfy its return shape; no audit consumer
>   reads receipts, so the internalized op skips the wave entirely on the zero-lane path.
> - **The mechanism-tier ride-along**: `waves/reportWave.ts` now re-exports the transport
>   tier's wave-level reason subset as `WaveLevelFailureReason` alongside `WaveAdapter` — the
>   sanctioned type-only seam grew one name; guard Rule G's interior ban is unchanged.
> - **Pi adapter** (`pi/v1/learning/audit.ts`): the registration with a COMPLETE
>   frozen-baseline deepEqual pin, the `auditBundleDirOf` workflow-state binding, adapter/model
>   resolution at the execute site, and the thin Result-rendering `executeAuditWave` core — now
>   pinned with exact-text renders for two representative arms. New feature-suite pins:
>   mid-flight + pre-aborted cancellation (run stopped, verdicts still written) and the
>   deterministic full-sequence reduction order.
> - **WorkflowSession / PromptEvidence changes**: NONE — the `audit_bundle_dir` handoff
>   binding and the `audit` registry stage are untouched.
> - **Dogfood**: none for this node — the audit path has live evidence
>   (`docs/design/archive/session-audit-dogfood.md`) and externally observable behavior is
>   preserved; the Phase-6 gate rides node 6.3, and the outstanding Phase-5 dogfood record
>   **must close before 6.3 starts**.

> **Status (Objective #2083, Node 6.3):** the harvest + dream workflows landed in `learning/`
> — realized-shape notes:
>
> - **Behavior moved**: `run_harvest_wave` + `run_dream_wave` — registrations (byte-identical
>   metadata), the pre-spawn/pre-launch refusal ladders, and the two-level dream
>   ordering/recovery policy (verified marker clear → stale-bundle removal → strict analyst
>   wave → budget check → bundle write → reducer wave → §8.65 bracket → finalize-in-place →
>   marker set) — behavior-preserving against contracts §8.48/§8.59–§8.62/§8.65 (error
>   vocabulary, result texts, and serialized wire shapes pinned exact). The six old modules
>   (`waves/harvestWave.ts`, `waves/dreamWave.ts`, `waves/dreamReducerWave.ts`,
>   `waves/dreamReport.ts`, `doors/harvestWaveTools.ts`, `doors/dreamWaveTools.ts`) + six test
>   files were deleted whole in the same change (index imports and guard census entries
>   included; **zero `waves/` production edits** — `reportWave.ts` reused as-is).
> - **Typed feature ops** in the Pi-free `extension/learning/` home: `analyzeHarvest`
>   (harvest.ts — lane planning, the wave, pointer stamping, the malformed-report lane
>   degrade; outcome `wave_failed`/`analyzed` carrying `WaveAttemptReceipt`s) and
>   `analyzeDream` (dreamAnalysis.ts — the two-level policy above dream.ts/dreamReducer.ts;
>   ONE `io_failed` arm for all four io sites plus the `DreamAnalysisAggregate` union of the
>   six real post-launch arms, discriminated on the exact wire fields so contradictory
>   combinations are unrepresentable while serialization stays byte-identical).
>   `containment.ts` is the one cross-flow consolidation (the structural `LanedDocs` view
>   keeps it a leaf); the dream runners now return `attempt: WaveAttemptReceipt` (no
>   `WaveScriptReceipt` in any learning signature); `dreamReport.ts`'s export surface shrank
>   to `buildDreamReport`/`DreamReportContext`/`DREAM_REPORT_INPUT_SCHEMA` (+ referenced
>   types).
> - **Pi adapters** (`pi/v1/learning/harvest.ts` + `dream.ts`):
>   `installHarvestBindings`/`installDreamBindings` with COMPLETE frozen-baseline deepEqual
>   registration pins, inlined guideline literals, production capability wiring
>   (`digestSessionData`, the one `appendWorkflowState`-backed `markBundleDigest` closure,
>   `revalidationBracket`, `atomicWriteFileSync`, force `rmSync`), `subagentModel` resolution
>   at the execute site, and the exported thin execute cores
>   (`executeHarvestWave`/`executeDreamWave`) mapping the typed outcomes to Results. New
>   feature-level pin: the glue-boundary cancellation rule — an abort between the waves
>   issues NO reducer spawn, with exact cancelled-attempt accounting.
> - **WorkflowSession / PromptEvidence / gating changes**: NONE — both tools keep
>   `PERK_TOOLS` + `READ_ONLY_TOOLS` membership and no stage list; `dream_bundle_digest`
>   semantics unchanged.
> - **Accounting ledger** (recalculated at the implementation-time parent head `d316e843`):
>   - Production LOC: 4,295 deleted (the six modules) → 4,515 added across the eight
>     successors (`learning/containment.ts` 104, `learning/harvest.ts` 408,
>     `learning/dream.ts` 935, `learning/dreamReducer.ts` 707, `learning/dreamReport.ts`
>     1,498, `learning/dreamAnalysis.ts` 435, `pi/v1/learning/harvest.ts` 225,
>     `pi/v1/learning/dream.ts` 203); whole-change production net **+220** (rewiring
>     included). **Named invariant for the growth** (operator-accepted on this node): every
>     added line beyond the verbatim moves is the plan-named new semantics-bearing code — the
>     two typed outcome unions and the REQUIRED capability seams on
>     `analyzeHarvest`/`analyzeDream` — plus the module-split overhead of the containment
>     extraction and the two adapters (headers, the `LanedDocs` seam). Zero policy/behavior
>     code grew; the predicted swamping deletion never existed because the trivial guards
>     stay flow-private by operator decision, so no large duplication remained to delete.
>   - Test LOC: 6,524 (six suites) → 6,985 (seven suites), net +461 — the added pins are
>     frozen registration baselines, cancellation arms, exact-text renders, and
>     serialized-key-order guards.
>   - Files: 6 production modules + 6 suites deleted; 8 production modules + 7 suites added.
>   - Export ledger — **Retired** (deleted or privatized): `registerHarvestWave`,
>     `registerDreamWave`, `runHarvestWave`, `buildHarvestLanes`, `stampHarvestReport`,
>     `validateDreamReport`, `renderDreamReport`, `decodeDreamReducerReport`, the
>     dream-report caps/constants + input component types. **Relocated**: the containment
>     trio (`lexicalContainmentError`/`verifyDocContainment`/`ContainmentFs`), the harvest +
>     dream manifest decoders/schemas/caps/filenames,
>     `codePointLength`/`decodeStringArray`/`decodeDreamAnalystReport`,
>     `runDreamAnalystWave`/`runDreamReducerWave` (outcomes now carry
>     `attempt: WaveAttemptReceipt`), the bundle serializers
>     (`composeDreamBundle`/`finalizeDreamBundle`/`decodeFinalizedDreamBundle`/
>     `nonKeepProposals`), `buildDreamReport`/`DreamReportContext`/
>     `DREAM_REPORT_INPUT_SCHEMA`, `executeHarvestWave`/`executeDreamWave`. **Newly
>     introduced**: `analyzeHarvest` + `HarvestAnalysisOutcome`, `analyzeDream` +
>     `DreamAnalysisOutcome`/`DreamAnalysisAggregate`, `LanedDocs`,
>     `installHarvestBindings`/`installDreamBindings`.
>   - Deletion test: stripping `learning/harvest.ts` / `learning/dreamAnalysis.ts` guts both
>     adapters (`pi/v1/learning/harvest.ts` imports the decoder + op + schema;
>     `pi/v1/learning/dream.ts` imports `analyzeDream` + the decode surface) — verified by
>     the import graph.
> - **Dogfood**: the Phase-6 gate (Arms A/B/C) rides this node post-review from the train
>   worktree — to be recorded in `docs/design/archive/ts-decomposition-phase6-dogfood.md`.
>   The Step-0 Phase-5 evidence debt was decoupled by operator decision at implementation
>   start ("proceed with 6.3 now; Step 0 handled separately") — the Phase-5 record remains
>   owed on the train and must close before the Phase-6 gate runs.

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

> **Status (Objective #2083, Node 7.1):** the first delivery slices landed — the stack-status
> read + CI execution — realized-shape notes:
>
> - **Behavior moved**: `run_ci` + `/ci` + `--allow-project-ci` (registrations byte-identical,
>   frozen-baseline deepEqual pins incl. the flag via the bound runner's `getFlags()`), and
>   `objective_stack_status` + `/objective-stack` — behavior-preserving against the frozen
>   binding inventory (wire payloads, refusal/confirm texts, render prose, and gating all
>   unchanged; `READ_ONLY_TOOLS` untouched). `doors/ciExecutor.ts` + its suite were deleted
>   whole in the same change (index import and guard census entries included);
>   `doors/objectiveStack.ts` survives with exactly the mutating family.
> - **CI is the feature; status is adapter-tier.** `extension/delivery/ci.ts` is the one
>   Pi-free feature op (`runCiChecks` — selection incl. exact-name-before-comma-split and
>   first-duplicate-row, declared-order concurrent execution, change-scoped glob gating with
>   compute-once + fail-open-null, never-throw per-check folding, route-don't-relay scratch)
>   returning the typed `CiRunOutcome` union (`not_configured`/`invalid_selection`/`completed`;
>   `executed` carries no `passed` — derived, so a contradiction is unrepresentable) with the
>   delivery-specific typed progress union (`run_started`/`check_settled`, ordered deep-copied
>   snapshots, sink-failure ownership incl. async-rejecting sinks). The stack-status slice was
>   realized **adapter-only** (`pi/v1/delivery/stackStatus.ts`) — a deliberate narrowing of the
>   roadmap's "semantic operations" wording for this slice: the read is pure decode + render +
>   delegation with zero policy (the 4.2 zero-policy precedent), so no feature op was built.
>   Readiness and CI share no abstraction.
> - **Semantic ports** (each with one production adapter + deterministic fakes):
>   `RunConfiguredCheck` ("run this configured check") and `ObserveChangedFiles` ("changed
>   files vs trunk, `null` = unknown") — the `bash -lc` runner and the git trunk-detection
>   composition (`changedFiles`) live in `pi/v1/delivery/ci.ts`; "load checks" is the adapter
>   passing the validated `PerkConfig.ci.checks` view inward (no config port). The wire
>   vocabulary (`CiReport`/`CiCheckResult`/`CiResult`), the private union→wire mapping, the
>   glyph renders, the 1s unref'd elapsed ticker, and the scope gate + `ctx.ui.confirm` +
>   per-activation `ApprovalLatch` all live in the adapter; refusals (`project_ci_unconfirmed`)
>   and `bad_input` never enter the feature union. No exported execute core — the
>   confirm/decline/latch and cancellation arms are tested through the REGISTERED tool (the
>   harness gained additive `ctx.signal` + scripted-confirm knobs).
> - **Substrate moves**: the stack-objective resolution primitive to
>   `substrate/workflowState.ts` (`resolveStackObjective`, re-typed off Pi to a structural
>   `BranchSource` slice) with the command vocabulary split out to the stack-owned Pi-free
>   `delivery/stackObjective.ts` (`parseStackObjectiveArg` + `STACK_NO_OBJECTIVE_MESSAGE`,
>   message text byte-identical — parsing/prose are binding concerns, not workflow-state
>   mechanism; the review-pass split) and the lenient
>   list helpers (`objectListField`/`stringListField`) to `substrate/coldDoor.ts`;
>   `coldDoor.test.ts` gained the missing `ctx.signal`→`pi.exec` cancellation pin.
>   `findingLines` stays a deliberate two-copy module-private helper (status render + the
>   surviving `renderLandOutcome`) per the cold-door doctrine — consolidation rides the land
>   migration. The `/objective-stack` command's duplicated inline cold-door call was deleted
>   (both surfaces share one status read).
> - **WorkflowSession / PromptEvidence / gating changes**: NONE.
> - **Accounting ledger** (recalculated at the implementation-time parent head `84906a8c`):
>   - Production LOC (post-address recount): 1,026 deleted (−755 `doors/ciExecutor.ts`,
>     −265 the objectiveStack status portion, −4 index, −2 review-comment re-anchor) → 1,238
>     added
>     (`delivery/ci.ts` 361, `pi/v1/delivery/ci.ts` 539, `pi/v1/delivery/stackStatus.ts` 237,
>     `delivery/stackObjective.ts` 16, `substrate/workflowState.ts` +24,
>     `substrate/coldDoor.ts` +16, objectiveStack rewiring
>     +34, index +9, review +2); whole-change production net **+212** against the ≤ 0 target.
>     **Named excess classes** (each against a plan-named new invariant; operator-accepted
>     on this node): the typed `CiRunOutcome`/
>     `CiCheckOutcome` union + the adapter's union→wire mapping (~90); the typed progress
>     union + deep-copy emission + sink-failure ownership + the adapter's ticker translation
>     (~90); the two port seams + their production composition (~25). Zero policy/behavior
>     code grew; the status slice itself is ≈ net-zero (−230 door / +237 adapter).
>   - Test LOC: 1,644 deleted → 2,335 added, net +691 — the new arms are the frozen
>     registration baselines (tool + command + flag), the union→wire mapping pins,
>     confirm-accept/latch + confirm-decline, the pre-aborted `ctx.signal` arm, progress
>     snapshot isolation + throwing-sink containment, the port-signal pins, the
>     coldDoor signal pin, the stack-arg parser rows, and the list-helper + resolver unit
>     rows.
>   - Files: +9 (`delivery/ci.ts` + test, `pi/v1/delivery/ci.ts` + test,
>     `pi/v1/delivery/stackStatus.ts` + test, `delivery/stackObjective.ts` + test,
>     `testing/objectiveStackFixtures.ts`), −2
>     (`doors/ciExecutor.ts` + test).
>   - Export ledger — **Retired**: `registerCiExecutor`, `CiExec`, `RunCiOpts`, `RunCiDeps`
>     (incl. the never-used `decideScope` override), the test-only `cap` option; privatized:
>     `runOneCheck`, `ciScratchPath`, `matchesGlob`, `stackStatus`. **Renamed**:
>     `ExecOutcome` → `CiExecOutcome` (feature); `NO_OBJECTIVE_MESSAGE` →
>     `STACK_NO_OBJECTIVE_MESSAGE`, `parseObjectiveArg` → `parseStackObjectiveArg`
>     (the stack-owned `delivery/stackObjective.ts`). **Relocated**: `decideCiScope`/`CiScope` + `runCiChecks` (feature,
>     reshaped return); `CiReport`/`CiCheckResult`/`CiResult` + `renderCiProse` +
>     `renderCiProgress` (readonly-widened param) + `changedFiles` (CI adapter);
>     `renderStackStatus` (status adapter); `resolveStackObjective` +
>     `objectListField`/`stringListField` (substrate). **Newly introduced**: `CiRunOutcome`,
>     `CiCheckOutcome`, `CiProgressState`/`CiProgressEntry`/`CiProgressEvent`,
>     `RunConfiguredCheck`, `ObserveChangedFiles`, reshaped `RunCiChecksOpts`/
>     `RunCiChecksDeps`, `installCiBindings`, `installStackStatusBindings` — every added
>     export has a production importer or is a frozen-baseline/exported-core test surface.
>   - Deletion test: gutting `delivery/ci.ts` hollows the CI adapter — `pi/v1/delivery/ci.ts`
>     imports the scope policy, the runner op, both unions, and both ports; selection,
>     ordering, glob gating, fail-closed recovery, and progress semantics all vanish, leaving
>     only registration + render shells. Verified by the import graph.
> - **Dogfood**: the cheap migrated-status read (`/objective-stack 2083` from a fresh
>   read-only session) + one run-all `run_ci` through the reloaded migrated executor ride the
>   Step-7 gate; the full Phase-7 dogfood gate closes at node 7.5. The Phase-5/6 dogfood
>   records are this layer's HARD submission gate (no waiver) — re-checked at `/submit`.
>   Operator decision at implementation close: the Phase-5/6 gates RUN from the `plan-2114`
>   train worktree (the migrated review/learning flows' live extension; the Phase-5 legs
>   against its real open PR #2115), with BOTH records committed on THIS layer — trading the
>   designed own-layer placement for no published-layer amend, no handoff re-stamp, and no
>   cascade; the gate's operative requirement (the records exist in this layer's synchronized
>   ancestry) is satisfied as written — both records landed (`f10b7cf1` Phase 5, `19a9545b`
>   Phase 6; the Phase-5 terminal leg also surfaced the pre-existing stacked-layer active-arm
>   scoping gap, filed as #2117). Step-7 evidence (2026-08-31, fresh sessions in this worktree
>   at `19a9545b`): `/ci` run-all through the LIVE migrated executor → "all checks passed"
>   (the command's one-line human summary — the verbose report remains the `run_ci` tool's
>   model-facing output, the unchanged split); `/objective-stack 2083` from a fresh `pi --plan`
>   (gate-on) session rendered the full 16-layer train (published prefix 11/16, next
>   build-ready 7.1) — the migrated read-only door works end to end under the gate. Review
>   follow-up evidence (2026-08-31, at `86baa9dc`): a fresh headless session
>   (`pi --mode json -p`, env-leak guard applied) invoked the REGISTERED `run_ci` tool — the
>   JSON event stream shows `tool_execution_start` for `run_ci`, live `tool_execution_update`
>   ticker partials (the glyph render with elapsed seconds), and the full model-facing report
>   ("perk CI: all checks passed." + all 8 ✓ rows) — the moved tool's execute/onUpdate/
>   full-result path exercised end to end, green.

> **Status (Objective #2083, Node 7.2):** slices 3–4 landed — the review-feedback transitions
> (`classify_review_feedback`, `finalize_address`, `/address`) and submit + publication
> (`submit`, `/submit`) — realized-shape notes:
>
> - **Behavior moved**: both flows out of `extension/doors/` behind two Pi-free feature ops —
>   `extension/delivery/submit.ts::submitChange` (one entry: external publish → verified-success
>   session updates → the bounded conflict decision, composable as `publishVerified` +
>   `decideConflictFollowUp`) and `extension/delivery/address.ts::finalizeAddress` (pre-effect
>   refusal → publish → resolve → request↔row fate correlation → verified-success recording →
>   the conflict decision, composing the sibling's internals one-way) — with named installers
>   `pi/v1/delivery/submit.ts` + `address.ts`. `doors/submit.ts` + `doors/address.ts` (+ both
>   test suites) deleted whole in the same node (Rule E burn-down ×2; Rule G swapped the
>   address census entry). Registration surfaces are frozen-baseline pinned byte-identical AND
>   every load-bearing arm carries a full-details WIRE baseline captured from the OLD doors
>   pre-deletion (byte-exact `assert.deepEqual` on the JSON round-trip, optional-key absence
>   semantics included). `toolGating.ts`, `stageExecutionE2e.test.ts`, and
>   `waves/reviewClassifierWave.test.ts` stayed byte-untouched (parity proofs — all green).
> - **The conflict-decision timing split is structural**: `/submit` decides immediately after
>   publish; `finalize_address` decides only after corroborated full resolve success — a
>   resolve failure never burns an attempt (negative-pinned e2e). Drive translation stays at
>   each surface (`driveConflictFollowUp`); the command's report-before-drive order is pinned
>   by a shared-recorder test.
> - **Action-specific ports, one production composition**: `PublishChange` (production =
>   `createChangePublisher` — the `perk pr submit --json` cold-door composition, which also
>   owns `operation.notes` warning reports at publish-success time — pre-resolve on EVERY
>   published arm, pinned by the notes-on-failure regression), `ResolveThreads` (production =
>   `perk pr resolve-threads --json --batch`, the fail-arm payload re-narrowing preserved),
>   the `ConflictAttempts` read/write capability, and `recordImplementationPointer`
>   (never-throws contract; the production `captureSessionPointer` closure). The address
>   installer builds `FinalizeAddressDeps` by extending `publishDepsFor(pi, ctx)` — the
>   one-production-adapter invariant is structural.
> - **Named interior deltas (the only behavior changes)**: **D1** — the ok-arm corroboration
>   guard: a nominal-success resolve envelope whose rows fail to corroborate every requested
>   thread routes to `published_partial` (no `last_review_batch`, no termination); §8.52
>   amended in the same change ("full success = corroborated per-thread success"). The
>   module-private ThreadFate fold has two consumers (safe-retry derivation + D1) — the
>   drop-the-fates simplification stays declined. **D2** — `conflictResolutionAttempts`
>   narrows a readable-but-malformed persisted value to 0; a THROWING branch read still
>   propagates (the load-bearing failure path, pinned). **D3** — `issue` decodes via
>   `stringField` (the opaque string id `PrSubmitOut.issue: str` actually sends; the old
>   `numberField` never matched — details silently dropped it); one documented baseline delta
>   with a both-ways regression pair. **D4** — `--run-id` sourcing stays parity via the DIRECT
>   throwing `rebuildWorkflowState(branchOf(ctx)).run_id` read at the adapter, invoked lazily
>   at publish time (`PublishDeps.readRunId`): a throwing branch read still fails BEFORE the
>   external call, while the finalize empty-batch refusal keeps firing first — the
>   pre-migration order (the review's address pass caught the eager-read regression); recorded
>   also because review caught the `activeSessionRunId` near-miss (it catches, and would
>   silently drop the stamp). Post-review hardenings beyond the plan's four: the ok-arm
>   corroboration guard additionally refuses CONTRADICTORY duplicate rows (rows disagreeing on
>   `success` never corroborate; the retry strips their replies — last-row precedence remains
>   only on the partial/retry path), and `setConflictAttempts` refuses a non-integer/negative
>   write loudly (the reader narrows such values to 0, so persisting one would silently reopen
>   the budget — invalid counter states are now unrepresentable through the seam).
> - **Declined hardening (recorded)**: the submit-path drive-despite-unverified-increment
>   posture is deliberately preserved (parity; the seam's loud warning is the mitigation) —
>   pinned by the unverified-increment parity test; the sync path's withhold-and-release stays
>   the stricter posture over the same checked seam (`objectiveStackDrive.test.ts`'s
>   dropped-increment/lease-release arm survives verbatim). Revisiting the split is 7.4's call.
> - **Substrate/session moves**: the checked counter seam `conflictResolutionAttempts` +
>   `setConflictAttempts` (equal-value short-circuit; strict read-back boolean; byte-identical
>   failure texts) joins `substrate/workflowState.ts` — the counter stays OUT of
>   `WorkflowSession` (pre-effect bounding state); `CONFLICT_RESOLUTION_ATTEMPT_CAP` lives in
>   `delivery/submit.ts` (the bound is policy); `doors/objectiveStack.ts` repoints + dedupes
>   its reset/increment over the seam. `WorkflowSession` grew exactly one variant:
>   `record-review-batch` (`last_review_batch`, LWW, strict read-back, scope "address",
>   classification ignored by the op; persisted shape byte-identical; the memory backing
>   gained a `lastReviewBatchRecord()` observer).
> - **Accounting ledger** (recomputed after the review-address pass):
>   - Production LOC: 928 deleted (−373 `doors/submit.ts`, −555 `doors/address.ts`) → 1,264
>     added (`delivery/submit.ts` 147, `delivery/address.ts` 295, `pi/v1/delivery/submit.ts`
>     372, `pi/v1/delivery/address.ts` 450) plus seams (+53 substrate, +57 session) − 7
>     objectiveStack dedupe + 1 comment re-anchor wrap; whole-change production net **+440**
>     against the ≤ 0 target. **Named excess classes** (each against a plan-named invariant):
>     the typed outcome unions + action ports + the composition factory across the two feature
>     modules (+447 feature-tier, of which the adapter tier shrank −106 — the fate
>     correlation, D1's guard incl. the contradictory-duplicate refusal, retry-unrepresentable
>     states, and the ordering/atomicity policy now live once, Pi-free, deletion-testable);
>     the D2 checked counter seam + its invalid-write refusal (+53); the
>     `record-review-batch` session variant across seam + two backings (+57). Zero new policy
>     surface beyond the plan's named deltas + the two review-pass hardenings above. The
>     plan-required operator acceptance of this named ledger rides the PR review gate: the
>     ledger is posted on PR #2123 (body + review thread) and the human's approval of that PR
>     IS the recorded acceptance gesture — merge does not proceed without it.
>   - Test LOC: 1,028 deleted (−547 `doors/submit.test.ts`, −481 `doors/address.test.ts`) →
>     2,201 added across the four new suites (`delivery/submit.test.ts` 236,
>     `delivery/address.test.ts` 359, `pi/v1/delivery/submit.test.ts` 789,
>     `pi/v1/delivery/address.test.ts` 817) + 70 session-suite rows + 93 substrate rows + 5
>     harness (the `fullArgvFile` wire-pin knob) − 2 guard — net +1,339: the new arms are the
>     full-details wire baselines, the D1 matrix incl. contradictory duplicates, the
>     unverified-increment parity pin, the counter narrowing + invalid-write matrix, the
>     order pins (submit-before-resolve argv; record-before-decision full event traces;
>     report-before-drive), the resolve `--batch` wire pin (flag adjacency + exact staged
>     rows), the throwing-run-id-read abort pins (feature + adapter), the notes-on-failure
>     regression, the never-burn-an-attempt e2e, the both-reports pin, and the
>     session-recording failure arms.
>   - Files: +8 / −4; touched: `objectiveStack.ts`, `objectiveStackDrive.test.ts`,
>     `index.ts`, `importDirectionGuard.test.ts`, the session trio, `workflowState.ts` +
>     test, four comment re-anchors (`coldDoor.ts`, `plannotatorHandoff.ts`,
>     `stageExecution.ts`, `ready.ts`).
>   - Export ledger — **Retired**: `registerSubmit`, `registerAddress`, `submitPr`,
>     `driveConflictResolution`, `resetConflictAttempts`, `resolveReviewThreads` (+ its dead
>     standalone empty-batch arm), `SubmitResult`/`SubmitDetails`, `ResolveResult`/
>     `ResolveOk`/`ResolveFailExtras`, `FinalizeAddressOk`/`FinalizeAddressFailExtras`.
>     **Renamed**: `SubmitOk` → `PublishedChange` (with D3's field-truth fix).
>     **Relocated**: `CONFLICT_RESOLUTION_ATTEMPT_CAP`, `ThreadInput`/`ThreadResultRow`,
>     `decodeResolveParams`, `executeClassifyReviewFeedback` + result types,
>     `addressGuidance`, `conflictResolutionGuidance`. **Newly introduced**: `PublishChange`/
>     `PublishAttempt`, `ConflictAttempts`, `ConflictFollowUp`, `PublishDeps`,
>     `SubmitChangeOutcome`, `publishVerified`, `decideConflictFollowUp`, `submitChange`,
>     `ResolveThreads`/`ResolveThreadsAttempt`, `AddressFinalization`, `FinalizeAddressDeps`/
>     `FinalizeAddressOutcome`, `finalizeAddress`, `installSubmitBindings`/
>     `installAddressBindings`, `publishDepsFor` (carrying the lazy `readRunId` port),
>     `renderPublishedMessage`, `driveConflictFollowUp`,
>     `conflictResolutionAttempts`/`setConflictAttempts` (substrate), `ReviewBatchRecord`/
>     `ReviewBatchCounts` + the `record-review-batch` variant (session). Module-private by
>     review: `createChangePublisher` + `conflictAttemptsFor` (every production consumer
>     composes through `publishDepsFor` — the one-composition invariant is structural), the
>     ThreadFate type, and the completed outcome no longer carries the applied
>     `ReviewBatchRecord` (no production reader — the memory observer is the test seam).
>     Every added export has a production importer or is a frozen-baseline/exported-core test
>     surface.
>   - Deletion test: gutting the two feature modules hollows both installers — ordering,
>     atomicity, corroboration, retry derivation, the bounded decision, reset-on-clean,
>     pointer ordering, and verified-success recording all vanish, leaving registration +
>     decode + render shells. Verified by the import graph (both installers import the ops,
>     the unions, and the ports).
> - **Dogfood (Step-8 protocol)**: live proof #1 observed (2026-08-31): this layer's own
>   publication rode the MIGRATED `pi/v1/delivery/submit.ts` — a fresh headless session
>   (`pi --mode json -p`, env-leak guard applied, extension loaded from this worktree at
>   `32e1a185`) invoked the REGISTERED `submit` tool, which opened draft PR #2123
>   ("Opened draft PR #2123 → …/pull/2123 (plan embedded) (stack #2093, layer 13/13)",
>   `base: "plan-2116"`, `mergeable: true`) — and the details carried `issue: "2122"` as the
>   opaque STRING id: D3 observed live (the retired decode dropped the field). The final-head
>   re-publish rides the implementing session's terminating `submit` tool — that session's
>   in-memory binding predates the migration (loaded at session start; a warm session cannot
>   reload itself), which is exactly the byte-parity the wire baselines pin; the migrated
>   binding's live publication is proof #1 above. Live proof #2 (2026-08-31, the
>   review-address pass on PR #2123's 13-thread multi-angle review): the post-address final
>   head was re-published through the MIGRATED submit binding from a second fresh headless
>   session — Step 8.4 satisfied on the migrated door. The address loop itself
>   (classify → fix → finalize) ran live end-to-end in the implementing session, whose
>   in-memory bindings predate the migration (byte-parity-pinned by the wire baselines); a
>   live observation of the migrated `pi/v1/delivery/address.ts` bindings stays honestly
>   unclaimed — it rides a future address pass from a fresh session (or the 7.5 full-phase
>   dogfood). The PR-body accounting-ledger append + read-back (Step 8.5) was performed in
>   the address pass after the final-head submit; the terminating `finalize_address`
>   re-publish that closes the pass regenerates the body (the plan's named residual —
>   re-append rides the next gesture; this committed note is the durable ledger copy). The
>   full Phase-7 dogfood gate closes at 7.5.

> **Status (Objective #2083, Node 7.3):** slice 5 landed — the ready + handoff transitions
> (`ready`, `/ready`, and the ready-time reconcile continuation, contracts.md §8.66) —
> realized-shape notes:
>
> - **Behavior moved**: `doors/ready.ts` wholesale, behind the Pi-free feature op
>   `extension/delivery/ready.ts::readyChange` (one entry: the exterior effect first, then the
>   exhaustive route classification, then — on the stamped-with-cohort path ONLY — the
>   continuation decision) with the named installer `pi/v1/delivery/ready.ts`
>   (`installReadyBindings` + the exported `driveReadyContinuation` translation).
>   `doors/ready.ts` + `doors/ready.test.ts` deleted whole in the same node (Rule E burn-down).
>   Registration surfaces frozen-baseline pinned byte-identical; every load-bearing arm carries
>   a full-details WIRE baseline captured from the OLD door pre-deletion (byte-exact
>   `assert.deepEqual` on the JSON round-trip, optional-key absence semantics included —
>   verified byte-identical against the pre-migration capture before the suites were written).
>   Message/warning texts byte-identical; SHA-bound ready semantics untouched (no warm `stale`
>   arm — a cascade-staled stamp is repaired Python-side by re-running ready).
> - **Correlated facts + mint-only evidence (the named invariants)**: the `ReadyFacts` union
>   (`incremental` with `stacked` false-vs-absent preserved for the wire /
>   `stacked_unverified` / `stacked`) makes a cohort without the stacked routing fact — or a
>   dropped cohort masquerading as incremental — unrepresentable, and each `ReadyOutcome` arm
>   is constrained to its matching variant (compile-time-negative pinned). The drive arm
>   carries ONLY the nominal `ReadyDriveEvidence` (an unexported class with a `#private` field;
>   type-only export — the WorkerModelSelection precedent), minted by `readyChange` from the
>   SAME facts value the arm carries, strictly after the strict evidence vocabulary passed
>   (`^[A-Za-z0-9._-]{1,64}$` ids; `^[0-9a-f]{40}$` both endpoints; integer PR). The arm order
>   is pinned: gate refusal BEFORE evidence validation (today's order); `retryPlan` carries the
>   safe-interpolation policy (`null` ⇒ the `<plan>` placeholder).
> - **Action-specific port, one production composition**: `MarkReady` (production =
>   `createReadyMarker` — the `perk pr ready --json` cold-door composition; module-private,
>   composed only through the module-private `readyDepsFor`); the gate read is the injected
>   `sessionReadOnly` capability, read ONLY on the stamped-with-cohort path (the three negative
>   arms are throwing-sentinel pinned). No WorkflowSession writes exist on this path and none
>   were added. `driveReadyContinuation` is exhaustive over the outcome AND the nested
>   continuation with `never` checks (no catch-all default — union growth breaks the adapter
>   at typecheck time); it stays exported solely because the streaming `followUp` branch is
>   unreachable through the idle harness (its production importer is the installer itself).
>   `readyDepsFor`/`renderReadyMessage`/`createReadyMarker` and the details builder are
>   module-private (review-settled; composed behavior proven through the registered bindings
>   via `spyInjections`).
> - **Accounting ledger** (final numbers; operator acceptance rides the PR-approval gesture —
>   the 7.1/6.3 named-invariant escape hatch):
>   - Production LOC (recomputed after the review-address pass): 281 deleted
>     (`doors/ready.ts`) → 515 added (`delivery/ready.ts` 193, `pi/v1/delivery/ready.ts` 322);
>     whole-change production net **+234** against the plan's ~+110 estimate and its ~+150
>     re-examination bar — re-examined before submit: the excess is the two named invariant
>     classes, not padding — (1) the correlated facts variants + their outcome-arm constraints
>     + the mint-only nominal evidence class (three variant interfaces, the `#private` brand,
>     the double never-checked exhaustive switches); (2) the `MarkReady` port + the
>     wire-identical details rebuild the split itself requires (the door built details
>     implicitly from one decode shape). Zero new policy surface; comment-carried intent
>     preserved per AGENTS.
>   - Test LOC (recomputed): 492 deleted (`doors/ready.test.ts`) → 825 added
>     (`delivery/ready.test.ts` 269, `pi/v1/delivery/ready.test.ts` 556) — net +333: the new
>     arms are the feature-tier fake-deps suite (ordering, the three throwing-sentinel gate
>     pins, gate-before-evidence, the relocated INVALID_EVIDENCE matrix with per-row retryPlan,
>     evidence minting + the post-mint mutation-immunity pin, the compile-time negatives), the
>     frozen registration baselines, the full-details wire baselines incl. the six-field
>     cohort-drop matrix and BOTH incremental forms (the legacy absent-`stacked` form and the
>     current worker's explicit `stacked: false` + null-cohort form), the
>     `["pr","ready","--json"]` argv pin, the exact refusal-warning bytes through registered
>     surfaces (the read-only arm via a read-only-scaffolded `/ready` — exactly production's
>     gesture), the full-cohort integration pin (ONE injected drive with the pinned range +
>     binding suffix), and the report-before-drive order pin.
>   - **Review-address hardening (PR #2125)**: `ReadyDriveEvidence` snapshots the validated
>     PRIMITIVES at mint time instead of retaining the caller-reachable `ReadyHandoff` object
>     — post-validation mutation of `facts.handoff` can no longer reach the drive render
>     (aliasing closed; mutation-immunity pinned in the feature suite).
>   - **Declined simplifications (recorded, from the ponytail lane)**: (a) deleting
>     `ReadyDriveEvidence` and driving from the stamped facts — declined: the mint-only
>     nominal evidence IS the plan-settled resolution of the validated-drive invariant (the
>     stamped facts carry the RAW decoded cohort, not proof of validation; the snapshot
>     hardening above strengthens exactly this boundary); (b) collapsing `ReadyOutcome.kind`
>     into `facts.route` — declined: the outcome vocabulary names transition outcomes (incl.
>     `failed`, which has no facts route) while the route names the wire's routing facts; the
>     plan settled the honest-arm vocabulary, and `readyChange`'s classification switch is the
>     ONE conversion point.
>   - Files: +4 / −2; touched: `index.ts`, `importDirectionGuard.test.ts` (census burn-down),
>     `pi/v1/objective.ts` (comment re-anchor), `substrate/stageTools.test.ts` (DRIVE_COVERAGE
>     label + comment), `shared/contracts.md` (two re-anchors, no behavior amendment),
>     `prose-prompt-map.yaml` + regenerated `prose-prompt-map.md`,
>     `first-principles/python-cli-guidelines.md` (one additional stale anchor found in
>     implementation), this note.
>   - Export ledger — **Retired**: `registerReady`, `markReady`, `driveReadyReconcile`,
>     `ReadyResult`, `ReadyDetails`, the `ReadyOk` name (no compatibility re-exports).
>     **Relocated**: `ReadyHandoff` (verbatim). **Newly introduced**: `ReadyPr`, `ReadyFacts`,
>     `MarkReady`, `MarkReadyAttempt`, `ReadyDeps`, `ReadyOutcome`, `ReadyContinuation`,
>     `ReadyDriveEvidence` (type-only), `readyChange` (feature); `installReadyBindings`,
>     `driveReadyContinuation` (adapter). Every added export has a production importer or is
>     the one exported-core test seam.
>   - Deletion test: gutting `delivery/ready.ts` hollows the installer — outcome
>     classification, the SHA-bound evidence verification, evidence minting, the gate-refusal
>     ordering, the safe-retry policy, and the session-transition decision all vanish, leaving
>     registration + decode + render shells that can decide nothing. Verified by the import
>     graph (the installer imports the op, the unions, and the port).
> - **Live-proof closeout protocol** (review-settled — no new gate, no waiver; the Phase-4/5
>   evidence-only-commit precedent): (1) implementation lands; review + address complete; the
>   final head is published via `/submit`. (2) The human runs `perk ready <plan>` from a fresh
>   session in the train worktree — the MIGRATED binding performs the stamp + reconcile drive:
>   that is the recorded live observation (session id, observed stamp facts, the drive entry),
>   bound to that intermediate published head (intermediate-head proof explicitly acceptable).
>   (3) The observation lands as ONE docs-only evidence commit appended to this note. (4) The
>   tip's handoff stamp is re-run (`perk ready <plan>` again) — the idempotent re-stamp
>   converges on the new head and re-enters the reconcile pass; this protocol statement is the
>   recording, so the re-stamp needs no further evidence. The layer cannot finish with
>   uncommitted evidence or a stale stamp; the definitive `run_ci` remains the pre-submit one.
>   The full Phase-7 dogfood gate closes at 7.5.

> **Update (Objective #2130, Node 1.1, 2026-09-02):** the live-proof closeout protocol
> above was never executed — its arms were bound to the pre-land #2083 train, which
> landed (and #2083 closed) before any arm ran; no evidence append exists. The closeout
> is closed via the Phase-7 record at
> `docs/design/archive/ts-decomposition-phase7-dogfood.md`: its equivalent fresh leg
> exercises the same migrated binding — the warm in-session `/ready` on objective #2130
> node 1.1's plan (leg C there). Surface correction, recorded honestly: the protocol's
> step 2 names `perk ready <plan>`, but the migrated binding
> (`pi/v1/delivery/ready.ts::installReadyBindings`) is the warm in-session `ready` tool +
> `/ready` command; the cold `perk ready` CLI is the Python continuation wrapper
> (`src/perk/cli/commands/pr/ready_cmd.py` — worker mechanics plus the launch of the
> ready-time reconcile session, whose in-session drive, `driveReadyContinuation`, is
> adapter code). A live leg for the migrated binding therefore uses the warm `/ready`.

> **Status (Objective #2083, Node 7.4):** slice 6 landed — the delivery train-operation family
> + per-plan land (`objective_stack_sync`/`adopt`/`recover`/`land`, `/objective-sync`/
> `/objective-recover`/`/objective-land`, the §8.56 reconcile drive, the §8.51 sync-conflict
> resolver dispatch, and `land`/`/land`) — realized-shape notes:
>
> - **Behavior moved**: `doors/objectiveStack.ts` (1,305) and `doors/land.ts` (252) deleted
>   whole in the same node (Rule E burn-down; no forwarding exports). The stack family split
>   into two Pi-free feature ops — `delivery/stackConflict.ts` (the §8.51 warm conflict state
>   machine: `corroborateSyncConflict` moved intact + the ordered `decideSyncResolution`
>   pipeline over injected read/claim/attempts ports) and `delivery/stackReconcile.ts` (the
>   §8.56 evidence decision, mint-only) — under four named installers in `pi/v1/delivery/`
>   (`stackSync.ts`, `stackRecover.ts`, `stackLand.ts`, the shared `stackDrive.ts`
>   render/registrar helpers). Per-plan land migrated **adapter-only**
>   (`pi/v1/delivery/land.ts` — the stack-status zero-policy precedent; the operator-settled
>   scope). Registration surfaces frozen-baseline pinned byte-identical (five tools + four
>   commands, complete `deepEqual`); the representative full-details wire baselines were
>   captured from the OLD doors pre-deletion and verified byte-identical against the migrated
>   bindings before the new suites were written (the 7.3 ritual; the capture script is
>   re-runnable).
> - **Named behavior deltas (D1–D6; contracts amended in the same change)**: **D1** (the one
>   ordinary-path change, operator-approved) — the conflict-resolver dispatch on BOTH warm
>   surfaces now rides the ONE shared `inspectConflictBudget` cap read + each consumer's
>   strict verified `attempts.write`, and an unverified counter increment
>   (strict read-back `false`) WITHHOLDS the dispatch with a loud report instead of driving
>   (§8.3's surface-uniform withhold posture; the submit/address throwing-read arm stays
>   load-bearing). **D2** — cross-plane: `ContinuationOut.targets_contained` (Python,
>   canonical `validated_targets` containment, fail-closed tolerant compute) is now a warm
>   dispatch-eligibility requirement (`true` or no dispatch — absent means an older cold CLI
>   and fails closed with a remediation-naming reason). **D3** — `/land`'s pending-learn
>   marker write is guarded: a caught fs failure degrades to a loud run-`/learn` warning line;
>   the verified land result and its reconcile drive stand. **D4** — the land advisory
>   sub-objects decode three-state (absent/malformed/present); malformed drops from details
>   but warns loudly (exact UNVERIFIED bytes pinned), and the after-land drive additionally
>   gates the objective id on the marker-safe vocabulary. **D5** — `decideSyncResolution` has
>   a total exception boundary: every thrown port failure translates to the typed
>   `state_error` arm (`conflict-dispatch state failure:` prefix) with
>   release-on-throw-after-acquisition; the outcome union is closed and honest. **D6** — the
>   reconcile evidence is minted into a nominal `StackReconcileEvidence` snapshot
>   (`#private` brand, frozen rows; post-decision payload mutation cannot reach the render):
>   PR renders only as a positive safe integer, the objective url only as an unrepaired
>   credential-free https reconstruction (`href === raw`), else `?`/`""`.
> - **Accounting ledger** (final numbers; operator acceptance rides the PR-approval gesture —
>   the 7.1–7.3 named-invariant escape hatch):
>   - Production TS LOC (recomputed after the review-address pass): 1,557 deleted → 1,999
>     added in new files (`delivery/stackConflict.ts` 363, `delivery/stackReconcile.ts` 165;
>     adapters: `stackSync.ts` 549, `stackRecover.ts` 265, `stackLand.ts` 223, `stackDrive.ts`
>     120, `land.ts` 314) + amendments net +45
>     (`delivery/submit.ts` +24, `pi/v1/delivery/submit.ts` +14, `index.ts` +7,
>     `stackStatus.ts` ±0) — whole-change production net **+487** against the plan's ≤ +300
>     bar. Re-examined before submit: the excess is the four named invariant classes, not
>     padding — (1) the typed dispatch pipeline (the closed `SyncResolutionOutcome` union, the
>     three injected ports, the token-fenced withhold-and-release, D1/D5's
>     withhold/total-boundary arms) replacing the door's inline best-effort dispatch core;
>     (2) the mint-only sanitized evidence class + D2/D6's gates (the door sanitized inline at
>     render time with no mint boundary); (3) the shared budget inspect + the strict
>     verified-write discipline at its two consumers; (4) the split's explicit wire-identical
>     details rebuilds + the
>     render/argv/decode separation the door built implicitly from one decode shape. Offsets
>     banked as planned: the land feature layer dropped (adapter-only), the `findingLines`
>     door copy consolidated into the `stackStatus.ts` export, three command registrations
>     collapsed into `registerStackDrivingCommand`, representative-not-exhaustive goldens.
>     Python production: +26 (`status_cmd.py` — D2). Zero new policy surface; comment-carried
>     intent preserved per AGENTS.
>   - Test LOC (recomputed): 2,271 deleted (`doors/objectiveStack.test.ts` 1,162,
>     `doors/objectiveStackDrive.test.ts` 618, `doors/land.test.ts` 491) → 3,300 added in new
>     suites (`stackConflict.test.ts` 504, `stackReconcile.test.ts` 207, `stackSync.test.ts`
>     921, `stackRecover.test.ts` 451, `stackLand.test.ts` 460, `stackDrive.test.ts` 225,
>     `land.test.ts` 532) + amendments +104 (`delivery/submit.test.ts` +24 D1 flip,
>     `pi/v1/delivery/submit.test.ts` +47 + `address.test.ts` +37 e2e withheld pins,
>     `stageTools.test.ts` −2 repoint, `importDirectionGuard.test.ts` −2 census) — TS net
>     +1,133: the new arms are the feature-tier port suites (ordering trace, cap boundaries,
>     withhold-and-release, the D5 throwing matrix, the D6 URL/PR mint matrix, snapshot
>     immunity + compile-time negatives), the frozen registration + representative wire
>     baselines, the D1/D3/D4 changed-arm baselines captured new, and the option-shaped-id
>     refusal arms. Python tests: +80
>     (`test_objective_stack_cmd.py` — the three D2 arms + the unparseable-row assertion).
>   - Files: +7 production TS, +7 test suites; −5 (2 doors + 3 door suites); 1 Python
>     production file amended.
>   - Export ledger — **Retired**: `registerObjectiveStack`, `registerLand`,
>     `dispatchSyncResolver`/`driveSyncConflictResolution` (reshaped into
>     `decideSyncResolution` + the adapter's `runSyncResolution` translation), `StackResult`
>     (door shape), `LandResult`/`LandDetails`/`LandOk` (door shapes), and `landPr`
>     (privatized — the handler core survives module-private in `pi/v1/delivery/land.ts`,
>     proven through the registered tool) — no compatibility re-exports.
>     **Relocated**: the renders (`renderSyncOutcome`/`renderRecoverOutcome`/
>     `renderLandOutcome` + `withSyncNotes` module-private), the module-private envelope
>     decode helpers (the sync/adopt/recover/stack-land decodes and per-plan land's
>     `decodeLand`/`decodeObjective`/`decodeLearn`, each into its adapter module — land's
>     advisory pair reshaped three-state per D4), the argv builders
>     (`buildStackSyncArgs`/`buildStackAdoptArgs`/`buildStackRecoverArgs`/
>     `buildStackLandArgs`), the guidance renderers (`objectiveSyncGuidance`/
>     `objectiveRecoverGuidance`/`objectiveLandGuidance`/`syncConflictResolutionGuidance`),
>     `corroborateSyncConflict`, `SyncConflictDispatch`, `SyncMode`,
>     `ObjectiveLandUpdate`/`LearnConsumeUpdate`, `driveReconcileAfterLand`,
>     `driveStackReconcile` (→ `stackDrive.ts`, evidence-typed), `evidenceLines` +
>     `findingLines` (named adapter exports). **Newly introduced**:
>     `ConflictBudget`/`inspectConflictBudget` + the `withheld` arm
>     (feature, shared); `SyncResolutionOutcome`/`SyncResolutionDeps`/`ResolverClaim`/
>     `decideSyncResolution`/`autoDispatchEligible`/`settleSyncEpisode` (feature);
>     `decideStackReconcile` + `StackReconcileEvidence` (type-only) +
>     `StackReconcileEvidenceRow`/`StackReconcileDecision` (feature);
>     `registerStackDrivingCommand` (adapter); the four installers
>     (`installStackSyncBindings`/`installStackRecoverBindings`/`installStackLandBindings`/
>     `installLandBindings`); `runSyncResolution` (adapter — the offline followUp arm's test
>     seam + the installer's own production importer); `ContinuationOut.targets_contained`
>     (Python). Every added export has a production importer or a
>     frozen-baseline/exported-core test role.
>   - Deletion test: gutting `delivery/stackConflict.ts` + `delivery/stackReconcile.ts`
>     hollows the stack installers — corroboration, dispatch eligibility, the budget/claim
>     pipeline, episode settlement, and the evidence gate + mint all vanish, leaving
>     registration + decode + render shells that can decide nothing (the per-plan land
>     adapter intentionally carries zero migrated policy — the decision content lives in the
>     cold plane). Verified by the import graph (the installers import the ops, the unions,
>     and the ports).
>   - **Review-address hardening (PR #2127)**: the three PR-new id vocabularies
>     (`stackConflict.ts::ID_RE`, `stackReconcile.ts::EVIDENCE_ID_RE`,
>     `land.ts::OBJECTIVE_ID_RE`) and `BRANCH_RE` became alphanumeric-first — ids/branches
>     reach unquoted CLI-argument positions in injected guidance/dispatch text, so an
>     option-shaped `-`-leading value (e.g. `--help`) is now out of vocabulary (refusal arms
>     pinned). The three negative D2 containment tests were repaired to use a canonical ULID
>     (the fixture id's Crockford-invalid `O` made them vacuous — the ULID check
>     short-circuited before the path/symlink arms). `commitConflictAttempt` (a policy-free
>     pass-through) was inlined as each consumer's direct `attempts.write`; the unused
>     `objectiveArgErr` registrar option was deleted.
>   - **Declined simplifications (recorded, from the ponytail lane)**: replacing
>     `StackReconcileEvidence` (the nominal `#private`-branded, frozen mint) with a plain
>     readonly object — declined: the mint-only nominal evidence IS the plan-settled D6
>     resolution (the 7.3 `ReadyDriveEvidence` precedent — the exported `driveStackReconcile`
>     structurally cannot receive unsanitized evidence, where a structural type would accept
>     any forged object; the freeze is the snapshot-immunity half, pinned in the feature
>     suite).
> - **Live-proof closeout protocol** (plan-settled — the 7.3 shape): (1) implementation lands;
>   review + address complete; the final head is published via `/submit`. (2) From a fresh
>   session in the train worktree on the final head, run `/objective-stack 2083`,
>   `objective_stack_sync {dry_run: true}`, `objective_stack_recover {dry_run: true}`, and
>   `objective_stack_land {dry_run: true}` through the MIGRATED bindings against the real
>   train; record the session id + observed renders as ONE docs-only evidence commit appended
>   to this note. (3) Re-run the tip's handoff stamp. The mutating arms carry the wire
>   baselines, and the objective's own eventual recover/land runs through these migrated
>   bindings by construction — stated honestly. The full Phase-7 dogfood gate closes at 7.5.

> **Update (Objective #2130, Node 1.1, 2026-09-02):** the live-proof closeout protocol
> above was never executed — its arms were bound to the pre-land #2083 train, which
> landed (and #2083 closed) before any arm ran. The closeout is closed via the Phase-7
> record at `docs/design/archive/ts-decomposition-phase7-dogfood.md`: its equivalent
> fresh legs exercise the same migrated stack-family bindings on objective #2130's own
> train — `/objective-stack 2130`, `objective_stack_sync {dry_run: true}` then
> `{base: true}` (the real base-absorbing sync; a no-op outcome is still a live
> exercise), `objective_stack_recover {dry_run: true}`, and `objective_stack_land`
> `{dry_run: true}` — recorded there as leg E.

> **Status (Objective #2083, Node 7.5):** slice 7 implementation landed — `/commit-and-compact`
> migrated behind a typed delivery operation; the LAST delivery door deleted; the closing sweep
> recorded. The Phase-7 dogfood gate AND the objective's closing gate close AT this node but are
> **NOT YET CLOSED at this writing**: closure happens only when the ordered closeout protocol
> below completes (NO waiver) — its arms, the Phase-7 dogfood record, and arm D's observed bytes
> land as the closeout's docs-only commits appended to this note, and the ledger below (measured
> at the implementation head) re-measures at the actual final head if any train head moves.
> Realized-shape notes:
>
> - **Behavior moved**: `doors/commitCompact.ts` (250) + its suite (507) deleted whole in the
>   same node (the last Rule E delivery-door burn-down; no forwarding exports —
>   `CommitCompactIo` and its `Severity` edge retired outright, no compatibility shape). The
>   policy tier became the Pi-free feature op `extension/delivery/commitCompact.ts`
>   (`startCommitAndCompact`/`settleCommitAndCompact` over the closed
>   `CommitCompactStart`/`CommitCompactSettle` unions and the observations-only
>   `CommitCompactDeps` — the read-only gate rides a plain parameter; the invocation arm order,
>   fail-safe posture, observation ordering, pending mint, and settle gate all live here) under
>   the named installer `pi/v1/delivery/commitCompact.ts` (`installCommitCompactBindings` — the
>   `installReadyBindings` shape) at the SAME `index.ts` call position (after
>   `installObjectiveBindings`, whose `agent_settled` handler must register first). Command
>   registration metadata frozen-baseline pinned (deepEqual; description byte-identical; a
>   command-only door has no tool-JSON wire, so the baselines are registration metadata + text
>   byte pins — stated honestly); all SIX report messages byte-identical; both `prompts/`
>   templates, `prompts/_fixtures/live.yaml`, `tests/test_prompt_parity.py`, and `toolGating.ts`
>   byte-untouched. Pending-record discipline (review-hardened): EVERY invocation supersedes
>   the one-shot slot up front (a stale baseline never survives a clean/read-only/skip/failed
>   reinvocation into a later settle), and the drive arm re-arms it ONLY after the guidance
>   send — a throwing send leaves the slot unset (phantom-record + supersession pins).
> - **Named interior behavior deltas (warm-plane only — no contracts section exists for this
>   door, so NO `shared/contracts.md` amendment; below the user-docs surface)**:
>   - **D1 — discriminated HEAD baseline (fail-safe closure)**: the pending record now carries
>     `HeadBaseline` = `sha | unborn | unprovable` instead of `headSha`'s conflated null. The
>     production probe (module-private in the installer, over `substrate/git.ts`, fail-open):
>     `rev-parse HEAD` ok → `sha`; else `unborn` ONLY on the new
>     `substrate/git.ts::unbornHead` positive absence proof (`symbolic-ref -q HEAD` resolves AND
>     `for-each-ref` proves the pointed-to ref absent — exit-0, empty output; review-hardened: a
>     resolvable pointer whose ref EXISTS is a transient read failure, never unborn); else
>     `unprovable`. An
>     `unprovable` baseline still DRIVES the commit (committing is always safe) but the settle
>     arm SKIPS compaction with ONE new recorded warning ("the pre-commit HEAD could not be
>     captured — compaction skipped; run /compact to compact anyway."). Regression pins: the
>     start-unreadable/settle-readable case skips (through the registered paths, via a
>     malformed-`.git/HEAD` scratch repo); the true unborn arm still compacts on the first
>     commit.
>   - **D2 — trust-fenced committed-arm compaction instructions**: `compactInstructions` now
>     fences the raw `git log --oneline` listing (repository-controlled text) in the same
>     `<commit-evidence>` + untrusted-DATA demotion framing the continuation template uses, with
>     fence-delimiter neutralization (review-hardened: `fenceSafe` escapes `commit-evidence>`
>     tag text inside the listing at BOTH prose sites — the instructions and the continuation
>     render — so a closing-tag commit subject cannot escape the fence) — the committed-arm
>     instruction bytes changed (recorded); every other instruction/report/continuation surface
>     is byte-identical apart from the escaping. Pinned with hostile commit-subject + closing-tag
>     injection assertions, observed as exact `customInstructions` bytes through the
>     deferCompaction seam — no test-only export.
>   - **Narrowed safety claim (behavior-preserving, now stated honestly)**: the settle gate
>     proves a NEW COMMIT (HEAD movement as range evidence), NOT end-state cleanliness — a
>     commit that leaves the tree dirty still compacts BY DESIGN (regression-pinned); no
>     ancestry check added.
> - **Prose home**: adapter-side — the feature returns typed decisions carrying data only.
>   Exactly two prose exports remain (`commitAndCompactGuidance`,
>   `commitAndCompactContinuation`), exported SOLELY because `stageTools.test.ts`
>   DRIVE_COVERAGE (a production-guard census) imports them — recorded as guard seams.
>   `DIRECT_COMPACT_INSTRUCTIONS`, `compactInstructions`, and `activeSessionPlanRef` went
>   module-private (`activeSessionPlanRef` relocated verbatim: session-tier authority, full
>   shape validation, fail-open null, NO worktree-cache fallback — proven through registered
>   paths: valid linkage → targeted continuation; per-field LWW; cache-ref-only → generic;
>   malformed → generic; throwing branch read → generic). Prose map re-keyed (`ts-session` → the adapter path; both
>   `module:sendUserMessage` units, indices 0/1) and regenerated.
> - **Accounting** (vs predecessor head `5fc3eb45`, numstat): production net **+85** — the
>   planned migration measured **+57** at review time (under the +60 hard bar); the review pass
>   then mandated **+28** of hardening squarely inside the three named invariant classes (the
>   typed outcome unions' exhaustive settle translation; D1's positive unborn proof +
>   supersession discipline; D2's fence-delimiter escaping) — cutting reviewer-required
>   fail-safe code to fit the bar would game the metric, so the overage is REPORTED, not hidden;
>   operator acceptance rides the PR-approval gesture. Detail: door −250; feature +93; adapter
>   +218; `substrate/git.ts` +26 (`unbornHead`); sweep/index ±1s. Test net **+670** (door suite
>   −507; feature suite +225 — recording fakes, zero-git-read sentinels, the full D1 settle
>   matrix, compile-time negatives; adapter suite +932 — registered paths over a REAL bound
>   AgentSession with real `agent_settled` emission through the extension runner, incl. the
>   supersession, settle-containment, and fence-injection regressions). Files: production
>   +2/−1, tests +2/−1.
> - **Export ledger**: **removed** — `registerCommitAndCompact`, `CommitCompactIo` (+ the
>   `Severity` edge), the door's exported `activeSessionPlanRef`, `DIRECT_COMPACT_INSTRUCTIONS`,
>   `compactInstructions`, `PendingCompact`(door shape). **Newly introduced** — `HeadBaseline`,
>   `PendingCompact` (baseline-shaped), `CommitCompactCompletion`, `CommitCompactDeps`,
>   `CommitCompactStart`, `CommitCompactSettle`, `startCommitAndCompact`,
>   `settleCommitAndCompact` (feature); `installCommitCompactBindings` (adapter);
>   `substrate/git.ts::unbornHead` (production-consumed by the installer's probe).
>   **Relocated** — `commitAndCompactGuidance` + `commitAndCompactContinuation` (door →
>   adapter; guard seams). **Privatized (sweep)** — `substrate/git.ts::indexHidesChanges`
>   (`revalidationBracket`'s default flags probe is the one consumer; its direct test rows
>   re-routed through the bracket — real-repo assume-unchanged arm added, the null arm already
>   rode the `probes` seam), `doors/pendingWave.ts::WAVE_COLLECT_GRACE_MS` (tests re-anchored on
>   `collectGraceMs()` + the `PERK_WAVE_COLLECT_GRACE_MS` env knob),
>   `doors/plannotatorHandoff.ts::pickFreePort` (internal default; the injectable
>   `deps.pickFreePort` hook untouched). Every added export has a production importer or a
>   recorded guard-seam role.
> - **Sweep dispositions (kept + recorded, no churn)**: `substrate/coldDoor.ts::activeRunId`
>   KEPT untouched — live production behavior (`runColdDoor`'s stdin staging), a
>   `shared/contracts.md`-anchored name, and a documented deliberate export
>   (`docs/learned/workflow/cold-door-client.md`); recorded as a deliberate seam. Also kept:
>   the signature-participating contract types (`ColdDoorOpts`, `ExecHost`, `LaunchVia`,
>   `LaunchRequest`, `ConsoleErrorSink`, `ConsoleErrorInterceptor`, `AgentScratchBlock`,
>   `PendingWave`) and the deliberate test seams / Phase-8 residue (`resolveTerminalLaunch`,
>   `resolveClipboardScript`, `respondMessage`, `PLANNOTATOR_REVIEW_COMMAND`, the
>   readiness-probe constants/paths, the agentScratch helpers, the prior-node exported-core
>   seams across `pi/`).
> - **Observed drift, reconciled**: the opt-in prose-plane census pin
>   (`tools/prose-map/selector.test.ts` candidate count) was STALE at implementation start —
>   pinned 98 while the true census was 96 (node 7.4's door deletions removed 9 model-call
>   units and added 7, net −2, without running the opt-in suites). This node is count-neutral
>   (2 door units out, 2 adapter units in); the pin was reconciled to 96 here
>   (test-pin-sweep discipline).
> - **Final structural ledger** (measured at this node's head; selectors pinned: production =
>   `extension/**/*.ts` minus `*.test.ts` minus `testing/`, `vendor/` split out; edges =
>   `from "."`-relative import lines; Pi importers = `@earendil-works` import declarations):
>   - Production: **136 files / 42,376 LOC** incl. `vendor/` (133 / 40,687 excl.; vendor = 3
>     files / 1,689). Tests: **143 files / 67,541 LOC**. Vs the 1.1 baseline (102 files /
>     ~38,100): +34 files / +~4,200 LOC — the honest narrative: the decomposition ADDED
>     structure (feature ops + adapters + the session/authoring/codeReview/learning/delivery
>     homes) while deleting every delivery door; the growth is typed seams and guard census
>     surface, not duplicated policy.
>   - Import edges: **629** relative-import lines (628 at plan time; the door's 8 became the
>     feature's 0 + the adapter's 9). Cycles: **ZERO** (guard-enforced, `KNOWN_CYCLES` empty).
>   - Pi importers: **52** — the expected importer-neutral move (the deleted door's Pi import
>     replaced by the new adapter's).
>   - Registrations vs the inventory headline, location-shifted not grown: 36 `registerTool`
>     (after 5.2's `/pr-review-dynamic` retirement) + 26 `registerPerkCommand` call sites (+1
>     definition site in `substrate/command.ts`) + 2 `registerCommand` + 2 flags + 1 shortcut
>     + 33 `pi.on` sites (+1 comment mention).
>   - Remaining legacy modules, complete — the 7 surviving `doors/` modules:
>     `draftReviewWaveTools` (draft-review wave tools — the plannotator draft-review lanes),
>     `lifecycleGates` (session lifecycle fork/switch gates + dirty-repo guard),
>     `objectiveReviewBrowser` (the objective-draft review browser door), `pendingWave` (the
>     shared pending-wave state + collect race), `plannotatorHandoff` (the plannotator
>     browser-handoff mechanics), `planReviewBrowser` (the plan-draft review browser door),
>     `selfcheck` (the session-wiring verifier). Post-burn-down Rule E census residue (12
>     entries): the five door registrants (`draftReviewWaveTools`, `lifecycleGates`,
>     `objectiveReviewBrowser`, `planReviewBrowser`, `selfcheck` — `pendingWave` +
>     `plannotatorHandoff` carry no registration tokens), `substrate/agentScratch.ts` (scratch
>     provisioning + its flag), `substrate/bindingDelivery.ts` (Mechanism A injection),
>     `substrate/command.ts` (the `registerPerkCommand` definition site),
>     `substrate/toolGating.ts` (the gate's `before_agent_start` hook), `surfaces/surfaces.ts`
>     (the sanctioned rich-UI module's entry renderers), `vendor/btw/btw.ts` +
>     `vendor/whimsical/whimsical.ts` (borrowed packages, the named exception).
> - **Recorded deferrals**: Phase 8 — application-host adapters; migrating the 7 surviving
>   doors + the browser/wave mechanisms behind typed operations. The kept deliberate seams
>   (sweep items above). The ONE remaining full-branch `branchCarries` consumer —
>   `substrate/toolGating.ts` (the learned doc `pi/context-injection.md` overstates the
>   residue; reconciling it rides `/learn`, not this node). The 7.3 + 7.4 live-proof closeouts
>   were PENDING at this node's implementation start (their docs-only evidence commits are not
>   yet on the train) — surfaced to the operator; each rides its own node's protocol before
>   this node's gate closes.
> - **Ordered closeout protocol** (the definitive Phase-7 + objective gate — NO waiver; each
>   arm from a fresh session in the train worktree on the migrated head; session ids +
>   observed renders recorded; if ANY train head changes after step 3, steps 3–5 re-run on the
>   new head — the "definitive" labels attach to the LAST run): (1) implementation lands;
>   review + address complete; interim publications ride `/submit`. (2) **Arm E FIRST** — the
>   final base-absorbing sync: warm `objective_stack_sync` `{objective: "2083", dry_run: true}`
>   preview then `{objective: "2083", base: true}` through the MIGRATED stackSync binding (a
>   bare no-base sync does NOT satisfy this arm). (3) **Docs tail + arm D** — with the drafted
>   `docs/design/archive/ts-decomposition-phase7-dogfood.md` (also the objective's closing-gate
>   record) as the REAL dirty tree, a fresh session runs `/commit-and-compact` through the
>   MIGRATED binding: the driven commit IS the evidence commit; compaction + the evidence-first
>   continuation observed live; arm D's observed bytes append to THIS note as the second,
>   final docs-only commit (the docs tail is these ≤ 2 docs-only commits — no code changes, no
>   published-layer amend, no cascade). (4) **Arm A** — ONE definitive run-all `run_ci` at the
>   final head through the migrated CI binding, green. (5) **Arm B then C** — publish the
>   final head through the migrated `submit` binding from a fresh session; the human runs
>   `perk ready <this plan>` (the MIGRATED ready binding performs the SHA-bound stamp and
>   drives the §8.66 ready-time reconcile continuation; the tip re-stamp converges
>   idempotently).
> - **Deletion test (verified by the import graph)**: gutting `delivery/commitCompact.ts`
>   hollows the adapter — arm selection, the fail-safe posture, observation ordering, the D1
>   baseline discipline, the settle gate, and the pending mint all vanish, leaving
>   registration + render shells that can decide nothing (the installer's switches only
>   translate the feature's closed unions to effects).

> **Update (Objective #2130, Node 1.1, 2026-09-02):** the ordered closeout protocol's
> arms are **superseded** — the train landed (`40a30df8..a5dc757e` on `main`, the 16
> squash merges) and objective #2083 closed before any arm ran; arm E's target train and
> arm C's target plan no longer exist as written. The Phase-7 dogfood gate AND the
> objective closing gate are **closed via the record** at
> `docs/design/archive/ts-decomposition-phase7-dogfood.md`, which carries the landing
> evidence plus fresh live legs of the migrated delivery bindings re-bound to objective
> #2130 node 1.1. The leg → original-arm mapping: the record's own commit driven by
> `/commit-and-compact` (leg D) → arm D; the run-all `run_ci` at the final published head
> (leg A) → arm A; `/submit` plus the warm `/ready` on node 1.1's plan (legs B/C) → arms
> B/C; the stack sync with dry-run preview and `{base: true}` on #2130's train (leg E) →
> arm E. The final structural ledger above was re-measured at the #2130 baseline
> (`current-system-map.md` § Objective #2130 baseline) — the headline values reproduce.

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

> **Update (Objective #2130, Node 1.1, 2026-09-02):** this binding list is reworked in
> place — it is the list objective #2130 node 5.1 verifies. The deferred seams are
> removed from the binding criteria and recorded below with pointers to their one
> canonical rationale home (`module-contracts.md`); the storage-freedom criterion is
> added per `module-contracts.md` § Storage freedom.

### Architecture

- `authoring/`, `delivery/`, `codeReview/`, and `learning/` expose typed
  feature operations, not one common interface.
- There is no application kernel, global feature catalog, generic invocation,
  or universal result wrapper.
- `WorkflowSession` is authoritative for feature-facing state and artifacts
  (deepened by objective #2130 node 2.2).
- `ReportWave` exposes report assignments and opaque references, not RPC or Pi
  lanes (owed by objective #2130 node 2.1).
- Extension v1 and application facets are adapters, not domain dispatchers.
- The planning documents describe the built architecture; no contradictory
  architecture documents remain.

#### Deferred seams (recorded)

Removed from the binding list above; each owning `module-contracts.md` section
carries the one canonical rationale and re-earn condition:

- `config/` — deferred; see `module-contracts.md` § PerkConfig.
- `PromptEvidence` — deferred; see `module-contracts.md` § PromptEvidence.
- `StageRunner` — deferred; see `module-contracts.md` § StageRunner.

### Dependency direction

- Feature modules have no Pi runtime, TUI, RPC wire, raw branch, raw process,
  facet, service, value/list, Harness, lane, view, or slot dependencies.
- Feature homes are storage-free per `module-contracts.md` § Storage freedom
  (allow-listed domain I/O excepted), enforced by the import-direction guard.
- Stable mechanisms do not import features.
- Provider adapters depend on feature role interfaces, not the reverse.
- Pi adapters carry no feature policy — they decode, delegate to typed feature
  operations, and render.
- `extension/index.ts` is composition-only: per-`cwd` dependency loading and
  named installers, no feature policy.
- Rich UI calls remain confined to the sanctioned surfaces files.
- The production import graph contains no cycles (guard-enforced; the two
  baseline import cycles are gone).

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
- Production modules ship no test-only implementations and no test-only
  exports (deliberate, recorded guard/test seams excepted).
- The npm tarball remains one package; current entrypoints remain until an
  intentional application-host entry is added under a normative Pi contract.
- Workspaces and the zero-runtime-dependency policy remain unchanged.
- No code generation or additional package is required.

### Deletion

- Old registration and policy paths are gone.
- Transitional wrappers and re-exports are gone.
- No legacy compatibility paths remain.
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
