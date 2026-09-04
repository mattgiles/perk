# TypeScript decomposition: typed features and Pi application adapters

## Status

> **Status (Objective #2130, Node 1.1):** the migration this memo authorized has landed —
> the 16-layer #2083 train merged (`40a30df8..a5dc757e` on `main`, each commit subject
> carrying its merge PR number, `#2090` … `#2129`) and objective #2083 is closed. The
> dependency goals hold: both baseline import cycles are gone, Pi importers fell 56 → 52,
> `adapters/` and `factories/` were deleted whole, the feature homes (`authoring/`,
> `delivery/`, `codeReview/`, `learning/`) are Pi-free with direct tests, and `index.ts`
> is composition-only.
>
> The realized topology differs from this memo's sketch in named places: `session/` exists
> as drawn; the wave engine stayed `waves/` (not `execution/reportWave.ts`); stage drive
> stayed `worker/stageExecution.ts` (not `execution/stageRunner.ts`); configuration stayed
> `substrate/config.ts` (no `config/` directory was created); `pi/v1/` exists as drawn;
> `doors/` is 74% evacuated (7 surviving modules, owed by objective #2130 node 3.1).
>
> Seam dispositions, one line each (the detailed rationale and re-earn condition for each
> live in the named `module-contracts.md` section — the one canonical home):
>
> - `config/` — deferred; see `module-contracts.md` § PerkConfig.
> - `PromptEvidence` — deferred; see `module-contracts.md` § PromptEvidence.
> - `StageRunner` — deferred; see `module-contracts.md` § StageRunner.
> - `ReportWave` — owed by objective #2130 node 2.1, reversing the Node 5.1 recorded
>   supersession; see `module-contracts.md` § ReportWave.
>
> What objective #2130 owes (one sentence per phase; the roadmap on issue #2130 is the
> authority): Phase 1 reconciles these architecture documents, pins the storage-freedom
> policy and the quantitative baseline, and closes the Phase-7/objective gate record.
> Phase 2 deepens the seams — node 2.1 restores the opaque `ReportWave` lifecycle, node
> 2.2 makes `WorkflowSession` one deep authority behind a session-owned receipt, and node
> 2.3 executes the storage-freedom migrations and extends the import-direction guard.
> Phase 3 finishes the `doors/` evacuation and deletes the directory. Phase 4 retires
> test-shaped production surface and compresses duplication and migration commentary.
> Phase 5 verifies the reconciled acceptance criteria against the final state and closes
> the objective with a per-feature-family live dogfood record.

This memo is the current architecture proposal for decomposing the TypeScript in
`extension/`. It replaces the TypeScript topology proposed in
`docs/planning/future-proofing-decomposition.md`; it does not supersede that document's
broader product or workflow principles.

The proposal is future-first with respect to the Pi programming model described
in [`upcoming-pi-changes-memo.md`](../upcoming-pi-changes-memo.md). The intended
destination is Pi's application-host model. Today's extension-v1 integration
remains the working bridge until the future adapters prove parity and Pi's
support policy permits its removal.

This is a planning document. It does not authorize a behavioral change by
itself.

## Reading guide

Read this memo first for the architectural decision, then use the companion
documents for the evidence, contracts, and execution plan:

1. [`current-system-map.md`](current-system-map.md) records the current
   TypeScript topology and the evidence behind the decision.
2. [`module-contracts.md`](module-contracts.md) defines the target ownership,
   dependency direction, and important TypeScript interfaces.
3. [`migration-and-verification.md`](migration-and-verification.md) sequences
   the migration and defines its verification and dogfood gates.

## Decision

Organize the extension around typed feature modules, then adapt those features
to Pi at the host where each concern belongs:

```text
Pi application host — intended destination
  application/server       session            TUI/web
  manifests + services     values + drive     views + slots
              └───────────────┬────────────────┘
                              ▼
                     Pi application adapters
                              │
current extension-v1 bridge ──┤
current SDK/RPC bridges ───────┘
                              ▼
       authoring · delivery · code review · learning
                              │
      WorkflowSession · PerkConfig · ReportWave · StageRunner
```

