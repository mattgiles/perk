---
name: perk-implement
description: Implementing a perk plan in the implement stage — read the plan, work in focused steps, emit [WIP:n]/[DONE:n] progress markers when the plan has a `## Steps` list, then open the PR with /submit. Use when implementing a perk plan on a worktree branch.
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

## Progress markers (the checkpoint protocol)

perk tracks implementation progress with two inline markers you emit in your normal turn text:

- `[WIP:n]` — emit when you **start** work on checkpoint step *n*.
- `[DONE:n]` — emit when step *n* is **complete**.

Checkpoints surface this in the status bar: a `📋 done/total · ▶n` summary and a per-step checklist
(`☑` completed, `▶` the current step, `☐` pending). The current (`▶`) step is derived from your
latest live `[WIP:n]`, falling back to the lowest incomplete step; completion always wins (`▶` never
shows on a completed step).

**Step numbers come from the plan's `## Steps` list** — the numbered list under that heading is the
only source of valid step numbers. Emit markers that match those numbers.

**Prose plans may get a generated checklist.** If the plan has no `## Steps` list, perk may
generate a checklist on the fly and inject it as a context message ("perk generated the following
implementation checklist…"). When that injection appears, **use exactly the step numbers it
lists** — they drive the same checkpoint tracking as an authored `## Steps` list. If no injection
appears (generation is best-effort and may be unavailable), checkpoints are inert: the markers are
harmless no-ops, so **don't invent step numbers** — the status bar instead shows a coarse stage
label for the active plan.
