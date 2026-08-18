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

Stacked delivery is one deep Python package with a deliberately small repository-scoped public
front door. Construction is inert; status and every preparation use the same service:

```text
resolve_delivery(repo_root) -> Delivery                  # ZERO I/O
Delivery.status(StatusRequest {objective_id}) -> StatusResult
StatusResult -> exactly one of DeliveryTrain | no_train_reason
Delivery.prepare(PrepareRequest {kind, mode?, base?, objective_id?, node_id?, plan_id?})
  -> PrepareResult {kind, base?, identity?, notice?, planning?, layer?, parent_sha?, replan?}
Delivery.transfer(TransferRequest {predecessor_id, run_id, title, prose, base?, roadmap_nodes,
                                   carry_map, delivery})
  -> TransferResult {predecessor_id, successor, operation facts}
Delivery.publish(PublishRequest {kind, plan_id, dry_run?, delivery?, objective_id?, run_id?,
                                 trigger_run_id?})
  -> PublishResult {kind, canonical plan_id, dry_run, exactly one of Layer | Ready}
Delivery.sync(SyncRequest {mode, objective_id, run_id?, include_base?, dry_run?, adopt_node?,
                           trigger_plan_id?, trigger_run_id?}, consent=...)
  -> SyncResult {operation/result facts; nested Layer, Cascade, AbortPreview}
Delivery.recover(RecoverRequest {kind=operation_conclusion|cancellation_metadata,
                                 objective_id, action?, dry_run?, operation_id?}, consent=...)
  -> RecoverResult {kind; exactly one of OperationConclusion | CancellationMetadata}
Delivery.land(LandRequest {kind=plan|objective, plan_id?, branch?, objective_id?,
                           consumed_learn?, delivery_lineage?, dry_run?, run_id?},
              consent=...)
  -> LandResult {kind; exactly one of Plan | Objective}
```

Prepare is a closed flat family: authoring capability; replan facts from one objective snapshot;
strict/best-effort plan identity; planning layer start; and execution layer start. Frozen nested
records carry variant details and illegal request/result combinations fail at construction.
`TransferRequest` is frozen intent only; Transfer validates recoverability before I/O and owns the
single under-lock predecessor read, route, aggregate authority binding, and bounded errors.
`SyncRequest` is likewise a closed mode/field
matrix; `SyncResult` deliberately remains additive operation-produced data without new combination
guards. `PublishRequest` is a closed layer/ready matrix; `PublishResult` has exact nested
`Layer`/`Ready` details and carries nested cascade facts as `SyncResult` directly. The pure
`DeliveryTrain` reconstruction, private capability rows, internal `LayerContext`/layer core,
publication/synchronization engines and runtimes, and production adapters are not package-root
APIs. `DeliveryError` is the bounded status + Prepare + Transfer + Publish + sync + Recover + Land
hierarchy; status still translates only its exact six-code subset, while every Publish and Land
error carries joint phase/origin metadata (plan-variant Land: domain refusals `stacked_plan` /
`plan_not_found` / `no_pr` vs the `github_error` infra translation under the `land` phase —
no Git authority call exists on that path, so no speculative `git_error` arm; objective-variant
Land adds `land_drift` / `land_failed` / `merge_async_unavailable` / `merge_request_conflict`
plus the reconstruction origin-by-code rule, contracts §8.56). Claimed-prefix/continuation/writer/record-recovery vocabulary stays
internal. The package root has exactly the canonical **20 exports** (`Delivery`,
`resolve_delivery`, `DeliveryError`, the three authority ABCs, and the seven request/result
families); the recovery and land
context/runtime/adapters remain internal, there is no `recover_operations` or `RecoverError`
compatibility path, the post-merge finalization family (`finalize_landed_plan`,
`LandedPlan`, `LandFinalization`, `ObjectiveLandUpdate`, `LearnConsumeUpdate`) plus
`squash_commit_message` are package-internal module-path consumers only, and the atomic
objective-landing migration retired the last compatibility exports (the eleven readiness
names, the four landing names — `land_train` and `LandError` deleted outright —
`GatewayLandObservations`, and the seventeen journal + six persistence names whose only
public purpose was the unmigrated landing path).

