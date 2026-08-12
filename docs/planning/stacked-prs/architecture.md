# Stacked delivery architecture

This is the normative technical companion to [objective.md](objective.md). It records the domain
model, authorities, durable state, projection, mutation protocols, and recovery behavior needed to
keep stacked delivery reconstructable and safe. It deliberately stops short of choosing the
low-level class/file layout.

## Ubiquitous language

| Term | Meaning | Avoid confusing it with |
| --- | --- | --- |
| **Incremental delivery** | The current default: each objective node's plan lands independently. Represented by absence of an objective `delivery` field. | “Serial,” which describes timing rather than integration policy. |
| **Stacked delivery** | The explicit objective policy `delivery: stacked`: plans publish as ordered GitHub-native stacked PRs and intentionally land at objective scope. | A property inferred from PR bases. |
| **Delivery train** | Perk's objective-level ordered delivery construct. It survives objective replan through one delivery lineage. | GitHub's stack resource, which is remote review/merge state only. |
| **Layer** | One non-skipped roadmap node together with its one plan, branch, and PR. | A commit or arbitrary PR created outside the roadmap. |
| **Delivery order** | The deterministic topological order of non-skipped roadmap nodes, using `node_sort_key` to break ties. | Roadmap dependency edges or a persisted position. |
| **Published layer** | A layer whose remote branch, open PR/base, published head checkpoint, and—where applicable—native stack membership have been verified. | Merely having pushed a branch or created a PR. |
| **Published prefix** | The maximal contiguous sequence of published layers from the bottom of delivery order. | Any set of open PRs. |
| **Unpublished suffix** | Every future non-skipped delivery node after the published prefix. It may be reshaped through objective replan or reduced by a backend-native cancellation projected as a skip. | Uncommitted work in an existing worktree. |
| **GitHub stack** | GitHub's native remote resource relating two or more PRs in order. GitHub owns its membership, position, and merge operation. | The delivery train. |
| **Dynamic singleton** | A previously valid stacked objective reduced by later cancellation to one non-skipped layer. It retains stacked lineage and objective-scoped landing although no GitHub stack can exist. | An authored one-node stacked objective, which is rejected. |
| **Delivery lineage** | Stable identity for one delivery train across superseding objectives. Minted for stacked delivery and copied by replan. | Objective ID, which changes on replan. |
| **Predecessor layer** | The immediately preceding layer in delivery order, identified durably by plan identity. The bottom layer has no predecessor plan. | A mutable branch name or observed SHA. |
| **Parent checkpoint** | The verified parent commit from which the current published layer head was built. For the bottom layer, the parent is the objective base. | Planning provenance or the parent's current head forever. |
| **Published-head checkpoint** | The layer branch head last verified after publication or synchronization. | A desired future head or local `HEAD`. |
| **Stack operation** | A journaled, lineage-scoped mutation with exact before/after facts, such as publication, synchronization, adoption, transfer, or landing. | A local rebase attempt before any remote mutation is prepared. |
| **External atomicity breach** | An observed manual contiguous-prefix merge that put only part of a train into the objective base. | A successful perk landing. |

