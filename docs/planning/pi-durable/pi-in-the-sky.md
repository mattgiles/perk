# Pi in the sky: perk as a durable engineering workspace

2026-10-05. A strategy proposal for perk's maintainers, grounded in the source snapshots
listed below. The proposed architecture and experiments are future work.

For the first-v2 experience and longer-term product horizon, start with
[Perk with Pi Durable: a working vision](vision.md).

For a concrete walkthrough of TypeScript/Durable coordination with Python doors and issue-backed
plans, see the companion [How a durable perk would work](pi-durable-workflows.md).

For developing that integration alongside the current runtime, see
[A parallel path to Pi Durable](pi-durable-v2.md).

For an independent v1 pilot in delegated review preparation that can inform both runtimes,
see [A shared decision foundation for v1 and v2](decision-foundation.md).

## Direction

**Extend perk's durable plans into durable execution and coordination.** Perk already keeps
reviewed work outside any one conversation. Its cross-machine guarantee is
[stage-boundary and pushed-branch durability][current-durability]. Pi Durable raises the
possibility of retaining finer-grained execution progress and coordination across interruptions.

Perk would retain execution state and accepted evidence; bounded tasks would perform work;
validated domain outcomes would authorize continuation. An objective could span many
conversations while people join, steer, and review through whichever interface suits the moment.

Three ideas make this worth pursuing: objectives that execute across sessions, a shared
engineering workspace, and competing approaches that can be tested before committing to one.
Coordinator ownership, canonical-state authority, and worker runtime are independent
architectural decisions. None requires choosing the others in advance.

