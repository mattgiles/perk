# perk

The plan-oriented agent workflow: a Python CLI (the session exterior) and a Pi extension (the
session interior) drive written, reviewed, durable plans through a staged spine.

## Language

**Gist**:
A rough, problem-space-focused statement of intent ("something we would likely want to do")
tracked in the issue backend — upstream of both plans and objectives, carrying no implementation
detail.
_Avoid_: idea, note, ticket, seed

**Scope** (of a gist):
A gist's intended consumption tier — `plan` (a bounded, single-plan-sized intent) or `objective`
(a long-running, multi-plan-sized goal). A routing hint for the adoption doors: a storage
discriminator on Linear (objective scope stores the gist as a project), a header hint elsewhere.
_Avoid_: kind, type, size

### Objective delivery

**Incremental delivery**:
The default objective delivery policy in which each plan integrates independently when it is
ready.
_Avoid_: serial delivery, ordinary delivery

**Stacked delivery**:
An objective delivery policy in which plans remain separate review units but integrate together at
the objective boundary.
_Avoid_: stack mode, chained delivery

**Delivery train**:
The ordered set of layers belonging to one stacked-delivery lineage, including across objective
replans.
_Avoid_: stack, branch chain

**Layer** (of a delivery train):
The delivery unit formed by one non-skipped roadmap node and its plan.
_Avoid_: commit, phase, arbitrary pull request

**Published prefix**:
The contiguous initial portion of a delivery train whose layers have established review artifacts.
_Avoid_: open plans, published set

**Delivery lineage**:
The stable identity of a delivery train across superseding objectives.
_Avoid_: objective lineage, stack number

**Delivery order**:
The deterministic topological order of a train's non-skipped roadmap nodes, derived with
`node_sort_key` as tie-breaker and never persisted.
_Avoid_: roadmap order, stack position

**Predecessor layer**:
The immediately preceding layer in delivery order, identified durably by plan identity (the
bottom layer has none).
_Avoid_: parent branch

**Parent checkpoint**:
The verified parent commit a published layer head was built from (the objective base for the
bottom layer).
_Avoid_: planning provenance, the parent's current head

**Published-head checkpoint**:
The layer branch head last verified after publication or synchronization.
_Avoid_: desired future head, local HEAD

**Dynamic singleton**:
A delivery train reduced by later cancellation to one remaining layer after having been validly
authored with multiple layers.
_Avoid_: one-node stacked objective, standalone plan

**Cancellation projection**:
The read-side handling of a backend-native node cancellation (a Linear node-issue moved to a
canceled workflow state): the node projects as skipped only when positively proven to be
unpublished future work — a clean, coherent plan backlink is acceptable, but any identity
conflict, checkpoint or PR claim, completed/unresolved publication history, remote branch, or
branch-owned PR is not; anything unprovable stays a visible `canceled` layer with blockers,
and the persisted attachment status is never changed by the read (doctor `--fix` owns
persisting a proven-safe skip).
_Avoid_: auto-skip, native skip, cancellation sync

**Adoption** (of a layer head):
Accepting one layer's manually-pushed remote head as the intended stack state and cascading the
layers above it (`stack sync --adopt`).
_Avoid_: force-sync, overwrite

**Transfer manifest**:
The predecessor-carried TRANSFER journal record whose `before`/`after` payloads are the sole
durable authority for re-driving an interrupted replan transfer (the complete successor
materialization intent plus the recorded claimed prefix).
_Avoid_: successor manifest, session artifact

**Continuation manifest**:
The lineage-keyed, machine-local record of a mid-conflict sync stop — the disposable pointer to
the retained worktree and captured inputs that `--continue`/`--abort` consume.
_Avoid_: transaction log, checkpoint file

**Orphaned sync residue**:
Machine-local `sync-*` worktrees or `refs/perk/sync/*` temp refs whose operation no parseable
continuation manifest claims — inert until `stack recover`'s sweep collects them.
_Avoid_: garbage, stale worktrees

**Landed layer**:
A train layer classified terminal by the prepared⋈completed LAND-journal coverage join
(node/plan/PR identity equal AND the recorded head equal to the published-head checkpoint)
plus fresh merged corroboration of its PR — a merged PR without journal coverage is never
adopted.
_Avoid_: merged layer, finished node

**External prefix breach**:
The recorded degraded-atomicity conclusion of an interrupted LAND: a bottom-contiguous prefix
of the recorded layers was merged outside the operation while every remaining layer stayed
open at its recorded head, accepted explicitly (`stack recover --accept-prefix`) as a
completed record covering only the merged prefix (`external_prefix: true` + the remainder
proof).
_Avoid_: partial land, broken stack