These terms are recorded in the repository's
[objective-delivery glossary](../../../CONTEXT.md#objective-delivery). The glossary carries only
domain meanings; field names, APIs, and recovery algorithms remain in contracts and code.

## One deep module

Stacked delivery should be implemented as one deep Python module, referred to here as the
**delivery module** rather than prescribing a package name. Its interface should be substantially
smaller than its implementation:

```text
reconstruct objective/lineage -> DeliveryTrain
publish     DeliveryTrain + LayerContext -> OperationResult
synchronize DeliveryTrain + changed/adopted layer -> OperationResult
recover     DeliveryTrain + prepared operation -> OperationResult
transfer    old/new objective + DeliveryTrain -> OperationResult
land        complete DeliveryTrain -> OperationResult
```

Every public operation reconstructs fresh state before deciding anything. Mutators return typed
before/after projections and per-effect outcomes; command handlers do not infer success from log
text or recreate stack rules themselves.

The module receives three injected seams:

1. **Train persistence.** A backend-aligned adapter composing the existing `ObjectiveStore` and
   `IssueBackend`. The two interfaces remain useful lifecycle seams, but the selected backend is
   always the same and the delivery module needs one coherent persistence view.
2. **Git.** Fetch, resolve refs, inspect ancestry/worktrees, create the isolated candidate
   worktree, manage temporary refs, rebase, and issue exact-leased atomic pushes.
3. **GitHub-native delivery.** Repository capability, PR reads/writes, rules/reviews/checks,
   native stack reads/create/append, and asynchronous direct merge.

The GitHub seam is explicit rather than a generic stack-provider interface. Perk has no second
implementation to abstract, and Graphite's local/cache semantics are not substitutable for
GitHub's server resource and merge operation.

The TypeScript extension does not manipulate Git, PRs, journals, or backend records. It invokes
Python workers, decodes typed envelopes, and renders results through the existing surfaces module.

## Authorities

One fact has one authority. Other surfaces may cache or corroborate it but cannot silently replace
it.

| Fact | Authority | Notes |
| --- | --- | --- |
| Delivery policy | Active objective header | Absent means incremental; `stacked` is explicit. |
| Objective integration base | Active objective header/config resolution | Immutable after first publication; ordinary base advancement changes its head, not its identity. |
| Roadmap dependency graph | Objective backend | GitHub roadmap block or live Linear Project/node relations. |
| Delivery order | Pure derivation from the roadmap DAG | Deterministic topological sort + `node_sort_key`; never persisted. |
| Node-to-plan identity | Objective node backlink, corroborated by plan metadata | Exactly one plan per non-skipped delivery node. |
| Delivery lineage | Objective and plan metadata | Stable through superseding objectives. |
| Predecessor identity | Plan metadata | Stable plan identity, not a branch ref. |
| Branch content and ancestry | Git refs/objects | Checkpoints corroborate the last verified publication. |
| PR number, base, head, state | GitHub | Plan metadata remembers identity; GitHub is current truth. |
| Native stack membership/order | GitHub | Observed, never copied into objective metadata. |
| Required reviews/checks/rules | GitHub | Read fresh for landing. |
| Prepared/accepted/completed/abandoned operations | Issue/objective backend journal | Strict marked comments: objective issue on GitHub, Project metadata sentinel issue on Linear. |
| Local conflict progress | Disposable operation-local manifest | Useful only on that machine; never sufficient to mutate remote state. |
| Worktree cleanliness/ownership | Live local/remote execution state | A precondition, not persisted train topology. |

## Durable logical records

The field names below are recommended contract vocabulary, not a mandate on whether GitHub stores
them in a metadata block/comment or Linear stores them in an attachment/sentinel issue.

### Objective facts

```yaml
delivery: stacked                 # absent for incremental
delivery_lineage: <stable-id>     # stacked only
base: <integration-branch|null>   # existing field
supersedes: <objective|null>      # existing field
superseded_by: <objective|null>   # existing field
```

The roadmap continues to own node identity, status, dependencies, and its existing plan backlink.
No stack number, layer number, native position, branch ancestry, or capability result belongs in
the objective header.

### Plan facts

Every stacked layer's plan needs enough identity and verified checkpoints to reconstruct its place
without local metadata:

```yaml
objective_id: <current-owner>
objective_node_id: <node-id>
delivery_lineage: <stable-id>
predecessor_plan_id: <plan-id|null>
base: <objective-integration-branch|null> # existing field; not the immediate parent
parent_checkpoint_sha: <git-sha|null>
published_head_sha: <git-sha|null>
branch: <branch|null>             # existing staged field
pr: <github-pr|null>              # existing staged field
```

The bottom layer has no predecessor plan. Its `parent_checkpoint_sha` is the verified objective
base commit from which its published head was built. Higher layers record the predecessor head
used for their current published ancestry.

The existing plan `base` retains one meaning across delivery policies: the objective's ultimate
integration target. It no longer doubles as the worktree start point for stacked child layers.
`predecessor_plan_id` identifies the immediate logical parent; reconstruction resolves that plan's
branch, and `parent_checkpoint_sha` records the exact ancestry edge last verified.

The checkpoint pair is updated together only after publication verification. Before publication,
both may be absent. A mismatch between recorded checkpoints and live refs is classified; it is not
silently repaired.

No plan stores `planned_against_parent_sha`, native stack position, or an independent copy of the
objective's delivery policy. `delivery_lineage` is sufficient to route plan operations into the
train, including after objective replan.

### Operation journal

The logical journal is append-only and physically carried by one strict, schema-versioned marked
comment per event:

- GitHub appends to the objective issue's comments.
- Linear appends to the existing Project metadata sentinel issue's comments.

The canonical marker carries the deterministic operation/event identity:

```text
<!-- perk:stack-operation-event:<operation-id>:<event-role> -->
```

Linear may apply its existing safe HTML-marker transcoding, but the logical key and strict payload
remain identical across backends.

The persistence adapter paginates the complete carrier, ignores unrelated human comments, rejects
malformed perk-marked events, and treats a byte-identical deterministic event key as an idempotent
duplicate. A conflicting duplicate or a detectably edited event is corruption. Perk never edits or
deletes an event. Authorized comment deletion is out-of-band tampering rather than an adversarial
integrity threat this design attempts to make cryptographically detectable; every mutation still
cross-checks live Git/PR/stack/checkpoint facts. Engagement readers recognize and exclude journal
comments as perk machinery. The live backend gate proves pagination, ambiguous append recovery,
and payload limits at the maximum 100-layer prepared record before enabling train mutation.

A prepared record is immutable:

```yaml
event: prepared
operation_id: <ulid>
operation_kind: publish|sync|adopt|transfer|land
delivery_lineage: <stable-id>
objective_id: <objective-at-preparation>
run_id: <initiating-run>
created: <timestamp>
affected_plans: [<ordered-plan-ids>]
before: <kind-specific exact observations>
after: <kind-specific expected observations>
```

Later events refer to `operation_id`:

```yaml
event: accepted|completed|abandoned
operation_id: <ulid>
created: <timestamp>
observed: <verified result or proof of no irreversible effect>
```

`accepted` is permitted only when a remote API returns a recovery handle that cannot be derived
later, currently the async-merge UUID. Observable publication effects do not each create journal
events; recovery reads the branch, PR, native stack, and checkpoints directly. The bounded event
vocabulary avoids turning the journal into a general workflow engine or flooding a large objective
with per-effect comments.

The prepared event is serialized, size-validated, appended, and positively read back immediately
before the first remote effect: branch push for publication, atomic push for sync/adopt, successor
creation for transfer, and async request for land. An ambiguous prepare append blocks the remote
effect until rescanning finds the deterministic event key. Completion is appended only after every
postcondition and checkpoint write is verified; abandonment is legal only after proving every
effect remains at its before state.

The lineage journal may span superseding objectives. New operations append to the active
objective's carrier and reconstruction folds every carrier in the supersession chain. Transfer is
the exception at its boundary: prepare on the predecessor before successor creation, and keep that
operation's later events on the same predecessor carrier rather than copying history.

There is no overwriteable `status` field on the prepared event. Folding the event stream yields
unresolved operations. A lineage normally has at most one unresolved remote-mutating operation;
a second mutator must recover or explicitly abandon the first.

Kind-specific observations:

- **Publish/sync/adopt:** ordered branch refs with exact before/after SHAs, expected PR bases and
  heads, and expected native membership after convergence.
- **Transfer:** old/new objective IDs, old/new node ownership, and the exact ordered published plan
  prefix.
- **Land:** ordered node/plan/PR identities, every incremental base SHA and head SHA, merge method,
  target objective base; the later accepted event carries the GitHub async operation UUID.

Journal records need not store full diffs. The immutable PR identity plus incremental base/head
SHAs, followed after merge by each merge-commit SHA and final objective-base SHA, are sufficient to
retrieve or reconstruct evidence from Git objects, `refs/pull/<n>/head`, or PR diff/files/commits
APIs. Full patches are unbounded and generated summaries are lossy, so neither is stored. If exact
evidence becomes unavailable, reconciliation remains loudly retryable.

## Reconstructing `DeliveryTrain`

Reconstruction is a pure orchestration pipeline over adapters:

1. Resolve the requested objective, following supersession to the active objective for its
   delivery lineage when appropriate.
2. Read the objective header and roadmap from the selected backend.
3. Fold journal events ONCE and fetch remote refs — both BEFORE any cancellation
   normalization, because unresolved facts, publication coverage, and the cancellation proof
   all read them (local refs/worktrees are observed without treating absence as an error).
4. Normalize backend-observed status, including Linear cancellation of unpublished future nodes —
   fail-closed and projection-only: a native cancellation contracts only under the exact
   safe-contraction proof (a clean, coherent plan backlink — and abandoned-only publication
   history — is acceptable; any identity conflict, checkpoint or PR claim, completed or
   unresolved publication, remote branch, or branch-owned PR in any state is not); anything
   unprovable stays a visible `canceled` layer
   with blockers, and the persisted status is never changed by the read.
5. Validate the DAG and derive deterministic delivery order from non-skipped nodes. Reject fewer
   than two only at authoring; at runtime classify cancellation-derived one/zero-layer results as a
   dynamic singleton or all-skipped projection (status describes the projection only — singleton
   landing and all-skipped completion are landing-time behavior, not status claims).
6. Join every node to exactly one plan (idempotent — a plan preloaded by the cancellation proof
   is never re-joined); load its plan header and staged branch/PR facts.
7. Resolve predecessor plan identities from canonical order and compare them to stored identities.
8. Identify an unresolved operation from the fold, if any.
9. Fetch each PR and its actual base/head/state.
10. For two or more PRs, fetch GitHub native stack membership and order through a member PR.
11. Classify every layer and train-wide invariant.

The result is one immutable projection. Suggested layer state is orthogonal rather than a single
lossy enum:

```text
intent:       skipped | unplanned | planned | canceled
publication: unpublished | published | publication_drift
git:          absent | synced | local_ahead | remote_ahead | diverged | wrong_parent
pr:           absent | draft | ready | merged | closed | wrong_base
membership:   not_applicable | absent | exact | divergent
writer:       free | active | dirty
finalization: not_merged | merged | finalized
```

Train-wide derived facts include delivery order, published prefix length, next build-ready node,
structural drift, active operation, capability blockers, landing readiness, and informational
review-thread counts.

The projection separates **blockers** from **information**. For example, an unresolved required
review is a landing blocker; unresolved advisory threads are information; an absent native stack
for one published PR is not applicable; an absent stack for two PRs is a publication blocker.

## Capability and API convergence

Probe atomic-push support against the same authenticated push endpoint the mutator will use:

```text
git -c push.pushOption= push --atomic --dry-run --no-verify --no-signed \
  --no-follow-tags --recurse-submodules=no --porcelain \
  <push-endpoint> <observed-base-sha>:refs/heads/<base>
```

The no-op command reaches receive-pack and proves that it advertises atomic transactions, while
`--dry-run` sends no update commands. It does not prove write permission, ruleset acceptance,
leases, or future availability. Multiple push URLs are probed individually or rejected. Every real
mutation still uses `--atomic` plus exact leases and remains authoritative.

GitHub's stack create/append API has no client idempotency key. Perk's prepared operation and exact
membership observations supply it. Before mutation, wait until every PR exposes its expected
head/base and belongs to no other stack. After `2xx`, an ambiguous timeout/network/`5xx`, or a
validation/conflict response, reread the known stack or rediscover it through a member PR:

- exact desired membership is success;
- exact recorded before-state may retry after the settling interval;
- partial, reordered, extra, or different-stack membership is drift.

Mutations are serialized, rate-limit/`Retry-After` signals are honored, and retries never serve as
a substitute for read convergence.

## Publication protocol

Publication of a new layer is an idempotent convergence operation:

1. Reconstruct and require that the candidate is exactly the next delivery node.
2. Recheck GitHub stack and Git atomic-push capabilities.
3. Resolve the current local candidate, predecessor remote head, and exact remote head lease (or
   ref absence for a first push).
4. Require the candidate to contain the predecessor head and no unexplained topology.
5. Append/read back the prepared operation, then push the branch using the Git adapter.
6. Create or converge the PR to the predecessor branch, or objective base for the bottom layer.
7. At layer two create native membership; later append only an exact missing suffix.
8. Refetch branch, PR, and native stack.
9. Require all expected postconditions.
10. Persist plan branch/PR identity and checkpoint pair, then complete the operation.

The encompassing prepared operation contains the ordered expected branch, PR, registration, and
checkpoint effects. A crash after pushing and before registration reconstructs as “branch after,
PR/stack incomplete”; after PR creation it discovers the unique PR by exact head selector; after
registration it refetches native membership. Per-effect journal comments are unnecessary because
each state is remotely observable.

Publication never unlocks the next layer merely because the branch push succeeded. The full
published-layer definition is load-bearing.

## Synchronization protocol

### Preflight and candidate calculation

Sync's operation universe is the **checkpoint-claimed prefix** — the maximal contiguous bottom
run of layers carrying plan identity, a branch, a PR number, and the full checkpoint pair —
never the classifier's verified published prefix (which truncates on exactly the discrepancies
sync exists to diagnose, making the drift refusals unreachable). Given a changed claimed layer,
the affected set is that layer through the top of the claimed prefix. Unpublished future work is
excluded.

