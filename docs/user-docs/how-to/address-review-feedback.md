---
title: "How to address review feedback on a PR"
description: "Classify reviewer feedback on a plan's PR, fix the actionable items, and resolve the threads — then re-ready and land."
sidebar:
  order: 2030
sidebarGroup: "Core workflow"
---

# How to address review feedback on a PR

Classify reviewer feedback on a plan's PR, fix the actionable items, and resolve the threads —
then re-ready and land. Use this when a reviewer has left comments on the draft/ready PR.

**Prerequisite:** a PR with reviewer feedback to respond to. (`address` is the conditional step on
the spine — you only enter it when there is feedback.)

## Steps

1. **Open the session.** Stay in the submit/implement session if it is still live, or open a fresh
   one with cold [`perk address`](../reference/cli.md#perk-address) (the stage launcher).
2. **Run the address door.** Run warm `/address`. perk classifies the feedback in an isolated child
   session, then the parent fixes the actionable items and batch-resolves the threads. (In-session
   command; its reference is coming with Objective
   [#453](https://github.com/mattgiles/perk/issues/453) Node 2.2.)
3. **Classify only, take no action (optional).** Run `/address --preview` to see the classification
   without fixing or resolving anything — useful to triage before committing to changes.
4. **Review and let perk resolve.** Confirm the classification, let perk apply the fixes and resolve
   the addressed threads.
5. **Re-ready and land.** Once the feedback is addressed and committed, run warm `/ready` to put the
   PR back in front of the reviewer, then warm `/land` once it is approved. (Both in-session
   commands; reference coming with Node 2.2.)

> **On a stacked plan?** Feedback on a lower layer of a stacked PR train is addressed exactly the
> same way — `/address` fixes it, and the automatic cascade rewrites the published layers above the
> fix. See [How to review a stacked PR train](./review-a-stacked-train.md).

---

← Back to the [how-to router](index.md).
