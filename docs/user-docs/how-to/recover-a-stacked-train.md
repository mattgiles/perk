---
title: "How to recover a stacked delivery train"
description: "Diagnose an interrupted or drifted stacked-train operation from its symptom and conclude it with the right sync, recover, or handoff-repair move."
sidebar:
  order: 2185
sidebarGroup: "Objectives & learnings"
---

# How to recover a stacked delivery train

Diagnose an interrupted or drifted stacked-train operation from its symptom and conclude it
with the right move. The first move is always **read-only visibility**:
[`perk objective stack status`](../reference/cli/objective.md#perk-objective-stack-status-objective)
shows the train's unresolved operations, the pending conflict-continuation manifest, and any
orphaned residue — plus each published layer's `handoff <state>` and any `planning gated:`
line (the handoff rows below); [`perk objective stack recover
--dry-run`](../reference/cli/objective.md#perk-objective-stack-recover-objective) classifies every
unresolved operation against fresh authority **without acting**. Read first, then pick the
row below that matches what you see. In a session, the same surfaces are `/objective-stack`,
`/objective-sync`, `/objective-recover`, and `/objective-land` (see
[Workflow commands](../reference/in-session/workflow-commands.md)).

## Interrupted operations

| Symptom | First command | Classification | Action |
|---|---|---|---|
| A fresh sync refuses `sync_conflict_pending` — a rebase conflict stopped a cascade, and the refusal names the retained worktree + continuation manifest | Finish the rebase yourself in the retained worktree (`git rebase --continue`) — perk never drives conflict resolution | — | [`perk objective stack sync --continue`](../reference/cli/objective.md#perk-objective-stack-sync-objective) revalidates the captured inputs and concludes the interrupted cascade; `stack sync --abort` discards the retained continuation instead (confirmation-gated — the prompt names exactly what gets deleted) |
| An unresolved PUBLISH operation (a crashed `/submit`) in the `stack status` report | [`perk objective stack recover --dry-run`](../reference/cli/objective.md#perk-objective-stack-recover-objective) | recover only **reports** PUBLISH | Re-run `/submit` — publish's own resume owns the conclusion |
| An unresolved SYNC or ADOPT operation | [`perk objective stack recover`](../reference/cli/objective.md#perk-objective-stack-recover-objective) | `all_after` / `all_before` / `mixed` | `all_after` rolls forward automatically; a proven `all_before` is abandoned under confirmed `--abandon`; `mixed` only ever reports — investigate by hand |
| An unresolved TRANSFER (an interrupted `perk objective replan` — planning against the objective refuses and names the predecessor) | [`perk objective stack recover <old-objective-id>`](../reference/cli/objective.md#perk-objective-stack-recover-objective) — run it against the **predecessor** objective id the refusal names | `all_after` / `all_before` / `mixed` | A successor that exists and corroborates rolls forward to completion; an absent successor is abandoned under confirmed `--abandon`; `mixed` reports |
| An interrupted LAND (`pending` / `unexpected_enqueued` outcome; further landing is blocked until it concludes) | [`perk objective stack recover --dry-run`](../reference/cli/objective.md#perk-objective-stack-recover-objective) | handle probe + per-PR observation → `all_after` / `all_before` / `external_prefix` / `in_flight` / `mixed` | `all_after` rolls forward automatically (layers finalized, objective closed); a proven `all_before` is abandoned under confirmed `--abandon`, then re-land; `in_flight` is report-only — the merge request is still live, rerun recover later; `mixed` reports |

## Out-of-band drift

| Symptom | First command | Classification | Action |
|---|---|---|---|
| A prefix of the train was merged outside perk (someone pressed GitHub's merge button on the bottom layer(s)) | [`perk objective stack recover --dry-run`](../reference/cli/objective.md#perk-objective-stack-recover-objective) | `external_prefix` — a bottom-contiguous merged prefix with every remaining layer open at its recorded head | `stack recover --accept-prefix` records the breach (confirmation-gated), finalizes the merged layers, and leaves the remainder re-landable: [`stack sync --base`](../reference/cli/objective.md#perk-objective-stack-sync-objective), then [`stack land`](../reference/cli/objective.md#perk-objective-stack-land-objective). Caveat: an undeleted merged branch can leave the remainder's lowest PR reported as `pr_drift` until you delete the merged branch (GitHub then retargets the PR) or retarget it manually |
| A published branch was edited out-of-band — sync refuses `remote_drift` / `pr_drift` | [`perk objective stack status`](../reference/cli/objective.md#perk-objective-stack-status-objective) | — | A deliberate edit: adopt it with [`stack sync --adopt NODE`](../reference/cli/objective.md#perk-objective-stack-sync-objective) and cascade the layers above; an edit you can't explain: investigate before adopting anything |
| The objective base advanced (`base_advanced` notice in the status report — a notice, never a blocker) | [`perk objective stack status`](../reference/cli/objective.md#perk-objective-stack-status-objective) | — | [`stack sync --base`](../reference/cli/objective.md#perk-objective-stack-sync-objective) re-anchors the whole train onto the advanced base |
| Leftover `sync-*` worktrees or `refs/perk/sync/*` refs (a killed sync process) | [`perk objective stack recover`](../reference/cli/objective.md#perk-objective-stack-recover-objective) | — | The recover **orphan sweep** collects residue no parseable continuation manifest claims, after every conclude/report pass; an unparseable manifest skips the whole sweep (`sweep_skipped` — an unreadable claim could be protecting anything) |

## Handoff repair

Handoff states are review-side facts on the **stamp axis** — these repairs never involve
`stack sync` or `stack recover`.

| Symptom | What happened | Repair |
|---|---|---|
| Planning refuses typed `node_not_handoff_ready` (or `objective next`/`show`/`run` names a handoff blocker) | A direct dependency's post-review handoff stamp is missing | Run the copyable remediation the refusal prints: [`perk ready <PLAN>`](../reference/cli.md#perk-ready-plan) on the blocking dependency, after its review + address |
| `handoff stale` — the status line discloses `stamped <sha12> ≠ head <sha12>` | The layer's head moved after the stamp: a self-rewrite (address / re-`/submit`) or a cascade from a lower layer's fix — a stamp binds the exact reviewed head and never carries forward mechanically | Re-review the new head, then re-ready (`/ready`, or `perk ready <PLAN>`) |
| `handoff suspended` | The stamped PR was converted back to draft — a transient hold; the stamp still stands | Any return to non-draft resumes it — e.g. the idempotent `/ready` re-run (it converges on the same stamp) |
| The stamp succeeded but the ready-time reconcile session failed to launch (the loud second outcome, exit 1) | Only the pass launch failed; the stamp is never rolled back | The stamp stands; re-run `perk ready <PLAN>` from an interactive terminal to enter the pass |
| The ready-time pass refuses `stacked_append_refused` | The tail-append guard blocked a structural roadmap change (a stacked roadmap accepts only guarded `pending` tail-appends) | Structural changes route through [`perk objective replan`](../reference/cli/objective.md#perk-objective-replan-number) |

## What recover never does

**Retry is never recover's verb.** Recover *concludes* — it classifies an unresolved
operation against fresh authority and either rolls a verified `all_after` forward, abandons
a proven `all_before` under confirmation, or reports. When a retry is the right move, the
report names the **owning command** (`/submit` for PUBLISH, `stack sync` for a cascade,
`stack land` for a landing). And two classifications never act at all: `mixed` and
`in_flight` only ever report — `mixed` needs human investigation, `in_flight` needs you to
rerun recover once the live merge request settles or expires.

## Related

- **Learn:** [Drive a stacked objective to one atomic landing](../tutorials/drive-a-stacked-objective.md) — the healthy end-to-end train the recovery moves restore.
- **Do:** [How to review a stacked PR train](review-a-stacked-train.md) — resume review once the train is consistent.
- **Look up:** [Objective commands](../reference/cli/objective.md) — exact `stack` sync and recover syntax.
