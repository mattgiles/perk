# Future-proofing Perk through library decomposition

> Status: architectural direction, not an implementation plan. Package names are working names.
> The goal is to isolate Pi volatility behind reusable Perk interfaces while preserving Perk's
> existing two-plane contract.

## Context

The [upcoming Pi changes memo](upcoming-pi-changes-memo.md) identifies several change
axes that are likely to arrive on different schedules:

- extension-v1 registration and lifecycle may eventually give way to application hosts and
  plugin facets;
- custom branch entries may gain a replacement in application-owned typed values and lists;
- v3 JSONL sessions may move to format-4 JSONL or SQLite-backed repositories;
- the current SDK-driven worker may gain a durable Harness drive interface;
- `pi-subagents` child sessions may gain an alternative in Harness lanes;
- `ctx.ui` surfaces may gain an alternative in remote views and slots; and
- `.pi/settings.json` package convergence may eventually target an application manifest.

These changes all touch Perk's integration with Pi, but they do not change Perk's plan-oriented
workflow, delivery policy, review waves, artifact integrity rules, or Git/GitHub/Linear domain.
The decomposition should reflect that distinction.

The desired result is not a collection of tiny packages. It is a small number of deep modules:
each exposes a compact Perk-owned interface while hiding the substantial implementation needed
to make current and future Pi behavior satisfy that interface.

## Design objective

After this decomposition, each of the following should be possible without editing Perk's
workflow modules:

- replace custom-entry workflow persistence with typed values/lists;
- support both v3 and format-4 session evidence;
- replace current SDK session drive with durable Harness drive;
- replace or supplement `pi-subagents` with lanes;
- install Perk through extension v1 or future plugin-host facets;
- render through current `ctx.ui` calls or future views/slots; and
- launch ordinary `pi` or submit work to a stable Pi server.

The interfaces should survive because they describe Perk operations and outcomes, not Pi
objects or transport mechanics.

## Non-goals

- Do not merge the Python exterior and TypeScript interior into one runtime library.
- Do not split every current directory into a separately published package.
- Do not reproduce Pi's current extension interface behind a one-for-one wrapper.
- Do not design against exploratory plugin-host types before Pi makes them normative.
- Do not move stable Git, delivery, issue-backend, or objective behavior merely because Pi is
  changing.
- Do not independently version the candidate libraries at first. They can remain internal
  workspaces bundled into the existing wheel and npm artifact.
- Do not generate cross-language types. Continue to author shared contracts once and let each
  plane read its own bundled copy.

## Design principles

### Two planes, one contract

The existing [shared contract source](../../shared/README.md) remains the only bridge between the
Python exterior and TypeScript interior. It owns serialized or parsed vocabulary such as stage
IDs, run identity, provider selection, bindings, input/output envelopes, and other facts both
planes must interpret identically.

Within each plane, ordinary language-level interfaces can be used. Across planes, the interface
is always serialized data with validation at the receiving edge.

### Stable center, volatile adapters

```text
               composition roots
          perk CLI / extension entrypoint
                     │
        ┌────────────┴────────────┐
        │                         │
   deep Perk modules        Pi-specific adapters
   workflow/session/        v1 today; format 4,
   execution/presentation   durable drive, hosts later
        │                         │
        └──── Perk interfaces ────┘
                     │
              shared contracts
```

The stable side owns each interface. A Pi adapter satisfies it. Pi types must not leak inward.

### Semantic interfaces, not Pi-shaped interfaces

An interface such as this preserves current Pi terminology and therefore preserves its
volatility:

```ts
interface PiLikeSession {
  getBranch(): unknown[];
  appendEntry(type: string, data: unknown): void;
  prompt(text: string): Promise<void>;
  on(event: string, handler: (event: unknown) => void): void;
}
```

The useful interfaces instead state what Perk needs:

```ts
interface PerkSession {
  read(): Promise<WorkflowSnapshot>;
  apply(change: WorkflowChange): Promise<CommitResult>;
  artifact(request: ArtifactRequest): Promise<ArtifactResult>;
}

interface StageExecutor {
  execute(request: StageRunRequest, control: RunControl): Promise<RunOutcome>;
}

interface PerkPresentation {
  publish(update: SurfaceUpdate): void;
  interact(request: InteractionRequest, signal: AbortSignal): Promise<InteractionResult>;
}
```