Preflight runs over **every claimed layer** (not just the affected set — a drifted or held
claimed layer above the trigger must block a lower-layer cascade, and the affected set is only
derivable once the whole claimed world is verified) and requires:

- no unresolved lineage operation except one being recovered;
- no structural identity/topology blockers on the reconstruction (a mis-owned or mis-linked
  claimed plan must never be checkpointed);
- no active remote implement/address writer on a claimed plan;
- no dirty claimed worktree (a clean checked-out one does not block — the normal state of the
  just-amended layer);
- exact remote refs and PR heads consistent with their checkpoints, unless one layer is the
  explicitly adopted remote change;
- exact PR base chain and native composition; and
- atomic-push support.

Contracts §8.49 is the authoritative statement of the implemented protocol; this section is the
design rationale.

Use one isolated worktree for the operation, with temporary refs for all candidate heads. Rebase
bottom-up using each layer's stored parent checkpoint as the old ancestry edge and the newly
calculated predecessor head as the new edge. Do not move the user's checked-out refs during this
calculation.

If any rebase conflicts, stop before preparing a remote operation. Keep a tiny local manifest with
the operation inputs and temporary refs only so that a user can continue or abort on that machine.
A resumed calculation must reconstruct the train and verify that every captured remote/checkpoint
input still matches before it may proceed.

