---
title: "Gists, plans, and objectives"
description: "Why perk separates intent into three artifacts — a gist, a plan, and an objective — and what each level of commitment buys you."
sidebar:
  order: 4020
---

# Gists, plans, and objectives

perk keeps three distinct artifacts for intent, and the separation is deliberate: each one
answers a different question, carries a different level of commitment, and is consumed at a
different moment. Collapsing them — treating a gist as a small plan, or an objective as a big
one — loses exactly the property each was designed to protect. This page explains what each
artifact is for, why moving between them is a judgment call rather than a promotion, and why the
plan stays the only unit that is ever implemented.

## Three artifacts answer three different questions

A **gist** answers *"what do we want, and why does it matter?"* It is a rough, problem-space
statement of intent captured **before** any delivery shape has been committed: the problem or
desire, the constraints that bound it, and at most a strategic-level lean on the solution. A
gist deliberately carries no implementation detail — no steps, no roadmap, no estimates —
because its value is preserving the intent honestly while it is still unresolved. It lives as a
durable backlog item in the issue backend, waiting until someone decides it is worth planning.
A gist does carry one early hint of shape: a **scope** — whether the intent looks
single-plan-sized or objective-sized — which suggests its eventual consumption tier without
committing to it.

A **plan** answers *"what exactly will change, and how?"* It is a written, reviewed, durable
description of **one bounded change**, authored in read-only exploration and saved only after a
human approves it. The plan is the workload of the whole delivery spine: it is what gets
implemented on a branch, submitted as a pull request, reviewed, and landed. Its boundedness is
the point — a plan small enough to review honestly is the unit that keeps human judgment real.

An **objective** answers *"what long-running goal are we steering, and through which steps?"*
It coordinates a **multi-plan** goal as a roadmap of nodes, each node bounded enough to become
one plan, plus a reviewed delivery policy for how those plans integrate. The objective is a
durable coordination record: it tracks which nodes are done, reconciles its prose against what
actually merged, and knows what is safely next.

## Narrowing intent is a judgment boundary, not automatic promotion

The artifacts form a gradient from open problem to committed change, but nothing moves along
that gradient automatically. A plan-scoped gist can seed plan authoring, and an
objective-scoped gist can seed objective authoring — adoption stamps the new role onto the same
durable record — but in both cases a human-reviewed authoring pass decides what the resulting
scope and shape actually are. The gist's scope was a hint, not a contract; the authoring
conversation may narrow, split, or reshape the intent, and the review gate is where that
narrowing becomes explicit.

This is why a gist is not a mini-plan: it has no steps to inherit, on purpose. And an objective
is not a large plan: it never describes one change in reviewable detail — it describes the
*decomposition* of a goal into changes that will each earn their own review.

## Objectives emit plans rather than being implemented directly

An objective is never "implemented." As it advances, each non-skipped roadmap node is turned
into a bounded plan, and that plan travels the ordinary spine — implement, submit, review,
land — exactly as a hand-authored plan would. When the plan's pull request merges, the node is
marked done and the roadmap is reconciled against what was actually built.

The delivery policy changes how those plan-sized units *integrate*, not what the unit is.
Incremental delivery lands each plan's pull request independently as it becomes ready; stacked
delivery keeps the plans as separate review units whose branches build on one another and land
together as one atomic train. Under either policy, the plan remains the implementation and
review unit — the objective only coordinates.

## Why the separation matters

Each artifact protects something the others would erode:

- **The gist preserves unresolved intent.** Forcing every idea straight into a plan would
  invent premature steps and false precision; the gist keeps the problem statement honest until
  the design conversation is worth having.
- **The plan keeps review bounded.** Review quality collapses with size. Because the
  implementation unit is always one bounded plan, a reviewer can actually hold the whole change
  in their head — even when the change is one step of a much larger goal.
- **The objective gives the long goal a durable memory.** A multi-plan effort needs a record
  that outlives any one session or branch: what was decided, what has landed, what drifted, and
  what is next. The objective's roadmap and reconciliation loop are that record, kept in the
  canonical issue tier where any machine or teammate can resume it.

The commands, fields, statuses, and adoption mechanics behind all three artifacts live in the
how-to and reference pages below.

## Related

- **Do:** [Capture a gist](../how-to/capture-a-gist.md) — record durable intent before it is
  worth planning.
- **Do:** [Drive the full spine](../how-to/drive-the-full-spine.md) — take one bounded plan from
  authoring to landed.
- **Look up:** [Objectives](../reference/objectives.md) — the roadmap node schema, statuses,
  delivery policies, and command map.
