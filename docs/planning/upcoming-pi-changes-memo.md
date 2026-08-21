# Upcoming Pi changes: implications for Perk

> Point-in-time survey for Perk maintainers, frozen on 2026-08-20. This memo describes
> unreleased work, not a Pi compatibility promise or a Perk migration decision. Upstream
> source links are pinned to immutable commits; maturity labels matter as much as the code.

## Executive summary

Pi's `dev` branch is not a routine package update. It is building a durable agent runtime,
new session storage contracts, an experimental server/client process model, and the beginnings
of a plugin application-host architecture. Those changes approach several seams that Perk
currently owns because released Pi does not: reconstructible workflow state, bounded headless
session drive, run-event projection, session-log auditing, provider convergence, and subagent
orchestration.

The immediate conclusion is observation, not migration:

- **Implemented on `dev`:** a large part of the new AgentHarness storage model, typed values and
  lists, JSONL and SQLite repositories, atomic operation acceptance/inspection, usage storage,
  transport-neutral remote-service primitives, and mouse-aware TUI components.
- **In progress on `dev`:** direct durable drive is deliberately guarded until all reachable
  phases and recovery paths exist. The pinned branch's build/test check is red on one
  experimental remote-runtime concurrency test.
- **Experimental on `dev`:** the coding-agent server, client, session-worker, remote service
  vertical slices, and service-only TUI are behind the experimental path rather than the
  ordinary `pi` experience.
- **Exploratory/design input:** extension v2, complete application manifests, plugin facets,
  reload generations, contribution registries, views, slots, and several core service
  contracts are explicitly non-normative or incomplete.
- **Unchanged in this comparison:** today's coding-agent extension types, loader, runner,
  wrapper, and the current extension/SDK/session documentation. Perk should therefore not read
  this branch as an already-specified replacement for its extension-v1 integration.

The highest-confidence implications are:

1. Perk's Python parser of Pi's v3 JSONL format will need a compatibility decision before Pi's
   format-4 storage becomes the default source of session evidence.
2. Perk's `activeContextWindow()` depends on v3 compaction's `firstKeptEntryId`; format 4 uses a
   materialized `retainedTail` and does not expose or persist that field.
3. Perk's append-only `perk:workflow-state` entries and per-field rebuild have a plausible
   future home in Pi's application-owned typed values, but that is an overlap candidate rather
   than proven redundancy: fork policy, history, observability, and compatibility differ.
4. Pi's durable operation state and usage ledger may eventually replace parts of Perk's
   process-local worker accounting. They do not replace Perk's workflow semantics, terminal
   tools, Git/worktree lifecycle, plan contract, or cross-run delivery policy.
5. Pi's experimental server/client/session-worker path creates a possible local execution
   substrate. It is not yet evidence that Perk's GitHub Actions runner, run-event protocol, or
   exterior orchestration is redundant.
6. Lanes and durable agent operations could provide a stronger substrate for parallel agent
   work. They do not yet express Perk's selector/reviewer/aggregator waves, artifact contracts,
   or isolation rules, and they do not yet replace `pi-subagents`.
7. Plugin services, manifests, registries, and views point toward cleaner provider and TUI
   integration later. Most of that layer is still design input, so Perk should use it to shape
   questions and experiments, not production abstractions.

## Snapshot and method

### Frozen upstream comparison