Keep [#2656's Pi 1.0 compatibility program][pin-program] bounded. Completing it strengthens
the current system and gives us a better baseline for experiments. This memo neither adds
Durable to that program nor makes its completion depend on a new architecture.

## What has changed

The [October 1 announcement][announcement] presents Pi Durable as a separate experimental
framework alongside the Pi coding agent. Its combination of tasks, conversations, and
application documents makes a larger architectural question practical: could the same runtime
support the lifetime of the engineering workflow as well as its agent calls?

Earlier planning already explored durability, state ownership, shared services, and detached
interfaces. The released Durable package gives those questions a concrete implementation to
evaluate together:

| Earlier direction | Principle retained | Question to test now |
| --- | --- | --- |
| [Headless objective execution][headless] | Deterministic coordination, bounded workers, receipts, and human gates. | Which conductor responsibilities remain Perk policy, and which can Durable execute? |
| [Library decomposition][decomposition] | Perk owns semantic interfaces that hide runtime details. | Can those interfaces admit Durable while reducing caller obligations? |
| [Deep Pi integration][integration] and the [v3 memo][v3] | State, execution, and presentation need independent proofs; retaining Python is a migration default. | How much of that broader vision does this package support, and what must perk still build? |

Those documents describe older upstream snapshots. Their AgentHarness, lane, storage-format,
and application-host details require fresh verification against `packages/durable`. Their
central discipline survives: an architectural change earns its place by removing obligations
from callers while preserving perk's domain guarantees.

## 1. Objectives become durable programs

Imagine starting an approved objective node on Monday. Perk implements it, publishes a draft
PR, and starts its reviewer wave. The process dies. On Tuesday, a replacement process
recovers the completed reports, finishes the outstanding work, and waits for a maintainer's
decision. The maintainer responds that afternoon; execution continues within the approved
scope.

The objective would have an explicit execution state throughout. Perk's deterministic policy
would select eligible work and decide whether evidence satisfies a gate. Models would author,
implement, and review through bounded assignments with distinct contexts, capabilities,
budgets, and outcomes.

Durable provides custom checkpointed tasks, child ownership, and waits on other tasks.
Those are mechanisms on which perk could express the workflow. [Task documentation][tasks]
supports that possibility; it does not supply perk's objective dependency rules, review
completeness policy, or delivery semantics.

A useful Perk topology would keep execution state independently of interactive turns and
individual tasks. Bounded tasks would perform assignments and continue from accepted outcomes;
a pending human decision could outlive its requesting task. No continuously running model or
permanently live root task is required. Native Durable workers would use fresh conversations;
existing workers could retain their current execution binding. Clients attach to a Perk view
of retained facts and live work. Detachment, interrupting a turn, and cancelling an objective
have different scopes. The [background-subagent example][background-example] demonstrates
lifetime separation, but its follow-up message does not prove parent consumption or report
acceptance. Perk must own those meanings and the pending-decision lifecycle.

Fresh implementation context remains valuable, as does an independent reviewer's view. A long
objective could use many short conversations while retaining one coherent execution record.

The largest potential simplification is retained application state with shared execution
machinery. Objective coordination, stage driving, reviewer collection, deadlines, and waiting
currently cross several lifetimes. Durable could absorb scheduling and recovery mechanics while
short Perk operations validate and record “review complete,” “plan approved,” and “ready for
delivery.” Task completion and final model prose would not establish those facts. Roadmap
dependencies would remain distinct from the runtime's ownership tree.

Human gates would record decisions against the work and revision they authorize. Closing a
view leaves the gate pending. Perk must also retain its governing policy identity, recheck
applicable authorization before resumption, and enforce budgets across recovered attempts.
The [workflow companion][execution-state] owns record lifetime and continuation policy, including
the experiment defaults of one SQLite store per logical execution and conversation-owned
continuations. Its [resume rules][recovery-contract] cover compatibility, restrictions, and
budget admission; reopening tasks alone does not establish those guarantees.

**Proof:** interrupt a reviewer wave after one assignment finishes. Recovery should reuse that
report, continue unfinished work, and preserve the wave's restrictions, budgets, and acceptance
rules. External effects still require perk's reconciliation outside Durable's atomic commits.

## 2. Perk becomes a shared engineering workspace

Imagine drafting a plan in the terminal, leaving implementation running on a remote machine,
and opening a browser later to inspect its evidence. A teammate reviews a particular plan
revision while the agent continues an independent assignment. Both see the same engineering
state, including what is running and which decision is pending.

The workspace would hold explicit plans and revisions, objective progress, decisions,
artifact references, and review evidence. Conversations would read the portions relevant to
their assignments. Interfaces would present that state and submit semantic operations such
as proposing a revision, approving it, requesting the next action, or cancelling work.
These are proposed application responsibilities, not new command names or API contracts.

Durable's documents can change atomically with transcript entries and task creation; its
conversation watches support current views and subsequent changes. [Documents][documents],
[commit semantics][invariants], and [watching][watching] provide useful foundations. Perk
would still need to implement client transport, identity, authorization, and conflict handling.
Subscribing to state would confer no permission to change it.

The payoff would reach beyond multiplayer. A single maintainer could move between terminal,
browser, and unattended execution with the same operation semantics. Warm, cold, and
headless entry points could share more of their behavior. Interface lifecycle would govern
observation; explicit commands would govern execution.

Evidence could become easier to use as well. A review would identify the plan revision and
code head it assessed. A delivery decision would point to its supporting checks. `/learn`
could consume those relationships alongside conversation evidence, reducing dependence on
reconstructing every fact from session files. Curating durable learnings would remain an
explicit workflow decision.

All three configurations below could support this experience. Workspace documents could
hold execution facts and versioned observations of backend-owned plans, or the workspace
could also own approved workflow revisions. Each fact needs one owner; keeping independently
editable copies would undermine the simplification.

**Proof:** connect two clients, disconnect one, change the plan, and reconnect it. Both must
converge on current state. A stale approval must not authorize the changed revision, a
retried decision must not advance work twice, and disconnecting must not cancel execution.

## 3. Competing approaches become executable experiments

Imagine an objective whose central uncertainty is whether a refactor should preserve an
existing abstraction or replace it. Perk could investigate both from a common starting point,
produce a bounded implementation of each, run the same checks, and present the evidence
before the maintainer chooses.

This would make an important class of planning questions empirical. The comparison could
include correctness, migration difficulty, maintenance burden, runtime measurements, and
agent cost. A cheaper or faster candidate would still need to satisfy the agreed criteria.

Perk could assemble a basic comparison using existing agents and worktrees. Durable's
potential contribution is keeping the experiment's coordination, costs, evidence, and
unfinished work coherent across interruptions. The hypothesis is a more useful and recoverable
experiment, with conversation inheritance as one optional technique.

Durable supports conversation forks and document inheritance choices, including historical
values. Task documents are not copied by a conversation fork. [Fork documentation][forks]
and [document semantics][document-semantics] make the limits explicit. Perk would coordinate
those capabilities with a separate Git worktree or execution environment for each candidate.
Conversation history alone cannot reproduce a filesystem or reverse an external action.

A reviewed experiment plan would authorize the implementation work, define its starting
commit, comparison criteria, resource bounds, and publication limits. Ordinary planning
would retain its read-only posture. Each candidate would receive the relevant approved
material; implementation and independent review would keep fresh contexts where they improve
judgment. Forking would be a deliberate choice for exploration, rather than the default for
every worker.

Promotion would be an explicit domain operation: choose an approach, preserve the evidence,
and carry the selected work into the normal plan and delivery path. Any changed plan would
need the corresponding review. Authorization and assertions about published work would not
be copied into a candidate merely because its conversation inherited some history.

The selected and rejected candidates would leave evidence of what was tried, under which
conditions, and why one approach won. A maintainer revisiting an assumption could use that
record; `/learn` could curate it into durable recommendations.

**Proof:** run two candidates against one starting commit, stop one, and complete the other.
Their writes, budgets, and cancellation must remain isolated. The final report must identify
each tested revision, and selecting a candidate must not publish or merge it implicitly.

## Separate orchestration from state authority

Separate three axes: **who owns advancement**, **where canonical workflow records live**, and
**which runtime executes workers**. The following configurations compare the first two;
each still admits a separate worker-runtime choice.

| Configuration | Orchestration | Approved plans and objectives | Benefit and cost to evaluate |
| --- | --- | --- | --- |
| Evolve the exterior | Python selects domain actions; Durable executes bounded assignments. | GitHub/Linear remain authoritative. | Reuses existing coordination; cross-runtime protocols remain. |
| Consolidate orchestration | One coordinator advances work through Durable tasks; Python may supply typed eligibility evaluation. | GitHub/Linear remain authoritative. | May unify execution lifetimes; requires fresh backend reconciliation, with policy migration justified separately. |
| Consolidate workflow authority | TypeScript Perk policy coordinates through Durable tasks. | A Perk store owns revisions and decisions; issue backends publish projections. | Can commit workflow decisions and task admission together; adds authoritative-store operation and migration obligations. |

The middle configuration isolates the case for orchestration consolidation. Python could
continue supplying eligibility policy and mature Git, worktree, and backend operations.
One coordinator would own advancement; a Python evaluator would return a decision without
independently launching the next action. Execution receipts would reference approved artifacts
and reconcile against current authority, following the
[existing execution-contract distinction][execution-authorities]. A task checkpoint could
record an attempt without becoming a second mutable copy of objective truth.

In all three, Git remains authoritative for code, and GitHub remains authoritative for
PR and merge state. A workflow document can record an observation or an intended operation;
the external system determines whether the effect happened.

If workflow authority moved, issue edits would enter as explicit proposed changes, with revision
checks and conflict handling. They could not silently compete with the Perk store. Existing
issue-backed work would require an explicit import and cutover before its authority changed.
Likewise, exporting a readable plan would not back up execution history. A fresh clone with
GitHub access would no longer reconstruct all workflow state. That loss must be weighed
against the benefit of atomic decisions and task admission.

### Compare worker runtimes

Use the same restricted report assignment, exact subject, and interruption scenario to compare
three paths before committing to a worker replacement:

| Path | Opportunity | Obligations to test |
| --- | --- | --- |
| Recoverable existing supplier collection | Recollect persisted results and reacquire running work with less change to worker execution. | Stable assignment/attempt identity, subject validation, accepted-report retention, and recovery beyond process-local handles. |
| Durable coordination over current workers | Persist workflow progress while keeping current SDK resources, tools, and restrictions. | Reconcile unknown launches, attach/collect/cancel external workers, and enforce limits across attempts; never blindly replay a worker launch. |
| Native Durable workers | Use one runtime for task and conversation recovery, starting from supplied environment and tool mechanisms. | Bind Perk resources and restrictions, preserve enforcement on replay, and prove semantic report acceptance and budget accounting. |

The incumbent has more than in-memory state: Perk's [RPC adapter][worker-results] reads supplier
`status.json`. Installed pi-subagents 0.75.0 has [workflow reuse][supplier-reuse] for the same
session, script/arguments, child key, and fingerprint after `runtime-replaced`: successful
children may be reused and running children reattached. Journal appends can fail without
stopping the workflow, so missing records can cause reruns. This is narrower than general
host-crash recovery and does not make Perk's instance-owned collector recoverable by itself.
The older library mirror is 0.71.0; do not
attribute the installed behavior to it. Both the earlier [recollection proposal][v3] and
[transport comparison][integration] remain useful baselines.

Durable [custom tasks performing external work][external-task] make the hybrid path plausible.
That mechanism does not solve worker admission, surviving processes, or cancellation. All
three options face the same [application recovery requirements][recovery-contract].
Record each option's tool concurrency, retries, compaction, capabilities, and usage accounting;
compare stated conditions rather than assuming runtime defaults are equivalent. The
[development proposal][validation] owns that proof and the economical native binding.

The shared workspace has this common responsibility structure, independent of those choices:

```mermaid
flowchart TB
    Clients["Terminal, browser, remote clients"]
    Policy["Perk policy: coordination, gates, delivery decisions"]
    Approved["Approved plans and objectives: backend or Perk store"]
    State["Retained Perk execution state and accepted evidence"]
    Durable["Pi Durable: bounded tasks and conversations"]
    View["Perk execution view"]
    Operations["Git, worktree, backend operations"]
    External["Git and GitHub: code, PRs, merge facts"]
    Clients -->|commands| Policy
    Policy -->|reads approved work| Approved
    Policy <-->|validate and commit| State
    Policy -->|authorized work| Durable
    Durable -->|outcomes to reconcile| Policy
    State --> View
    Durable -->|live status and diagnostics| View
    View --> Clients
    Durable -->|external operations| Operations
    Operations --> External
    Operations -->|workflow updates| Approved
```

The boxes describe proposed responsibilities, not deployment units or new APIs. Language
consolidation earns its place where it removes a costly boundary; changing the authority for
approved work needs its own case.

## Recommendation and proofs

**Pursue the shared workspace as the product vision; prove Durable's execution and observation
benefits first.** Durable objectives are the strongest architectural opportunity. Competing
implementations remain a further exploration once work isolation and recovery are credible.
Compare coordinator ownership, canonical-state authority, and worker runtime separately.

The [validation sequence][validation] defines the acceptance evidence:

1. **Isolated host:** prove package/dependency separation, exclusive ownership before opening
   the store, and compatibility checks before scheduler resume.
2. **Independent early proofs:** compare restricted report-worker options, and separately prove
   a persisted human decision creates one continuation without a model or UI transport.
3. **Failure recovery:** retain completed evidence across owner death, reconcile surviving
   children, and enforce compatibility, restrictions, scoped cancellation, and budget admission.
4. **Experimental plan workflow:** implement an approved plan, publish incrementally, review,
   and hand off to a human, preserving separate stacked-publication regressions.
5. **First usable v2:** demonstrate multi-node objective reconciliation after external changes
   and recoverable learning over a retained evidence bundle.

The v1 review-preparation pilot can proceed independently. Its general questionnaire/RPC
investigation is not a prerequisite for either that pilot or Durable's decision proof.

Start on a prepared worktree with a pinned runtime and controlled effects. Live publication
would use a designated test repository. The later two-candidate experiment must additionally
prove workspace isolation, comparable evidence, bounded resources, and explicit selection.

The Perk/Durable extension integration remains unproven. The appendix distinguishes execution
mechanics that might shrink from policy, resource loading, and evidence guarantees that need
an implementation under either runtime. Each proof must name one owner of advancement.

Assess each migrated behavior by retained work, repeated model/tool work, manual recovery,
and obligations removed and added. V1 remains supported during the experiment, so repository-wide
deletion is not an early success criterion. Expand only where the new path demonstrates a
useful reduction in the work needed to operate or recover it.

Production adoption would also require storage and workspace recovery. Current backends
require one owning process without cross-process locking; SQLite's documented defaults
distinguish process-crash recovery from power or host failure. [Storage documentation][storage]
leaves backup, placement, and relocation as application responsibilities. Long-lived work also
needs task/document migrations and policy-version rules. Refusing incompatible resume must be
proven in the initial host; general migration and production operation belong in subsequent
plans. This memo does not choose a production host or amend the current two-plane contract.

## Appendix: evidence and boundaries

Snapshots: perk `91719e4933389fece395cd570d0b8a0f7506b7b8`; upstream Pi
`b7dfc049e917a265a5aefa9f3952a2dec9b81cfd`. The [package manifest][package] declares Durable
`1.0.3`; its [README][upstream] labels the API experimental. These source observations are
distinct from the October 1 announcement and #2656's exact Pi 1.0.0 compatibility work.
The [installed supplier 0.75.0][supplier-package] is a local inspection artifact, not a file
guaranteed in a fresh checkout or the library's 0.71.0 source snapshot.

The [Pi Durable Technical Manual][manual] is a 190-page local reference dated 2026-10-05,
covering Durable 1.0.3 at `5b6c792b424e73edefbfa558b901bcd64788dad2`. Page citations across these
documents use its printed pagination. The mirror above is newer but declares the same package
version. Its intervening Durable changes are unreleased watcher, file-read, output, and progress
default fixes; the inspected diff does not change the core task, Session, or document semantics
used here. A package version alone therefore does not identify the evidence baseline.

README/spec links identify **documented** contracts; source links identify **implementation
inspected**; test links identify **tests inspected**, meaning bodies were read, not executed.
The manual's captured two-process `SIGKILL` experiment (pp. 94–95) was inspected, not reproduced.
It supplies upstream crash-recovery evidence, not Perk integration or surviving-child-fencing
evidence. The architectural implications below remain proposals. Citations support the observed
behavior, not an assertion that the Perk integration has already been demonstrated.

| Boundary | Inspected evidence | Proposed reduction, retained responsibilities, and uncertainty |
| --- | --- | --- |
| Stage execution | Perk's [stage drive][perk-stage] handles `implement` and `address`; the [SDK adapter][perk-sdk] constructs coding-agent services with project resources. Durable's [scheduler][scheduler] restores running tasks to pending checkpoints; its [recovery test][task-recovery-test] exercises close/reopen. The manual distinguishes runtime completion from usable results (pp. 92, 95–96). | Durable might own interrupted execution and scheduling. Perk must bind resources, restrictions, and budgets, and validate typed outcomes before advancement. A runtime `done` result is insufficient. This does not establish that the coding-agent extension loads in Durable or which driver code could disappear. |
| Reviewer waves | [ReportWave][perk-wave] holds pending references in an instance-owned `WeakMap`, although supplier results persist. The [child policy][perk-child-policy] specifies fresh report delivery, a restriction floor, and subject restoration. The [background example][background-example] enqueues a report follow-up; queued follow-ups can remain unconsumed (manual pp. 84–87). | Durable identity could make collection reacquirable. Accepted reports need retained application records and continuation; notification delivery is insufficient. Keep schemas, completeness, exact subject availability, restrictions, and logical single acceptance. Measure simplification across interruption after partial success. |
| Workflow state and artifacts | [WorkflowSession][perk-artifacts] checks provenance and digests. The [commit implementation][commit-implementation] distinguishes definite rejection from uncertain persistence. [Fork tests][fork-tests] and the [document contract][document-semantics] establish lifetime and inheritance behavior; manual pp. 50–59 explain persistent record-policy choices. | Choose storage by record lifetime; retain accepted facts beyond tasks and give mutable documents a checkpoint policy. Hide uncertain-commit recovery in semantic operations. One successful backing experiment does not justify migrating every field or moving approved-plan authority. |
| Shared observation and learning | [Document-watch tests][watch-tests] check committed revisions; [conversation watches][watching] support attachment. Perk's [surfaces module][perk-surfaces] centralizes UI emission. Built-in views omit Perk documents, task graphs contain live work, and model context transforms history (manual pp. 37–48, 129–139). | Build the execution view from retained facts and live diagnostics. Derive learning from committed history, accepted outcomes, and provenance, preserving failures and corrections. Client transport, authorization, and stale-command handling remain Perk work; watches alone establish neither a remote application nor an evidence archive. |
| Delivery effects | Perk's [stacked-publication protocol][perk-publication] records intent before mutation; its [crash regression][perk-publication-test] rediscovers a PR. [Incremental submit][incremental-publication] uses its own branch/PR convergence path. Durable's [tool recovery][tool-recovery] checks replay policy; its [task recovery test][task-recovery-test] calls an idempotent service twice with one applied effect. | Preserve and prove route-specific reconciliation and mutation preconditions. The stacked journal does not establish incremental recovery. Durable's added value must also appear inside execution, such as retaining completed reviews while recovering outstanding assignments. |

No Durable runtime experiment, Perk extension-compatibility certification, multi-client
application, or failure-injection run was performed for this memo. The proposed experiments
must establish whether these mechanisms compose successfully. Current workflow contracts and
user-facing behavior remain unchanged.

[pin-program]: https://github.com/mattgiles/perk/issues/2656
[announcement]: https://earendil.com/posts/pi-durable/
[current-durability]: ../../user-docs/explanation/how-perk-thinks.md#stages-and-doors-how-you-move-through-the-workflow
[headless]: ../deepen-headless-execution/memo.md
[execution-authorities]: ../deepen-headless-execution/objective-execution-contract.md#authorities
[decomposition]: ../future-proofing-decomposition.md
[integration]: ../deep-opportunities-pi-integration.md
[v3]: ../upcoming-pi-changes-memo-v3.md
[upstream]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/README.md
[package]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/package.json
[tasks]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/README.md#child-tasks
[documents]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/README.md#your-own-state
[watching]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/README.md#watching-a-conversation
[forks]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/README.md#more-conversations-and-forks
[storage]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/README.md#storage
[invariants]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/docs/spec.md#1-terms-and-invariants
[document-semantics]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/docs/spec.md?plain=1#L1084-L1096
[background-example]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/test/examples/23-subagent-background.ts#L56-L115
[scheduler]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/src/harness/scheduler.ts#L238-L255
[task-recovery-test]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/test/harness-tasks-recovery.test.ts#L111-L144
[commit-implementation]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/src/session/session.ts#L405-L443
[fork-tests]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/test/session-forks.test.ts#L29-L108
[watch-tests]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/test/session-watches.test.ts#L39-L82
[tool-recovery]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/src/harness/tool.ts#L93-L110
[perk-stage]: ../../../extension/worker/stageExecution.ts#L60-L93
[perk-sdk]: ../../../extension/worker/sdkAdapter.ts#L458-L526
[perk-wave]: ../../../extension/waves/reportWave.ts#L638-L686
[perk-child-policy]: ../../design/pi-subagents-child-execution-policy.md
[perk-artifacts]: ../../../extension/session/workflowSession.ts#L531-L566
[perk-surfaces]: ../../../extension/surfaces/surfaces.ts#L120-L155
[perk-publication]: ../../../src/perk/delivery/publish.py#L879-L925
[perk-publication-test]: ../../../tests/test_delivery_publish.py#L1387-L1403
[incremental-publication]: ../../../src/perk/cli/commands/pr/submit_cmd.py#L230-L295
[validation]: pi-durable-v2.md#validation-sequence
[recovery-contract]: pi-durable-workflows.md#resuming-safely
[execution-state]: pi-durable-workflows.md#execution-identity-and-retained-evidence
[manual]: ../../Pi-Durable-Technical-Manual.pdf
[worker-results]: ../../../extension/waves/rpcAdapter.ts#L435-L446
[supplier-reuse]: ../../../.pi/npm/node_modules/pi-subagents/src/workflows/workflow-reuse.js
[supplier-package]: ../../../.pi/npm/node_modules/pi-subagents/package.json
[external-task]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/test/harness-tasks-recovery.test.ts#L59-L89
