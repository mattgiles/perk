---
title: "How to target a non-default base branch"
description: "Point plans and objectives at a different target branch when the repo's default is not where your work should land."
sidebar:
  order: 2090
sidebarGroup: "Core workflow"
---

# How to target a non-default base branch

By default every perk plan opens its PR against the repo's GitHub default branch and cuts its
worktree from that branch's tip. Point plans and objectives at a **different** target branch (e.g.
`develop`, a release line, or a long-running feature branch) when the default is not where your
work should land.

The chosen base drives all three consumers: the PR's merge target, the worktree branch
start-point, and the `/submit` merge-conflict probe. It is **pinned at save time** — a later config
change never retargets an already-saved plan or objective.

## Choose where the base comes from

There are two ways to declare a non-default base; they share one precedence chain:

> **the objective's own base → `[workflow] base` → the GitHub default branch.**

### Repo-wide default — `[workflow] base`

Set the default target branch for every standalone plan (and every objective that does not
override it) in committed `.perk/config.toml`:

```toml
[workflow]
base = "develop"
```

Standalone plans saved in this repo now target `develop` and base their worktrees off
`origin/develop`. See the [`[workflow]` config reference](../reference/configuration.md#workflow).

### Per-objective base — `objective create --base`

An objective declares its own target branch, which **every node plan inherits**:

```bash
perk objective create --body objective.md --base develop
```

When authoring an objective in a read-only session, pass `base` to the `objective_draft` /
`objective_save` tools instead — it rides the draft artifact through the review-first save (omit it
to use the repo default).

The objective is the source of truth for its node plans: when you plan a node, `perk plan save`
reads the objective's pinned `base` and copies it onto the plan. If `--base` is omitted at create
time, the objective pins the repo's `[workflow] base` instead (so it stays self-describing).

## What happens at save and submit

1. **Save.** `perk plan save` resolves the effective base once (objective base → `[workflow] base`
   → none) and pins it into both the plan's GitHub header and the local plan-ref.
2. **Implement.** `perk implement` cuts the `plan-<id>` worktree branch from `origin/<base>` instead
   of the detected trunk.
3. **Submit.** `/submit` opens the PR against the pinned base and probes mergeability against it.
4. **Land.** GitHub only autocloses a `Closes #N` footer when a PR merges into the **default**
   branch, so when the PR's base is non-default perk closes the plan issue explicitly at land
   (idempotent, fail-open). Default-base lands are unchanged — GitHub's native autoclose handles
   them.

When no base is declared anywhere, behavior is unchanged: plans target the GitHub default branch.

> **`base` vs. the `--base` flag.** The pinned `base` above is the PR merge target. The
> `perk implement --base <ref>` flag is a separate one-off git start-point override (for stacking a
> branch on another) — it still wins the worktree start-point verbatim but does not change the PR
> target.

---

← Back to the [how-to router](index.md).
