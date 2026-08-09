# How to track implement progress

Track step-by-step progress through an implement session. The implement session keeps a **live
todo checklist** (the borrowed checklist overlay) seeded from the plan's numbered steps — the
implementing agent owns it and keeps it honest as the work unfolds.

## Steps

1. **Author a `## Steps` list in the plan.** Add a numbered list under a `## Steps` heading in the
   plan body — it becomes the checklist seed. (The optional `## Steps` section is documented by
   the `perk-plan` skill — author it when you want to shape the initial checklist yourself.)
2. **Implement the plan.** Launch implement as usual
   ([`perk implement`](../reference/cli.md#perk-implement-plan-alias-impl)). The session seeds one
   checklist item per step, in order, before starting work.
3. **Watch the checklist live.** The agent marks items in progress and complete as it works, and
   splits or adds items when the work reveals more — the checklist is dynamic and model-owned, not
   a frozen copy of the plan.
4. **Check progress any time.** Open the checklist overlay (the `todo` list) in the interactive
   TUI — it is the progress surface for the implement session.

## Prose plans (no `## Steps`)

A prose plan works too: the implementing agent derives a short checklist from the plan body itself
before starting, then keeps it live the same way. An authored `## Steps` list remains preferred —
it is deterministic, reviewable, and visible in the plan issue.

---

← Back to the [how-to router](index.md).
