# How to drive a change through the full spine

Walk one change plan all the way along perk's **spine** — *plan → save → implement → submit →
(address) → land → learn* — staying in-session where the warm door exists and stepping out to a
cold shell where it does not. This is the reliable step sequence for an operator who already knows
perk. (First time? The [Get started tutorial](../tutorials/get-started.md) *teaches* the same path
hands-on on a throwaway repo; this guide is the map, not the lesson.)

## The spine, end to end

1. **Author and save the plan.** Draft in a read-only authoring session — warm `/plan` from inside
   a running session, or cold [`perk plan`](../reference/cli.md#perk-plan) for a fresh shell. Approve
   the plan to save it to GitHub (the read-only → read-write boundary). The warm `/plan` and
   `/plan-save` commands are in-session commands (their reference is coming with Objective
   [#453](https://github.com/mattgiles/perk/issues/453) Node 2.2); the cold save worker is
   [`perk plan save`](../reference/cli.md#perk-plan-save). *Trivial change?* The lightweight
   alternative is [`/implement-here`](../reference/in-session.md#implement-here) (also offered as
   a review verdict): exit plan mode **without** saving an issue and implement the reviewed draft
   right in the current session — skipping the rest of the spine (no issue, no worktree, no PR).
2. **Implement — cold only.** Run [`perk implement`](../reference/cli.md#perk-implement-plan-alias-impl)
   from your shell. This stage has **no warm door**: it must run in a *fresh* session and cannot
   inherit the planning conversation. That is deliberate context hygiene — see
   [How perk thinks → Stages and doors](../explanation/how-perk-thinks.md#stages-and-doors-how-you-move-through-the-workflow)
   for why implement is cold-only. perk creates the worktree, branches, and primes a clean session
   against the saved plan body.
3. **Submit the result.** From inside the implement session, run warm `/submit` once the work is
   committed — it pushes the branch and opens a draft PR. (In-session command; reference coming with
   Node 2.2. The cold worker is [`perk submit`](../reference/cli.md#perk-submit).)
4. **Mark it ready.** Run warm `/ready` to move the draft PR to ready-for-review (this also runs the
   project's CI checks as the draft → ready gate). (In-session command; reference coming with Node 2.2.)
5. **Address feedback (conditional).** If a reviewer leaves feedback, run warm `/address`. This step
   is optional — you only enter it when there is feedback to respond to. See
   [How to address review feedback on a PR](address-review-feedback.md).
6. **Land it.** Once approved, run warm `/land` to merge the PR, reconcile, and set the
   pending-learn marker. (In-session command; reference coming with Node 2.2. Cold worker:
   [`perk land`](../reference/cli.md#perk-land).)
7. **Capture the learning.** Run warm `/learn` to record durable learnings from the landed change
   (or skip it when nothing is durable — the skip is recorded on the plan too). Either outcome is
   canonical in the issue backend, so a merged plan's learned-vs-pending state survives machine
   switches and fresh clones. (In-session command; reference coming with Node 2.2. Cold worker:
   [`perk learn`](../reference/cli.md#perk-learn).)

## Detours off the spine

Each of these has its own recipe — follow the link when you hit that situation:

- Re-entering an in-flight plan from a cold shell → [How to resume a plan at its current stage](resume-a-plan.md).
- Responding to reviewer feedback → [How to address review feedback on a PR](address-review-feedback.md).
- Rewriting a saved-but-unlanded plan against the current codebase → [How to replan an open plan](replan-an-open-plan.md).
- Running the project's configured checks in-session → [How to run CI checks in a session](run-ci-in-session.md).
- Getting unblocked when uncommitted changes are in the way → [How to recover a dirty worktree](recover-a-dirty-worktree.md).
- Tracking step-by-step implement progress → [How to work with implementation checkpoints](work-with-checkpoints.md).

---

← Back to the [how-to router](index.md).
