# Upcoming Pi changes: implications for Perk, v2

> Superseding point-in-time survey for Perk maintainers, frozen on 2026-09-02. This
> replaces [the 2026-08-20 memo](upcoming-pi-changes-memo.md) as the current assessment.
> The original remains a historical snapshot. This memo describes unreleased Pi work and
> recommends evidence-gated follow-up; it is not a Pi compatibility promise or a Perk
> migration decision.

## Executive summary

Pi's `dev` branch has crossed an important threshold since the first survey. The durable
`AgentHarness` is no longer mostly storage plus a guarded drive design. Public lane drive is
enabled; prompt, tool, retry, deferred, compaction, navigation, abort, recovery, result, usage,
and watch paths have concrete implementations and tests. A small three-process coding agent
proves that a worker can restore a durable operation after the last presentation disconnects.

The application-host direction has also become much more concrete. Pi extracted the generic
runtime into a new, tested `@earendil-works/chord` package with facets, service dependency
assembly, stable service facades, keyed services, replicated state, delta encoding, independent
facet bundles, and generation reload. The experimental coding agent now uses those primitives
for real server, Session-worker, and TUI slices. It can build package-provided Session and TUI
facets, reload them, reuse the stable alternate-screen renderer, and attach a client locally or
through an authenticated Radius relay.

That is substantial implementation, but it is not yet the ordinary Pi programming model:

- Perk is pinned to Pi 0.84.1; the latest released Pi is 0.84.4.
- The ordinary coding agent still uses extension v1, the coding-agent SDK, and
  `SessionManager` format 3.
- `@earendil-works/chord` and Pi's facet host are absent from the 0.84.4 release tree.
- The client/server/facet path still requires `PI_EXPERIMENTAL=1`.
- Format 4 is explicitly pre-stabilization and can still change in place.
- WP08 fork transfer is incomplete, `watchSession()` remains stubbed, telemetry is partial,
  schema migration is activation-gated, and the frozen head contains a WP09 implementation
  handoff rather than the WP09 implementation.

The first memo's central caution therefore remains correct, but several maturity judgments have
changed:

1. **Durable drive is implemented on `dev`, not merely designed.** It is now the strongest
   candidate for simplifying Perk's `StageRunner` implementation.
2. **Format 4 is real but not stable or default.** Perk's Python format-3 reader is not facing
   an immediate released-format break; the risk arrives when Perk adopts a Harness-backed
   coding-agent host or Pi makes that host ordinary.
3. **Application-value fork behavior now argues against a wholesale state move.** The current
   WP08 contract copies application values/lists for tree forks and excludes them for branch
   forks. Perk intentionally inherits much of its workflow state along the active branch.
4. **Chord is a working substrate, not just vocabulary.** Pi's use of it is still experimental,
   but its boundaries closely match the application-adapter destination Perk designed in the
   TypeScript decomposition.
5. **The server is no longer only a local-process sketch.** Radius provides remote attachment
   to the same server, but it transports a presentation to compute; it does not provision
   checkout, credentials, job isolation, logs, or delivery. It does not replace Perk's GitHub
   Actions exterior.
6. **Lanes have a public operation surface and a live presentation proof.** They are a credible
   future execution backend for `ReportWave`, but they do not supply Perk's role, artifact,
   completeness, or filesystem-isolation semantics.
7. **“Extension v2” is no longer the useful framing.** The exploratory extension-v2 note was
   deleted. The concrete direction is independently bundled Chord facets plus semantic
   services. Extension v1 remains the default and has continued to evolve.
8. **Perk is better prepared than it was on 2026-08-20.** TypeScript-decomposition Phases 1–7
   have put workflow behavior behind `WorkflowSession`, `StageRunner`, `ReportWave`, feature
   operations, and Pi-v1 adapters. Pi can now be evaluated at those seams rather than through a
   second broad Perk rewrite.

The recommended posture is **prepare and probe, not migrate**. Keep the current v1 bridge and
Perk-owned exterior. Make durable `AgentLane` drive the first parity experiment behind
`StageRunner`. Follow with narrowly scoped state, wave, facet, and remote-attachment probes.
Adopt production surfaces only after Pi publishes them, stabilizes their storage and lifecycle
contracts, and demonstrates parity with Perk's existing behavior.

## Snapshot and method

### Frozen upstream comparison