> **Status:** the cold sync writes the continuation manifest and retains the conflicted worktree;
> `--continue`/`--abort` now consume it after fresh-input revalidation (contracts §8.49), and
> `stack recover` reports/concludes unresolved operations and sweeps orphaned residue (§8.51).

`objective stack sync --continue` and `--abort` own this pre-journal local state. Durable
`objective stack recover` is not used because no remote boundary was crossed. A dirty worktree or
active writer blocks before candidate calculation; perk never rewrites that branch during sync or
delivery-policy conversion.

### Atomic publication

Once every candidate head exists:

1. Write the prepared operation containing every exact before/after branch SHA.
2. Push all affected branch refs in one `--atomic` operation with one explicit
   `--force-with-lease=<ref>:<before-sha>` per existing ref.
3. On any rejection, assume no ref changed, refetch, and classify. Never retry individual refs.
4. Refetch all branches and PRs, verify ancestry, heads, bases, and native composition.
5. Update every layer's checkpoint pair.
6. Append completion.

The prepared record makes a lost client response recoverable. Exact leases make competing clients
safe without pretending the issue backend is a distributed lock.

Advancement of the objective base ref is normal. Status reports it, and explicit sync may treat the
new base head as the bottom layer's new parent and cascade the complete published train. Landing
does not silently perform that rewrite: it proceeds without sync only when GitHub considers the
exact train mergeable and every rule passes; otherwise it returns the copyable sync command.

