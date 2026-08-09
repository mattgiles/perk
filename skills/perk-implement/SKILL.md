---
name: perk-implement
description: Implementing a perk plan in the implement stage — read the plan, work in focused steps, keep a live todo checklist seeded from the plan's `## Steps` list, then open the PR with /submit. Use when implementing a perk plan on a worktree branch.
stages: [implement]
disable-model-invocation: true
references:
  - backends/github
  - backends/linear
---

# Implementing a perk plan (the implement stage)

The implement stage is where a saved perk plan becomes code on its own worktree branch. The flow is
simple and you own all of it:

1. **Read the full plan** first — the launch prompt gives you the exact read command and names
   the issue backend (`You are implementing perk plan <backend> #<id>`); per-backend reading
   recipes live in `backends/<backend>.md` (`github`, `linear`). The plan body is the contract —
   implement *that*, not a reinterpretation.
2. **Work in focused steps** and keep the tree committable — commit as coherent units land.
3. **Open the PR** with `/submit` once the implementation is complete and committed.

## Progress tracking (the todo checklist)

Keep a live checklist with the `todo` tool — the checklist overlay is the progress surface for the
implement session.

**Seed it from the plan's `## Steps` list before you start**: one item per numbered step, in
order. For a prose plan (no `## Steps`), derive a short checklist from the plan body yourself.

**Keep it live and honest**: mark an item in progress when you start it and complete when it
lands; split or add items as the work reveals more. The checklist must always reflect where the
implementation actually stands — it is yours to own, not a passive mirror of the plan.