| Item | Frozen value |
| --- | --- |
| Pi `main` | [`e266507`](https://github.com/earendil-works/pi/commit/e266507b606b9552fa277252644054afd4384b11) |
| Pi `dev` | [`6e8b9c8`](https://github.com/earendil-works/pi/commit/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695) |
| Merge base | [`96317e5`](https://github.com/earendil-works/pi/commit/96317e50b8d6e7f6d0e47fd29122baf1461c00f5) |
| Relationship | `dev` is 387 commits ahead and 8 commits behind `main` |
| Three-dot change set | 558 files, 90,200 insertions, 23,752 deletions |
| Frozen comparison | [`main...dev` at the two SHAs](https://github.com/earendil-works/pi/compare/e266507b606b9552fa277252644054afd4384b11...6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695) |
| Previous memo's `dev` | [`a17323e`](https://github.com/earendil-works/pi/commit/a17323e5b1e766433e76a3ed7a129f640924c079) |
| Change since v1 snapshot | 210 commits; 615 files, 67,250 insertions, 27,607 deletions |
| Frozen v1-to-v2 comparison | [`a17323e...6e8b9c8`](https://github.com/earendil-works/pi/compare/a17323e5b1e766433e76a3ed7a129f640924c079...6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695) |
| Latest Pi release | [0.84.4](https://github.com/earendil-works/pi/releases/tag/v0.84.4), published 2026-08-28 |
| Perk source snapshot | [`a5dc757`](https://github.com/mattgiles/perk/commit/a5dc757e727bd478122c379f292258471eca329e) |
| Perk package baseline | `@earendil-works/pi-{ai,coding-agent,tui}` 0.84.1 in [`package.json`](../../package.json) |

The first comparison describes the current work unique to `dev` from its merge base with the
frozen `main` head. The second describes what changed after the first memo's `dev` snapshot.
They answer different questions: “what is unreleased now?” and “which earlier conclusions need
reassessment?” Because `main` and `dev` diverge, neither is presented as a release diff.

The current `main...dev` work remains concentrated in the runtime and application-host areas:

| Package area | Changed files | Insertions | Deletions | Reading |
| --- | ---: | ---: | ---: | --- |
| `agent` | 212 | 53,671 | 10,952 | Durable drive, session semantics, tools, conformance, active work packages |
| `coding-agent` | 140 | 15,580 | 3,559 | Experimental host, facets, services, client/TUI, Session workers |
| `chord` | 39 | 10,840 | 0 | New standalone composition runtime |
| `session-backends` | 52 | 3,821 | 3,941 | SQLite ownership, snapshots, forks, conformance |
| `server` | 30 | 1,765 | 2,441 | Routing and transport simplification |
| `client` | 22 | 1,313 | 1,811 | Connection and remote-service integration |
| `tui` | 14 | 1,293 | 35 | Mouse and large-transcript work |
| `ai` | 23 | 1,255 | 115 | Streaming, provider, and assistant-frame support |
| `protocol` | 10 | 312 | 853 | Narrower Pi-owned routing over Chord service semantics |

### CI condition at the snapshot

At the frozen `dev` SHA, Pi's
[`build-check-test` job](https://github.com/earendil-works/pi/actions/runs/33619144703/job/100211874288)
is green: install, build, check, and test all succeeded. The experimental concurrent-start
failure recorded by v1 is no longer the branch condition.

Green CI is necessary evidence, not a maturity label. The head commit adds the WP09 tool
settlement handoff; it does not implement that handoff merely because the existing suite passes.
Similarly, explicitly deferred methods and design-only surfaces remain deferred even on a green
branch.

### Evidence rules

This memo uses upstream documentation to learn the intended contract, then checks that claim
against public exports, production source, tests, command gating, and CI. Commit subjects are a
census aid, not proof on their own. Links to upstream source are pinned to the frozen `dev` SHA.

Maturity labels mean:

| Label | Meaning |
| --- | --- |
| **Released/default** | Present in a published release or the ordinary coding-agent path. |
| **Implemented on `dev`** | Production code and tests exist at the frozen SHA; still unreleased unless separately stated. |
| **Experimental** | Implemented code exists behind the experimental command/path or an explicitly experimental contract. |
| **In progress** | A work package, method, or required behavior is explicitly incomplete. |
| **Design specification** | Detailed intended semantics exist, but implementation coverage is partial or the document says it is experimental. |
| **Perk inference** | A conclusion about Perk; not an upstream promise. |

An “overlap candidate” is a Pi substrate that may replace plumbing Perk currently supplies.
“Redundant” requires a released, supported replacement that has passed Perk parity. Nothing in
this memo makes a current Perk domain behavior redundant.

## Architecture at the frozen snapshot

There are still two coding-agent paths, but the proposed path is now a working vertical slice:

```text
ordinary/default Pi                         experimental application host
-------------------                         -----------------------------
Perk Python exterior                        local or Radius presentation
  -> ordinary pi process                      -> Pi server
     -> coding-agent AgentSession                 -> Session worker
        -> SessionManager v3                         -> Chord facet host
        -> extension-v1 loader/runner                   -> semantic services
           -> Perk pi/v1 adapters                         -> AgentHarness + AgentLane
              -> typed Perk features                       -> SessionRepo format 4

Perk StageRunner
  -> in-process coding-agent SDK
     -> AgentSession + SessionManager v3
```

The right side is not a speculative box anymore. It runs, has integration tests, can load
package facets, and can restore open Harness operations. It remains experimental and has not
replaced the left side. Perk's compatibility decisions must therefore ask both:

1. what is implemented in the monorepo; and
2. what a supported Perk integration can actually reach.

## Part I: reassessing the first memo

| V1 reading | Current evidence | V2 judgment |
| --- | --- | --- |
| Direct durable drive is guarded and unfinished | WP05 is complete through M10; `AgentLane.accept`, `drive`, `requestAbort`, convenience operations, and lane watch are public | **Reversed: implemented on `dev`** |
| The frozen branch is red on an experimental server race | Current build/check/test is green | **Reversed at this snapshot** |
| Remote service primitives live mainly in Pi's agent design | Generic services, facets, state, bundling, and reload moved into tested `@earendil-works/chord` | **Substantially implemented, still unreleased** |
| Server/client/session-worker is a thin local experimental slice | Fullscreen TUI reuse, semantic services, per-Session facets, reload, and Radius attachment landed | **Broader experimental vertical slice** |
| Lanes are a plausible but uncertain subagent substrate | Public `AgentLane` operations, lane snapshots, recovery, and a real three-process client exist | **Credible adapter target; isolation questions remain** |
| Format 4 is implemented except future migrations | Three backends and v3 normalization exist, but upstream now explicitly calls format 4 WIP and pre-stabilization | **Narrowed: implemented storage, unstable contract** |
| Extension-v1 core is unchanged | Extension loading became transactional on factory failure, UI-prompt events landed, and bundled-Node support changed loading | **No longer unchanged; still the default API** |
| Extension v2, views, and slots are the likely future API vocabulary | The extension-v2 note was deleted; narrow Chord facets/services and concrete presentation services now lead | **Reframed around facets and services** |
| Perk would first need internal seams before adopting the new host | Decomposition Phases 1–7 now provide `WorkflowSession`, `StageRunner`, `ReportWave`, and typed feature operations | **Perk preparation materially advanced** |

The important correction is not “v1 was too cautious.” The implementation changed rapidly in
thirteen days, and upstream also withdrew or replaced parts of its own designs. The durable-drive
gate opened; a planned remote-events abstraction was removed; the plugin runtime moved into
Chord; “extension v2” stopped being the active frame; and fork semantics were redesigned again.
The evidence continues to favor adapters at stable Perk seams over premature use of upstream
vocabulary.

## Part II: upstream change census

### 1. Durable `AgentHarness` drive is now real

#### Public lane surface

**Implemented on `dev`.** [WP05](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/work-packages/05-direct-durable-drive.md)
is complete through M10. The public
[`AgentLane` interface](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/src/harness/agent-harness.ts)
now exposes:

- split `accept(request)` and `drive({operationId, ...})` operations;
- direct `requestAbort(operationId)` and inspection;
- `prompt`, `skill`, prompt-template, compaction, navigation, `resume`, and `abort`
  conveniences;
- steer, follow-up, and next-run queues;
- result lookup, explicit usage recording, configuration changes, idle coordination, and a
  coherent lane snapshot/stream watch.

`AgentHarness.create` returns both the attached Harness and the open-operation inventory. The
host can inspect a restored operation, claim its drive, and continue from its durable state.
`DriveOutcome` distinguishes terminal settlement from retry and deferred waits. No nominal
deadline pretends to cancel an already admitted effect.

This is a much better candidate for programmatic headless work than v1's unfinished drive. It is
also lower-level than Perk's `StageRunner`. It does not know a Perk stage, plan, terminal tool,
run-event record, worktree, PR, or delivery outcome.

#### Durable transitions and effects

**Implemented on `dev`.** The
[Harness specification](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/harness.md)
now describes and the runtime tests exercise:

- lane-owned inboxes and immutable terminal result records;
- atomic acceptance and atomic run/structural boundaries;
- assistant generation with retry and deferred polling;
- durable tool planning, execution checkpoints, and terminal cleanup;
- total dispatch over the operation-state graph;
- explicit abort request and cancellation reconciliation;
- crash-style close, restore, and re-drive;
- post-commit event publication and coherent snapshot-plus-stream observation; and
- durable usage rows and ledger-derived totals.

The runtime separates durable intent from live effect ownership. Recovery does not infer a
missing operation from transcript gaps; it resumes from the recorded operation state. Unsafe or
unknown effect outcomes are represented and reconciled rather than blindly repeated. These are
the semantics Perk's process-local SDK loop has had to approximate around the current
`AgentSession`.

The [runtime suite](https://github.com/earendil-works/pi/tree/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/test/harness/runtime)
has focused coverage for public drive, total reconciliation, cancellation, assistant generation,
retry/deferred work, tool batches, terminal results, restoration, watches, and reducers. The
coding-agent
[`mini` proof](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/coding-agent/src/experimental/mini/README.md)
kills a Session worker when its last presentation disconnects and resumes an open durable
operation in the replacement worker.

**Perk inference.** The recovery boundary is now strong enough to justify a `StageRunner`
parity experiment. It is not strong enough to assume parity: Perk must prove its extension
tools/hooks can be represented, its terminal tool is observed exactly once, abort maps to its
budget semantics, and its run-event totals agree after crash and recovery.

#### Remaining Harness gaps

The current [implementation-status section](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/harness.md#L137)
is unusually explicit. Important gaps for Perk are:

- **`watchSession()`:** the only stubbed public Harness method. Lane watch works; a complete
  Session-wide lane inventory stream does not.
- **Telemetry:** the vocabulary is broader than production instrumentation; only a narrow
  subset is started and RPC trace propagation is absent.
- **Schema migrations:** specified but activation-gated; no format-4 migration exists.
- **JSONL snapshot compaction:** specified but not implemented, so old bytes are not reclaimed.
- **Search:** design only.
- **Remote `Session`:** the old raw remote-mutation contract conflicts with the product's
  process-local Session plus routed semantic services and awaits an explicit decision.
- **Conformance closure:** documented invariants outnumber dedicated tests in several corners.
- **WP08:** named-branch and streaming forks are only partly implemented.
- **WP09:** the frozen head adds a handoff for keeping settled-but-unplaced tool calls visible
  in `LaneSnapshot.operation.runningTools`. It is not yet the implementation.

These are bounded gaps, not evidence that public drive is fictional. They do matter to a Perk
probe: a worker adapter must not use `watchSession()`, telemetry cannot be its only accounting
source, and UI/report consumers must handle the WP09 snapshot limitation honestly.

### 2. Session, Branch, Lane, storage, and forks

#### Explicit ownership

**Implemented on `dev`.** [WP06](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/work-packages/06-session-branch-lane-separation.md)
separates four concepts:

```text
Session       global durable data + one mutation line
Branch        one named path through the entry tree
AgentLane     Branch + agent configuration + operation state
AgentHarness  manager of AgentLanes
```

There is no implicit `main`. A Branch can exist as data without being a configured agent lane.
`AgentHarness.lane(name)` atomically acquires or creates a complete lane and rejects partial
state as corruption. This gives Pi a precise place to host multiple agent execution contexts in
one durable Session.

**Implemented on `dev`.** [WP07](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/work-packages/07-sqlite-host-ownership-live-forks.md)
removes storage-layer writer leases and makes the host responsible for assigning exactly one
writable Session owner. SQLite supports explicit open modes, live read-only WAL snapshots,
safe physical identity, deletion reservation, and all-settled close. This aligns storage with
the server/worker topology rather than trying to make the database select process ownership.

**Perk inference.** Pi's lane boundary could host concurrent read-only reviewers or independent
agent configurations. It does not isolate their filesystem effects. Perk still needs to decide
whether roles may share a checkout, tools, credentials, and mutation authority.

#### Format 4 is implemented and unstable

The Harness has Memory, JSONL, and SQLite backends with a shared conformance model. JSONL uses
a format-4 header, transaction lines, entries, scalar values, list values, and usage. SQLite
uses the same logical Session model. Coding-agent format-3 JSONL can be normalized read-only
and rewritten atomically on the first non-empty format-4 commit.

At the same time, upstream now labels format 4 **WIP and pre-stabilization**. Pre-stabilization
shapes are replaced in place without a storage-version migration. JSONL/SQLite reject unknown
storage versions, and the first future incompatible change after stabilization is what activates
the migration design.

This distinction was not sharp enough in v1:

- format-4 code and conformance are real;
- format-4 files created by this unreleased work are not promised compatibility;
- ordinary coding-agent `SessionManager` remains
  [`CURRENT_SESSION_VERSION = 3`](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/coding-agent/src/core/session-manager.ts);
  and
- Perk encounters format 4 only if the supported coding-agent path changes or Perk deliberately
  adopts the Harness repository.

Format-4 compaction still replaces format 3's `firstKeptEntryId` with a self-contained
`retainedTail`. That remains a direct incompatibility with Perk's current live-context
algorithm, but it is a gated future incompatibility rather than a current released failure.

#### Fork semantics now constrain application state

**In progress.** [WP08](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/work-packages/08-named-branch-streaming-forks.md)
replaces the generic fork shape with explicit scopes:

```ts
type ForkOptions =
  | { scope: "branch"; branch: string; entryId?: string; position?: "before" | "at"; id?: string }
  | { scope: "tree"; id?: string };
```

The explicit scope, named branch, ancestry checks, configured-lane checks, and closed scalar
namespace classifier are implemented. List transfer, sequence/high-water preservation, direct
Memory construction, and bounded JSONL/SQLite streaming remain unfinished.

The intended policy is already important:

- a branch fork copies one named path and reconstructed lane configuration, but no arbitrary
  application values or lists;
- a tree fork copies the complete immutable tree and current application values/lists;
- operation, pending-effect, result, and usage state is excluded or reset;
- branch-scoped application state must be re-derived; and
- old replaced scalar values and deleted list elements are not available as a historical log.

**Perk inference.** `perk:workflow-state` is not merely an inefficient key/value store. It is a
branch-carried patch log. Perk's `active_plan_ref`, objective claim, mode/stage, review records,
and other fields have explicit inherit/reset/recompute policies. Moving them wholesale into Pi
application values would silently turn branch inheritance into absence. Any future
`WorkflowSession` backend must classify fields one by one.

### 3. Chord turns the host design into a reusable runtime

#### What is implemented

**Implemented on `dev`; unreleased.**
[`@earendil-works/chord`](https://github.com/earendil-works/pi/tree/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/chord)
is a standalone application-composition runtime. It has no dependency on another Pi workspace
package and is intended to be usable outside Pi. Its public package exports and tests cover:

- synchronous facet setup, complete dependency-graph validation, provider-before-consumer
  activation, resource ownership, and reverse-order disposal;
- singleton and keyed service tokens, local-only services, stable consumer facades, and
  provider replacement;
- replicated authoritative state with hydration readiness and independent client streams;
- compact JSON delta generation and validated immutable application;
- a transport-independent remote-service catalogue, call, subscription, snapshot, update, and
  error grammar;
- separate, content-addressed CommonJS facet bundles built with esbuild;
- SHA-256 verification, application-controlled external resolution, and fresh `node:vm`
  loading outside the normal module cache; and
- shape-preserving generation reload while retained singleton handles keep working.

Chord does not install dependencies, select Pi packages, prescribe a transport envelope, own
authentication, or know about Harness, tools, TUI, sessions, or Perk. Applications supply those
policies. Symmetric general RPC is still a planned optional layer; Pi currently supplies its own
routing envelope around Chord's service semantics.

This extraction matters for confidence. Facets and services are no longer only examples in a
large Pi design note. The generic lifecycle and replication machinery has a public source
boundary and focused tests. It is still unreleased: the Chord package is not present in the
0.84.4 tag.

#### Pi's use of Chord remains experimental

Pi's
[application-host specification](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/plugins.md)
is explicitly a design specification for the experimental architecture. It composes Chord into
three process roles:

- a server host owns Session records, worker management, authentication, attachment, and
  routing;
- a Session host owns one real Harness and Session authority; and
- a presentation host owns TUI behavior and consumes presentation-safe semantic services.

An extension package distributes independent facets to those hosts. It is not loaded as one
cross-process object, and there is deliberately no universal `CodingAgentPlugin` interface.
Shared strict-JSON service contracts connect the independently loaded bundles.

This is a better match for Perk than a monolithic “extension v2.” Perk already separates a
Python exterior, Session behavior, headless drive, report execution, providers, and TUI
surfaces. It also creates a new requirement: a future Perk package would need separately built
Session and TUI facets, not a mechanical translation of `extension/index.ts`.

### 4. The experimental coding agent is now an end-to-end host

#### Semantic service slices

**Experimental.** The
[service inventory](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/coding-agent/src/experimental/services/README.md)
lists working slices:

| Scope | Service | Implemented behavior |
| --- | --- | --- |
| server | `SessionDirectory` | Replicated session summaries |
| server | `SessionManagement` | Create, remove, attach, detach |
| server | `PresentationPlugins` | Build and reload selected Session's matching TUI artifacts |
| Session | `SessionPlugins` | Reload configured Session facet generation |
| Session | `Models` | Model/thinking state, persistence, refresh |
| Session | `AgentController` | Presentation-safe prompt, queue, abort, resume, compaction, navigation |
| Session | `Transcript` | Replicated lane state with source-event metadata |
| presentation | `SlashCommands` | Local contribution registry and built-in command slices |
| presentation | `PresentationUI` | Narrow selection and status capabilities |

The server and worker generate service catalogues from actual facet provisions. Consumers declare
requirements through `env.use()` or `env.observe()`; they do not maintain a second handwritten
service inventory. The server routes selected-Session services without exposing the Harness,
Session, tool registry, storage, credentials, or working directory to the presentation.

The experimental TUI uses stable coding-agent editor, message, tool, status, theme, and
alternate-screen components. Chord replicates a complete Transcript value, encodes delta
operations independently per client/state pairing, and rehydrates on reconnection or provider
replacement.

#### Package facets and reload

**Experimental.** Repeatable `-e` options select package directories. Chord discovers
conventional `src/session.ts` and `src/tui.ts` entries, builds them into separately owned
artifacts, and gives each host only its facet. Per-Session package selection persists with that
Session and does not alter other workers. The
[example plugin](https://github.com/earendil-works/pi/tree/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/coding-agent/examples/plugins/pi-example-plugin)
provides a Session service and a TUI `/hello` command through the public experimental plugin
subpath.

`/reload` rebuilds candidates, validates and activates a new facet graph, cuts it over, and
disposes the retired generation. Stable singleton service handles survive an ordinary
shape-preserving reload; keyed instances receive new generations.

Important limitations remain:

- the surface is exported under `@earendil-works/pi-coding-agent/experimental/plugin`;
- Radius clients cannot select server-local package paths;
- authenticated workspace/plugin authorization is still a continuation point;
- coordinated multi-worker reload reporting is incomplete;
- rich examples such as questions, diff review, canvas, and indexing remain patterns rather
  than built-in services; and
- private references, trace carriers, and flow control remain infrastructure work.

**Perk inference.** Chord's generation semantics are promising for Perk providers and standing
UI state, but a safe reload proof must include Perk's event subscriptions, report-wave pending
state, footer/status state, and run-scoped scratch resources. “The service handle survived” is
not enough.

#### Radius changes the topology, not the execution owner

**Experimental.** The server maintains an authenticated multiplexed WebSocket connection to a
Radius relay. A client can connect to `radius://<server-id>`, and reconnect behavior is tested.
The relay transports the same Pi client/server connection that a Unix socket carries locally.

This enables:

- attaching a presentation from another machine;
- observing and controlling a worker-owned durable Session without co-locating the TUI;
- reconnecting after an abnormal relay close; and
- using the same semantic service contracts across local and remote presentation.

It does not:

- create a repository checkout or worktree;
- place a branch at a plan;
- provision model/GitHub credentials for a job;
- select a secure remote compute environment;
- produce CI-provider logs, statuses, and artifacts;
- enforce Perk's delivery and cancellation policy; or
- make a server's local filesystem path meaningful to a remote client.

**Perk inference.** Radius is a potential attach/debug/approval channel for a headless Perk run.
The Pi server or a GHA job still has to own the compute and checkout. Radius therefore
complements the remote runner; it does not replace it.

### 5. Extension v1 and format 3 remain the supported bridge

The first memo observed that extension-v1 types, loader, runner, and docs were unchanged in its
frozen comparison. That is no longer literally true:

- extension factories now commit runtime registrations only after successful initialization
  and discard failed factory state;
- extensions can observe UI-prompt lifecycle events;
- bundled Node distribution changed virtual-module loading; and
- extension documentation continued to grow around Session replacement and UI behavior.

Most of those changes shipped in 0.84.3/0.84.4. They evolve extension v1 rather than replace it.
The ordinary `pi` entry still constructs `AgentSession`/`SessionManager` and loads extensions
through that API. The SDK still documents `createAgentSession` with `SessionManager`. The
ordinary persisted format remains version 3.

The exploratory `pi-extensions-v2.md` file from v1 was deleted. Its useful architectural ideas
were not all abandoned; they were redistributed into Chord, the Pi facet specification, and
concrete services. The consequence for Perk is:

- keep extension v1 as the current compatibility bridge;
- track its real incremental changes during normal Pi bumps;
- do not invent an “extension v2 adapter” against a deleted note; and
- treat the facet host as a separate experimental integration until Pi publishes a supported
  package and compatibility policy.

### 6. Smaller changes relevant to Perk

The branch also contains improvements that are useful but do not alter the main architecture:

- Harness tools now include bounded shell-output capture and adaptive update publication,
  reducing the risk that remote presentation or storage is overwhelmed by unbounded output.
- Assistant frames and Transcript delta publication support burst-safe streaming and cheaper
  replication.
- TUI mouse support and large-transcript benchmarking improve interactive clients.
- Bundled Node and deferred extension loading change distribution/startup behavior.

Perk should receive released versions of these through ordinary compatibility upgrades. None
justifies coupling Perk feature code directly to the experimental host.

## Part III: how Perk uses Pi now

Perk changed materially after the first memo. The user-visible workflow did not move to the new
Pi host; its TypeScript ownership boundaries did.

### 1. Exterior launch and remote orchestration

[`src/perk/run/launch/`](../../src/perk/run/launch/) still owns the cold session exterior:
stage and plan selection, run-id minting, worktree positioning, extension/package
materialization, skill delivery, handoff state, model selection, and `pi` process replacement.

[`src/perk/run/run_worker.py`](../../src/perk/run/run_worker.py) still owns remote worker setup:
checkout/branch position, packaged extension and skills, process lifetime, and normalized
outcome delivery. GitHub Actions remains the current remote execution host.

These responsibilities are above an agent runtime. Chord can improve the interior application
host; Radius can connect a presentation; neither decides which plan branch is safe to mutate or
how a PR is delivered.

### 2. Typed features behind Pi-v1 adapters

TypeScript-decomposition Phases 1–7 are complete at the Perk snapshot. Authoring, delivery, code
review, and learning expose typed operations. Current Pi registrations are concentrated in
[`extension/pi/v1/`](../../extension/pi/v1/), while feature code uses Perk vocabulary rather
than raw extension contexts.

This is the most important downstream change since v1. The future Pi host does not need to
become Perk's application kernel. Its facets can call the same typed operations the v1
installers call today.

### 3. `WorkflowSession` and branch-carried state

[`WorkflowSession`](../../extension/session/workflowSession.ts) is the feature-facing seam for
run identity, verified session artifacts, named reads, and a closed union of proven state
changes. Its production
[branch backing](../../extension/session/branchWorkflowSession.ts) still delegates to
`perk:workflow-state` custom entries and strict append/read-back verification.

The current field classification is already richer than “put this object in a database.” Fields
may inherit across a branch fork, reset across a run, recompute from parent identity, remain an
append-only audit, enter model-visible results, or link to external artifacts. That
classification is exactly what a future values/lists backend must preserve.

[`activeContextWindow()`](../../extension/substrate/workflowState.ts) still reads
`firstKeptEntryId` from a v3 compaction. A format-4 context adapter must instead consume a
stable projection of `retainedTail`.

### 4. `StageRunner` boundary

[`runStage()`](../../extension/worker/stageExecution.ts) owns Perk's headless `implement` and
`address` semantics: stage input, budgets, counters, terminal signals, normalized outcome, and
Perk run events. Its private
[SDK adapter](../../extension/worker/sdkAdapter.ts) translates current coding-agent events and
constructs the SDK session.

This is now a clean replacement point. A durable-Harness adapter should implement the existing
stage contract; it should not cause feature code or Python to learn `AgentLane` states.

### 5. `ReportWave` boundary

[`ReportWave`](../../extension/waves/reportWave.ts) owns report assignments, validation,
completeness policy, normalized failures, and receipts. The
[transport seam](../../extension/waves/transport.ts) describes spawn, completion, stop, and
aggregate reads. The production
[RPC adapter](../../extension/waves/rpcAdapter.ts) currently targets `pi-subagents`.

This separation makes a future lane adapter possible without redefining selector, reviewer,
aggregator, artifact, or report semantics.

### 6. Session auditing remains a physical-format dependency

[`src/perk/learn/session_jsonl.py`](../../src/perk/learn/session_jsonl.py) independently parses
format-3 coding-agent JSONL for learning/audit. It expects one header object and one entry
object per line, v3 entry vocabulary, branch parent IDs, custom entries, compaction details,
tool messages, and usage fields.

It does not parse format-4 transaction arrays, values/lists, usage rows, or a SQLite Session.
Its leniency protects against unknown fields, not a different storage grammar.

This dependency remains safe for the current supported host and unsafe to carry unchanged into
a Harness-backed host.

### 7. Surfaces remain the right UI boundary

[`extension/surfaces/`](../../extension/surfaces/) is still the exclusive rich-UI boundary.
Feature code asks for semantic reports/status/footer behavior; headless execution does not
require a TUI.

Pi's current experimental presentation services are deliberately narrow, and there is no
generic serialized view tree to adopt. A future adapter may distribute Perk UI behavior across
Session and TUI facets, but the surfaces boundary should remain above Chord and TUI primitives.

## Part IV: intersection and decision map

| Pi change | Current Perk seam | What Pi can plausibly replace | What remains Perk-owned | V2 posture |
| --- | --- | --- | --- | --- |
| Public durable `AgentLane` drive | `StageRunner` SDK adapter | Accept/drive/recover/abort, raw events, usage | Stage prompt, budgets, terminal tools, run events, outcome | **First parity experiment** |
| Values/lists and explicit fork policy | `WorkflowSession` branch backing | Selected current-value storage | Field meaning, fork/history/verification/artifact policy | **Classify field by field** |
| Format 4 and `retainedTail` | Context adapter + Python audit | Stable repository/context projection | Prompt-evidence and learning/audit meaning | **Compatibility gate before host adoption** |
| Named lanes | `ReportWave` transport | Child execution and recovery plumbing | Roles, manifests, reports, artifacts, completeness, receipts | **Later bounded experiment** |
| Chord facets/services | Pi-v1 adapters and provider seams | Host lifecycle, remote service binding, reload | Typed features, config choice, workflow policy | **Phase-8 target after publication** |
| Chord replicated state/deltas | Surfaces and live progress | Snapshot/hydration/update transport | Presentation semantics and headless invariants | **Adapter opportunity** |
| Package facet bundling | `perk init` package convergence | Separate Session/TUI entries and reload | Package selection, version/policy, repair | **Model now; do not ship** |
| Experimental server/workers | SDK worker process | Session-local durable process ownership | Worktree/job/delivery exterior | **Local host candidate** |
| Radius relay | Remote observation/control | Presentation transport and reattachment | Compute provisioning, credentials, CI, delivery | **Attach-only experiment** |
| Evolving extension v1 | Current `pi/v1` installers | Incremental supported host behavior | Compatibility tests and adapter composition | **Retain and bump normally** |
| Stable TUI reuse | Surfaces adapter | Rendering implementation | UI policy and no-UI behavior | **Low-risk future adapter** |

## Detailed implications

### A. Workflow state: use values only where branch semantics permit

Pi values offer direct reads, atomic writes, namespace ownership, and coherent transactions.
Those are attractive for fields that represent current Session-wide state.

They do not automatically preserve what Perk gets from custom branch entries:

- append history;
- active-branch inheritance;
- relationship to transcript position;
- selective model-context handling;
- v1 extension reachability; and
- the same evidence in the physical session log used by audits.

The new fork policy makes the mismatch explicit. Branch forks exclude application state. Tree
forks copy current values/lists but not overwritten/deleted history. Perk's current branch fork
inherits several LWW fields precisely because the source entries remain on the copied path.

Recommended classification:

| Perk state kind | Candidate Pi storage | Reason |
| --- | --- | --- |
| Session-global current setting with no audit need | Application value | Direct read and transaction are useful |
| Append-only operational record with no transcript relationship | Application list, after fork/list completion | Preserves ordered current elements, not deleted history |
| Branch-inherited workflow fact | Custom entry or explicit re-derivation | Generic branch fork excludes application state |
| Run identity derived across fork/adopt | Perk derivation plus durable reference | Identity policy remains Perk-owned |
| Artifact pointer with digest/read-back discipline | `WorkflowSession`-owned hybrid | Storage location does not replace verification |
| Context-visible block | Entry/projector path | A value is not conversation placement |

The first state probe should use one low-risk, non-contextual, Session-wide field and compare
read complexity, reload, branch fork, tree fork, inspection, and failure behavior. Do not begin
with `run_id`, stage/mode, active plan/objective, review ledgers, or artifact pointers.

### B. Durable drive: the highest-value experiment

The current SDK adapter owns substantial lifecycle glue:

- session/runtime construction;
- event translation;
- token/turn/time counters;
- budget abort;
- terminating-tool observation;
- pointer recording;
- extension loading; and
- cleanup and outcome normalization.

`AgentLane` can plausibly replace session-local pieces: operation acceptance, durable progress,
retry/deferred waits, effect recovery, raw usage, abort, and coherent observation. It cannot
replace Perk's policy vocabulary.

The first experiment should implement a second private `StageRunner` adapter over a frozen
Harness build and run the same disposable stage scenario through both adapters. It must prove:

1. identical initial prompt and active tool set;
2. the Perk terminating tool settles exactly once;
3. provider/tool crashes resume without duplicate unsafe effects;
4. external cancellation and each budget trip map to the same `RunOutcome`;
5. usage totals agree through retry, deferred work, and restart;
6. Perk run events remain ordered and complete;
7. session pointers/audit evidence remain discoverable; and
8. extension-provided tools and hooks have a supported facet/Harness representation.

Failure on item 8 is an admission failure, not an invitation to copy all v1 registration logic
into the adapter. The experiment should wait for a publishable Pi package or use a deliberately
throwaway frozen-source harness; no production dependency should point at moving `dev`.

### C. Format compatibility: separate current safety from future migration

Perk's current parser is compatible with the host it currently uses. Supporting 0.84.4 does not
require teaching it format 4, because ordinary `SessionManager` still emits v3.

Before a Harness-backed host becomes supported, Perk needs a golden corpus:

- native coding-agent v3;
- v3 opened read-only through the Harness;
- v3 after first format-4 write;
- native format-4 JSONL;
- format-4 SQLite;
- compaction with `retainedTail`;
- custom entries and opaque embedded IDs;
- tool call/result pairing and usage totals; and
- torn/malformed tail behavior.

Preferred boundary, in order:

1. a stable Pi export/projection API across JSONL and SQLite;
2. a small TypeScript adapter using the published Session repository API;
3. dual physical parsers only if offline partial-file auditing remains a required capability.

The Python learning pipeline should not learn SQLite and every WIP transaction spelling merely
because those bytes exist on `dev`.

### D. Lanes can replace transport, not waves

Pi now answers several v1 open questions: lanes have names, independent configuration, public
operations, cancellation, snapshots, and durable recovery. That makes a two-lane reviewer proof
reasonable after Harness publication.

Still unproven for Perk:

- working-directory and filesystem-effect isolation;
- per-role permission/tool policy under one worker;
- concurrent drive and provider limits;
- bounded artifact export;
- model and credential separation;
- behavior when one unsafe tool outcome is unknown; and
- mapping tree/branch forks to ephemeral reviewer lifetimes.

The experiment should implement `WaveAdapter`, not a new wave abstraction. Use two read-only
assignments first, then one disposable tool-using assignment. Compare reports, failures,
receipts, cancellation, and restart with the current RPC adapter. Retain `pi-subagents` until
the lane adapter wins that comparison on a released surface.

> **Update (Objective #2130, Node 2.1):** `WaveAdapter` is now waves-interior behind the
> `ReportWave` lifecycle's supplier (`createReportWave` constructs a fresh rpc adapter per
> launch; `reportWaveOver` is the injection seam). A lane adapter still implements
> `WaveAdapter` — inside `waves/`, swapped in at the supplier.

### E. Chord validates Perk's decomposition

The [TypeScript decomposition](ts-decomposition/memo.md) chose typed feature operations with Pi
facts confined to adapters. Chord's actual shape reinforces that decision:

- Session facets can adapt `WorkflowSession` and `StageRunner`;
- a TUI facet can adapt surfaces and local presentation contributions;
- semantic services can connect the two without exposing a raw Harness;
- `ReportWave` can receive a lane-backed adapter;
- provider facets can implement Perk provider roles; and
- generation reload can rebuild host bindings without changing feature interfaces.

The decomposition's deferred Phase 8 should be updated by evidence when implementation planning
begins, but its core laws remain right:

- Chord types stay in the future `pi/application/` adapter area;
- feature modules do not import services, facets, values, lanes, or replicated state;
- extension v1 and the application host never double-register a behavior;
- each replacement passes the same seam tests before deletion; and
- the v1 bridge remains until Pi declares a removal/support policy.

The first Chord proof should be read-only and cross-facet: expose one Session-owned Perk status
projection through a narrow service and render it through a TUI facet. Reload the generation and
detach/reattach the presentation. This tests service shape, standing-state reconstruction,
resource disposal, and surfaces adaptation without granting a new host mutation authority.

### F. Radius is useful for observation and approval

A future headless Perk worker could expose a Session through a Pi server while a maintainer
attaches through Radius to inspect progress or answer a deferred interaction. That is valuable
for long-running `implement`/`address` work and for debugging a recovered run.

Keep three boundaries:

1. Perk/GHA owns repository and job authority.
2. The Pi Session worker owns Harness execution.
3. Radius carries authenticated presentation traffic only.

The first Radius proof should attach to a disposable local headless run and exercise reconnect,
standing transcript, cancel/abort distinction, and late attachment. It should not send GitHub
credentials through presentation service payloads, select server filesystem paths remotely, or
be used as the delivery acknowledgement channel.

### G. Providers, packages, and surfaces get better targets, not less policy

Perk currently converges `.pi/settings.json` packages and chooses plan/footer/web providers.
Chord package metadata and Pi's repeatable `-e` path are a different representation:

- Chord describes which host-specific entries a package offers;
- Pi's server builds and distributes those entries;
- Perk still decides which implementation its repository permits and config selects; and
- `perk init`/`doctor --fix` still own convergence and repair.

Do not add `chord.facets` or an experimental Pi `-e` graph to Perk's public config yet. A paper
mapping of the existing Perk package/provider graph is useful for finding missing upstream
semantics, especially ordering, versioning, package installation, trust, and headless-only
selection.

For UI, retain the surfaces module. Pi's narrow `PresentationUI` and `SlashCommands` services
show the intended discipline: expose semantic capabilities, not a raw TUI. If a standing report
needs a new service, the Session facet should own its data and the TUI facet its rendering.

### H. Upgrade extension v1 independently of host adoption

Perk is three patch releases behind the latest stable Pi. A normal `perk bump-pi 0.84.4` is a
separate compatibility decision from adopting the durable host.

That upgrade should verify:

- Perk's extension factory leaves no partial registrations on failure;
- UI prompt events do not violate the surfaces-only rule;
- bundled Node resolves Perk and its virtual peer modules;
- `SessionManager` v3 compaction/state behavior remains unchanged for Perk; and
- the SDK worker's event and cleanup characterizations still pass.

Passing those checks says extension v1 works on 0.84.4. It says nothing about production
readiness of Chord, format 4, or the experimental client/server path.

## What remains intrinsically Perk-owned

Even if Pi ships everything described here, Perk still owns:

- plan, objective, gist, review, address, delivery, and learning semantics;
- stage graph, doors, terminal signals, and structured workflow outcomes;
- Git branches, worktrees, stacked trains, publish/cascade/sync/recover/land policy;
- GitHub and Linear issue/PR backends;
- run identity across Sessions, jobs, artifacts, and delivery acknowledgements;
- repository initialization, provider selection, configuration convergence, and repair;
- model, skill, tool, and permission policy per workflow stage;
- budget policy and its workflow-level result;
- selector/reviewer/aggregator roles, bounded assignments, reports, artifacts, and receipts;
- CI checks and remote delivery gates; and
- the cross-plane contract between Python exterior and TypeScript interior.

Pi can make those features more durable and easier to host. It does not define them.

## Crosswalk with existing Perk planning

### TypeScript decomposition

Source: [`ts-decomposition/memo.md`](ts-decomposition/memo.md) and
[`migration-and-verification.md`](ts-decomposition/migration-and-verification.md)

| Existing direction | V2 reading |
| --- | --- |
| Typed feature operations, not a universal application kernel | **Reinforced** by Chord's host-specific facet model |
| Keep Pi types at adapters | **Reinforced** by service/facet/value/lane churn |
| `WorkflowSession` hides storage | **Reinforced and now constrained** by explicit fork policy |
| `StageRunner` hides SDK drive | **Ready for a durable-lane parity probe** |
| `ReportWave` hides RPC | **Ready for a later lane-adapter probe** |
| Extension v1 remains the bridge | **Still required** |
| Phase 8 targets services/facets/views/slots | **Refine:** services/facets are concrete; generic views/slots have not emerged as the current API |
| Application-host cutover requires parity | **Unchanged** |

Phases 1–7 have already paid the major internal decomposition cost. Do not reopen their domain
interfaces merely to mirror Chord. Phase 8 is the admission-and-adapter phase it was intended to
be.

### Deepen headless execution

Source: [`deepen-headless-execution/memo.md`](deepen-headless-execution/memo.md)

| Existing direction | V2 reading |
| --- | --- |
| Perk Python owns objective/job/worktree durability | **Reinforced** |
| Pi SDK is the current inner driver | **Current bridge; durable `AgentLane` is now a credible successor** |
| Perk stores detailed inner turn/tool accounting | **Challenge:** prefer Pi's durable operation/usage authority when parity proves it |
| GitHub Actions first for remote execution | **Reinforced; Radius is presentation transport** |
| Typed `RunIntent`/outcome remains Perk-owned | **Reinforced** |
| Avoid PTY automation | **Reinforced by typed services and replicated state** |
| Reuse report waves | **Reinforced** |

The likely long-term ledger split is clearer: Pi records durable Session operation facts; Perk
records objective/job/workflow facts and references Pi Session/lane/operation identities.

### Pi-subagents improvements

Source: [`pi-subagents-improvements.md`](pi-subagents-improvements.md)

| Existing direction | V2 reading |
| --- | --- |
| `pi-subagents` is the current execution bridge | **Still true** |
| Perk owns report-oriented waves | **Reinforced** |
| Child Sessions are the execution unit | **Now plausibly replaceable for some roles by lanes** |
| Process-local progress is weak | **Potentially superseded by lane operation/watch state** |
| Artifacts and aggregation remain Perk contracts | **Unchanged** |
| Isolation must be explicit | **More important when lanes share a Session worker and checkout** |

Continue improving Perk wave behavior independently of the transport. Avoid new
`pi-subagents`-specific policy in the logical tier.

## Prioritized recommendations

### Now: compatibility and planning

1. **Make no production code depend on Pi `dev` or Chord.**
2. **Treat the existing Phase-8 admission rules as authoritative.** Update their frozen
   maturity facts only when a concrete implementation plan is authored.
3. **Upgrade to released Pi versions separately.** Evaluate 0.84.4 through the normal
   `bump-pi` compatibility path; do not bundle it with application-host work.
4. **Preserve v3 audit fixtures.** They are the baseline for any future cross-format proof.
5. **Track WP08, WP09, `watchSession()`, telemetry, and format-4 stabilization separately from
   “WP05 complete.”**

### First experiment after a publishable Harness surface

Implement one disposable `StageRunner` parity harness over `AgentLane`. Include provider and
tool crash/reopen points, terminal-tool settlement, external abort, every budget class, retry,
deferred work, usage, and event comparison. This experiment has the highest deletion upside and
the smallest Perk domain impact.

### Follow-on experiments, in order

1. **`WorkflowSession` value probe:** one low-risk Session-global current value; branch/tree
   fork matrix and audit comparison.
2. **`ReportWave` lane probe:** two read-only roles, then one disposable tool role; compare
   isolation, recovery, receipts, and cancellation with RPC.
3. **Chord facet probe:** one read-only Session status service plus TUI facet; reload and
   detach/reattach.
4. **Radius attach probe:** observe and control a disposable headless local run through
   reconnect; keep GHA exterior unchanged.
5. **Format projection corpus:** only after storage/export contracts stabilize or the
   application host becomes a supported candidate.

Each probe must be removable, pinned to an immutable upstream version, and implemented behind
the existing Perk seam. A failed admission proof leaves production behavior untouched.

### Deliberately defer

- replacing extension v1;
- adding Chord or experimental facet keys to Perk public configuration;
- moving all `perk:workflow-state` fields to values/lists;
- teaching the Python parser WIP format-4 physical grammar;
- replacing GHA with a Pi server or Radius;
- moving all Perk subagents into one Session;
- exposing raw Harness/Session objects through Perk services;
- using Pi SQLite as Perk's workflow database; and
- deleting current adapters before parity and support policy exist.

## Validation matrix for later decisions

| Hypothesis | Perk seam | Maturity prerequisite | Required proof | Disconfirming evidence |
| --- | --- | --- | --- | --- |
| Durable drive can thin the worker | `StageRunner` | Published Harness API; WP09 resolved or accepted; compatible tool/facet path | Crash/reopen, abort, budgets, terminal, usage, events all match | Missing Perk hook/tool lifecycle, duplicate effect, opaque totals |
| Selected values can back workflow state | `WorkflowSession` | Stable values and completed fork behavior | Field-specific branch/tree/reload/audit matrix | Lost inheritance/history or weaker verification |
| Pi projection can replace physical parsing | Session audit adapter | Stable cross-backend export/repository API | Golden v3/converted/native JSONL/SQLite corpus | Backend gaps, no offline/partial evidence |
| `retainedTail` preserves Prompt evidence | Context adapter | Stable format-4 context projection | Equivalent live-entry classification around compaction | Summary ambiguity or unavailable retained entries |
| Lanes can back report execution | `WaveAdapter` | Supported concurrent lane API and documented isolation | Two readers + one tool role; restart/cancel/receipt parity | Shared-effect leak, no per-lane policy, incomplete recovery |
| Chord can host Perk adapters | Future `pi/application/` | Published Chord/Pi facet contract | Status vertical slice, reload, detach/reattach, cleanup | Missing package trust/config/lifecycle guarantees |
| Radius can improve run observability | Remote presentation adapter | Supported auth/relay contract | Late attach, reconnect, standing state, scoped abort | Credential leakage, ambiguous authority, unreliable hydration |
| Pi server can replace GHA | Exterior runner | Remote compute/job/deployment contract beyond Radius | Full isolated checkout-to-delivery run | Server remains Session/presentation host only |

## Watch triggers

Revisit this memo when any of the following happens:

- Chord and the Pi facet host appear in a published release or release candidate.
- `PI_EXPERIMENTAL` is removed from the client/server path.
- Pi publishes a facet-package compatibility and trust policy.
- Format 4 is declared stable or becomes ordinary coding-agent storage.
- A stable normalized transcript/export surface spans JSONL and SQLite.
- WP08 and WP09 are complete.
- `watchSession()` is implemented.
- Harness telemetry covers provider/tool/drive paths and crosses RPC.
- Extension v1 receives a deprecation/removal policy.
- Lane filesystem/tool isolation becomes an explicit host contract.
- Radius gains documented multi-user authorization and deployment semantics.

At every trigger, freeze `main`, candidate, merge base, CI, package version, and supported
command gate before changing a conclusion. Do not update this memo's moving facts in place; write
the next dated assessment or an implementation-specific admission record.

## Migration principles if the host ships

1. **Adopt supported contracts, not branch vocabulary.**
2. **Replace through existing Perk seams.** Storage through `WorkflowSession`, drive through
   `StageRunner`, lanes through `WaveAdapter` (waves-interior behind `createReportWave` since
   Objective #2130, Node 2.1), UI through surfaces, host registration through Pi adapters.
3. **Keep domain types Pi-free.**
4. **Preserve branch and audit semantics field by field.**
5. **Separate stable-version compatibility from optional host adoption.**
6. **Test recovery at effect boundaries, not only process startup.**
7. **Keep exactly one live registration path per host.**
8. **Delete only after observable parity on a released surface.**
9. **Keep the Python exterior until a replacement proves job/worktree/delivery authority, not
   merely Session durability.**

## Source guide

### Upstream primary sources at the frozen `dev` SHA

- [AgentHarness implementation specification](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/harness.md)
- [Public AgentHarness and AgentLane interfaces](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/src/harness/agent-harness.ts)
- [WP05 — direct durable drive](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/work-packages/05-direct-durable-drive.md)
- [WP06 — Session, Branch, Lane separation](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/work-packages/06-session-branch-lane-separation.md)
- [WP07 — SQLite host ownership](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/work-packages/07-sqlite-host-ownership-live-forks.md)
- [WP08 — named-branch and streaming forks](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/work-packages/08-named-branch-streaming-forks.md)
- [WP09 — LaneSnapshot tool-settlement handoff](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/work-packages/09-lane-snapshot-settled-tools.md)
- [Post-WP05 roadmap audit](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/post-wp05-roadmap.md)
- [Chord overview and public behavior](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/chord/README.md)
- [Chord public exports](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/chord/src/index.ts)
- [Pi application hosts and facets](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/plugins.md)
- [Facet service RPC](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/agent/docs/rpc.md)
- [Experimental service inventory](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/coding-agent/src/experimental/services/README.md)
- [Three-process mini coding agent](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/coding-agent/src/experimental/mini/README.md)
- [Experimental plugin public subpath](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/coding-agent/src/experimental/plugin.ts)
- [Radius relay implementation](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/coding-agent/src/experimental/radius-relay.ts)
- [Ordinary format-3 SessionManager](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/coding-agent/src/core/session-manager.ts)
- [Extension-v1 public types](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/coding-agent/src/core/extensions/types.ts)
- [Extension-v1 loader](https://github.com/earendil-works/pi/blob/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695/packages/coding-agent/src/core/extensions/loader.ts)

### Perk implementation and planning sources

- [`package.json`](../../package.json) — current Pi package baseline
- [`src/perk/run/launch/`](../../src/perk/run/launch/) — Python session exterior
- [`src/perk/run/run_worker.py`](../../src/perk/run/run_worker.py) — remote worker exterior
- [`extension/pi/v1/`](../../extension/pi/v1/) — current supported Pi adapters
- [`extension/session/workflowSession.ts`](../../extension/session/workflowSession.ts) — stable
  feature-facing state/artifact seam
- [`extension/substrate/workflowState.ts`](../../extension/substrate/workflowState.ts) —
  branch patch log and v3 compaction window
- [`extension/worker/stageExecution.ts`](../../extension/worker/stageExecution.ts) and
  [`sdkAdapter.ts`](../../extension/worker/sdkAdapter.ts) — `StageRunner` and current SDK adapter
- [`extension/waves/reportWave.ts`](../../extension/waves/reportWave.ts) and
  [`rpcAdapter.ts`](../../extension/waves/rpcAdapter.ts) — logical wave and current transport
- [`src/perk/learn/session_jsonl.py`](../../src/perk/learn/session_jsonl.py) — physical v3
  learning/audit reader
- [`extension/surfaces/`](../../extension/surfaces/) — rich-UI/headless boundary
- [TypeScript decomposition](ts-decomposition/memo.md)
- [Deepen headless execution](deepen-headless-execution/memo.md)
- [Pi-subagents improvements](pi-subagents-improvements.md)

## Bottom line

Pi's `dev` branch is now building a coherent application platform, not merely accumulating
runtime experiments. Durable lane execution works. Chord supplies real composition and
replication machinery. The experimental coding agent proves server/worker/presentation
separation, package facets, reload, local attachment, and Radius attachment.

The platform is still unreleased and deliberately split from ordinary Pi. Its storage contract
is WIP, its host security and compatibility policy are incomplete, and several recovery,
snapshot, telemetry, fork, and service details remain active work.

For Perk, the timing is favorable. The TypeScript decomposition has already separated workflow
meaning from Pi plumbing. Perk should exploit that preparation by testing the new substrate
behind its existing seams—durable drive first—while keeping extension v1, format-3 auditing,
`pi-subagents`, surfaces, and the Python/GHA exterior in production.

The likely end state is still a thinner Perk interior and a stronger Pi runtime. The new
evidence makes that end state more credible. It does not make Perk's workflow domain, branch
policy, delivery exterior, or evidence contract any less its own.