There is no application kernel, universal capability protocol, global feature
catalog, or string-keyed dispatcher in the target design. Pi's binding
metadata stays in the Pi adapter. Feature code exposes ordinary, typed
operations using the language of the workflow it implements.

“Future-first” describes placement and lifecycle, not permission to copy
exploratory upstream types into Perk. Stable Perk modules use Perk vocabulary.
Strict JSON, contribution registries, values, lanes, services, views, and host
generation types stop at Pi adapters.

The extension remains one npm package. Directories express ownership; they are
not package boundaries.

## Why this is the right decomposition

The present extension is not suffering from a lack of layers. It is suffering
from ownership spread across entrypoint registration, workflow helpers, state
files, rendering, and lifecycle hooks.

The current evidence matters:

- 101 production TypeScript files contain about 37,300 lines.
- The production graph has 517 distinct local import or re-export edges.
- 56 files import Pi APIs; only nine use Pi as a runtime import.
- The extension registers 37 tools, 30 effective feature commands, two flags,
  one shortcut, and 33 lifecycle hooks.
- The graph contains at least two local cycles:
  `config.ts ↔ bindings.ts` and
  `planReview.ts ↔ planAdapterPlannotator.ts`.
- Tool bindings already carry behavior that a generic final-result interface
  would erase: schemas, prompt guidance, execution policy, and incremental
  progress.
- Report waves already have a useful domain shape, with in-memory and RPC
  execution behind it.

These facts point to two separate problems:

1. Workflow behavior needs a coherent home.
2. Host integration needs to stop leaking through those homes.

A generic middle layer would hide both problems behind a larger protocol. A
typed feature seam solves them directly.

## What the Pi refactor changes

The upstream work does not invalidate the feature decomposition. It strengthens
the case for narrow seams around volatile substrate and changes which Pi host
will eventually implement them.

| Upstream direction | Maturity at the frozen survey | Effect on this proposal |
| --- | --- | --- |
| Extension v1 | Current surface, unchanged | Keep as the compatibility bridge |
| Typed values and lists | Implemented on unreleased `dev` | Candidate storage behind `WorkflowSession` |
| Format-4 context and `retainedTail` | Implemented on unreleased `dev` | New TypeScript context adapter for `PromptEvidence` |
| Durable drive and usage | In progress | Candidate execution behind `StageRunner` |
| Lanes and session workers | Experimental | Candidate execution behind `ReportWave` and local execution roots |
| Services and application facets | Exploratory with implemented slices | Target placement model, not a stable Perk interface |
| Views and slots | Exploratory | Candidate adapter behind the surfaces seam |

Compatibility and adoption are distinct. Format-4 context may require a
TypeScript compatibility adapter when it ships. Values, durable drive, lanes,
services, and views are adopted only when their interfaces and semantics earn
the replacement.

## Reassessment of the first proposal

### What it got right

The first proposal established several decisions worth retaining:

- it began with measured repository evidence rather than an idealized folder
  tree;
- it treated modules as ownership units without requiring npm packages;
- it favored vertical workflow ownership over technical layers;
- it separated durable state from live conversation context;
- it kept report waves distinct from stage execution;
- it declined a universal presentation bus; and
- it required behavioral parity, deletion, contract tests, and dogfood gates
  during migration.

Those are the foundation of this revision.

### What it got wrong

The proposed application kernel made unlike operations look alike. A generic
capability protocol would have traded compile-time workflow information for
runtime narrowing. Its catalog described too little of the actual host
contract: command parsing, flags, shortcuts, hooks, progress, and lifecycle
ordering did not fit honestly.

The state design also claimed more than the current backing proves. A ledger
with general revisions and conflicts would have been an invented storage
model, not an extraction of present invariants. A single Pi shell placed too
many unrelated adapter concerns in one imagined module. Finally, presenting
four feature areas as implementations of one protocol confused common
ownership discipline with common behavior.

### What was underbaked

