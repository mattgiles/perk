---
title: "How to author an objective roadmap"
description: "Stand up a new objective — a multi-plan goal with a structured roadmap — so perk can emit bounded plans as it advances."
sidebar:
  order: 2140
sidebarGroup: "Objectives & learnings"
---

# How to author an objective roadmap

Stand up a new **objective** — a multi-plan goal with a structured roadmap of nodes — so perk can
emit bounded plans from it as it advances. Use this when a goal is too big for one plan.

This runs in a **read-only** authoring session and is **local-only**.

## Steps

1. **Start authoring.** Run
   [`perk objective author`](../reference/cli.md#perk-objective-author). perk launches a read-only
   session for drafting the objective + roadmap.
2. **Describe the goal and its nodes.** Tell the agent what the objective is and the work it breaks
   into. It drafts the objective **prose** (the why, the design, the boundaries) and a **structured
   roadmap** of nodes via the `objective_draft` tool.
3. **Review the draft.** Read the prose and the node list. Check the node order and dependencies —
   see the aside below for the roadmap shape.
4. **Approve.** Approval saves the `perk:objective` issue, activates it, and starts budget tracking
   (the manual failsafe is [`perk objective save`](../reference/cli.md#perk-objective-save) /
   the `objective_save` tool).
5. **Inspect it.** Run
   [`perk objective show N`](../reference/cli.md#perk-objective-show-number-alias-s) (alias
   `perk objective s N`) to print the header, roadmap, and next actionable node.

> **Roadmap shape.** Every node starts `pending`. Leave `depends_on` unset for **sequential**
> dependencies (each node depends on the previous), use `[]` for **no** dependencies, or list node
> ids for **explicit** ones. A node's **phase** is derived from its id prefix (`1.2` → phase 1).
> See [Objectives — the roadmap model](../reference/objectives.md) for the full node schema.

## Choose the delivery mode

During authoring the agent asks how the objective's plans should **land** — the reviewed delivery
choice, shown as a prominent `**Delivery:**` line on the review surface and saved with the
objective:

- **Incremental** (the recommended default) — each node plan lands as its own independent PR.
  Pick this unless you have a concrete reason not to.
- **Stacked** — all non-skipped nodes land as **one atomic pull-request train**: each layer
  branches from its predecessor, each draft PR targets the parent layer's branch, and the layers
  register in a native GitHub stack. The save validates the roadmap (2–100 non-skipped nodes, a
  clean dependency graph) and runs a **capability preflight** against the real Git/GitHub plane
  (native-stack API surface, squash direct-merge + no merge queue on the base, an atomic-push
  dry-run) — an unsupported repository refuses the stacked save with honest
  expected-vs-observed details.

**Stacked's current limitations** — know these before choosing it:

- **Normal published-suffix rewrites converge automatically**: after committing a change to an
  already-published layer, re-run `/submit` or finish `/address` through `finalize_address`; perk
  cascades the claimed suffix from the invoking plan's committed head. Explicit
  `perk objective stack sync` remains the owner of base advancement (`--base`), preview
  (`--dry-run`), out-of-band adoption (`--adopt`), and retained-conflict continuation/discard
  (`--continue`/`--abort`); `perk objective stack recover` concludes interrupted operations and
  sweeps orphaned residue.
- **Landing is objective-scoped and atomic** — preview readiness with `perk objective stack
  land --dry-run`, then land the WHOLE remaining train in one confirmed, journaled merge
  with bare `perk objective stack land` (in-session: `/objective-land`). `perk pr land` /
  `/land` refuse a stacked plan (`stacked_plan`) before any mutation. **Never land stacked
  layers individually**: a layer PR targets its parent's branch, so landing one alone merges
  into the wrong target and tears the train — the refusal enforces this. An interrupted
  landing reports `pending` (unresolved); once the merge settles or its request expires,
  `perk objective stack recover` classifies and concludes it — and an externally merged
  prefix can be accepted explicitly as a recorded breach (`--accept-prefix`), after which
  the remainder re-lands via `stack sync --base` then `stack land`.

For the guided, end-to-end version of this flow, see
[Tutorial 2 → Drive a multi-plan goal with an objective](../tutorials/drive-an-objective.mdx).
For the guided, end-to-end **stacked** version, see
[Drive a stacked objective to one atomic landing](../tutorials/drive-a-stacked-objective.md);
day-to-day, [How to review a stacked PR train](./review-a-stacked-train.md) covers the
reviewer's side and [How to recover a stacked delivery train](./recover-a-stacked-train.md)
the triage moves when a train operation is interrupted or drifts.

---

← Back to the [how-to router](index.md).
