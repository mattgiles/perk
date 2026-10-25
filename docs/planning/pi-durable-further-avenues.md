# Pi Durable: reassessment and further avenues

2026-10-24. A planning assessment for Perk maintainers. Source inspection and offline experiments
continued into 2026-10-25 UTC. This document supplements the five documents in
[`pi-durable/`](pi-durable/); it leaves them unchanged. Recommendations below are new planning
inputs, not an adopted runtime architecture or a compatibility certification.

## 1. Executive reassessment

**The case for retaining execution, evidence, and human decisions has strengthened. Several
mechanisms and reuse assumptions need revision before implementation.** Pi Durable has
acquired useful execution mechanisms since the original proposal, while the experimental
coding-agent host that proposal expected to inspect has disappeared. Perk has also completed
substantial preparation of its own. The next investment can be a bounded application of
durability with a measurable recovery benefit.

The most consequential findings are:

1. **Remove the experimental coding-agent host from the reuse assumptions.** Pi 1.2 removed
   it with the source-only application stack. Chord now offers a different host runtime;
   neither is a supported way to load Perk's existing extension into Durable. A new host
   composition still needs an owner. [Host removal][coding-changelog], [current Chord][chord-readme].
2. **Rewrite the storage-failure protocol before implementing it.** `StorageRejected` no longer
   exists in Durable 1.2+. Storage failures end the Session/Harness; the read-only
   `StorageRequestError` exemption must not become a safe-to-retry write category. The newer
   source also changes when storage adopts an in-memory commit. The original intent to
   reconcile uncertain acceptance survives; its specific exception model does not.
   [Released changes][durable-changelog], [current error rules][head-errors].
3. **Separate visible progress from stored evidence.** At the newer source snapshot,
   deferred commits can reach watches before storage. Accepted decisions and report receipts
   need immediate commits, with the facts they derive read inside the transaction. The
   original observation model needs this qualification. [Deferred commit contract][deferred-spec].
4. **Give native Durable workers a stronger, narrower comparison.** Released Durable now
   supplies recoverable codemode scripts, nested tool tasks, structured tool output, deferred
   tools, and caller selection. These remove potential custom machinery. They do not supply
   Perk's report acceptance, resource loading, restrictions, or execution-wide budgets.
   [Released tool changes][durable-changelog], [tool recovery implementation][tool-source].
5. **Exploit waits and diagnostics before building a shared workspace.** Durable sleep,
   wake signals, crash-loop parking, typed reports, and telemetry can make a small execution
   intelligible and recoverable. They also make an always-resident coordinator process less
   fundamental to the product vision. Hosting a wakeable execution remains application work.
   [Sleeping and reports][durable-changelog], [wake example][stable-readme].
