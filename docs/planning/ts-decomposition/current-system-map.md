# Current TypeScript system map

> **Snapshot:** Perk commit `3f7f84c9`, inspected 2026-08-23. This document
> describes the current `extension/` implementation. It is evidence for
> [the decomposition decision](memo.md), not a target contract.

The upstream comparison is frozen separately in
[`upcoming-pi-changes-memo.md`](../upcoming-pi-changes-memo.md). This map uses
its maturity labels only to identify TypeScript volatility; it does not treat
unreleased Pi work as current Perk behavior.

## Method

The production selector matches the source guards and npm exclusion rules:

```text
extension/**/*.ts
minus extension/**/*.test.ts
minus extension/testing/**
```

The file census and line counts are reproducible with:

```sh
rg --files extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**'
rg --files extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**' | xargs wc -l
```

Structural searches use ast-grep and apply the same production selector to the
JSON result. For example:

```sh
ast-grep run --kind import_statement --lang ts --json extension
ast-grep run --pattern 'pi.registerTool($$$ARGS)' --lang ts --json extension
ast-grep run --pattern 'registerPerkCommand($$$ARGS)' --lang ts --json extension
ast-grep run --pattern 'pi.on($$$ARGS)' --lang ts --json extension
```

When using JSON output, exclude matches whose file ends in `.test.ts` or
starts with `extension/testing/`. Counts in this document were checked against
the literal registration vocabulary as well as structural queries, because
some commands pass through a helper while `/btw` registers directly.

The local import graph was computed from static import declarations and
re-exports:

```sh
ast-grep run --kind import_statement --lang ts --json extension
ast-grep run --pattern 'export { $$$NAMES } from "$SOURCE"' --lang ts --json extension
```

For each production declaration, resolve a relative specifier as an exact path,
a `.ts` path, or a directory `index.ts`; then count both declarations and
distinct source-to-target edges. Tarjan's algorithm over the resolved graph
finds strongly connected components. There are no production
`export * from` declarations at this snapshot.

The graph algorithm is described rather than checked in as a one-off analyzer:
implementation work should either repeat these steps or add a maintained guard
with tests. Counts are evidence at this commit, not architectural constants.

## Headline census

| Measure | Current value |
| --- | ---: |
| Production TypeScript files | 101 |
| Production lines | 37,310 |
| Relative import/re-export declarations | 518 |
| Distinct resolved local source-to-target edges | 517 |
| Files importing a Pi package | 56 |
| Pi import declarations | 61 |
| Files with runtime Pi imports | 9 |
| `pi.registerTool(...)` calls | 37 across 25 files |
| `registerPerkCommand(...)` calls | 29 |
| Effective feature commands | 30, including direct `/btw` |
| `pi.registerFlag(...)` calls | 2 |
| `pi.registerShortcut(...)` calls | 1 |
| `pi.on(...)` calls | 33 across 14 files |
| `pi.appendEntry(...)` calls | 10 across 5 files |
| Multi-file production cycles | 2 |

There are two source call sites for `pi.registerCommand(...)`: the shared
command helper and the direct `/btw` registration. Counting those two sites as
two commands would be wrong. The helper expands to 29 feature registrations,
and `/btw` makes the effective total 30.

The nine runtime Pi importers are `selfcheck.ts`, `planTitle.ts`,
`structuredOutput.ts`, `surfaces.ts`, both `/btw` files, both worker
modules, and `workerMain.ts`. Most of the remaining Pi importers use only
`ExtensionAPI`, `ExtensionContext`, or related host types. Type-only coupling
does not affect runtime resolution, but it still makes host vocabulary part of
feature interfaces and tests.

## Current callers and Pi pressure

There are two current TypeScript composition roots:

- `extension/index.ts` binds the interactive extension-v1 host;
- `extension/workerMain.ts` launches the headless SDK worker.

There is no current Pi application-host caller. Configuration is also not one
activation-global value: callers load `.perk/config.toml` and the local overlay
from the active `ctx.cwd` at invocation or lifecycle time. A target config
module must preserve that lifetime.

The upstream direction approaches six current seams:

| Current TypeScript pressure point | Future Pi direction | Maturity | Architectural reading |
| --- | --- | --- | --- |
| `workflowState.ts` branch patches and rebuild | typed values/lists | implemented on unreleased `dev` | candidate storage behind `WorkflowSession` after field classification |
| `activeContextWindow()` and `firstKeptEntryId` | format-4 `retainedTail` | implemented on unreleased `dev` | direct TypeScript compatibility risk behind `PromptEvidence` |
| `worker.ts` SDK lifecycle and counters | durable drive and usage ledger | in progress | candidate adapters behind `StageRunner` |
| `reportWave.ts` RPC and child sessions | Pi lanes | experimental | candidate execution behind `ReportWave` |
| `surfaces/` imperative TUI calls | views and slots | exploratory | candidate rendering adapter with late-attach proof |
| extension-v1 registration and providers | manifests, facets, services, registries | exploratory | future composition placement, not a stable feature interface |

The Python session-audit parser is outside this TypeScript plan. Format-4 work
here concerns only the context and state projections consumed by `extension/`.

## Directory distribution

| Current directory | Files | Lines | Present role |
| --- | ---: | ---: | --- |
| `doors/` | 27 | 12,436 | Commands, tools, delivery, review, and learning flows |
| `waves/` | 16 | 7,124 | Wave engine, adapters, manifests, and reducers |
| `factories/` | 15 | 5,562 | Gist, plan, and objective authoring |
| `substrate/` | 27 | 5,528 | State, config, resources, paths, registration, and result helpers |
| `vendor/` | 3 | 1,689 | `/btw` and whimsical host extensions |
| `hunkFeedback/` | 4 | 1,582 | Hunk inbox, receiver, storage, and publisher |
| `worker/` | 2 | 1,193 | SDK stage drive and read-only child execution |
| Root | 2 | 868 | Interactive and worker composition roots |
| `surfaces/` | 3 | 830 | TUI formatting, reporting, footer, and renderers |
| `adapters/` | 2 | 498 | Plannotator and Tombell plan-provider bridges |

These directory names aid navigation, but they are not dependency strata.
`doors/` and `factories/` each mix registration, workflow policy, state,
execution, providers, and result projection.

## Import graph

### Highest-volume directory edges

| Edge | Imports |
| --- | ---: |
| `doors → substrate` | 149 |
| `factories → substrate` | 77 |
| `doors → waves` | 31 |
| `substrate → substrate` | 29 |
| `doors → surfaces` | 27 |
| `root → doors` | 26 |
| `doors → doors` | 24 |
| `waves → waves` | 23 |
| `factories → factories` | 21 |
| `root → factories` | 13 |
| `factories → surfaces` | 11 |
| `doors → factories` | 10 |

The pattern is feature behavior reaching sideways and downward into many
helpers rather than calling a coherent feature interface. The
`doors → factories` edge is especially revealing: door and factory describe
delivery form, not ownership.

### Highest fan-in

| Module | Production importers | What the fan-in exposes |
| --- | ---: | --- |
| `surfaces/report.ts` | 45 | Many flows depend on a structural Pi-shaped report target |
| `substrate/workflowState.ts` | 40 | State, context, identity, and persistence are shared directly |
| `substrate/cache.ts` | 28 | Workflow layout and artifacts are broadly visible |
| `substrate/command.ts` | 25 | Registration and presentation pass through one helper |
| `substrate/prompts.ts` | 25 | Prompt rendering is common infrastructure |
| `substrate/result.ts` | 24 | Pi result projection is visible in feature code |
| `substrate/bindingDelivery.ts` | 21 | Host lifecycle and context delivery are shared across flows |
| `substrate/config.ts` | 21 | Leaf modules consume configuration parsing |
| `waves/reportWave.ts` | 21 | Report waves are a proven shared mechanism |
| `substrate/coldDoor.ts` | 20 | Python process and JSON details are visible at feature leaves |

`reportWave.ts` passes the deep-module test: removing it would spread
capability checks, spawn and settle races, cancellation, completeness,
normalization, aggregation, and receipts across many review and learning
flows.

`report.ts` is useful but shallower. Its interface mirrors host facts such as
`hasUI`, `mode`, and `ui.notify`; features still own the meaning of what is
reported.

### Highest fan-out