### Adoption

> **Status:** `sync --adopt` and its `--dry-run` preview are landed (contracts §8.49), with
> deliberate adoption confirm-gated on the warm surface (§8.51).

`sync --adopt NODE` changes only the classification of one known remote difference: after a dry
run and confirmation, that observed remote head becomes the intentional candidate head for the
selected layer. Every upper published layer is still recalculated and atomically pushed. Adoption
does not accept wrong PR bases, native composition edits, non-prefix topology, or multiple
unexplained changed layers.

## Replan transfer protocol

Replan is a cross-object transaction without a shared backend transaction primitive, so it uses
convergence:

1. Reconstruct the old train and establish its exact published prefix.
2. Validate the proposed successor: before publication any policy is valid; afterward it must
   preserve stacked delivery, objective base, lineage, and prefix plan order.
3. Append/read back the prepared transfer event on the predecessor carrier.
4. Create the successor objective first, carrying delivery lineage and a transfer manifest that
   names the old objective and exact prefix.
5. Move or update unfinished node ownership using backend-native operations, preserving plan and
   node-issue identity where Linear supports it.
6. Update each published plan's `objective_id` and `objective_node_id` to its successor owner.
7. Reconstruct the successor and verify the entire prefix plus unpublished suffix.
8. Stamp the bidirectional supersession relationship and close the old objective last.
9. Complete the transfer operation on the predecessor carrier.

