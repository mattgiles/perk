---
name: perk-implement
description: Implementing a saved perk plan on its worktree branch — the implement stage. Use when implementing a perk plan in a perk repo.
stages: [implement]
disable-model-invocation: true
references:
  - backends/github
  - backends/linear
---

# Implementing a perk plan (the implement stage)

The implement stage is where a saved perk plan becomes code on its own worktree branch. The flow —
read the full plan first, work in focused steps keeping the tree committable, verify as you work,
keep the live `todo` checklist seeded from the plan's `## Steps`, then open the PR with `/submit` —
is stated in your launch prompt; you own all of it. The detail it doesn't carry:

- **Per-backend plan-reading recipes** live in `backends/<backend>.md` (`github`, `linear`) — the
  launch prompt names the issue backend (`You are implementing perk plan <backend> #<id>`).
- **The plan body is the contract** — implement *that*, not a reinterpretation.
- **The checklist overlay is the progress surface** for the implement session — the checklist is
  yours to own, not a passive mirror of the plan.