The final import census closed with the package root as the only public import path. Outside
the package, production code references `perk.delivery` submodules solely for: the nested
render vocabulary command modules need to present typed results (the `train` projections and
the `land`/`landing` readiness and evidence records); the deliberately retained read-only
helpers (`train.resolve_active_objective` — the supersession forward walk every stack command
shares — `recover.observe_orphans`, `continuation.pending_continuation`, and
`diagnostics.classify_finding`); and the internal layer-context records the worktree cache
writes (`layer.LayerContext`/`LayerContextOut`). No production caller invokes delivery
mechanics — publication, synchronization, transfer, recovery, or landing — outside a façade
operation. The full census record is [final-census.md](final-census.md).

`RecoverRequest` is a strict
two-kind family — `operation_conclusion` plus the `cancellation_metadata` repair variant
(report-only action, no operation target, no consent) — and `RecoverResult` is the matching
strict wrapper: one kind↔detail guard over nested `OperationConclusion` (the complete
operation report and consent previews) and `CancellationMetadata` (per-candidate
`CancellationAction` rows, the separate failed action, aborted/dry-run/unavailable facts),
with no forwarding properties. `LandRequest` is the complete flat kind-guarded Land family:
`kind="plan"` (the incremental `perk pr land` operation; reconstructed caller intent,
`plan_id` carried verbatim) beside `kind="objective"` (the §8.55 readiness preview on
`dry_run` and the §8.56 atomic mutation, which requires a `run_id` while the preview forbids
one). The flat shape gives the plan-ref-derived intent fields dataclass defaults — the
accepted residual documented in contracts §8.4 (header-half refusal + exact-request pins are
the mitigation). `LandResult` is the strict kind↔detail wrapper: nested
`PrSummary`/`ObjectiveUpdate`/`LearnUpdate`/`Plan` records for the plan variant, and the
`Objective` detail embedding the §8.55 `land.LandReadiness` projection as-is (the
`StatusResult.train` precedent) plus the mutation facts — `outcome: null` marks exactly the
dry-run preview and the in-band BLOCKED refusal (the CLI owns the `land_blocked` exit-code
policy). `Delivery.land` carries the realized consent keyword: the objective mutation's
confirmation callback (`None` auto-approves), rejected with `ValueError` on the
non-mutating shapes (`kind="plan"` and the objective dry-run); the objective mutation also
owns the stack-operation lock (runtime-bound, held from reconstruction through close; the
preview is lock-free). Landing evidence stays
deferred/type-only so importing the package does not create a façade↔landing cycle
(`landing.py` imports the façade at runtime; the façade reaches the engine only inside
`Delivery.land`).

The façade receives three nominal aggregate authorities:

1. **`DeliveryPersistence`.** A backend-aligned authority composing the existing
   `ObjectiveStore`, `IssueBackend`, and train persistence for objective/plan/journal reads,
   plan-body/header effects, prepared/outcome appends, checkpoint-pair writes, transfer carry
   normalization, successor lookup/creation, supersession finalization, and state-aware objective
   close for recovery convergence.
   Production backend selection is deferred
   until the first persistence operation, is cached only after the backend identities agree, and
   leaves no partial selection after a failed attempt.
2. **`DeliveryGit`.** A bound read-only repository root; trunk detection; broad/exact-ref fetch;
   repository- or worktree-scoped commit resolution; ref/ancestry/worktree/base observation;
   publication's single-ref exact-lease push; Prepare's push-URL resolution + no-op atomic probe;
   and sync's genuine Git operations: one
   exact-leased atomic multi-ref push, temp-ref update/delete/list, isolated detached worktree
   add/remove/prune, detached checkout/rebase, retained-worktree rebase/dirty state, and recovery's
   complete worktree-admin path inventory (including stale entries). Existing
   substrate Git records/results/errors are reused unchanged; config/lock/continuation/path/clock
   helpers are not Git authority methods.
