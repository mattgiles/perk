---
title: "Drive a stacked objective to one atomic landing"
description: "Author a stacked objective, publish its layers as one pull-request train, cascade review feedback, and land the whole train atomically."
sidebar:
  order: 1030
---

# Drive a stacked objective to one atomic landing

By the end of this lesson you will have authored an objective with **stacked** delivery,
published its two plans as one **pull-request train** — each layer's PR stacked on its
parent's branch — cascaded a review fix through the train automatically, and landed the
whole train in **one atomic merge**. There is one path, and you walk it to the end.

Stacked delivery is for the goal whose layers **build on each other's code**: layer 2 calls
a function layer 1 introduces, so the plans cannot land independently — they land together
or not at all. (When the nodes are independent, pick **incremental** — the recommended
default you used in [Drive a multi-plan goal with an objective](./drive-an-objective.mdx).)

## Before you start

You've completed [Get started with perk](./get-started.md) and
[Drive a multi-plan goal with an objective](./drive-an-objective.mdx): perk is installed and
verified, and you know the spine (`implement → /submit → /ready → /land`) and the objective
loop (`author → plan → implement → land`). This lesson starts from a fresh scratch repo.

## Step 1 — Create a scratch repo

Create a brand-new **public** repo to play in, seed it with one minimal file, push it, and
wire it for perk. This repo is disposable — you'll delete it at the end. (Public matters
here: the stacked save reads the base branch's merge rules, and GitHub exposes that API on
private repos only on paid plans — on a free-plan private repo the save refuses honestly,
which you'll see in Step 2.)

```bash
gh repo create perk-stacked-tutorial --public --clone
cd perk-stacked-tutorial
```

Create `textkit.py` holding only a module docstring — the text-utilities module you'll
build in two stacked layers:

```python
"""A tiny text-utilities module, built one stacked layer at a time."""
```

Commit it, push `main`, then wire the repo for perk and commit that wiring:

```bash
git add textkit.py && git commit -m "Add textkit.py"
git push -u origin main
perk init
git add -A && git commit -m "perk init"
```

Run the rest of this tutorial from inside the `perk-stacked-tutorial` checkout.

## Step 2 — Author the objective, choosing stacked

Author the objective exactly as in the previous lesson:

```bash
perk objective author
```

In the read-only authoring session, type one short request — note the cross-layer
dependency, which is what motivates stacked:

> Author an objective to build a small text-utilities module in textkit.py, with a two-node
> roadmap: node 1.1 adds normalize(text) (collapse whitespace, lowercase), node 1.2 adds
> slug(text) built on normalize(). Use stacked delivery — layer 2 calls layer 1's code.

The agent drafts the objective prose plus the 2-node roadmap and asks you the **delivery
choice**. This time pick **stacked** — the review surface shows it as a prominent
`**Delivery:**` line so you can't approve it by accident. **Approve** the draft.

On approval, perk validates the roadmap for stacked delivery (2–100 non-skipped nodes, a
clean dependency graph) and runs a **capability preflight** against the real Git/GitHub
plane — the native-stack API surface, squash direct-merge allowed and no merge queue on the
base, and an atomic-push dry-run — *before* anything is written. Two honest outcomes:

- **The save succeeds.** The objective is saved with `delivery: stacked` and a stable
  train identity, and perk prints the issue URL.
- **The save refuses.** A repository that can't take a stacked train gets a typed
  `capability_unsupported` refusal naming the exact expected-vs-observed facts — for
  example, on a free-plan private repo:

  ```
  This repository cannot take a stacked delivery train against base 'main':
  - merge-rules: could not verify the merge rules for base 'main' (can't verify ⇒ don't promise): …
  ```

  This is a legitimate stopping point, not a perk failure: nothing was written, and the
  fallback is to author the same roadmap with **incremental** delivery instead. If you hit
  it here, re-check that your scratch repo is public, then re-author.

Inspect what was saved — substitute your objective issue number for `<N>`:

```bash
perk objective show <N>
```

