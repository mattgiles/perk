# Objective: objectives can deliver as one atomic pull-request train

> **Status:** proposed ground-up replacement for the design currently recorded in
> [#1408](https://github.com/mattgiles/perk/issues/1408). This document is the canonical product
> objective.
> The older `docs/planning/stacked-prs.md` and `docs/planning/stacked-pr-recommendations.md` are
> research inputs, not specifications; this directory supersedes them wherever they disagree.

Read this objective together with two durable companions:

- [Stacked delivery architecture](architecture.md) defines the authorities, stored facts,
  operation protocols, recovery behavior, and command ownership that make the product contract
  implementable.
- The repository [objective-delivery glossary](../../../CONTEXT.md#objective-delivery) defines the
  canonical language used here—incremental delivery, stacked delivery, delivery train, layer,
  published prefix, delivery lineage, delivery order, predecessor layer, parent checkpoint,
  published-head checkpoint, and dynamic singleton.

## Objective

Give an objective an optional **stacked delivery** policy under which its roadmap still produces
ordinary, independently reviewable plans, but those plans form one ordered **delivery train** of
GitHub-native stacked pull requests and enter the objective base branch in one atomic landing.

Stacked delivery exists to combine three properties that perk currently makes users choose
between:

1. **Coherent integration.** The objective base never contains a knowingly partial objective.
2. **Overlapped execution and review.** Work on a later roadmap node can begin after its
   predecessor layer is safely published; it does not wait for that predecessor to merge.
3. **Plan-sized review.** Every roadmap node remains one bounded plan and one incremental PR diff.

The current behavior remains the default. An objective whose header has no `delivery` field uses
**incremental delivery**: each plan lands independently, exactly as it does today. Only the
explicit value `delivery: stacked` opts into the new behavior. We use *incremental* in prose and
code for the default policy, but do not serialize `delivery: incremental`; absence preserves the
existing storage shape and behavior.

This is an objective delivery policy, not a new kind of plan, a special branch type, a wrapper
around the `gh stack` extension, or a second objective scheduler.

The terms in this section are domain terms, not convenient synonyms; use the
[objective-delivery glossary](../../../CONTEXT.md#objective-delivery) when interpreting the rest of
the objective.

## Why this belongs at the objective level

A plan knows how to turn one reviewed unit of intent into one PR. It cannot decide whether several
plans must reach the integration branch together, because it neither owns the roadmap nor sees the
other plans. Conversely, an objective already owns the enduring goal, roadmap, node-to-plan links,
and completion lifecycle. It is the smallest domain object capable of making an atomic-delivery
promise without weakening the plan as perk's unit of work and review.

The objective dependency graph and the delivery train answer different questions:

- The **roadmap DAG** expresses why work depends on other work.
- The **delivery train** is the deterministic total order in which the resulting PR layers are
  built, reviewed, synchronized, and landed.

Any valid objective roadmap can use stacked delivery. Fan-out, fan-in, and independent nodes do
not disqualify an objective. Perk derives one train by performing a deterministic topological sort
of the DAG and using the existing `node_sort_key` as the tie-breaker. The author does not maintain
a second order, and storage does not persist a derived position.

The separation between roadmap authority and derived delivery order is specified in
[Architecture: Authorities](architecture.md#authorities) and
[Reconstructing `DeliveryTrain`](architecture.md#reconstructing-deliverytrain).

## Product contract

### Choosing the delivery policy

The objective author decides whether to use stacked delivery while authoring the objective:

- `objective_draft` accepts a first-class delivery choice.
- The authoring agent explicitly asks the human which policy to use and recommends incremental
  delivery by default.
- The rendered review surface displays the choice prominently.
- Approval and `/objective-save` persist only the reviewed choice through the same save seam.
- Cold and automated authoring pass the same typed value; there is no hidden CLI-only flag.

Changing an existing roadmap or its delivery policy goes through objective replan. Before any
layer has been published, a successor objective may change between incremental and stacked
delivery. After the first stacked layer is published, stacked delivery is immutable for that
delivery lineage. A future explicit “abandon train” workflow may support destructive conversion;
ordinary replan does not.

Stacked objective creation is rejected unless all of these conditions hold:

- The roadmap is a valid DAG.
- After excluding nodes already marked `skipped`, it contains between 2 and 100 delivery nodes.
- Every delivery node can produce exactly one plan and one PR layer.
- The resolved objective base supports direct landing without a required merge queue.
- GitHub's native stacked-PR capability is available for the repository.
- The Git remote supports an atomic multi-ref push under the caller's effective access.

A one-node stacked objective is rejected. The user should save it as a standalone plan with
`/plan-save`, or author a genuinely multi-plan objective. Perk does not silently convert the
request to incremental delivery.

The capability checks happen before the objective is created so perk does not persist a promise
it already knows it cannot honor. Every mutating train operation checks the relevant external
capabilities again because GitHub's preview, repository rules, credentials, and remote behavior
can change later. Atomic-push support is probed against the actual authenticated push endpoint with
an exact no-op `git push --atomic --dry-run --no-verify`; this proves server capability and
authentication, not branch write permission or future rule acceptance. Every real ref mutation
therefore remains one authoritative exact-leased atomic push. There is no sequential fallback.

The corresponding stored objective/plan facts and exact capability envelope live in
[Architecture: Durable logical records](architecture.md#durable-logical-records) and
[Capability and API convergence](architecture.md#capability-and-api-convergence).

### One node, one layer

Every non-skipped roadmap node produces exactly one **layer**:

- one ordinary perk plan issue in the configured issue backend;
- one deterministic plan branch and worktree;
- one GitHub PR whose incremental diff is reviewed independently;
- one plan-specific CI, review, address, and learn lifecycle.

Combining several nodes into one layer, splitting one node across several train layers, and adding
unplanned helper layers are outside this objective. Those operations would make the roadmap cease
to be the train's reconstructable source of intent.

Nodes skipped before publication create no layer and disappear from the unpublished suffix. The
normal way to reshape that suffix is replan; a backend-native cancellation of an unpublished
Linear node is the deliberate exception and projects as a skip — **fail-closed and
projection-only**: the node contracts only when reconstruction positively proves it is
unpublished future work (a clean, coherent plan backlink — and abandoned-only publication
history — is acceptable; any identity conflict, checkpoint or PR claim, completed or unresolved
publication, remote branch, or branch-owned PR in any state is not), the persisted attachment
status is never changed by the read (doctor `--fix` owns
persisting a proven-safe skip), and anything unprovable stays a visible `canceled` layer with
blockers. A published node cannot
subsequently be skipped, canceled, reordered, removed, or placed behind a new node: that is
structural drift and requires replan.

The 2–100 rule is an authoring-time validity rule, not a reason to make later cancellation brittle.
If cancellation reduces a previously valid train to one non-skipped layer before a native stack
exists, the delivery train becomes a **dynamic singleton**: it retains stacked lineage and may land
only through objective-scoped landing, which directly merges the sole PR with the same readiness,
journal, and finalization discipline. Native stack membership and stack-preview availability are
not applicable to that landing. If no delivery layers remain, the all-skipped objective completes
without a merge. This exception does not permit authoring a one-node stacked objective.

See the [architecture's reconstruction model](architecture.md#reconstructing-deliverytrain) for
how ordinary layers, a dynamic singleton, and an all-skipped completion project without creating a
second roadmap authority.

### Planning and build readiness

Stacked delivery does not redefine objective completion and does not weaken the existing terminal
statuses. `done` and `skipped` remain terminal; a published but unmerged layer remains in progress.
Instead, the delivery module derives a separate **build-ready** condition.

The first delivery node is build-ready when the objective is valid and its integration base can be
resolved. Each later node is build-ready only when the immediately preceding delivery layer has:

- a saved node-to-plan link;
- a verified remote branch at the expected published head;
- an open PR, draft or ready, targeting the expected predecessor branch; and
- once at least two PRs exist, verified membership and order in the expected GitHub-native stack.

This makes the published prefix strict and contiguous. A registration failure or wrong PR base
does not get waved through as “eventual consistency”; it blocks the next layer until convergence
or recovery verifies the remote truth.

Planning should inspect the latest verified predecessor branch so the author sees the code the
new plan will inherit. That observation is useful context, not a staleness lock. Perk deliberately
does **not** persist `planned_against_parent_sha` and does not reject implementation merely because
the predecessor or the rest of the codebase changed after planning. Ordinary plans already face
that risk; stacked plans treat it as a normal implementation danger.

Build readiness is a derived projection rather than a new node status; its source-of-truth joins
and blocker vocabulary are defined in
[Architecture: Reconstructing `DeliveryTrain`](architecture.md#reconstructing-deliverytrain).

### Implementation and publication

Local and remote implementation use the same parent-preparation path and receive the same
immutable `LayerContext`:

- the objective, node, plan, delivery lineage, and predecessor plan identities;
- the objective base for the bottom layer;
- the latest verified remote predecessor head for every higher layer; and
- the branch/ref information needed to create the worktree without relying on pre-existing local
  stack metadata.

Immediately before creating or refreshing a layer worktree, perk fetches and verifies the current
remote parent, then starts the layer from that commit. The parent checkpoint is durable operational
state used for later cascading rebases; it is not planning provenance.

`/submit` remains the publication door. For a new stacked layer it:

1. reconstructs and validates the train;
2. checks exact branch ancestry and leases;
3. publishes the branch;
4. creates or converges the PR onto the expected base;
5. creates the native GitHub stack at the second PR or appends the next missing suffix;
6. refetches Git refs, PRs, and stack membership; and
7. records checkpoints only after every required postcondition is verified.

The first PR is a logical train layer even though GitHub cannot create a native one-PR stack. The
second publication creates the native stack. New PRs remain drafts unless the existing submit
workflow says otherwise. A verified draft layer unlocks its successor; `/ready` remains a
per-layer human review gesture.

Remote stack registration is conservative and convergent:

- no stack plus the exact first two PRs creates one;
- an exact expected prefix may append its missing suffix;
- an exact match is a no-op;
- reordered, extra, cross-linked, or independently edited composition fails closed.

Perk never automatically deletes and recreates a native stack, rewrites an independently edited
composition, or degrades the objective to incremental delivery.

The exact validate-mutate-verify sequence and GitHub idempotency rules are normative in
[Architecture: Publication protocol](architecture.md#publication-protocol).

### Updating a published layer

Changing a lower published layer invalidates the ancestry of every published layer above it.
Submitting that lower layer therefore synchronizes the entire affected **published suffix** before
reporting success. This behavior is also available explicitly through
`perk objective stack sync` and is reused by `/address`.

The safe-enough synchronization model is intentionally small:

1. Reconstruct the train and preflight every affected layer.
2. Refuse before remote mutation if another writer owns an affected layer, an affected worktree
   is dirty, the remote has unadopted changes, or any exact lease no longer matches.
3. Use one operation-scoped isolated worktree and temporary refs to calculate every candidate head
   from the changed layer upward.
4. If a rebase conflicts, leave every remote ref unchanged and retain only a small disposable
   local manifest needed to continue or abort that candidate calculation.
5. Write a durable prepared operation record containing the exact before/after ref set.
6. Publish all affected refs in one atomic multi-ref push with exact per-ref leases.
7. Refetch and verify the complete suffix, PR bases, ancestry, and native composition.
8. Append operation completion and update plan checkpoints.

Normal user branches and worktrees are not moved during candidate calculation. Perk never
auto-stashes, auto-commits, or edits another active writer's work. The preferred recovery from
active upper-layer work is to finish and submit that work first; otherwise the user stops the run
and preserves the work explicitly.

Only published layers participate in a cascade. Unpublished work at the top is not rewritten
behind its author's back; when eventually submitted, it catches up with the latest predecessor in
the same way any branch catches up with a changed codebase.

Advancement of the objective base by unrelated merged work is likewise a normal codebase change,
not train corruption and not a reason to invalidate old plans. Reconstruction reports the current
base and whether the bottom layer needs to catch up. When repository rules, conflicts, or user
intent require an update, the same transactional cascade starts at the bottom layer and carries
the new base through the published train. It either updates the entire train or no remote layer;
`perk objective stack sync` is the explicit operation that performs this rewrite. Landing may
proceed without it when GitHub reports the exact train mergeable and all rules pass. When an
up-to-date rule or conflict requires synchronization, landing stops with the copyable sync command
rather than silently changing reviewed heads.

Out-of-band remote edits are drift, not a new authority. `perk objective stack sync --adopt NODE`
offers the explicit exception: it presents a dry run, requires human confirmation, adopts the
observed remote head for that layer, and transactionally rebuilds the published suffix above it.
There is no implicit auto-adopt.

Candidate isolation, continuation/abort, atomic push, base advancement, and explicit adoption are
specified together in
[Architecture: Synchronization protocol](architecture.md#synchronization-protocol).

### Cross-machine operation and recovery

A published train can be reconstructed and operated from a fresh clone. No `.git/gh-stack`,
Graphite cache, worktree inventory, session directory, or prior checkout is authoritative.
Uncommitted local edits remain local, exactly as in ordinary Git; cross-machine resumability begins
once work is committed and published.

Every remote-mutating train operation is journaled in the configured objective/issue backend
before its irreversible step. Journal entries are append-only facts:

- a prepared entry records operation identity, kind, delivery lineage, affected plans, and exact
  before/after observations;
- an accepted entry is used only when a remote API returns a recovery handle that cannot be
  reconstructed later, notably GitHub's async-merge UUID;
- completion records the verified result;
- abandonment records that inspection proved the irreversible step did not occur.

Each event is one strictly marked, schema-versioned comment. GitHub stores it on the objective
issue; Linear stores it on the Project's existing metadata sentinel issue. Append-only means perk
never edits or deletes these comments. Exact duplicate event keys are idempotent; malformed,
conflicting, or detectably edited perk events are corruption. Authorized comment deletion is
treated as out-of-band tampering rather than an adversarial integrity threat perk attempts to
solve cryptographically; live Git, PR, stack, and checkpoint verification remains the safety
backstop.

The prepared event is appended and read back immediately before the first remote effect: branch
push for publication, atomic push for sync/adopt, successor creation for transfer, and merge
request for landing. Perk does not emit a comment after every observable branch, PR, or
registration effect; recovery derives those facts from the remote and appends only the minimal
accepted/completed/abandoned outcome.

The active state is a fold over those records, not a mutable “current operation” field. Exact Git
leases ensure at most one concurrent ref mutation can apply. A new machine recovers by comparing
the remote to the prepared record:

- all refs still at **before**: nothing was pushed; safely rebuild, retry, or abandon;
- all refs at **after**: the push succeeded; verify secondary effects and finish checkpoints;
- any mixed or unexpected set: report drift and require explicit repair.

`perk objective stack recover` exposes this behavior without starting unrelated new work, scoped
to the operation kinds delivered so far: an all-after SYNC/ADOPT rolls forward automatically
(deterministic, never asks twice); an all-after TRANSFER found on the predecessor journal
corroborates its run-id successor and rolls the recorded manifest forward through ownership,
verification, finalization, and completion; an all-after PUBLISH is reported because its
roll-forward stays `/submit`'s own idempotent resume. LAND remains report-only. Recovery is
conclude-only across the board: a proven all-before operation may be explicitly abandoned after
confirmation, while the retry itself routes to the operation's owning command (sync re-runs
through `stack sync`; publication through `/submit`; a transfer retry is objective replan).
A mixed/other state never mutates automatically. Multiple unresolved operations require an
explicit operation ID, and elapsed time never substitutes for remote proof.

The comment-carried event schema, cross-objective folding rules, and full outcome matrix live in
[Architecture: Operation journal](architecture.md#operation-journal) and
[Recovery matrix](architecture.md#recovery-matrix).

### Replanning and delivery lineage

The paved road for changing a roadmap remains objective replan: create a successor objective,
carry forward only unfinished work, and supersede the predecessor. Stacked delivery adds a stable
**delivery lineage** so that a train remains one domain object across that succession.

Before the first publication, replan may change the delivery policy and reshape the roadmap
freely. Existing unpublished plan identities are preserved when their nodes carry forward; replan
atomically rewrites or clears lineage, predecessor, and checkpoint metadata for the successor
policy. It does not rewrite local branches. Clean unpublished commits catch up during their next
implementation/submission preparation, while a dirty worktree or active writer blocks conversion
until the user reaches a safe point. After publication, the successor must:

- preserve stacked delivery and the delivery lineage;
- preserve the objective integration base;
- carry the published prefix in exactly the same order with the same plan identities;
- transfer each published plan's current objective/node ownership to the successor;
- leave branch, PR, and native stack identities unchanged; and
- reshape only the unpublished suffix.

Transfer is a journaled, rerunnable operation. The predecessor-carried prepared event **is** the
durable transfer manifest: it names the predecessor, the exact published prefix, and the complete
successor materialization intent before successor creation begins. The old objective is closed
only after reconstructing the successor proves that every published plan has transferred and the
prefix is unchanged. A partial backend failure therefore remains recoverable on GitHub Issues and
Linear Projects.

On Linear, a later unpublished node moved to the canceled state projects as `skipped` and simply
disappears from the future train, including the dynamic singleton/zero-layer outcomes above —
provided the exact safe-contraction proof passes (fail-closed: unprovable evidence keeps the node
a projection-only `canceled` layer, and the projection persists nothing). Canceling a published
node is structural drift and blocks train mutation until the edited authority is repaired (then
status re-run; replan only if the future roadmap still needs reshaping).

The write ordering that keeps a superseding-objective transfer recoverable is specified in
[Architecture: Replan transfer protocol](architecture.md#replan-transfer-protocol).

### Landing

Intentional landing is objective-scoped. Ordinary `/land` and `perk pr land` refuse any plan that
belongs to a stacked delivery lineage and direct the user to the objective operation. The agreed
cold command is:

```text
perk objective stack land [OBJECTIVE]
```

V1 supports only GitHub's native asynchronous **direct merge** with squash semantics for a native
stack, plus an ordinary direct squash merge behind the same objective operation for a dynamic
singleton. A base that requires merge queue is rejected because queue grouping may split the train
and violate the atomic integration promise. Perk does not emulate atomicity by merging PRs
sequentially.

Before sending the merge request, landing reconstructs the train and requires:

- every non-skipped roadmap node has exactly one published layer;
- the published prefix is therefore the complete train;
- every PR is open and ready rather than draft;
- every expected branch head, PR base, ancestry edge, and native stack position matches;
- required reviews, status checks, branch rules, and conflict checks pass;
- no train operation or affected writer is active; and
- the objective base still supports direct stack merge.

Landing uses one typed per-layer readiness projection over exact refs, mergeability, review
decision, required checks, and aggregate GitHub rule state. Pending or unknown required state is a
temporary blocker. Posted review comments and unresolved review threads are displayed separately
as information and are **not** perk-invented landing gates. This matches today's `/land`: the human
may intentionally land while advisory discussion remains. If a repository itself enforces
conversation resolution, GitHub's aggregate rule state blocks the PR and perk honors that rule.

Landing writes its prepared journal record before calling GitHub. That record captures, for every
layer, the node and plan identities, PR number, incremental base SHA, and exact head SHA. It then
submits one native async merge operation with `merge_action: direct_merge`, `merge_method: squash`,
and the verified top head SHA. An accepted UUID is appended immediately. Perk polls once per second
for up to 60 seconds; timeout means accepted and pending recovery, never failure or success. A
terminal `failed` means nothing merged. An `enqueued` response to the explicit direct request is a
protocol/capability violation. Every `merged` result is still verified across all PRs before
bookkeeping. If the process, machine, or 24-hour operation handle disappears, a later land or
recover invocation uses the journal and exact PR/ref state rather than issuing a speculative
second merge.

A manually merged contiguous prefix is accepted as irreversible degraded reality, recorded as an
external atomicity breach, and recovered by synchronizing the remaining suffix onto the objective
base before atomically landing the remainder. A merged non-prefix layer, a closed-unmerged layer,
or an otherwise broken order is fatal structural drift.

GitHub merge completion and perk bookkeeping are separate facts. Once GitHub reports the PRs
merged, the code is landed even if issue-backend updates fail. Per-plan finalization is idempotent
and retryable:

- close or converge the plan issue;
- stamp the canonical learn state;
- mark its roadmap node `done`;
- perform learn-consumption bookkeeping and activity emission; and
- preserve the per-plan `/learn` lifecycle.

The objective becomes complete only after all merged layers are finalized and all roadmap nodes
are terminal. Objective reconciliation then runs once, using the journal's ordered per-layer
evidence rather than a current-worktree accident. The evidence persists PR identity, incremental
base/head SHAs, observed merge-commit SHA, and final objective-base SHA; exact diffs are recovered
from Git objects, pull refs, or PR APIs rather than storing unbounded patches or lossy summaries.
A bookkeeping retry never reissues a completed merge.

The authoritative readiness interpretation, async wire states, external-prefix recovery, and
finalization boundary are defined in
[Architecture: Landing protocol](architecture.md#landing-protocol).

## Architectural direction

One deep Python delivery module owns the train lifecycle. Its public interface is expressed in
domain operations such as reconstruct/status, prepare/publish, synchronize/adopt, recover,
transfer, and land. It is keyed by objective identity or delivery lineage and returns immutable
before/after projections plus typed outcomes. Existing submit, address, land, replan, supervisor,
and doctor paths are thin callers.

The module constructs one immutable `DeliveryTrain` projection from injected seams:

- a backend-aligned persistence adapter composing the existing `ObjectiveStore` and
  `IssueBackend` selected by the same `[issues]` configuration;
- a Git adapter for refs, ancestry, isolated candidate work, and exact leased atomic pushes; and
- an explicitly GitHub-native PR/stack adapter for capability, PR, rules, stack, and async merge
  operations.

There is no generic “stack provider” abstraction and no Graphite-shaped branch manager. GitHub is
already the universal Git/PR plane when the issue backend is Linear, so only durable objective,
plan, journal, and transfer records vary by issue backend.

The TypeScript extension remains the session interior: it provides warm human/model doors,
renders structured results through the surfaces module, and delegates durable Git/GitHub/backend
work to Python workers. Any behavior both planes must understand is amended in
`shared/contracts.md` in the same implementation turn.

The agreed cold CLI surface is deliberately small:

```text
perk objective stack status  [OBJECTIVE] [--json]
perk objective stack sync    [OBJECTIVE] [--base] [--dry-run] [--adopt NODE | --continue | --abort]
perk objective stack recover [OBJECTIVE] [--dry-run] [--operation ID] [--abandon]
perk objective stack land    [OBJECTIVE] [--dry-run] [--yes]
```

The explicit objective argument wins; otherwise inference is allowed only from the active
plan/worktree. Perk never searches several open objectives and guesses. Status is
confirmation-free. Adopt, abandonment, and landing show the exact objective/lineage and require
interactive confirmation or `--yes` headlessly; deterministic roll-forward recovery does not ask
again. The group contains no `create`, `publish`, `push`, `rebase`, `unstack`, or generic `repair`
command: existing lifecycle doors own creation/publication, low-level Git is encapsulated,
conversion is not an ordinary operation, and recovery is driven by recorded facts.

The warm human surface keeps perk's established gesture-oriented commands:

```text
/objective-stack    # status
/objective-sync     # sync, adopt, continue, or abort
/objective-recover  # durable-operation recovery
/objective-land     # objective-scoped landing
```

Model tools are separately typed rather than exposing one mutation action enum.

The division between these commands and the existing workflow doors is normative in
[Architecture: Command ownership](architecture.md#command-ownership); its
[verification strategy](architecture.md#verification-strategy) explains how the preview-dependent
behavior is proved without making CI network-dependent.

## System invariants

The implementation is correct only while all of these remain true:

1. Absence of `delivery` retains current incremental behavior and storage compatibility.
2. A stacked objective is authored with one objective base and 2–100 layers; later cancellation
   may produce a dynamic singleton or an all-skipped zero-layer completion.
3. Any valid roadmap DAG can be stacked; canonical train order is derived, deterministic, and not
   separately editable.
4. Every non-skipped train node maps bijectively to one plan, branch, and PR layer.
5. The published layers always form a contiguous prefix of canonical train order.
6. A successor becomes build-ready only after the predecessor is remotely published and fully
   verified; at two or more layers this includes native stack membership.
7. A published prefix is immutable. The unpublished suffix may be reshaped through replan, or
   reduced by backend-native cancellation projected as a skip.
8. Stacked delivery policy is immutable after first publication and survives objective
   supersession through one stable delivery lineage.
9. The objective integration base is immutable after first publication.
10. Durable reconstruction never depends on local stack metadata or existing worktrees.
11. Checkpoints are observations written only after their remote postconditions are verified;
    they are never speculative desired state.
12. Remote branch changes are drift until explicitly adopted.
13. A cascade changes no remote ref unless every candidate head is ready and one exact-leased
    atomic push succeeds.
14. Perk never mutates dirty worktrees or work owned by another active writer.
15. At most one prepared remote-mutating operation may be unresolved for a delivery lineage.
16. Native stack composition is converged only from absent/exact-prefix states; ambiguous
    composition fails closed.
17. Ordinary plan landing cannot intentionally merge any layer of a stacked objective, including a
    dynamic singleton.
18. Perk-initiated landing either merges the complete remaining train atomically or merges none of
    it; sequential fallback is forbidden.
19. Required GitHub rules gate landing; advisory review threads do not independently gate it.
20. A confirmed GitHub merge is never reported as unmerged because secondary bookkeeping failed.
21. All remote mutations and cross-objective transfers are idempotently recoverable from durable
    backend facts and live GitHub/Git state.

## Success criteria

The objective is complete when all of the following are demonstrated:

- An author can review and save the same stacked objective against either GitHub Issues or Linear,
  while an unqualified objective behaves byte-for-byte and behaviorally as before.
- A one-node stacked objective is rejected, and a 2–100-node objective with a non-linear DAG is
  accepted and deterministically ordered.
- Later cancellation can reduce that valid objective to a dynamic singleton that lands only
  through objective scope, or to an all-skipped objective that completes without a merge.
- Starting from a fresh clone, perk can reconstruct status, implement the next build-ready layer,
  and publish it without any `gh stack` or Graphite cache.
- A real two-layer objective can be planned, implemented locally or remotely, submitted as draft
  PRs, registered as a GitHub-native stack, reviewed independently, and landed together.
- A later layer can be planned while a lower published layer is still under review.
- Updating a lower layer either publishes the complete affected suffix in one leased atomic push
  or changes no remote branch; conflicts and competing writers are safe, explicit blockers.
- A deliberate remote edit is rejected until `sync --adopt` is confirmed, after which the suffix
  converges transactionally.
- An interrupted publication, sync, transfer, or landing can be recovered on a second machine by
  inspecting the backend journal and remote state.
- GitHub and Linear journals use their agreed marked-comment carriers, reject detectable
  tampering/conflicts, and recover correctly without per-effect event spam.
- Replan preserves a published prefix and lineage while allowing the unpublished roadmap suffix
  to change, on both issue backends.
- Objective landing refuses drafts, failed required checks/reviews, wrong ancestry, composition
  drift, merge-queue-only bases, and active operations—but permits advisory unresolved comments.
- An injected bookkeeping failure after a successful merge resumes finalization without attempting
  another merge.
- An externally merged contiguous prefix follows the documented degraded recovery path; a
  non-prefix merge fails closed.
- `just test` and `just ci` cover the domain projection, both persistence adapters, gateway fakes,
  remote-runner parity, ref races, eventual consistency, failure recovery, and unchanged
  incremental behavior.
- The implementation updates `shared/contracts.md`, the appropriate `docs/user-docs/` Divio
  quadrants, and the delivered `perk-expert` references in the same turns as their corresponding
  behavior.

## Boundaries and non-goals

- **No replacement for incremental delivery.** Stacked delivery is opt-in and deliberately costs
  more operational machinery.
- **No authored one-layer train.** Standalone work remains a plan; only later cancellation may
  produce the dynamic singleton described above.
- **No restriction to chain-shaped roadmaps.** The roadmap DAG is intent; the train is a derived
  topological order.
- **No multiple trains per objective in V1.** Independent delivery trains may be a later feature.
- **No merge-queue integration in V1.** Queue grouping cannot currently uphold this objective's
  atomicity promise.
- **No sequential remote fallback.** Neither synchronization nor landing trades correctness for
  best-effort progress.
- **No automatic remote adoption or destructive stack repair.** Independent remote edits require
  explicit human intent.
- **No local authority.** Session files and temporary worktrees support an in-progress local
  calculation but never define the train.
- **No `gh-stack` extension dependency.** Perk uses GitHub's native API through its own narrow
  adapter and keeps its one-worktree-per-plan model.
- **No generic Graphite compatibility layer.** The useful erk lessons are incorporated without
  preserving Graphite's cache, command vocabulary, or dual authority.
- **No plan-freshness fiction.** A changed codebase between planning and implementation is a normal
  danger, not a reason to persist a non-controlling planning SHA.
- **No invisible editing of another writer's work.** Dirty or actively owned layers block.
- **No review-thread policy change.** Landing displays unresolved discussion but leaves the final
  discretion with the user unless repository rules say otherwise.
- **No speculative roadmap mutation outside replan.** Structural changes to a published train use
  the existing superseding-objective path.

## Assumptions and decisions carried by this objective

- GitHub remains the Git, PR, CI, stack, and merge plane for both issue backends.
- The configured issue backend stores both objectives and plans even though perk exposes separate
  `ObjectiveStore` and `IssueBackend` seams.
- GitHub's native stack APIs remain preview-quality and can change; the GitHub adapter, capability
  probes, tolerant reads, and failure injection localize that instability.
- Git exact leases and remote atomic push are the concurrency primitive. V1 does not introduce a
  distributed lock.
- GitHub native direct stack merge is treated as atomic only when the operation and observed result
  prove it. External partial merges are accepted as degraded reality, never represented as a
  successful perk atomic landing.
- Cross-machine recovery concerns committed/published work and durable operation facts. Perk does
  not attempt to transport uncommitted editor state.
- Authorized journal-comment deletion is out-of-band corruption rather than an adversarial threat;
  every mutation still fails safe from live remote/checkpoint verification.
- The objective implementation itself can land incrementally; writable stacked-objective creation
  is enabled only after the two-layer vertical slice passes its dogfood gate.

## Roadmap

The roadmap is intentionally organized around vertical capabilities, not one file or schema per
node. Explicit dependencies preserve safe implementation order while allowing independent work to
proceed in parallel. Every behavior-changing node owns its same-turn contract, tests, and user-doc
updates; the final documentation node is a cohesive usability pass, not a dumping ground for drift.

| Node | Slug | Depends on | Outcome |
| --- | --- | --- | --- |
| 1.1 | `delivery-domain` | — | Lock language, ordering, invariants, and additive stored contracts. |
| 1.2 | `durable-train-state` | 1.1 | Implement backend-neutral train persistence, lineage, checkpoints, and append-only operations for GitHub and Linear. |
| 1.3 | `train-projection` | 1.2 | Reconstruct one immutable `DeliveryTrain` and expose read-only status. |
| 2.1 | `stacked-authoring` | 1.1, 1.2 | Carry an explicit reviewed delivery choice through draft/save validation and capability checks. |
| 2.2 | `parent-aware-execution` | 1.3 | Derive build readiness and use one parent-aware path for planning and local/remote implementation. |
| 2.3 | `layer-publication` | 2.1, 2.2 | Publish verified draft layers and converge GitHub-native stack registration through `/submit`. |
| 2.4 | `publication-dogfood` | 2.3 | Pass a real two-layer dogfood gate and enable writable stacked-objective creation. |
| 3.1 | `transactional-sync` | 1.2, 2.3 | Calculate a cascade in isolation and publish the complete suffix atomically with exact leases. |
| 3.2 | `sync-recovery-surface` | 3.1 | Complete `objective stack` status/sync/recover, explicit adoption, and cross-machine recovery. |
| 3.3 | `workflow-convergence` | 3.2 | Route lower-layer submit/address and supervisor behavior through the same synchronization module. |
| 4.1 | `lineage-replan` | 1.2, 2.3 | Transfer an immutable published prefix through a successor objective with a rerunnable manifest. |
| 4.2 | `backend-drift` | 1.3, 4.1 | Project Linear cancellation correctly and diagnose structural train drift on both backends. |
| 5.1 | `merged-plan-finalization` | 2.3 | Extract idempotent post-merge finalization and guard ordinary `/land`. |
| 5.2 | `atomic-objective-land` | 3.2, 5.1 | Preflight and submit a journaled GitHub-native direct stack merge through `objective stack land`. |
| 5.3 | `land-recovery-reconcile` | 4.1, 5.2 | Recover async/external outcomes, finalize every plan, and reconcile once from durable evidence. |
| 6.1 | `failure-hardening` | 3.3, 4.2, 5.3 | Prove races, fresh-clone/remote parity, preview failures, and unchanged incremental behavior. |
| 6.2 | `stacked-delivery-dogfood` | 6.1 | Complete operator/reviewer documentation and use perk to deliver a real objective atomically. |

### Phase 1: domain, persistence, and projection

#### 1.1 — Delivery domain

Use the canonical language in the
[objective-delivery glossary](../../../CONTEXT.md#objective-delivery) and add the domain contracts
for objective delivery policy, delivery lineage, node identity on plans, stable predecessor-plan identity,
parent and published-head checkpoints, and deterministic topological train order. Define strict
2–100-node validation without constraining the roadmap DAG. Preserve absent-field compatibility
for incremental objectives and existing plans. Amend `shared/contracts.md` and boundary/schema
snapshots in the same turn, but do not yet enable writable stacked authoring.

#### 1.2 — Durable train state

Add the backend-aligned persistence adapter that composes the selected `ObjectiveStore` and
`IssueBackend`. Implement the same logical state for GitHub Issues and Linear Projects/plans:
delivery lineage, plan ownership, verified checkpoints, transfer manifests, and append-only stack
operation records. Store strict marked comments on the GitHub objective issue and the Linear
Project metadata sentinel; make deterministic event keys idempotent, reject malformed/conflicting/
detectably edited records, and fold the minimal `prepared|accepted|completed|abandoned` vocabulary
across objective succession. Enforce one unresolved remote mutation per lineage and read back every
append before crossing its boundary. Keep journal comments out of human-engagement inputs. Cover
pagination, ambiguous POST responses, the maximum 100-layer record size, authorized deletion as
out-of-band corruption, partial writes, and retries before any production train mutation depends
on it.

#### 1.3 — Train projection

Build the deep Python delivery module's read path and immutable `DeliveryTrain`: load the active
objective lineage, resolve the DAG and canonical order, join nodes to plans, observe Git refs and
worktrees, fetch PRs/native stack state, fold journals, and classify blockers versus information.
Add the GitHub-native read/probe adapter and `perk objective stack status [OBJECTIVE] [--json]`.
Status must work from a fresh clone, identify exact authority conflicts, and remain useful for an
incremental objective by explaining that no delivery train exists.

### Phase 2: author-to-publication vertical slice

#### 2.1 — Stacked authoring

Add the first-class delivery choice to objective draft/review/save on both backends. Make the human
choice explicit, default incremental, render it in review, reject one-node and over-limit trains,
and validate arbitrary DAG order. Resolve the objective base and perform non-mutating native-stack,
direct-merge/queue, and authenticated no-op atomic-push capability checks against the real push
endpoint. State honestly that the probe proves server capability/authentication rather than write
permission. Keep the write path gated until Node 2.4 so the repository cannot create a stacked
objective that perk cannot yet drive.

#### 2.2 — Parent-aware execution

Derive stacked build readiness from `DeliveryTrain` without changing global terminal-status
semantics. Update objective planning to run with the latest verified predecessor context while
treating later movement as normal danger. Introduce the shared immutable `LayerContext` and one
preparation path used by local implementation and `src/perk/run/workflow_artifacts.py`: fetch and
verify the latest parent, create the bottom layer from the objective base or a child from its
predecessor, and record the operational parent checkpoint. Prove parity without pre-existing
worktrees or local stack metadata.

#### 2.3 — Layer publication

Route stacked `/submit` through the delivery module. Publish a branch with an exact lease, create
or converge its PR onto the expected base, create native membership at layer two, append only an
exact missing suffix, refetch all remote facts, and update checkpoints only after verification.
Because GitHub supplies no stack-mutation idempotency key, use the prepared operation plus exact
before/desired membership: after `2xx`, ambiguous network/`5xx`, or `422`, refetch and classify
exact-after as success, unchanged-before as retryable, and every partial/different composition as
drift. Serialize mutations and honor GitHub rate-limit/retry guidance.
Registration failure leaves a recoverable prepared operation and blocks successor readiness.
Retain draft-by-default behavior and per-layer `/ready`. Give stacked PR bodies clear “this layer”
and “train context” sections without making prose authoritative.

#### 2.4 — Publication dogfood gate

Drive a real two-node objective through authoring, bottom implementation/publication, successor
build readiness, parent-aware implementation, second publication, and verified native stack
registration using perk itself. Exercise at least one remote/fresh-clone implementation path.
Only after the gate passes, remove the temporary write guard and document stacked delivery as a
supported authoring choice.

### Phase 3: safe change propagation

#### 3.1 — Transactional synchronization

Implement published-suffix synchronization with one operation-scoped isolated worktree and
temporary refs. Preflight active writers, dirty worktrees, remote drift, PR bases, ancestry, and
exact leases. Calculate every candidate head before preparing the durable operation. On conflict,
change no remote ref and retain only the disposable continuation manifest. On success, issue one
atomic multi-ref push with explicit per-ref leases, refetch and verify every postcondition, then
complete the journal and checkpoints. Base advancement is reported and enters this same cascade
only through explicit sync. No sequential fallback or normal-worktree rewriting.

#### 3.2 — Sync and recovery surface

Complete the agreed `perk objective stack` subgroup: detailed status, dry-runnable sync, explicit
`--adopt NODE`, and generic journal recovery. Define human confirmation and structured output.
Recover all-before and all-after operations safely across machines; classify mixed/other remote
sets as drift. All-after rolls forward; all-before retries after confirmation or explicitly
abandons; multiple unresolved operations require an ID. Add `sync --continue|--abort` for local
conflicts without elevating its manifest to durable authority. Implement the agreed warm commands,
separate typed model tools, objective inference precedence, and `--yes` discipline.

#### 3.3 — Workflow convergence

Make lower-layer `/submit` automatically synchronize the affected published suffix and route
post-`/address` propagation through the same operation. Update objective-run prioritization so
lower-layer repair/sync outranks new upper work while review waiting does not. Ensure `/ready`,
status, submit, address, and later land all consume the same projection and typed blockers rather
than implementing parallel stack logic in their command handlers.

### Phase 4: replan and backend drift

#### 4.1 — Lineage-preserving replan

Extend objective replan with the stable delivery lineage and prepared transfer manifest. Preserve
the exact published plan prefix, update each plan's objective/node ownership, permit arbitrary
unpublished suffix reshaping, verify the successor projection, and close the predecessor only
after convergence. Make the objective base immutable after publication. Before publication,
preserve carried plan identities while rewriting/clearing delivery metadata, never rewrite local
branches, and block on dirty/active work. Support interruption at every write on GitHub and Linear
and make rerun finish the transfer without duplicating objectives, plans, or journal effects.

#### 4.2 — Backend drift

Teach the Linear project adapter to project cancellation of unpublished future nodes as skipped
delivery work while treating published cancellation as structural drift. Add train-specific
handling for a cancellation-derived dynamic singleton (objective-scoped ordinary direct squash
merge, no native membership) and all-skipped completion. Add train-specific
doctor/status findings for canceled/published mismatches, duplicate plan links, wrong lineage,
prefix gaps, independently edited native composition, missing journal outcomes, and impossible
checkpoint relationships. Safe fixes may repair representational metadata; semantic/topological
conflicts must direct the user to replan or an explicit GitHub repair.

### Phase 5: atomic landing and finalization

#### 5.1 — Merged-plan finalization

Extract an idempotent finalization operation from `_pr_land_impl` that accepts reconstructed plan,
PR, objective, and evidence inputs rather than the active worktree cache. Reuse it for incremental
land without behavior drift. Make `perk pr land` and `/land` refuse plans carrying stacked lineage
before any ready/merge mutation. Preserve plan closing, learn state, consumed-learning updates,
node completion, activity reporting, and visible partial bookkeeping results.

#### 5.2 — Atomic objective land

Implement `perk objective stack land` and its thin warm/model door. Produce a complete dry-run
land plan; reject incomplete publication, drafts, failed required checks/reviews/rules, conflicts,
wrong SHAs/bases/composition, queue-required bases, active writers, and unfinished operations.
Build `LandReadiness` from exact GraphQL refs, mergeability, review decision, required-check flags,
and aggregate rule state; report advisory unresolved threads separately. Prepare the exact
per-layer landing journal and submit `merge-async` with direct/squash/verified top SHA, recording
the returned UUID. Poll once per second for 60 seconds; distinguish pending, merged, failed, and an
unexpected enqueued result. Support the dynamic singleton through the same objective operation.

#### 5.3 — Landing recovery and reconciliation

Recover an interrupted async merge from its operation identity and observed PR states. Accept and
record only an externally merged contiguous prefix, synchronize the remainder onto the objective
base, and reject non-prefix/closed drift. Finalize confirmed merged plans independently and
idempotently; distinguish GitHub merge completion from backend finalization. Once every node is
terminal, close the objective and run exactly one reconciliation using ordered journal evidence,
including each layer's PR identity, incremental base/head SHAs, merge commit, and final objective
base SHA. Recover exact diffs through Git objects, pull refs, or PR APIs; store neither full patches
nor lossy summaries.

### Phase 6: hardening, documentation, and final dogfood

#### 6.1 — Failure hardening

Exercise gateway eventual consistency and preview removal, exact-lease races, atomic-push refusal,
process death before/after every irreversible boundary, stale prepared records, dirty/active
worktrees, absent worktrees, cross-machine continuation, Linear partial transfers, remote runner
parity, async merge timeouts, external prefix merges, and post-merge bookkeeping failures. Expand
doctor and JSON envelopes as needed. Keep the full incremental suites green and demonstrate that
absent metadata follows the existing paths rather than a new compatibility branch.

#### 6.2 — Stacked-delivery dogfood

Complete the cohesive user experience: tutorials for authoring and daily work, reviewer guidance,
the four-command CLI reference, warm-door reference, recovery decision tables, limitations, and
the matching self-contained `perk-expert` references. Then author and deliver a meaningful perk
objective through the supported stacked path, including lower-layer feedback, a cascade, execution
from a second clone or remote runner, and one atomic objective landing. Treat this as the final
product gate, not a scripted happy-path demonstration. Keep CI hermetic; run the live preview proof
in a designated durable dogfood repository and record publication/fresh-clone plus
landing/interrupted-recovery evidence as ordinary merged history.
