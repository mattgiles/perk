# Perk with Pi Durable: a working vision

2026-10-05. A product vision for Perk users and maintainers. The v2 experiences below are
proposed shipping goals; they have not been implemented or demonstrated.

**Perk retains the continuity of the work: its progress, evidence, and pending decisions.**
You can begin a change, leave it, and return to an account of where it stands. Completed review
work remains useful. A question still has the context needed to answer it. An objective can
span many conversations while keeping its direction.

Imagine returning to the export feature you started yesterday. The implementation has reached
a draft PR. One reviewer found a problem with large exports; another finished without findings.
Perk shows the affected revision, the correction, and the decision waiting for you. You can
inspect the evidence, ask for a change, or take the next human delivery step. You spend your
attention on the work's quality and direction.

The first useful v2 should make that continuity ordinary for a plan, an objective, and a
learning pass. As the product matures, the same foundation could support collaboration,
comparisons between implementations, and richer learning across completed work.

For the bounded pre-v2 investment in questions, delegation, and human review behind this
experience, see [A shared decision foundation for v1 and v2](decision-foundation.md).

## The first v2: three ordinary workflows

The following stories use an illustrative application adding export support. They describe a
target experience, not an account of an actual Perk run. Here, “first v2” means a usable
integration supporting all three workflows. The [parallel-development proposal][v2] currently
ends its validation sequence at one approved node and a persisted human decision. Shipping
the experience below also requires proving objective coordination and learning continuity.

### A plan you can leave and return to

Today, a reviewed plan already survives its originating conversation. Perk provides fresh
implementation sessions, draft publication, review, and explicit delivery gates. Its
[durability boundary][current-model] includes saved plans and pushed branches; individual
components retain different amounts of execution progress.

You write a plan to add CSV export. The requirements cover selected records, stable column
ordering, and large datasets. Authoring remains read-only until approval and save. The saved
plan lives in your configured issue backend. From a Python door, you start implementation in
the prepared worktree with fresh context.

In v2, that action begins a recoverable execution associated with the approved plan. Perk
can tell you which assignment is active, which code it concerns, and whether it needs you.
The implementation worker receives the relevant plan and project guidance. Its conversation
can finish while review and subsequent decisions remain part of the same work.

Suppose the implementation reaches a draft PR and two reviewers start. One report has been
accepted when the host process stops. After the host restarts with its execution data and
workspace available, Perk checks the plan and code revisions. It retains the accepted report
for unchanged work, then recovers the outstanding assignment or explains why intervention is
needed. Review restrictions and consumed budgets continue to govern the work.

You return to a specific finding: the implementation buffers the whole export in memory.
You request a correction within the approved scope. The changed code receives the required
checks and review; the earlier report remains historical evidence, clearly associated with
the revision it assessed. A decision left open on an older revision cannot approve the new one.

Once the evidence is ready, Perk waits for your delivery judgment. You can close the view and
return to the same pending decision. Marking ready and landing remain explicit human actions.
If publication was interrupted, Perk reconciles GitHub's actual state through its existing
delivery machinery before deciding what remains to do. That [recovery discipline][publication]
already matters today and carries into v2.

The benefit is a shorter path back into the work: the relevant change, completed evidence,
and next decision are retained together. Pi Durable's [scheduler][scheduler] and
[close/reopen recovery test][task-recovery] provide a foundation for interrupted tasks. Perk
must supply the revision checks, workflow rules, and useful account you return to.

### An objective that keeps its place

Now widen the work into an objective: prepare the backend export interface, add CSV export,
and expose it in the application. Each node has a bounded plan. The interface work depends on
the earlier changes being ready under the objective's delivery rules.

Today, Perk already represents those dependencies. Its [objective supervisor][supervisor]
makes at most one safe decision per invocation and stops at planning, review, or other human
boundaries. The [operator workflow][objective-guide] describes how to interpret the result
and advance again after the boundary is resolved.

In the first-v2 experience, you admit the objective's execution within its approved scope
and budget. The coordinator retains its place while individual assignments run and decisions
remain pending. It can continue eligible, authorized work after a wait without making you
reconstruct which supervisor action comes next. You still author and approve the bounded
plans that authorize implementation.

