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

- **Published-suffix sync is explicit, not automatic**: rewriting an already-published layer
  (or advancing the objective base) is cascaded with `perk objective stack sync` (`--base` for
  a base advance) — a confirmed, transactional rewrite of the published branches. Nothing
  propagates automatically from submit/address, and the recovery surface does not exist yet:
  no adoption of out-of-band drift, no `--dry-run`, no conflict `--continue` or `--abort`
  (a mid-cascade rebase conflict is retained for manual resolution), and no generic recovery
  command.
- **No atomic landing yet** — and `perk pr land` does not yet refuse stacked plans. **Never land
  stacked layers individually**: a layer PR targets its parent's branch, so landing one alone
  merges into the wrong target and tears the train.

For the guided, end-to-end version of this flow, see
[Tutorial 2 → Drive a multi-plan goal with an objective](../tutorials/drive-an-objective.md).

---

← Back to the [how-to router](index.md).
