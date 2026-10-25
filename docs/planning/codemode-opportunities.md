# Code Mode opportunities for perk

2026-10-24. A product and architecture proposal for perk maintainers, grounded in perk
4.1.0 at `730983750157be17920b80cced3050bae53ed75c` and the installed Pi 1.4.0 SDK.
This document proposes future behavior; it changes no runtime or shared contract.

## Recommendation

**Make perk programmable: give Code Mode typed access to agents, workflow operations,
evidence, checks, and decisions.** Let a model compose those capabilities into a useful
program without having to become the message bus between every step.

The largest opportunity is agents as callable functions. A program could investigate several
questions, use the results to choose a deeper investigation, run an experiment, and return
the evidence needed for a decision. The parent model would spend its attention on that
decision. Today, much of the information needed to coordinate this work either crosses the
parent's context or sits behind a flow-specific entrypoint that a script cannot call.

Build that foundation into real workflows. The first should prepare an adaptive investigation
and review. Follow it with a repair-and-verification workflow. Then enable competing
implementation experiments during planning and sustained objective execution. These are two
horizons: a useful programmable core on the current runtime, followed by larger changes to
workspace authority and execution lifetime.

This requires changing existing contracts. The automatic association between orchestration
and model-only exposure should go. Actions should have structured results. Workflow completion
should be separable from ending the outer agent turn. A planning session should be able to
commission an explicitly authorized experiment in an isolated workspace. These are substantive
changes worth considering, even where current policy deliberately forbids them.

Judge the replacement by what it enables and what it removes. A successful redesign should
retire prompt choreography, duplicated adapters, and unnecessary context transfers. Adding a
second programming interface over all the same obligations would be a weak outcome.

## Evidence and the product goals

The three external sources establish different parts of the case:

- [Pi's Code Mode reference][pi-codemode] establishes the available mechanism: sandboxed
  JavaScript composes tools and selectively emits results. Tool discovery, output schemas,
  classifiers, and images are available building blocks. The installed SDK's declarations and
  implementation were inspected alongside the reference.
- [Ronacher's explanation][ronacher] places composition on the harness side of the execution
  boundary. This matters when combining native tools, model services, and agent execution that
  shell scripts cannot naturally reach. His discussion also identifies inconsistent result
  shapes and durability as unresolved concerns.
- [Cloudflare's article][cloudflare] makes the case for presenting tool capabilities as a
  programming interface and keeping intermediate transfers outside model context. Its Worker
  implementation is architectural prior art; perk already has a native execution mechanism.

Those sources motivate a hypothesis, rather than establish a measured improvement in perk.
No live model benchmark, repair campaign, or interrupted objective execution was run for this
assessment. The recommendations below are architectural judgments with proposed experiments.

Perk's learned corpus gives the proposal its purpose:

| Product goal or lesson | Consequence for Code Mode |
| --- | --- |
| [Route data instead of relaying it][delegation-principles]. Fresh contexts provide isolation and distinct capabilities. | Pass subjects and artifact references into callable agents; keep their large intermediate results outside the coordinator's model context. |
| [Wave mechanics moved into code for concrete reasons][wave-learnings]. Models previously had to reproduce schemas, launch procedures, and collection protocols. | Scripts should call operations that own those responsibilities. Making the model reconstruct raw engine protocols would repeat a known failure. |
| [Planning-time facts decay][facts-decay]. A saved plan can outlive the code and assumptions it inspected. | Make premises and acceptance evidence recheckable across the plan lifecycle. |
| [Objectives coordinate bounded plans][objective-learnings], while [delivery owns its operation and recovery semantics][delivery-learnings]. | Compose work at these semantic boundaries; make continuation more capable without duplicating delivery rules in generated scripts. |
| [Learning reconstructs what actually happened][learn-evidence]. Missing evidence and uncertain linkage matter. | Keep provenance and coverage through reductions; let learning consume execution outcomes as well as conversations. |

These are reasons for the proposed design. The exact current stage matrix, tool names,
child profiles, and placement of guard state are implementation choices that can change.

## Today's system: what it does, and why

The [shared contracts][contracts] remain the behavioral baseline. Older learned records and
planning proposals explain intent, but current code decides what has already landed. For
example, the earlier [structured-output memo][structured-memo] proposed preparing the review
classifier's evidence in the parent; that preparation is implemented today.

| Current owner and path | Current behavior | Why it exists |
| --- | --- | --- |
| Python doors, issue backends, GitHub gateway, and delivery operations | Position worktrees, launch sessions, and perform canonical backend/Git effects. Native tools frequently call Python workers through the cold-door seam. | Work spans processes and machines; one authoritative operation must interpret effects and recovery. This is already a mixed implementation, rather than a ban on Python inside a live workflow. |
| [Tool registration][perk-tool] and [tool policy][tool-policy], contracts §8.40 | Queries declare structured result schemas. Terminal, interactive, orchestration, host, and bounded-writer tools become model-only. Under the read-only gate, nested perk calls admit eligible queries. | Prevent nested execution from escaping a gate, stranding a writer, or confusing session control with an ordinary function result. |
| Code Mode lift, contracts §8.40 | A user-enabled Code Mode survives in registry read-only stages under the documented mode/cohort conditions. Perk does not enable it universally. `objective_stack_status` is the sole catalogued perk query in this snapshot. | Preserve useful read composition while the rest of the callable interface remains intentionally narrow. |
| [ReportWave][report-wave] over [its transport][wave-transport] | Owns assignment validation, start/collect/run, completeness, receipts, cancellation handling, and transport selection. It renders a short pi-subagents workflow script. | Remove engine mechanics from model-authored instructions and centralize trustworthy collection. The system already uses programmatic fan-out below the model-facing layer. |
| Flow mechanisms and Pi installers | Review, scout, exploration, classification, and learning entrypoints choose report schemas, assignment policy, model configuration, and result rendering. | The shared engine does not know each feature's subject, required coverage, or interpretation of a report. |
| [Review classification][classifier] and [address binding][address-binding] | Code fetches a feedback snapshot, selects unresolved threads and discussion comments, and binds the child's judgments to exactly those IDs. Anchors and totals come from the snapshot. Finalization publishes before resolving held threads. | A model must not invent a PR, thread identity, anchor, total, or evidence of successful publication. |
| [Automated review][automated-review] | Holds a per-activation, single-use review pass and a code-derived minimum verdict. The post path refuses a clean result over actionable findings or incomplete coverage. | Concise prose must not erase required work or turn an incomplete review into a clean one. Current binding is to PR identity, not an immutable head SHA. |
| [Plan review][plan-review] and [approval/save gate][approval-gate] | Review distinguishes approval, denial, dismissal, edits, abort, and unavailable UI. Successful save precedes gate release; effective access is observed. | Human intent concerns particular reviewed content and a destination. A failed save or held gate release cannot count as completed approval-to-implementation. |
| [Configured CI runner][ci-runner] | Runs configured checks concurrently, preserves complete output in scratch, and returns bounded output plus machine details. Its adapter owns command trust. | Checks are deterministic mechanics. They need no agent to schedule them, and arbitrary model-authored commands must not acquire configured-CI trust. |
| [Headless stage execution][stage-execution] and [model-call policy][model-policy], contracts §8.11 | Drives implement/address to a domain terminal signal. The worker's Code Mode disables `models`; its token accounting observes turn/compaction boundaries and excludes separate report-child sessions. | An idle model is not proof of stage completion. Nested model usage is unavailable mid-script, and current accounting cannot enforce a whole campaign budget across children. |
| [Objective supervisor][objective-run], contracts §8.20/§8.37 | Makes one deterministic dispatch decision per invocation. It does not author plans or land work. | These paths have explicit execution and human-decision boundaries; a supervisor cannot assume capabilities that the stage runner lacks. |
| [Learn evidence][evidence-core] and [dream analysis][dream-analysis] | Gather linked evidence and manifests. Dream orders analysts, bounded bundle creation, reducers, and revalidation before accepting a complete outcome. | Completeness, source currency, and artifact identity are semantic facts, rather than presentation details. |

The important distinction is between a reason and its present mechanism. Report identity needs
an owner; that owner need not always be an activation-local holder. A stage needs a completion
criterion; completing an operation need not terminate the calling script. A planning checkout
can remain protected while a separate, authorized workspace permits experimental writes.

## The proposed programmable core

### Operations return outcomes; adapters control conversations

Expose a discoverable perk namespace through Pi's native tool namespace and deferred-tool
mechanisms. Give useful operations structured outputs whether they read, mutate, launch an
agent, or request a decision. Queries remain useful, but they should not monopolize the
machine interface.

Separate an operation's meaning from its presentation. Publishing a change returns an account
of publication. Finalizing review feedback returns the publication and resolution outcome.
Requesting plan review returns a decision or a pending request. A direct model-facing wrapper
can still stop the outer turn when appropriate. A script-facing caller can inspect the same
domain outcome and continue within its authority.

This is a direct change to `registerPerkTool` policy and §8.40, not something native discovery
can accomplish by itself. Initially expose existing feature operations behind the new result
contract. As callers migrate, remove wrappers whose only remaining purpose is translating the
same operation into another tool-specific protocol. Keep substantive feature operations such
as address finalization and delivery recovery; their effect ordering is useful API behavior.

The namespace should describe semantic capabilities, rather than mirror every CLI subcommand.
Native declarations can carry the argument/result schemas. There is no need for a perk MCP
server, a new sandbox, or a generated SDK to start this work.

### Agents become callable capabilities

An agent call should accept a bounded assignment and return a typed outcome containing the
validated report, coverage, execution identity, artifact references, and observed usage.
The capability owns profile/model resolution, workspace placement, child restrictions,
cancellation, and collection. Programs can pass returned data or references into subsequent
calls without first printing it for the parent model.

Start with ReportWave as the implementation beneath this interface. It already owns much of
the difficult behavior. Its module-private generated workflow script is different from Pi's
Code Mode: enabling Code Mode does not remove that transport. A later engine replacement can
remove the script/RPC/aggregate machinery once it supplies the required behavior. The
[current supplier assessment][supplier-assessment] explains why ordinary native parallel calls
do not yet replace per-assignment schemas, identities, and restriction delivery.

This also creates a better place for model tiering. Use ordinary code for deterministic
selection, a classifier for bounded labels or scores, a small reasoning agent for summaries,
and a stronger agent for investigation or design. Pi's classifier answers do not directly
provide the free-form summaries required by today's review-classifier report. Replacing that
child requires a deliberate output and quality decision, not an API-name substitution.

### Replace blanket exclusions with scoped operation authority

Today's nested gate and constant read-only report-child floor are understandable protections
for the existing surface. The proposed interface should authorize the operation and its
resources: an investigation may read a subject; a repair may write its assigned workspace;
an experiment may create disposable results; publication needs its relevant authorization.

This would revise the [child execution policy][child-policy] and contracts §8.3/§8.40. It is
especially valuable during planning: the coordinator could remain unable to change the main
checkout while commissioning a bounded experiment elsewhere. Merely creating a git worktree
does not constrain a shell process; enforcing that scope requires an execution boundary or
launcher appropriate to the promised isolation. A path in a tool argument is insufficient.

The operation implementation must bind subject and permission. A script-supplied field saying
"approved" cannot establish approval. Conversely, an explicitly delegated repair or experiment
should not need another confirmation at every mechanical step. The program should make full
use of the authority already granted to the work.

### Human decisions become composable outcomes

Review and questions need values that distinguish answered, denied, cancelled, unavailable,
and pending. They also need the reviewed subject/revision and the actor or delegated policy.
The existing review outcome types and source-sensitive save checks are useful starting points.
The [decision-foundation proposal][decision-foundation] maps current consumers and why a UI
callback alone cannot establish decision identity or truthful attribution.

A near-term bounded workflow can request review and return its outcome. A longer workflow
should retain a pending decision and release execution resources. Replying later should wake
the owning execution, revalidate the subject, and admit the authorized continuation. It should
not hold a Code Mode worker open while a person is away.

This allows review, implementation, and publication to participate in programs while retaining
meaningful human involvement. Broader delegated approval could be a later policy capability;
it requires explicit scope and its own evidence standard. Today's model-only enum should not
be the permanent way of expressing that product decision.

### Programs and durable execution have different lifetimes

Use native Code Mode for bounded composition. A coordinator can observe current work, launch
authorized jobs, transform completed outcomes, request a decision, and return a compact result.
Persist subjects, accepted results, and effect receipts through application operations.

Longer objective execution needs a host that owns scheduling, waits, recovery, and operation
identity. The [Pi Durable vision][durable-vision] and [parallel integration proposal][durable-v2]
already investigate that direction. Code Mode provides a programmable interface to such an
executor; enabling it does not create the executor. An ad hoc generated script has no automatic
restart at its last `await`.

An execution should record which recipe revision and inputs it admitted. Recovery reuses or
reconciles recorded operations under that revision and current authorization. It must not ask
a fresh model to silently regenerate the supposedly same program. Pi's small session store
is useful working state, but it is not a canonical objective ledger or a transaction around
external effects.

### Executable recipes replace mechanical instructions

Use ordinary JavaScript for composition. A skill can supply a short, versioned recipe together
with guidance about when to use it and where judgment is needed. Teams could customize a review
campaign or investigation without implementing another full Pi extension.

Perk-owned standard workflows can be ordinary tested application functions over the same
capabilities. They need not send fixed code through a VM on every invocation. Model-authored
composition uses Code Mode's sandbox. Both should reach the same semantic operations.

Start by shipping a few useful recipes with existing skill/package delivery. Build file-backed
recipe execution or overrides only when a working caller needs them. Avoid inventing another
workflow language, plugin registry, or universal dispatcher as the entry fee for composition.

## What should be rewritten or rerouted

The migration unit is a working capability and its callers. These are proposed cuts through
the current system, rather than promises that every listed module can be deleted wholesale.

| Current mechanism | Proposed replacement and responsibility transfer | Expected removal | Contract and evidence required |
| --- | --- | --- | --- |
| Query-only result schemas; kind-derived model-only exposure | Typed outcomes for semantic operations; explicit script reachability and operation authorization. Root-turn control moves to adapters. | The rule that every orchestration or interactive tool is uncallable from scripts; text parsing for successful actions. | Amend §8.40 and the result/exposure policy. Prove nested success, soft failure, cancellation, stage authority, and direct/script outcome equivalence. |
| Flow-specific agent launch/install/render paths | A callable agent/job interface over the existing execution owner; feature code supplies meaningful assignments and acceptance policy. | Repeated transport adaptation, model resolution, and prose-only report transfers where the shared interface subsumes them. | Preserve assignment identity, schemas, requested coverage, child policy, partial outcomes, and cancellation. Delete an adapter only after its behavior has a replacement owner. |
| Parent-mediated scout/explorer sequences | Programs compose typed investigations, inspect unanswered questions, and launch the next bounded assignment. | Repeated parent turns used to relay results or calculate follow-up inputs. | Extend §8.70 and relevant stage policies. Prove dependent investigation without losing uncovered questions. |
| `/address` classification → parent fixes → terminal finalizer | Programs can compose snapshot-bound classification, repair jobs, CI, review, and the existing finalization operation. | Mechanical prompt sequencing and data re-entry. The snapshot binder and publish-before-resolve semantics remain operation responsibilities. | Amend §8.4/§8.40 and worker-facing behavior as needed. Retain exact subject membership and truthful partial resolution. |
| Review-wave collection and activation-local post holders | Accepted review results referenced by the post operation; atomic admission/consumption where calls may overlap. | Model-visible report relaying and, with retained execution, activation-local ownership that prevents recovery. | Preserve minimum verdict and coverage policy. Current sequential post assumptions must be replaced before concurrent script calls are allowed. |
| Terminal review/save tools coupling operation completion to turn completion | A decision/save operation plus a direct adapter's continuation decision. Retained decisions add an execution-owned pending state. | The assumption that every successful workflow operation ends the model turn. | Amend §8.23/§8.41 and §8.11 where worker terminal semantics change. Prove reviewed bytes/destination, save outcomes, and effective gate release. |
| Learning analysts/reducers behind fixed entrypoints | Shared evidence capabilities and typed agent calls composed into standard or adaptive analysis recipes. | Repeated installer plumbing and unnecessary intermediate context; fixed routing where adaptive investigation proves better. | Preserve §8.35 and dream's §8.59–§8.65 coverage, bundle, currency, and publication conditions. |
| Raw/capped CI text read by the parent | Programs consume check outcomes and selected diagnostic evidence; the existing configured-check operation runs checks. | Full failure-log relaying and repeated parsing. CI already runs in parallel; Code Mode adds no scheduling win there. | Preserve trust, complete-output references, skips, and run-all semantics. Do not repeat a green CI run merely to obtain a different presentation. |
| One-dispatch objective supervisor | Sustained execution over typed plan/stage/decision operations; Python doors admit or inspect that execution. | Repeated manual re-entry between eligible steps and eventually redundant supervisor/worker coordination. | Deliberately extend §8.20/§8.11/§8.38. Prove multi-node coordination and recovery before retiring the old path. |
| Worker refusal of script classifier/image calls | An accounted model-call capability with per-call admission, execution limits, usage receipts, and clear unsupported cases. | The blanket restriction once replacement budgeting is demonstrated. | Revise §8.11. Current nested usage arrives too late for its watchdog; a new interface must state what it actually bounds. |

### Worked mapping: an address campaign

Today, the address binding fetches feedback through the canonical worker and builds a prepared
snapshot. It sends exactly the selected subjects to the classifier child. Code binds the
returned classifications to that snapshot and holds them in the activation. The parent model
reads the compact classification, edits the checkout, and eventually calls `finalize_address`.
The [feature operation][address-feature] publishes fixes, then resolves only held threads on
the held PR, reporting partial or unknown effects accurately.

The proposed campaign exposes that bound classification as data to a program. A repair
assignment receives its subject by reference; an implementation agent returns the resulting
change. The program can feed that change to configured checks and independent review without
printing every intermediate result. Finalization still invokes the canonical publication and
resolution operation. Ending the enclosing turn becomes an adapter choice.

Delegated repair deliberately changes today's address guidance, which says that judgment and
edits stay with the parent and the fix is never delegated. It also needs a new completion
profile. The current implement worker succeeds after publication; it cannot serve as a
patch-producing repair agent unchanged. The first repair capability must produce a change
without publishing it, either through a bounded agent profile or an explicitly split worker
operation. Its instructions, accepted output, and publication authority must agree.

This transfers coordination into a program. It does not transfer subject binding, publication
ordering, or interpretation of remote effects into model-authored JavaScript. Parallel repairs
need separate workspaces or serialization, followed by an integration step and verification
of the combined change. A report about a patch is not proof that the patch was integrated.

For a first bounded implementation, keep the classification/post record activation-owned and
complete one campaign within that lifetime. Retained campaigns require moving that ownership
into execution state. Do not describe the first implementation as restartable merely because
its inputs have references.

## Second-order effects that determine the design

### Concurrency changes the meaning of a review pass

Today, `ClassificationHolder.current` holds one bound classification per activation. A new
classification clears it before fetching. Automated review similarly moves its single holder
to pending before resolving the new target, invalidating an earlier pass even if the new
attempt fails. `publishAutomatedReview` consumes the recorded pass after successful publication;
its check-and-consume sequence assumes sequential calls. A null holder also permits the
backwards-compatible standalone post path. These are specific behaviors, not one universal
rule requiring a wave before every post.

Making the tools callable inside `Promise.all` can overwrite a classification or permit two
publishers to pass the same precondition. Replacing one holder with a map of retained reports
creates a different problem: an older report may become postable after a newer attempt was
intended to invalidate it. Persistence alone does not preserve recency policy.

Initially serialize these feature transitions at their operation boundary while allowing
independent investigations to overlap. A retained design needs campaign/subject-bound records,
atomic consumption, and an explicit current-attempt policy. Test the older-complete/newer-failed
case as well as duplicate posting. Requiring review evidence on a newly defined campaign path
would be an intentional policy change; describe it separately from existing standalone posting.

A retained pass also needs its semantic state. Today's durable `last_pr_review` record and
attempt receipts do not carry the private minimum-verdict floor. Saving those existing records
would not by itself preserve posting eligibility. Retain the floor or reconstruct it from the
validated effective reports under the recorded policy.

Even read composition needs attention to shared effects. The [stack-status query][stack-status]
can fetch remote-tracking refs, while [objective engagement gathering][engagement-learnings]
can repeat backend scans. Parallel calls can contend or multiply network work. A coherent
observation or domain batch can share a fetch; Code Mode alone cannot turn these operations
into independent, free reads.

### A program can outlive the authority under which it started

Current read-write stage diets primarily shape presentation; the read-only gate supplies the
call-time backstop. A hidden or deferred declaration is not an authorization mechanism. A
script can also await a review while the session changes mode, the objective is revised, or
another caller supersedes the subject.

Therefore, broad script reachability needs a stronger operation boundary than tool visibility.
Check the current admitted subject and permission when an effect is admitted, and recheck
where an operation's semantics require it before committing that effect. Separate root-session
mode from a job's authorized workspace: completion of one child must not release the
coordinator's gate or authorize its siblings. Revocation can stop further admission, but does
not undo effects already performed. This is additional responsibility acquired by a more
programmable interface, and it must appear in the simplification accounting.

### Function completion can stop proving stage completion

The [result seam][result-seam] and Pi's script conversion already make a consequential
distinction: an action's soft failure normally rejects its script call, whereas a query with
an output schema can resolve a structured `ok: false` result. Adding output schemas to actions
therefore changes existing script error behavior. Choose a consistent new contract: domain
refusals and partial effects return typed outcomes; execution/transport failures remain
explicit failures. Migrate callers accordingly. A result schema describes shape; validation
and subject binding still need their existing owners.

`applyStageEvent` in the stage worker records details from tools named `submit` and
`finalize_address`. Its terminal classifier combines those details with domain evidence;
address additionally requires the review-batch record and successful publication evidence.
It does not accept a generic successful tool result as stage completion.

Factoring publication into a newly named script-callable operation can therefore perform the
right GitHub effect yet leave the worker unable to recognize success. Ending a Code Mode
script also says nothing about whether its workflow succeeded: structured refusal can be a
normal returned value. The replacement must give the stage owner authoritative completion
evidence bound to its job, through an operation outcome or event it actually consumes. Update
the worker classifier and event mapping together. Do not substitute arbitrary script output
or an agent's claim of completion for the current domain predicate.

### Writable experiments affect more than their directory

Current report children share the caller checkout safely only within their read-only policy.
A writable experimental child changes that premise. Git worktrees share repository state;
jobs can also share dependency caches, inherited credentials, setup hooks, and main-checkout
workflow storage. The learned evidence pipeline already records a historical failure in which
children inherited a run ID and overwrote the parent's session pointer.

An experiment needs deliberate job/run identity, artifact ownership, and a profile that cannot
impersonate an implementation of the approved plan. State what is shared and what is isolated.
Prevent experimental results from updating canonical plan progress until explicitly adopted.
Preserve enough environment and fixture information for a comparison to be meaningful.
Cleanup must not erase a failed candidate's evidence or kill another job's resources.

Filesystem write authority also differs from permission to execute repository code or publish
through inherited credentials. For example, a foreign-PR review must not acquire test-execution
authority just by entering an experiment recipe. The isolation/credential design is a real part
of this capability's cost, beyond creating worktrees.

### Nested programs can multiply cost and occupy the execution pool

Today's worker token budget excludes separate report children. A generated loop over callable
agents could launch expensive work without the parent spending many tokens or ending its turn.
Per-call caps are insufficient if the program may create arbitrarily many calls. Limits must
cover the owning campaign and its descendants as well as individual jobs.

There is also a scheduling consequence. Pi limits Code Mode workers across sessions in one
process. A parent script awaiting a child that needs the same saturated pool can starve useful
work. Today's background report processes have separate process-local pools; this becomes a
particular concern if an executor moves children in-process. Keeping a human decision open in
a VM is another way to occupy scarce capacity without useful computation.

Use bounded calls for immediate work and execution-owned jobs for longer lifetimes. Yield
pending coordination instead of holding a VM indefinitely. Test queueing, cancellation before
start, and aggregate admission; raising the worker count alone is not an ownership design.

### Durable reuse can preserve the wrong evidence

The current wave transport adds a fresh launch token because engine reuse after reload could
otherwise present an earlier inspection as a new one. Retaining accepted results for recovery
is valuable, but conflicts with the meaning of an explicitly new review if reuse becomes
automatic.

Distinguish resume from new inspection. Reuse must satisfy the assignment's actual subject,
recipe, policy, and freshness contract. Today's automated review is PR-bound, not generally
head-bound; adding a head/revision requirement would strengthen and change that contract.
Decide that per operation rather than implying the existing system already guarantees it.
Delivery effects need their own existing journal/read-back reconciliation, independent of
whether the analysis result was reusable. A completed program or restored store entry does
not make external effects transactional.

### Selective output changes what the human and parent can notice

The parent can lose useful disagreement when a program returns only top-ranked findings.
Classifier-driven routing can repeatedly exclude unusual failures, while overlapping analysts
can make one source appear to supply several independent confirmations. A smaller transcript
can look more decisive while containing less reliable evidence.

Retain requested subjects, routing decisions, omitted counts, failures, and inspectable source
references. Evaluate low-priority and disagreement cases, not just obvious actionable examples.
Keep reduction policy visible through the existing report/evidence surfaces; a new dashboard
is not required. Treat fetched text and agent outputs as data, including when they contain code.
Promoting a discovered snippet into an executable recipe is a separate trust decision. The
operation API should accept structured inputs so callers need not assemble shell commands
from untrusted report fields.

### The migration reaches prompts, packaging, and configuration

Retiring a launcher does not retire its semantics. Agent definitions currently own rubrics and
completion instructions; code owns schemas and coverage; stage guidance names tools; model
selection uses a fixed configuration vocabulary. A generic agent API can accidentally bypass
configured models or omit a required reviewer even if its transport works perfectly.

Map each migrated caller through its feature operation, agent profile, model selection,
guidance/skill carrier, result schema, and tests. Amend the stage/tool matrix and the §8.57
prompt carriers with the new contract. Defaults and discovery also affect user behavior:
native user/project modifier merging means a project seed can override a global negative.
Document the project opt-out and test resolved choices. A smaller declaration set that makes
the intended capability hard to discover is not a product improvement.

Saved recipes add a compatibility obligation that disposable instructions had less of. Record
their API/recipe revision and refuse an unsupported recovered program with an actionable
migration path. Do not silently reinterpret its calls under a changed contract. Breaking an
interface can be the right simplification, but the retirement plan must account for admitted
executions and stored recipes as well as the currently shipped command.

## Flagship opportunities

All `tools.perk_*` examples below are **illustrative proposed APIs**, not callable tools today.
Their names and fields show the intended interaction; they are not settled wire contracts.
Caller-provided references identify work; authority comes from the host's admitted scope,
not possession of a reference. Each capability must return complete, partial, failed, or
pending outcomes according to its domain.

### 1. Review-to-repair campaigns

**Experience:** "Take this feedback through investigation, repairs, checks, and independent
review. Bring me the resulting change and any decisions that remain."

Today, classification and finalization have strong semantics, but the parent coordinates the
work between them. Automated review has its own wave, required coverage, and posting state.
A campaign could use these capabilities together and adapt its investigation to the findings.
For example, a suspected authorization bug earns a focused investigation before repair;
independent documentation issues can be handled separately.

```js
// Proposed bounded campaign; no operation here exists under these names today.
const feedback = await tools.perk_feedback_classify({ subject });
if (!feedback.ok) return feedback;
const repair = await tools.perk_agent_run({
  role: "repair", subject: feedback.snapshot,
});
if (!repair.ok) return repair;
const checks = await tools.perk_checks_run({ subject: repair.change });
if (!checks.ok || !checks.passed) return { repair, checks };
return tools.perk_review_prepare({
  subject: repair.change, evidence: checks.receipt,
});
```

Code Mode's advantage is flexible coordination over returned values: branching, routing, and
feeding evidence to the next capability without another parent-model pass. An ordinary compiled
function remains a good implementation of the standard campaign. The programmable API lets a
model or team vary the investigation without creating a new shipped flow tool for each variant.

**First experiment:** expose an investigation/review-preparation path with typed agent results.
Then run one repair in an approved workspace through CI and review handoff. Compare with the
current address/review flow on the same feedback. Retain every item in the coverage denominator;
a cheap classifier may prioritize work, but cannot silently discard inconvenient findings.

The initial benefit is fewer coordination turns and a coherent evidence packet. Later versions
can continue into authorized publication and resolution. Compare native classifier labels plus
targeted summarization against the existing classifier child before replacing that child.

### 2. Competing approaches while planning

**Experience:** "Before we commit to this migration, try the streaming and batching approaches
against the same workload. Show correctness, resource use, and the resulting patches."

Today's report children are structurally read-only in the caller checkout. Write-capable
foreground children serve specific purposes, such as conflict resolution and library curation.
There is no general planning experiment capability. The proposed change is explicit:
planning can commission bounded write-capable jobs in isolated experimental workspaces.

```js
// Proposed API; both experiments share a reviewed question and comparison basis.
const approaches = ["streaming", "batching"];
const runs = await Promise.allSettled(approaches.map((approach) =>
  tools.perk_experiment_run({ subject: experiment, approach })
));
return runs.map((run, i) => ({
  approach: approaches[i],
  ...(run.status === "fulfilled"
    ? { outcome: run.value }
    : { failed: String(run.reason) }),
}));
```

The experiment operation owns workspace creation, starting revision, allowed resources,
execution limits, test procedure, and artifact retention. Approaches are compared against the
same acceptance basis. A failed experiment remains in the comparison. The final design choice
can consider clarity and compatibility as well as test and benchmark results.

Code Mode makes multi-arm experiments cheap to express and easy to adapt after an initial
result. The new experiment execution capability supplies the substantive ability to do the work.
Both parts are needed. This could change planning from code inspection followed by predictions
into code inspection plus empirical design evidence.

**First experiment:** one approved performance/design question, two disposable workspaces,
one fixed fixture, and independent inspection of both resulting changes. Demonstrate the
promised filesystem/network boundary, cancellation behavior, and retained results before
making this an unattended planning feature. Adopt a candidate through the normal reviewed
change path; experimental success does not itself publish a production change.

### 3. Objectives that keep advancing

**Experience:** "Advance the approved export objective within this scope and budget. Work on
independent nodes together. Wait when a plan or delivery decision needs me, and keep your place."

The current supervisor selects one dispatch and stops. The stage worker supports implement and
address; authoring and human decisions need different execution paths. The proposed coordinator
must acquire those capabilities and retain their outcomes. Wrapping `perk objective run` in a
JavaScript loop would not supply them.

A bounded Code Mode step could coordinate an authoritative observation of ready work:

```js
// Proposed executor integration: one coordination step, not a persistent VM loop.
const observation = await tools.perk_execution_observe({ execution });
if (!observation.ok) return observation;
const launches = await Promise.allSettled(observation.ready.map((step) =>
  tools.perk_job_start({ step: step.ref })
));
return tools.perk_execution_yield({
  observation: observation.ref, launches: launches.map((launch) =>
    launch.status === "fulfilled"
      ? { outcome: launch.value }
      : { failed: String(launch.reason) }
  ),
});
```

The executor owns job lifetimes and subsequent wakes. Admission revalidates the observed step;
an old ready-work snapshot cannot force a stale launch. Programs can express coordination
strategy and combine multiple objectives, while domain operations decide current eligibility.
Planning, refinement, implementation, review, and learning become explicit work with distinct
contexts and outcomes. Human decisions remain visible work states.

This is the largest horizon-two investment. Durable execution is valuable independently of
Code Mode. Code Mode's contribution is a programmable coordination surface over it, through
which a team can express strategies without reproducing engine protocols or adding another
bespoke top-level workflow.

**First experiment:** execute two independent approved nodes, retain one completed result across
an interruption, and continue into a pending human decision. Then change the objective before
resumption. The coordinator must explain what remains usable and what requires reconciliation.
Use the existing Durable proposals to evaluate an executor instead of building a JavaScript
checkpoint engine inside perk.

### 4. Plans with executable assumptions and acceptance evidence

**Experience:** "Is this saved plan still sound? Which assumptions changed, and what evidence
would make its implementation acceptable now?"

The [fact-decay lessons][facts-decay] describe repeated failures of stale module locations,
counts, interfaces, and dependency assumptions. Existing objective doctor and delivery status
diagnose defined state drift; they do not generally re-evaluate a plan's substantive premises.
Review and CI provide evidence, but there is no general per-claim account across the lifecycle.

Let plans carry references to meaningful assumptions and acceptance claims. Programs can rerun
their checks, join findings to changed code and human engagement, and commission investigation
where observation is insufficient. Deterministic assertions and model judgments must remain
distinguishable. Free-form requirements need not be converted into a rigid plan language.

```js
// Proposed API; claim checks produce evidence, not automatic plan approval.
const basis = await tools.perk_plan_evidence({ subject: plan });
if (!basis.ok) return basis;
const checks = await Promise.allSettled(basis.claims.map((claim) =>
  tools.perk_claim_check({ claim: claim.ref, revision: basis.revision })
));
return checks.map((check, i) => ({
  claim: basis.claims[i].ref,
  ...(check.status === "fulfilled"
    ? { outcome: check.value }
    : { unknown: String(check.reason) }),
}));
```

Code Mode enables custom combinations of repository, contract, backend, and test evidence
without a hard-coded feature for every question. A model can ask for the failing premises and
their sources rather than ingesting every successful check. A dedicated compiled checker is
still preferable for an invariant repeated across all plans.

**First experiment:** annotate a saved plan with a small set of real premises and acceptance
claims. Change one relevant interface and one irrelevant file. Produce the correct affected
claims, source references, and unknowns, then feed the result into the existing refinement or
replan workflow. Start with an attached evidence artifact before proposing a plan schema change.

### 5. Learning across many changes

**Experience:** "What keeps causing us to rework this subsystem? Connect the plans, review
findings, abandoned approaches, incidents, and existing learnings. Propose the most useful fix."

Today, `/learn` gathers a plan's linked sessions and change evidence. Harvest identifies
improvements from learned docs; dream analyzes and cross-examines the corpus. Those are
substantial existing analysis pipelines. Their manifests and typed reports should become
capabilities for programs, rather than being replaced by ad hoc filesystem scans.

The new capability is analysis across cohorts of work and sources. Code can join identities,
group repeated symptoms, and inspect coverage. Classifiers can supply advisory routing labels.
Fresh analysts investigate each candidate pattern; stronger reasoning reconciles causes and
chooses the proposal. The output can be a gist, bounded objective, or explicit conclusion
that the evidence is insufficient.

```js
// Proposed API; a cohort is gathered by feature-owned evidence readers.
const cohort = await tools.perk_evidence_gather({ subject: selection });
if (!cohort.ok) return cohort;
const routing = await tools.perk_evidence_route({ subject: cohort.ref });
if (!routing.ok) return routing;
const reports = await Promise.allSettled(routing.groups.map((group) =>
  tools.perk_agent_run({ role: "analyst", subject: group.ref })
));
return reports.map((report, i) => ({
  group: routing.groups[i].ref,
  ...(report.status === "fulfilled"
    ? { outcome: report.value }
    : { uncovered: String(report.reason) }),
}));
```

The program keeps large joins and repeated source text outside the parent model's context.
It can follow a surprising pattern into another bounded investigation. This offers more
flexibility than another fixed analyst angle, while preserving a standard recipe for ordinary
learn work.

**First experiment:** use a bounded, locally available cohort with known rework patterns and
counterexamples. Compare the proposed findings with existing learn/dream outputs and a direct
strong-model analysis. Include missing sessions and duplicate evidence. Routing must not
double-count one incident as several independent observations or hide a failed analyst.
Publication and any update to `docs/learned/` stay explicit learn-workflow operations.

## Additional opportunities and priorities

These rankings are judgments about user value, Code Mode's contribution, and the cost of the
missing execution capabilities. They are not measured savings.

| Priority | Opportunity | Why this order |
| --- | --- | --- |
| Foundation | Typed callable operations, agents, and evidence | Unlocks actual workflow composition and provides a concrete simplification target. More query tools alone are insufficient. |
| First product proof | Adaptive investigation and review preparation | Demonstrates result-dependent work with modest effect scope; the existing wave substrate supplies much of execution. |
| First write workflow | Repair, checks, and independent review | Directly reduces coordination in an existing, important workflow and tests callable actions. |
| High-value expansion | Competing experiments; executable plan evidence | Makes plans better before expensive implementation and exposes missing workspace/evidence semantics. |
| Cohort expansion | Cross-change learning and connected investigations | Reuses the evidence/agent foundation; quality and source coverage matter more than classification throughput. |
| Larger product horizon | Sustained objectives and portfolio coordination | Highest continuity benefit, with substantial new execution, decision, and recovery ownership. |

**Visual verification** is a strong secondary candidate. A program could gather screenshots
across relevant states, use a vision-capable classifier to flag likely failures, and return
selected images with reproduction evidence for an agent or person to inspect. This fits
acceptance evidence for applications developed with perk. It needs a capture/execution
capability, model accounting, and evaluation against real visual failures. Standalone image
generation has a weaker connection to perk's core workflow.

**Connected-service investigations** could join issue discussions, production errors, changes,
and project documentation into a reviewable diagnosis. Use existing connectors when available;
keep GitHub access behind the canonical `gh` gateway. Configured MCP availability does not
currently grant access through perk's read-only floor. A productized investigation must
deliberately define trusted read capabilities instead of trusting third-party read-only hints.

**Portfolio rehearsal** could compare the consequences of different objective orders, resource
allocations, or approaches before admitting work. Reuse authoritative graph and delivery
projections for mechanical facts. Label hypothetical outcomes distinctly from observed state.
This is a natural extension once execution observations and experiment receipts are usable.

## What first-class support needs to mean

**Available and discoverable.** Make native Code Mode part of perk's standard loadout once
the first callable workflow is ready, initially in `on` mode with direct tools available.
Use init's seed-when-unnamed convergence and a documented project opt-out; preserve explicit
choices and test actual resolved settings. `only` is an optional later posture once the
surface can complete its workflows. Namespace descriptions and a few short skill recipes
should teach composition at the moment it is useful.

**Machine results that carry meaning.** Operations return validated outcomes, references to
complete artifacts, and usable diagnostics. A process exit, a successful promise, a valid
report, complete coverage, and a completed workflow are different facts. Scripts must be able
to distinguish them without parsing English. Existing result unions and boundary decoders
are useful source material; a generic `{success: true}` wrapper would lose information.

**One execution owner per job.** That owner handles limits, cancellation, collection, and late
results. Programs can express concurrency, but should not have to implement subscribe-before-
spawn, transport deadlines, stop acknowledgement versus terminal proof, or drain-once
collection. Direct tools and recipes should invoke the same owner. The public handle should
not expose an engine-private workflow directory as authority.

**Whole-work resource accounting.** Extend accounting to the jobs a campaign owns, with
per-call admission and observed usage. Current worker tokens exclude report children and
observe script model usage only after completion; renaming these totals cannot produce a
campaign budget. Bound calls, concurrency, wall time, and provider request limits where
supported. A hard aggregate cost/token ceiling additionally needs enforceable per-call bounds
or reservations; otherwise state the limit's possible overshoot. Expose model calls through
an observable capability where native `models` cannot meet the required policy.

**Evidence survives selective output.** Returning a short result should leave inspectable
subjects, coverage, revisions where relevant, and artifact references. Context reduction
does not imply removal from session logs or storage. Existing evidence normalization and
privacy rules continue to matter. Retention belongs to the execution/evidence owner, and a
small Code Mode store should not become a competing canonical record.

**Decisions have a lifetime.** An operation awaiting a person needs an identity and a subject;
longer-lived decisions also need retained resolution and consumption. A dismissed surface is
different from denial. Disconnecting should not silently cancel an admitted objective.
Changing the subject may invalidate evidence or a decision. The precise revision contract
must be stated per operation, since today's review paths do not all bind the same way.

## Adoption sequence and deletion gates

### Horizon one: a useful programmable core on the current runtime

1. **Prove callable agent results.** Expose one investigation capability over ReportWave with
   structured outcomes. Revise the automatic model-only/nested policy for that operation.
   Demonstrate dependent investigation and cancellation through the real Code Mode path.
2. **Ship review preparation.** Compose prepared subjects, agents, evidence reduction, and
   review handoff. Route an existing standard command through the same operations so the
   new interface has a real product caller.
3. **Ship a repair campaign.** Add typed access to approved workspace work, configured CI,
   review, and existing effectful feature operations. Separate domain completion from outer
   turn termination. Preserve actual operation authority at every call.
4. **Make composition ordinary.** Seed Code Mode, supply focused recipes, and migrate suitable
   standard flows. Remove superseded prompt procedures and adapters as each caller switches.
   Amend the matching contracts, user docs, expert configuration references, and prose-map
   carriers with their implementations.

The first investigation should dogfood preparation of the repair workflow. The repair workflow
should then help build the experiment capability. Use perk to drive those handoffs and encode
their automatable preconditions in the normal test suites.

### Horizon two: experimental workspaces and retained execution

5. **Enable empirical planning.** Add authorized isolated experiments and their comparison
   evidence. Extend plan/refinement work to consume rechecked assumptions and experiment
   results. Revise the child floor through explicit workspace authority.
6. **Retain campaign ownership.** Move accepted results and pending decisions out of
   activation-local state where restart continuity is promised. Evaluate Pi Durable against
   the existing lifecycle and effect-recovery requirements.
7. **Advance objectives continuously.** Add supported authoring/decision/learning execution
   paths and multi-node coordination. Revalidate the backend and workspace at advancement.
   Retire the one-step supervisor path only after the new path supplies its usable shell and
   machine interfaces.
8. **Expand across changes and sources.** Build cohort learning and connected investigations
   over the retained evidence and callable analysis capabilities.

Each migration needs a responsibility ledger: the old owner, the new owner, its behavioral
evidence, and the code or carrier removed. Keeping an old pathway temporarily is a migration
choice. Keeping two permanent meanings for review completeness, publication, or job completion
would defeat the simplification.

## Experiments and acceptance evidence

Use the existing pytest and node:test suites, real Pi sessions with scripted provider
responses, and the wave memory adapter for deterministic coverage. Live model experiments
assess usefulness and quality after the execution semantics are covered. Avoid a new bespoke
test framework for Code Mode.

| Scenario | Required evidence |
| --- | --- |
| Direct versus scripted operation | Equivalent authorized inputs yield the same domain outcome and effects; the adapter alone decides outer-turn behavior. |
| Dependent investigation | A script uses an earlier report to form a later assignment without relaying the full report through the parent model. Unanswered questions remain visible. |
| Partial, malformed, duplicate, or blocked reports | Completed siblings remain usable; requested coverage remains truthful; a clean result cannot erase actionable evidence. |
| Script abort with a child in flight | The owner requests cancellation and reports observed termination separately from acknowledgement. Late results cannot attach to another campaign. |
| Two post or consume calls overlap | Admission/consumption is serialized or atomic. Today's sequential holder logic is not assumed safe under new concurrency. |
| Review decision followed by a changed subject or failed save | The operation applies its actual source-sensitive freshness rules. A failed or uncertain save cannot release implementation authority by implication. |
| Publication or resolution fails partway | Preserve observed effects and existing recovery semantics. A restarted script cannot blindly repeat an ambiguous external mutation. |
| Parallel repairs or experiments | Workspaces and results are distinguishable; integration is observed; verification concerns the combined or compared revision. The claimed isolation boundary is exercised. |
| Nested model calls exhaust resources | Whole-work accounting includes relevant children without double counting. Demonstrate the stated bound and report any in-flight overshoot honestly. |
| Objective interruption and changed backend state | Retained results and pending decisions survive according to the promised lifetime. Current scope and prerequisites are checked before continuing. |
| Missing or contradictory learning evidence | Missing sources and contested claims remain explicit. Deduplication does not manufacture independent support. |

Compare the same bounded tasks through direct tools, shell composition where appropriate,
existing code-owned waves, and the proposed interface. A workflow already implemented well
as a compiled function is an important baseline.

Measure successful task outcomes, findings missed or introduced, coverage, parent-model input
volume, coordination turns, total model cost including children, wall time, human interventions,
and maintenance obligations removed. Include a small task where Code Mode's setup costs may
outweigh its benefit. Classifier confidence is a routing signal to evaluate, not a calibrated
quality guarantee.

For every major experiment, decide the adoption criterion before running it. Adopt the new
path when it enables useful previously unavailable work or materially reduces coordination
and upkeep while meeting its declared quality and effect semantics. If savings appear only
in printed tokens while task quality drops or total child cost rises, report that outcome
and revise the design.

## Decision

Build **callable agents and typed workflow operations first**, then use them to deliver an
adaptive investigation and a repair campaign. Plan for experiments and durable objectives as
product capabilities with explicit execution owners.

The current system has earned many of its constraints through real failures. Those failures
tell us which responsibilities a replacement must carry. They do not require the same tools,
the same stage boundaries, or the same orchestration architecture forever.

[pi-codemode]: https://pi.dev/docs/latest/codemode
[ronacher]: https://lucumr.pocoo.org/2026/10/6/codemode/
[cloudflare]: https://blog.cloudflare.com/code-mode/
[contracts]: ../../shared/contracts.md
[delegation-principles]: ../design/first-principles/erk-subagent-usage.md
[wave-learnings]: ../learned/workflow/report-waves.md
[facts-decay]: ../learned/workflow/planning-time-facts-decay.md
[objective-learnings]: ../learned/workflow/objective-lifecycle.md
[delivery-learnings]: ../learned/workflow/objective-delivery.md
[learn-evidence]: ../learned/workflow/learn-evidence-pipeline.md
[structured-memo]: command-interface-and-structured-output-opportunities.md
[perk-tool]: ../../extension/pi/perkTool.ts
[tool-policy]: ../../extension/substrate/toolPolicy.ts
[result-seam]: ../../extension/substrate/result.ts
[stack-status]: ../../extension/pi/v1/delivery/stackStatus.ts
[engagement-learnings]: ../learned/workflow/human-engagement-reads.md
[report-wave]: ../../extension/waves/reportWave.ts
[wave-transport]: ../../extension/waves/transport.ts
[classifier]: ../../extension/waves/reviewClassifierWave.ts
[address-binding]: ../../extension/pi/v1/delivery/address.ts
[address-feature]: ../../extension/delivery/address.ts
[automated-review]: ../../extension/codeReview/automated.ts
[plan-review]: ../../extension/authoring/plan/review.ts
[approval-gate]: ../../extension/authoring/review/approvalGate.ts
[ci-runner]: ../../extension/delivery/ci.ts
[stage-execution]: ../../extension/worker/stageExecution.ts
[model-policy]: ../../extension/worker/modelCallPolicy.ts
[objective-run]: ../../src/perk/cli/commands/objective/run_cmd.py
[evidence-core]: ../../src/perk/learn/evidence.py
[dream-analysis]: ../../extension/learning/dreamAnalysis.ts
[supplier-assessment]: pi-and-subagents-assessment-2026-10-24.md
[child-policy]: ../design/pi-subagents-child-execution-policy.md
[decision-foundation]: pi-durable/decision-foundation.md
[durable-vision]: pi-durable/vision.md
[durable-v2]: pi-durable/pi-durable-v2.md