A retry searches for the already-created successor and manifest rather than minting another one.
The old objective stays open on an incomplete transfer so the train never disappears behind a
prematurely closed source.

Before first publication, carried plan identities survive a policy change. Replan atomically
rewrites or clears their lineage, predecessor, and checkpoint metadata but never rewrites a local
branch. Clean unpublished commits catch up through the next implement/submit preparation. Any
dirty worktree or active writer blocks conversion. An existing remote PR already makes the layer
published, so this conversion path no longer applies.

## Landing protocol

### Preflight

Landing requires a complete published train. It reads fresh rather than trusting a prior status:

- objective and lineage are active and not transferring;
- no unresolved non-land operation exists;
- no affected writer or dirty worktree exists;
- every layer is published with exact checkpoints;
- every PR is open, ready, conflict-free, and in the exact base/membership order;
- required checks, reviews, and rules pass;
- advisory review-thread counts are collected but do not block;
- the objective base permits direct merge and GitHub still offers the native operation.

A dynamic singleton uses the same preflight but treats native membership as not applicable and
performs one ordinary direct squash merge through the objective operation. A zero-layer
all-skipped objective has nothing to merge and proceeds directly to objective completion.

The readiness projection reads exact head/base refs, `mergeable`, `mergeStateStatus`,
`reviewDecision`, required status/check contexts, and unresolved thread counts through **per-PR
strict paginated GraphQL reads** (the implemented transport, superseding this document's earlier
one-batched-query sketch: GitHub offers no cross-PR snapshot consistency, per-alias pagination is
inexpressible, and the mutation re-verifies the top SHA at submit time anyway). Each per-PR read
repeats the scalars on every page and refuses the whole read when any repeated scalar changes
between pages (the scalar-coherence guard), so checks/threads from different commits are never
combined. Conflicting, changes-requested/review-required, failed/unfinished required checks,
`BEHIND`, and aggregate `BLOCKED` states block. Unknown mergeability/rules are transient blockers.
Optional failing checks do not block by themselves. Unresolved threads are informational unless an
enforced conversation-resolution rule is what makes GitHub report the PR blocked.

The dry run renders bottom-to-top layers, exact SHAs, rules, informational comments, and every
blocker. No `--force` bypass exists for structural or repository-rule blockers.

### Merge and observation

Before calling GitHub, append a prepared land record with exact per-layer evidence. Submit
`PUT /pulls/{top_pr}/merge-async` with `merge_action: direct_merge`, `merge_method: squash`, and the
verified top `sha`. A `202 pending` or compatible existing `409 pending` supplies a UUID; append it
as `accepted` only after verifying the accepted options match the prepared request. A `200 merged`
is already terminal. Retry an ambiguous submit only with the identical SHA-pinned request so a
`409` can recover the original handle.

Poll the UUID once per second for 60 seconds. Timeout means accepted/pending observation, not
failure or success, and recovery never sends another request while the operation can remain
active. The documented wire states are `pending`, `merged`, `enqueued`, and `failed`: terminal
`failed` means atomic non-application; `enqueued` after the explicit direct request is an
unexpected protocol/capability state. A merged response still requires exact per-PR verification.
If the handle expires after its 24-hour availability window, recover from PR/ref/base facts:

- every remaining PR merged: complete the merge observation and begin finalization;
- every remaining PR still open and GitHub says the operation failed/not applied: append a failed
  or abandoned outcome that accurately permits retry;
- a contiguous merged prefix caused externally: record an external atomicity breach and enter the
  degraded recovery path;
- any non-prefix merged/closed state: structural drift, no automatic mutation.

### External contiguous-prefix recovery

An external prefix merge cannot be undone. Recovery:

1. records which exact prefix merged and that perk did not provide atomic landing;
2. treats the objective base's new head as the parent of the first remaining layer;
3. runs the normal transactional synchronization protocol over every remaining published layer;
4. verifies GitHub's remaining stack composition; and
5. atomically lands the remainder when it is ready.

This preserves safety for future changes without misrepresenting the already-partial integration.

### Finalization

For each confirmed merged PR, run a shared idempotent plan finalizer. Its result must expose each
secondary effect rather than collapse them into “land failed.” Finalization may partially progress
across plans and invocations. The source of truth remains: GitHub says whether code merged; the
backend says which bookkeeping converged.

Only after every merged plan is finalized and every roadmap node is terminal should perk close the
objective and launch one objective reconciliation. Reconciliation receives the journal's ordered
layer evidence, not whatever diff happens to be visible from the current checkout. Persist PR
identity, incremental base/head SHAs, each observed merge-commit SHA, and final objective-base SHA;
retrieve exact diffs through Git objects, pull refs, or PR APIs. If all exact evidence is
unavailable, finalization remains loudly retryable rather than falling back to a lossy summary.

## Command ownership

The cold CLI namespace reflects the domain split:

| Command | Module operation | Mutates |
| --- | --- | --- |
| `perk objective stack status` | `reconstruct` | Nothing |
| `perk objective stack sync` | `synchronize` or `adopt` | Published branch suffix, then checkpoints |
| `perk objective stack recover` | `recover` | Only effects required to conclude an existing prepared operation |
| `perk objective stack land` | `land` | GitHub stack merge, then idempotent bookkeeping |

> **Status (landed vs deferred):** `stack status`, the complete `stack sync` control surface,
> `stack recover`, and the warm `/objective-*` gestures are landed (contracts §8.49/§8.51).
> Automatic submit/address suffix propagation is also landed (§8.52). The readiness dry-run
> (`stack land --dry-run`, contracts §8.55) and the landing mutation (bare `stack land` +
> `/objective-land`, contracts §8.56) are landed; interrupted-landing recovery and the
> ordered-journal-evidence objective reconciliation remain deferred (`stack recover` keeps
> LAND rows report-only).

An explicit objective argument wins; otherwise only the active plan/worktree may supply it. Perk
does not search and guess among open objectives. Status is confirmation-free. Adopt, abandonment,
and landing confirm interactively or require `--yes` headlessly; deterministic roll-forward
recovery does not ask twice. When several unresolved operations are detected, recovery requires an
explicit operation ID.

Warm human commands remain gesture-oriented rather than mirroring the cold subgroup mechanically:

```text
/objective-stack    status
/objective-sync     sync | adopt | continue | abort
/objective-recover  durable-operation recovery
/objective-land     objective-scoped landing
```

Each model operation has its own typed tool; there is no broad mutation action enum.

Existing lifecycle commands remain owners of their gestures:

- objective author/save chooses and creates the policy;
- objective plan selects the next build-ready node;
- implement creates a worktree from `LayerContext`;
- submit publishes a layer and may synchronize a changed published suffix;
- address fixes one layer and invokes synchronization afterward;
- ready changes one PR's review state;
- objective replan changes the unpublished roadmap and transfers lineage;
- ordinary land refuses stacked-lineage plans.

This prevents the subgroup from becoming a competing workflow with `stack create`, `stack add`, or
`stack submit` commands.

## Recovery matrix