3. **`DeliveryGitHub`.** Stable PR facts, tolerant native-stack membership, rich all-state
   branch-owned PR lookup, strict rich stack facts, and authoring Prepare's host stack-capability +
   base merge-rule facts; publication/ready add only distinct full-PR reads and PR/stack mutations,
   while sync adds active-writer observation with adapter-owned exact trigger corroboration. The
   widened branch/strict-stack endpoints are reused rather than duplicated. Recovery additionally
   uses the total async merge-handle probe and strict merged-evidence read through this same
   aggregate, and objective landing consumes them too (the probe as its poll; the evidence for
   re-observation, verification, and abandon proof) beside its three owned additions
   (`pr_land_facts`, `submit_merge_async`, `merge_pr_direct`). Landing-readiness observations
   are aggregate-backed package-internal adapters in `observe.py`.

The aggregate growth is exact: publication adds persistence `get_plan_body(*, issue_id)` and
`update_plan_header(*, issue_id, fields)`; Transfer adds carry normalization,
`find_objective`, `supersede_objective`, and `finalize_supersession`; Git adds
`push_with_exact_lease(branch, *, expected_remote_sha)`; GitHub widens/reuses
`pr_for_branch(branch) -> PullRequest|null` and `strict_stack(number) -> StackRestFacts|null`, and
adds `get_pr`, `create_pr`, `update_pr_body`, `update_pr_base`, `reopen_pr`, `mark_pr_ready`,
`create_stack`, and `append_stack`. Recovery adds exactly persistence `close_objective`, Git
`worktree_admin_paths`, and GitHub `merge_async_probe` / `merged_evidence`; the
cancellation-metadata variant adds only the optional persistence capability
`native_cancellation_metadata_writer()` — a concrete default-`None` method overridden by the
lazy production adapter (returning the resolved store exactly when it structurally satisfies
the package-internal writer Protocol) and the owned fake. Incremental land adds exactly abstract
persistence `backend_id()` (the aligned issue-backend identity for backend-branching squash
text — abstract because a wrong silent default would be dishonest) and abstract GitHub
`merge_pr(number, *, commit_message)` (the direct idempotent squash merge returning the
synthetic MERGED view); no default-branch capability is added (that read stays inside the
internal finalizer). Objective landing adds exactly three GitHub methods — `pr_land_facts`
(the rich readiness enrichment, raw-`GitHubError` posture), `submit_merge_async` (total),
and `merge_pr_direct` (total, SHA-pinned — distinct from the non-pinned incremental
`merge_pr`) — and deliberately **reuses** the recovery aggregate's `merge_async_probe` as
its poll and `merged_evidence` for re-observation/verification/abandon proof (no duplicate
endpoints); the landing observations adapter (`observe.GatewayLandObservations`, now
package-internal over the aggregate) and the fail-closed `observe._AggregateWriterProbe`
(which retired `perk.run.writer_probe.GhaRemoteWriterProbe`) are constructed by the engine
from the bound GitHub authority. No parallel branch/stack/objective authority is introduced.

The nominal interfaces make authority ownership explicit and support small owned in-memory fakes;
interface, real adapter, and constructor-configured fake move together. Calls that authoring
Prepare must classify and continue return frozen nested success/error discriminants; only the real
adapter catches expected Git/GitHub exceptions. Identity Prepare catches only the three expected
persistence families at its boundary; unexpected programming errors propagate. Another subgateway
layer would currently be shallower than these aggregate interfaces, so none is added. The façade
composes the pure projection by passing aggregates into narrower roles and owns each Prepare
variant's authority ordering.