| Module | Local dependencies | Present responsibility spread |
| --- | ---: | --- |
| `index.ts` | 56 | Composition, lifecycle, state, surfaces, providers, and all registrations |
| `factories/planReview.ts` | 17 | Several authoring reviews, UI choice, saving, edits, and results |
| `doors/address.ts` | 15 | Registration, review wave, Python call, state, and presentation |
| `doors/objectiveReviewBrowser.ts` | 15 | Provider interaction, wave, draft/save policy, and presentation |
| `doors/learn.ts` | 14 | Capture, waves, artifacts, state, exterior calls, and results |
| `doors/planReviewBrowser.ts` | 14 | Provider interaction, wave, drafts, state, and presentation |
| `factories/objectivePlan.ts` | 14 | Selection, exterior calls, claim, gating, prompts, and lifecycle |

These are candidates for deeper vertical ownership. The counts do not prove
that every listed file should become its own module.

### Production cycles

```text
substrate/config.ts ⇄ substrate/bindings.ts
factories/planReview.ts ⇄ adapters/planAdapterPlannotator.ts
```

The config cycle exists because configuration consumes binding parsing while
binding vocabulary also lives with configuration. Parsing and defaults should
move to `config/`; Pi binding metadata should remain in `pi/`.

The plan-review cycle is an ownership inversion. Provider-neutral authoring
policy should depend on a `DraftReviewer` role. The Plannotator adapter should
implement that role and be supplied at composition.

## Binding topology

Registrations are distributed across feature leaves rather than concentrated
behind feature interfaces. Current tool definitions can include:

- runtime schemas;
- prompt snippets and prompt guidelines;
- execution mode and availability rules;
- `onUpdate` progress;
- host result and presentation shapes.

Commands have their own string argument and completion contract. Flags,
shortcuts, and hooks have still different forms. These facts do not support a
single contribution shape. They support explicit Pi adapters that preserve
each host form while calling typed feature operations.

The placement and meaning of model-facing prose are different concerns.
Features should own the relevant Prose units, Prompt concerns, audience, and
order. Extension-v1 bindings currently place them in host fields. A future Pi
registry may place them differently without becoming their semantic owner.

The 33 hooks cover session start, tree changes, shutdown, agent start and
settle, context, turn start and end, tool calls, switching, and forking. Some
hooks compose session state; others gate tools or update presentation. A
catalog containing only a name and callback would omit these lifecycle facts.
The future Pi application registry may model more of those facts, but it
remains a host adapter concern rather than a Perk-wide invocation catalog.

Tool gating also governs an enumerated set of borrowed-package tools, not only
the 37 Perk registrations. It derives access from workflow mode and stage and
resynchronizes on host lifecycle events. This is Pi-side access enforcement:
feature modules should not inherit the borrowed-tool census merely to become
host-neutral.

## Interactive composition and lifecycle

[`extension/index.ts`](../../../extension/index.ts) is 719 lines and is both
composition root and session-lifecycle coordinator. It currently:

- constructs tool gating, scratch state, vendor extensions, providers, status,
  renderers, and the Hunk receiver;
- registers doors and factories individually;
- handles session-start claim, reload, fork, child adoption, run-id minting,
  handoff consumption, plan-ref reconciliation, pointer capture, gate
  synchronization, footer installation, and status;
- handles session-tree rebuild and synchronization; and
- disposes session-owned resources on shutdown.

The ordering is load-bearing: establish before consume, synchronize gates
before fallible reconciliation, and perform strict linkage reads before pointer
capture. That policy should be expressed through `WorkflowSession` and
session-specific Pi adapters. It does not justify moving every registration
behind one application object.

The v1 composition root should load `cwd`-scoped dependencies and call named
installers directly. The future Pi application host will distribute state,
execution, providers, and presentation across facets. Neither shape justifies
a universal Perk application object.

## Workflow state and Prompt evidence

[`workflowState.ts`](../../../extension/substrate/workflowState.ts) is a
341-line mixed module with 40 importers. It owns or exposes:

- the `WorkflowState` record and artifact pointers;
- branch-entry structural mirrors and `branchOf()` casting;
- per-field last-write-wins rebuild;
- append, rebuild, read-back verification, and reporting;
- claim, fork, adoption, and mint decisions;
- plan-ref equality and launched-stage resolution; and
- `activeContextWindow()`, including the current compaction rule.

Durable state and live conversation evidence happen to be derived from a Pi
branch today. They do not share authority or lifecycle.

The durable half supports a `WorkflowSession` seam: identity, validated state,
verified updates, artifacts, and provenance. The live half supports a
`PromptEvidence` value produced by a Pi context adapter. Absence of live
evidence, including an unsupported projection, must not be treated as absence
of durable state.