`ExtensionContext`, `SessionManager`, `AgentEvent`, `RemoteState`, `PluginFacet`, `View`, and
`firstKeptEntryId` belong inside adapters. They must not appear in the stable interfaces.

### Host topology is not Perk's module topology

Future Pi may run server, session, TUI, and web facets in different processes. Those are adapter
locations, not reasons to create `perk-server-domain`, `perk-session-domain`, or
`perk-tui-domain` libraries.

A Perk feature should remain cohesive. A future plugin-host adapter may expose several facets
that all call the same Perk module. Adding a web facet should not move or duplicate workflow
behavior.

### One adapter is hypothetical; two adapters are real

Each extracted seam should begin with at least:

- the current production adapter; and
- an in-memory or scripted adapter used by the interface-level contract suite.

The future Pi adapter then becomes a third implementation. A package containing only interface
declarations and one pass-through adapter is shallow and should not exist.

## Target library map

### 1. Shared cross-plane contracts

**Current home:** [`shared/`](../../shared/README.md)

**Owns:**

- stage registry and state-key vocabulary;
- skill bindings and provider catalog;
- run identity and cross-plane paths;
- machine input/output schemas; and
- any future `RunIntent`, `RunEvent`, `RunOutcome`, session reference, or evidence envelope that
  both planes exchange.

**Interface:** parsed and serialized records only.

**Import rule:** may depend on no Python or TypeScript implementation. Both planes resolve and
bundle it independently.

This source is already correctly placed. The decomposition should expand it only when a fact
truly crosses planes, not as a dumping ground for ordinary shared-looking types.

### 2. TypeScript workflow library

**Working name:** `@mgiles/perk-workflow`

