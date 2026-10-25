# Pi after 0.85.0: implications and opportunities for Perk, v3

> Point-in-time assessment for Perk maintainers, frozen on 2026-09-05. This supersedes
> [v2](upcoming-pi-changes-memo-v2.md) as the current assessment; v2 and
> [v1](upcoming-pi-changes-memo.md) remain historical snapshots. Recommendations and
> experiments below are proposed work, not implemented Perk behavior or migration commitments.

## Executive recommendation

Pi's former `dev` work has landed, and 0.85.0 is published. That changes the available
experiments substantially. It also exposes a more useful immediate question: how much of
Perk's existing Pi integration could become simpler and more capable without adopting a new
application host?

**Improve the current integration first, starting with compatibility, context projection,
and clearer lifecycle ownership.** Perk still pins Pi 0.84.1. Released fixes now improve
extension initialization, message ordering, compaction, session forks, tool working directories,
provider streams, and interactive feedback. Some of the best opportunities need no Pi bump:
`ReadonlySessionManager.buildContextEntries()` already exists in 0.84.1, while Perk manually
reconstructs the compaction window. Pi's registry already owns authenticated model dispatch,
while callers still participate in compatibility selection. Those are concrete opportunities
to remove knowledge from callers and concentrate it in deeper modules. [Release changes][u-changelog],
[existing projection API][u-baseline-session], [Perk context implementation][p-state].

**Explore the new runtime through four bounded architectural questions:** durable execution
for stages and waves; branch-aware state and evidence; Chord service/facet composition; and
reattachable presentations around long-lived execution. These could make Perk resumable,
easier to compose, and usable through more than one presentation. The existing `StageRunner`,
`WorkflowSession`, `ReportWave`, typed feature operations, and surfaces module provide useful
places to test those ideas without redesigning the workflow domain.

The release boundary needs care. Version 0.85.0 published AgentHarness and Chord, and its
coding-agent package contains experimental client/plugin exports. **The subsequent `main`
head deliberately makes the remote application host development-only**, excluding its
implementations from distributions and making those subpaths source-only. The ordinary local
SDK and stdio RPC remain supported paths. Chord itself remains a published library. Treat
each of these as a distinct adoption candidate. [Release manifest][u-package],
[post-release distribution policy][u-development], [distribution tests][u-distribution-test].

The largest change since v2 within the durable runtime is tool settlement: a completed tool's
result is now durably staged before its end event, and remains visible until its own transcript
placement. That makes reconnect and recovery more credible. It does not finish format-4
stabilization, fork transfer, Session-wide watching, or host authorization. [Settlement contract][u-wp09],
[remaining implementation gaps][u-harness].

The recommended outcome is a thinner integration with better existing workflow behavior,
followed by evidence about which new runtime facilities earn their place. Perk continues to
own plans, stages, permission policy, review completeness, worktrees, delivery, and learning.

## Snapshot and evidence method

### Frozen comparisons

