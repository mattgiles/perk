---
title: "Objectives — the roadmap model"
description: "The objective command map, roadmap node model, delivery policies, and backend-specific storage and lifecycle."
sidebar:
  order: 3040
---

# Objectives — the roadmap model

Use this page to look up the complete objective command map, roadmap node model, delivery
policies, and backend-specific storage and lifecycle.

## Orientation

An **objective** is a multi-plan goal. Its roadmap advances by emitting one bounded plan per node.
The committed `[issues]` selection chooses the objective store as well as the plan/learning issue
backend, so both tiers stay in the same tracker family while using distinct protocols.

Under the default **GitHub** backend, an objective is a GitHub Issue plus its first comment. The
issue body carries the compact header and canonical roadmap in metadata blocks; the first comment
carries the rendered roadmap table and Reconcilable prose. Under **Linear**, an objective is a
Linear Project. Its overview carries the copyable command callout and human Reconcilable prose;
the objective header and manifest live as attachments on a metadata sentinel issue, and per-node
state lives as attachments on node-issues. Phases are Project Milestones and explicit dependencies
are blocking relations. See [Issue backends](./providers-and-backends/issue-backends.md) for the
full GitHub/Linear storage comparison.

For the *why* of objectives — how a roadmap emits bounded plans as it advances — read
[Gists, plans, and objectives](../explanation/gists-plans-and-objectives.md). For a guided,
end-to-end walkthrough, see
[Tutorial 2 → Drive a multi-plan goal with an objective](../tutorials/drive-an-objective.mdx).

## Objective commands at a glance

Each row links to its authoritative entry in the [CLI reference](./cli.md) or the
[Workflow commands](./in-session/workflow-commands.md).

