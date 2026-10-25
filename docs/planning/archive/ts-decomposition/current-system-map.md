# Current TypeScript system map

> **Snapshot:** Perk commit `95ff7cc7`, inspected 2026-08-24. This document
> describes the current `extension/` implementation. It is evidence for
> [the decomposition decision](memo.md), not a target contract. The refresh
> commits themselves are docs-only changes under `docs/` and do not invalidate
> the `extension/` facts measured at the stamped commit.

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
| Production TypeScript files | 102 |
| Production lines | 38,063 |
| Relative import/re-export declarations | 521 |
| Distinct resolved local source-to-target edges | 520 |
| Files importing a Pi package | 56 |
| Pi import declarations | 61 |
| Files with runtime Pi imports | 9 |
| `pi.registerTool(...)` calls | 37 across 25 files |
| `registerPerkCommand(...)` calls | 29 |
| Effective feature commands | 31, including direct `/btw` |
| `pi.registerFlag(...)` calls | 2 |
| `pi.registerShortcut(...)` calls | 1 |
| `pi.on(...)` calls | 33 across 14 files |
| `pi.appendEntry(...)` calls | 10 across 5 files |
| Multi-file production cycles | 2 |

There are two source call sites for `pi.registerCommand(...)`: the shared
command helper and the direct `/btw` registration. Counting those two sites as
two commands would be wrong. The helper's 29 source call sites also do not map
one-to-one onto commands: the learn-factory door's single call site
(`doors/learnFactory.ts`) is invoked twice at composition — once per kind
(`/learn-docs`, `/learn-code`) — so the helper registers 30 runtime commands,
and `/btw` makes the effective total 31. (The previous snapshot recorded 30
effective commands; that was an undercount of the same code shape, not drift —
both learn-factory invocations already existed at `3f7f84c9`.)

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
| `doors/` | 27 | 12,824 | Commands, tools, delivery, review, and learning flows |
| `waves/` | 16 | 7,124 | Wave engine, adapters, manifests, and reducers |
| `substrate/` | 28 | 5,893 | State, config, resources, paths, registration, and result helpers |
| `factories/` | 15 | 5,562 | Gist, plan, and objective authoring |
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
| `doors → substrate` | 150 |
| `factories → substrate` | 77 |
| `doors → waves` | 31 |
| `substrate → substrate` | 30 |
| `doors → surfaces` | 27 |
| `root → doors` | 26 |
| `doors → doors` | 25 |
| `waves → waves` | 23 |
| `factories → factories` | 21 |
| `root → factories` | 13 |
| `factories → surfaces` | 11 |
| `root → substrate` | 10 |
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
| `substrate/cache.ts` | 29 | Workflow layout and artifacts are broadly visible |
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
| `doors/objectiveStack.ts` | 14 | Stack read/drive tools, exterior calls, state, and presentation |
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

### Later-node premise confirmations (Node 1.1)

Four premises later decomposition nodes build on were re-verified at the
stamped commit. All four pass:

| Premise (consumer) | Result at `95ff7cc7` |
| --- | --- |
| The `substrate/config.ts ⇄ substrate/bindings.ts` cycle exists exactly at `bindings.ts`'s type-only `import type { TomlScalar } from "./config.ts"` edge (Node 1.2) | **Pass** — `bindings.ts` carries that type-only import; `config.ts` imports `parseUserBindings` and `SkillBinding` (runtime) from `bindings.ts` |
| `runReadOnlyChild()` / `createReadOnlySession()` in `worker/readOnlySession.ts` have no production caller (Node 3.1) | **Pass** — production code imports only the model-visible capping helpers (`capForModel` in `worker/worker.ts`; `capForModel` + `DEFAULT_MODEL_VISIBLE_CAP` in `doors/ciExecutor.ts`); the only other reference is a comment |
| The `factories/planReview.ts ⇄ adapters/planAdapterPlannotator.ts` cycle exists via the adapter's type-only `import type { ReviewOutcome }` edge (Node 4.1) | **Pass** — the adapter carries `import type { ReviewOutcome } from "../factories/planReview.ts"`; `planReview.ts` value-imports the adapter |
| The two door modules with module-level pending slots are `doors/reviewWaveTools.ts` and `doors/draftReviewWaveTools.ts` (Node 5.1) | **Pass** — both carry a module-scope `let pending`; `doors/commitCompact.ts`'s `pending` is function-scoped. (Other module-scope slots exist — `doors/annotationPush.ts`'s surface/ledger state, `doors/prReview.ts`'s `reviewWaveState`, `doors/draftReviewWaveTools.ts`'s `context` — but the *pending-wave* slots are exactly the two named) |