| Item | Frozen value |
| --- | --- |
| Pi `main` | [`5cd93f6`](https://github.com/earendil-works/pi/commit/5cd93f688aaab89dbb6dfa4aca535f21796ae185) |
| Pi `dev` | [`a17323e`](https://github.com/earendil-works/pi/commit/a17323e5b1e766433e76a3ed7a129f640924c079) |
| Merge base | [`b7bb00b`](https://github.com/earendil-works/pi/commit/b7bb00b936dbe21b8e160b3e89efdec361846699) |
| Relationship | `dev` is 264 commits ahead and 7 commits behind `main` |
| Three-dot change set | 375 files, 52,429 insertions, 20,497 deletions |
| Frozen comparison | [`main...dev` at the two SHAs](https://github.com/earendil-works/pi/compare/5cd93f688aaab89dbb6dfa4aca535f21796ae185...a17323e5b1e766433e76a3ed7a129f640924c079) |
| `dev` head timestamp | 2026-08-20 21:09:41 UTC |
| Perk package baseline | `@earendil-works/pi-{ai,coding-agent,tui}` 0.84.1 in [`package.json`](../../package.json) |

The size figures describe the three-dot change from the merge base to `dev`, matching the
linked comparison. Because the branches diverged, they are not a direct two-tip release diff.
This memo also does not assume that every `dev` commit will ship together or unchanged.

The change is concentrated in the runtime-facing packages:

| Package area | Changed files | Insertions | Deletions | Reading |
| --- | ---: | ---: | ---: | --- |
| `agent` | 145 | 31,421 | 9,287 | Durable harness, storage, operations, values, telemetry, plugin design |
| `coding-agent` | 96 | 10,455 | 2,112 | Experimental server/client/session worker and application vertical slices |
| `session-backends` | 50 | 2,972 | 3,946 | SQLite repository/storage rework |
| `server` | 30 | 2,311 | 2,431 | Session routing and Unix transport |
| `client` | 20 | 1,634 | 1,806 | Remote client/connection simplification |
| `tui` | 13 | 1,097 | 35 | Mouse routing and mouse-aware components |
| `protocol` | 10 | 1,617 | 802 | Wire projections for the new runtime/service work |
| `ai` | 6 | 903 | 71 | Durable assistant-message frame reduction and UUID utilities |

### CI condition at the snapshot

This branch is active work. At the frozen `dev` SHA, `generate` succeeded, `publish` was
skipped, and [`build-check-test` failed](https://github.com/earendil-works/pi/actions/runs/32417967896/job/96583373711).
The coding-agent suite reported 2,026 passed, 51 skipped, and one failed test:
`experimental-remote-runtime.test.ts` failed while checking that concurrent launchers leave one
server active, due to an invalid default experimental server identity. This is narrow evidence,
not a claim that the rest of `dev` is broken; it is also concrete evidence that the remote
runtime path is not yet a stable base for Perk.

### Maturity vocabulary

Every upstream observation in this memo uses one of these labels:

| Label | Meaning in this memo |
| --- | --- |
| **Implemented on `dev`** | Code and tests exist at the frozen SHA. It is still unreleased. |
| **In progress** | An implementation work package or guarded path explicitly remains unfinished. |
| **Experimental** | Code exists, but its namespace, CLI gate, or own documentation marks it experimental. |
| **Exploratory** | Design notes explicitly say they are not a spec or normative contract. |
| **Unchanged current surface** | The released-style extension surface exists and was not changed by this three-dot comparison. |
| **Perk hypothesis** | An inference about possible interaction; it is not an upstream commitment. |

“Overlap candidate” means Pi may be growing a substrate for behavior Perk currently supplies.
“Redundant” is reserved for behavior proven unnecessary against a released, stable Pi contract.
No item in this memo reaches that latter threshold.

## The architecture under construction

The easiest way to read the branch is as two paths that currently coexist:

```text
current/default path                         proposed/experimental path
--------------------                         --------------------------
perk CLI exterior                            application/server host
  -> launches ordinary `pi`                    -> session directory + management services
     -> coding-agent session                       -> per-session worker process
        -> extension-v1 loader/runner                   -> durable AgentHarness + Session
           -> Perk extension                               -> remote service facades
        -> v3-style SessionManager JSONL                   -> client/TUI attachment

        [unchanged in this comparison]         [implemented + in progress + exploratory]
```

The durable AgentHarness is the most concrete foundation. The experimental remote composition
sits above it. The broader plugin host and extension-v2 designs sit above and around both, but
are not yet a normative replacement for today's extension loader.

## Part I: upstream change census

### 1. Durable AgentHarness and session model

#### Storage authority

**Implemented on `dev`.** The [AgentHarness implementation specification](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/harness.md)
defines a session around three durable forms:

- immutable conversation entries containing placement and payload;
- mutable, typed scalar values and append-only typed lists addressed by namespace and key; and
- an append-only usage ledger.

Storage admits atomic transactions across those forms. Application-owned namespaces use the
same public `value()`/`list()` address model as core state. The detailed [values design](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/values.md)
and completed [WP01](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/work-packages/01-bound-values-lists.md)
show this is implemented work rather than only an aspiration.

**Implemented on `dev`.** The repository abstraction has memory, JSONL, and SQLite backends.
JSONL remains append oriented but can compact storage representation; SQLite has explicit
session rows, entries, sequences, values, usage, writer leases, and conformance tests. Branch
indexes, search, and statistics are projections rather than the authority.

**Perk hypothesis.** Pi is creating a first-class home for small application state that Perk
currently encodes as custom transcript entries. Whether that home is suitable depends on
visibility, fork behavior, audit-history requirements, and extension-v1 access—not merely on
whether a typed key/value API exists.

#### Lanes, operations, and atomic acceptance

**Implemented on `dev`.** A session can hold named lanes. Each lane has configuration, a leaf,
state, and a last result. An accepted prompt or structural intent becomes a durable operation,
and the operation's complete current state acts as a program counter. Atomic acceptance avoids
the gap where input has been accepted but its operation is not recoverable.

**Implemented on `dev`.** Work packages 00 through 04 mark runtime replacement, typed values,
atomic acceptance, deadline removal, and mutation publication complete:

- [WP00 — Runtime1 removal](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/work-packages/00-runtime1-removal.md)
- [WP01 — Bound values and lists](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/work-packages/01-bound-values-lists.md)
- [WP02 — Atomic acceptance](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/work-packages/02-atomic-run-acceptance.md)
- [WP03 — Remove drive deadlines](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/work-packages/03-remove-drive-deadlines.md)
- [WP04 — Mutation publication](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/work-packages/04-mutation-publication.md)

**In progress.** [WP05 — Direct durable drive](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/work-packages/05-direct-durable-drive.md)
is marked implementation-ready and keeps public drive disabled until every reachable execution
and reconciliation path exists. At the frozen SHA, the concrete-package table calls WP05
“implementation,” later runtime slices remain future candidates, and `runtime2/lane.ts` still
throws `SliceNotImplemented` from `drive()` and `requestAbort()`. The unreleased changelog already
describes no-tool execution, request recovery, retry/deferred state, durable tools, and replay as
added; the source and active work-package table are the safer maturity evidence. This memo
therefore treats direct durable execution as unfinished.

#### Recovery and effect boundaries

**In progress.** The normative harness contract requires intent to be persisted before provider,
tool, or other non-idempotent effects. After settlement, it requires result, usage, state, and
publication to land atomically. Recovery is designed to reload the operation program counter
rather than reconstruct progress from missing records. Tools can declare replay as safe or
never; unknown outcomes for unsafe effects are designed to settle in-band instead of silently
repeating them. These are target semantics for the unfinished direct-drive slices, not all
currently reachable behavior.

**In progress.** The contract gives abort, close, and fault distinct meanings. Close is designed
as a controlled crash that leaves durable state for restoration. Expected provider/tool
failures become outcomes, while invariant and storage-admission failures fault the harness.
Public abort and the complete recovery/failure-drain behavior remain part of future runtime
slices at this snapshot.

**Perk hypothesis.** This is a potential substrate for Perk worker durability inside one Pi
session. It does not itself recover Git state, a worktree, a plan delivery train, a GitHub
Actions job, or Perk's cross-session run state.

#### Usage, events, hooks, and telemetry

**Implemented substrate; in-progress execution coverage.** The storage and public contracts
support usage rows with durable sequences and ledger-derived totals. The target runtime commits
every settled model attempt and emits the committed sequence so consumers can reject late older
projections. Because full direct drive is unfinished, the ledger is a real storage capability
but not yet proof that every intended execution path populates it.

**Implemented substrate; in-progress execution coverage.** Event publication, hook primitives,
and a broad typed catalog exist for run, turn, message, tool, structural, lane, usage, write,
fault, and handler activity. The contract requires deterministic hook aggregation and
publication only after committed state is visible. The complete catalog/order remains a future
surface-completion slice.

**Implemented on `dev`.** Telemetry schemas and helpers are part of the harness work, with a
separate [telemetry guide](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/telemetry.md).

**Perk hypothesis.** Perk could eventually derive budget and diagnostic projections from Pi's
durable ledger/events, but Perk's run-event stream has a different audience and vocabulary. It
records workflow-level facts such as stage, terminal signal, terminating-tool result, PR, and
run identity, which remain Perk-owned even if their low-level inputs come from Pi.

### 2. Session format 4 and v3 compatibility

**Implemented on `dev`, except future migrations.** Format 4 stores entries, typed values/lists,
and usage with an explicit storage version. JSONL and SQLite share the session semantics even
though their physical representation differs. Chained migrate-on-open for future format-4
storage versions is still the R11 candidate; the frozen JSONL source rejects an unsupported
storage version rather than migrating it.

**Implemented on `dev`.** The harness specification's v3 compatibility appendix defines a
read-only normalization path for old coding-agent JSONL sessions and an atomic conversion on
the first format-4 write. Important transformations include:

- v3 entry IDs are re-minted as time-prefixed UUIDv7 IDs;
- known structural references are remapped, while IDs embedded in opaque custom data or message
  text are not rewritten;
- v3 `custom_message` records become custom agent messages;
- session info, names, and labels move into typed values;
- model, thinking, and active-tool change nodes no longer remain conversation entries;
- old usage is summarized into an adjustment row on first format-4 write; and
- v3 compaction's `firstKeptEntryId` is resolved and materialized as a complete `retainedTail`.

**Implemented on `dev`.** Format 4 compaction is a self-contained checkpoint: context uses its
summary plus `retainedTail` plus later entries, and does not read earlier history. Format 4 does
not expose or persist `firstKeptEntryId`.

**Perk hypothesis.** Read compatibility inside Pi does not automatically provide compatibility
for Perk's independent Python parser. Perk must either consume a stable exported projection,
teach its parser both formats, or stop treating the physical coding-agent JSONL file as its
audit boundary.

### 3. Experimental server, client, and session workers

**Experimental.** `packages/coding-agent/src/experimental/` now contains server composition,
client runtime/TUI, a coordinator, a harness wire adapter, process management, session-worker
management, and remote service implementations. The [experimental services readme](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/coding-agent/src/experimental/services/README.md)
describes a service-only client enabled with `PI_EXPERIMENTAL=1`.

**Experimental.** The server owns repository-backed session directory/management and routes to
per-session workers. A client can list, create, switch, and attach to sessions; the worker owns
the durable Harness for its session. Unix sockets and server identity/profile management supply
the local transport and process-discovery layer.

**Experimental.** Remote models, chat, session directory, session management, worker, and
connection services form vertical slices. Some services are functional; Accounts and
Transcript remain incomplete scaffolds.

**Experimental and currently failing one CI race.** The frozen failure occurs in concurrent
experimental server startup/profile handling. That makes concurrency and identity ownership a
specific seam to retest before Perk considers this substrate.

**Perk hypothesis.** The topology resembles the process separation Perk wants for durable
headless execution, but today it is local service composition—not a replacement for Perk's
remote CI job lifecycle, credentials, checkout positioning, branch ownership, or run-delivery
contract.

### 4. Remote services and plugin application hosts

**Implemented experimentally on `dev`.** The agent package exports transport-neutral remote
service primitives: service definitions, providers/namespaces, singleton and keyed services,
replicated `RemoteState`, and ordered non-replayed `RemoteEvents`. Values crossing this boundary
are strict JSON.

**Exploratory with implemented slices.** [Coding-Agent Application Hosts and Plugin Facets](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/plugins.md)
explicitly calls itself tentative design input. It reports an experimental implementation for
the service substrate and Models, Chat, SessionDirectory, and SessionManagement vertical
slices; application host contexts, plugin kernel, references, telemetry propagation, and most
example facets remain illustrative.

**Exploratory.** The application-host design separates server, session, TUI, and web facets.
Plugins would contribute services and presentation or behavior at the host where each concern
belongs, rather than assuming one in-process extension object owns all capabilities.

**Exploratory.** Contribution registries gather ordered contributions, wrappers, and
interceptors, then the host finalizes and publishes a complete registry. Views are proposed as
the session-to-client presentation primitive; slots and typed durable addresses allow named,
composable UI and state ownership.

**Exploratory.** [Plugin reloading](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/plugin-reloading.md)
defines replacement of a complete manifest generation across host facets. Registries rebuild
from all retained contributions, session workers may be replaced, and replicated state
rehydrates from a fresh complete snapshot. The document explicitly is not an implementation
handoff.

**Exploratory.** [RPC design notes](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/rpc.md)
define required service binding, state, events, keyed instances, cancellation, and context
semantics while deferring exact control frames and local proxy implementation.

### 5. Extension v2 is not yet the current extension API

**Exploratory.** [Pi extension system v2 design notes](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/extensions/pi-extensions-v2.md)
open with “exploratory” and “not a spec.” The plugin and reload documents supersede portions of
those notes where they conflict.

**Exploratory.** The notes investigate supervisor/session host/client tiers; separate load
scopes; the verbs contribute, intercept, observe, and effect; replayable registries; views; and
multi-facet manifests. They are valuable evidence of direction, not an API Perk can target.

**Unchanged current surface.** In the frozen comparison, these current coding-agent paths do
not change:

- `src/core/extensions/types.ts`
- `src/core/extensions/runner.ts`
- `src/core/extensions/wrapper.ts`
- `src/core/extensions/loader.ts`
- `docs/extensions.md`
- `docs/sdk.md`
- `docs/session.md`

**Perk hypothesis.** Perk can expect eventual pressure on its extension integration, but there
is no evidence here for preemptively replacing `registerTool`, lifecycle hooks, event buses,
`appendEntry`, `sessionManager`, or UI calls. Compatibility work should follow a normative
surface or adapter, not exploratory vocabulary alone.

### 6. AI and TUI changes

**Implemented on `dev`.** The AI package adds an assistant-message frame reducer that can fold
partial frames into a coherent assistant message. This supports durable/remote streaming where
clients may receive incremental state rather than an in-process mutable object.

**Implemented on `dev`.** The TUI package adds normalized mouse routing, `MouseRegion`, component
`handleMouse` support, and mouse-aware editor, input, select-list, settings-list, box, layout, and
alternate-screen behavior. Coding-agent interactive components use the new routing for
expand/collapse behavior.

**Perk hypothesis.** Mouse support is a modest optional enhancement for Perk's human UI. It does
not change Perk's rule that rich UI goes through its `surfaces` module, and it should not cause
workflow tools to become UI-dependent. The assistant-frame reducer is more relevant if Perk
later consumes a remote session stream.

## Part II: how Perk uses Pi today

Perk spans Pi's exterior and interior. Any migration analysis that looks only at the extension
misses the worker and session-audit dependencies; any analysis that looks only at the SDK misses
the interactive workflow state and UI.

### 1. Exterior launch and package convergence

The Python CLI owns session launch in [`src/perk/run/launch/__init__.py`](../../src/perk/run/launch/__init__.py).
It resolves the Pi executable, builds arguments and environment, warms extension installation,
materializes worktree state, exposes stage-specific skills and model settings, records handoff
data, and finally replaces the process with `pi`.

`perk init` converges the repository's `.pi/settings.json`, package list, `.perk/config.toml`,
managed skill exposure, and extension path. In this repository the Pi package graph includes
the local Perk extension plus third-party extensions such as `pi-subagents`, plan/review UI,
web access, diff, and question/todo helpers.

This plane is intrinsically Perk-owned where it expresses workflow stages, worktree positioning,
Git/GitHub/Linear coordination, configuration, and skill delivery. A new Pi host may change how
packages load, but not why Perk selects and configures them.

### 2. Interactive extension integration

[`extension/index.ts`](../../extension/index.ts) registers Perk's session lifecycle and stage
interior. Across production extension code, Perk uses a broad extension-v1 surface:

- tool registration and active-tool control;
- `before_agent_start`, `turn_start`, `turn_end`, tool, context, fork/switch, tree, shutdown,
  and settled lifecycle events;
- user-message injection and custom session entries;
- extension event buses and subprocess execution;
- session branch, entry, leaf, and session-file access; and
- UI notifications, status, footer, widgets, working messages, and entry renderers through the
  Perk surfaces seam.

This is high integration breadth. The reassuring current fact is that the extension-v1 core
files are unchanged in the frozen upstream comparison. The caution is that plugin application
hosts eventually propose different placement and lifetime boundaries.

### 3. Perk workflow state inside a Pi branch

[`extension/substrate/workflowState.ts`](../../extension/substrate/workflowState.ts) defines
`perk:workflow-state` custom entries. Perk appends partial records, scans the active branch, and
rebuilds each field with last-write-wins semantics. The state includes run and session identity,
stage/mode, plan/objective links, review outcomes, artifact digests, and recovery counters.

This mechanism provides:

- transcript-local persistence without a separate Perk database;
- branch/fork behavior inherited from Pi's entry tree;
- an auditable sequence of state changes;
- compatibility with current extension APIs; and
- a model-context path for selected custom content.

It also couples Perk to entry shape and branch reconstruction, pays repeated scan/rebuild cost,
and makes “current value” an application convention rather than a storage primitive.

### 4. Compaction-aware context reconstruction

`activeContextWindow()` in the same module finds the latest compaction entry, reads
`firstKeptEntryId`, and selects the retained pre-compaction entries plus later entries. Perk uses
that view to avoid mistaking text quoted only in a summary for a still-live custom block.

This is a direct format seam. Pi's proposed format 4 deliberately eliminates the persisted
`firstKeptEntryId` field in favor of `retainedTail`, so the current algorithm cannot simply read
the same property after an upgrade.

### 5. Session pointers and Python session auditing

[`extension/substrate/sessionPointers.ts`](../../extension/substrate/sessionPointers.ts) records
the planning or implementation session file associated with a Perk run. The headless worker and
interactive extension both contribute pointers.

[`src/perk/learn/session_jsonl.py`](../../src/perk/learn/session_jsonl.py) then parses Pi's
physical v3 JSONL grammar independently of Pi. It expects a `{type:"session"}` header followed
by entry lines with `type`, `id`, `parentId`, messages, custom data, compaction data, tool calls,
and usage-related fields. It produces a flat, lenient projection; the downstream learning/audit
normalization reconstructs the active branch and feeds rendering.

This is intentionally lenient, but leniency over fields is not format-4 support. Header,
transaction, value/list, usage, ID-remapping, and compaction representation changes cross the
parser's structural assumptions.

### 6. SDK-driven headless workers

[`extension/worker/worker.ts`](../../extension/worker/worker.ts) drives `implement` and `address`
without a human TUI. It directly creates coding-agent SDK session services and a model runtime,
loads extensions, installs a headless binding, prompts the session, listens to events, tracks
turn/token/wall-clock budgets, aborts on a tripped budget or external signal, checks terminating
tools, records session pointers, and emits Perk run events.

[`extension/worker/readOnlySession.ts`](../../extension/worker/readOnlySession.ts) creates
isolated, read-only child SDK sessions for bounded analysis. Perk also uses these sessions as a
substrate for multi-angle agent waves.

These implementations compensate for current SDK lifecycle gaps in a deliberate, tested way.
They are also the Perk code most likely to benefit from a stable durable drive API.

### 7. Remote runner and run-event protocol

[`src/perk/run/run_worker.py`](../../src/perk/run/run_worker.py) owns the exterior remote-worker
lifecycle: resolve the packaged entry, deliver skills, position the branch/worktree, spawn the
worker, and report its outcome. GitHub Actions supplies a reproducible remote execution host.

The TypeScript worker emits a Perk-owned NDJSON stream with `run_started`, tool outcomes, and one
`run_finished` carrying status, terminal signal, budget totals, PR metadata, and normalized
errors. This protocol connects Pi activity to Perk's workflow and remote execution contract; it
is not merely a mirror of agent-loop events.

### 8. Providers, packages, subagents, and TUI

Perk owns provider seams for plans, footers, and web behavior; repository configuration selects
providers while `perk init` converges the corresponding Pi packages. It also owns stage-specific
tool exposure, skill bindings, model selection, and safeguards around third-party package
composition.

Perk uses `pi-subagents` as an execution bridge, then adds selector/reviewer/aggregator wave
semantics, bounded manifests, scratch artifacts, report validation, and stage-specific
coordination. Rich UI is centralized in [`extension/surfaces/`](../../extension/surfaces), which
keeps headless behavior independent from TUI availability.

## Part III: intersection map

| Pi change | Current Perk dependency | Perk-owned behavior above Pi | Possible intersection | Status |
| --- | --- | --- | --- | --- |
| Typed values/lists | Custom branch entries + rebuild | Workflow vocabulary, verification, artifact linkage | Store current fields without transcript scans; lists for append-only application records | Overlap candidate |
| Format-4 JSONL/SQLite | v3 Python parser, session-file pointers | Audit normalization, learning corpus, rendering | Parser break; opportunity to consume a stable repository/export API | Direct compatibility risk |
| `retainedTail` compaction | `activeContextWindow()` reads `firstKeptEntryId` | Context-injection dedup policy | Algorithm must adapt to format-4 projection | Direct compatibility risk |
| Durable operations/recovery | SDK prompt + process-local budget/event tracking | Stage prompt, terminal tools, outcome classification | Reuse durable accept/drive/abort/inspect and post-crash state | High-value overlap candidate |
| Usage ledger | Process-local `message_end` accounting | Perk budget policy and workflow-level outcome | Derive durable totals; sequence-safe projection | High-value opportunity |
| Harness lanes | Separate sessions and `pi-subagents` children | Wave roles, manifests, isolation, aggregation | Some parallel work might share a durable session | Experimental hypothesis |
| Server/client/session workers | GHA runner + local SDK worker | Git/worktree/job/delivery orchestration | Alternative local host or attach/debug path | Experimental hypothesis |
| Remote services | In-process extension API and event buses | Provider semantics and workflow contract | Stable facades across process boundaries | Experimental overlap candidate |
| Plugin manifests/facets | `.pi/settings.json` package convergence | Perk config, provider selection, init/doctor | Express package facets/dependencies/lifetimes explicitly | Exploratory opportunity |
| Contribution registries | Perk provider registry + tool composition | Deterministic selection and policy | Reduce bespoke integration if normative registry supports it | Exploratory overlap candidate |
| Views/slots | Perk surfaces + entry renderer/footer/widgets | Workflow presentation and headless invariants | Portable session-to-client rendering | Exploratory opportunity |
| Mouse routing | TUI surfaces | Perk UI policy | Optional interaction improvements | Low-risk enhancement |
| Assistant frame reducer | In-process session event consumption | Perk run-event projection | More robust remote streaming client | Experimental opportunity |

## Detailed hypotheses and decision boundaries

### A. Typed values versus `perk:workflow-state`

Today Perk treats custom entries as an append-only patch log and derives current state per field.
Pi's typed values provide direct current-value reads and atomic writes in an application
namespace. Superficially, they solve the same problem.

What might become overlap:

- current-value storage for `run_id`, `stage`, plan/objective links, counters, and artifact
  digests;
- write/read-back verification using one bound address instead of a full branch scan; and
- schema association at the address boundary rather than repeated structural assertions.

What may remain distinct:

- Perk's historical patch sequence is useful audit evidence, while overwriting a value discards
  old value history;
- Pi's generic fork copies only explicitly handled core addresses and does not automatically
  copy application addresses, while custom entries follow the conversation branch;
- Perk sometimes needs content visible to model-context reconstruction, which a value is not;
- extension-v1 access to application values is not established by the unchanged current API;
  and
- Perk's strict append/rebuild/report seam is a workflow invariant, not only storage plumbing.

Therefore the useful experiment is a field-by-field classification, not wholesale replacement:
which fields need current value only, which need history, which must fork, which must be visible
to the model, and which already have an exterior authority?

### B. Durable drive versus Perk's headless worker

Pi's target accept/drive/requestAbort/inspect surface covers a large part of the inner agent-loop
lifecycle that Perk currently assembles. A stable version could reduce Perk-owned code for:

- durable prompt acceptance;
- crash-aware provider/tool execution;
- retry, deferred, and replay policy;
- settled usage totals;
- abort state and final harness outcome; and
- event publication after durable commits.

Perk still owns:

- selecting `implement` versus `address` and constructing the stage prompt;
- binding the correct extension packages, skills, model, auth, and repository config;
- requiring a stage-specific terminating tool and interpreting its payload;
- turn/token/wall-clock policy even if measurement comes from Pi;
- mapping Pi outcome into Perk status, terminal signal, PR, and error vocabulary;
- run IDs, session pointers, worktrees, Git, GitHub Actions, and delivery trains; and
- deciding when a recovered inner operation is safe and useful in the larger workflow.

The likely opportunity is a thinner Perk adapter around durable drive, not removal of the
worker plane.

### C. Format 4 versus Perk's session audit boundary

Three strategies are plausible; none is selected here:

| Strategy | Benefit | Cost/question |
| --- | --- | --- |
| Teach the Python parser v3 + format 4 | Preserves offline, dependency-light auditing | Couples Perk to physical transaction/value/list grammar and future migrations |
| Ask Pi for/export a stable normalized transcript | Decouples Perk from backend representation | Requires a CLI or library contract suitable for old and partially written sessions |
| Move auditing into a Pi-aware TypeScript adapter | Reuses Pi repository normalization | Changes Perk's Python learning pipeline and packaging boundary |

The first proof should include a v3 file opened read-only, first-write conversion, a native
format-4 JSONL file, and a SQLite-backed session. It must verify custom entries, opaque IDs,
parent/branch reconstruction, compaction context, tool-call pairing, usage totals, and malformed
or torn-tail behavior.

### D. Experimental server versus Perk's remote execution

Pi's server/session-worker topology could improve local resilience and observability:

- a Perk command might submit work to a long-lived local Pi server;
- a human could attach a TUI to a running headless session;
- the worker could survive a presentation client disconnect; and
- session discovery could replace some file-pointer discovery for live sessions.

It does not yet address the remote workflow concerns GitHub Actions provides:

- clean checkout and worktree positioning;
- isolated credentials and job permissions;
- repository event/status integration;
- durable job logs and artifact upload;
- concurrency and cancellation at the CI-provider layer; and
- branch delivery from a remote machine.

A local-server experiment and a GHA-runner experiment answer different questions. Treating one
as a replacement for the other would conflate the Pi session exterior with Perk's workflow
exterior.

### E. Lanes versus `pi-subagents` and Perk waves

Pi lanes allow multiple named execution contexts over one durable session repository. This
could be useful for a selector and several reviewers that need a shared durable base while
keeping leaves/configuration separate.

Open questions prevent a replacement claim:

- Are lanes intended for concurrently driven agents in the application host that Perk can use?
- Can each lane have its own model, tools, thinking level, context policy, and cancellation?
- What isolation exists for working-directory effects and tool permissions?
- How are lane results exported, bounded, and attributed to a Perk wave manifest?
- Do lane forks or session forks provide the artifact lifetime Perk expects?
- Can a failed host resume all wave members without duplicating unsafe tools?

Perk's wave semantics—role selection, prompts, fan-out bounds, artifact paths, validator,
aggregator, and report contract—remain domain behavior. Lanes may eventually replace some child
session plumbing while leaving the wave module intact.

### F. Plugin hosts versus Perk provider/package convergence

Perk currently maps config to packages and lets each loaded package register tools, hooks, and UI
against extension v1. The plugin design proposes explicit manifests, facets, dependencies,
services, and complete-generation reload.

Potential improvements if that design becomes normative:

- `perk init` could converge a declared Perk application facet graph rather than a loosely
  ordered package list;
- footer, plan, and web providers could become explicit service contributions with dependency
  validation;
- headless hosts could omit TUI facets without relying on every extension to gate UI access;
- package removal/reload could rebuild registries coherently instead of depending on ad hoc
  disposal; and
- a session worker could expose Perk state to multiple clients through a narrow remote facade.

Perk still owns provider selection, configuration semantics, workflow tools, and repair policy.
The upstream design does not make `perk init` or `perk doctor` redundant; it might give them a
better target representation.

### G. Views and slots versus Perk surfaces

Perk's surfaces module is already the right internal boundary: workflow code asks for a report,
footer, status, widget, or renderer without importing TUI primitives directly. If Pi views/slots
stabilize, the surfaces implementation could target them while the rest of Perk remains stable.

The key proof is semantic parity in three modes:

- interactive local TUI;
- headless SDK worker with no UI; and
- remote client attached after the session has already produced state.

This is an adapter opportunity. It is not a reason to spread experimental view types through
Perk workflow modules now.

## What remains intrinsically Perk-owned

Even a fully realized Pi roadmap is a runtime/platform substrate. Perk's differentiating domain
contract remains above it:

- plan-oriented stages, stage graph, transitions, and doors;
- objective/plan/gist/review/learn workflow semantics;
- Git branch, worktree, stacked train, publish, cascade, sync, recover, and landing policy;
- GitHub and Linear issue/PR backends;
- run identity and cross-session/cross-job linkage;
- repository initialization, configuration convergence, diagnostics, and repair;
- provider selection for plan/footer/web behavior;
- model, skill, tool, and permission policy per stage;
- terminating tools and structured workflow outcomes;
- reviewer-wave selection, roles, artifacts, aggregation, and report validation;
- CI checks and delivery gates; and
- the contract between Python exterior and TypeScript interior in `shared/`.

Upstream capability should let Perk delete substrate emulation while deepening these domain
modules. It should not move Perk's workflow vocabulary into Pi-specific plumbing.

## Crosswalk with existing planning memos

This survey does not edit or supersede either prior memo. It records how the new evidence changes
their confidence.

### `deepen-headless-execution/memo.md`

Source: [`docs/planning/deepen-headless-execution/memo.md`](deepen-headless-execution/memo.md)

| Prior direction | New status | Why |
| --- | --- | --- |
| Keep Perk's durable orchestration in the Python exterior | **Reinforced** | Harness durability is session-internal; Git/worktree/job orchestration remains outside it. |
| Use bounded Pi SDK recipes for the inner worker | **Reinforced, with simplification opportunity** | Durable drive may become the stable recipe and delete custom lifecycle glue. |
| Use GitHub Actions first for remote execution | **Reinforced for current delivery** | Pi's server is experimental and local-process oriented; remote CI concerns remain uncovered. |
| Keep a typed Perk `RunIntent`/outcome contract | **Reinforced** | Pi outcomes do not include Perk stage, plan, PR, and delivery semantics. |
| Build a Perk conductor/ledger for multi-session execution | **Challenged at the inner boundary** | Pi now owns durable operations and usage inside a session; the Perk ledger should not duplicate those records. |
| A missing durable layer exists between sessions | **Still true, but boundary may move** | Pi session workers/services could host inner durability; Perk still coordinates runs/jobs/worktrees. |
| Do not depend on PTY automation | **Reinforced** | The server/client/service direction favors typed APIs and streams rather than terminal scraping. |
| Reuse Perk waves | **Reinforced** | Lanes may change execution plumbing, not wave semantics. |

The largest revision to test later is whether the proposed ObjectiveExecutionEngine should store
detailed turn/tool/usage progress itself. If Pi exposes stable recovery inspection and ledger
queries, Perk's durable record should reference Pi session/operation identities and store only
workflow-level state.

### `pi-subagents-improvements.md`

Source: [`docs/planning/pi-subagents-improvements.md`](pi-subagents-improvements.md)

| Prior direction | New status | Why |
| --- | --- | --- |
| Improve `pi-subagents` workflow scripting | **Still relevant now** | No released/normative lane-based application API replaces it. |
| Perk owns report-oriented waves | **Reinforced** | Upstream lanes and services do not define selector/reviewer/aggregator contracts. |
| Child sessions are the execution unit | **Newly uncertain long term** | Named lanes may become a cheaper or more recoverable unit for some roles. |
| Parent aggregates bounded child artifacts | **Reinforced** | Durable runtime does not define Perk's artifact or report schemas. |
| Subagent progress is primarily process-local | **Potentially superseded** | Durable lane operations and usage could make execution progress recoverable. |
| Extension APIs are the composition boundary | **Newly uncertain long term** | Plugin facets/services may move composition across host processes. |

The practical reading is to continue treating `pi-subagents` as the current bridge while keeping
Perk's wave module independent of that bridge. A future lane adapter should be able to satisfy
the same wave contract rather than forcing a wave redesign.

## Opportunity backlog, ordered by evidence—not commitment

### Near-term compatibility watch

1. Add a frozen format-4 fixture/probe as soon as Pi declares the format stable enough for
   downstream testing.
2. Track the normative replacement for `firstKeptEntryId` in the API Perk can actually access.
3. Track changes to current extension-v1 types and SDK session construction separately from the
   experimental plugin documents.
4. Track the release status and public enablement guard for direct durable drive.
5. Track whether coding-agent emits or exports a stable normalized transcript across backends.

### Bounded experiments after maturity gates

1. Re-express one non-contextual, non-forked workflow field as a Pi application value and compare
   auditability, failure behavior, and read complexity with the custom-entry path.
2. Drive one read-only Perk child through the durable Harness API, preserving current caps and
   structured handoff, before attempting an implementation worker.
3. Project a Perk budget from the usage ledger and verify exact agreement across a crash/reopen.
4. Run a two-lane read-only reviewer experiment and compare isolation/recovery with two current
   child sessions.
5. Attach an experimental client to a headless local session and test Perk surfaces without
   changing the GHA remote runner.
6. Model the existing plan/footer/web provider set as an illustrative plugin manifest to find
   missing upstream semantics; do not ship that model as config.

### Opportunities deliberately deferred

- replacing `.pi/settings.json` package convergence with plugin manifests;
- moving Perk's interactive extension wholesale to extension v2;
- replacing the GHA worker with a Pi server;
- replacing all custom entries with values;
- moving all subagents into lanes; and
- using SQLite as Perk's own workflow database.

Each depends on a normative or released surface that does not exist at the frozen snapshot.

## Validation matrix for future decisions

| Hypothesis | Affected Perk seam | Maturity prerequisite | Later proof | Confirming evidence | Disconfirming evidence |
| --- | --- | --- | --- | --- | --- |
| Values can replace some workflow-state patches | `workflowState.ts` | Values reachable from supported extension/host API; fork policy documented | Port one low-risk field with dual-read comparison | Same recovery/fork semantics, simpler reads, acceptable audit | Lost history/fork state, no extension access, weaker diagnostics |
| Format 4 can be audited without physical parsing | `session_jsonl.py` | Stable export or repository read API | Golden corpus across v3, converted v3, native JSONL, SQLite | Stable normalized entries/branches/custom data/usage | Backend-specific gaps or no offline/partial-file support |
| `retainedTail` supports Perk's live-context test | `activeContextWindow()` | Stable branch/context projection | Compaction fixtures with quoted custom content | Exact live-entry classification before/after compaction | Summary ambiguity or no access to retained messages |
| Durable drive can thin the worker | `worker.ts` | Public drive enabled; all WP05 paths complete; green upstream CI | Crash/reopen at provider and tool boundaries | No duplicate unsafe effect; equivalent terminal result and budgets | Missing extension/tool hooks, opaque recovery, incompatible abort |
| Usage ledger can own raw budget accounting | `worker.ts` counters | Stable ledger query/events | Compare totals through retries, deferred work, compaction, crash | Exact monotonic totals and durable sequence | Missing categories, late projection ambiguity, inaccessible ledger |
| Pi server can host local Perk runs | launch + worker | Experimental gate removed or API declared stable | Start/attach/cancel/restart concurrent sessions | Stable identity, recovery, extension loading, attach semantics | Races, single-user assumptions, missing auth/config isolation |
| Pi server can replace GHA remote execution | `run_worker.py` + CI | Remote deployment/auth/job contract documented | End-to-end remote worktree run and delivery | Equivalent isolation, logs, cancellation, credentials, artifacts | Server remains local/session-only or lacks delivery integration |
| Lanes can replace some child sessions | subagent/wave bridge | Concurrent lane drive and isolation normative | Two read-only roles + one tool-using role | Equivalent model/tool/context isolation and better recovery | Shared effects/context leak or no per-lane policy |
| Plugin registries can host Perk providers | provider registry/init | Manifest/facet/registry contract normative | Plan/footer/web vertical slice | Deterministic selection, headless facets, coherent reload | Missing config selection, lifecycle, or third-party compatibility |
| Views can back Perk surfaces | `extension/surfaces/` | View/slot protocol normative | Same status/footer/report in local, headless, attached client | One adapter preserves UI/headless behavior | Client-specific state loss or workflow code needs view awareness |

## Watch triggers

Revisit this memo when any of these occurs:

- Pi publishes a release candidate containing the durable harness rewrite.
- Direct durable drive becomes public rather than guarded.
- Format 4 becomes coding-agent's default persisted session format.
- Pi documents a stable normalized transcript/export surface.
- The server/client path leaves `PI_EXPERIMENTAL` or gains a compatibility policy.
- Extension v2 or plugin application hosts become a normative specification or work package.
- The current extension-v1 types/loader/runner change materially.
- Pi documents application-value access and fork policy for coding-agent plugins.
- Lane concurrency and application-host ownership become public contracts.
- The upstream `build-check-test` check is green at the candidate SHA.

At each trigger, freeze new `main`, candidate, and merge-base SHAs before updating conclusions.
Do not silently replace the evidence in this memo with moving branch links.

## Migration principles if the work ships

These principles constrain later plans without selecting one now:

1. **Follow stable contracts.** Do not implement against an exploratory document when current
   extension APIs still work.
2. **Adapt at Perk seams.** Put new session state behind `workflowState`, new drive behind the
   worker runtime seam, new UI behind surfaces, and new subagent execution behind the wave
   bridge.
3. **Preserve exterior/interior ownership.** Pi may deepen the session interior; Perk still owns
   workflow and delivery exterior behavior.
4. **Migrate evidence before deleting readers.** Session audits need golden cross-format proof
   before parser or pointer behavior changes.
5. **Separate compatibility from adoption.** Supporting format 4 is required if released;
   adopting server, lanes, values, or plugin hosts is optional and separately justified.
6. **Require recovery proofs.** Every claimed durability improvement must be tested at effect
   boundaries and process restarts, not inferred from API names.
7. **Delete only proven overlap.** Keep Perk's behavior until the replacement is released,
   reachable in all supported modes, and demonstrated to preserve the Perk contract.

## Source guide

### Upstream primary sources at the frozen `dev` SHA

- [AgentHarness implementation specification](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/harness.md)
- [Bound values and lists](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/values.md)
- [Assistant durability](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/assistant-durability.md)
- [Tool durability](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/tool-durability.md)
- [Direct durable drive work package](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/work-packages/05-direct-durable-drive.md)
- [Telemetry](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/telemetry.md)
- [Application hosts and plugin facets](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/plugins.md)
- [Plugin reloading](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/plugin-reloading.md)
- [Plugin service RPC notes](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/rpc.md)
- [Extension v2 exploratory notes](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/agent/docs/extensions/pi-extensions-v2.md)
- [Experimental coding-agent services](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/coding-agent/src/experimental/services/README.md)
- [TUI mouse region implementation](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/tui/src/components/mouse-region.ts)
- [Assistant-message frame reducer](https://github.com/earendil-works/pi/blob/a17323e5b1e766433e76a3ed7a129f640924c079/packages/ai/src/utils/assistant-message-frame.ts)

### Perk implementation and planning sources

- [`package.json`](../../package.json) — pinned Pi packages and extension package metadata
- [`src/perk/run/launch/__init__.py`](../../src/perk/run/launch/__init__.py) — exterior Pi launch
- [`extension/index.ts`](../../extension/index.ts) — interactive extension entrypoint
- [`extension/substrate/workflowState.ts`](../../extension/substrate/workflowState.ts) — custom
  branch state, compaction window, and verified append
- [`extension/substrate/sessionPointers.ts`](../../extension/substrate/sessionPointers.ts) — run
  to session-file linkage
- [`src/perk/learn/session_jsonl.py`](../../src/perk/learn/session_jsonl.py) — independent v3
  session parser
- [`extension/worker/worker.ts`](../../extension/worker/worker.ts) — bounded SDK headless drive
- [`extension/worker/readOnlySession.ts`](../../extension/worker/readOnlySession.ts) — isolated
  read-only child sessions
- [`src/perk/run/run_worker.py`](../../src/perk/run/run_worker.py) — exterior remote worker
- [`extension/surfaces/`](../../extension/surfaces) — UI/headless boundary
- [`deepen-headless-execution/memo.md`](deepen-headless-execution/memo.md) — existing headless
  architecture assessment
- [`pi-subagents-improvements.md`](pi-subagents-improvements.md) — existing subagent bridge and
  wave plan

## Bottom line

Pi is moving toward a deeper runtime: durable execution, backend-neutral sessions, process
separation, and eventually multi-host plugins. That direction aligns unusually well with the
places where Perk has had to build substrate on top of Pi. The likely long-term result is a
thinner Perk interior with stronger recovery and cleaner host boundaries.

It does not imply a thinner Perk domain. Perk's plan workflow, exterior orchestration, delivery,
providers, wave semantics, and workflow-level contracts remain its own. The safe path is to
track concrete maturity gates, build adapter-level probes, preserve format evidence, and remove
only the substrate that a released Pi contract has actually made redundant.