Construction is assignment-only: no config, credentials, subprocess, Git, or network access occurs
until a method needs the corresponding authority. Status preserves branch-sensitive laziness: an
incremental objective returns its successful no-train result before trunk detection, fetch, or
GitHub observation. Authoring never touches persistence; identity performs one objective read;
planning performs one status reconstruction; execution performs status followed by exact parent
fetch/verification; replan performs one objective read and, only for stacked delivery, a journal
read plus bound status classification. Transfer binds the same aggregates into the retained
private recovery seams and a fresh-only aggregate carrier; its runtime owns only lock/id/clock.
Recover binds those same aggregates plus the façade's cause-aware status bridge into one private
context. Its private runtime contains only worktree-root resolution, one shared lock, local
manifest/directory enumeration, the package-internal per-layer finalizer, sleep, and clock;
config resolves before the lock, which is then held through consent, reclassification,
convergence, metadata reads, and the final sweep. Publish binds the same authorities plus bound
status/sync into one private context; its private runtime owns only
clock/sleep/id/PR-body validation. Plan-variant land binds the three aggregates into one private
context; its private runtime holds only the package-internal per-layer
finalizer. Objective-variant land binds persistence + GitHub plus the façade's cause-preserving
train-reconstruction bridge into its own private context; its private runtime holds the same
package-internal finalizer plus the operation lock, sleep, and clock (the sync/recover runtime shape),
and the mutation arm holds that lock from reconstruction through consent, merge, verification,
finalization, and close. Both Publish dry-run arms and the plan-variant Land dry-run
return before every authority call (the objective dry-run is an online read — reconstruction +
fresh observations — just lock/consent/run-id-free). Every effectful operation still
reconstructs fresh state before
deciding anything. Mutators return typed
before/after projections and per-effect outcomes; command handlers do not infer success from log
text or recreate stack rules themselves.

The GitHub seam is explicit rather than a generic stack-provider interface. Perk has no second
implementation to abstract, and Graphite's local/cache semantics are not substitutable for
GitHub's server resource and merge operation.

The TypeScript extension does not manipulate Git, PRs, journals, or backend records. It invokes
Python workers, decodes typed envelopes, and renders results through the existing surfaces module.

## Authorities

One fact has one authority. Other surfaces may cache or corroborate it but cannot silently replace
it. The façade does not invent a fourth authority: its three nominal adapters aggregate the
existing persistence, Git, and GitHub rows below. The pure status projection decides from their
observations; each Prepare/Publish variant orders only the authority reads it owns. The
repository path held by an adapter is composition context, not evidence; backend selection is
cached only after objective/issue alignment succeeds. Plan identity and planning presentation use
their one captured persistence/train snapshot; execution additionally trusts only the exact
parent ref fetched and resolved by the Git authority.

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

`Delivery.status` is the repository boundary: it invokes the internal pure reconstruction exactly
once and converts the answer into the explicit `StatusResult` train/no-train branches. Stable
pure-core failures cross that boundary only through the bounded `DeliveryError` vocabulary.
Reconstruction itself remains a pure orchestration pipeline over injected authorities:

1. Resolve the requested objective, following supersession to the active objective for its
   delivery lineage when appropriate.
2. Read the objective header and roadmap from the selected backend; incremental policy returns the
   successful no-train result immediately, before fallback trunk, fetch, or GitHub reads.
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
9. Resolve the objective base: use its pinned header value when present, otherwise call
   `DeliveryGit.trunk_branch` at this decision point rather than during service construction.
10. Fetch each PR and its actual base/head/state.
11. For two or more PRs, fetch GitHub native stack membership and order through a member PR.
12. Classify every layer and train-wide invariant.

The result is one immutable projection. It also captures the active objective title and exact
node tuple for planning Prepare. Those are internal projection inputs with defaults for pure
callers; status output intentionally omits them, so adding planning authority does not grow or
change human/JSON status bytes. Suggested layer state is orthogonal rather than a single lossy
enum:

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

