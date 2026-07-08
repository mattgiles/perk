# How to work with implementation checkpoints

Track step-by-step progress through an implement session. perk's checkpoints turn a plan's numbered
steps into an ordered checklist and advance it as the implementing agent emits inline markers — so
you (and the status chip) can see exactly which step is in flight at any moment.

## Steps

1. **Author a `## Steps` list in the plan.** Add a numbered list under a `## Steps` heading in the
   plan body. The numbers in that list are the only valid checkpoint step numbers. (The optional
   `## Steps` section is documented by the `perk-plan` skill — author it when you want explicit
   per-step tracking.)
2. **Implement the plan.** Launch implement as usual
   ([`perk implement`](../reference/cli.md#perk-implement-plan-alias-impl)). The session seeds an
   ordered checklist from the `## Steps` list.
3. **Watch the markers advance.** As it works, the implementing agent emits `[WIP:n]` when it
   **starts** step *n* and `[DONE:n]` when it **finishes** — each marker advances the checkpoint.
4. **Check progress any time.** Watch the status chip, or run warm `/checkpoints` for a one-line,
   read-only summary of done/total and the current step. (In-session command; its reference is
   coming with Objective [#453](https://github.com/mattgiles/perk/issues/453) Node 2.2.)

## Prose plans (no `## Steps`)

A prose plan with no `## Steps` list is **inert** for the *explicit* checklist — the `[WIP:n]` /
`[DONE:n]` markers have no authored numbers to bind to. But an implement session can **generate** a
bounded checklist for a prose plan automatically and inject it; when that happens, the agent uses
exactly the generated step numbers. If no checklist is generated, checkpoints stay inert and the
status bar shows a coarse stage label instead — don't invent step numbers.

---

← Back to the [how-to router](index.md).
