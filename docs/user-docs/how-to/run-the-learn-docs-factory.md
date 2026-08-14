---
title: "How to run the learn-docs factory"
description: "Consolidate accumulated perk:learn issues into committed learned-docs knowledge by running the learned-docs plan factory."
sidebar:
  order: 2190
sidebarGroup: "Objectives & learnings"
---

# How to run the learn-docs factory

Consolidate accumulated `perk:learn` issues into committed `docs/learned/` knowledge by running the
learned-docs plan factory.

## Steps

1. **Start the factory.** Inside a `pi` session where a plan can be saved (the default
   main-checkout session) run [`/learn-docs`](../reference/in-session/workflow-commands.md#learn-docs), or from the
   shell run [`perk learn docs`](../reference/cli.md#perk-learn-docs) (the cold door — it launches
   its own factory session). A session where the `plan_save` tool is not active (read-only, a
   worktree stage, or a provider restriction) refuses `/learn-docs` and points at the cold door.
   The factory gathers the
   **doc-destined** open `perk:learn` issues into an inbox and authors a **read-only**
   `docs/learned` consolidation **plan** — it does **not** write docs directly. The gathered records
   are session-grounded and carry a routable classification (a `decision`, optional `target`);
   pre-stamped `SHOULD_BE_CODE` issues are handled by [`/learn-code`](run-the-learn-code-factory.md)
   instead.
2. **It curates AND verifies.** The factory consolidates the doc-destined learnings (cleanup-first,
   regenerating the routing via `perk learn docs-sync`), and still **verifies placement**: when a
   learning actually belongs in code/comment/docstring/schema/user-docs, the plan emits a
   `SHOULD_BE_CODE` follow-up step routing it to code rather than forcing a learned doc.
3. **Review and approve the plan.** Read the consolidation plan and approve it like any other plan;
   approval saves it to GitHub.
4. **Drive it through the spine.** Take the saved plan through the ordinary
   implement → submit → land flow (see
   [How to drive a change through the full spine](drive-the-full-spine.md)). The docs are written
   during **implement**, not by the factory.
5. **Land it.** On land, the consumed `perk:learn` issues are closed and labelled
   `perk:consolidated`.

> **It is a plan factory.** Like [`/objective-plan`](../reference/in-session/workflow-commands.md#objective-plan),
> `/learn-docs` produces a plan to route through the spine — don't expect it to edit `docs/learned/`
> directly.

## Related

- **Do:** [How to run the learn-code factory](run-the-learn-code-factory.md) — route the
  SHOULD_BE_CODE learnings this factory defers.
- **Do:** [How to drive a change through the full spine](drive-the-full-spine.md) — the implement →
  submit → land flow the saved plan rides.
- **Look up:** [Workflow commands](../reference/in-session/workflow-commands.md) — the exact
  `/learn-docs` and `/learn` semantics.