Stacked objective creation calls
`Delivery.prepare(PrepareRequest(kind="authoring", base=<stored-base-or-null>))`; the façade
resolves a null base through the Git authority, then observes native-stack, merge-rules, remote-base,
and one atomic-push row per configured URL in that order. Independent failures aggregate into one
bounded refusal; push probing is skipped without a positive remote-base SHA. A successful compact
`PrepareResult` deliberately does not expose rows or claim repository preview enrollment/write
permission. Dry-run creation never constructs the service or calls Prepare.

Plan save uses identity Prepare for one-snapshot base + `PlanIdentity` derivation. Strict mode is
reserved for real node-linked saves; objective-only saves and dry runs are best-effort. With no
node, policy/lineage/order are irrelevant; with a node, the pure identity rules enforce stacked
lineage, membership, and linked predecessor before any write. Every plan-header write arm gets the
entire identity trio, while `PlanRef` remains a routing cache containing lineage only.

Real stacked planning uses planning Prepare after the initial objective read has selected policy.
The immutable train is then the sole authority for title, URL, nodes, graph fallback, resumable
claims, base/lineage/order, readiness, and predecessor observations. It returns a closed
`PlanningDecision` rather than mixing expected no-action states with hard failures. The subsequent
node-status mark is observational and non-CAS; it is not a lease or atomic claim.

Fresh local and remote stacked starts independently use execution Prepare. It reconstructs status
once, proves the exact plan is next build-ready, derives the internal layer context, exact-fetches
the latest parent branch, and resolves that remote-tracking ref as a nonblank commit. Local
`worktree add` and remote `checkout -b` are intentionally different gestures over the same result;
neither caller fetches or derives a parent. Deferred publication may reuse the callback-only
internal layer core, which has no repository/global defaults.

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

Publication is realized behind `Delivery.publish(PublishRequest(kind="layer", ...))`. The façade
re-reads the current plan, owns body/header composition, and binds one aggregate context to the
private engine. Cause-aware bridges unwrap only status-oriented Git/GitHub wrappers with the
matching raw cause, preserving the protocol's original per-call classification; all other typed
failures stay typed. Publication itself is lock-free. A lower claimed layer calls the same
façade's bound `sync`, whose dispatcher owns the one non-reentrant operation-lock entry.

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
published-layer definition is load-bearing. The result returns real header/embed/body-check,
stack/checkpoint, resume/no-op, and parent-target facts; automatic cascade carries `SyncResult`
directly rather than copying an operation shape. Submit retains only selection/config,
mergeability diagnostics, Linear mirroring, and presentation.

Draft-to-ready is the other `Delivery.publish` kind. Selection stays in the CLI (explicit canonical
main-root read versus invoking-checkout plan-ref read). Incremental ready intentionally preserves
all-state branch-PR behavior: draft means attempt ready regardless of PR state; non-draft means
idempotent success. Stacked ready reconstructs once, validates target publication before a fresh
non-OPEN race, applies unresolved/structural mutation vetoes only to an OPEN draft, then marks it
ready. Both dry-run kinds are exact authority-free sentinels.

## Synchronization protocol

Synchronization is realized behind `Delivery.sync`. The façade binds its persistence/Git/GitHub
authorities and `Delivery.status` into the private engine context. One immutable private runtime
owns only config, operation lock, continuation containment/manifest/path helpers, clock, sleep, and
operation-id minting; it is not a fourth authority or public dependency seam. The `consent`
keyword is required: callers explicitly provide a callback or deliberately pass `None` for
automation's auto-approval policy. Every mode acquires one operation lock, and every
reconstruction/re-entry uses the bound status call graph.

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

Once every candidate head exists and consent is granted:

1. Re-observe every lease input, then write the prepared operation containing every exact
   before/after branch SHA.
2. Exclude candidate==before refs. Push the remaining set in **zero or one** `--atomic` operation
   with one explicit `--force-with-lease=<ref>:<before-sha>` per existing ref.