The objective view should make three different conditions obvious: something is running,
something is waiting for your judgment, or something cannot proceed because a prerequisite
is unmet. For export support, you might see the backend node complete, CSV export awaiting
review, and interface work waiting on that change. Selecting a node reveals its plan, current
revision, evidence, and reason for waiting.

Each implementation and independent reviewer gets the appropriate fresh context. The shared
execution record carries the relationships between those conversations. You can discuss a
design question without turning that conversation into every worker's inherited history.
The objective stays coherent as the number of conversations grows.

Suppose priorities change while CSV export awaits review. You revise the remaining objective
through the backend workflow. Perk notices the changed scope and pauses affected advancement
for reconciliation and any required plan review. The old checkpoint cannot authorize expanded
work. If you cancel execution instead, Perk stops further admission, addresses active owned
work, and keeps evidence of external effects already attempted.

After you land a node and its required follow-up is reconciled, the coordinator can identify
the next eligible action. A missing plan remains a planning decision; a completed worker does
not establish a merge or finish the objective. This story uses incremental delivery to keep
the sequence clear, without redefining Perk's stacked-delivery rules.

The practical change is sustained coordination. You retain control over scope and delivery,
while Perk retains the waits, completed assignments, remaining dependencies, and reasons it
needs your attention.

### A learning pass that can use the whole record

After CSV export lands, you run the learn flow. You want future work to benefit from the
large-export problem and its correction.

Today, learning already has substantial structure. The [evidence gatherer][learn-evidence]
collects the plan, merged diff, session evidence, and existing documentation inventory, marking
missing or ambiguous sources explicitly. The [warm `/learn` workflow][learn-skill] can use
independent analysts over one shared bundle, followed by a reconciled capture or skip. The
[cold learn door][learn-door] currently needs the original local checkout because session
evidence lives there. These are existing capabilities and constraints.

In the proposed v2 flow, Perk assembles a retained evidence bundle for the landed change.
Alongside the approved plan and final diff, it can include recorded attempts, relevant
conversation evidence, accepted reviews, and decisions associated with their revisions. You
can trace the memory problem from the original assumption through the review finding to the
correction that shipped.

Fresh analysts consider what diverged from the plan, which course corrections matter, and
where an insight belongs in the existing documentation or code. They share the same evidence
and report their findings. They do not independently publish learnings. The parent learn
workflow reconciles the analysis and owns the capture-or-skip decision, preserving the
existing division of responsibility.

Suppose one analyst's result is retained before the host restarts. Returning to the learn
pass reuses that valid result for the same bundle and recovers remaining analysis where safe.
An interrupted or unavailable analysis stays visible as such. The current [analyst wave][learn-wave]
already reports skipped angles; continuity should preserve honest evidence quality rather
than turn missing analysis into an implied clean result.

The useful learning might be that this application's export paths must be tested with datasets
larger than memory. The captured record cites the evidence and identifies a documentation or
code destination. If the investigation finds nothing worth retaining, a deliberate skip is
still a successful outcome. Capture remains an issue-backend operation, and the learn cycle
closes only after verified backend success, following the existing [capture policy][learn-capture].

Later, the established docs or code factory can turn that captured insight into a reviewed
change. The future planner benefits once the curated guidance or code improvement is in place.
No durable transcript by itself becomes a new project rule.

This first-v2 goal requires a learn binding that can gather and retain Durable evidence;
the existing JSONL reader does not supply it automatically. Access still depends on retaining
the execution data and needed artifacts. The payoff is an explanation grounded in the work
across its conversations, with progress in the learning pass recoverable too.

## What carries across the change

Python doors remain a way to drive the workflow from a shell or automation. GitHub or Linear
continues to own approved plans and objectives. Git and the workspace determine code state;
GitHub determines PR, review, CI, and merge facts. Durable execution records hold assignments,
progress, and decisions under Perk policy. The [workflow companion][workflows] explains how
these responsibilities fit together.

