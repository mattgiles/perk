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

### Model-facing prose

**Prose unit**:
The smallest named behavior-shaping fragment that perk treats as one reviewable identity, such as
a template body, Markdown section, tool description, or injected guidance block.
_Avoid_: prompt file, sentence, copy block

**Session shape**:
A concrete delivery variant whose model context differs from its siblings, such as a cold, warm,
headless, ambient, or subagent path through the same capability.
_Avoid_: stage, door when the delivery variant is what matters

**Prompt assembly**:
The ordered prose units and external context boundaries that shape one session shape under a named
scenario.
_Avoid_: full prompt, transcript, concatenated string

**Prompt concern**:
A recurring behavioral instruction with one canonical carrier and explicitly related prose units.
_Avoid_: duplicated phrase, tag, topic

**Agent scratch**:
A run-owned, disposable directory for non-authoritative command and model intermediate files,
distinct from pointer-validated session data and host-global temporary space; never provisioned
in a runner child.
_Avoid_: session data, evidence store, temp directory

**Runner child**:
A pi-subagents background child (`PI_SUBAGENT_CHILD=1`), the only kind in which perk's extension
activates as a child; every perk report child is one.
_Avoid_: native child, report identity, `<active_agent>` name

**Report restriction packet**:
The constant `perk.parent-restrictions/1 = {readOnly: true}` binding perk's `ReportWave` stamps on
every report child; with the runner bit it is the whole authorization input for the child's
read-only floor.
_Avoid_: parent-restriction snapshot, captured parent gate, caller-read-only policy

**Read-only floor**:
The activation-latched restriction a runner child derives from the packet; it composes into the
tool gate and cannot be cleared by gate exit, tree navigation or a same-activation restart.
_Avoid_: child mode, inherited mode

### Report-wave lane identity

**Semantic lane id**:
The producer-owned identity a learn-flow manifest gives one lane (a harvest `<category>-<n>`, a
dream cluster id, an audit `expectation_id`) — what analysts match byte-exact against the manifest
and what typed outcomes report on.
_Avoid_: lane key, run key, label

**Routing token**:
Any producer-owned identity rendered into a report child's task prose for byte-exact lane
selection or verbatim echo — usually the semantic lane id, plus the audit wave's pair-level
`session_basename` (a token, not a lane id) — untrusted DATA, never an instruction; admitted only
through the `waves/laneIdentity.ts` fence (a refusal rule, never escaping).
_Avoid_: escaped id, sanitized id, lane key

**Orchestration key**:
The code-owned `runs.all` item key a producer-lane learn wave (harvest, audit, dream analyst) gives
one lane — the fixed `lane.<ordinal>` (a global 1-based ordinal in lane-plan order) from
`waves/laneIdentity.ts`; opaque, never derived from producer bytes, never surfaced as a lane
identity (it appears only in attempt receipts' `requestedKeys`, receipt children, and failure
details). Closed slug-enum waves (learn analyst, dream reducer) key by the slug and have none.
_Avoid_: lane id, label, sanitized key, run key (when the identity is meant)

### Review

**Approval guidance**:
Nonblocking advice accompanying an approval. It neither changes the verdict into a request for
changes nor establishes that a platform review was posted.
_Avoid_: change request, posting confirmation

**Activity**:
The optional second half of perk's one composed `perk` status value (`<objective> · <activity>`):
a short plain-text phrase naming a Perk-owned wait the operator cannot otherwise see — today only
`waiting on browser review`, begun by the two plannotator browser waits (the browser doors' open
core on readiness, the warm `plan_review` bridge on entry), ended when each wait settles, and
shown while any begun wait is unended. Never a spinner, a working state, a liveness signal, or a
per-interaction record.
_Avoid_: status, working indicator, spinner, liveness

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

### Objective refinement

**Refinement** (of a roadmap node):
A dated, reviewed, advisory elaboration of one existing roadmap node, persisted as a single
marked comment on the node's carrier (the Linear node-issue) with its authoring provenance and
the node source it was written against. Content only: neither an executable plan, a node
status, a claim, nor a readiness or freshness proof; stored metadata never authenticates human
approval.
_Avoid_: pre-plan, draft plan, node body, elaboration

**Refined** (a roadmap node):
The presence of a valid saved refinement record for the node — derived from the carrier's
comment, never a node state, header, manifest, or plan-ref field. A refined node stays exactly
as selectable for planning as before; a changed source reads as advisory drift, not absence.
_Avoid_: pre-planned, unblocked, ready

### Learned-corpus curation

**Learned corpus**:
The tracked `docs/learned/` doc set (minus the generated index) that `/learn` grows and the
curation factories read.
_Avoid_: knowledge base, notes

**Dream**:
The whole-corpus curation audit at one stamped commit (`perk learn dream`), reading the corpus
inward to curate the corpus itself; contrast **harvest**, the bounded outward mine that reads
docs as lenses into the code.
_Avoid_: full harvest, corpus scan

**Dream report**:
The reviewed, durable companion record of a dream (one row per doc, stances, selections,
overflow, follow-ups), persisted as immutable marker-keyed comments on the objective's report
carrier.
_Avoid_: audit log, wave output

**Disposition**:
The one final per-doc curation verdict from the closed set `keep` / `revise` / `merge-into` /
`retire`.
_Avoid_: action, fate, status

**Curation unit**:
One coherent plan-sized bundle of curation work (e.g. a merge source + survivor + forced
repoints), selected or ranked into overflow, mapping many-to-one onto roadmap nodes.
_Avoid_: task, work item

**Curation objective**:
The ONE bounded objective a dream authors (≤ 12 distinct roadmap nodes), carrying
`origin: learn-dream`.
_Avoid_: cleanup epic

**Harvest follow-up**:
A report-only code-improvement lead surfaced during a dream, citing a **surviving destination**
(a final-`keep`/`revise` doc, or a cluster named by one); never curation-roadmap work and never
a minted issue.
_Avoid_: code TODO, side quest

**Execution lock**:
The per-worktree `perk-submit-conflict.lock` (`worktreeResolverLock.ts`) that serializes
participating conflict resolvers on one canonical Git directory; busy for any incumbent, never
reclaimed; released by a correlated native `completed` terminal or a pre-launch refusal
(`invalid_request`/`unavailable_context`/`duplicate_node`) with no start evidence, otherwise
retained for a human.
_Avoid_: resolver lock, file claim, lease

**Resolver session claim**:
The `<manifest>.resolver-lock` lease (`resolverLease.ts`) a `/objective-sync` invocation holds for
the retained operation; same-PID reacquire and dead-PID reclamation permitted; never bypasses the
execution lock.
_Avoid_: lock, resolver lock

**Native worktree default**:
pi-subagents' global `worktree` setting in `<agent dir>/extensions/subagent/config.json`, applied
to every delegation that omits the field and read by both engines once at activation; perk
observes and refuses, never converges it.
_Avoid_: worktree allocation default, perk-managed worktree setting