Several central types were named without sufficient laws or concrete callers.
The raw-context-to-domain flow, guidance provenance, borrowed-tool gating,
incremental progress, configuration ownership, flags, shortcuts, and hook
ordering needed explicit treatment. The original migration phases also moved
too much before proving a complete slice, and its graph methodology was not
reproducible enough to distinguish call sites from effective registrations.

The attending documents now specify those details and state where evidence is
still intentionally incomplete.

### The superior alternative adopted here

Use typed feature operations and explicit Pi bindings. Share deep mechanisms
such as session verification and report-wave execution, not a universal
invocation shape. The upcoming Pi application host now supplies a concrete
placement target: its adapters may distribute across facets, while the Perk
interfaces they call remain independent of those facet types.

## First principles

### Preserve domain information

TypeScript should make illegal workflow requests difficult to express. A gist
draft, a plan review, a delivery result, and a learning report do not become
safer by being converted into a common invocation envelope.

Each feature therefore defines the smallest operations, inputs, results, and
errors that express its own work. Shared types are introduced only when two
real callers require the same semantics.

### Group by reason to change

A vertical feature module owns the workflow policy that changes together:

- authoring owns the progression from draft through review and save;
- delivery owns readiness, publication, and Delivery train progression;
- code review owns review requests, findings, and resolution state;
- learning owns analyst waves, consolidation, and routing.

Pi registration does not belong to those modules. Neither do terminal
rendering details, raw session context, or RPC transport vocabulary.

### Make host seams explicit

The adapter for a Pi tool should be visible and boring:

1. decode and validate the Pi request;
2. obtain the feature and session dependencies;
3. call one typed feature operation;
4. translate progress and the final result into Pi output.

Commands, flags, shortcuts, and hooks follow the same rule. Explicit bindings
are preferable to a universal registry because the binding forms are
materially different.

### Put invariants behind deep modules

`WorkflowSession` owns session identity, verified workflow state, artifact
provenance, and semantic changes such as claim, fork, and adoption. Callers ask
it to perform semantic transitions. They do not read arbitrary storage and
apply arbitrary patches. Host attachment, reload generations, and disposal are
adapter concerns; a new generation reconstructs the module from durable state.

`ReportWave` owns report fan-out and fan-in. Callers supply named report
assignments and consume typed outcomes; they do not know whether execution used
the current RPC bridge or future Pi lanes.

`StageRunner` owns execution of actual Perk stages in an approved
session-interior execution root. It hides today's SDK drive and the future
durable Harness drive behind the same Perk outcome. It does not become a
general recipe runner.

### Distinguish durable state from live evidence

Durable workflow state and live conversation evidence have different
lifecycles.

- `WorkflowSession` is authoritative for state and artifacts.
- `PromptEvidence` is a value derived from the context projection available to
  the active Pi host.

`PromptEvidence` is explicitly available or unavailable. It records the
ordered prose units directly evidenced for one Session shape. It is reconciled
against durable state by pure feature policy; it is not another state store.

### Keep presentation at the edge

Features return typed outcomes and typed progress. Pi adapters choose messages,
cards, reports, and status surfaces. Standing presentation must be derivable
again after host attachment or generation replacement; transient progress may
remain transient. This preserves the existing surfaces module as the only
rich-UI seam without inventing a universal presentation bus.

## Target ownership

### Feature modules

`authoring/`, `delivery/`, `codeReview/`, and `learning/` are ownership
areas, not implementations of one interface. Their public interfaces are ordinary
typed functions or small interfaces.

Authoring may be split internally into gist, plan, and objective flows because
those flows have distinct state machines. That does not require them to share a
generic authoring protocol.

### Stable mechanisms

`session/` owns `WorkflowSession` and artifact provenance.

`config/` owns parsing and the typed `PerkConfig`. Configuration remains a
snapshot loaded from the active `cwd` at the same session or invocation points
as today; it is not one extension-global value. Features receive only the
configuration they use; no universal dependency bag is passed inward.

`execution/reportWave.ts` owns the proven report-wave mechanism.
`execution/stageRunner.ts` owns worker-stage execution.

These mechanisms remain narrow. They do not become a place for unrelated
workflow policy.

### Pi integration