Continuity requires an available host and retained data. Closing a client can leave execution
running; stopping its host pauses local work until recovery. Resuming elsewhere needs the
execution store and a suitable workspace. Checkpoints do not back up uncommitted files, and
cancellation cannot undo a published PR. Durable's [storage contract][storage] requires one
owning process per store and distinguishes process-crash recovery from host or power failure.

These constraints shape a useful promise: Perk should show what it retained, what it verified,
and what still needs repair. Fresh authorization checks and budget enforcement remain Perk
responsibilities after recovery; Durable's [runtime settings][settings] are not persisted.

| Experience | Current Perk | First-v2 target | Future development |
| --- | --- | --- | --- |
| A plan | Saved intent, resumable stages, component-specific recovery. | Retained execution, review progress, and pending decisions across interruption. | Several interfaces and people participate in the same work. |
| An objective | Dependency-aware supervision, one safe decision per invocation. | Coordination persists across assignments and human waits. | A shared view helps people direct several concurrent efforts. |
| Learning | Evidence gathering, analyst reports, capture/skip, and reviewed consolidation. | Retained execution evidence and recoverable learning progress. | Evidence across executions informs comparisons and future planning. |
| Collaboration | Issue/PR collaboration, remote work, and browser review already exist. | The owner can return to retained work and its decisions. | Authorized participants observe, hand off, and steer shared execution. |
| Comparing approaches | Agents and worktrees can support manually coordinated trials. | First-v2 continuity supplies a foundation for later experiments. | Approved experiments retain comparable results, costs, and selection rationale. |

## As the product matures

### A workspace people can share

Once a plan and its execution have continuity, the next opportunity is to make participation
independent of the interface you started with.

You begin an export change in the terminal. Later, a browser view shows its current evidence
and the decisions that need attention. A teammate opens the same work to assess the memory
tradeoff. They can understand the relevant revisions and findings without reading every
conversation or asking you to reconstruct yesterday's progress.

A useful shared view would answer: what changed since I last looked, which work can continue,
and which decision belongs to me? One participant might discuss a follow-up while another
reviews the current patch. Contributions would have visible authorship and scope. A stale
approval would require renewed review, and two people responding to the same request would
not advance the work twice.

This could make handoffs across schedules much easier. You leave the reasoning, evidence,
and pending decision with the work. A colleague can pick it up while you are away, within
their authority. Your return brings you to the current state rather than an abandoned view.

Durable's [conversation watches][watching] expose committed views and subsequent changes.
Perk would still need the interfaces, transport, identity, permissions, and conflicting-decision
handling that make them a collaborative product. Multiple clients would talk through the store's
owner. Neither collaboration nor moving work between machines follows from sharing a database file.

The longer-term value is a common place to direct engineering effort: inspect outcomes,
discuss tradeoffs, and contribute decisions while independent assignments continue.

### Questions that can become experiments

Suppose the next export requirement is much larger. Should exports stream through the web
application, or run as background jobs? Discussion establishes the constraints, but a small
implementation of each would reveal more about memory, responsiveness, and operational cost.

You approve a bounded experiment with a common starting revision, evaluation criteria,
resource limits, and permitted effects. Perk prepares isolated workspaces for both candidates.
Each receives the relevant requirements and checks. The comparison remains one piece of work
even though its candidates use distinct conversations and execution environments.

You could leave while the candidates run, return to one completed result, and inspect why
the other needs help. Stopping one candidate would leave the other intact. A changed requirement
would be visible in the comparison's validity, rather than quietly changing what one candidate
was asked to prove.

The final comparison would link each finding to the implementation and conditions that produced
it. Correctness, maintenance burden, measured performance, and agent expenditure could all
matter. The result might favor the simpler approach, reveal that neither is ready, or identify
a narrower question worth testing. Perk would preserve that reasoning with the evidence.

Selecting an approach would lead into the normal reviewed-plan and delivery path. The choice
would not itself publish or merge the candidate. Ordinary planning would retain its read-only
boundary; experimental implementation would have its own explicit authorization.