| Item | Frozen evidence |
| --- | --- |
| Assessment date | 2026-09-05 |
| Perk source | [`7d05d7a1`](https://github.com/mattgiles/perk/commit/7d05d7a1acb5227fb9d788b56e5bb06b244881d3) |
| Perk development baseline | Pi AI, coding-agent, and TUI pinned to 0.84.1; peer dependencies remain wildcard, in [package.json](../../package.json) |
| Pi baseline tag | 0.84.1, [`53fa77cc`](https://github.com/earendil-works/pi/commit/53fa77ccd8a279eb87e92294ef3687b03ff80112) |
| Latest published release | [0.85.0][u-release], published 2026-09-04 at 10:18:28 UTC |
| Release commit | [`107d79f1`](https://github.com/earendil-works/pi/commit/107d79f11072bbc8a3a757ed7fd69596bee7d68c) |
| Frozen `main` | [`cce65539`](https://github.com/earendil-works/pi/commit/cce65539877fe11423463a508c6f54a28ad50abb) |
| V2's `dev` snapshot | [`6e8b9c8e`](https://github.com/earendil-works/pi/commit/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695) |
| V2 snapshot to release | 47 commits ahead, zero behind; v2's snapshot is an ancestor of the release |
| Release to frozen `main` | 11 commits ahead, zero behind |

Three comparisons answer different questions:

- [Perk's Pi baseline to the release][u-baseline-diff]: which supported-version changes must
  an upgrade assess?
- [V2's `dev` snapshot to the release][u-v2-diff]: which previous maturity judgments changed?
- [The release to frozen `main`][u-main-diff]: which subsequent fixes or policies are still
  unreleased?

The old moving `dev` ref is no longer available. Its immutable commit remains the historical
comparison point. A changelog preparation commit mentioning 0.85.1 on `main` is not evidence
of a published 0.85.1 release.

### Publication, reachability, and support are separate facts

| Surface | In published 0.85.0 | At frozen `main` | Assessment |
| --- | --- | --- | --- |
| Coding-agent executable | Declared `pi` bin uses `dist/bundle/cli.js` | Bundled executable retained | Ordinary CLI path |
| Local coding-agent SDK and stdio RPC | Public root/library and bundled RPC entry | Retained | Current integration targets |
| AgentHarness and AgentLane | Public `pi-agent-core` exports and compiled implementation | Runtime work retained | Published API; storage/lifecycle maturity still needs individual checks |
| Chord | Independent package with runtime, context, delta, bundler, and Node exports | Still a coding-agent runtime dependency | Published composition substrate |
| Coding-agent `./client` and `./experimental/plugin` | Import/type exports and compiled files are present | Only `source` exports remain; implementations excluded from distributions | Experimental integration whose distribution policy has narrowed |
| Remote server/client host | Experimental implementation in the published tree | Run from a checkout with `PI_EXPERIMENTAL=1` | Source-development experiment |
| Ordinary SessionManager storage | Format 3 | Format 3 | Existing Perk audit baseline |
| Harness storage | Format 4 | Still pre-stabilization | Published implementation without a stable format contract |

This table is grounded in npm metadata, the 0.85.0 coding-agent tarball listing, public source
exports, and the two frozen manifests. It does not infer installability merely from a monorepo
directory. [Agent exports][u-agent-exports], [Chord exports][u-chord-exports],
[release package][u-package], [main package][u-main-package].

The post-release packaging change addresses a concrete defect: direct use of 0.85.0's modular
`dist/cli.js` can encounter an undeclared remote-server dependency. The declared bundled
executable takes a different path. Perk's exterior launches the Pi executable; this research
did not establish that Perk hits that defect. It is evidence for checking isolated consumers
and the actual executable/SDK entrypoints during upgrades. [Upstream fix][u-distribution-fix],
[Perk launch code][p-launch].

### Verification strength

The release-tag [Build Binaries run][u-release-ci] succeeded. At frozen `main`, the
[`build-check-test` job][u-main-ci] reports successful install, build, check, and test steps.
These are different commits and workflows; the binary release result is not presented as a
full release-tag test run.

For feature claims, this memo distinguishes:

- **Observed implementation:** source, public declarations, or published artifact contents
  were inspected.
- **Upstream test evidence:** relevant tests exist and were read; their presence does not
  mean this assessment executed them.
- **Proposed Perk improvement:** a recommendation grounded in present code, requiring a
  separate implementation and acceptance proof.
- **Architectural hypothesis:** a possible payoff, with a bounded experiment and evidence
  that would disconfirm it.

Experimental gates and unfinished behavior are stated alongside each affected capability.
GitHub reads used `gh`; the older local Pi checkout was not treated as the release source.

## What changes from v2

| V2 conclusion | V3 disposition | Consequence for Perk |
| --- | --- | --- |
| The surveyed platform is unreleased | **Revised:** the frozen `dev` work is in 0.85.0 | Evaluate actual published libraries and artifacts |
| Chord is absent from the stable release | **Retired:** Chord is published | A small standalone composition experiment is now possible |
| WP09 is an implementation handoff | **Retired:** settlement, snapshot, reducer, and recovery changes are implemented | Include settled-but-unplaced tools in a durable-drive proof |
| Extension v1 and SessionManager v3 are the ordinary bridge | **Retained** | A normal Pi bump does not imply a format-4 migration |
| Facets become adoptable when published | **Refined:** release contents are insufficient; later `main` makes Pi's host source-only | Track the generic library separately from the coding-agent integration |
| WP08 is incomplete; values cannot replace branch history wholesale | **Retained** | Preserve field-specific inheritance, audit, and reset semantics |
| `watchSession()` is stubbed and telemetry incomplete | **Retained** | Lane watching is useful; Session-wide observability is still a separate gap |
| Durable drive is the strongest execution experiment | **Reinforced** | Publication and settlement implementation improve the experiment's basis |
| Lanes could replace wave transport | **Retained, bounded** | Prove role/context/effect isolation and report semantics separately |
| Radius complements the execution exterior | **Retained** | Explore attachment without transferring worktree or delivery authority |
| Perk's decomposition is useful preparation | **Retained and actionable now** | Deepen existing interfaces before adding more adapters |
| Upgrade to 0.84.4 independently | **Updated:** assess 0.85.0 and subsequent distribution fixes | Establish an explicit compatibility baseline rather than merely moving pins |

Sources for the changed runtime conclusions are [WP09][u-wp09], the
[Harness status inventory][u-harness], [public package exports][u-package], and
[main's development contract][u-development].

## Upstream capability survey

### 1. The ordinary Pi path has useful incremental improvements

The main coding-agent still uses `AgentSession`, extension-v1 registration, and
`SessionManager` with `CURRENT_SESSION_VERSION = 3`. The public SDK exports context-building
helpers. Version 0.85.0 additionally lets `SessionManager.inMemory()` restore `FileEntry[]`,
including a stored header, instead of requiring callers to recreate a tree through append
calls that generate new identities. This is useful for accurate fixtures and externally
managed session experiments; it does not make in-memory state durable by itself.
[Session implementation][u-session], [SDK exports][u-sdk-exports].

The upgrade span has several changes directly relevant to Perk:

| Release | Relevant change families | Perk implication |
| --- | --- | --- |
| 0.84.2 | Configurable default tools, fullscreen search, additional display controls | Characterize tool scoping against the host's configured starting set |
| 0.84.3 | Failed-extension cleanup, bundled Node loading, nested skill discovery, compaction-failure events, session-scoped model/thinking selection | Check initialization, package loading, resources, and failure reporting |
| 0.84.4 | UI-prompt lifecycle events, RPC queue clearing, safer queued extension-message placement, JSONL newline repair | Distinguish waiting from working and preserve valid histories |
| 0.85.0 | Restorable in-memory sessions, compaction-preserving forks, compaction abort, built-in tools respecting `ctx.cwd`, stream fixes, transcript controls | Improve existing execution and evidence behavior; verify the actual paths Perk uses |

This is a relevance census, not every release-note bullet. Provider-specific changes include
per-turn Anthropic thinking effort, response-stream compatibility repairs, and model/config
updates. TUI work includes faster large-transcript search, an embedded working indicator,
and jumping back to the latest message. These arrive through ordinary upgrades and do not
require a facet migration. [Tagged changelog][u-changelog].

`ui_prompt_start` and `ui_prompt_end` describe Pi UI prompts. They are not a universal signal
that every borrowed browser integration is waiting for a human. Similarly, new host spinner
behavior is not permission for Perk to bypass its surfaces module. [Extension event types][u-extension-types],
[Perk surfaces][p-surfaces].

### 2. Durable Harness drive is published, with explicit effect semantics

The public runtime separates Session storage, branch history, and lane execution. A lane
admits and drives operations, supports steering/follow-up queues, abort/resume, configuration,
results, and coherent watching. Operation state persists at effect boundaries. Reopening can
recover an operation instead of relying on the original driver's process-local promises.
[Public Harness and lane interfaces][u-lane], [runtime implementation][u-runtime].

That is useful infrastructure for Perk, but the contract retains distinctions a worker must
respect: cancelling a caller's wait is different from aborting durable work; a provider
request interrupted mid-stream may have an unknown outcome; safe replay differs from unsafe
external effects; and Perk's wall-clock, turn, and fresh-token budgets remain application
policy. The new substrate does not supply a completed plan or PR outcome merely because an
operation settles. [Harness drive and recovery contract][u-harness].

The important post-v2 improvement is **settled tool visibility**. Consider parallel calls A
and B: B finishes while A still prevents source-ordered placement. B's finalized result is
committed as `outcome_ready` before `tool_end` is published. A watcher keeps B as a settled
row until B's own `entry_added` places its result in the transcript. Reconnection therefore
does not turn a finished tool into a missing tool. Restoring an already staged outcome does
not require executing the effect again. [Implemented settlement design][u-wp09],
[reducer][u-reducer], [reducer tests][u-reducer-test], [tool recovery tests][u-tools-test].

This strengthens a concrete recovery window. It does not establish exactly-once GitHub
mutations, replay safety for arbitrary Perk tools, or compatibility with extension-v1 hooks.
Those are essential inputs to exploration E1 below.

### 3. Session storage and fork policy still constrain state adoption

Harness storage has Memory, JSONL, and SQLite implementations. Format 4 provides transactions,
immutable entries, current scalar/list values, and usage data. JSONL uses transaction records;
SQLite implements the same logical Session model. Legacy format-3 data can be normalized on
read and rewritten when a format-4 write occurs. None of this changes the ordinary
coding-agent SessionManager's format. [Session/storage contract][u-harness],
[ordinary SessionManager][u-session].

Format 4 remains explicitly pre-stabilization. Its shapes can change in place; the future
migration mechanism is activation-gated. The fork contract is also only partially implemented:

| Fork | Intended transfer | Consequence |
| --- | --- | --- |
| Named branch | Selected ancestry plus reconstructed lane configuration; no arbitrary application values/lists | Branch-owned workflow facts must be carried in history or re-derived |
| Whole tree | Immutable tree plus current application values/lists; execution/result/usage state excluded or reset according to the contract | Copying a tree is not resuming every operation or recovering historical value versions |

WP08 has explicit scope, branch selection, ancestry/configuration checks, and scalar policy.
List transfer, sequence preservation, and bounded backend transfers remain unfinished. Current
values also do not preserve all superseded values or deleted list elements as an audit trail.
[Fork semantics and implementation status][u-harness].

Perk's branch patch log, verified artifact pointers, and external evidence files consequently
have distinct reasons to exist. A normalized context projection is promising; a wholesale
move of workflow state to values would discard meaning. Format-4 compaction's `retainedTail`
also needs its own context/evidence proof before replacing format-3 readers.

The remaining implementation inventory is broader than format stability:

| Area | Status at the release | Practical limit |
| --- | --- | --- |
| Session-wide watching | `watchSession()` throws `SliceNotImplemented` | A working lane watch is not a complete Session observer |
| Telemetry | Span vocabulary exists; production starts only the tool-hook span; RPC trace propagation is absent | Perk cannot yet delegate its entire execution-observability contract |
| JSONL reclamation | Snapshot compaction is specified but unimplemented | Dead storage bytes are not reclaimed by that mechanism |
| Search and remote Session mutation | Search is unimplemented; the proposed raw remote-mutation design conflicts with process-local ownership | Neither is an available replacement for an existing Perk subsystem |
| Fork transfer and SQLite divergence | WP08 remains partial; uncompacted branch divergence can copy history | Bounded-copy and complete transfer guarantees need separate proof |
| Conformance closure | The specification lists required cases, with acknowledged gaps | A normative test matrix is not proof every row has a dedicated passing test |

These limits are explicitly recorded in the [Harness implementation status][u-harness];
the Session-wide watch stub is also present in [production source][u-runtime].

### 4. Chord supplies a real composition module

Chord is independent of the Pi workflow domain. Its implementation supplies facet setup,
dependency validation, provider-before-consumer activation, reverse disposal, singleton and
keyed services, stable service facades, replicated state, JSON delta encoding, and separately
bundled facet entries. A shape-preserving reload can replace providers while retained
consumers continue using their service handles. [Chord overview][u-chord],
[public exports][u-chord-exports], [facet lifecycle tests][u-facets-test].

The potential benefit is lifecycle ownership: providers and consumers declare relationships
once, and the host owns activation and cleanup. Package building/loading can also separate
Session code from presentation code. Chord does not choose trusted packages, install their
dependencies, decide Perk's provider policy, or turn a loaded bundle into a security sandbox.
It also does not justify a new generic Perk application kernel. An experiment should first
demonstrate a real reduction in caller obligations at one existing seam.

### 5. Pi's application host is implemented but remains experimental

The experimental host separates a server, a Session worker, and presentations. Facet setup
derives service catalogues from actual providers. Current services include:

| Host | Implemented service responsibilities | Explicit continuation work |
| --- | --- | --- |
| Server | Session directory; create/remove/attach/detach; matching presentation bundles | Workspace authorization, per-client projections, plugin policy |
| Session | Model/thinking state; controller operations; transcript replication; Session facet reload | Provider/auth composition and coordinated multi-worker reload reporting |
| Presentation | Slash-command contributions; narrow selection/status UI | Additional capabilities as concrete consumers require them |

The Session owns the Harness reducer and publishes a replicated transcript. The presentation
reuses coding-agent TUI components. Package facets have separate Session and TUI entries, and
generation reload validates and replaces their graph. Question dialogs, diff review, Git,
indexing, and canvas examples in the design specification are patterns, not an implemented
built-in service inventory. [Service implementation inventory][u-services],
[host specification][u-plugins].

The smaller `mini` agent is a separate proof. It transports a snapshot followed by semantic
Harness events, reduced with `reduceLaneSnapshot()`, rather than the larger host's Chord
replication path. It can attach multiple presentations and resume an open operation after a
replacement worker starts. Its server intentionally kills a worker when the last presentation
leaves. It has no extension/skill/hook integration and records scaling and login-cancellation
shortcuts. It proves recovery mechanics, not a production unattended Perk host. [Mini documentation][u-mini].

### 6. Radius enables attachment, while execution authority remains elsewhere

The experimental relay carries authenticated, multiplexed connections to a Pi server.
Tests cover connection/reconnection behavior and restoring attachment. That can support a
useful Perk experience: leave a long task, return later, and observe or intervene in the same
execution. [Radius relay tests][u-radius-test], [service contracts][u-services].

The relay does not create a plan checkout, select a safe branch, provide job credentials,
run CI, or acknowledge PR delivery. Authentication of a relay connection also does not finish
the host's explicitly deferred workspace/plugin authorization. Perk's exterior remains the
owner of those execution decisions. Exploration E4 is about presentation continuity.

### 7. What is only on subsequent `main`

The most significant post-release change for this memo is the remote-host distribution
restriction and its regression coverage. Other changes include selector save-key fixes,
GPT-6 Astra provider support, mouse-hover selection behavior, Alt-wheel scrolling, and
deterministic footer debounce tests. These are tracked as unreleased at the frozen head.
[Frozen release-to-main comparison][u-main-diff].

They support two different follow-ups: check a later release's packaging before selecting
an upgrade baseline, and let ordinary provider/TUI changes flow through compatibility
validation. They do not change the four architectural priorities.

## Perk's current integration: strengths and remaining friction

The TypeScript decomposition has already established useful interfaces. The important
current ownership is:

| Module | What it owns today | What remains tied to Pi or a supplier |
| --- | --- | --- |
| Python launch and remote worker | Run identity, stage/worktree positioning, package/skill materialization, process launch, outcome delivery | Executable discovery and host/package compatibility |
| Pi-v1 adapters and typed feature operations | Registration and input translation around authoring, review, delivery, and learning behavior | Hook ordering and lifecycle composition |
| `WorkflowSession` | Named state reads, classified changes, verified artifacts | Branch patch-log representation and session lifecycle projections |
| Context injection | Shared inject/strip registration and Perk-specific evidence rules | Manual compaction-window reconstruction and marker scans |
| Tool gating | Stage scope and structural read-only enforcement | Initial tool snapshots and competing extension activation |
| Model dispatch | Structured requests and deterministic fallback | Host-capability selection and live runtime access |
| `StageRunner` | Stage outcomes, budgets, terminal signals, run events | SDK construction, extension binding, event translation, disposal |
| `ReportWave` | Assignments, validation, completeness, collection, receipts | RPC envelopes, generated workflow scripts, completion/artifact transport |
| Surfaces and provider adapters | TUI/RPC/JSON routing, footer/status/report ownership, borrowed review integration | Provider completion conventions and host lifecycle |
| Python session reader | Learning/audit interpretation of captured session evidence | Physical format-3 JSONL grammar |

Implementation sources: [launch][p-launch], [remote worker][p-remote], [Pi-v1 adapters][p-v1],
[session interface][p-session], [context injection][p-context], [tool gating][p-gating],
[structured requests][p-structured], [stage execution][p-stage], [report waves][p-waves],
[surfaces][p-surfaces], [audit reader][p-audit].

Several completed improvements should be preserved and credited:

- Injection's hook pair is already consolidated; another extraction would repeat landed work.
- The worker already makes one SDK `prompt()` call whose await spans settlement. Pi owns
  turn iteration; Perk observes events and enforces its budgets.
- SDK construction already isolates user-global resources with a temporary agent directory
  while retaining project resources. Cleanup includes construction failure and disposal.
- `ReportWave` already hides transport behind an internal adapter and gives callers opaque
  references, typed reports, and explicit completeness behavior.
- Rich UI already goes through surfaces. Footer cleanup and context ownership have existing
  tests; unresolved flicker reports do not establish a need to replace the renderer.

These points are supported by the [context installer][p-context], [worker adapter][p-sdk],
[wave interface][p-waves], and [surfaces implementation][p-surfaces]. The opportunity is to
make those interfaces more complete and easier to use, with fewer host facts escaping them.

## Prioritized improvements within existing scope

The ordering below puts compatibility first, then improvements with direct caller and
workflow benefits. **Depth** means behavior callers can obtain through a small interface:
fewer ordering rules, representation details, and failure conventions for each caller to
learn. Moving code into another file is not itself evidence of increased depth.

### R1. Establish a real compatibility baseline across the integration

**Observed friction.** Perk's exact development pins, wildcard peers, borrowed npm packages,
CLI executable, and direct SDK worker form several distinct compatibility surfaces. A green
test suite against 0.84.1 cannot establish behavior with arbitrary newer borrowed packages.
The current settings select unpinned pi-subagents and Plannotator packages, among others.
The worker loads project resources through the SDK, which differs from simply launching
the bundled executable. [Package baseline][p-package], [Pi settings][p-settings], [SDK setup][p-sdk].

**Recommendation.** Make a normal Pi upgrade a small integration audit. Record the exact
Pi/package tuple exercised; test the real executable and an isolated SDK consumer; verify
extension initialization, required role tools, provider events, model selection, and
TUI/headless behavior. Evaluate 0.85.0 against subsequent packaging fixes before selecting
the production target. Treat a minimum supported host version and borrowed-package pinning
as explicit compatibility decisions in that implementation plan.

**Payoff and simplification.** Maintainers can distinguish a Perk defect from package drift,
and know which compatibility branches can eventually be removed. Operators get released
fork, compaction, stream, and working-directory fixes without coupling the upgrade to a new
host. This recommendation does not yet prove any existing adapter redundant.

**Acceptance.** A failed extension factory leaves no registrations/listeners behind; a cold
worktree loads its own extension/resources; built-in tools use the intended `cwd`; a real
review role sees its required capabilities; provider results still reach Perk's save/review
operations. Include normal CLI, SDK worker, and borrowed-child paths. A source-only export
must never be mistaken for an available installed-package interface. The upstream package
distribution tests provide a useful consumer-oriented pattern. [Distribution tests][u-distribution-test].

### R2. Delegate compaction projection to Pi and keep evidence policy in Perk

**Observed friction.** `activeContextWindow()` reconstructs a format-3 compaction window
from `firstKeptEntryId`; `branchCarries()` searches serialized entries. The shared context
installer combines those operations with Perk's marker/flavor rules. Pi already exposes
`buildContextEntries()` in the installed 0.84.1 session interface, so this opportunity is
available before upgrading. [Current traversal][p-state], [injection caller][p-context],
[baseline Pi API][u-baseline-session].

**Recommendation.** Put one Pi-v1 context projection behind the existing injection/evidence
seam. Let Pi select the active leaf and compaction-retained entries. Keep Perk responsible
for distinguishing live injected content from summaries, choosing the current flavor,
handling a cold prompt not yet persisted, and removing stale owned context. Exclude
compaction summaries from marker evidence: the public projection includes the summary entry.
Use typed entry/content inspection where it removes a demonstrated marker false positive.

**Payoff and simplification.** Perk stops maintaining a second compaction traversal. Fixes
to projection reach binding and scratch delivery consistently, while navigation and repeated
compaction are less likely to suppress needed instructions. Preserve full-branch
once-per-session questions as a different policy; they should not silently acquire
compaction-window semantics.

**Acceptance.** Compare retained versus summarized injections, repeated compaction, tree
navigation, quoted markers in summaries/tool output, flavor changes sharing a custom type,
and ordinary binding prompts that must survive stripping. Verify exact scratch-block
matching and pre-persistence cold prompts. Use the existing context and workflow-state
characterizations as the baseline. [Context tests][p-context-test], [state tests][p-state-test].

### R3. Deepen session reads and resolve lifecycle facts once

**Observed friction.** `WorkflowSession` already owns a `link-plan-ref` change, but the
commit/compact adapter still decodes the session's plan ref independently. That read has
session-only authority, unlike the generic checkout-first resolver. Separately, `index.ts`
derives tool-scope stage, implementation-capture stage, and feedback-receiver inputs from
the same identity decision. Some of these values intentionally differ for forks and adopted
children. [Session interface][p-session], [session-only read][p-commit-compact],
[lifecycle composition][p-index].

**Recommendation.** Add proven named reads to the existing session interface, and resolve
the relevant lifecycle facts inside the session module before composition consumes them.
Make the different authority and inheritance rules explicit in those results. Keep operation
ordering, lazy reads, strict-linkage verification, and best-effort state writes intact.
Do not replace every read with a universal state object or flatten distinct stage meanings.

**Payoff and simplification.** Callers obtain the plan ref or admitted lifecycle fact they
need without understanding branch entry shapes or replaying the identity decision tree.
This reduces both duplicate decode logic and the chance of a child impersonating its
parent's stage or consuming an unrelated checkout selector.

**Acceptance.** Reload preserves identity; forks inherit permitted state while isolating
run artifacts; adopted children inherit permitted mode without a parent claim; failed claims
do not consume handoffs; corrupt review ledgers refuse destructive append; and read-back
or artifact-digest failures retain their existing classifications. A future Pi values
backing must pass these same interface tests. [Session tests][p-session-test],
[identity lifecycle][p-lifecycle].

### R4. Make effective-tool ownership explicit across extension lifecycles

**Observed friction.** Gating snapshots active tools on first engagement and reapplies
filters on lifecycle changes. Its source documents late pi-subagents registration and the
limitations of several extensions owning `setActiveTools`. A tool available after initial
binding can disappear on later synchronization. The behavior is characterized in the stage
tool tests. [Gating implementation][p-gating], [stage tool tests][p-stage-tools-test].

**Recommendation.** Keep one Perk policy for effective tools, with explicit inputs for
available tools, stage, read-only mode, and host capability. Define how deliberate foreign
activation changes interact with that policy and when a newly registered tool is admitted.
Retain structural enforcement at `tool_call`; presentation availability alone is not the
read-only guarantee. Preserve bare-session behavior and existing warm-stage exceptions.

**Payoff and simplification.** A role's required tools become an intentional contract rather
than a consequence of registration timing. Reviewers retain streaming/structured-output
capabilities where required; headless sessions avoid human-only question tools. Repeated
snapshot repair and registration-order knowledge can move out of individual integrations.

**Prerequisite and acceptance.** The inspected 0.85.0 extension API does not supply a new
composable activation-policy or registration-settled contract. This is a bounded Perk design
problem and possible upstream contribution, not a shipped replacement to invoke. Test late
registration, reload, tree navigation, foreign toggles, a real headless turn, and adopted
children. Preserve distinctions between gate enforcement and stage visibility.
[Extension interface][u-extension-types].

### R5. Put model compatibility behind one host-owned request path

**Observed friction.** Plan-title generation chooses between registry dispatch and manually
resolved credentials. `completeStructured()` supports both routes. The registry path already
preserves the credential-resolved endpoint, nullable headers, and provider environment.
Meanwhile `/btw` probes the model registry facade's private runtime field to preserve live
credentials and extension-provided models in a child session. [Title caller][p-title],
[structured-output module][p-structured], [live runtime probe][p-btw].

**Recommendation.** Make host capability selection an adapter-owned concern so feature
callers request a typed result with cancellation and their fallback policy. Prefer the
existing registry dispatch where supported. Retain older-host fallback only according to an
explicit supported-version decision. Keep the `/btw` live-runtime gap documented and tested;
the inspected new extension context still does not expose a public `ModelRuntime` accessor.

**Payoff and simplification.** Feature code no longer needs to know which credential path
the host supports. Runtime-only providers, API-key overrides, and custom endpoints behave
consistently, and compatibility work has one local home. This extends an existing good
direction; it is not a new generic model orchestration framework.

**Acceptance.** Exercise runtime-registered providers, session-only key overrides, endpoint
and header deletion behavior, provider environment, cancellation, missing models, and
deterministic title fallback. Keep the facade probe characterization until a public
replacement is verified. Wildcard peer declarations alone cannot justify removing
compatibility behavior. [Model-dispatch tests][p-structured-test], [extension types][u-extension-types].

### R6. Complete worker failure and observation semantics before replacing its driver

**Observed friction.** The SDK adapter already owns binding, subscriptions, session rebinding,
abort, and cleanup. `runStage()` owns budget and terminal policy. One remaining failure
edge is concrete: production `resolveAuth()` can await `ModelRuntime.create()` before the
worker's main `try`, so a rejected construction can escape normalized outcome handling.
This is a source-visible failure path, not a reproduced production incident.
[Worker boundary][p-stage], [auth/runtime construction][p-sdk].

**Recommendation.** Bring initialization failures under the same outcome and final-event
guarantees as failures during drive. Make the existing event stream reliable enough to
explain whether work failed before model selection, during a tool, at a budget boundary,
or after a definitive stage result. Keep Perk's terminal interpretation separate from SDK
idle/settlement events.

**Payoff and simplification.** Local and remote execution get a usable failure result
instead of an exceptional exit with incomplete evidence. The same characterization suite
then becomes the measuring instrument for a Harness adapter. Durable execution should earn
its place by removing lifecycle machinery while preserving these results.

**Acceptance.** Include model-runtime rejection, no available model, extension binding
failure, cancellation before and during drive, definitive submit/address outcomes, merge
conflicts, fresh-token budgets, cleanup, and exactly one final run event. The current
single-prompt design should remain the baseline; adding another generic turn loop is not
part of this recommendation. [Worker tests][p-stage-test], [SDK adapter tests][p-sdk-test].

### R7. Improve wave evidence and child-policy clarity through the existing interface

**Observed friction.** Report transport handles request/reply timeouts, completion arriving
before a spawn reply, cancellation during launch, durable aggregate reads, and generated
supplier scripts. Receipts are deliberately output-free telemetry; the aggregate is report
authority. These distinctions are useful but easy to lose when a supplier changes how it
creates or settles child sessions. [Transport][p-transport], [RPC adapter][p-rpc],
[wave semantics][p-waves].

**Recommendation.** Make required child capabilities and execution mode explicit at the
supplier seam. Verify streaming feedback separately from final report success. Improve
partial-evidence retention and recovery of collection where the durable supplier result
permits it, with an explicit distinction between recollecting an existing run and launching
the assignment again. Keep strict review and best-effort learning completeness policies
separate, and maintain single-use collection semantics for each reference.

**Payoff and simplification.** Users get useful progress and recoverable evidence when a
review partly fails; they need fewer manual reruns of expensive completed work. Family
callers continue to use assignments and reports rather than supplier identities or status
files. A future lane supplier can be compared against these same behaviors.

**Acceptance.** Exercise completion-before-reply, cancellation during spawn, timeout and
orphan handling, corrupt aggregate, missing receipt, partial required assignments,
overlapping collectors, and two simultaneously bound sessions. A receipt or visible progress
message must never become sufficient evidence that a required report succeeded.
[Adapter contract tests][p-wave-contract-test], [report tests][p-wave-test].

### R8. Make waiting and progress clearer through the existing surfaces module

**Observed friction.** Perk has several human interactions with different completion
conventions: Pi UI prompts, provider-backed review, and external feedback delivery. The
surfaces module already owns rendering and mode routing. The new prompt lifecycle events
offer a better signal for some waits, but do not cover all borrowed browser flows.
[Surfaces][p-surfaces], [Plannotator adapter][p-plan-adapter], [UI event types][u-extension-types].

**Recommendation.** Represent working, waiting for a decision, and settled feedback as
semantic state at each interaction's owning adapter, and project it through surfaces.
Use Pi prompt events where they describe the actual interaction; use provider completion
state where they do not. Preserve existing differences in plan patch application,
objective/gist reconciliation, and review posting. Align progress and cleanup conventions
without accidentally unifying those policies.

**Payoff and simplification.** A long pause becomes understandable to the operator, and
headless consumers get meaningful status without needing terminal rendering. Existing
provider-specific waits have a clearer lifecycle, giving a later replicated presentation
something coherent to display.

**Acceptance.** Verify TUI, RPC, and JSON behavior; cancellation and dismissed review;
missing provider; late completion after session change; reload cleanup; and one footer/status
owner. Preserve the charter's surfaces-only rules and `/btw` exception. No budget is paused
or extended merely because a new UI event exists; that would be a separate policy change.
[Surfaces guard][p-surfaces-guard], [TUI charter][p-charter].

## Four architectural explorations

These are the four highest-value questions to investigate, in priority order. Each starts
with an existing Perk interface and asks for a concrete improvement in behavior or ownership.
They are bounded research proposals, not four production migrations.

### E1. Can durable operations become the execution substrate for stages and waves?

**Possible future workflow.** An implementation stage loses its worker. A replacement
reopens the same operation, explains what completed, reconciles uncertain effects, and
continues without asking a supervisor to infer progress from an interrupted process. Later,
a review wave can recover its completed reports and remaining assignments through the same
kind of durable execution facts.

**Why now.** AgentHarness is published, lane drive is implemented, and WP09 supplies a
stronger settlement/reconnect contract than v2 observed. The mini agent demonstrates worker
replacement and operation resumption. Its lack of extension integration means it is evidence
for runtime mechanics, not yet for running Perk's tools. [Lane interface][u-lane],
[tool recovery tests][u-tools-test], [mini topology][u-mini].

**Smallest experiment.** Start with one disposable `StageRunner` adapter that drives an
actual existing stage/tool path using controlled provider and effect fixtures. Kill and
reopen at provider admission, tool intent, settled outcome, and transcript placement.
Compare its outcomes, budgets, and events with the current SDK adapter. Include an unsafe
effect whose external result must be reconciled rather than blindly replayed. Only after
that works, try two read-only report assignments through the private wave adapter, followed
by one disposable tool-using assignment.

**Architectural payoff.** Pi could own durable operation facts and recovery, while Perk
keeps workflow outcomes and references Session/lane/operation identities. Driver-local
reconstruction, some subscription/settlement machinery, and supplier-specific wave transport
could shrink. The two Perk interfaces remain distinct: sharing an execution substrate does
not merge stage policy with report completeness.

**Admission and disconfirmation.** Require a viable Perk tool/hook/resource integration,
compatible usage accounting, explicit abort semantics, and stable-enough storage for the
experiment. Success includes no lost settled result, no unsafe duplicate effect, the same
terminal outcome, and preserved role/tool/context/worktree isolation. Missing extension
semantics, opaque recovered totals, or shared-effect leakage disconfirm replacement at the
affected seam. If the new adapter duplicates most existing lifecycle machinery, retain the
current driver and record the narrower capability that did work.

### E2. Can session state and evidence acquire clearer, durable ownership?

**Possible future workflow.** A maintainer opens a recovered run and sees three clearly
separated things: workflow history on the selected branch, current presentation/application
state, and execution facts from Pi. Learning and audit consume a normalized evidence view
instead of guessing how a particular storage file represents those facts.

**Why now.** The Session model has concrete values/lists, repositories, lane state, and
fork rules. The ordinary SDK's new in-memory restore also makes it easier to replay an
accurate v3 evidence corpus with original identities. The obstacle is now semantic as well
as technical: current values cannot stand in for branch history, and format-4 transfer and
stability remain incomplete. [Session implementation][u-session], [Harness state/fork contract][u-harness].

**Smallest experiment.** Put one disposable, current-only status value beside the existing
branch-owned active-plan linkage. Compare original, reopened, compacted, navigated,
branch-forked, and tree-forked Sessions. Verify which facts survive and which must be
re-derived. Separately project a small evidence corpus through the public v3 context API
and candidate format-4 interfaces; include retained injected context, quoted summaries,
tool outcomes, custom workflow entries, and usage. Inspect JSONL/SQLite behavior only through
supported candidate interfaces before considering a new Python reader.

**Architectural payoff.** `WorkflowSession` can hide several appropriate storage forms
behind a stable domain interface. Pi may become the authority for operation usage and
normalized transcript projection, while Perk owns branch inheritance, artifact integrity,
and the evidence needed to justify workflow decisions. Current-state data need not be
manufactured as transcript history, and historical facts need not be squeezed into values.

**Admission and disconfirmation.** Classify each proposed field by inheritance, reset,
history, context visibility, and audit needs. Success preserves those properties across
fork/compaction/recovery and supports useful offline evidence. Lost linkage, unavailable
historical values, incomplete backend projection, or unstable transfer semantics block the
corresponding move. No blanket state migration follows from a successful status-value probe.

### E3. Can Chord turn existing feature modules into simpler semantic services?

**Possible future workflow.** One workflow-status service feeds a terminal surface and a
headless observer. Reloading its implementation refreshes the consumers without each one
recreating subscriptions, carrying a raw Pi context, or reconstructing status from messages.

**Why now.** Chord is independently published and has implemented lifecycle, service,
replication, and reload behavior. It can be investigated without committing to Pi's
source-only remote host. The latter is a separate packaging and integration question.
[Chord interface][u-chord], [lifecycle tests][u-facets-test], [host distribution policy][u-development].

**Smallest experiment.** Expose one read-only existing workflow-status capability through
a narrow service. Feed it to the current surfaces module and a headless consumer. Exercise
initial hydration, provider replacement, a rejected reload, disposal, and a consumer
disconnect. Measure which listener, refresh, and cleanup obligations disappear from callers.
If the library experiment earns its place, map the same capability onto separate Session
and TUI facets in a pinned source-host experiment.

**Architectural payoff.** Perk features could become reusable application modules with a
thin Pi registration adapter. Lifecycle ownership would be explicit, and terminal versus
headless presentation would vary without duplicating workflow meaning. Package selection
and provider policy still belong to Perk; service assembly should not become a second
configuration authority.

**Admission and disconfirmation.** Keep feature-facing types Pi-free and presentation-safe.
Require one registration per behavior, consistent initial and replacement snapshots, and
complete cleanup of subscriptions and scratch resources. Reject a design that introduces
more service/token knowledge than it removes, needs raw Harness or TUI objects in feature
interfaces, or cannot preserve existing failure ordering. A stable facade alone does not
prove a successful generation reload.

### E4. Can a presentation detach without becoming the execution owner?

**Possible future workflow.** A developer starts a long Perk run, closes the terminal, and
later attaches from another terminal or a future web/mobile client. They see current stage,
settled tools, progress, and any pending interaction, then choose to observe or intervene.
The checkout and delivery authority stay with the original execution host.

**Why now.** The experimental server, worker-owned transcript, semantic services, and Radius
transport give this topology a concrete implementation to study. Coherent lane snapshots
and settled-tool visibility make late attachment more meaningful than replaying terminal
output. A web/mobile Perk client is a possible evolution, not a shipped Pi capability
established by this survey. [Services][u-services], [relay tests][u-radius-test].

**Smallest experiment.** Run a disposable local headless task under a pinned source host,
then attach locally and through Radius. Disconnect while a tool runs, attach after it
settles, reconnect after transport loss, and compare two observers. Exercise a pending
interaction and distinguish closing a presentation, cancelling a request, and aborting the
operation. Record the host's actual worker-lifetime policy: mini's kill-and-restore behavior
must not be described as uninterrupted background execution.

**Architectural payoff.** Execution, observation, and interaction can have independent
lifetimes. Perk's current remote runner could gain an attach/debug/decision surface while
continuing to own the job. E3 supplies a possible semantic presentation interface; E1 supplies
durable execution facts. E4 asks whether their combination works for an operator.

**Admission and disconfirmation.** Success requires coherent late state, explicit control
authority, no accidental abort on detach, and reliable reconciliation after reconnect.
Workspace/plugin authorization and multi-client policy must be sufficient for the proposed
deployment. Ambiguous control ownership, missing standing state, or a requirement to route
delivery acknowledgements through the presentation blocks production adoption. A successful
local proof would still leave remote deployment as separate work.

## Relationship to existing Perk planning

| Existing direction | V3 reading |
| --- | --- |
| [TypeScript decomposition](ts-decomposition/memo.md) | Reinforced: typed feature operations and existing interfaces are the experiment entrypoints. R2–R5 deepen current modules without reopening completed extractions. |
| [Application-host admission and migration](ts-decomposition/migration-and-verification.md) | The individual parity gates remain useful. Update maturity facts in a future admission record: Chord is published, WP09 implemented, and Pi's remote host source-only on subsequent `main`. Generic views/slots are not an established replacement API. |
| [Deepen headless execution](deepen-headless-execution/memo.md) | Retain the Python conductor/job/worktree exterior. E1 investigates a stronger interior driver; Pi operation durability does not supply objective-length delivery policy. |
| [Pi-subagents improvements](pi-subagents-improvements.md) | Improve current wave behavior independently of supplier choice. Distinguish a supplier's native child `AgentSession` from an AgentHarness lane; they have different isolation and lifecycle contracts. |
| [Earlier future-proofing proposal](future-proofing-decomposition.md) | Judge progress by complexity hidden or deleted at proven interfaces. The existence of another upstream abstraction is insufficient reason to add another Perk abstraction. |

The local September 5 pi-subagents and Plannotator assessments were also read as research
leads. They were untracked at this assessment's Perk snapshot, so this memo does not depend
on them as published evidence. Their useful overlap is captured here through current Perk
source: compatibility baselines, explicit child capabilities, durable report authority,
and consistent provider lifecycle projection. Their detailed supplier surveys remain
separate work.

Perk retains ownership of stage/door semantics, run identity, model/tool/skill policy,
review assignments and completeness, plan/objective/gist state, branch/worktree delivery,
issue backends, CI gates, and learning evidence. A future cross-plane behavior change must
amend [shared/contracts.md](../../shared/contracts.md). User-facing changes update the matching
user docs; config/provider/backend changes also update the perk-expert mirror. The memo
itself changes none of those contracts.

## Recommended sequence and decision criteria

| Priority | Work | Evidence required before advancing |
| --- | --- | --- |
| Establish the baseline | R1 compatibility audit | Exact package tuple and actual CLI/SDK/borrowed-extension paths characterized |
| Deepen current usage | R2 context and R3 session reads; address R6 initialization failure alongside relevant worker work | Fewer caller obligations; existing authority/evidence behavior preserved |
| Improve coordination and feedback | R4 tool ownership, R5 model dispatch, R7 waves, R8 waiting/progress | Required capabilities and meaningful state survive lifecycle changes |
| Lead architectural research | E1 durable stage, then bounded wave proof | Recovery, effect safety, budgets, terminal outcomes, and isolation agree |
| Clarify data placement | E2 state/evidence proof | Field-specific fork/history semantics and useful audit projection preserved |
| Test composition and presentation | E3 standalone service experiment, then E4 source-host attachment | Measurable lifecycle simplification and coherent detached/reattached behavior |

The sequence expresses priority and prerequisites, not a requirement to finish every current
improvement before a disposable experiment. R2 is immediately investigable on 0.84.1;
E3's standalone library proof does not require remote deployment; E4's source-only status
limits the production conclusion it can establish.

The deletion test applies throughout: if a candidate adapter merely relocates all the
existing lifecycle, recovery, and representation rules into a new wrapper, its architectural
payoff is weak. If Pi takes responsibility for those rules and Perk callers become simpler
while preserving outcomes, the new module has earned consideration.

### Watch triggers that remain open

- A subsequent release ships the new distribution policy: reassess the supported upgrade
  baseline and installed-consumer behavior.
- Pi defines a supported remote host/facet package contract, including compatibility and
  authorization, or removes its source-only/experimental gate.
- Format 4 stabilizes and WP08 completes the required transfer semantics.
- A stable normalized evidence/export interface spans the relevant storage backends.
- `watchSession()` and the missing telemetry paths become implemented.
- Pi exposes public live-model-runtime access or a composable tool activation lifecycle.
- Concurrent lane isolation becomes an explicit host contract sufficient for Perk's roles.
- Extension v1 receives an actual deprecation/support policy.

Chord publication and WP09 implementation are resolved triggers from v2. Future assessments
should freeze a new snapshot rather than editing this memo's moving facts in place.

## Verification record and limits

Completed for this assessment:

- Queried release metadata, immutable tag/commit relationships, and exact-head upstream CI
  results through `gh`.
- Inspected the frozen release and main source, declarations, manifests, implementation
  status, and relevant test bodies.
- Queried npm metadata for Pi coding-agent, pi-agent-core, and Chord 0.85.0. Inspected the
  coding-agent tarball listing to verify the bundled CLI/RPC, modular SDK, client, and
  experimental plugin/server files actually shipped.
- Compared those artifacts with subsequent main's source-only export policy and its
  package-distribution regression tests.
- Inspected current Perk implementation and existing characterization tests, including the
  installed 0.84.1 context projection API.

No Perk or upstream runtime test suite, live model session, remote deployment, or recovery
experiment was executed to author this memo. Existing tests are cited as inspected evidence,
and upstream CI is identified separately. Every R/E acceptance scenario above is proposed
validation for later work. In particular, no installed 0.85.0 Perk compatibility claim,
storage migration, or prototype success is asserted.

## Source guide

Upstream implementation links below use the frozen release unless labeled **main** or
**baseline**. Local code links are navigational counterparts to the frozen Perk commit;
the snapshot table identifies the implementation assessed.

- Release and distribution: [release][u-release], [tagged changelog][u-changelog],
  [release package][u-package], [main package][u-main-package],
  [main development policy][u-development], [main distribution tests][u-distribution-test].
- Ordinary integration: [SessionManager][u-session], [baseline SessionManager][u-baseline-session],
  [SDK exports][u-sdk-exports], [extension types][u-extension-types].
- Durable runtime: [public exports][u-agent-exports], [Harness/lane interface][u-lane],
  [runtime][u-runtime], [full contract/status][u-harness], [WP09][u-wp09],
  [reducer][u-reducer], [reducer tests][u-reducer-test], [tool tests][u-tools-test].
- Composition and hosts: [Chord][u-chord], [Chord exports][u-chord-exports],
  [facet tests][u-facets-test], [host specification][u-plugins],
  [services][u-services], [mini][u-mini], [Radius tests][u-radius-test].

[u-release]: https://github.com/earendil-works/pi/releases/tag/v0.85.0
[u-changelog]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/coding-agent/CHANGELOG.md
[u-baseline-diff]: https://github.com/earendil-works/pi/compare/53fa77ccd8a279eb87e92294ef3687b03ff80112...107d79f11072bbc8a3a757ed7fd69596bee7d68c
[u-v2-diff]: https://github.com/earendil-works/pi/compare/6e8b9c8ea6ba378346b8afd5884e2fb34d6d3695...107d79f11072bbc8a3a757ed7fd69596bee7d68c
[u-main-diff]: https://github.com/earendil-works/pi/compare/107d79f11072bbc8a3a757ed7fd69596bee7d68c...cce65539877fe11423463a508c6f54a28ad50abb
[u-package]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/coding-agent/package.json
[u-main-package]: https://github.com/earendil-works/pi/blob/cce65539877fe11423463a508c6f54a28ad50abb/packages/coding-agent/package.json
[u-development]: https://github.com/earendil-works/pi/blob/cce65539877fe11423463a508c6f54a28ad50abb/packages/coding-agent/docs/development.md
[u-distribution-test]: https://github.com/earendil-works/pi/blob/cce65539877fe11423463a508c6f54a28ad50abb/packages/coding-agent/test/package-distribution.test.ts
[u-distribution-fix]: https://github.com/earendil-works/pi/commit/1382777ed8000e8a84f81053d66f6bb713dccd92
[u-release-ci]: https://github.com/earendil-works/pi/actions/runs/33860912601
[u-main-ci]: https://github.com/earendil-works/pi/actions/runs/33963985069/job/101300683665
[u-agent-exports]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/agent/src/index.ts
[u-sdk-exports]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/coding-agent/src/index.ts
[u-session]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/coding-agent/src/core/session-manager.ts
[u-baseline-session]: https://github.com/earendil-works/pi/blob/53fa77ccd8a279eb87e92294ef3687b03ff80112/packages/coding-agent/src/core/session-manager.ts
[u-extension-types]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/coding-agent/src/core/extensions/types.ts
[u-harness]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/agent/docs/harness.md
[u-lane]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/agent/src/harness/agent-harness.ts
[u-runtime]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/agent/src/harness/runtime/harness.ts
[u-wp09]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/agent/docs/work-packages/09-lane-snapshot-settled-tools.md
[u-reducer]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/agent/src/harness/runtime/reducer.ts
[u-reducer-test]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/agent/test/harness/runtime/reducer.test.ts
[u-tools-test]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/agent/test/harness/runtime/drive-tools.test.ts
[u-chord]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/chord/README.md
[u-chord-exports]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/chord/src/index.ts
[u-facets-test]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/chord/test/facets.test.ts
[u-plugins]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/agent/docs/plugins.md
[u-services]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/coding-agent/src/experimental/services/README.md
[u-mini]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/coding-agent/src/experimental/mini/README.md
[u-radius-test]: https://github.com/earendil-works/pi/blob/107d79f11072bbc8a3a757ed7fd69596bee7d68c/packages/coding-agent/test/experimental-radius-relay.test.ts
[p-package]: ../../package.json
[p-settings]: ../../.pi/settings.json
[p-launch]: ../../src/perk/run/launch/
[p-remote]: ../../src/perk/run/run_worker.py
[p-v1]: ../../extension/pi/v1/
[p-state]: ../../extension/substrate/workflowState.ts
[p-context]: ../../extension/pi/v1/contextInjection.ts
[p-context-test]: ../../extension/pi/v1/contextInjection.test.ts
[p-state-test]: ../../extension/substrate/workflowState.test.ts
[p-session]: ../../extension/session/workflowSession.ts
[p-session-test]: ../../extension/session/workflowSession.test.ts
[p-lifecycle]: ../../extension/session/lifecycle.ts
[p-commit-compact]: ../../extension/pi/v1/delivery/commitCompact.ts
[p-index]: ../../extension/index.ts
[p-gating]: ../../extension/substrate/toolGating.ts
[p-stage-tools-test]: ../../extension/substrate/stageTools.test.ts
[p-structured]: ../../extension/substrate/structuredOutput.ts
[p-structured-test]: ../../extension/substrate/structuredOutput.test.ts
[p-title]: ../../extension/pi/v1/planTitle.ts
[p-btw]: ../../extension/vendor/btw/btw.ts
[p-stage]: ../../extension/worker/stageExecution.ts
[p-stage-test]: ../../extension/worker/stageExecution.test.ts
[p-sdk]: ../../extension/worker/sdkAdapter.ts
[p-sdk-test]: ../../extension/worker/sdkAdapter.test.ts
[p-waves]: ../../extension/waves/reportWave.ts
[p-wave-test]: ../../extension/waves/reportWave.test.ts
[p-wave-contract-test]: ../../extension/waves/adapterContract.test.ts
[p-transport]: ../../extension/waves/transport.ts
[p-rpc]: ../../extension/waves/rpcAdapter.ts
[p-surfaces]: ../../extension/surfaces/surfaces.ts
[p-surfaces-guard]: ../../extension/surfacesGuard.test.ts
[p-plan-adapter]: ../../extension/pi/v1/providers/plannotator.ts
[p-charter]: ../design/tui-charter.md
[p-audit]: ../../src/perk/learn/session_jsonl.py