A failed confirmation here would be material drift for the objective roadmap
and must be surfaced for reconciliation, never absorbed.

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
each host form while calling typed feature operations. The frozen
per-registration detail — one row per tool, command, flag, shortcut, and
hook, with the nine binding facts — lives in
[`binding-inventory.md`](binding-inventory.md), stamped at the same commit as
this map.

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
343-line mixed module with 40 importers. It owns or exposes:

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

Run fresh at the stamped commit: `extension/surfacesGuard.test.ts` passes
(2/2 — it confines rich-UI calls (`ctx.ui.*`, `setStatus`/`setWidget`/
`setFooter`/`setWorkingMessage`, `pi.registerEntryRenderer`) and
`@earendil-works/pi-tui` imports to the surfaces module, with `vendor/btw/`
the one named exception); the six other source guards
(`bareImportGuard`, `cacheGuard`, `coldDoorGuard`, `pathsGuard`,
`piAiCompatGuard`, `writeGuard`) pass 7/7; and the packaging suite
(`tests/test_packaging.py`) passes 19/19.

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

An `npm pack --dry-run` at the stamped commit packs 219 entries: the 102
production files under `extension/`, 84 under `prompts/`, 31 under `shared/`,
plus `README.md` and `package.json`. The `pi.extensions` entrypoint is
`./extension/index.ts`; `dependencies` is absent (zero runtime dependencies);
the only workspaces are `docs/site` and `tools/prose-review`.

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

## Objective #2130 baseline (commit `53fe2d7d`, measured 2026-09-02)