**Candidate current sources** (as written; the ts-decomposition work has since dissolved the
first three homes — `doors/`, `factories/`, and `adapters/` were evacuated and deleted, their
flows now living in the Pi-free feature homes `authoring/`/`delivery/`/`codeReview/`/`learning/`
behind `extension/pi/v1/` adapters, which are today's candidate sources for this library):

- `extension/doors/`
- `extension/factories/`
- provider-neutral portions of `extension/adapters/`
- flow-specific orchestration in `extension/waves/`
- stage, plan-reference, and workflow decision types currently scattered across those folders

**Owns:**

- Perk tool vocabulary, schemas, and handlers;
- stage-specific lifecycle policy;
- plan/gist/objective/review/learn behavior;
- wave roles, manifests, completeness, validation, and aggregation policy; and
- mapping domain outcomes into stable tool results.

**Does not own:**

- `pi.registerTool` or lifecycle-hook registration;
- `ExtensionContext`;
- session storage mechanics;
- Pi UI calls;
- SDK construction; or
- `pi-subagents` RPC envelopes.

Its outward interface should be a host-neutral catalog of Perk contributions and workflow
handlers. The extension-v1 and future plugin-host adapters decide how to register those
contributions.

The existing factory/adapter cycle should disappear as part of this extraction. Stage constants,
`ReviewOutcome`, plan-provider-neutral values, and provider selection belong in the workflow
library. Concrete Plannotator and Tombell adapters depend inward on those types; workflow code
must not import a concrete adapter.

### 3. TypeScript session library

**Working name:** `@mgiles/perk-session`

**Candidate current sources:**

- [`extension/substrate/workflowState.ts`](../../extension/substrate/workflowState.ts)
- [`extension/substrate/sessionData.ts`](../../extension/substrate/sessionData.ts)
- [`extension/substrate/sessionPointers.ts`](../../extension/substrate/sessionPointers.ts)
- binding/context dedup logic that depends on live session state

**Owns:**

- `WorkflowSnapshot` and `WorkflowChange`;
- run/session claim rules;
- per-field update semantics;
- fork and rewind behavior;
- session artifact provenance and digest verification;
- live-context classification needed for injection dedup; and
- commit verification and normalized errors.

**External interface:**

```ts
interface PerkSession {
  read(): Promise<WorkflowSnapshot>;
  apply(change: WorkflowChange): Promise<CommitResult>;
  artifact(request: ArtifactRequest): Promise<ArtifactResult>;
}
```

The module may have internal seams for persistence and clock/filesystem behavior. They do not
belong in its external interface.

**Initial adapters:**

- an in-memory adapter for the contract suite; and
- a branch-entry adapter implementing today's `appendEntry` plus branch rebuild behavior.

**Expected future adapters:**

- a Pi application-value/list adapter; and
- possibly a remote session-service adapter if Perk state lives in another process.

The session module—not the adapter—must decide which fields require history, which require only
current value, which must fork, and which must be visible to model context. A values/list adapter
is a storage implementation, not a new definition of Perk workflow semantics.

### 4. TypeScript execution library

**Working name:** `@mgiles/perk-execution`

**Candidate current sources:**

- [`extension/worker/stageExecution.ts`](../../extension/worker/stageExecution.ts) and its
  private SDK adapter [`extension/worker/sdkAdapter.ts`](../../extension/worker/sdkAdapter.ts)
- the deep report-wave runner in
  [`extension/waves/reportWave.ts`](../../extension/waves/reportWave.ts)
- run-event normalization and budget/terminal classification

This library can contain several deep modules with separate interfaces:

```ts
interface StageExecutor {
  execute(request: StageRunRequest, control: RunControl): Promise<RunOutcome>;
}

interface ReadOnlyExecutor {
  execute(request: ReadOnlyRequest, control: RunControl): Promise<ReadOnlyResult>;
}

interface WaveRunner {
  run(request: ReportWaveRequest, control: RunControl): Promise<ReportWaveResult>;
}
```

**Owns:**

- stage prompts and terminating-tool requirements;
- turn/token/wall-clock policy;
- Perk run-event and outcome vocabulary;
- tool-outcome normalization;
- read-only child caps and structured handoff;
- wave completeness and failure semantics; and
- cancellation behavior visible to Perk callers.

**Initial adapters:**

- current coding-agent SDK session construction and events;
- current `pi-subagents` RPC bridge; and
- scripted/in-memory execution adapters.

**Expected future adapters:**

- durable `AgentHarness` accept/drive/abort/inspect;
- Pi server/session-worker submission;
- lane-backed wave execution; and
- remote attach/event projection.

The existing `WaveAdapter` (`extension/waves/transport.ts`) is a proven internal seam: it has
memory and RPC adapters plus one shared behavioral suite. Callers should continue to use the
deep `ReportWave` lifecycle (`start`/`collect`/`run`) rather than learning `ping`, `spawn`,
completion races, stop, and aggregate-file mechanics.

> **Update (Objective #2130, Node 2.1):** the caller surface is now the opaque `ReportWave`
> lifecycle over `createReportWave(bus)` — adapter selection is wave-owned (a fresh rpc adapter
> per launch), and the `WaveAdapter` injection seam still exists but is waves-interior behind
> the supplier (`reportWaveOver` is the test seam). Future lane adapters still implement
> `WaveAdapter` inside `waves/`.

The worker's present `StageRunDeps` and structural Pi mirrors are useful internal test seams.
They should not become the new library's external interface.

### 5. TypeScript presentation library

**Working name:** `@mgiles/perk-presentation`

**Candidate current sources:**

- [`extension/surfaces/report.ts`](../../extension/surfaces/report.ts)
- pure formatting and presentation models from
  [`extension/surfaces/surfaces.ts`](../../extension/surfaces/surfaces.ts)
- review-interaction models currently embedded in browser/terminal doors

**Owns:**

- semantic notices and diagnostics;
- objective/status presentation state;
- review interaction requests and outcomes;
- footer and renderer view models; and
- headless behavior for each semantic presentation request.

**External interface:** semantic updates and interactions, not Pi UI methods.

**Initial adapters:**

- current `ctx.ui`/entry-renderer adapter;
- headless/logging adapter; and
- a recording adapter for tests.

**Expected future adapters:**

- Pi views and slots;
- remote TUI presentation; and
- web presentation.

The current `report()` module is a useful beginning because callers ask to report a Perk
diagnostic rather than choosing every terminal behavior themselves. Its `ReportTarget` still
structurally mirrors Pi and should become an internal adapter detail as the module deepens.

### 6. TypeScript Pi host adapters

**Working names:**

- `@mgiles/perk-pi-v1`
- `@mgiles/perk-pi-host` when the new host contract is normative

**Current sources:**

- [`extension/index.ts`](../../extension/index.ts)
- registration-only portions of doors and factories;
- Pi event-bus and context translation;
- current UI adapter implementation; and
- current SDK and `pi-subagents` adapter implementations.

The v1 package should be a composition root and adapter collection. It may import Pi packages,
construct the deep Perk modules, register their contributions, translate lifecycle events, and
dispose resources. It should own no workflow decisions.

A future plugin-host package may provide server, session, TUI, and web facets. Those facets
should satisfy the same Perk interfaces or invoke the same contribution catalog; they must not
fork the workflow implementation.

Only these adapter packages should import `@earendil-works/pi-*` at runtime. An import guard
should enforce that rule.

### 7. Python exterior application library

**Working name:** `perk-exterior`

Most of `src/perk` is stable relative to the Pi work. Existing deep modules such as
[`IssueBackend`](../../src/perk/backends/issue_backend.py) and
[`Delivery`](../../src/perk/delivery/facade.py) should remain intact.

The exterior application library owns:

- run intent and workflow-level run state;
- worktree and Git positioning policy;
- remote-job lifecycle;
- delivery coordination;
- cancellation/retry/resume policy; and
- composition of GitHub/Linear and Pi adapters.

It must not import `perk.cli`. Today `run`, `state`, and `convergence` import
`UserFacingCliError` or `Ensure` from `perk.cli.ensure`. Move application error/result vocabulary
to a neutral module; the Click command layer catches and renders it.

The CLI then becomes a composition and presentation adapter over the exterior application's
interfaces.

### 8. Python Pi exterior adapter

**Working name:** `perk-pi-exterior`

**Candidate current sources:**

- `src/perk/run/launch/`
- Pi-specific settings/package convergence under `src/perk/convergence/`
- extension installation and version pinning;
- Pi executable/environment construction; and
- live session-pointer discovery needed for launch and recovery.

**Interface sketch:**

```python
class PiExterior(Protocol):
    def converge(self, desired: PiApplication) -> ConvergenceReport: ...
    def launch(self, request: SessionLaunch) -> NoReturn: ...
```

The current adapter targets `.pi/settings.json`, the ordinary `pi` CLI, and an extension-v1
package. A future adapter might target a plugin manifest or server submission while preserving
the exterior application's run intent and outcome contracts.

The desired Pi application is Perk vocabulary: required capabilities, stage, resources, model,
and host mode. It should not be a serialized copy of today's Pi settings file.

### 9. Python session-evidence library

**Working name:** `perk-evidence`

**Candidate current sources:**

- [`src/perk/learn/session_jsonl.py`](../../src/perk/learn/session_jsonl.py)
- branch normalization and audit projection;
- session-pointer reading; and
- evidence models consumed by learn/audit behavior.

**External interface:**

```python
class SessionEvidenceReader(Protocol):
    def read(self, reference: SessionReference) -> SessionEvidence: ...
```

`SessionEvidence` should contain Perk's normalized messages, tool calls, custom workflow facts,
usage, compaction evidence, and diagnostics. It should not expose physical JSONL record types,
SQLite rows, or `firstKeptEntryId`.

**Initial adapters:**

- current lenient v3 JSONL reader; and
- an in-memory/golden-fixture reader used by the contract suite.

**Expected future adapters:**

- format-4 JSONL reader;
- Pi repository/export adapter; and
- SQLite-backed reader if Pi exposes a stable route.

This extraction lets learn and audit behavior remain unchanged while the evidence source is
replaced or widened.

## Target source dependency graph

```text
shared contracts
├── Python domain/exterior
│   ├── delivery + issue backends
│   ├── evidence interface
│   └── Pi exterior interface
└── TypeScript workflow
    ├── session interface
    ├── execution interfaces
    └── presentation interface

composition roots
├── perk CLI
│   ├── Python exterior
│   ├── Git/GitHub/Linear adapters
│   └── Pi exterior + evidence adapters
├── extension-v1 entrypoint
│   ├── TypeScript workflow
│   └── Pi-v1 session/execution/presentation adapters
└── future plugin-host entrypoints
    ├── the same TypeScript workflow
    └── host/session/view/drive adapters
```

Adapters import the interfaces they satisfy. Composition roots construct adapters and inject
them. Stable modules never import composition roots or concrete adapters.

## Import rules to enforce

1. Only Pi adapter packages may import `@earendil-works/pi-ai`,
   `@earendil-works/pi-coding-agent`, or `@earendil-works/pi-tui` at runtime.
2. The workflow library may import session, execution, and presentation interfaces, but no
   concrete adapter.
3. Concrete plan-provider adapters may import provider-neutral workflow types; the workflow
   library may not import Plannotator or Tombell adapters.
4. Python domain/exterior modules may not import `perk.cli`.
5. CLI and extension entrypoints are composition roots and may not be imported by lower modules.
6. Cross-plane data must be declared in `shared/` and validated independently by both planes.
7. Tests use the same external interface as production callers. Adapter-specific mechanics stay
   in adapter contract suites.

## Physical layout

Moving files is the final step, not the first. Prove the interfaces and import graph inside the
current tree before introducing workspace packaging.

A possible later layout is:

```text
shared/                         # single cross-plane contract source
packages/
  perk-workflow-ts/
  perk-session-ts/
  perk-execution-ts/
  perk-presentation-ts/
  perk-pi-v1-ts/
  perk-exterior-py/
  perk-pi-exterior-py/
  perk-evidence-py/
extension/
  index.ts                      # current npm composition root
src/perk/
  cli/                          # current wheel composition/presentation root
```

The workspace libraries can remain private and be bundled into `@mgiles/perk` and the `perk`
wheel. Separate publication should happen only if an independent consumer and compatibility
policy emerge.

## Migration sequence

### Phase 1: enforce direction before moving code

- Add import guards for the desired dependency graph.
- Move `UserFacingCliError` and application result types out of `perk.cli`.
- Move stage constants and provider-neutral result types out of concrete factories/adapters.
- Remove production cycles between factories and plan adapters.

Behavior remains unchanged. This phase makes later extraction mechanical rather than
architecture-changing.

### Phase 2: deepen session behavior

- Introduce `WorkflowSnapshot`, `WorkflowChange`, and `PerkSession`.
- Put custom-entry rebuild, verification, artifact provenance, fork, rewind, and context-window
  behavior behind it.
- Implement the in-memory and current branch-entry adapters.
- Move callers and tests to the `PerkSession` interface.

This is the highest-priority seam because both format 4 and typed values/lists approach it.

### Phase 3: deepen execution behavior

- Extract stage budget, terminal outcome, event projection, and terminating-tool policy from SDK
  construction.
- Keep SDK/session construction in the current Pi adapter.
- Promote the `ReportWave` lifecycle (`createReportWave`) as the WaveRunner implementation while
  keeping `WaveAdapter` internal (already waves-interior since Objective #2130, Node 2.1).
- Add interface-level suites for stage execution, read-only execution, and waves.

This prepares current SDK, durable Harness, server, and lane adapters to coexist.

### Phase 4: separate workflow contributions from registration

- Make doors and factories export host-neutral tool definitions and handlers.
- Let the v1 composition root translate them into `registerTool` and lifecycle registrations.
- Keep provider choice and workflow outcomes inside Perk.
- Test handlers through the workflow interface without constructing a Pi context.

The future plugin-host adapter can then contribute the same definitions through registries and
facets.

### Phase 5: deepen presentation

- Replace Pi-shaped targets in callers with semantic `SurfaceUpdate` and interaction requests.
- Keep current notification/status/footer/renderer calls inside the v1 adapter.
- Preserve explicit headless behavior through a headless adapter.
- Add a recording adapter and interface-level tests.

Future views/slots/web work becomes an adapter addition rather than a workflow rewrite.

### Phase 6: isolate Python Pi volatility

- Extract `SessionEvidenceReader` before adding format-4 support.
- Extract Pi convergence/launch behind `PiExterior`.
- Keep worktree, Git, remote-job, delivery, and issue-backend behavior in the exterior
  application.
- Express cross-plane run/session references in `shared/` where needed.

### Phase 7: add future adapters side by side

After Pi publishes stable contracts:

- implement values/list session persistence beside the branch-entry adapter;
- implement durable Harness drive beside the current SDK adapter;
- implement lane-backed waves beside the `pi-subagents` adapter;
- implement plugin-host facets beside extension v1; and
- implement views/slots beside current surfaces.

Run the same interface-level contract suites against both implementations. Remove a current
adapter only after the future one preserves all relevant Perk behavior in interactive, headless,
fork/reload, and recovery scenarios.

## Testing strategy

### The interface is the test surface

For each deep module, tests should construct the module through its external interface and assert
observable Perk results. They should not inspect the adapter's internal Pi calls unless they are
part of that adapter's own contract suite.

### Contract suites per seam

- `PerkSession`: memory, branch-entry, and later values/list adapters.
- `StageExecutor`: scripted, current SDK, and later Harness/server adapters.
- `WaveRunner` internals: memory, `pi-subagents`, and later lanes adapters.
- `PerkPresentation`: recording, headless, current TUI, and later view adapters.
- `SessionEvidenceReader`: golden v3, converted v3, native format 4, and SQLite/export fixtures.
- `PiExterior`: dry-run/current CLI and later manifest/server adapters.

The existing wave adapter contract suite is the model: one set of behavioral assertions runs
against the memory implementation and production RPC implementation.

### Replace, do not layer

Once an interface-level suite owns a behavior, delete shallow tests that merely pin the old call
graph. Retain adapter tests only for translation, compatibility, and error normalization. Tests
should survive moving implementation code within a deep module.

### Compatibility gates

Before replacing a current adapter, demonstrate:

- identical Perk result vocabulary;
- identical workflow state and artifact invariants;
- equivalent fork, rewind, compaction, reload, and reconnect behavior where applicable;
- equivalent cancellation and uncertain-effect handling;
- equivalent headless behavior; and
- no new Pi type imports outside adapter packages.

## Failure modes to avoid

### A giant `PiPort`

Storage, execution, presentation, host installation, and package convergence will mature at
different times. One large interface couples them and forces all callers to understand every Pi
change. Keep them as separate deep modules.

### Interface-only packages

A package containing dozens of types and pass-through methods creates navigation cost without
locality. The module owning an interface must also hide the behavior that makes the interface
valuable.

### Upstream vocabulary in stable types

Copying `SessionEntry`, `AgentEvent`, plugin-service contracts, or view frames into Perk merely
creates a second version of Pi's interface. Normalize into Perk facts at the adapter.

### Splitting by current folders

`extension/substrate` is not one cohesive library, and `doors`, `factories`, and `adapters` are
not clean dependency layers. Package moves must follow ownership and interface direction rather
than current paths.

### Splitting by future host

Server/session/TUI/web facets are deployment adapters. Perk workflow behavior must not fork by
host kind.

### A big-bang move

First make interfaces real in place, then enforce imports, then move files. Each phase should
leave current extension-v1 and CLI behavior operational.

## Success criteria

The decomposition is successful when:

- the TypeScript workflow library contains no runtime Pi imports;
- Python domain/exterior modules contain no `perk.cli` imports;
- `extension/index.ts` is primarily composition and registration;
- workflow state callers do not know whether state lives in custom entries or values/lists;
- execution callers do not know whether work runs through SDK sessions, Harness drive, a Pi
  server, or lanes;
- presentation callers do not know whether output targets a local TUI, remote view, web client,
  or headless log;
- learn/audit callers do not know whether evidence came from v3 JSONL, format-4 JSONL, SQLite, or
  a normalized export;
- current and future adapters run the same interface-level contract suites; and
- deleting any proposed library would force its hidden complexity back into several callers.

That last deletion test is the guard against decomposition for its own sake. The purpose is not
more packages; it is stable, high-leverage Perk interfaces with Pi-specific change concentrated
in replaceable adapters.
