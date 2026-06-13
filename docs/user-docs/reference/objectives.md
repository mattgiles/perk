# Objectives — the roadmap model

This page describes perk's **objective model**: the objective command surface at a glance, the
roadmap **node schema**, the **node statuses** (and the resumable-lease lifecycle), and the
**metadata blocks** an objective stores on GitHub. It describes the model; it does not teach a task
(those belong in [how-to/](../how-to/index.md)) or argue a design (those belong in
[explanation/](../explanation/index.md)). See the [user-docs router](../index.md) for how this
quadrant fits the whole.

This page is **human-reviewed for accuracy** against `perk/objective.py` (`NodeStatus`,
`ObjectiveNode`, `TERMINAL`, the resumable-lease docstrings) and `shared/contracts.md` (the storage
blocks), like the [in-session reference](./in-session.md).

## Orientation

An **objective** is a multi-plan goal stored as a **GitHub issue + its first comment**. The issue
body carries the compact header and the canonical roadmap (as collapsible `perk:`-namespaced
metadata blocks); the first comment carries the human-readable rendered roadmap **table** plus
reconcilable **prose**. As the roadmap advances, the objective emits bounded plans — one per node.

For the *why* of objectives — how a roadmap emits bounded plans as it advances — read
[How perk thinks](../explanation/how-perk-thinks.md). For a guided, end-to-end walkthrough, see
[Tutorial 2 → Drive a multi-plan goal with an objective](../tutorials/drive-an-objective.md).

## Objective commands at a glance

A compact recap of the objective surface. Each row links to its authoritative entry in the
[CLI reference](./cli.md) (cold `perk …` commands) or the
[in-session reference](./in-session.md) (warm `/…` commands + model tools).