3. On any rejection, refetch and classify. Never retry individual refs.
4. Refetch **all affected refs**, including excluded no-op refs, plus PRs; verify ancestry, heads,
   bases, and native composition.
5. Update every layer's checkpoint pair.
6. Append completion.

The prepared record makes a lost client response recoverable. Exact leases make competing clients
safe without pretending the issue backend is a distributed lock. Dry run stops before consent and
journal/push/checkpoint/manifest effects, but candidate work can create local residue; cleanup is
best-effort and any surviving residue is reported for orphan sweep.

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

Replan is a cross-object transaction without a shared backend transaction primitive. The
authoring door first asks `Delivery.prepare(kind=replan)` for one objective snapshot and, for a
stacked predecessor, its journal-gated claimed/open-PR constraints; the command does not
reconstruct or classify delivery itself. The approved save submits one immutable Transfer intent.
Delivery validates its shape before I/O, takes the shared operation lock, performs exactly one
predecessor read/classification, and keeps the lock through plain supersession or the convergence
route:

1. Reconstruct the old train and establish its exact published prefix.
2. Validate the proposed successor: before publication any policy is valid; afterward it must
   preserve stacked delivery, objective base, lineage, and prefix plan order.
3. Append/read back the prepared transfer event on the predecessor carrier.
4. Create the successor objective first, carrying delivery lineage and a transfer manifest that
   names the old objective and exact prefix.
5. Move or update unfinished node ownership using backend-native operations, preserving plan and
   node-issue identity where Linear supports it.
6. Update each published plan through generic grouped header writes: ownership together, stacked
   lineage/predecessor together, or all four stacked fields cleared together.
7. Reconstruct the successor and verify the entire prefix plus unpublished suffix.
8. Stamp the bidirectional supersession relationship and close the old objective last.
9. Complete the transfer operation on the predecessor carrier.

A retry searches for the already-created successor and manifest rather than minting another one.
The old objective stays open on an incomplete journaled transfer so the train never disappears
behind a prematurely closed source. Recovery continues to use the private `TransferSeams`
roll-forward core; fresh callers reach it only through `Delivery.transfer`, whose cause-aware
status bridge preserves domain versus Git/GitHub/store failure classification.

Before first publication, carried plan identities survive a policy change. Replan atomically
rewrites or clears their lineage, predecessor, and checkpoint metadata but never rewrites a local
branch. Clean unpublished commits catch up through the next implement/submit preparation. Any
dirty worktree or active writer blocks conversion. An existing remote PR already makes the layer
published, so this conversion path no longer applies. The non-journaled incremental-to-stacked
route remains only rerun-convergent by construction. Real Linear death after a carried node MOVE
but before ownership/finalization is not proven: without a durable intent record, a later run cannot
safely bind that partial state to the preflighted request. That recovery algorithm requires a
separate behavior design rather than inference in this interface migration.

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
| `perk pr submit` (stacked route) | `Delivery.publish` layer | Layer branch/PR/native stack, then plan identity/checkpoints |
| `perk pr ready` | `Delivery.publish` ready | Draft→ready when required |
| `perk objective stack status` | `Delivery.status` + internal read-only orphan observation | Nothing |
| `perk objective stack sync` | `Delivery.sync` cascade/continue/abort | Published branch suffix, then checkpoints; or retained local conflict state |
| `perk objective stack recover` | `Delivery.recover` operation conclusion | Only effects required to conclude an existing prepared operation |
| `perk objective stack land` | `Delivery.land` objective | GitHub stack merge, then idempotent bookkeeping |
| `perk pr land` | `Delivery.land` plan | PR ready→squash-merge, then idempotent bookkeeping |