| Observed condition | Safe interpretation | Recovery |
| --- | --- | --- |
| Prepared ref operation; all refs equal `before` | Atomic push did not apply. | Retry after confirmation, or explicitly abandon after proof. |
| Prepared ref operation; all refs equal `after` | Atomic push applied; client lost later progress. | Roll forward automatically: verify PR/stack effects, write checkpoints, append completion. |
| Prepared ref operation; mixed before/after | Claimed atomicity is contradicted or refs changed independently. | Fail closed; diagnose remote/transport behavior and repair explicitly. |
| Prepared ref operation; an unrelated SHA appears | Out-of-band mutation or competing actor. | Fail closed; explicit adopt only if it is one intentional layer change. |
| Local candidate rebase conflicts before journal | No remote effect. | Continue or abort disposable candidate work after revalidation. |
| Publication branch exists, PR absent/wrong | Publication interrupted between effects. | Recover idempotently from recorded branch and expected PR base. |
| PR chain exact, native membership absent | Registration incomplete. | Create/append only if the observed PR prefix is exact. |
| Native stack reordered/contains extras | Independent structural edit. | Human repair or replan; never recreate automatically. |
| Replan successor exists, transfer partial | Cross-backend write interruption. | Resume from transfer manifest; keep old objective open. |
| Land prepared, every PR open | Merge not observed. | Query async operation; retry only after a definitive non-applied result. |
| Land prepared, every PR merged | Merge succeeded. | Finalize plans and objective without remerging. |
| Manual contiguous prefix merged | Irreversible external atomicity breach. | Record, sync remaining suffix to base, land remainder atomically. |
| Non-prefix PR merged or layer closed | Structural train corruption. | Fail closed; human repair/replan. |
| Merge complete, some finalization missing | Code landed; bookkeeping incomplete. | Retry only missing idempotent finalization effects. |
| Valid train canceled down to one unpublished/published layer | Dynamic singleton; native membership is inapplicable. | Land the sole PR only through objective-scoped direct squash merge. |
| Every delivery node skipped | Nothing remains to merge. | Complete the objective without a landing mutation. |

## Verification strategy

`just test` and `just ci` remain hermetic. Gateway fakes and tolerant boundary fixtures cover stack
create/append convergence, exact Git commands, all async submit/poll states, required versus
optional checks, journal failure injection, and every recovery row above.

Preview availability and server behavior get a separate operator-run dogfood in a designated
durable repository configured for stacks, squash direct merge, no queue, and one stable required
workflow. The publication gate records objective/plan/PR/stack identities and reconstructs from a
fresh clone. The landing gate records before SHAs, merge UUID and terminal result, per-PR merge
SHAs, final base SHA, final backend state, and one intentionally interrupted recovery. Successful
runs remain ordinary merged history; no recurring network CI or destructive reset script is
introduced.

## What perk carries forward from erk

The erk/Graphite implementation established several useful realities:

- a layer needs a stable non-trunk parent identity;
- changing a lower layer requires a bottom-up cascade;
- submit is best understood as validate, mutate, then verify;
- operators need a compact stack indicator and explicit troubleshooting path; and
- checkout, sync, submit, and land all need to agree on one topology.

This architecture keeps those lessons but rejects the parts that made recovery ambiguous:

| erk/Graphite behavior | Stacked-delivery decision |
| --- | --- |
| Graphite/local cache participated in topology authority. | Objective/plan backend + Git/GitHub reconstruct the train; local metadata is disposable. |
| Branch-manager selection and Graphite compatibility shaped the interface. | One GitHub-native adapter; no generic branch manager. |
| Sync mutated real branches/worktrees bottom-up and could skip a branch checked out elsewhere. | Calculate in one isolated worktree; an active/dirty writer blocks before remote mutation. |
| Earlier local mutations could remain when a later rebase failed. | Temporary refs contain candidates; conflict changes no remote branch or user worktree. |
| Force pushes happened layer by layer. | One atomic multi-ref push with exact leases; no sequential fallback. |
| Landing merged PRs sequentially and could partially integrate the stack. | One GitHub-native atomic direct stack merge; external prefixes are degraded recovery only. |
| Stack state was primarily machine-local. | Append-only backend journal enables second-machine recovery. |

The result is not a port of erk. It is the smallest model that preserves its proven workflow value
while using GitHub's first-party resource and perk's objective/plan storage as durable context.
