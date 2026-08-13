---
title: "How to advance an objective with the run supervisor"
description: "Push an objective's backlog forward one safe step at a time with the deterministic run supervisor."
sidebar:
  order: 2250
sidebarGroup: "Headless & remote"
---

# How to advance an objective with the run supervisor

Ask the deterministic supervisor to make one autonomously safe objective decision, then stop at the
next machine-safe or human boundary.

## Steps

1. **Run the supervisor once.** Run
   [`perk objective run <NUMBER>`](../reference/cli.md#perk-objective-run-number-alias-r) (alias `r`).
   Each invocation reports the locally known cumulative run budget, makes at most one safe decision,
   and exits. There is no `--once` option because one decision per invocation is already the command's
   behavior.
2. **Act on the reported outcome.** The supervisor uses these current action boundaries:

   | Outcome | What to do next |
   | --- | --- |
   | `dispatched` | It sent the next ready `implement` or `address` stage to CI; inspect the named run. |
   | `awaiting_run` | A matching Actions run is queued or in progress; wait or invoke the command with `--wait`. |
   | `plan_required` | Author the named node's plan with the printed command. |
   | `ready_for_review` | Implementation produced a draft pull request; inspect it and mark it ready with the human `/ready` gate. |
   | `awaiting_review` | The pull request is waiting at the human review boundary. |
   | `merged_pending_reconcile` | The merge is visible but its land reconciliation or local learn pass is still pending; follow any printed `perk plan resume` remediation. |
   | `build_blocked` | A stacked delivery train is not build-ready; inspect it with the printed stack-status command. |
   | `repair_required` | Stacked state or an unresolved operation needs the printed recovery or status command before dispatch can continue. |
   | `blocked` | Every remaining node depends on unfinished work; resolve the dependency or blocker. |
   | `pr_closed` | A pull request closed without merging and needs a human decision. |
   | `completed` | Every node is terminal; the supervisor reports the audit and closes the objective when not in dry-run mode. |

3. **Optionally observe one active run.** Add `--wait` to poll a currently active run for up to ten
   minutes. If it completes, the supervisor refreshes objective state and makes one new safe decision;
   if it does not, the result remains `awaiting_run` and is marked inconclusive. Actions discovery
   prevents a fresh clone from double-dispatching merely because it lacks the original local record.
4. **Preview without mutation.** Add `--dry-run` to classify the next graph decision without
   dispatching, minting a run id, writing state, or closing the objective. Stacked build readiness is
   explicitly left unchecked in this offline preview.
5. **Stop at human gates.** The supervisor can dispatch unattended work and observe state, but it
   never marks a pull request ready, approves review, or lands a pull request. Handle those boundaries
   explicitly, then invoke the supervisor again when you want the next decision.

## Related

- **Do:** [Advance or skip nodes](./advance-or-skip-nodes.md) — make a human-directed node
  transition.
- **Do:** [Supervise dispatched runs](./supervise-dispatched-runs.md) — inspect the selected run.
- **Look up:** [Objectives reference](../reference/objectives.md) — node states, outcomes, and
  delivery semantics.
