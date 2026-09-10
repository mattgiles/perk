---
title: "How to refine future nodes before planning"
description: "Write a dated advisory refinement of a pending or blocked roadmap node ahead of its planning turn, review and save it, and see how the later planning session consumes it."
sidebar:
  order: 2145
sidebarGroup: "Objectives & learnings"
---

# How to refine future nodes before planning

Sharpen a `pending` or `blocked` roadmap node that has no plan yet — **before** anyone plans it —
by writing a dated **refinement**: a reviewed, advisory elaboration saved as one marked comment on
the node-issue. A refinement is never a plan, a claim, an unblock, or a fast-track; the node stays
exactly as plannable as before, and the later planning session reads the refinement as dated
DATA it must re-verify.

Refinement **authoring** is for **Linear-Project objectives only** in this release — a GitHub
objective refuses with `unsupported_backend` before any network call (its carrier, the objective
issue, stores and reads refinements, but the refine doors are not yet enabled there). The pass
runs in a **read-only** session.

## Prerequisites

- A Linear-backed objective (see [How to switch the issue backend to Linear](./switch-to-linear.md)).
- A roadmap node that is `pending` or `blocked` and has no plan — check with
  `perk objective show N`.
- A configured review surface (the `plan` provider seam) — the refinement is approved there.

## Steps

1. **Pick the node.** Run `perk objective show N` and choose a refinable node: one whose status is
   `pending` or `blocked` and that carries no plan — blocked, far-future nodes included. A node
   with a valid prior refinement can be refined again; the save replaces the comment whole.
   Preview the target without touching anything:

   ```sh
   perk objective refine N --node ID --dry-run --json
   ```

   The report names the selected identity, its status, whether a prior refinement exists, and
   the checkout observation (`HEAD` + dirty flag). Nothing is synced, written, or launched.

2. **Start the pass.** From a cold shell:

   ```sh
   perk objective refine N --node ID
   ```

   Omit `--node` to select the first refinable, unrefined future node. Add `--no-sync` to skip the
   one `main` fast-forward that otherwise runs before selection. The session explores the checkout
   you run it from, dirty changes included — it never positions another worktree. From an idle,
   **unbound** session, run `/objective-refine N --node ID` instead.

   Refusals at this step, with the recovery move:

   - `unsupported_backend` — a GitHub objective; the refine doors admit Linear only in this
     release (the GitHub carrier stores and reads refinements, but authoring there is not yet
     enabled).
   - `node_ineligible` — the node is claimed, planned, or finished; pick a `pending`/`blocked`
     node without a plan.
   - `no_unrefined_node` — nothing is left to refine without `--node`; name a node explicitly to
     re-refine it.
   - `bound_session` (warm only) — the session is already bound to a plan or carries a planning
     claim; start `perk objective refine` cold instead.

3. **Author with the model.** The model reads the grounding context — the target node as read,
   the full prior refinement when one exists, the human engagement on the node-issue, the
   capture-time checkout observation, and any warnings — then explores read-only and keeps the
   working draft current with the `objective_refinement_draft` tool. Answer its questions and steer
   it. Anything a later plan must re-verify — a function signature, a file layout, a dependency —
   belongs in the text as an explicit assumption, not as a fact.

4. **Review and save.** `plan_review` renders the refinement (identity header, advisory notice,
   checkout observation, then the Markdown) on your review surface. **APPROVE saves exactly one
   marked comment on the node-issue** and ends the turn. DENY returns your feedback to the model
   for a rewrite. A Plannotator approval carrying Direct Edits saves nothing and returns one revise
   round — the header lines are bound metadata, so edit the Markdown through the model instead.

5. **Use the human failsafe when the review does not land.** A skipped, dismissed, or unavailable
   review saves nothing; the model presents the draft and offers you the save. Run
   `/objective-refinement-save` (no arguments) yourself: it needs no prior review, it may follow a
   denial, and its result is labelled a manual save. It is also the deliberate retry after an
   unconfirmed approval save — read the node's comments back first (see
   [Browser draft review](../reference/in-session/review-and-authoring.md#browser-draft-review)).

6. **Inspect the node context.** Read back what a planning session will see:

   ```sh
   perk objective node-engagement N --node ID
   ```

   The human form prints the engagement block, then the full dated
   `<untrusted_node_refinement:…>` block — `saved_at`, `authored`, the checkout observation,
   `source_digest`, and a `source_changed` line — then `refinement: <path>`. Add `--json` to get
   the file pointer instead. `absent`, `unsupported`, `unavailable`, and any `warnings[]` are
   **visible incomplete retrieval**, never "no refinement": the planning session reports them as
   incomplete advisory input.

7. **Plan the node when its turn comes.** A refinement changes no status, so the node becomes
   plannable exactly as it would have without one. When it does, run `perk objective plan N` (it
   snapshots the refinement at launch and seeds only a pointer the session pages) or
   `/objective-plan N` (it reads the refinement through the node-engagement worker after the
   planning transition). Either way the session runs a **full, fresh planning pass**: it weighs
   the refinement as dated DATA, re-verifies every assumption against the live tree, and discards
   obsolete ones explicitly in the plan's Assumptions. A `source_changed: yes` line means the node's
   source moved after the refinement was written — expect the plan to say what it dropped.

## Expected result

- One refinement comment on the node-issue whose first line is the
  `perk:objective-refinement:v1:<key>` marker.
- The node exactly as plannable as before — no status, backlink, or roadmap change.
- A later plan whose Assumptions name what the refinement got right and what it had to drop.

## Related

- **Look up:** [Objectives — Node refinements](../reference/objectives.md#node-refinements-linear-project-objectives-only)
  — the refinement model, its guarantees, and both consumption paths.
- **Look up:** [`perk objective refine`](../reference/cli/objective.md#perk-objective-refine-number)
  — the door's flags, ordering, and refusals.
- **Do:** [How to advance or skip roadmap nodes manually](./advance-or-skip-nodes.md) — change a
  node's status by hand when the refined node must become plannable.