Durable's [conversation forks][forks] and [usage records][usage] offer useful ingredients.
Perk would supply workspace isolation, comparable measurements, budgets, and promotion rules.
A conversation fork alone cannot reproduce a filesystem. The opportunity is to make important
design questions cheaper to investigate and their answers easier to revisit.

### Learning that accumulates across work

With several export-related changes complete, a broader question becomes possible: which
assumptions repeatedly caused rework, and which interventions helped?

A mature Perk could bring together relevant evidence from those executions. One plan's
review caught buffering; another uncovered a timeout; the experiment exposed the cost of a
background worker. You could examine the differences in requirements and tested conditions,
then decide whether they support a project rule, a targeted code change, or further investigation.

This would extend an existing loop. Perk already has [docs and code consolidation][learn-docs]
and [harvest][learn-harvest] workflows for turning captured or curated learning into proposed
work. The new opportunity is a richer body of execution evidence: accepted and rejected
approaches, actual corrections, review coverage, and outcomes tied to specific changes.

Future planning could use that record to surface a relevant earlier experiment and the
conditions under which its conclusion held. A maintainer could challenge a recommendation,
inspect its source, and retire it when the code or circumstances change. Fresh agents could
receive the curated guidance relevant to their assignment, with links back to supporting evidence.

That requires deliberate retention, retrieval, comparison, and curation. A repeated model
assertion is not independent evidence, and an old result may no longer apply. Suggestions
would remain proposals until adopted through the appropriate workflow. The system's usefulness
would come from making well-supported lessons available when they affect a decision.

Together, these possibilities give the initial workflows room to grow. A recoverable plan
becomes shared work; a durable objective can coordinate investigations; an evidence-backed
learn pass can inform the next objective. Each expansion should improve the quality or ease
of real engineering decisions.

## Reading the proposal

For the strategic choices and evidence assessment, read [Pi in the sky][strategy]. For Python
doors, state authority, and the worked old/new flow, read [How a durable perk would work][workflows].
For developing and proving the integration alongside the current runtime, read
[A parallel path to Pi Durable][v2]. This vision adds the intended user experience, including
the objective and learning acceptance work needed beyond that memo's initial proofs.

Current-behavior observations use Perk `91719e4933389fece395cd570d0b8a0f7506b7b8`; upstream
citations pin Pi `b7dfc049e917a265a5aefa9f3952a2dec9b81cfd`. Official documentation describes
mechanisms, linked source identifies inspected implementations, and the linked recovery test
was read rather than run. The stories and future capabilities are product proposals. This
document introduces no command syntax, deployment decision, or runtime implementation.

[strategy]: pi-in-the-sky.md
[workflows]: pi-durable-workflows.md
[v2]: pi-durable-v2.md#four-validation-stages
[current-model]: ../../user-docs/explanation/how-perk-thinks.md#where-the-truth-lives-the-state-tiers
[publication]: ../../../src/perk/delivery/publish.py#L879-L925
[supervisor]: ../../../src/perk/cli/commands/objective/run_cmd.py#L1-L8
[objective-guide]: ../../user-docs/how-to/advance-an-objective-headlessly.md
[learn-evidence]: ../../../src/perk/learn/evidence.py#L1-L22
[learn-skill]: ../../../skills/perk-learn/SKILL.md
[learn-door]: ../../user-docs/reference/cli/learn-and-gist.md#perk-learn
[learn-wave]: ../../../extension/learning/analystWave.ts#L247-L285
[learn-capture]: ../../../extension/learning/capture.ts
[learn-docs]: ../../user-docs/reference/cli/learn-and-gist.md#perk-learn-docs
[learn-harvest]: ../../user-docs/reference/cli/learn-and-gist.md#perk-learn-harvest
[scheduler]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/src/harness/scheduler.ts#L238-L255
[task-recovery]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/test/harness-tasks-recovery.test.ts#L111-L144
[storage]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/README.md#storage
[settings]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/README.md#settings
[watching]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/README.md#watching-a-conversation
[forks]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/README.md#more-conversations-and-forks
[usage]: https://github.com/earendil-works/pi/blob/b7dfc049e917a265a5aefa9f3952a2dec9b81cfd/packages/durable/README.md#usage-and-cost