Current delivery also distinguishes direct custom context or submitting-prompt
evidence from prose quoted by a compaction summary. Stage bindings, command
bindings, and agent scratch have different trigger, run, and audience rules.
A target `PromptEvidence` value must retain those facts and the relevant
Session shape; a bare set of marker
strings would be insufficient.

`activeContextWindow()` directly reads the v3 `firstKeptEntryId` compaction
field. Format 4 materializes `retainedTail` instead. The future adapter must
consume a stable TypeScript context projection rather than teaching feature
code either physical form. Compaction itself does not imply unavailable
evidence.

The current append path verifies state by reading it back. It does not expose a
general storage revision or compare-and-swap primitive. A target design must
preserve verified read-back and must not invent revision or conflict guarantees
the backing cannot enforce.

Before any field moves to Pi values or lists, classify its authority, need for
history, fork inheritance, model visibility, verification tier, and artifact
relationship. A future storage adapter may remain hybrid; “Pi has values” is
not evidence that every custom entry should become one.

## Feature ownership hypotheses

The following groups are migration hypotheses grounded in repeated policy.
Their precise public interfaces must be discovered by moving one use case at a time.
They are not four implementations of a shared protocol.

### Authoring

Gist, plan, and objective flows repeat a recognizable progression: prepare
context, maintain a validated draft, choose a review provider, interpret review
or direct edits, save canonically, update linkage, and release a gate only
after success.

`planReview.ts` is the strongest signal. Its 1,237 lines span several draft
types, saving, first-party UI, Plannotator decisions, direct edits, wave launch,
and Pi projection. Authoring policy belongs together; provider events and Pi
registration do not.

### Delivery

Submit, address, ready, land, CI, commit or compact, Delivery train operations, and Hunk
feedback share transition ordering and external-effect semantics. Today each
door composes some mixture of Python argv, decoding, state updates, reporting,
and Pi registration.

Durable Git, GitHub, and Linear policy remains in the Python exterior. The
TypeScript feature should own session-interior orchestration and typed
semantic requests to that exterior.

### Code review

Fixed and dynamic review waves, browser and terminal review, stack review,
annotations, and posting share target freshness, completeness, evidence, and
posting policy. Current files are divided primarily by host surface and command
shape.

Code review should own subjects, findings, and disposition rules. Human
surfaces, reviewer providers, and report execution remain adapters.

### Learning

Capture, learn-code, learn-docs, audit, harvest, and dream share
untrusted-evidence handling, run-bound manifests, completeness, reduction, and
artifact validation. They span doors, factories, waves, substrate, and the
Python exterior.

Learning should own those meanings while delegating analyst execution to
`ReportWave` and durable persistence to typed exterior operations.

## Execution

[`worker.ts`](../../../extension/worker/worker.ts) is 899 lines. It combines
stable Perk concepts—budgets, terminal signals, run outcomes, and event
projection—with volatile SDK details such as model resolution, session
construction, listeners, prompting, and disposal.

[`readOnlySession.ts`](../../../extension/worker/readOnlySession.ts) can
construct a separate SDK session, run one inspect-only task, verify a handoff,
cap model-visible text, and normalize errors. At this snapshot,
`runReadOnlyChild()` and `createReadOnlySession()` have no production caller;
only the model-visible capping helpers are imported by production code. The
unused runner therefore does not prove a separate target interface.

[`reportWave.ts`](../../../extension/waves/reportWave.ts) is 845 lines and
already demonstrates a deep mechanism with memory and RPC adapters and shared
contract tests. Its public vocabulary still exposes some transport details,
including workflow scripts, pings, event channels, async identifiers, and
directories. Those should become private to the RPC adapter while typed report
outcomes remain public.

The current `WaveLane` name also collides with Pi Harness lanes without proving
identity. Target feature vocabulary should call one logical request a
`ReportAssignment`; a future Pi-lane adapter decides how assignments map to
host lanes.

Current report-wave pending state includes module-global state. That creates a
session-lifecycle risk and should become wave- or session-owned.

Stage execution and report waves must stay separate. A stage is registry-bound,
mutation-aware, and terminal-oriented. A report wave is coverage- and
aggregation-oriented.

Durable Pi operations and the usage ledger may eventually replace the worker's
raw SDK drive and process-local accounting. They do not replace Perk's stage
Prompt assembly, terminating-tool contract, budget policy, workflow run events,
or terminal outcome. Those stable meanings belong in `StageRunner`; operation
IDs, recovery records, and usage rows remain adapter details.

