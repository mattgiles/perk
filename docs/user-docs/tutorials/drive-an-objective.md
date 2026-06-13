# Drive a multi-plan goal with an objective

By the end of this lesson you will have authored an **objective** with a small roadmap,
driven its first node through a bounded plan all the way to a merged pull request, and
watched perk close the loop — marking the node done and reconciling the roadmap against what
was actually built. There is one path, and you walk it to the end. An
[objective](../explanation/how-perk-thinks.md) is a long-running goal that **generates**
bounded plans node by node, rather than being implemented directly: you decompose the goal
into a roadmap, then let perk emit one focused plan per node. This tutorial assumes you have
already completed [Get started with perk](./get-started.md), so perk is installed and your
environment is verified.

## Before you start

You've completed [Get started with perk](./get-started.md): perk is installed and on your
PATH, and the environment it checks (`git`, an authenticated `gh`, `node`, `pi`, `uv`) is
verified. That is the only prerequisite — this lesson starts from a fresh scratch repo.

## Step 1 — Create a scratch repo

Create a brand-new private repo to play in, seed it with one minimal file, push it, and wire
it for perk. This repo is disposable — you'll delete it at the end.

```bash
gh repo create perk-objective-tutorial --private --clone
cd perk-objective-tutorial
```

Create `calc.py` holding only a module docstring — the arithmetic module you'll build one
objective node at a time:

```python
"""A tiny arithmetic module, built one objective node at a time."""
```

Commit it, push `main`, then wire the repo for perk and commit that wiring:

```bash
git add calc.py && git commit -m "Add calc.py"
git push -u origin main
perk init
git add -A && git commit -m "perk init"
```

`perk init` is the same wiring [Get started with perk](./get-started.md) covered (Step 3) —
see it there for the detail. Run the rest of this tutorial from inside the
`perk-objective-tutorial` checkout.

## Step 2 — Author the objective

Author the objective — the long-running goal perk will generate plans from:

```bash
perk objective-author
```

(`oauthor` is the short alias.) This opens an interactive `pi` session in **read-only
authoring mode** — the objective mirror of `perk plan`. The agent can explore the repo but
not edit it. Type one short request:

> Author an objective to build a small arithmetic module in calc.py, with a two-node roadmap:
> node 1.1 adds add() and subtract(), node 1.2 adds multiply() and divide() (with a
> zero-divisor guard).

The agent drafts the objective prose plus the 2-node roadmap, then perk presents it for your
review. **Approve** it. On approval, perk **saves the objective as a GitHub issue** (a
`perk:objective` issue), activates it, and the session leaves read-only mode. perk prints the
issue URL; you can also see it with:

```bash
gh issue list
```

Inspect the roadmap and node statuses — substitute the objective issue number perk just
created for `<N>`:

```bash
perk objective show <N>
```

You'll see the header, a progress summary, and the next actionable node — both nodes start
`pending`:

```
Objective #<N>: Build a small arithmetic module in calc.py
  summary: {'pending': 2, 'planning': 0, 'in_progress': 0, 'done': 0, 'blocked': 0, 'skipped': 0, 'total': 2}
  next: 1.1
```

## Step 3 — Plan the first node

Plan the first node of the objective:

```bash
perk objective-plan <N>
```

(`oplan` is the short alias; `<N>` is the objective issue number from Step 2.) perk selects
the next actionable node — `1.1` — and opens a **read-only plan session** scoped to just that
node, not the whole objective. Type one short request:

> Plan node 1.1: add add(a, b) and subtract(a, b) to calc.py.

The agent drafts a **bounded plan** for node `1.1` and perk presents it for your review.
**Approve** it. On approval, perk **saves the plan as a GitHub issue linked to the objective
node** and advances node `1.1` from `planning` to `in_progress`. Confirm the link and the new
status:

```bash
perk objective show <N>
```

Node `1.1` now reads `in_progress` and carries its plan-issue backlink. Because node `1.2`
sequentially follows `1.1` in the roadmap, it stays blocked until `1.1` lands — so the `next`
line reports node `1.1` in flight (with its saved plan) rather than a new plannable node:

```
Objective #<N>: Build a small arithmetic module in calc.py
  summary: {'pending': 1, 'planning': 0, 'in_progress': 1, 'done': 0, 'blocked': 0, 'skipped': 0, 'total': 2}
  next: — (in flight: node 1.1 pr #<plan-issue>)
```

## Step 4 — Implement and land the node

This is the perk spine you learned in [Get started with perk](./get-started.md) (Steps 5–7),
now driving the node's plan. Build it:

```bash
perk implement
```

With no argument, `perk implement` picks up the plan you just saved. perk materializes a
**worktree branch** and launches a fresh `pi` session primed to build that plan — the agent
adds `add()` and `subtract()` to `calc.py`, committing as it goes. Then, still inside that
session, run the three warm commands in turn:

```
/submit
```

opens a **draft PR**.

```
/ready
```

runs the repo's CI checks and flips the PR to ready-for-review. Your scratch repo configured
no checks (the `[ci]` table is commented out), so perk reports there are no checks to run —
non-fatal.

```
/land
```

squash-merges the PR into `main`. These are the same doors Tutorial 1 taught — see
[Get started with perk](./get-started.md) Steps 5–7 if you want the detail on each.

## Step 5 — Watch perk close the loop

This is the payoff. When `/land` merges the node's PR, perk does two things automatically, **in
the same session** — you don't run any extra commands:

- **Auto-done.** Because node `1.1` was backlinked to the merged plan, the land path marks the
  node `done`. You did not run an "advance node" command.
- **Auto-reconciliation.** `/land` then **auto-drives** the objective-reconcile pass: the agent
  re-reads the objective against the merged diff and rewrites any now-stale roadmap prose to
  match what was actually built. You watch the agent do this in the session.

Confirm the closed loop:

```bash
perk objective show <N>     # node 1.1 = done; node 1.2 = pending (next)
gh issue view <N>           # the objective body prose reconciled to reality
```

`perk objective show <N>` now reports node `1.1` done and node `1.2` as the next pending node:

```
Objective #<N>: Build a small arithmetic module in calc.py
  summary: {'pending': 1, 'planning': 0, 'in_progress': 0, 'done': 1, 'blocked': 0, 'skipped': 0, 'total': 2}
  next: 1.2
```

The objective is **not** closed — node `1.2` is still pending, so the goal stays open and
ready for its next lap. An objective closes only when **all** its nodes are terminal.

## What you did

You authored an **objective** with a 2-node roadmap, drove its first node through a bounded
plan to a merged PR, and watched perk **auto-mark the node done** and **reconcile the roadmap**
against what was actually built — all without an explicit "advance" or "reconcile" command.

The loop repeats: run `perk objective-plan <N>` again to plan node `1.2` (add `multiply()` and
`divide()`), and the same spine — implement → submit → ready → land — carries it home. When
the last node lands, perk closes the objective.

The `perk-objective-tutorial` repo was disposable — delete it whenever you like:

```bash
gh repo delete perk-objective-tutorial
```

To find your way around the rest of the docs, head back to the
[user-docs router](../index.md); for the concepts behind objectives, read
[How perk thinks](../explanation/how-perk-thinks.md).