Both nodes start `pending`, exactly as in the previous lesson. The stacked difference shows
on the **delivery train** view:

```bash
perk objective stack status <N>
```

```
Objective #<N>: stacked delivery train (base main, published prefix 0/2)
  lineage 01XXXXXXXXXXXXXXXXXXXXXXXX
  1. 1.1 unplanned [unpublished] no pr
  2. 1.2 unplanned [unpublished] no pr
  next build-ready: 1.1
no findings
```

One line per layer, bottom→top, plus the `next build-ready:` line — the single layer perk
will plan next.

## Step 3 — Plan the first node

On a stacked objective, node selection is **build-readiness-derived**: perk reconstructs
the live delivery train and selects the next **build-ready** layer — not merely the next
pending node. See it enforce that — ask for the wrong node explicitly, and it refuses with
a typed `node_not_build_ready` error:

```bash
perk objective plan <N> --node 1.2
```

```
Error: Node 1.2 is not the build-ready layer — the next build-ready node is 1.1 (stacked planning follows the delivery order).
Inspect the train: perk objective stack status <N>
```

Now plan the node perk selects on its own:

```bash
perk objective plan <N>
```

In the read-only plan session, type one short request:

> Plan node 1.1: add normalize(text) to textkit.py — collapse whitespace runs to single
> spaces, strip the ends, and lowercase.

**Approve** the plan. As before, perk saves it as a plan issue linked to node `1.1` and the
node advances to `in_progress`.

## Step 4 — Implement and publish layer 1

Build it with the spine you already know:

```bash
perk implement
```

The agent adds `normalize()` to `textkit.py`, committing as it goes. Then, still in the
session:

```
/submit
```

perk opens a **draft PR** for the layer's canonical `plan-<id>` branch. Because this is the
train's bottom layer, the PR targets the **objective base** (`main`) — exactly like an
ordinary plan so far. Check it:

```bash
gh pr view    # base: main, draft
```

Keep this session open — you'll come back to it in Step 6.

## Step 5 — Plan, implement, and publish layer 2

Now the stacked shape appears. Plan the next node — from a fresh shell in the scratch
repo's root checkout:

```bash
perk objective plan <N>
```

perk selects node `1.2` even though layer 1 is only published, not merged — on a stacked
train, a published-but-unmerged predecessor is exactly what the next layer builds on. Type:

> Plan node 1.2: add slug(text) to textkit.py, built on normalize() — join the normalized
> words with hyphens.

**Approve** it, then implement:

```bash
perk implement
```

Watch the launch output: perk reconstructs the delivery train and starts layer 2's worktree
**from layer 1's branch** (`layer 1.2 starts from plan-<id> @ <sha>`), so the new session
begins with `normalize()` already present. The agent adds `slug()` — calling
`normalize()` — and commits. Then:

```
/submit
```

This layer's draft PR targets **the parent layer's branch** (not `main`), so its GitHub
diff is only this layer's work, and the two PRs are registered together in a **native
GitHub stack** — the success message carries a stack suffix like `stack #6, layer 2/2`.
Observe the whole train:

```bash
perk objective stack status <N>
```

```
Objective #<N>: stacked delivery train (base main, published prefix 2/2)
  lineage 01XXXXXXXXXXXXXXXXXXXXXXXX
  1. 1.1 plan #<plan-1> [published] pr #<pr-1> (draft) stack exact
  2. 1.2 plan #<plan-2> [published] pr #<pr-2> (draft) stack exact
  build blocked: all layers published or landed
no findings
```

Open a layer PR on GitHub (`gh pr view <pr-2> --web`) and read its body: perk inserts a
`### This layer` section (with an explicit disclaimer — the delivery train is
authoritative; the body refreshes only at publication) and a `### Train context` table
listing every layer bottom→top. Both are presentation, not authority — the train you just
printed is the live truth.

## Step 6 — Cascade a fix through the train

Here is the payoff of stacked bookkeeping. Suppose review feedback lands on **layer 1**
(the bottom PR). Fix it the way you'd fix any plan: switch back to the layer-1 implement
session from Step 4, make the change — say, sharpen `normalize()`'s docstring — commit it,
and re-run:

```
/submit
```

perk publishes the amended layer and then **automatically cascades** the published layers
above it: layer 2's branch is rewritten onto the new layer-1 head, pushed, and verified —
no explicit sync command, and layer 2's session isn't involved. The submit result reports
how many layers moved. Confirm with:

```bash
perk objective stack status <N>    # both layers still published, heads advanced
```

(Feedback that arrives as PR review threads is addressed the same way — `/address`
classifies and fixes it, and its finalizer runs the same publish-plus-cascade.)

## Step 7 — Ready each layer

Each layer PR flips ready-for-review individually, from its own session (or worktree):

```
/ready
```

Run it in the layer-1 session, then in the layer-2 session. Readying is the review gate
only — it never merges anything. Both PRs now show ready-for-review while the train waits,
whole, for the landing.

## Step 8 — Land the whole train atomically

First preview the landing readiness — from the scratch repo's root checkout:

```bash
perk objective stack land <N> --dry-run
```

```
Objective #<N>: landing readiness (dry run) — READY
  base main: squash allowed, merge queue not required
  native stack API surface: present (host-schema evidence only)
  1. 1.1 plan #<plan-1> pr #<pr-1> OPEN ready base main head-ref plan-<id> head <sha> MERGEABLE/CLEAN
  2. 1.2 plan #<plan-2> pr #<pr-2> OPEN ready base plan-<id> head-ref plan-<id2> head <sha> MERGEABLE/CLEAN
plan: stack_merge_async via squash — top pr #<pr-2> at <sha> (2 layer(s))
```

The verdict is typed — `ready` with the exact per-PR facts and the would-be land plan, or
`blocked` with every blocker named. Note what is *not* offered: landing one layer. Try
`/land` in a layer session and it refuses with a typed `stacked_plan` error before touching
anything — a layer PR targets its parent's branch, so merging one alone would merge into
the wrong target and tear the train.

Now land — in a layer session run `/objective-land`, or from the shell:

```bash
perk objective stack land <N>
```

perk renders the land plan — every layer bottom→top with PRs and exact SHAs — and asks you
to confirm. Approve it, and the WHOLE train merges as **one journaled, atomic operation**:

```
landed 2 layer(s) atomically (operation 01XXXXXXXXXXXXXXXXXXXXXXXX)
  1.1 plan #<plan-1> (pr #<pr-1>): merged as <sha>
  1.2 plan #<plan-2> (pr #<pr-2>): merged as <sha>
objective #<N> complete — closed
reconcile evidence: 2 layer(s), final base <sha> — reconcile objective #<N> with /objective-reconcile
```

Then the close-out you know from the previous lesson runs for the whole train at once:
every layer is finalized (plan issues closed, nodes marked `done`), the objective is
**closed** because every node is terminal, and the reconcile pass is driven with the
landed-train evidence. Confirm:

```bash
perk objective show <N>       # both nodes done; objective complete
git checkout main && git pull # normalize() and slug() landed together
```

## What you did

You authored an objective whose plans **could not land independently** — layer 2 calls
layer 1's code — chose **stacked** delivery past a real capability preflight, published two
draft PRs as a native GitHub **stack** (each layer's PR on its parent's branch, each diff
just that layer), watched a layer-1 fix **cascade automatically** through the published
layers above it, readied each layer individually, and landed the whole train as **one
atomic merge** that finalized every layer and closed the objective.

The `perk-stacked-tutorial` repo was disposable — delete it whenever you like:

```bash
gh repo delete perk-stacked-tutorial
```

From here: [How to review a stacked PR train](../how-to/review-a-stacked-train.md) is the
reviewer's side of what you just drove; [How to recover a stacked delivery train](../how-to/recover-a-stacked-train.md)
is the triage map for when a train operation is interrupted or drifts; and
[Objectives → Delivery](../reference/objectives.md#delivery) is the exact reference for the
delivery choice — including stacked's current limitations.