The current `run_ci` path emits incremental `onUpdate` progress. This is
direct evidence that a generic final-result-only operation would lose behavior.
Typed delivery progress should cross the feature seam and be translated by its
Pi binding.

## Presentation and host extras

The surfaces guard already confines rich UI calls and TUI imports to
[`surfaces/`](../../../extension/surfaces), with the named `/btw` exception.
That physical rule should remain.

The dependency direction needs improvement:

- feature operations return typed outcomes and progress;
- Pi rendering adapters decide notifications, reports, status, footer, and
  working messages;
- the surfaces module performs the sanctioned host calls.

There is no need for a universal presentation bus.

The future application host adds a lifetime requirement rather than a new
feature dependency: standing status, footer, widget, and report state must be
reconstructible when a client attaches after work has begun or a plugin
generation reloads. Transient progress may remain transient. If views and
slots stabilize, they should replace only the surfaces adapter.

`vendor/btw/` and `vendor/whimsical/` are host extensions, not Perk workflow
features. They may remain composed directly by the Pi extension.

## Python exterior seam

[`coldDoor.ts`](../../../extension/substrate/coldDoor.ts) usefully
concentrates process mechanics: binary resolution, scratch-file stdin,
cancellation, exit and envelope handling, strict JSON parsing, and version-skew
diagnostics. Its current interface exposes argv, a Pi execution host, and
caller-owned decoders to about 20 importers.

Features should instead depend on narrow semantic operations such as saving a
plan, publishing a change, or capturing learning. A private process adapter may
reuse the existing transport mechanics. Feature code should not know command
spelling, exit codes, or stdout envelopes.

Any request or outcome interpreted by both planes remains a serialized contract
in `shared/` and is validated independently. Ordinary TypeScript-only types do
not move there.

## Existing tests and guards

Useful migration assets already exist:

- the recursive real-Pi harness in `extension/testing/harness.ts`;
- memory/RPC report-wave adapter contract coverage;
- focused tests for reducers, codecs, budgets, and outcomes;
- rich-UI, import, path, cache, cold-door, write, and Pi-compat guards;
- packaging tests for shipped source, workspaces, dependencies, and entrypoint
  paths; and
- worker unit and end-to-end tests.

The weakness is primary test surface. Many feature tests call `register*`,
synthesize Pi contexts, and inspect callbacks because registration is the only
public route.

After a vertical slice, its behavior should be tested by calling the typed
feature operation directly. Keep the Pi harness for registration metadata,
input translation, lifecycle adaptation, progress, result rendering, headless
behavior, and surfaces.

## Packaging constraints

[`package.json`](../../../package.json) and packaging tests establish:

- `@mgiles/perk` ships raw TypeScript under `extension/`, plus `shared/`
  and `prompts/`;
- Pi loads only `./extension/index.ts`;
- production code has zero runtime dependencies and may use only Node,
  relative, and approved host imports;
- the only workspaces are `docs/site` and `tools/prose-review`;
- tests and `extension/testing/` are excluded from the npm tarball;
- TypeScript uses bundler resolution and explicit `.ts` imports; and
- the Python runner resolves `extension/workerMain.ts` by path.

These facts favor one in-tree logical decomposition. Multiple npm packages
would add build, install, resolution, and compatibility work without an
independent consumer.

## Limits of this map

Static imports show dependency pressure, not semantic cohesion. Registration
counts show host spread, not how many domain operations should exist.
Line counts identify review targets, not desired module sizes. The four feature
areas are therefore starting ownership hypotheses, to be accepted or corrected
by vertical migration.

This map also does not claim that every Pi type import is harmful. Pi types are
appropriate in adapters and composition roots; the architectural problem is
their use as the only callable interface to feature policy.

## Architectural conclusion

The system already contains useful deep mechanisms, especially report waves
and process transport. Its missing seam is not one host-neutral application
dispatcher. It is a set of typed feature operations that can be called without
Pi.

The highest-leverage change is to prove that seam with one vertical authoring
slice, place durable invariants behind `WorkflowSession`, derive
`PromptEvidence` at the Pi edge, and isolate stage and report execution before
the Pi substrate changes. Extension v1 remains the bridge; the destination
distributes adapters across Pi application facets without changing feature
interfaces. Physical reorganization should follow ownership, not precede it.