The Pi edge has two logical families:

- `pi/v1/` is the current extension-v1 compatibility bridge;
- `pi/application/` is the intended application-host adapter family, admitted
  only as the upstream facet contracts become normative.

Together the Pi adapters own:

- installation of tools, commands, flags, shortcuts, and hooks;
- request schemas and argument completion;
- tool availability and execution-mode policy;
- raw session and context adaptation;
- provider, execution, state, and remote-service adapters;
- progress and final-result rendering.

`extension/index.ts` remains the v1 composition root and calls named installers
directly. There is no stable `PiExtension`, binding array, or installer
protocol. A future Pi application manifest contributes the same feature
operations to the appropriate facets without becoming a Perk domain object.
`workerMain.ts` remains the current worker execution root.

## Names

Names should be ordinary English, sized to the concept, and stable if an
implementation detail changes.

| Name | Meaning | Why it holds |
| --- | --- | --- |
| `WorkflowSession` | One verified Perk workflow session | More precise than “store”; less grand than “application session” |
| `PromptEvidence` | Direct evidence of prose units in one Prompt assembly and Session shape | Uses existing product vocabulary and names a value |
| `ReportWave` | Parallel report production and collection | Already proven in the code and domain vocabulary |
| `StageRunner` | Runs a registered Perk stage in a worker | Narrower and more honest than a general wave or recipe runner |
| `PerkConfig` | Validated extension configuration | Plain ownership, with no “manager” or “service” suffix |
| `DraftReviewer` | Reviews an authored draft | Describes the collaborator's role |
| `ChangeReviewer` | Reviews a code change | Distinguishes it from draft review without implementation jargon |
| `ProseUnitId` | Stable identity of one behavior-shaping prose unit | Reuses the glossary rather than minting “guidance block” |
| `ReportAssignment` | One named request inside a report wave | Avoids confusing Perk work with Pi Harness lanes |

Avoid names that are broader than the implementation:

- `PerkApplication` and `PerkApplicationSession` imply a central runtime
  object that the design does not need.
- `Capability`, `Contribution`, `Invocation`, `Reaction`, and
  `SemanticResult` erase useful differences.
- `WorkflowLedger` suggests an append-only accounting model the current state
  backing does not provide.
- `ContextIndex` makes ephemeral evidence sound authoritative.
- `WaveRunner` collapses report waves and stage execution.
- `PiV1Shell` makes every host concern sound like one module; `pi/` is a
  family of small adapters.
- `PiExtension` and `PiBinding` turn straightforward current-host wiring into a
  shallow protocol and become ambiguous beside the future application host.

Folder names use the product noun where it improves recognition. For example,
`codeReview/` is clearer than `review/`, because authoring also contains
review.

## Seam placement

A seam is justified when it hides a volatile detail behind a smaller, more
stable interface.

| Volatile detail | Seam | Consumer |
| --- | --- | --- |
| Pi context projection | prompt-evidence adapter | feature reconciliation |
| Values, lists, and conversation entries | workflow-session storage adapters | `WorkflowSession` |
| RPC and Pi lane execution | report-execution adapters | `ReportWave` |
| SDK and durable Harness drive | stage-drive adapters | `StageRunner` |
| Draft-review provider | `DraftReviewer` | authoring |
| Code-review provider | `ChangeReviewer` | code review |
| Web lookup provider | feature-specific lookup port | the feature that requests it |
| Pi schemas, registries, and manifests | explicit Pi adapters | Pi |
| Views, slots, and current TUI calls | surfaces adapters | Pi clients |

An interface is a test surface. Every introduced seam needs a production
adapter and an in-memory or deterministic test implementation. If a second
implementation is neither present nor useful for testing, keep the function
concrete.

## Rejected alternatives

### A generic application kernel

A kernel with `start`, `invoke`, `react`, and `close` looks uniform, but
it moves validation and narrowing into every implementation. It also makes
tools, commands, hooks, and worker stages appear interchangeable when their
lifecycle and output obligations differ.

The deletion test fails: removing one workflow would still require editing the
kernel's protocol and catalog. With explicit feature bindings, the workflow's
module and bindings can be removed together.