6. **Preserve the original separation of authorities.** Git/GitHub effects are still outside
   local transactions. Store ownership still does not fence surviving commands. Our actual
   `SIGKILL` experiments reproduced that distinction on both snapshots: a fixture report record survived,
   a task recovered, and its Node execution subprocess remained alive until explicitly killed.
   See [the experiment record](#6-offline-experiments-and-reproduction).
7. **Rebaseline the incumbent rather than comparing with October 5 Perk.** Current Perk adopts
   Pi 1.4.0 and pi-subagents 0.81.0. Its report transport deliberately defeats supplier workflow
   reuse on a fresh launch. Recovery of an existing assignment and a new review are different
   product operations; removing that freshness rule would change review meaning.
   [Adoption record][adoption], [current transport][perk-transport].

The recommended next planning unit is **one recoverable, revision-bound report collection and
one persisted human decision over its evidence**, with a CLI account of progress. Keep the
first operation read-only with respect to the reviewed repository. Compare current-worker
collection and native Durable execution at that seam. Let the result determine the next
integration investment. The broader plan/objective/learning vision remains useful as the
product horizon.

## 2. Baselines, method, and coverage

### Evidence identities

| Evidence | Snapshot and interpretation |
| --- | --- |
| Original Perk observations | `91719e4933389fece395cd570d0b8a0f7506b7b8`, as recorded by the five original documents. Historical descriptions, not today's behavior. |
| Original Pi source | `b7dfc049e917a265a5aefa9f3952a2dec9b81cfd`; Durable manifest 1.0.3. A historical source archive was inspected. |
| Original technical manual | The originals identify `5b6c792b424e73edefbfa558b901bcd64788dad2`. Its page references remain historical evidence; this assessment does not recertify the manual or reproduce its captured experiment. |
| Current Perk | `7df5fef35d810d0de72347da5f4755eed51af0bd`, version 4.1.0. Four development SDK pins are 1.4.0; the managed supplier is 0.81.0. |
| Released Pi used in experiments | v1.4.0, `4a080252f06caf63a525d7873c5d94d3c23887e0`. Its package changelogs identify the 1.1–1.4 release boundaries. |
| Newer Pi source used in experiments | `38ff99177fba21e9c57a670f4e95adcf407c99c7`, the library checkout inspected here. Manifests still say 1.4.0, but its `Unreleased` changes are **not** features of the 1.4.0 release. |
| Pi web documentation | The library mirror of `https://pi.dev/docs/latest`, with live [release notes][release-notes] consulted. Moving documentation is navigational evidence; pinned source decides version-specific claims. |

Durable still labels its API experimental, with changes possible between releases. A common
1.x version or an aligned dependency version is not an integration compatibility guarantee.

The source library is under `docs/library/source-code/github.com/earendil-works/pi`; the coding-agent
documentation mirror is under `docs/library/documentation/pi`. They were consulted without
refreshing or editing them. The library's historical Git checkout did not contain all older
blobs, so complete original and release archives were obtained with `gh api`, rather than
treating a partial local checkout as a complete release.

Evidence labels in the analysis mean:

- **Documented:** a pinned README, specification, changelog, or published release note states it.
- **Source-inspected:** the implementation or test body was read. A test citation alone does
  not mean it ran.
- **Reproduced:** the stated assertion passed in the offline experiments in section 6.
- **Inference / proposal:** a consequence or possible Perk design, with its remaining proof named.

### Release and subsystem coverage

Public coding-agent release notes are only part of the evidence. The separately published
Durable and Chord packages changed substantially without those changes appearing as the main
coding-agent features. The following coverage uses their matching package changelogs too.

| Boundary | Relevant evolution | Planning consequence |
| --- | --- | --- |
| 1.0.4 bridge from the old snapshot | Environment watcher fixes, PowerShell, and the initial remote execution package. | Do not carry forward the manual's environment/API snapshot as the implementation target. [Durable][durable-changelog], [environments][env-changelog]. |
| 1.1 | Task/response/tool timing, historical context reads, ordered scans, context retention, and Durable Object SQLite. Coding-agent settlement gains `aborted`. | Better inspection and historical comparison; runtime settlement remains separate from domain acceptance. [Durable][durable-changelog], [agent-core][agent-changelog]. |
| 1.2 | Native Durable codemode, nested calls, structured output, deferred tools, restart abandonment, input-entry placement, fatal storage failures, bounded caches, wait-cycle detection. Chord's facet/service runtime is replaced; the experimental coding-agent application stack is removed. | Revisit the worker and host implementation, cancellation model, persistence boundary, and tool security together. [Durable][durable-changelog], [Chord][chord-changelog], [coding-agent][coding-changelog]. |
| 1.3 | Namespaced SQLite tables and coordinated Cloudflare adapter access; context-baseline repair. Internal Pi dependencies become exact. Sandbox shutdown can settle before worker exit. | A shared database becomes an option; namespace isolation is not a transaction or fencing guarantee. Track physical worker exit separately from script results. [Durable][durable-changelog], [sandbox][codemode-changelog], [adoption][adoption]. |
| 1.4 | Durable sleeping, host clocks/timers/wakes, restart limits, typed reports and blocked tasks, telemetry, IndexedDB, live model/settings providers, explicit document checkpoint predicates, SQLite schema migration. | Reconsider host residence, diagnostics, data operations, compatibility, and proof ordering. [Durable][durable-changelog], [telemetry][telemetry-changelog]. |
| After 1.4, through the pinned source | Read-only Harness, storage adoption callback, unified watch lifecycle and coalescing, deferred progress persistence, streaming-memory improvements, and a handoff continuation fix. | Useful experiment targets; keep their API and durability consequences out of claims about released 1.4.0. [Unreleased changes][head-changelog], [deferred semantics][deferred-spec]. |

The AI, agent-core, codemode, MCP, telemetry, environment, and coding-agent changelogs were
inspected for these boundaries. AI changes improve cache behavior, request identity, timing,
and tracing. MCP 1.2 changes structured content to arbitrary JSON and repairs cancellation after
auth refresh; it does not make a Durable MCP host binding automatic. Current Perk's existing
SDK/MCP work is evidence to preserve, not work to repeat. [AI changes][ai-changelog],
[MCP changes][mcp-changelog], [current pair assessment][pair-assessment].

Model-catalog additions, terminal/platform fixes, and configuration schemas matter to the
current host and future resource loaders. None independently settles the Durable architecture.
No claim here depends on a particular model's price or quality, a live provider run, a Windows
measurement, or a browser/Cloudflare deployment. TUI fixes to concurrent dialogs improve v1
presentation; they do not persist a human decision across host death.

### What Perk has already prepared

The [October 24 pair assessment][pair-assessment] and [adoption record][adoption] supersede the
original runtime-version mismatch as a description of the development pins. Today's code also
has stronger nested-call gating, worker MCP composition, browser-operation ownership, evidence
normalization, cancellation receipts, and report collection behavior than the October 5
snapshot. Their existence reduces the scope of readiness work; it does not certify their
translation to another runtime.

Two current seams remain important. [`ReportWave`][perk-wave] retains pending collection state
in an instance-owned `WeakMap`. [`transport.ts`][perk-transport] adds a fresh launch UUID expressly
to prevent a new launch from inheriting old supplier results. A durable collector would need
an explicit operation to recover the **same** assignment, with the same subject and authority.
It must preserve the ability to request a fresh inspection.

Draft review still has an activation-owned slot and uncertain-save latch in
[`draftReview.ts`][perk-review]. New browser lifecycle handling does not make that decision
durable. Conversely, an old observation of missing lifecycle cleanup must not be used as
evidence against today's [browser-operation owner][browser-owner]. Adoption, offline
characterization, and live certification remain separate claims.

## 3. Existing-plan audit

The ledger groups related claims and their proof obligations. **Keep** means the reasoning
survives, not that integration is complete. **Revise** means the mechanism or implementation
assumption changed. **Reopen** means a design choice now deserves comparison. **Strengthen**
means upstream or the experiments improve its support while leaving application obligations.

### Strategy and product direction

| ID / original location | Disposition | Current evidence and planning consequence |
| --- | --- | --- |
| S1 — [three architectural axes](pi-durable/pi-in-the-sky.md#separate-orchestration-from-state-authority) | **Keep.** | Advancement owner, canonical records, and worker runtime are still independent. New storage backends and Chord do not justify moving approved-plan authority. Compare changes one axis at a time. |
| S2 — [durable objectives](pi-durable/pi-in-the-sky.md#1-objectives-become-durable-programs) | **Strengthen.** | Sleeping, wake signals, parking, and reports supply more useful execution machinery. Objective dependencies, approval, eligibility, budget admission, and effect reconciliation remain Perk policy. [Released mechanisms][durable-changelog]. |
| S3 — [worker comparison and supplier reuse](pi-durable/pi-in-the-sky.md#compare-worker-runtimes) | **Revise.** | Its 0.75.0 installed supplier is historical. Current Perk explicitly opts fresh launches out of reuse; supplier improvements do not recover an activation-owned `ReportWaveRef`. Compare reacquisition of one assignment, not arbitrary artifact reuse. [Current transport][perk-transport], [collector][perk-wave]. |
| S4 — [shared engineering workspace](pi-durable/pi-in-the-sky.md#2-perk-becomes-a-shared-engineering-workspace) | **Reopen implementation.** | Chord now provides typed remote objects, principal-specific variants, links, and observable state. Authentication, operation identity, current authorization, and reconnect reconciliation remain application work. Links do not resume in-flight calls. [Chord contract and limits][chord-spec]. |
| S5 — [competing implementations](pi-durable/pi-in-the-sky.md#3-competing-approaches-become-executable-experiments) | **Keep; deepen evidence.** | Forks still do not clone a worktree or confer authority. Historical context reads can preview the context a fork would inherit without creating one. Record code, environment, resources, model selection, costs, and comparison criteria independently. [Durable changes][durable-changelog]. |
| S6 — [first-v2 plan/objective/learn experience](pi-durable/vision.md#the-first-v2-three-ordinary-workflows) | **Deepen the early usability criterion.** | The originals already distinguish independent early proofs, an experimental plan workflow, and the broader three-workflow target. Preserve that separation. Add an explicit operator-usable report/decision milestone so recovery benefit can be assessed before the plan workflow is complete. This refines delivery grouping rather than correcting a missing staged approach. |

### Workflow, storage, and recovery

| ID / original location | Disposition | Current evidence and planning consequence |
| --- | --- | --- |
| W1 — [doors and coordinator](pi-durable/pi-durable-workflows.md#doors-remain-coordination-moves), [fact ownership](pi-durable/pi-durable-workflows.md#each-fact-keeps-one-owner) | **Keep.** | One advancement owner is still required. Python can evaluate eligibility and perform mature operations without also advancing the same execution. A successful custom task is not proof of a save, PR, merge, or completed objective node. |
| W2 — [retained evidence and record lifetimes](pi-durable/pi-durable-workflows.md#execution-identity-and-retained-evidence) | **Keep.** | Task memos/documents and nested-call journals are execution mechanisms with bounded lifetimes. Accepted reports, pending decisions, cancellations, and effect receipts need retained application records. Preserve artifact provenance/digests and append corrections to accepted evidence. Value-version migrations do not change a document's persistent scope/history/fork commitments. The custom probes reproduced the value of session-scoped state. |
| W3 — [one SQLite store per execution](pi-durable/pi-durable-workflows.md#store-and-record-policy) | **Reopen topology; retain experiment default.** | Namespaced tables and Cloudflare coordination permit sharing a database with host tables. They do not remove Session failure boundaries, coordinate worktrees, or make transactions span separate stores. Start with one execution/store; measure before consolidating. [Storage contract][stable-storage]. |
| W4 — [checkpoint policy](pi-durable/pi-durable-workflows.md#store-and-record-policy) | **Strengthen.** | The originals already require an explicit policy. Durable 1.4 now requires `checkpointWhen` at definition time. `() => false` is an explicit experimental choice, not a long-term reconstruction-cost policy. [Released changes][durable-changelog]. |
| W5 — [admission and request identity](pi-durable/pi-durable-workflows.md#admission-and-conversation-identity) | **Keep.** | Conversation creation and submission remain separate operations. Request deduplication does not validate an equivalent subject or authorization. Retain the mapping and stable operation identity before trying to recover work. [Submission implementation][submissions-source]. |
| W6 — [transcript writes](pi-durable/pi-durable-workflows.md#transcript-writes-and-compaction) | **Revise placement details.** | Model-relevant input still needs boundary-aware submission. Since 1.2 a display-only write can append immediately; custom input entries carry application data into normal input placement. Do not queue every human-visible annotation as model input, or treat a display entry as accepted domain work. [Input tests][input-tests]. |
| W7 — [compatibility and operation-boundary restrictions](pi-durable/pi-durable-workflows.md#resuming-safely) | **Keep; broaden tool-path coverage.** | Recovered safe tools still enter the execute phase without replaying the initial argument validation or `beforeTool` sequence. Nested calls add more paths to enforce. Resume must also retain the governing resources, actual subject, authorization, and budgets. [Tool implementation][tool-source], [recovery tests][tool-recovery-tests]. |
| W8 — [ownership before opening](pi-durable/pi-durable-workflows.md#resuming-safely) | **Revise for the newer viewer path.** | Ordinary opens still recover work and storage open can initialize/migrate schema. The newer `readOnly` Harness skips task recovery and refuses writes/scheduling. This qualifies the claim that every Harness open mutates, but it is not a storage-forensics guarantee or synchronized observer. [Viewer tests][readonly-tests], custom viewer probe. |
| W9 — [surviving children](pi-durable/pi-durable-workflows.md#resuming-safely) | **Strengthen with reproduction.** | Real owner `SIGKILL`, on both snapshots, left a `NodeExecutionEnv.exec()` process writing its heartbeat. Replacement scheduling must stop, join, or isolate old effects before authorizing conflicting work. A database lock alone cannot establish that. |
| W10 — [budgets and accepted results](pi-durable/pi-durable-workflows.md#budget-admission-and-usage), [continuation](pi-durable/pi-durable-workflows.md#accepting-work-and-continuing) | **Keep; deepen accounting.** | Native nested tools, classifier/image requests, retries, and dynamic models/settings expand the accounting surface. Do not turn timing or usage telemetry into an admission budget. Validate typed reports, completeness, subject identity, and tool-controlled termination independently of model recap. [Native execution][durable-changelog], [current worker][perk-worker]. |
| W11 — [persisted decisions](pi-durable/pi-durable-workflows.md#persisted-decisions) | **Strengthen with reproduction.** | On both snapshots, a reply after the requester finished created one conversation-owned continuation; duplicate replies reused it; changed/cancelled fixtures refused it; receipt recovery worked after storage success plus lost acknowledgment. This tests a small fixture protocol, not Perk actors, destinations, or save authorization. |
| W12 — [commit outcomes](pi-durable/pi-durable-workflows.md#commit-outcomes-and-recovery) | **Revise before implementation.** | The `StorageRejected` distinction is obsolete. Storage errors fail the Harness; invalid/cancelled reads have narrower handling. At HEAD, adoption occurs inside storage's commit callback; an error after adoption retains the adopted changes while failing the Session. Retain receipts and reopen/reconcile before retry. [Released errors][stable-errors], [HEAD transactions][transaction-spec]. |
| W13 — [cancellation and closing](pi-durable/pi-durable-workflows.md#attaching-stopping-and-moving-machines) | **Keep; add new states.** | Restart abandonment, sleeping tasks, parked tasks, and failed-run inbox policy now affect continuation. `close` remains different from cancellation, and shutdown acknowledgment remains different from physical subprocess exit. Include background work explicitly in cancellation scope. [Ownership tests][ownership-tests], [sandbox changes][codemode-changelog]. |
| W14 — [views and learning](pi-durable/pi-durable-workflows.md#execution-views-and-learning-evidence) | **Revise APIs and persistence assumptions.** | HEAD removes `taskGraph()` and document/view state getters in favor of watches. Watches coalesce and may include unstored progress; telemetry is diagnostic. Build retained evidence from persisted domain facts and committed entries, not UI frames, model context, or event counts. [HEAD changes][head-changelog], [deferred contract][deferred-spec]. |

### Development path and shared decisions

| ID / original location | Disposition | Current evidence and planning consequence |
| --- | --- | --- |
| V1 — [private workspace under `extension/pi/v2`](pi-durable/pi-durable-v2.md#recommendation) | **Reopen physical location.** | Explicit entry/dependency isolation is sound. A sibling private workspace outside `extension/` is worth comparing because the current bare-import census walks that entire tree. It could avoid exclusions in the shipped-runtime scan; shared-interface imports, cross-workspace guards, and tests still need deliberate design. [Bare-import guard][bare-guard], [direction guard][direction-guard]. |
| V2 — [dependency isolation](pi-durable/pi-durable-v2.md#package-and-verification-isolation) | **Revise baseline; keep proof.** | Perk's development Pi versions now align numerically with Durable 1.4.0, whose dependencies include Chord, codemode, telemetry, and optional image machinery. That is not package-instance, extension-loader, or resource compatibility. Verify exact resolution and published entry points in a standalone host. [Manifest][durable-package], [current package][perk-package]. |
| V3 — [experimental host reuse](pi-durable/pi-durable-v2.md#what-to-reuse-adapt-and-keep-separate) | **Obsolete.** | The referenced `coding-agent/src/experimental/durable` host is removed. Preserve it as historical prior art only; estimate the replacement host explicitly. The new Chord runtime is not that host's compatible successor. [Removal][coding-changelog], [Chord rewrite][chord-changelog]. |
| V4 — [environment and worker reuse](pi-durable/pi-durable-v2.md#what-to-reuse-adapt-and-keep-separate) | **Strengthen options.** | Use current Node/remote execution and conformance suites as the starting point. Images, argv execution, bounded listing, and remote terminals reduce reasons to build equivalent machinery. A cwd remains no sandbox. [Environment package][env-readme], [coding tools][tools-index]. |
| V5 — [coexistence, migration, exit](pi-durable/pi-durable-v2.md#coexisting-executions), [adoption](pi-durable/pi-durable-v2.md#adoption-and-exit) | **Keep; add data downgrade boundary.** | Keep disjoint experimental work and one writer. SQLite schema v2 in 1.4 cannot be reopened by 1.3 or earlier; a package rollback is not a data rollback. Back up before migration and reconcile external effects before handing work back to v1. [Released migration][durable-changelog]. |
| V6 — [validation sequence](pi-durable/pi-durable-v2.md#validation-sequence) | **Keep guarantees; reorder delivery.** | Its failure cases remain valuable. Host composition, report recovery, a durable decision, and a useful CLI status can form a smaller first slice. Objective orchestration, publication, and `/learn` then earn separate proofs against that result. |
| V7 — [shared feature and state interfaces](pi-durable/pi-durable-v2.md#what-to-reuse-adapt-and-keep-separate) | **Keep; prove at one consumer.** | `WorkflowSession` exposes synchronous state/artifact operations; an asynchronous Durable commit cannot simply replace their backing. Reuse provenance, digest, save-gate, and report-validation rules while proving acknowledgment/visibility at the boundary. Do not convert every v1 operation to async or maintain a duplicate policy implementation in anticipation of reuse. [Current interface][workflow-session]. |
| D1 — [decision-foundation baseline](pi-durable/decision-foundation.md#evidence-baseline) | **Stale environment description.** | Installed 0.87.0 versus declared 0.99.2 no longer describes the development checkout. The questionnaire/RPC evidence still does not establish compatibility on the adopted pair; rerun the specific boundary if that caller is chosen. Do not carry forward either the mismatch or a compatibility claim. [Current pins][perk-package]. |
| D2 — [operation-specific preparation and authority](pi-durable/decision-foundation.md#what-the-foundation-should-own), [bounded pilot](pi-durable/decision-foundation.md#a-bounded-v1-pilot) | **Keep as an independent option.** | Better v1 lifecycle handling does not authorize delegated approval or save. Keep exact-subject review/save guards and separate missing information, authority, presentation, and execution capability. Build this pilot when it has a working consumer; it need not block the Durable decision proof. [Current review slot][perk-review]. |
| D3 — [questionnaire investigation](pi-durable/decision-foundation.md#separate-questionnaire-compatibility-investigation) | **Keep boundaries; avoid premature generalization.** | A supported dialog callback remains distinct from stable request correlation, truthful actor attribution, and cancellation. New classifier models or recommended answers supply no approval authority. No questionnaire compatibility experiment was run here. |
| D4 — [later delegated approval](pi-durable/decision-foundation.md#sequence-acceptance-and-deferred-work) | **Keep as a separate policy decision.** | The proposal requires full coverage from four standard critics plus Ponytail, dispositioned findings, and an identified final subject. New runtime completion or classifier capabilities do not satisfy those conditions or establish delegation. The preparation pilot and the fixture reply protocol grant no autonomous approval/save authority. |
| P1 — [shared participation](pi-durable/vision.md#a-workspace-people-can-share), [accumulating learning](pi-durable/vision.md#learning-that-accumulates-across-work) | **Keep as a horizon; deepen retention.** | Current Chord and telemetry improve presentation ingredients. Shared approval still needs authenticated actors and fresh subjects; cross-execution learning still needs retention, retrieval, permission, and curation. Persisted transcripts do not become project rules automatically. |

The original proofs for isolation, incomplete review coverage, stale evidence, cancellation,
uncertain local/external acceptance, objective reconciliation, learning fidelity, and explicit
adoption/exit all remain necessary. They should be assigned to the feature that first needs
them, rather than accumulated as prerequisites for every initial experiment.

## 4. Further avenues

### 4.1 Make retained evidence the first useful application

**Proposal:** recover one report assignment and its accepted outcome across interruption while
retaining the original subject, execution identity, resources, and restrictions. A new review
continues to mint fresh identity. This draws the missing product distinction exposed by S3.

Compare three implementations at the same acceptance boundary:

| Option | Concrete opportunity | Cost and reason to reject it |
| --- | --- | --- |
| Recover current-worker collection | Retain validated reports and stable assignment/attempt identities while using current worker resources and restrictions. | Supplier availability is not a supported reacquisition protocol by itself. Reject if recovery requires guessing from paths/status previews or conflicts with fresh-inspection semantics. |
| Durable coordinator with current workers | Durable retains admission, waits, accepted reports, and decisions; a narrow adapter reconciles external workers. | Unknown launch, attach, cancellation, surviving children, and accounting remain cross-runtime obligations. Reject if that bridge costs more than the retained work saves. |
| Native Durable report worker | Use fresh conversations, built-in nested tasks, structured results, and recoverable scripts. | Perk tools, required instructions, restrictions, model configuration, and budgets need a real binding. Reject if it duplicates substantial Perk policy or weakens the report floor. |

The smallest proof uses two fixture report assignments, accepts one, interrupts the owner, and
recovers the remainder. Then repeat against the actual restricted report seam with a faux
model. Compare completed work retained, repeated tool/model work, recovery interventions, and
new lifecycle obligations. The process-death probe here establishes useful primitives, not
this Perk comparison. Current-worker collection remains the control even if native execution
looks more elegant.

Record each option's execution profile: effective model/resources, tool concurrency, provider
and harness retries, compaction, deadlines, and usage units. Coding-agent 1.4 queues codemode
work when its pool is busy; a standalone Durable sandbox host still needs its own capacity
policy. Sandbox results can settle before physical worker exit, so count capacity through
the exit/release hooks when that limit matters. [Coding-agent changes][coding-changelog],
[sandbox contract][codemode-changelog]. A common prompt does not make those profiles equivalent.

### 4.2 Treat human decisions as application operations with no resident waiter

The fixture experiments strengthen the original decision direction. A pending decision can
outlive its requesting task. A reply can validate the current subject and create a
conversation-owned continuation in one commit. No waiting model, browser, questionnaire, or
permanently live root task is necessary for that local mechanism.

The next proof should bind a real Perk decision: exact reviewed bytes, save destination,
supersession, allowed action, actor, cancellation, and gate-release semantics. Keep backend
publication outside the commit and preserve the existing uncertain-save refusal. A continued
workflow must reconcile its receipt after acknowledgment loss before issuing another effect.

This suggests a useful early product: a CLI lists pending decisions and their evidence,
accepts an explicitly authorized reply, and reports its receipt. Channels can follow that
operation. The simpler option is an active-session decision when restart continuity is not
needed. Adopt persistence where abandoning and reopening the decision is a real user cost.
Reject a universal question/approval framework before this first operation works.

### 4.3 Revisit hosting as three separate responsibilities

The removed host increases composition work, but the surrounding substrate is richer:

| Responsibility | Existing ingredient | Perk still owns |
| --- | --- | --- |
| Run and retain work | Durable tasks, documents, sleeping, clocks, wake signals, reports. | Execution admission, compatibility, evidence acceptance, policy, budgets, effect recovery. |
| Place files and commands | Node execution; `pi-env` remote daemon/SSH; optional bounded listing and terminals. | Trust, credentials, workspace identity, isolation, restrictions, orphan reconciliation. |
| Present and invoke operations | Chord contracts, principals, variants, IPC/WebSocket links, observable state; the existing Perk surfaces seam for v1. | Authentication, grant mapping, stale-operation checks, retry semantics, useful views, and UI integration. |

**Proposal:** compose a minimal Node host first, preserve this separation in its interfaces,
and evaluate Chord only when an actual remote operation or second client needs it. Rebuilding
the removed application stack or making every Perk feature a Chord object would introduce a
large migration before proving continuity.

Chord is worth a focused transport proof: an owner and viewer see the same subject; only the
authorized operation is exposed; a dropped reply is reconciled by operation identity; reconnect
converges on current state. Its principal-specific contracts are useful ingredients. Its
specification explicitly leaves authentication/grants to the app, does not persist the reload
commit decision, and does not resume links. In-flight calls can have unknown effects.
[Specification and limitations][chord-spec]. The 22 reproduced principal/reload tests do not
demonstrate a Perk client or durable reload protocol.

A wakeable Durable Object is a credible later host for retained coordination. Durable sleep
releases the invocation, `wake()` describes when a process is needed, and `onWake` lets a host
use alarms. The upstream example arms an alarm **before** admitting work because the wake
callback occurs after commit. Copying only its final idle calculation could strand work after
a crash. [Host wake example][stable-readme], [sleep tests][sleep-tests].

Keep provider credentials and the execution store local while trying remote files/commands
through `pi-env`. This independently tests remote placement without migrating canonical state
or deploying a service. IndexedDB offers another separate avenue: a local, bounded inspector
or personal experiment. Browser retention, a single owning tab/worker, and a Web Lock remain
required; it is not a shared-workspace database or backup strategy. No remote, browser, or
Cloudflare deployment was executed for this assessment.

### 4.4 Make observation explicit about what has actually been retained

HEAD creates an important distinction:

| Observable information | Suitable use | Insufficient evidence for |
| --- | --- | --- |
| Immediate application commit and retained receipt | Accept a report/decision and authorize one continuation after validation. | Success of an external GitHub/Linear/process effect without reconciliation. |
| Committed entries and `subscribeCommits()` publications | Retained history, export, and a prospective stored-log consumer. | Every live progress update, or a ready-made replication service. |
| Watches, conversation views, `pi.live`, task graph | Responsive progress and current diagnostic explanations. | A durable acceptance record, complete event history, or a count of logical events. |
| Telemetry and timing | Diagnose retries, tool latency, recovery paths, and costs under stated conditions. | Authorization, budget reservations, complete transcript/evidence, or automatic privacy. |
| Read-only Harness snapshot | Inspect stored work without scheduling its recovery. | Automatic refresh from another writer, zero-write storage initialization, or distributed ownership. |

**Reproduced:** a HEAD reader cached a session document at value 0; the writer stored 1; the
reader still returned 0; reopening the reader returned 1. Its read-only flag controls mutation
and scheduling, not coherence with another Session. Start with owner-served views or explicit
snapshot refresh, and prove freshness before using either for human decisions.

**Source-inspected:** deferred commits are eligible only for changes to existing conversation
documents with `history: "latest"` and `fork: "initial"`. Entries, task changes, session
documents, creation, and migration make such a commit immediate. Ordinary immediate commits
that read a held document through `tx` store its held changes with derived writes. A watch or
outside-transaction snapshot may be ahead of storage. The default progress deadline is 1,000 ms,
with line/I/O delay in the loss bound; it is not an exact one-second crash guarantee.
[Deferred specification][deferred-spec]. The reproduced upstream tests exercise these rules.

Consequently, the new execution view should show its retained subject and accepted outcomes
separately from live diagnostics. First prove an understandable CLI snapshot. A future browser
can display the same distinctions without becoming a second workflow authority.

The old README's general statement that nothing is shown before storage remains in the HEAD
README, while its new deferred-commit specification permits exactly that for eligible progress.
That is an upstream documentation inconsistency. This assessment follows the detailed contract,
implementation, and passing tests, and records the exception explicitly rather than treating
the opening paragraph as an unconditional guarantee. [HEAD README][head-readme],
[implementation][session-source], [tests][deferred-tests].

### 4.5 Bind capabilities at execution, including replay

Native codemode now journals results before delivering them to the script, reattaches nested
work, controls clock/randomness for replay, and refuses divergent calls or changed sandbox
fingerprints. Those are substantial building blocks for bounded research and report tasks.
They do not make arbitrary external effects exactly-once, nor make the sandbox's tool bridge
a read-only boundary. [Codemode tests][codemode-tests].

`modelTools` governs what the model is offered; other enabled tools can remain callable from
scripts. Deferred visibility also does not remove a tool's authority. `callers` distinguishes
model calls and tool calls, not a particular caller's approved subject. Use the actual enabled
tool set and operation-boundary policy to constrain an assignment. [Caller tests][caller-tests].
The reproduced tests cover this separation and safe/unsafe recovery.

The tool implementation resolves a recovered safe tool and invokes its execute phase without
the initial `beforeTool` validation path. Perk's read-only gate cannot simply be translated
into that hook and declared complete. Required policy must also hold in the actual tool or
environment operation on each attempt. Retain exact subject availability and resource checks
through compaction, registry replacement, and restoration. Dynamic settings/models providers
make revalidation more important: a configured model name is not a complete record of the
effective provider, resource set, and admitted budget.

**Proposal:** the native-worker experiment should begin with one explicit capability set,
required guidance rendered successfully, bounded model/tool work, and refused writes. Add a
revoked permission and changed-code resume case before expanding to implementation. Defer a
general host abstraction until this comparison identifies repeated caller obligations.
Classifier/image APIs may help a specific analysis operation later; retain the current worker's
refusals until an accountable, bounded caller earns their use.

### 4.6 Use diagnostics to explain waiting, not only running

Released 1.4's `sleeping`, `restart_limit`, typed `ReportInfo`, blocked task graph, and failed-run
inbox policy let Perk explain more states without synthesizing them from model prose.
`wake().active === false` can mean scheduled sleep, parked work, or no eligible work; it is not
workflow completion. A host must report why progress stopped and how it can resume.

**Proposal:** retain the domain reason for a wait and combine it with runtime diagnostics.
A human decision, an unmet objective prerequisite, a missing task definition, an incompatible
policy version, and a parked crash loop need different next actions. Explicit retry must not
discard accepted sibling evidence or silently replenish an execution's budget.

Telemetry adds another useful view of the same execution: submission, phase, model-request,
checkpoint, and replay relationships can expose repeated work after restart. It can help answer
whether Durable actually removed recovery labor. Trace spans are not the archive. Bounded error
diagnostics can still contain caller content; use the adapter's retention/access policy and
do not claim that all diagnostics are content-free. [Durable telemetry][telemetry-source],
[AI tracing][ai-changelog], [stored telemetry][chord-readme].

The current source's bounded document cache and faster scheduler reduce obvious long-running
host costs. Upstream benchmarks are upstream measurements; this assessment did not reproduce
their performance numbers or establish Perk-scale capacity. Measure the working report slice
before choosing process/store consolidation on performance grounds.

### 4.7 Preserve a useful historical record for learning and experiments

Historical context reads make a new, inexpensive question practical: *what would this worker
have seen at a particular entry?* Pair that derived view with committed history, the resource
and tool selection at admission, and accepted outcomes. This can help compare context assembly
or prepare a fork without creating a competing implementation first. It does not reproduce
model responses or filesystem state.

Compaction fixes and per-model thresholds improve continuity. Omitting thinking from a
summarization request is different from deciding what historical evidence to retain. Current
Perk already normalizes system state and tool changes into `/learn` evidence; a Durable reader
must preserve those meanings and declared omissions rather than regress to final answers.
[Current evidence contract][perk-contracts], [context/compaction changes][durable-changelog].

**Proposal:** retain one evidence bundle that can explain accepted and rejected approaches,
failed attempts, corrections, the exact tested revision, and the reason a decision advanced
work. The same bundle can support review recovery, a human handoff, and later learning. Start
with the current evidence schema and a Durable source binding. Add cross-execution search or
automated comparisons only after provenance, permission, retention, and stale-result handling
are demonstrated.

Durable codemode replay is not a general experimental reproducibility facility. It reuses
recorded tool results to continue one script. A fair comparison between approaches still needs
separate workspaces, comparable inputs and resource limits, and independent outcome checks.
Selecting a candidate remains an explicit decision that does not publish or merge it.

### 4.8 Treat compatibility and rollback as data operations

The first host needs an application-owned execution manifest sufficient to decide whether the
available task/tool code, resource policy, runtime, and actual workspace can resume the admitted
work. This deepens the original compatibility requirement without choosing a field schema now.
Task migrations and Chord contract checks cover their own representations; they do not know
whether a reviewed branch or authorization remains valid.

Keep an exact released dependency graph for the first working slice and a separate HEAD
characterization. A new package version is insufficient evidence identity: the HEAD package
still reports 1.4.0 while changing storage, watches, and progress. Exercise the real public
exports in the host and record resolved package versions/locations. A sibling private workspace
outside the shipped extension is a candidate worth measuring against the original nested
layout; neither location proves feature independence.

SQLite 1.4's migration prevents opening the resulting store with older releases. A first
data-operations proof should back up a stopped execution, restore a copy, verify its receipts,
and refuse incompatible resume before admitting work. It must also identify how worktree
contents and external effects are reconciled. Browser storage persistence, remote environment
placement, and an exported plan do not replace this proof.

A log-replication feature appeared and was reverted before the 1.4 release. It is useful
evidence that the area is being explored, not a capability to put in the roadmap as delivered.
`subscribeCommits()` now has semantics suitable for a consumer of stored commits, but transport,
bootstrap, ownership handover, and reconciliation would still be a separate design.
[Feature commit][replication-feature], [revert][replication-revert], [current contract][deferred-spec].

## 5. Recommended planning agenda

The first plan should freeze **released 1.4.0** for its implementation experiment, with exact
dependencies. Keep HEAD viewer/deferred characterization as a separate input. Neither feature
is necessary to prove retained reports or a persisted decision, and neither should silently
change what the first host promises about storage.

| Order | Planning unit and dependency | Evidence required / stop condition |
| --- | --- | --- |
| 1 | **One retained report/decision operation.** Correct W12's storage model; select the precise review subject and acceptance rules. No publication or shared client needed. | A valid report survives restart; a later reply creates one continuation; changed subject, revocation/cancellation, duplicates, and lost acknowledgment have explicit outcomes. Stop if feature policy must be copied or the report floor weakened. |
| 2 | **Worker comparison at that operation.** Use current-worker collection as the control and compare the hybrid/native paths in 4.1. | Actual restricted assignments, required resources, nested-call/replay enforcement, semantic completion, scoped cancellation, and once-counted usage under stated limits. Compare recovery labor and repeated work. Choose on those results, including retaining v1 if it wins. |
| 3 | **Host/data lifecycle and a useful CLI view.** Implement only the composition the chosen path needs; finalize store placement and manifest inputs for the experiment. | Ownership before writable open, compatibility refusal, real process death with surviving-child handling, parked/sleeping diagnostics, retained decisions, backup/restore, and explicit repair outcomes. No default runtime switch. |
| 4 | **One plan workflow.** Depends on 1–3 preserving their guarantees. Use the mature Python operations and current backend authority. | Incremental publication reconciles its own interrupted effects; stacked publication retains separate coverage. Human ready/merge boundaries survive. Failure must leave work recoverable through an explicit path. |
| 5 | **Objective and learning continuity.** Build on the working plan slice. | Multi-node eligibility reconciles backend edits and merges; learning retains original evidence and accepted results across interruptions. Task completion cannot mark a node or capture complete. |
| Parallel research, after a working operation exists | **Chord client transport; wakeable remote hosting; HEAD observation/persistence.** None is a prerequisite for the first retained operation. | Two-client freshness and reply recovery; alarm-before-admission behavior; explicit live-versus-stored views. Stop if the new substrate creates a second authority or unbounded operational work. |

This sequence retains the original failure obligations while changing their delivery grouping.
It does not require finishing every v1 improvement before learning from Durable, and does not
relax the current runtime's regression or certification requirements. User-facing adoption
would amend the cross-plane contract and user docs in the implementation that changes behavior.

Three findings would change this recommendation:

- A supported current-worker recovery operation preserves all of Perk's report guarantees
  with markedly less work: prioritize that path and defer native workers.
- A native Durable binding demonstrates resource/restriction parity and materially simpler
  recovery: deepen that binding without moving approved-plan authority as a side effect.
- Both paths require extensive duplicated feature policy or impose unacceptable data
  operations: retain the current workflow, preserve independent improvements, and reconsider
  the adoption hypothesis itself.

## 6. Offline experiments and reproduction

### Environment and measured results

The scratch root was `/tmp/perk-durable-avenues.DoqGYM`. `head/` is the exact library source
snapshot; `stable/` and `original/` were complete `gh api` source archives at the hashes above.
Dependency installation used `npm ci --ignore-scripts --no-audit --no-fund` in scratch copies.
The scratch shell selected Node 25.4.0 / npm 11.7.0 for dependency preparation; test and
process-probe commands explicitly used Node **26.12.1**. Both satisfy upstream's stated Node
minimum; no claim about Perk's complete host-support matrix follows.

Telemetry, Chord, and codemode were built in their own workspaces. The source archives omit
generated AI catalogs, so the installed Perk development package's 1.4.0
`dist/providers/data` directory was copied into each scratch `packages/ai/src/providers/data`.
`npm run build:offline --workspace packages/ai` validated the data and compiled successfully
on both snapshots. Model-catalog/provider behavior was not an experiment target. These setup
steps matter: an initial unbuilt-source test invocation did not load any tests and is not
counted as an upstream failure or a pass.

All measured model interactions used upstream faux providers or no model. Network access was
used to obtain source archives/dependencies; the experiments required no provider, SSH server,
external service mutation, or publication. Temporary databases and test processes were cleaned
up by the probes. No production Perk feature was replaced.

| Run | Result | What it establishes |
| --- | --- | --- |
| Released 1.4.0 Durable, 14 focused upstream files | **230/230 passed**, 0 pending. | Selected tool replay, nested restart, codemode journal, sleep, parking, reports, storage failure, ownership, input, caller, structured-output, watch, and failed-inbox contracts. |
| HEAD Durable, the same files plus three new files | **272/272 passed**, 0 pending. | The above at the newer snapshot, plus read-only Harness and deferred progress/document commits. Test bodies differ by version; counts are not a performance comparison. |
| HEAD Chord principal/reload suites | **22/22 passed**, 0 pending. | Selected in-memory principal variants and reload contracts. No networked Perk client or durable cluster reload claim. |
| Temporary decision probe, released 1.4.0 | **4/4 passed**. | Late/no-waiter reply, duplicate reply, changed subject, cancellation, and accepted-write/lost-ack receipt recovery in a small local fixture. |
| Temporary decision + viewer probes, HEAD | **5/5 passed**. | The same fixture semantics, plus a cached reader remaining stale until reopened. |
| Real owner `SIGKILL` + SQLite + Node execution, each snapshot | **Both passed.** `retainedFirst=1`, `completedSecond=1`, `restarts=1`, `childSurvivedOwner=true`. | A retained application record survived, a running task recovered to pending, and the detached command survived owner death. The parent explicitly killed it before allowing controlled completion. |

The final assertion total is **533 passing test cases plus two successful process-death probes**.
The decision fixture checks subject equality and cancellation; it does not implement or test
authentication, delegated authority, artifact digests, save destinations, resource compatibility,
real report schemas, or external-effect reconciliation. Its recovered continuation performs a
local counter update. The crash fixture releases controlled work after explicitly terminating
the old subprocess; it does not prove that a real Perk child can be reacquired or fenced.

### Commands for the upstream checks

After preparing each source snapshot and its dependencies as above, run from `packages/durable`
with the chosen Node 26.12.1 executable. This list deliberately excludes provider e2e tests and
the separate workerd tier:

```sh
node ../../node_modules/vitest/vitest.mjs run \
  test/harness-storage-failure.test.ts \
  test/harness-nested-tools-restart.test.ts \
  test/codemode.test.ts \
  test/harness-sleep.test.ts \
  test/harness-blocked.test.ts \
  test/harness-reports.test.ts \
  test/session-watches.test.ts \
  test/harness-tasks-recovery.test.ts \
  test/harness-ownership.test.ts \
  test/harness-structured-output.test.ts \
  test/harness-input-entries.test.ts \
  test/harness-callers.test.ts \
  test/harness-tools-recovery.test.ts \
  test/harness-failed-run-inbox.test.ts \
  --reporter=json --outputFile=/tmp/durable-report.json
```

On HEAD add `test/harness-read-only.test.ts`, `test/session-deferred-commits.test.ts`, and
`test/harness-deferred-progress.test.ts`. From `packages/chord`, run:

```sh
node ../../node_modules/vitest/vitest.mjs run \
  test/principals.test.ts test/reload.test.ts \
  --reporter=json --outputFile=/tmp/chord-report.json
```

For an independently acquired source snapshot, use `gh api
repos/earendil-works/pi/tarball/<full-sha>` redirected to an archive, extract it into a new
scratch directory, and install from its lockfile. Build telemetry first, then Chord/codemode
and the AI package with the catalog setup above. These are scratch build requirements, not
changes to Perk's package or CI configuration.

### Complete temporary probe sources

The sources below are included so the custom results can be reproduced without retaining
this machine's scratch directory. Place them under `packages/durable/test/` in a disposable
prepared checkout. They are experiment fixtures, not proposed Perk runtime modules.

#### `avenues-decision.test.ts`

Run with Vitest on either snapshot. This is a deliberately small decision fixture; its subject/cancellation checks are not a complete authority policy.

```typescript
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createModels } from "@earendil-works/pi-ai";
import { createRegistry, defineDoc, defineExtension, defineTask, Harness, type TaskId, type Tx } from "@earendil-works/pi-durable";
import { afterEach, expect, it } from "vitest";
import { openNodeSqliteStorage } from "../src/storage/sqlite/node.ts";
import { context } from "./session-support.ts";

const directories: string[] = [];
afterEach(async () => { for (const directory of directories) await rm(directory, { recursive: true, force: true }); });

const Decision = defineDoc<{ subject: string; cancelled: boolean; continuation: TaskId<null> | null; executions: number }>({
  kind: "avenues.decision", version: 1, scope: "session", checkpointWhen: () => false,
  initial: () => ({ subject: "revision-a", cancelled: false, continuation: null, executions: 0 }),
});
const finished = { status: "terminal", outcome: { status: "completed", result: null } } as const;
const Request = defineTask<null, { phase: "run" }, null>({
  name: "avenues.request", version: 1, initial: () => ({ phase: "run" }),
  phases: { run: (_task, runtime, ctx) => runtime.commit(async (tx) => { await tx.doc(Decision); return finished; }, ctx) },
  abort: (_task, runtime, ctx) => runtime.commit(() => ({ status: "terminal", outcome: { status: "aborted" } }), ctx),
});
const Continue = defineTask<null, { phase: "run" }, null>({
  name: "avenues.continue", version: 1, initial: () => ({ phase: "run" }),
  phases: { run: (_task, runtime, ctx) => runtime.commit(async (tx) => { (await tx.doc(Decision)).executions++; return finished; }, ctx) },
  abort: (_task, runtime, ctx) => runtime.commit(() => ({ status: "terminal", outcome: { status: "aborted" } }), ctx),
});
function registry() {
  const result = createRegistry();
  result.install(defineExtension({ name: "avenues", tasks: [Request, Continue] }));
  return result;
}
async function open(path: string) {
  const storage = await openNodeSqliteStorage(path);
  const reports: unknown[] = [];
  const harness = await Harness.open(storage, { registry: registry(), models: createModels(), onReport: error => reports.push(error) }, context);
  return { storage, harness, root: await harness.root(context), reports };
}
async function fixture() {
  const directory = await mkdtemp(join(tmpdir(), "avenues-decision-"));
  directories.push(directory);
  const path = join(directory, "store.sqlite");
  const first = await open(path);
  const requester = await first.root.commit(tx => tx.createTask(Request, null, { ownership: { kind: "conversation" } }), context);
  first.harness.resume();
  expect((await first.harness.waitForTask(requester, context)).state.outcome.status).toBe("completed");
  await first.harness.close(context);
  return { path, requester, ...await open(path) };
}
async function reply(tx: Tx, subject: string) {
  const decision = await tx.doc(Decision);
  if (decision.subject !== subject || decision.cancelled) throw new Error("stale or cancelled");
  if (decision.continuation !== null) return decision.continuation;
  decision.continuation = await tx.createTask(Continue, null, { ownership: { kind: "conversation" } });
  return decision.continuation;
}

it("accepts a reply after its requester finishes, with no waiter, and creates one continuation for duplicate replies", async () => {
  const opened = await fixture();
  try {
    expect((await opened.harness.getTask(opened.requester, context))?.state.status).toBe("terminal");
    const one = await opened.root.commit(tx => reply(tx, "revision-a"), context);
    const two = await opened.root.commit(tx => reply(tx, "revision-a"), context);
    expect(two).toBe(one);
    opened.harness.resume();
    await opened.harness.waitForTask(one, context);
    expect((await opened.harness.snapshot(Decision, context))?.executions).toBe(1);
  } finally { await opened.harness.close(context); }
});

it.each(["changed-subject", "cancelled"])("admits no continuation for %s", async kind => {
  const opened = await fixture();
  try {
    await opened.root.commit(async tx => {
      const decision = await tx.doc(Decision);
      if (kind === "cancelled") decision.cancelled = true;
      else decision.subject = "revision-b";
    }, context);
    await expect(opened.root.commit(tx => reply(tx, "revision-a"), context)).rejects.toThrow("stale or cancelled");
    expect((await opened.harness.snapshot(Decision, context))?.continuation).toBe(null);
    expect(opened.reports).toEqual([]);
  } finally { await opened.harness.close(context); }
});

it("recovers an accepted reply after storage succeeds but its acknowledgement is lost", async () => {
  const opened = await fixture();
  const commit = opened.storage.commit.bind(opened.storage);
  let failAck = true;
  opened.storage.commit = async (...args: Parameters<typeof commit>) => {
    const sequence = await commit(...args);
    if (failAck) { failAck = false; throw new Error("lost acknowledgement"); }
    return sequence;
  };
  await expect(opened.root.commit(tx => reply(tx, "revision-a"), context)).rejects.toThrow("lost acknowledgement");
  expect((await opened.harness.closed).reason).toBe("failed");
  const recovered = await open(opened.path);
  try {
    const before = await recovered.harness.snapshot(Decision, context);
    expect(before?.continuation).not.toBe(null);
    const duplicate = await recovered.root.commit(tx => reply(tx, "revision-a"), context);
    expect(duplicate).toBe(before?.continuation);
    recovered.harness.resume();
    await recovered.harness.waitForTask(duplicate, context);
    expect((await recovered.harness.snapshot(Decision, context))?.executions).toBe(1);
    const tasks = await recovered.storage.scanTasks({}, 100, undefined, context);
    expect(tasks.items.filter(task => task.kind === Continue.definition.name)).toHaveLength(1);
  } finally { await recovered.harness.close(context); }
});
```

#### `avenues-viewer.test.ts`

Run with Vitest on HEAD only. It measures cached snapshot freshness across two Harness instances.

```typescript
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createModels } from "@earendil-works/pi-ai";
import { createRegistry, defineDoc, Harness } from "@earendil-works/pi-durable";
import { expect, it } from "vitest";
import { openNodeSqliteStorage } from "../src/storage/sqlite/node.ts";
import { context } from "./session-support.ts";

const Count = defineDoc<{ value: number }>({ kind: "avenues.count", version: 1, scope: "session", checkpointWhen: () => false, initial: () => ({ value: 0 }) });
it("a cached read-only snapshot does not refresh when another Harness commits", async () => {
  const directory = await mkdtemp(join(tmpdir(), "avenues-viewer-"));
  const path = join(directory, "store.sqlite");
  const options = { models: createModels(), registry: createRegistry() };
  const writer = await Harness.open(await openNodeSqliteStorage(path), options, context);
  let viewer: Harness | undefined;
  try {
    await writer.commit(tx => tx.doc(Count), context);
    viewer = await Harness.open(await openNodeSqliteStorage(path), { ...options, readOnly: true }, context);
    expect((await viewer.snapshot(Count, context))?.value).toBe(0);
    await writer.commit(async tx => { (await tx.doc(Count)).value = 1; }, context);
    expect((await writer.snapshot(Count, context))?.value).toBe(1);
    expect((await viewer.snapshot(Count, context))?.value).toBe(0);
    await viewer.close(context);
    viewer = await Harness.open(await openNodeSqliteStorage(path), { ...options, readOnly: true }, context);
    expect((await viewer.snapshot(Count, context))?.value).toBe(1);
  } finally {
    if (viewer !== undefined) await viewer.close(context);
    await writer.close(context);
    await rm(directory, { recursive: true, force: true });
  }
});
```

#### `avenues-crash.ts`

Run `node --conditions=source test/avenues-crash.ts` from `packages/durable` on either snapshot. It kills only its own scratch owner and command group, then cleans its scratch database.

```typescript
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { BACKGROUND_CONTEXT as context } from "@earendil-works/chord/context";
import { createModels } from "@earendil-works/pi-ai";
import { createRegistry, defineDoc, defineExtension, defineTask, Harness, type TaskId } from "../src/index.ts";
import { NodeExecutionEnv } from "../src/env/node.ts";
import { openNodeSqliteStorage } from "../src/storage/sqlite/node.ts";

const Reports = defineDoc<{ first: number; second: number }>({
  kind: "avenues.reports", version: 1, scope: "session", checkpointWhen: () => false,
  initial: () => ({ first: 0, second: 0 }),
});
function registry(directory: string, holding: boolean) {
  const Pending = defineTask<null, { phase: "run" }, null>({
    name: "avenues.pending", version: 1, initial: () => ({ phase: "run" }),
    phases: { run: async (task, runtime, ctx) => {
      if (holding) {
        const env = new NodeExecutionEnv({ cwd: directory });
        let output = "";
        let announced = false;
        const code = 'const fs = require("node:fs"); console.log(process.pid); setInterval(() => fs.appendFileSync(process.argv[1], "tick\\n"), 25);';
        const result = await env.exec([process.execPath, "-e", code, join(directory, "heartbeat")], {
          onOutput: chunk => {
            output += chunk;
            if (!announced && output.includes("\n")) {
              const childPid = Number(output.trim());
              assert(Number.isSafeInteger(childPid) && childPid > 0);
              announced = true;
              console.log(JSON.stringify({ childPid, taskId: task.id }));
            }
          },
        }, ctx);
        if (!result.ok) throw result.error;
      }
      await runtime.commit(async tx => {
        (await tx.doc(Reports)).second++;
        return { status: "terminal", outcome: { status: "completed", result: null } };
      }, ctx);
    } },
    abort: (_task, runtime, ctx) => runtime.commit(() => ({ status: "terminal", outcome: { status: "aborted" } }), ctx),
  });
  const value = createRegistry();
  value.install(defineExtension({ name: "avenues", tasks: [Pending] }));
  return { value, Pending };
}
async function open(directory: string, holding: boolean) {
  const { value, Pending } = registry(directory, holding);
  const harness = await Harness.open(await openNodeSqliteStorage(join(directory, "store.sqlite")), {
    models: createModels(), registry: value, onReport: error => console.error(error),
  }, context);
  return { harness, Pending, root: await harness.root(context) };
}
async function heartbeat(path: string): Promise<number> {
  try { return (await readFile(path, "utf8")).length; }
  catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") return 0;
    throw error;
  }
}
const delay = () => new Promise(resolve => setTimeout(resolve, 25));
if (process.argv[2] === "child") {
  const directory = process.argv[3];
  assert(directory !== undefined);
  const { harness, Pending, root } = await open(directory, true);
  await root.commit(async tx => { (await tx.doc(Reports)).first = 1; }, context);
  const taskId = await root.commit(tx => tx.createTask(Pending, null, { ownership: { kind: "conversation" } }), context);
  harness.resume();
  await harness.waitForTask(taskId, context);
  await harness.close(context);
} else {
  const directory = await mkdtemp(join(tmpdir(), "avenues-sigkill-"));
  const owner = spawn(process.execPath, ["--conditions=source", fileURLToPath(import.meta.url), "child", directory], { stdio: ["ignore", "pipe", "pipe"] });
  assert(owner.stdout !== null && owner.stderr !== null);
  let diagnostics = "";
  owner.stderr.on("data", chunk => { diagnostics += String(chunk); });
  let childPid: number | undefined;
  try {
    const lines = createInterface({ input: owner.stdout });
    const marker = await new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`owner did not become ready: ${diagnostics}`)), 10_000);
      lines.once("line", line => { clearTimeout(timer); resolve(line); });
      owner.once("exit", () => { clearTimeout(timer); reject(new Error(`owner exited before kill: ${diagnostics}`)); });
    });
    lines.close();
    const parsed: unknown = JSON.parse(marker);
    assert(typeof parsed === "object" && parsed !== null && "childPid" in parsed && "taskId" in parsed);
    assert(typeof parsed.childPid === "number" && Number.isSafeInteger(parsed.childPid));
    assert(typeof parsed.taskId === "number" && Number.isSafeInteger(parsed.taskId));
    childPid = parsed.childPid;
    const taskId = parsed.taskId as TaskId<null>;
    const exited = once(owner, "exit");
    assert(owner.kill("SIGKILL"));
    const [, signal] = await exited;
    assert.equal(signal, "SIGKILL");
    const before = await heartbeat(join(directory, "heartbeat"));
    for (let attempt = 0; attempt < 80 && await heartbeat(join(directory, "heartbeat")) <= before; attempt++) await delay();
    assert(await heartbeat(join(directory, "heartbeat")) > before, "NodeExecutionEnv child did not survive owner death");
    process.kill(-childPid, "SIGKILL");
    childPid = undefined;
    const { harness } = await open(directory, false);
    try {
      const task = await harness.getTask(taskId, context);
      assert.equal(task?.state.status, "pending");
      assert.equal(task?.restarts, 1);
      assert.deepEqual(await harness.snapshot(Reports, context), { first: 1, second: 0 });
      harness.resume();
      await harness.waitForTask(taskId, context);
      assert.deepEqual(await harness.snapshot(Reports, context), { first: 1, second: 1 });
      console.log(JSON.stringify({ node: process.version, retainedFirst: 1, completedSecond: 1, restarts: task.restarts, childSurvivedOwner: true }));
    } finally { await harness.close(context); }
  } finally {
    if (owner.exitCode === null && owner.signalCode === null) owner.kill("SIGKILL");
    if (childPid !== undefined) {
      try { process.kill(-childPid, "SIGKILL"); }
      catch (error) { if (!(error instanceof Error && "code" in error && error.code === "ESRCH")) throw error; }
    }
    await rm(directory, { recursive: true, force: true });
  }
}
```

The custom Vitest commands were `node ../../node_modules/vitest/vitest.mjs run test/avenues-decision.test.ts`
on 1.4.0 and the same command with `test/avenues-viewer.test.ts` added on HEAD. JSON reporters
were used for the result counts. Both process-death runs printed the same asserted result:

```json
{"node":"v26.12.1","retainedFirst":1,"completedSecond":1,"restarts":1,"childSurvivedOwner":true}
```

### Source references

Released references pin v1.4.0; HEAD references pin the inspected newer commit. Source links
describe upstream mechanisms, not a promise that Perk's integration exists. Local links point
to the original proposals and current Perk evidence.

[release-notes]: https://pi.dev/changelog
[durable-changelog]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/CHANGELOG.md
[head-changelog]: https://github.com/earendil-works/pi/blob/38ff99177fba21e9c57a670f4e95adcf407c99c7/packages/durable/CHANGELOG.md
[coding-changelog]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/coding-agent/CHANGELOG.md
[agent-changelog]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/agent/CHANGELOG.md
[ai-changelog]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/ai/CHANGELOG.md
[mcp-changelog]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/mcp/CHANGELOG.md
[chord-changelog]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/chord/CHANGELOG.md
[chord-readme]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/chord/README.md
[chord-spec]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/chord/docs/spec.md
[codemode-changelog]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/codemode/CHANGELOG.md
[env-changelog]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/env/CHANGELOG.md
[env-readme]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/env/README.md
[telemetry-changelog]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/telemetry/CHANGELOG.md
[stable-readme]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/README.md#sleeping-and-waking-up
[stable-storage]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/README.md#storage
[stable-errors]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/README.md#errors
[head-readme]: https://github.com/earendil-works/pi/blob/38ff99177fba21e9c57a670f4e95adcf407c99c7/packages/durable/README.md
[head-errors]: https://github.com/earendil-works/pi/blob/38ff99177fba21e9c57a670f4e95adcf407c99c7/packages/durable/README.md#errors
[transaction-spec]: https://github.com/earendil-works/pi/blob/38ff99177fba21e9c57a670f4e95adcf407c99c7/packages/durable/docs/spec.md#4-transactions-and-storage-ownership
[deferred-spec]: https://github.com/earendil-works/pi/blob/38ff99177fba21e9c57a670f4e95adcf407c99c7/packages/durable/docs/spec.md#41-deferred-commits
[session-source]: https://github.com/earendil-works/pi/blob/38ff99177fba21e9c57a670f4e95adcf407c99c7/packages/durable/src/session/session.ts
[durable-package]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/package.json
[tool-source]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/src/harness/tool.ts
[submissions-source]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/src/harness/submissions.ts
[telemetry-source]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/src/harness/telemetry.ts
[tools-index]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/src/tools/index.ts
[readonly-tests]: https://github.com/earendil-works/pi/blob/38ff99177fba21e9c57a670f4e95adcf407c99c7/packages/durable/test/harness-read-only.test.ts
[deferred-tests]: https://github.com/earendil-works/pi/blob/38ff99177fba21e9c57a670f4e95adcf407c99c7/packages/durable/test/session-deferred-commits.test.ts
[tool-recovery-tests]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/test/harness-tools-recovery.test.ts
[codemode-tests]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/test/codemode.test.ts
[caller-tests]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/test/harness-callers.test.ts
[input-tests]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/test/harness-input-entries.test.ts
[sleep-tests]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/test/harness-sleep.test.ts
[ownership-tests]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/durable/test/harness-ownership.test.ts
[replication-feature]: https://github.com/earendil-works/pi/commit/4c25119f5432dbaa4942ad329642aa0cfecae385
[replication-revert]: https://github.com/earendil-works/pi/commit/cae9fd28a2d3d515c83ea495093e3768cc8efab6
[adoption]: ../design/archive/pi-1.4.0-adoption.md
[pair-assessment]: pi-and-subagents-assessment-2026-10-24.md
[perk-package]: ../../package.json
[perk-contracts]: ../../shared/contracts.md#835--the-learn-evidence-bundle-contract
[perk-wave]: ../../extension/waves/reportWave.ts
[perk-transport]: ../../extension/waves/transport.ts
[perk-review]: ../../extension/pi/v1/draftReview.ts
[workflow-session]: ../../extension/session/workflowSession.ts
[browser-owner]: ../../extension/pi/v1/browserOperation.ts
[perk-worker]: ../../extension/worker/sdkAdapter.ts
[bare-guard]: ../../extension/bareImportGuard.test.ts
[direction-guard]: ../../extension/importDirectionGuard.test.ts
