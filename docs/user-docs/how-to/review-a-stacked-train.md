---
title: "How to review a stacked PR train"
description: "Review each layer of a stacked pull-request train on its incremental diff, leave feedback on any layer safely, and never merge a layer individually."
sidebar:
  order: 2045
sidebarGroup: "Core workflow"
---

# How to review a stacked PR train

Review each layer of a stacked pull-request train on its own incremental diff, leave
feedback on any layer — including a bottom one — without coordinating rebases, and hand the
approved train back to its author for the one atomic landing. Use this when the PR in front
of you is a **layer of a stacked delivery train** (its body carries a `### Train context`
table, and its base branch is another `plan-<id>` branch rather than the repository's
default).

## Steps

1. **Review each layer PR on its incremental diff.** A layer PR targets its **parent
   layer's branch** — not the objective's base — so GitHub's diff view shows exactly that
   layer's work, nothing beneath it. Review layers bottom→top when you can: each layer
   assumes its parent's code.
2. **Treat the PR body's train sections as presentation, not authority.** perk inserts a
   `### This layer` section and a `### Train context` table (every layer, bottom→top) into
   each layer PR's body. Both are **non-authoritative** and refresh only at publication —
   the delivery train itself is the authority. See the live train with
   [`perk objective stack status`](../reference/cli.md#perk-objective-stack-status-objective)
   (one line per layer: plan, PR, publication state, plus any blockers).
3. **Leave feedback on any layer — lower layers included — normally.** Feedback on a
   bottom layer is safe: the author addresses it through the ordinary `/address` flow (or a
   commit plus re-`/submit`), and perk's **automatic cascade** rewrites every published
   layer above the fix onto the new head. You never coordinate the rebase, and the upper
   layers' diffs stay exactly their own work.
4. **Approve and ready layers normally.** Review verdicts are the ordinary per-PR ones,
   and the author flips each layer ready-for-review individually with `/ready`. Readying
   never merges anything — a fully-ready train still waits, whole, for its landing.
5. **Never press GitHub's merge button on an individual layer.** A layer PR's merge target
   is its *parent's branch*: merging one layer alone merges into the wrong target and tears
   the train. perk's own `/land` refuses a stacked plan with a typed `stacked_plan` error —
   but GitHub's UI will not refuse for you, so the discipline is yours. Landing is
   **objective-scoped and atomic**: the author/operator lands the whole remaining train in
   one confirmed merge (`/objective-land`, or
   [`perk objective stack land`](../reference/cli.md#perk-objective-stack-land-objective)) —
   see [Objectives → Delivery](../reference/objectives.md#delivery) for the landing shape
   and stacked delivery's current limitations.

---

← Back to the [how-to router](index.md).