> **Status (landed vs deferred):** `stack status`, the complete `stack sync` control surface,
> `stack recover`, and the warm `/objective-*` gestures are landed (contracts §8.49/§8.51).
> Layer publication and incremental/stacked draft→ready are landed behind `Delivery.publish`
> (§8.47/§8.52); automatic submit/address suffix propagation is also landed. The readiness dry-run
> (`stack land --dry-run`, contracts §8.55), the landing mutation (bare `stack land` +
> `/objective-land`, contracts §8.56), interrupted-landing recovery (the §8.51 LAND arm:
> handle×observation classification, automatic all-after roll-forward, confirmed abandon,
> the `--accept-prefix` breach, and the finalization-convergence pass), and the
> ordered-journal-evidence objective reconciliation drive are all landed. The incremental
> `perk pr land` is landed behind `Delivery.land` (the `kind="plan"` variant; contracts §8.4),
> with post-merge finalization package-internal. The atomic objective-landing operation — the
> §8.55 readiness preview and the §8.56 journaled mutation — is likewise landed behind
> `Delivery.land` (the `kind="objective"` variant): `land_train` and `LandError` are gone,
> consent and the operation lock arrived exactly where they existed, BLOCKED became the
> in-band readiness-only detail, and the delivery root export census closed at the canonical
> 20 names; recover and both land variants keep
> only private runtime callbacks to the shared per-layer finalizer.
> Cancellation-metadata repair is landed as the second Recover variant
> (`kind="cancellation_metadata"`): dispatched before worktree config and the operation lock,
> isolated from every operation-conclusion mechanism (no journal mutation, classification,
> consent, finalization, close, or sweep) while retaining read-only train reconstruction as
> its fresh safety proof; `perk objective doctor --fix` is now a thin request/result mapper
> over it, and `perk objective stack recover` remains operation-conclusion-only.
>
> **Live-proof addendum (2026-08-13):** the dogfood gate **PASSED**: real GitHub merge-async
> atomically merged a 3-layer train, the land worker was deliberately SIGKILLed after its
> journaled `accepted` event, and second-clone `stack recover` classified `all_after` and
> converged finalization, close, and reconcile evidence. See
> `docs/design/stacked-delivery-dogfood.md`. Branch-protection and external-prefix arms remain
> capture-if-fired/hermetic-only; the core live-wire gap is closed.

An explicit objective argument wins; otherwise only the active plan/worktree may supply it. Perk
does not search and guess among open objectives. Status is confirmation-free. Adopt, abandonment,
and landing confirm interactively or require `--yes` headlessly; deterministic roll-forward
recovery does not ask twice. When several unresolved operations are detected, recovery requires an
explicit operation ID. `RecoverRequest.action` is one closed service choice even though the CLI
retains its existing booleans; one union consent callback renders either action preview, and a
positive answer is followed by from-scratch classification. Fold-first TRANSFER rejects the
LAND-only accept-prefix choice before observation/effects. All fallible result metadata reads
precede cleanup so the manifest-protected orphan sweep is the final authority/effect phase.
Detailed stack status deliberately keeps its direct package-internal `observe_orphans` read: it is
fail-honest, lock-free, and cannot mutate or become a second recover request variant.

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
- objective plan selects the next build-ready node through planning Prepare;
- implement creates a worktree from execution Prepare's verified context and parent SHA;
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

`just test` and `just ci` remain hermetic. Owned constructor-configured fakes for the three façade
authorities record calls and seed typed failures/discriminants, proving status branches, authoring
Prepare ordering/aggregation, bounded error translation, zero-I/O construction, no persistence
access from Prepare, and the incremental/dry-run short circuits. Composed real-Git-adapter tests pin
Prepare's narrow raw-cause preservation without changing status prefixes. Private formatter tests
pin both capability honesty caveats, while the retained real-transport test proves an
`advertiseAtomic=false` remote refuses the no-op probe without moving a ref. Gateway fakes and
tolerant boundary fixtures cover stack create/append convergence, exact Git commands, all async
submit/poll states, required versus optional checks, journal failure injection, and every recovery
row above.

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