| Surface | What it does |
| --- | --- |
| [`perk objective author`](./cli/objective.md#perk-objective-author) | Draft a new objective and roadmap, optionally adopting a pre-existing source with `--from`. |
| [`perk objective save`](./cli/objective.md#perk-objective-save) | Persist an authored objective at the read-only → read-write boundary. |
| [`perk objective plan`](./cli/objective.md#perk-objective-plan-number) | Select the next node and author a bounded plan. |
| [`perk objective create`](./cli/objective.md#perk-objective-create-alias-new) (`new`) | Create an objective directly from structured input. |
| [`perk objective show`](./cli/objective.md#perk-objective-show-number-alias-s) (`s`) | Show the header, roadmap, summary, and next node. |
| [`perk objective node`](./cli/objective.md#perk-objective-node-number) | Update one node with an explicit status or backlink change. |
| [`perk objective node-add`](./cli/objective.md#perk-objective-node-add-number) | Add a genuinely-new node and assign its next phase-local id. |
| [`perk objective engagement`](./cli/objective.md#perk-objective-engagement-number) | Read objective and node-issue human engagement as untrusted data. |
| [`perk objective node-engagement`](./cli/objective.md#perk-objective-node-engagement-number) | Read one node-issue's pre-planning engagement. |
| [`perk objective reconcile`](./cli/objective.md#perk-objective-reconcile-number-alias-rec) (`rec`) | Rewrite only the Reconcilable prose region after a merge. |
| [`perk objective replan`](./cli/objective.md#perk-objective-replan-number) | Re-author unfinished work as a superseding objective. |
| [`perk objective next`](./cli/objective.md#perk-objective-next-number-alias-n) (`n`) | Print the next plannable node. |
| [`perk objective run`](./cli/objective.md#perk-objective-run-number-alias-r) (`r`) | Advance the backlog one autonomously safe step. |
| [`perk objective doctor`](./cli/objective.md#perk-objective-doctor-number-alias-doc) (`doc`) | Diagnose and optionally repair manifest, cancellation, or delivery-train drift. |
| [`perk objective stack status`](./cli/objective.md#perk-objective-stack-status-objective) | Report the published delivery train and unresolved operations. |
| [`perk objective stack sync`](./cli/objective.md#perk-objective-stack-sync-objective) | Preview or cascade a published suffix after an amend or base advance. |
| [`perk objective stack recover`](./cli/objective.md#perk-objective-stack-recover-objective) | Conclude an interrupted stack operation and sweep residue. |
| [`perk objective stack land`](./cli/objective.md#perk-objective-stack-land-objective) | Preview or atomically land the remaining train. |
| [`/objective`](./in-session/workflow-commands.md#objective) | Show, set, or clear the active objective and budget. |
| [`/objective-plan`](./in-session/workflow-commands.md#objective-plan) + `objective_node` | Start the plan factory; link a plan or advance a node. |
| [`/objective-reconcile`](./in-session/workflow-commands.md#objective-reconcile) + `reconcile_objective` | Reconcile the prose region after land. |
| [`/objective-save`](./in-session/workflow-commands.md#objective-save) + `objective_draft` / `objective_save` | Draft and save an objective in-session. |

`perk objective author` has no warm slash twin; objective authoring starts from the cold command or
from plan-mode read-only authoring.

## The roadmap node schema

Structured authoring accepts `StructuredRoadmapNode`; stored roadmaps use `ObjectiveNode`. The
input model supplies `pending` when `status` is omitted, but every stored node has an explicit
status. `adopt_issue` is the other input-only field: authoring consumes it as an adoption side-map
and drops it before persistence.

<!-- perk:reference-facts:objective-fields:start -->
| Field | Structured authoring input | Stored node | Semantics |
| --- | --- | --- | --- |
| `id` | required string | required | Stable node id, e.g. `"1.2"`. The phase is derived from its prefix and is never stored separately. |
| `description` | required string | required | What the node delivers. |
| `status` | optional; defaults to `pending` | required | One of the six [node statuses](#node-statuses). |
| `slug` | optional string | optional | Short stable label for the node. |
| `pr` | optional string or null | optional | Linked plan/PR backlink, or null when none. |
| `depends_on` | optional list or null | optional | Tri-state: absent/null infers the previous node; `[]` means no dependencies; a non-empty list is explicit. |
| `comment` | optional string | optional | Operator note attached to the node. |
| `adopt_issue` | optional string | not stored | Linear authoring-only source issue id; consumed as an adoption mapping and dropped from `ObjectiveNode`. |
<!-- perk:reference-facts:objective-fields:end -->

Nodes can also be **inserted post-hoc** during reconciliation — `add_objective_node` (warm tool) /
[`perk objective node-add`](./cli/objective.md#perk-objective-node-add-number) (cold) auto-assigns the next
`<phase>.<n>` id and appends the node within its phase. Used sparingly, only for genuinely-new work
(a deferred follow-up, an uncovered gap, a missing prerequisite, or human-requested work). Adding a
**non-terminal** node to a closed objective **reopens it automatically** (the reopen-on-incomplete
invariant — roadmap incomplete ⇒ open, the mirror of land's close-on-complete), including an
objective a human closed early; the one exemption is a **superseded** objective (`objective
replan` closed it deliberately — dead lineage is never resurrected). Flipping an existing terminal
node back to non-terminal via `objective_node`/`perk objective node` does **not** auto-reopen —
the invariant rides node *insertion* only.

## Node statuses

A node's `status` is one of six values (`NodeStatus`):

<!-- perk:reference-facts:objective-statuses:start -->
| Status | Meaning |
| --- | --- |
| `pending` | Not yet started; plannable once its dependencies are terminal. |
| `planning` | A **resumable claim** — selected for planning, no saved plan yet (`pr` null). Re-running `/objective-plan` resumes it. |
| `in_progress` | A **committed** plan — a plan was saved and the node↔plan backlink set atomically. |
| `done` | Completed and landed. **Terminal.** |
| `blocked` | Dependencies are not all terminal (or set explicitly). |
| `skipped` | Deliberately not done. **Terminal** — satisfies the node as a dependency. |
<!-- perk:reference-facts:objective-statuses:end -->

- **Terminal set** = `{done, skipped}`. A dependency is "satisfied" only when terminal, so a
  terminal node **unblocks** the nodes that depend on it.
- **The resumable-lease distinction.** `planning` is a claim with no saved plan (`pr` null) and is
  resumable; `in_progress` is a committed plan. A `planning` node that already carries a `pr` is
  treated as in-flight, not resumable.
- **`blocked`** marks a node whose dependencies are not all terminal; it can also be set explicitly.
- **Explicit-status-only.** A node's `status` is **never** inferred from its `pr` — setting `pr`
  never changes `status`.

## Delivery

An objective declares how its node plans **land** — the reviewed delivery choice, recorded at
save time:

- **`incremental`** (the default, and the recommended choice) — each node plan lands as its own
  independent PR against the objective's base. Omitting the choice means incremental; nothing is
  written to the header.
- **`stacked`** — all non-skipped roadmap nodes land as **ONE atomic pull-request train**: each
  layer's branch starts from its predecessor's, each draft PR targets the parent layer's branch,
  and the layers are registered in a native GitHub stack. The choice is validated at save (2–100
  non-skipped nodes, no duplicate ids / unknown deps / cycles) and **capability-checked** against
  the real Git/GitHub plane (native-stack API surface, squash direct-merge + no merge queue on
  the base, an atomic-push dry-run) before anything is written. Layers publish through the
  ordinary `/submit` door — see [`perk pr submit`](./cli/pr.md#perk-pr-submit) and
  [Workflow commands](./in-session/workflow-commands.md).

Day-to-day operation needs no dedicated commands: a published-suffix rewrite converges
automatically from the normal workflow — re-run `/submit` after committing a published-layer
change, or finish `/address` through `finalize_address`, and perk cascades the claimed suffix
using the invoking plan's committed head and verified published heads for every successor. The
explicit [`perk objective stack sync`](./cli/objective.md#perk-objective-stack-sync-objective) owns base
advancement (`--base`), preview (`--dry-run`), deliberate out-of-band adoption (`--adopt`), and
retained-conflict continuation/discard (`--continue`/`--abort`);
[`perk objective stack recover`](./cli/objective.md#perk-objective-stack-recover-objective) concludes
interrupted operations and sweeps orphaned residue. The in-session equivalents are
`/objective-stack`, `/objective-sync`, `/objective-recover`, and `/objective-land`.

Learn the full stacked flow in
[Drive a stacked objective to one atomic landing](../tutorials/drive-a-stacked-objective.md);
day-to-day, see [How to review a stacked PR train](../how-to/review-a-stacked-train.md) and
[How to recover a stacked delivery train](../how-to/recover-a-stacked-train.md).

**Current limitations (read before choosing stacked):**

- **Merge-queue bases are unsupported.** The stacked capability check at save requires squash
  direct-merge allowed and no
  [merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
  on the base; at landing, a queue-required base is a readiness blocker, and a queue seizing
  the merge request is the unresolved `unexpected_enqueued` outcome.
- **One train per objective.** All non-skipped roadmap nodes form ONE atomic train under a
  single `delivery_lineage` — there is no way to split a roadmap into independent trains or
  land a subset. Exclude work from the train by skipping its nodes.
- **Delivery policy and base are immutable after first publication.** Base *advancement* stays
  normal (`stack sync --base` moves the base's head, not its identity). Replanning preserves
  both: `perk objective replan` on a stacked objective is transfer-based — it preserves the
  published prefix exactly (carried in order), mandatory-carries every plan with an open PR,
  and closes the old objective only after the successor verifies — see
  [How to replan an objective](../how-to/replan-an-objective.md#replanning-a-stacked-objective-the-transfer).
  An interrupted transfer concludes via `stack recover <old-objective-id>`.
- **In-place adoption is incremental-only.** `perk objective author --adopt-from` refuses
  `--delivery stacked` — author a fresh stacked objective instead.
- **Never land stacked layers individually.** `perk pr land` / `/land` refuse a stacked plan
  (`stacked_plan`) before any mutation — a layer PR targets its parent's branch, so landing
  one alone merges into the wrong target and tears the train. Landing is objective-scoped and
  atomic: `perk objective stack land --dry-run` reports the typed ready/blocked verdict with
  the exact per-PR facts and the would-be land plan; bare `perk objective stack land` (or the
  in-session `/objective-land`) merges the WHOLE remaining train in one confirmed, journaled
  operation, then finalizes every layer and closes the objective once every node is terminal.
  An interrupted landing (`pending` / `unexpected_enqueued`) is an unresolved LAND operation
  concluded by `perk objective stack recover` — classification against fresh authority,
  automatic `all_after` roll-forward, `--accept-prefix` for an externally merged prefix.
- **GitHub-native stacks are preview-quality.** GitHub's stacked-PR and atomic-merge APIs are
  a public preview and subject to change; per-repo enrollment and merge-async availability are
  observable only at mutation time (`merge_async_unavailable`).

## The metadata blocks

On GitHub, an objective stores three `perk:`-namespaced, schema-version-`"1"` metadata blocks as
collapsible sections an operator can read with `gh issue view N` (under Linear the same header
fields ride native **attachments** instead — see
[Issue backends](./providers-and-backends/issue-backends.md)):

- **`objective-header`** (issue body) — compact, queryable
  `{run_id, created, objective_comment_id, status, base}`, where `status` is the objective-level
  rollup (e.g. `"active"`) and `base` is the objective's target branch (inherited by every node
  plan; `null` when unset — see
  [Target a non-default base branch](../how-to/target-a-non-default-base-branch.md)). Marked by
  `<!-- perk:metadata-block:objective-header -->`. Two conditional fields appear **only on a
  stacked objective**: `delivery: stacked` (the reviewed delivery choice — absence means
  incremental, and `incremental` is never written) and `delivery_lineage` (the stable ULID
  identity of the delivery train, minted at stacked authoring and copied by replan; see
  [Delivery](#delivery)). Incremental objectives store neither field. A third conditional
  field, `dream_report`, appears only on an objective saved by a `perk learn dream` session:
  the id of the issue whose comments durably hold the reviewed
  dream-report parts — on GitHub the objective issue itself, on Linear the Project's metadata
  sentinel (see
  [Issue backends](./providers-and-backends/issue-backends.md#the-dream-report-companion)).
  A fourth conditional field, `origin`, likewise appears only on a dream-authored objective
  (value `learn-dream`): stamped once at creation, never merged into a header after create,
  and carried forward by replan supersession — it is what the one-open-dream-objective guard
  reads.
- **`objective-roadmap`** (issue body) — the **canonical** flat-node roadmap YAML
  (`{schema_version: "1", nodes: [...]}`), deterministically re-rendered on every node update.
  `depends_on` / `comment` columns are omitted from serialization unless some node specifies them.
  Marked by `<!-- perk:metadata-block:objective-roadmap -->`.
- **`objective-body`** (first comment) — the human-readable rendered roadmap **table**
  (marker-bounded by `<!-- perk:roadmap-table -->`, re-rendered from the canonical roadmap) **plus
  prose**, where the prose is the marker-bounded **Reconcilable** region. Reconcile rewrites only
  this Reconcilable region; the table and any **Immutable** notes are never touched.

When an objective is first created, perk prepends a **copyable command callout** to the top of its
human-readable surface — the `objective-body` comment (GitHub / Linear issue-backed) or the Project
**overview** (Linear project-backed) — a one-click-copy ` ```perk objective plan <id>``` ` block
(where `<id>` is the objective's ref id: the GitHub number, a Linear `ENG-N` identifier, or the
Project UUID). Opening the objective surfaces the exact command to plan its next actionable node. It
is added once and sits above every metadata block, so reconciles and table re-renders preserve it.

### The manifest (Linear-Project objectives only)

A Linear objective is a **Project**, not an issue — its roadmap is *observed* state (one node-issue
per node, blocking relations, phase milestones) that anyone can edit in Linear. To detect that
divergence, perk also persists an **`objective-manifest`** recording the roadmap's **structural
identity**: each node's `id` / `slug` / `description` and explicit `depends_on`, plus the pinned
milestone name per phase. `status`/`pr` are excluded (they are live state). Under Linear it is
stored (with the `objective-header`) as an **attachment envelope on the project's metadata
sentinel issue**, not in the overview. perk keeps this manifest
in sync on every write; [`perk objective doctor`](./cli/objective.md#perk-objective-doctor-number-alias-doc)
diffs it against the live Project to find — and safely repair — drift. GitHub objectives have no
separate observed surface and so carry no manifest (doctor's second part — the delivery-train
diagnosis — runs on every backend). See
[How to check an objective for drift](../how-to/check-an-objective-for-drift.md).

One more observed-state wrinkle on Linear: a human can **cancel a node-issue natively** (move it
to a canceled workflow state). perk reads that as external intent — the node *projects* as
skipped (a **cancellation projection**) while the persisted attachment status is untouched — but
only when the cancellation can be positively **proven safe**: unpublished future work, where a
clean, coherent plan backlink is acceptable but any identity conflict, checkpoint or PR claim,
completed or unresolved publication history, remote branch, or branch-owned PR is not. Anything
unprovable (a published layer, a live branch or PR in any state, a pending publication,
conflicting identity) stays a visible
`canceled` layer with blockers; `perk objective doctor --fix` persists the proven-safe skips.

### Pre-planning node-issue engagement (Linear-Project objectives only)

Because each Linear-Project roadmap node **is** a node-issue, a human can comment on it (or edit its
description) **before** perk ever plans it. When you run `/objective-plan`, perk reads that
engagement and folds it into the plan-authoring context as an **untrusted-DATA** block (comments +
description edits, with distinguishable authorship; perk's own machinery comments are skipped) — so
the authored plan comprehends your feedback. You can inspect it directly with
[`perk objective node-engagement N --node <id>`](./cli/objective.md#perk-objective-node-engagement-number).
GitHub single-issue objectives have no per-node issues, so this is a Linear-first behavior (empty on
GitHub).

### Objective + node-issue engagement at reconcile time

The post-merge `/objective-reconcile` pass also weighs **human engagement on the objective + its
node-issues** (comments + description edits), not only the landed PR diff: it auto-runs
[`perk objective engagement N`](./cli/objective.md#perk-objective-engagement-number) and folds the resulting
`<untrusted_objective_engagement>` block — treated as untrusted DATA — into what may be stale, while
obeying the same section-boundary and don't-churn rules. **GitHub** surfaces the objective issue's
own comments + edits; **Linear** surfaces the project's comments plus each node-issue's
comments/edits. You can inspect it directly with the same command (`--json` for the machine
payload).

## Related

- **Learn:** [Drive a multi-plan goal with an objective](../tutorials/drive-an-objective.mdx) —
  author and land a first node hands-on.
- **Do:** [Author an objective roadmap](../how-to/author-a-roadmap.md) — stand up an objective
  from a real goal.
- **Understand:** [Gists, plans, and objectives](../explanation/gists-plans-and-objectives.md) —
  why objectives generate plans instead of being implemented directly.
