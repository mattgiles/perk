# Module contracts

## Purpose

This document makes the architecture in `memo.md` concrete enough to guide a
safe implementation. It defines ownership, import direction, and the shape of
the important seams. Code examples are illustrative TypeScript, not APIs to
copy before their first migrated caller proves them.

The governing rule is:

> Preserve feature-specific types until the Pi edge; share only mechanisms
> whose semantics are already shared.

## Target topology

> **Status (Objective #2130, Node 1.1):** planned → realized paths after the #2083 train
> landed: `session/` — built as drawn. `config/perkConfig.ts` — not created; configuration
> stayed `substrate/config.ts` (see § PerkConfig). `execution/reportWave.ts` — the wave
> engine stayed `waves/` (see § ReportWave). `execution/stageRunner.ts` — stage drive
> stayed `worker/stageExecution.ts` (see § StageRunner). `pi/v1/` — built as drawn.
> `pi/application/` — not created (Phase 8; an explicit objective #2130 non-goal).
> `doors/` (absent from the sketch) was evacuated and deleted by objective #2130 node 3.1:
> `planReviewBrowser`/`objectiveReviewBrowser`/`selfcheck`/`draftReviewWaveTools`/
> `lifecycleGates` → `pi/v1/`, `plannotatorHandoff` → `pi/v1/providers/`, with the Pi-free
> policy splits landing `session/lifecycleGates.ts` + `authoring/review/draftContext.ts`.

```text
extension/
  index.ts                     Pi composition root
  workerMain.ts                worker composition root

  authoring/
    gist/
    plan/
    objective/
  delivery/
  codeReview/
  learning/

  session/
    workflowSession.ts
    artifacts.ts
  config/
    perkConfig.ts
  execution/
    reportWave.ts
    stageRunner.ts

  pi/
    v1/                         current compatibility bridge
      authoring/
      delivery/
      codeReview/
      learning/
      session/
      providers/
      execution/
      rendering/
    application/                future facet adapters, once normative

  surfaces/
  vendor/
```

This is an ownership map, not a required file-for-file move. Existing files
move only with a complete vertical slice. A directory should remain small until
multiple files have distinct reasons to change.

The import direction is:

```text
index.ts / workerMain.ts
           │
           ▼
       Pi adapters ───────────────► feature modules
           │                              │
           └──────────────┬───────────────┘
                          ▼
       session · config · report wave · stage runner
                          │
                          ▼
                     shared/
```

Feature modules do not import `pi/`, `surfaces/`, Pi runtime packages, TUI
packages, or RPC wire types. Stable mechanisms do not import feature modules.
Composition roots may import both.

`pi/application/` is a logical destination, not permission to create empty
facets before upstream interfaces exist. The current v1 bridge and each future
facet call the same feature operations. They do not share a universal host
interface.

## Type laws

### Decode once at the edge

Pi tool input, command text, environment variables, configuration files, JSON,
RPC messages, and branch-backed files are untrusted until decoded. Their
adapters validate once and pass domain values inward.

Feature operations do not repeatedly accept `unknown` or re-parse host
payloads.

### Keep operations specific

There is no shared `Invocation`, `Capability`, or `SemanticResult`.

A feature operation uses:

- a named input with only the data it requires;
- a result union whose cases matter to its caller;
- a feature error union when recovery differs by failure;
- a typed progress channel only when the work is incremental.

For example:

```ts
type SaveGistResult =
  | { status: "saved"; gist: SavedGist }
  | { status: "unchanged"; gist: SavedGist }
  | { status: "reviewRequired"; draft: GistDraft };
```

The Pi binding maps those cases to host output. It must not collapse the
operation to `Promise<unknown>`.

### Model expected outcomes as data

Expected outcomes such as “review required,” “not ready,” or “guidance
unavailable” are discriminated values. Exceptions are reserved for broken
invariants, failed dependencies, cancellation that crosses the operation, and
other failures the immediate caller cannot handle as an ordinary branch.

Share a failure type only when callers can recover from it in the same way.

### Runtime schemas belong at trust seams

TypeBox or equivalent runtime schemas remain beside Pi or transport adapters.
Domain types may be inferred from those schemas when the host shape and domain
shape are genuinely identical. Otherwise, map explicitly.

Future Pi remote services carry strict JSON. That constraint belongs to their
request, state, event, and cancellation codecs. Feature operations do not
become JSON-shaped merely because a future adapter may proxy one of them across
a process seam.

### No universal dependency bag

Constructors and functions receive named dependencies:

```ts
saveGist(input, { session, reviewer, planAuthoring: config.planAuthoring });
```

They do not receive `Services`, `Runtime`, or a host context whose contents
grow with every feature.

### Own Prose units with their behavior

A feature owns the identity, content, audience, and ordering constraints of the
Prose units that shape its behavior. A Pi adapter owns their placement in tool
descriptions, prompt guidance, messages, or Prompt assembly hooks. Human-facing
layout remains a presentation concern.

This division prevents the future contribution registry from becoming the
authority for Perk prompt concerns. A registry carries the prose; the feature
defines what it means.

## Storage freedom

> **Status (Objective #2130, Node 1.1):** this section pins the normative policy the
> objective's Phase-2 work enforces and Phase-5 verifies. It is new with node 1.1; the
> census below is the bounding input for node 2.3.

### The rule

Feature homes (`authoring/`, `delivery/`, `codeReview/`, `learning/`) must not observe
session or branch storage. The Pi/session edge recovers context and passes
runtime-validated values inward.

The **deny set** — imports forbidden in feature homes:

- `substrate/workflowState.ts` — raw workflow state (branch-backed state mechanics);
- `substrate/sessionData.ts` — session-data mechanics;
- the run-scratch surface of `substrate/cache.ts` — `scratchDir`, `runScratchDir`,
  `ensureRunScratch`, `atomicWriteFileSync`;
- `substrate/git.ts` — git bracketing.

### The allow rule

Legitimate domain file I/O is permitted: injectable fs probes with production defaults
(existence or realpath checks over caller-supplied paths — e.g. resolved-containment
verification) and pure path vocabulary. What distinguishes allowed domain I/O from
storage mechanics is this classification: an allowed probe answers a question about a
path the caller supplied; storage mechanics locate, read, or write Perk's own
session/branch/run storage.

### Enforcement

- Objective #2130 node 2.3 extends the import-direction guard
  (`extension/importDirectionGuard.test.ts`) with the deny set above — the Rule-D
  sibling: storage freedom guarded like Pi freedom — and executes the `migrate-in-2.3`
  rows below.
- Objective #2130 node 5.1 verifies the final state against this section.

### Census (as of commit `53fe2d7d`)

One row per observed use in the feature homes, each re-verified by import inspection at
the stamped commit. Classifications: `migrate-in-2.3` / `allowed-domain-I/O` /
`owed-by-2.2` / `census correction — no feature-home use`.

> **Fresh stamp (Node 2.2):** the two `owed-by-2.2` rows below are **executed** — re-verified
> by import inspection in node 2.2's change: the three draft ops now carry results with the
> session-owned `SessionArtifactReceipt` (imported from `session/workflowSession.ts`; zero
> `substrate/workflowState.ts` imports remain), and the two `PlanRef` imports ride the
> `session/workflowSession.ts` re-export (zero feature-home `substrate/cache.ts` `PlanRef`
> imports remain).

> **Fresh stamp (Node 2.3):** the three `migrate-in-2.3` rows below are **executed** —
> re-verified by import inspection in node 2.3's change:
> `authoring/objective/dreamReportGate.ts` is a pure resolver over the runtime-minted
> `DreamGateRecovery` capability (production capability + recovery ladder + bracket live in
> `pi/v1/objectiveDreamGate.ts`; the feature imports only `learning/dream.ts`,
> `learning/dreamReducer.ts`, `learning/dreamReport.ts` — zero `node:fs`, zero `substrate/*`);
> `delivery/ci.ts` persists through the required `PersistCheckOutput` port (the scratch
> path derivation + atomic write live in `pi/v1/delivery/ci.ts`; the feature imports only
> `substrate/config.ts` + `substrate/modelVisible.ts` — the wire `CiCheckResult.scratchPath`
> keeps its name and bytes); and `learning/dreamAnalysis.ts` resolved via the marker-port
> fold — the existing `markBundleDigest` capability retyped to
> `(finalized: string | null) => boolean` so digesting lives with the sole production closure
> at the Pi edge (`pi/v1/learning/dream.ts`; `digestSessionData` stays in
> `substrate/sessionData.ts`). The allowed rows are kept. **Rule H is live**
> (`extension/importDirectionGuard.test.ts`): the storage-free homes × the storage interior
> over the resolved-edge map, empty allowlist, per-home anti-vacuity floor, control-14
> mutation fixtures. Noted strengthenings: `substrate/cache.ts` is enforced MODULE-LEVEL — a
> conservative superset of the pinned run-scratch export surface (pure cache vocabulary rides
> `session/workflowSession.ts` re-exports, the 2.2 precedent) — and the guarded interior also
> covers `session/branchWorkflowSession.ts`, the concrete branch/file session adapter (a
> feature importing it could open storage itself; the abstract `session/workflowSession.ts`
> seam stays importable).

| File | Observed use | Classification | Rationale |
| --- | --- | --- | --- |
| `authoring/objective/dreamReportGate.ts` | imports `node:fs` (`existsSync`/`readFileSync`), `substrate/cache.ts::runScratchDir`, `substrate/git.ts::revalidationBracket`, `substrate/sessionData.ts` (`digestSessionData`, `SessionDataCtx`), and `substrate/workflowState.ts` (`branchOf`, `rebuildWorkflowState`, `WorkflowState`) | `migrate-in-2.3` | the full forbidden set — session storage recovered inside a feature home; 2.3 keeps the decision pure behind a runtime-minted narrow capability recovered at the Pi/session edge |
| `delivery/ci.ts` | imports `node:fs` (`existsSync`/`mkdirSync`) and the `substrate/cache.ts` scratch writers (`atomicWriteFileSync`, `ensureRunScratch`, `scratchDir`); `CiCheckOutcome.executed` returns `scratchPath` | `migrate-in-2.3` | run-scratch imports are in the explicit deny set — scratch routing is session-storage mechanics, not domain I/O |
| `learning/containment.ts` | `node:fs` `existsSync`/`realpathSync` as injectable production defaults for `verifyDocContainment`, the resolved-containment layer (symlink-escape detection); `lexicalContainmentError` is pure string/path normalization with no fs use | `allowed-domain-I/O` | injectable-default fs probes over caller-supplied paths for resolved-containment verification; not session-storage mechanics |
| `learning/harvest.ts` | `node:fs` `existsSync` as the injectable default (`opts.exists ?? existsSync`) for `stampHarvestReport`'s pointer post-pass | `allowed-domain-I/O` | an injectable existence probe over caller-supplied doc paths; not session-storage mechanics |
| `learning/dream.ts` | none — zero `node:fs`/file-read usage in the file | `census correction — no feature-home use` | the objective's census item is stale: the manifest/bundle file reads live at the Pi adapter `pi/v1/learning/dream.ts` (`existsSync`/`readFileSync`/`rmSync` — allowed by construction) and in `dreamReportGate.ts` (already classified above) |
| `learning/dreamAnalysis.ts` | imports `digestSessionData` from `substrate/sessionData.ts` (a pure sha256 helper) | `migrate-in-2.3` | relocate or inject the pure digest helper so `substrate/sessionData.ts` can be module-level denied |
| `authoring/gist/draft.ts`, `authoring/plan/draft.ts`, `authoring/objective/draft.ts` | type-only `SessionArtifactPointer` imports from `substrate/workflowState.ts` | `owed-by-2.2` — **executed** (see the fresh stamp above) | the session-receipt work replaced the exposed substrate pointer shape (`SessionArtifactReceipt` via `session/workflowSession.ts`); explicitly outside 2.3's bucket |
| `authoring/plan/save.ts`, `learning/prose.ts` | type-only `PlanRef` imports from `substrate/cache.ts` | `owed-by-2.2` — **executed** (see the fresh stamp above) | the same session-owned receipt/vocabulary work (the `PlanRef` re-export from `session/workflowSession.ts`); explicitly outside 2.3's bucket |

## Feature modules

Feature modules own workflow decisions. They do not all implement a common
interface.

### Authoring

Authoring contains three related but distinct flows:

- gist authoring;
- plan authoring and replanning;
- objective authoring, review, and reconciliation.

Each flow owns its progression, typed drafts, review findings, and save rules.
Prefer one-entry use-case functions. Introduce a review role only when a
provider-backed implementation and deterministic test implementation share the
same feature-specific semantics:

```ts
interface GistDraftReviewer {
  review(draft: GistDraft, signal: AbortSignal): Promise<GistReviewOutcome>;
}

function saveGist(
  input: SaveGistInput,
  dependencies: SaveGistDependencies,
): Promise<SaveGistOutcome>;
```

That operation is not a template that plan and objective authoring must copy.
Their state machines decide their interfaces. A generic
`DraftReviewer<Draft, Decision>` would share syntax while erasing recovery
semantics.

### Delivery

Delivery owns readiness, publication, Delivery train progression, recovery,
and landing policy. It receives typed outcomes from exterior tools rather than importing
command execution or GitHub output formats throughout the feature.

Exterior roles are introduced from migrated callers rather than forecast as a
general Git interface. “Publish this prepared change” may earn a narrow role;
“Git service” does not. A port is admitted only with one production adapter and
one useful deterministic implementation.

### Code review

Code review owns review requests, normalized findings, dispositions, and the
rules for resolving or publishing review state. `ChangeReviewer` describes
the external reviewer role:

```ts
interface ChangeReviewer {
  review(change: ReviewableChange): Promise<ChangeReview>;
}
```

Pi rendering and provider response formats remain outside. Code review may use
`ReportWave` for parallel reviewers without learning its transport.

### Learning

Learning owns analyst roles, harvested observations, consolidation, routing,
and dream or harvest selection policy. It may use `ReportWave`, but the
meaning and acceptance of each report remain in learning.

Learning does not become the owner of all report execution merely because it
uses the most waves.

### Cross-feature calls

Prefer one feature consuming another feature's named operation over sharing
its internal state. If two features appear to need the same helper:

1. keep it with the first caller;
2. add the second real use;
3. compare semantics, not syntax;
4. extract the smallest shared mechanism only if the meanings match.

Feature modules never coordinate through a global event bus or capability
catalog.

## WorkflowSession

`WorkflowSession` is the authoritative feature-facing seam for one workflow
session. It owns:

- session identity and kind;
- validated workflow state;
- artifact names, contents, and provenance;
- verified writes and read-back;
- claim, mint, fork, adoption, and handoff ordering.

It does not own:

- Pi registration or rendering;
- raw conversation context;
- feature progression rules;
- arbitrary file access;
- report-wave or feature-local pending work;
- host attachment, reload-generation, or adapter-disposal mechanics;
- a fictional revision model unsupported by storage.

An illustrative shape is:

```ts
interface WorkflowSession {
  read(): Promise<WorkflowSnapshot>;
  apply(change: WorkflowChange): Promise<WorkflowChangeResult>;
  readArtifact(name: SessionArtifactName): Promise<ReadArtifactResult>;
  writeArtifact(write: ArtifactWrite): Promise<WriteArtifactResult>;
}

type WorkflowChangeResult =
  | { status: "applied"; snapshot: WorkflowSnapshot }
  | { status: "unchanged"; snapshot: WorkflowSnapshot }
  | { status: "unverified"; problem: SessionProblem }
  | { status: "rejected"; problem: SessionProblem };
```

`WorkflowChange` is a closed union of storage-level semantic changes admitted
from migrated callers. It is not a feature dispatcher or JSON patch. Artifact
names are a closed set or validated feature-owned names, not arbitrary paths.
`unverified` means an effect may have landed but the read-back proof failed;
callers must read authoritative state before retrying.

The constructor or factory establishes identity once:

```ts
type OpenWorkflowSession =
  | { status: "opened"; session: WorkflowSession }
  | { status: "absent" }
  | { status: "invalid"; problems: ReadonlyArray<SessionProblem> };
```

State persistence and artifact persistence are separate internal seams. The
current adapter uses branch entries for state and pointer-validated files for
artifacts. An eventual Pi adapter may combine values, lists, and conversation
entries; it need not force every field into one storage form. Both are tested
through `WorkflowSession`.

Before a field can move to Pi storage, record:

| Question | Possible answers |
| --- | --- |
| Authority | session interior, Python exterior, derived |
| Retention | current value, append-only history |
| Fork behavior | inherit, reset, recompute |
| Model visibility | required, forbidden |
| Verification | strict read-back, best effort |
| Artifact relationship | none, pointer, digest authority |

If the backing cannot prove a compare-and-swap revision, the interface must not
claim one. A new Pi host generation reopens the session from durable state;
adapter disposal never deletes that state.

## PromptEvidence

> **Disposition (Objective #2130, Node 1.1): deferred.** The value type was never built
> (the Phase-2 narrow-until-proven rule, reaffirmed at every later phase). The inline
> `branchCarries(activeContextWindow(branch), MARKER)` idiom is the realized shape of
> context evidence; objective #2130 node 4.2 consolidates its repeated implementations
> into one pi/v1 helper. The `PromptEvidence` value itself waits for a second context
> projection — the format-4 host — whose adapter would give the type its second real
> deriver. Until then this section documents the target semantics, not a binding
> criterion (removed from the final acceptance criteria by node 1.1).

`PromptEvidence` is an immutable value describing which Prose units are
directly evidenced in the current Prompt assembly:

```ts
type PromptEvidence =
  | {
      status: "available";
      sessionShape: SessionShape;
      units: ReadonlyArray<DeliveredProseUnit>;
    }
  | {
      status: "unavailable";
      reason: "sourceUnavailable" | "unsupportedProjection" | "malformedEvidence";
    };
```

Each delivered unit preserves its `ProseUnitId`, intended audience, run or
trigger scope, direct provenance, and observed order where ordering matters.
Quoted prose in a compaction summary is not direct provenance. Wrong-run,
wrong-stage, wrong-command, wrong Session shape, and ineligible-agent evidence
do not satisfy the current Prompt concern.

The v1 adapter derives the value from the current branch and
`firstKeptEntryId`. The future application adapter derives it from Pi's stable
context projection and `retainedTail`; physical format-4 records do not escape
that adapter. Compaction is not itself unavailability.

Feature-owned pure functions reconcile the particular Prompt concern they
understand. Unavailable evidence never proves durable absence.
`PromptEvidence` is not persisted and has no module interface of its own.

Agent scratch may provide external context to a Prompt assembly, but its
run-owned disposable files are neither `WorkflowSession` artifacts nor Pi
application state.

## ReportWave

> **Disposition (Objective #2130, Node 1.1): owed by objective #2130 node 2.1.** The
> Node 5.1 status note in `migration-and-verification.md` recorded the opaque
> `start`/`collect`/`run` + `ReportWaveRef` lifecycle as superseded by the kept
> `startReportWave`/`runReportWave`-over-`WaveAdapter` shape; objective #2130 reverses
> that disposition. The reversal rationale: the mechanism now has ten proven consumers
> behind two adapters, yet nine `rpcAdapter` construction sites leak transport selection
> to callers and pending state remains door-owned (`doors/pendingWave.ts`) — exactly the
> caller-visible mechanics this section says the wave must own. Node 2.1 restores this
> section's opaque lifecycle as one atomic layer; the realized lifecycle semantics it
> must preserve (never-rejecting detached results, subscribe-before-spawn buffering, the
> start-vs-run cancellation split, the pending-collect semantics) are enumerated in the
> #2130 roadmap.

> **Update (Objective #2130, Node 2.1): disposition realized.** The opaque
> `start`/`collect`/`run` lifecycle ships in `extension/waves/reportWave.ts`; the realized
> shape deviates from the sketch below only where noted:
>
> - The full `ReportWave*` rename landed (`ReportWaveRequest`, `ReportWaveResult`,
>   `ReportWaveFailure`/`ReportWaveFailureReason`, `ReportWaveLevelFailureReason`,
>   `ReportWaveCompleteness`, `ReportWaveLaunchManifest`, `ReportWaveAttemptReceipt`), with
>   `AssignmentReport` as the one stutter-avoiding exception (pairs with
>   `ReportAssignment`/`AssignmentFailure`).
> - `WaveControl` carries only `signal`, and `collect(ref)` takes NO control parameter (the
>   sketch's slot would have carried only a test-only timing knob; the
>   `PERK_WAVE_COLLECT_GRACE_MS` env knob is the one grace seam). `collect` returns the added
>   `CollectWaveResult` union (`none`/`running`/`settled`) carrying the grace/retention
>   semantics — the sketch's `Promise<ReportWaveResult>` had no way to say "still running,
>   ref retained".
> - Pending execution is an instance-owned `WeakMap<ReportWaveRef, PendingRecord>` with
>   `delete(ref)` as the atomic drain claim — drain-once holds even under overlapping
>   collectors, and a foreign instance's ref collects `none` structurally.
> - Adapter supply is wave-owned: `createReportWave(bus)` (the production factory,
>   constructed once at the `index.ts` composition root) builds a fresh rpc adapter per
>   launch; `reportWaveOver(adapter)` is the injection seam over the same core.
> - The one-line identity-guarded slot clear (`if (state.pending === ref) …`) remains flow
>   policy in the two collect cores — which wave is *current* is the flow's own state; every
>   race/grace/drain mechanic below it is wave-owned.

`ReportWave` is the shared mechanism for asking several named reporters to
produce reports and then collecting their outcomes. It owns:

- reporter fan-out;
- correlation and pending state;
- cancellation and timeout mechanics;
- fan-in and deterministic ordering;
- transport-independent wave progress.

It does not own:

- which reporters a feature selects;
- report prompts or domain acceptance;
- feature-specific consolidation;
- Pi rendering;
- RPC, workflow-script, child-session, or Pi-lane types in its interface.

The public interface preserves blocking and nonblocking use without exposing
how the work runs:

```ts
interface ReportWave {
  start(request: ReportWaveRequest, control?: WaveControl): Promise<StartWaveResult>;
  collect(ref: ReportWaveRef, control?: WaveControl): Promise<ReportWaveResult>;
  run(request: ReportWaveRequest, control?: WaveControl): Promise<ReportWaveResult>;
}
```

`ReportWaveRequest` contains ordered `ReportAssignment` values, not “lanes.”
`ReportWaveRef` is opaque Perk vocabulary. Validation precedes preflight;
preflight precedes launch; completion is correlated before the durable
aggregate is read; results normalize into requested order. Provider
unavailability, spawn failure, timeout, cancellation, unreadable aggregates,
and assignment failures are expected result cases. Returned completion work
never rejects, receipts remain output-free, and pending state belongs to the
wave instance rather than process-global state.

The current RPC implementation and deterministic memory implementation are
internal adapters. A Pi-lane adapter is admitted only after lane concurrency,
isolation, cancellation, and recovery satisfy this interface.

## StageRunner

> **Disposition (Objective #2130, Node 1.1): deferred.** The realized shape is SDK
> confinement around `worker/stageExecution.ts::runStage` (the Phase-3 rename + private
> SDK adapter + drive-session handle), not a `StageRunner` protocol object. Objective
> #2130 node 4.1 narrows the module's exported surface to the real production interface.
> The protocol object waits for a second execution root — the durable-drive host — whose
> adapter would give the interface its second implementation. Until then this section
> documents the confinement invariants the worker seam already enforces, not a binding
> criterion (removed from the final acceptance criteria by node 1.1).

`StageRunner` executes an actual registered Perk stage in a session-interior
execution root. Its feature-facing shape stays small:

```ts
interface StageRunner {
  run(
    request: StageRunRequest,
    progress: StageProgressSink,
    signal?: AbortSignal,
  ): Promise<StageRunOutcome>;
}
```

It owns:

- resolving a stage identifier through the shared stage registry;
- stage Prompt assembly and terminating-tool requirements;
- Perk turn, token, and wall-clock budget policy;
- workflow-level run events and terminal outcome normalization;
- session-pointer policy and recovery decisions.

It does not own feature dispatch, arbitrary recipes, report-wave fan-out, or Pi
registration.

The current SDK adapter owns model/auth/session construction, raw event
translation, prompt/abort, and disposal. The future durable-drive adapter owns
Pi operation acceptance, inspection, recovery, usage-ledger projection, and
abort mechanics. Raw operation IDs and usage rows do not enter the
`StageRunner` interface. Perk owns its budget policy and `StageRunOutcome`; it
does not duplicate Pi's low-level operation ledger.

Every run produces exactly one terminal outcome. Cancellation, budget
exhaustion, model failure, incomplete idle, and unsafe uncertain effects remain
distinct. An unsafe uncertain effect is never replayed automatically.
`workerMain.ts` is the initial consumer; future Pi session-worker roots may join
the allowlist after their maturity gate. A free-form task runner remains an
unearned abstraction.

## PerkConfig

> **Disposition (Objective #2130, Node 1.1): deferred.** Configuration stayed
> `substrate/config.ts`; no `config/` directory was created. The motivating problem —
> the `config.ts ⇄ bindings.ts` import cycle — was broken in place by Phase 1 (bindings
> no longer import config vocabulary), so the module's cycle-breaking justification is
> already satisfied without it. The directory is re-earned only when a real second host
> or substrate consumer appears with its own configuration lifecycle. Until then this
> section documents the ownership rules `substrate/config.ts` already obeys, not a
> required move (removed from the final acceptance criteria by node 1.1).

`config/` owns parsing, validation, defaults, and the typed `PerkConfig`.
Configuration is decoded from the active `cwd` at the same session or
invocation points as today. A `PerkConfig` is an immutable snapshot, not one
extension-global value and not a mutable manager.

Features receive narrow views, preferably plain values:

```ts
createCodeReview({
  reviewer,
  session,
  model: config.codeReview.model,
});
```

Configuration must not import binding definitions to discover defaults, and
bindings must not import configuration internals. Removing that mutual
knowledge breaks the current `config.ts ↔ bindings.ts` cycle.

Provider selection is composition. A factory in `pi/v1/providers/` or a future
Pi provider-service adapter may load `PerkConfig` for the current `cwd` and
construct a feature-specific reviewer. The feature sees only the narrow role
interface.

## Pi adapters and application facets

There is no `PiExtension` module and no `PiBinding[]` interface. The current
composition root calls named installers directly:

```ts
installGistBindings(pi, gistDependencies);
installDeliveryBindings(pi, deliveryDependencies);
installSessionLifecycle(pi, sessionDependencies);
```

The repeated call shape is wiring, not a seam. Each installer owns one coherent
set of extension-v1 registrations. Its cleanup is idempotent and releases only
activation-owned resources; durable workflow state survives.

A v1 tool adapter owns:

- the Pi tool name and description;
- runtime input schema;
- placement of feature-owned Prose units in prompt fields;
- execution mode and availability policy;
- incremental progress translation;
- final result rendering.

A command binding owns command text parsing and completion. Flag, shortcut, and
hook bindings retain their own Pi forms. They do not need to masquerade as
tools.

The intended application-host placement is:

| Pi facet or facility | Perk adapter responsibility |
| --- | --- |
| Application/server | manifest generation, provider-service discovery, complete-generation lifecycle |
| Session | feature contributions, `WorkflowSession` storage, `StageRunner`, `ReportWave` |
| Typed values/lists | eligible current values and histories selected by field policy |
| Durable operations/usage | stage drive, recovery, raw usage projection |
| Lanes | report-assignment execution after isolation parity |
| TUI/web | surfaces, standing state, reports, views, and slots |
| Remote services | strict-JSON codecs, cancellation, state snapshots, ordered events |

This table fixes ownership, not exact upstream TypeScript names. A future
manifest contributes feature operations directly to Pi registries. It does not
introduce a Perk catalog or dispatcher.

### Tool access

`pi/v1/toolAccess.ts` owns the host-specific enforcement currently called tool
gating. It owns:

- the exact census of Perk and borrowed tool names;
- translation from verified session mode and stage to Pi tool availability;
- synchronization on the relevant Pi lifecycle hooks; and
- fail-safe behavior for an absent borrowed tool.

It consumes typed session posture from `WorkflowSession` and the shared stage
registry. Feature modules do not import borrowed tool names or mutate Pi's tool
set. A feature binding may declare its own execution and availability rule,
but the adapter combines that rule with session-wide read-only enforcement.

`ToolAccess` is a v1 adapter, not a generic authorization framework. Its
contract tests retain the current borrowed-package census and stage coverage.
A future Pi contribution adapter translates the same Perk availability rules
into that host's registry and lifecycle. Deleting a feature may honestly edit
the central borrowed-tool census where host-wide policy requires it.

`index.ts` loads `cwd`-scoped dependencies at their current lifecycle points,
calls named v1 installers, and wires host events to session or feature
operations. It contains no feature policy.

## Progress and rendering

Progress is part of an operation contract only where callers can observe useful
intermediate state. Use a narrow sink or callback with a feature-specific
event union:

```ts
type RunChecksProgress =
  | { type: "checkStarted"; name: CheckName }
  | { type: "checkFinished"; result: CheckResult };
```

The Pi adapter converts those events to `onUpdate`, working messages, status,
or reports through the existing surfaces seam. A CLI or test adapter may
record them differently.

Feature results contain meaning, not prose layout. Rendering modules may share
formatting primitives, but there is no universal `render(result)` contract.

Presentation is divided by lifetime:

- transient progress and notifications may disappear after delivery;
- standing status, footer, widget, and report state must be reconstructible
  from authoritative semantic state when a client attaches or a generation
  reloads.

A future view adapter may add feature-specific standing read models when a
real surface requires them. It must not create a universal update journal.

All rich UI and TUI calls continue to obey the repository surfaces-module
rule.

## Ownership matrix

| Concern | Owner | Must not leak into |
| --- | --- | --- |
| Workflow progression | feature module | Pi binding, storage adapter |
| Session identity and verified state | `WorkflowSession` | feature-local file helpers |
| Artifact provenance | `WorkflowSession` | rendering |
| Current Prompt assembly evidence | Pi prompt-evidence adapter | durable session state |
| Configuration parsing | `config/` | feature logic |
| Provider construction | Pi composition/provider adapter | feature module |
| Report fan-out and fan-in | `ReportWave` | feature-specific report meaning |
| Stage execution | `StageRunner` | report waves, tool bindings |
| Prose-unit meaning and order | feature module | Pi registry authority |
| Schemas and registration metadata | Pi adapter | feature operation |
| Progress and final presentation | Pi rendering adapter | domain result types |
| RPC, service, and facet wire formats | Pi adapter | feature module |
| Agent scratch | run-owned disposable storage | session artifacts or application values |

## Future-adapter admission

Future-first does not mean unguarded adoption. Each candidate must satisfy its
own interface rather than a generic “new Pi” gate.

| Candidate | Admission requirement |
| --- | --- |
| Format-4 context | Supported TypeScript context projection; v3 and `retainedTail` evidence parity |
| Values/lists | Supported application access; documented fork behavior; one field-classified dual-read proof |
| Durable drive | Public drive enabled; complete recovery paths; provider/tool crash proof; terminal and budget parity |
| Usage ledger | Complete, queryable population; monotonic totals agree with current accounting through retry and recovery |
| Pi lanes | Normative concurrent drive, role isolation, cancellation, recovery, and bounded-result semantics |
| Application facets/services | Normative manifest, lifecycle, reload-generation, service, and cancellation contracts |
| Views/slots | Normative snapshot/update contract; local, headless, and late-attached parity |

An admitted adapter first runs beside the current implementation under the same
interface tests. The host selects one adapter; both never perform the same
effect. The old adapter is deleted only after semantic parity and support-policy
approval.

## Test contracts

Every feature operation has direct tests that construct the feature with
in-memory dependencies and call its typed interface without Pi.

Every Pi binding has adapter tests that prove:

- the correct registration form and metadata;
- host input decoding;
- feature invocation;
- progress translation when applicable;
- final result or error translation;
- lifecycle behavior for hooks.

`WorkflowSession` is tested through branch-backed and in-memory storage, with a
future values/lists adapter joining the same interface suite. `ReportWave` is
tested through its public start/collect/run interface while memory, RPC, and
eventual lane mechanics receive focused internal adapter coverage.

`StageRunner` policy tests use a scripted drive. Current SDK and future durable
drive adapters must pass the same observable recovery, budget, terminal, and
outcome cases.

Import guards prove:

- feature directories have no runtime Pi or TUI imports;
- feature directories have no RPC wire imports;
- stable mechanisms do not import features;
- only approved composition or adapter files register with Pi;
- `StageRunner` has only approved execution-root consumers;
- stable modules import no Pi facet, service, value/list, lane, Harness, view,
  or slot types.

The import guards supplement behavioral tests. They do not replace them.

## Deletion tests

The module structure is healthy if these hypothetical deletions are local:

- Removing gist authoring deletes its feature files and Pi bindings without
  editing a universal protocol.
- Replacing Pi context extraction edits the prompt-evidence adapter without
  editing learning or authoring policy.
- Replacing RPC report execution with Pi lanes edits the report-wave adapter without editing
  report selection or consolidation.
- Replacing SDK drive with durable drive does not change `StageRunner` callers
  or the Perk outcome.
- Replacing v1 with application facets does not change feature operations.
- Removing worker stage execution does not change report-wave callers.
- Replacing a review provider edits provider construction without changing
  draft or change review policy.

If a migration step cannot pass its deletion test, its ownership is still too
spread out.
