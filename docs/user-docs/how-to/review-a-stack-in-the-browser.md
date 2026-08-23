---
title: "How to review a PR stack in the browser"
description: "Review an entire PR stack — a perk delivery train or any base-ref chain — in one combined-diff browser session, then post judgment-routed per-PR reviews."
sidebar:
  order: 2046
sidebarGroup: "Core workflow"
---

# How to review a PR stack in the browser

Review a whole PR stack in **one** browser session: plannotator renders the combined diff
(stack base → top head), one adversarial reviewer wave covers the combined diff, you triage
everything together, and perk posts **one review per member PR** — each finding routed to the
PR that introduced it, nothing posted without your explicit approval. Use this instead of
[per-layer review](./review-a-stacked-train.md) when you want the stack judged as a whole;
use [`/pr-review-browser`](./review-a-foreign-pr.md) when the target is a single PR.

Two entries, one flow:

- **`/stack-review-browser [target] [focus note]`** — the warm door, from any perk session.
- **`perk objective stack review [OBJECTIVE|--pr <n>]`** — the cold launcher; it prepares the
  same checkout and opens a dedicated session that starts the same flow with one
  `open_stack_review` call. Preview safely with `--dry-run` (fully side-effect-free: no fetch,
  no checkout, no launch).

**Targets.** A bare number, `#n`, or issue URL is an **objective** — its stacked delivery train
is the stack. `pr:<n>` (door) / `--pr <n|url>` (launcher) walks the **base-ref chain** from any
member PR, so non-perk stacks work too. With no target, the active objective (or the worktree
plan-ref's linked objective) is used. Typed refusals keep the flow honest: a single open PR is
`not_a_stack` (use `/pr-review-browser`), forks are `fork_unsupported`, more than one open child
on the upward walk is `ambiguous_stack`, deeper than 20 members is `stack_too_deep`, and a stack
whose commits don't actually stack is `stack_topology_broken` (sync the stack first).

**Prerequisites:** the plannotator extension loaded (`[providers] plan = "plannotator-plan"`,
`perk init`, restart pi) and an interactive session — the browser flow refuses headless.

## Steps

1. **Invoke the door.** E.g. `/stack-review-browser 77 dig into the migration edits` (an
   objective's train) or `/stack-review-browser pr:148` (a chain from any member PR). perk
   fetches every member head in one round trip, validates the commit topology fail-closed,
   checks out the **top** head detached at `review-<top>` (untrusted foreign code — nothing
   from it is executed), and opens plannotator on the combined diff in the background.
   Resolution warnings (train blockers, recorded-vs-observed head drift) are notes, not
   refusals.
2. **Reviewers stream in.** One adversarial wave runs over the **combined diff** (the reviewer
   children fetch per-member context — each layer's own diff plus the combined diff — with
   `perk pr review-context --pr <top> --stack`). Findings arrive as badged `perk:<angle>`
   annotations in the browser while the session stays free.
3. **Triage in the browser, then close it.** Annotate, edit, or dismiss findings as usual.
   This is a **local-diff session with no attached PR**, so there is no posting from the UI —
   closing the browser returns your annotations to the session for the posting step.
4. **perk routes findings to their PRs.** Each finding is attributed to the member PR that
   introduced it (judgment over the per-PR diffs): folded into that PR's review body by
   default, anchored inline only where the location is unambiguous in that PR's own diff.
5. **Approve the per-PR posting.** perk dry-run-validates **all** per-PR batches first, then —
   with your explicit go-ahead — posts one review per member PR, bottom→top, through the gated
   `submit_pr_review` tool (formal verdicts confirm per PR). Every real post is recorded in the
   `review_posts` ledger; if anything fails mid-sequence the flow stops, shows
   posted-vs-pending, and a resume skips the already-posted PRs — a review is never posted
   twice.
6. **Clean up.** `perk pr review cleanup --pr <top>` removes the stack checkout.

If the browser never becomes ready, the flow degrades loudly to an in-session findings table —
triage and the per-PR posting protocol are unchanged (they never depended on the browser).

## Related

- **Do:** [How to review a stacked PR train](review-a-stacked-train.md) — the per-layer alternative: review each layer on its own incremental diff.
- **Look up:** [Review and authoring](../reference/in-session/review-and-authoring.md#stack-review-browser) — the door's full grammar and refusal detail.
- **Look up:** [`perk objective stack review`](../reference/cli/objective.md#perk-objective-stack-review-objective) — the cold launcher's flags and dry-run preview.