> **Update (Objective #2130, Node 5.1, 2026-09-04):** the final measurement is **taken** —
> node 5.1 re-ran these four pipelines verbatim at the final train state (`cead475a`); the
> before/after tables, the file-by-file importer and export deltas, and the named rationale
> for the remaining excess live in `docs/design/archive/ts-seam-deepening-closeout.md` §2.
> This section stays as-stamped: the pinned before-snapshot. One expectation moved with the
> train: pipeline 4's calibration row, `extension/worker/stageExecution.ts`, reports
> 13 declarations / 16 names at the final state (node 4.1's landed narrowing of the 26 / 30
> pinned below) — the closing record's calibration gate carries the updated numbers.

This section is objective #2130's quantitative baseline, measured independently of — and
without modifying — the frozen #2083-era snapshot above (`95ff7cc7`). Every measure
records its complete, copy-paste-runnable command followed by the value measured at the
stamped commit; objective #2130 node 5.1 re-runs these exact pipelines for the final
before/after comparison. `main` moved one docs-only commit past the #2083 train tip
(`a5dc757e` → `53fe2d7d`, a planning-doc addition) before this measurement; no
`extension/` content changed, and the headline values reproduce the Node 7.5 final
structural ledger exactly.

### 1. Production census and LOC (incl./excl. vendor)

```sh
rg --files extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**' | wc -l
rg -c '' extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**' | awk -F: '{s+=$2} END {print s}'
rg --files extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**' -g '!extension/vendor/**' | wc -l
rg -c '' extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**' -g '!extension/vendor/**' | awk -F: '{s+=$2} END {print s}'
```

Measured: **136 files / 42,376 LOC** including vendor; **133 files / 40,687 LOC**
excluding vendor (vendor = 3 files / 1,689 LOC). Matches the Node 7.5 final ledger.

### 2. Comment-only share

A production line is comment-only iff it matches `^\s*(//|/\*|\*)`. This classifier is
an approximation — a `*`-led line inside a template string would miscount — accepted and
stated.

```sh
rg -c '^\s*(//|/\*|\*)' extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**' | awk -F: '{s+=$2} END {print s}'
```

Measured: **10,326** comment-only lines (≈ 24.4% of the 42,376 production lines).

### 3. Pi importers

The selector is the import-declaration prefix `from "@earendil-works`. A bare
`@earendil-works` token grep over-counts (55 files at this commit — comment and string
mentions included) and is recorded as NOT the selector.

```sh
rg -l 'from "@earendil-works' extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**' | wc -l
```

Measured: **52** Pi importers. Matches the Node 7.5 final ledger.

### 4. Export inventory

Counting semantics: one top-level export statement = one **declaration**; **names** =
symbols exposed (`export { a, b }` = 2, and the same re-exported form counts its names;
`export const a = …, b = …` counts each declarator; `export function`/`class`/`type`/
`interface`/`enum` = 1; `export default` / `export =` = 1; a namespace re-export
`export * from` / `export * as ns from` counts as a declaration and is reported
explicitly — none exist at this commit). The per-file table lists every production file
with ≥ 1 export declaration; zero-export files are omitted from the table but included
in the file total (at this commit every production file carries ≥ 1 export declaration,
so the table has 136 rows). The table is generated by the script below (which uses the
repository's existing `typescript` devDependency), never hand-edited.

Calibration gate, run before recording: the `extension/worker/stageExecution.ts` row must
report 26 declarations / 30 names — the objective's pinned example; a mismatch means the
script or the objective claim is wrong, and the discrepancy is investigated and recorded,
never papered over. **Passed at this commit** (26 / 30).

```sh
node --input-type=module - <<'EOF'
import { readFileSync } from "node:fs";
import { execSync } from "node:child_process";
import ts from "typescript";
const files = execSync(
  "rg --files extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**'",
  { encoding: "utf8" },
).trim().split("\n").sort();
let totD = 0, totN = 0, stars = 0;
const rows = [];
for (const f of files) {
  const src = ts.createSourceFile(f, readFileSync(f, "utf8"), ts.ScriptTarget.Latest, true);
  let d = 0, n = 0;
  for (const st of src.statements) {
    if (ts.isExportDeclaration(st)) {
      d++;
      if (st.exportClause && ts.isNamedExports(st.exportClause)) n += st.exportClause.elements.length;
      else stars++;
      continue;
    }
    if (ts.isExportAssignment(st)) { d++; n++; continue; }
    const mods = ts.canHaveModifiers(st) ? ts.getModifiers(st) : undefined;
    if (!mods?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)) continue;
    d++;
    if (ts.isVariableStatement(st)) n += st.declarationList.declarations.length;
    else n += 1;
  }
  if (d > 0) rows.push([f, d, n]);
  totD += d; totN += n;
}
console.log("| File | Export declarations | Exported names |");
console.log("| --- | ---: | ---: |");
for (const [f, d, n] of rows) console.log(`| ${f} | ${d} | ${n} |`);
console.log(`TOTAL: files=${files.length} declarations=${totD} names=${totN} star-exports=${stars}`);
EOF
```

Measured totals: **136 files with exports / 1,146 export declarations / 1,155 exported
names / 0 star-exports**.

| File | Export declarations | Exported names |
| --- | ---: | ---: |
| extension/authoring/gist/draft.ts | 11 | 11 |
| extension/authoring/gist/prose.ts | 6 | 6 |
| extension/authoring/gist/review.ts | 4 | 4 |
| extension/authoring/gist/save.ts | 7 | 7 |
| extension/authoring/objective/draft.ts | 10 | 10 |
| extension/authoring/objective/dreamReportGate.ts | 6 | 6 |
| extension/authoring/objective/planning.ts | 8 | 8 |
| extension/authoring/objective/prose.ts | 10 | 10 |
| extension/authoring/objective/review.ts | 5 | 5 |
| extension/authoring/objective/save.ts | 11 | 11 |
| extension/authoring/plan/draft.ts | 4 | 4 |
| extension/authoring/plan/prose.ts | 4 | 4 |
| extension/authoring/plan/review.ts | 7 | 7 |
| extension/authoring/plan/save.ts | 10 | 10 |
| extension/authoring/plan/source.ts | 3 | 3 |
| extension/codeReview/automated.ts | 18 | 18 |
| extension/codeReview/submission.ts | 11 | 11 |
| extension/delivery/address.ts | 8 | 8 |
| extension/delivery/ci.ts | 13 | 13 |
| extension/delivery/commitCompact.ts | 8 | 8 |
| extension/delivery/ready.ts | 10 | 10 |
| extension/delivery/stackConflict.ts | 9 | 9 |
| extension/delivery/stackObjective.ts | 2 | 2 |
| extension/delivery/stackReconcile.ts | 4 | 4 |
| extension/delivery/submit.ts | 13 | 13 |
| extension/doors/draftReviewWaveTools.ts | 13 | 13 |
| extension/doors/lifecycleGates.ts | 4 | 4 |
| extension/doors/objectiveReviewBrowser.ts | 7 | 7 |
| extension/doors/pendingWave.ts | 4 | 4 |
| extension/doors/planReviewBrowser.ts | 7 | 7 |
| extension/doors/plannotatorHandoff.ts | 25 | 25 |
| extension/doors/selfcheck.ts | 19 | 19 |
| extension/hunkFeedback/inbox.ts | 17 | 17 |
| extension/hunkFeedback/perkFeedback.ts | 17 | 17 |
| extension/hunkFeedback/receiver.ts | 11 | 11 |
| extension/hunkFeedback/store.ts | 18 | 18 |
| extension/index.ts | 1 | 1 |
| extension/learning/analystWave.ts | 8 | 8 |
| extension/learning/audit.ts | 14 | 14 |
| extension/learning/capture.ts | 8 | 8 |
| extension/learning/containment.ts | 4 | 4 |
| extension/learning/dream.ts | 21 | 21 |
| extension/learning/dreamAnalysis.ts | 3 | 3 |
| extension/learning/dreamReducer.ts | 18 | 18 |
| extension/learning/dreamReport.ts | 4 | 4 |
| extension/learning/harvest.ts | 12 | 12 |
| extension/learning/prose.ts | 3 | 3 |
| extension/learning/routing.ts | 5 | 5 |
| extension/pi/v1/codeReview/automated.ts | 5 | 5 |
| extension/pi/v1/codeReview/browser.ts | 7 | 7 |
| extension/pi/v1/codeReview/checkout.ts | 8 | 8 |
| extension/pi/v1/codeReview/reviewWave.ts | 8 | 8 |
| extension/pi/v1/codeReview/stack.ts | 17 | 17 |
| extension/pi/v1/codeReview/submit.ts | 5 | 5 |
| extension/pi/v1/codeReview/terminal.ts | 5 | 5 |
| extension/pi/v1/delivery/address.ts | 6 | 6 |
| extension/pi/v1/delivery/ci.ts | 7 | 7 |
| extension/pi/v1/delivery/commitCompact.ts | 3 | 3 |
| extension/pi/v1/delivery/land.ts | 4 | 4 |
| extension/pi/v1/delivery/ready.ts | 2 | 2 |
| extension/pi/v1/delivery/stackDrive.ts | 3 | 3 |
| extension/pi/v1/delivery/stackLand.ts | 4 | 4 |
| extension/pi/v1/delivery/stackRecover.ts | 4 | 4 |
| extension/pi/v1/delivery/stackStatus.ts | 3 | 3 |
| extension/pi/v1/delivery/stackSync.ts | 8 | 8 |
| extension/pi/v1/delivery/submit.ts | 5 | 5 |
| extension/pi/v1/gist.ts | 7 | 7 |
| extension/pi/v1/learning/audit.ts | 4 | 4 |
| extension/pi/v1/learning/dream.ts | 3 | 3 |
| extension/pi/v1/learning/factory.ts | 3 | 3 |
| extension/pi/v1/learning/harvest.ts | 4 | 4 |
| extension/pi/v1/learning/learn.ts | 5 | 5 |
| extension/pi/v1/objective.ts | 10 | 10 |
| extension/pi/v1/objectiveAuthoring.ts | 11 | 11 |
| extension/pi/v1/objectivePlanning.ts | 10 | 10 |
| extension/pi/v1/objectiveReview.ts | 5 | 5 |
| extension/pi/v1/plan.ts | 5 | 5 |
| extension/pi/v1/planReview.ts | 15 | 15 |
| extension/pi/v1/planTitle.ts | 5 | 5 |
| extension/pi/v1/providers/annotations.ts | 24 | 24 |
| extension/pi/v1/providers/plannotator.ts | 11 | 11 |
| extension/pi/v1/providers/selection.ts | 3 | 3 |
| extension/pi/v1/providers/tombell.ts | 4 | 4 |
| extension/pi/v1/review.ts | 18 | 18 |
| extension/session/branchWorkflowSession.ts | 1 | 1 |
| extension/session/lifecycle.ts | 11 | 11 |
| extension/session/memoryWorkflowSession.ts | 2 | 2 |
| extension/session/workflowSession.ts | 13 | 13 |
| extension/substrate/agentScratch.ts | 9 | 9 |
| extension/substrate/bindingDelivery.ts | 7 | 7 |
| extension/substrate/bindings.ts | 9 | 9 |
| extension/substrate/cache.ts | 28 | 28 |
| extension/substrate/clipboard.ts | 2 | 2 |
| extension/substrate/coldDoor.ts | 14 | 14 |
| extension/substrate/command.ts | 1 | 1 |
| extension/substrate/config.ts | 11 | 11 |
| extension/substrate/consoleCapture.ts | 3 | 3 |
| extension/substrate/git.ts | 8 | 8 |
| extension/substrate/miniJinja.ts | 1 | 1 |
| extension/substrate/miniYaml.ts | 1 | 1 |
| extension/substrate/modelVisible.ts | 3 | 3 |
| extension/substrate/paths.ts | 5 | 5 |
| extension/substrate/prompts.ts | 2 | 2 |
| extension/substrate/providers.ts | 16 | 16 |
| extension/substrate/registry.ts | 5 | 5 |
| extension/substrate/resolverLease.ts | 7 | 7 |
| extension/substrate/resources.ts | 4 | 4 |
| extension/substrate/result.ts | 8 | 8 |
| extension/substrate/runId.ts | 3 | 3 |
| extension/substrate/sessionData.ts | 14 | 14 |
| extension/substrate/sessionPointers.ts | 9 | 9 |
| extension/substrate/structuredOutput.ts | 7 | 7 |
| extension/substrate/terminalLaunch.ts | 5 | 5 |
| extension/substrate/toolGating.ts | 14 | 14 |
| extension/substrate/toolParams.ts | 11 | 11 |
| extension/substrate/unifiedDiff.ts | 1 | 1 |
| extension/substrate/workflowState.ts | 22 | 22 |
| extension/surfaces/footerProvider.ts | 2 | 2 |
| extension/surfaces/report.ts | 5 | 5 |
| extension/surfaces/surfaces.ts | 38 | 42 |
| extension/vendor/btw/btw.ts | 4 | 4 |
| extension/vendor/btw/core.ts | 13 | 13 |
| extension/vendor/whimsical/whimsical.ts | 3 | 3 |
| extension/waves/adversarialReviewWave.ts | 7 | 7 |
| extension/waves/draftReviewWave.ts | 7 | 7 |
| extension/waves/memoryAdapter.ts | 3 | 3 |
| extension/waves/objectiveExplorerWave.ts | 6 | 6 |
| extension/waves/ponytail.ts | 8 | 8 |
| extension/waves/prReviewWave.ts | 11 | 11 |
| extension/waves/reportWave.ts | 19 | 20 |
| extension/waves/reviewClassifierWave.ts | 4 | 4 |
| extension/waves/rpcAdapter.ts | 6 | 6 |
| extension/waves/transport.ts | 18 | 18 |
| extension/worker/sdkAdapter.ts | 12 | 12 |
| extension/worker/stageExecution.ts | 26 | 30 |
| extension/workerMain.ts | 1 | 1 |