| Surface | What it does |
| --- | --- |
| [`perk objective-author`](./cli.md#perk-objective-author-alias-oauthor) (`oauthor`) | Draft a new objective + roadmap in a read-only session. |
| [`perk objective-save`](./cli.md#perk-objective-save) | Persist the drafted objective to GitHub (read-only → read-write boundary). |
| [`perk objective-plan`](./cli.md#perk-objective-plan-number-alias-oplan) (`oplan`) | Select the next node and author a bounded plan. |
| [`perk objective show`](./cli.md#perk-objective-show-number-alias-s) (`s`) | Show the header, roadmap, summary, and next node. |
| [`perk objective node`](./cli.md#perk-objective-node-number) | Update one node (explicit-status-only). |
| [`perk objective reconcile`](./cli.md#perk-objective-reconcile-number-alias-rec) (`rec`) | Rewrite the Reconcilable prose region against the merged diff. |
| [`perk objective next`](./cli.md#perk-objective-next-number-alias-n) (`n`) | Print the next plannable node. |
| [`perk objective run`](./cli.md#perk-objective-run-number-alias-r) (`r`) | Advance the backlog one autonomously-safe step. |
| [`/objective`](./in-session.md#objective) | Show, set, or clear the active objective + budget. |
| [`/objective-plan`](./in-session.md#objective-plan) + `objective_node` | Start the plan factory; link a plan or advance a node. |
| [`/objective-reconcile`](./in-session.md#objective-reconcile) + `reconcile_objective` | Reconcile the prose region post-land. |
| [`/objective-save`](./in-session.md#objective-save) + `objective_draft` / `objective_save` | Draft and save an objective in-session. |

`perk objective-author` has **no** warm slash twin — objective authoring is reached cold, or via
plan-mode read-only authoring.

## The roadmap node schema

Each roadmap node (`ObjectiveNode`) is a flat record. `id`, `description`, and `status` are
required; the rest are optional.

| Field | Type | Required | Semantics |
| --- | --- | --- | --- |
| `id` | string | yes | Stable node id, e.g. `"1.2"`. The **phase** is derived from the id prefix (`"1.2"` → phase 1, `"2A.1"` → phase 2A) and is never stored. |
| `description` | string | yes | What the node delivers. |
| `status` | string | yes | One of the six [node statuses](#node-statuses) below. |
| `pr` | string \| null | no | The linked plan/PR backlink (e.g. `"#456"`), or `null` when none. |
| `depends_on` | list \| null | no | Dependency node ids. **Tri-state:** `null`/absent → infer **sequential** deps (the previous node); `[]` → explicitly **no** deps; `["1.1", …]` → **explicit** deps. |
| `slug` | string | no | Optional short slug. |
| `comment` | string | no | Optional note. |

## Node statuses

A node's `status` is one of six values (`NodeStatus`):

| Status | Meaning |
| --- | --- |
| `pending` | Not yet started; plannable once its dependencies are terminal. |
| `planning` | A **resumable claim** — selected for planning, no saved plan yet (`pr` null). Re-running `/objective-plan` resumes it. |
| `in_progress` | A **committed** plan — a plan was saved and the node↔plan backlink set atomically. |
| `done` | Completed and landed. **Terminal.** |
| `blocked` | Dependencies are not all terminal (or set explicitly). |
| `skipped` | Deliberately not done. **Terminal** — satisfies the node as a dependency. |

- **Terminal set** = `{done, skipped}`. A dependency is "satisfied" only when terminal, so a
  terminal node **unblocks** the nodes that depend on it.
- **The resumable-lease distinction.** `planning` is a claim with no saved plan (`pr` null) and is
  resumable; `in_progress` is a committed plan. A `planning` node that already carries a `pr` is
  treated as in-flight, not resumable.
- **`blocked`** marks a node whose dependencies are not all terminal; it can also be set explicitly.
- **Explicit-status-only.** A node's `status` is **never** inferred from its `pr` — setting `pr`
  never changes `status`.

## The metadata blocks

An objective stores three `perk:`-namespaced, schema-version-`"1"` metadata blocks as collapsible
sections an operator can read with `gh issue view N`:

- **`objective-header`** (issue body) — compact, queryable
  `{run_id, created, objective_comment_id, status}`, where `status` is the objective-level rollup
  (e.g. `"active"`). Marked by `<!-- perk:metadata-block:objective-header -->`.
- **`objective-roadmap`** (issue body) — the **canonical** flat-node roadmap YAML
  (`{schema_version: "1", nodes: [...]}`), deterministically re-rendered on every node update.
  `depends_on` / `comment` columns are omitted from serialization unless some node specifies them.
  Marked by `<!-- perk:metadata-block:objective-roadmap -->`.
- **`objective-body`** (first comment) — the human-readable rendered roadmap **table**
  (marker-bounded by `<!-- perk:roadmap-table -->`, re-rendered from the canonical roadmap) **plus
  prose**, where the prose is the marker-bounded **Reconcilable** region. Reconcile rewrites only
  this Reconcilable region; the table and any **Immutable** notes are never touched.

## See also

- [CLI commands](./cli.md) — the authoritative `perk objective …` catalog.
- [In-session commands & tools](./in-session.md) — the warm `/objective-*` commands and model tools.
- [Tutorial 2 → Drive a multi-plan goal with an objective](../tutorials/drive-an-objective.md) — the
  guided lesson.
- [How perk thinks](../explanation/how-perk-thinks.md) — the *why* behind objectives.
- How-to guides: [author a roadmap](../how-to/author-a-roadmap.md),
  [advance or skip nodes](../how-to/advance-or-skip-nodes.md),
  [reconcile an objective](../how-to/reconcile-an-objective.md),
  [run the learn-docs factory](../how-to/run-the-learn-docs-factory.md).
- The [user-docs router](../index.md).

> **Status:** this page is part of Objective
> [#453](https://github.com/mattgiles/perk/issues/453) (Node 3.2). The objective model is
> human-reviewed for accuracy against `perk/objective.py` and `shared/contracts.md`.
