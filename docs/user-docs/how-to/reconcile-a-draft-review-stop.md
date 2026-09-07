---
title: "How to reconcile a draft-review stop"
description: "Preserve evidence and reconcile possible draft-review saves or delivery before continuing existing work or choosing a fresh run."
sidebar:
  order: 2136
sidebarGroup: "Core workflow"
---

# How to reconcile a draft-review stop

Use this procedure when a Plannotator plan, objective, or gist review stops with `busy`,
`invalid-state`, `persistence-failed`, or `unresolved-dispatch`. It also applies to retained
pre-dispatch locks and content-written/pointer-dropped orphan artifacts. A refusal is not a denial,
a failed save receipt is not proof nothing saved, and reopening Pi is not a retry protocol.

**Human-only; no in-place state repair.** Perk provides no draft-review recovery command,
startup/reload discovery, replay, or explicit resume. This page offers no guaranteed escape:
if effects remain unresolved, leave the run stopped. The guarantee is at-most-once participating
machine-local dispatch, not exactly-once delivery or power-loss durability.

## Before you start

Keep the stop diagnostic. It names the canonical run, known request/review IDs, exact artifact and
lock locations when the namespace is verifiable, failing phase/checkpoint, and known save receipt.
An unavailable field stays unknown, not absent. The fixed files are `draft-review.json` and
`draft-review.lock`, beside the run's draft in its canonical session-data namespace. Use the exact
reported paths; do not guess a different checkout or run. Lock owner metadata identifies a claimant,
not whether it saved or delivered anything.

## 1. Stop all participants and prove quiescence

Stop every Pi session and **every child save subprocess** able to use this namespace. Then close
the old browser and prevent further interaction. Establish subprocess quiescence, not merely PID
death, lock age, a closed terminal, or an idle Pi prompt. If you cannot prove all participants are
stopped, leave the state intact and stop here. Never remove a live lock.

## 2. Preserve evidence before investigating

Keep the lock, review artifact, relevant draft (`plan-draft.md`, `objective-draft.json`, or
`gist-draft.json`), run handoff, Pi session/transcript, and identity/digest diagnostics. Include
receipts and evidence for prior attempts in the same run. If necessary, copy the evidence into an
owner-controlled private directory; it can contain private draft and reviewer content.

Do not edit JSONL, forge provenance pointers, prune the run, delete artifacts, or remove the lock
to try again. Do not turn an orphan file into a current-run artifact by adding a pointer.
Preservation is not repair and grants no dispatch authority.

## 3. Classify the stop with corroboration

Inspect the failed phase, persisted transcript, and backend receipts for **this and prior attempts**:

- A validated pending/invalidated record plus complete no-dispatch evidence, or a positively
  identified opening-write failure before request emission, can establish a pre-dispatch stop.
- An opening-looking **orphan alone is not proof of no effects**. Neither a missing pointer or
  message, a dead PID, nor an absent search result proves nothing happened.
- Dispatch/uncertain state, save-started without a receipt, a failed write, or incomplete evidence
  means possible effects. Disk may be ahead of its provenance pointer. Do not manufacture an
  `uncertain` record or reset consumption yourself.

Even a proven pre-dispatch failure of the current attempt does not exclude an earlier saved
subject in this run. Correlation is not authority; intent is not completion.

## 4. Resolve possible saves and delivery

Using normal **read-only** tools and returned IDs/URLs, inspect existing backend objects, objective
node linkage, and persisted messages. For GitHub, use `gh` rather than unauthenticated web fetches.
Check the existing object identified by a confirmed receipt; do not create another to test whether
the first save worked. A successful gate exit remains a fact even if later bookkeeping failed.

A tool return or message-send spy proves an attempt, not delivery. Perk requires an exact persisted
tool/user entry; absence of that evidence does not prove the backend save was absent. Human
corroboration here is not runtime backend verification. If save, linkage, or delivery effects
remain unresolved, **stay stopped: neither a new review nor a new run is a safe retry**.

## 5. Continue existing work or deliberately choose a fresh run

If saved work exists, continue its normal plan/objective/gist workflow rather than duplicate it.
See [Resume a saved plan](./resume-a-plan.md). Do not mistake that normal saved-object workflow
for resuming the abandoned draft decision.

Only after the human establishes no unresolved save/delivery and chooses to restart, launch a
**fresh run**, preserving the original factory, adoption/replan arguments, node intent, and scope.
Examples (choose the appropriate original factory, not all of them):

```sh
perk plan
perk objective plan <objective> --node <node>
perk objective author
perk gist author --scope <scope>
```

The objective-node example is only for a **still-plannable node**. Never blindly reset an
in-progress node: inspect its saved plan first. Preserve original adoption/replan factory arguments
where applicable instead of using an unseeded example that would create a duplicate subject.

## 6. Carry content, never authority

Verify a **different run ID**. Re-enter human-checked content through the appropriate `plan_draft`,
`objective_draft`, or `gist_draft` tool, preserving structured fields. Request new human review.

Never copy correlation, consumption, provenance maps, locks, request IDs, review IDs, dispatch
intent, or approvals into the fresh run. Copy content, not authority. Leave the abandoned residue
intact for investigation and later deliberate cleanup; deleting a lock would not fix orphan
provenance or unresolved intent. No automated rollback, quarantine, or cleanup is promised.

## Check the outcome

Either the human has reconciled existing saved work and continues it, or has established no
unresolved effects and explicitly entered checked content into a distinct fresh run for new review.
Otherwise the correct outcome is an honest stop with preserved evidence, not another save attempt.

## Related

- **Look up:** [Review and authoring](../reference/in-session/review-and-authoring.md#browser-draft-review) —
  guarded effects, stale diagnostic DATA, and delivery limits.
- **Look up:** [Providers & issue backends](../reference/providers-and-backends.md#plannotator-draft-review-transport)
  — status catch-up and transport limits.