### A Perk-owned global registry

A discriminated union would be safer than a string-and-`unknown` registry, but
it would still centralize every operation name and payload. It would reproduce
the present registration concentration under a different name.

Use a closed union inside a feature when that feature has a real state machine.
Do not lift all features into one union.

If Pi's future application host requires a contribution registry, the Pi
adapter contributes named feature operations to that host registry. That does
not make the registry a Perk domain interface.

### Horizontal technical layers

Top-level `commands/`, `tools/`, `handlers/`, and `services/` make a
single workflow change span many directories. Those categories are useful
inside the Pi adapter, not as the domain architecture.

### One host shell module

Pi integration is one architectural edge, but not one source file. Tool
binding, session adaptation, provider construction, report transport, and
rendering have different reasons to change. They share a directory and import
direction, not a catch-all object.

### Multiple npm packages

Package boundaries would add manifests, build ordering, versioning, and
workspace resolution without an independent consumer. Start with source
modules. Extract a package only when a real consumer or deployment boundary
appears.

## Migration posture

Migration proceeds by complete vertical slices. Each slice introduces one
typed feature operation, binds it to Pi, proves it through feature and adapter
tests, and deletes the old path. Transitional duplication is acceptable only
inside that slice and only until its dogfood gate passes.

The first proving slice is gist authoring. It extracts only the
`WorkflowSession` and `PromptEvidence` behavior that gist authoring actually
needs. The session interface grows from later callers; it is not “completed”
horizontally before the first feature proves it.

The future Pi application adapters form a gated cutover lane. The v1 bridge and
future adapters may coexist in the package, but they must never register the
same behavior twice in one host. After facet parity, the future host becomes
primary; v1 is removed only when support policy permits.

The migration must not:

- introduce a generic registry as scaffolding;
- preserve old APIs through indefinite compatibility wrappers;
- invent storage revisions that the backing store cannot verify;
- perform a directory-only move with unchanged ownership;
- defer all deletion to a final cleanup phase.

The detailed order and gates live in
[`migration-and-verification.md`](migration-and-verification.md).

## Success criteria

The decomposition succeeds when:

- a feature test can call a typed operation without constructing Pi;
- a Pi adapter test can validate registration and translation without running
  feature policy;
- feature modules do not import Pi runtime APIs, TUI APIs, RPC vocabulary, or
  branch-backed storage details;
- `WorkflowSession` is the only feature-facing authority for session state and
  artifacts;
- live context is passed as `PromptEvidence`, including explicit
  unavailability; *(Deferred — see `module-contracts.md` § PromptEvidence and the Node 1.1
  status note.)*
- report-wave callers cannot observe RPC or Pi lane mechanics;
- only approved execution roots consume `StageRunner`, initially
  `workerMain.ts`; *(Deferred — see `module-contracts.md` § StageRunner and the Node 1.1
  status note.)*
- current and future Pi adapters invoke the same feature operations without a
  common application dispatcher;
- reload generations reconstruct standing state without process-global
  authority;
- tool progress remains incremental where it is incremental today;
- deleting one feature removes its feature module and host adapters, with only
  honest composition and host-wide tool-census edits outside them;
- the extension still builds and ships as one npm package.

## Durable records

This proposal introduces implementation vocabulary, not new product-domain
terms, so it does not require a `CONTEXT.md` glossary change. No cross-plane
behavior changes in this planning step, so `shared/contracts.md` and user
documentation remain unchanged.

When implementation changes cross-plane or user-facing behavior, those records
must be updated in the same change under the repository conventions.

## Bottom line

The elegant center is not a universal application object. It is a small set of
Perk interfaces whose implementations can move to the Pi host that owns their
lifecycle.

Typed feature modules own workflow meaning and Prose units.
`WorkflowSession` owns durable invariants. `ReportWave` and `StageRunner` own
their two different execution shapes. The v1 bridge keeps Perk working while
future application-host adapters move storage, drive, lanes, services, and
views to their natural Pi facets without letting those host types define the
interior.
