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

For the guided, end-to-end version of this flow, see
[Tutorial 2 → Drive a multi-plan goal with an objective](../tutorials/drive-an-objective.md).

---

← Back to the [how-to router](index.md).
