---
title: "How to run the learn-code factory"
description: "Route the pre-stamped SHOULD_BE_CODE perk:learn issues into their real code homes by running the learn-code plan factory."
sidebar:
  order: 2200
sidebarGroup: "Objectives & learnings"
---

# How to run the learn-code factory

Route the pre-stamped `SHOULD_BE_CODE` `perk:learn` issues into their real code homes by running the
learn-code plan factory — the additive sibling of
[the learn-docs factory](run-the-learn-docs-factory.md).

## Steps

1. **Start the factory.** Inside a `pi` session run
   [`/learn-code`](../reference/in-session.md#learn-code), or from the shell run
   [`perk learn code --gather`](../reference/cli.md#perk-learn-code). It gathers only the open
   `perk:learn` issues `/learn` classified `SHOULD_BE_CODE` into a **lean** inbox (each learning's
   classification + an optional `target` pointer, no docs scan) and authors a **read-only** plan —
   it does **not** edit code directly.
2. **It verifies the target.** For each learning the factory finds and confirms the precise code
   home (a type/constant, comment, docstring, schema, or user-doc), reading the codebase to verify
   the `target` before committing a step. The classification is a default route, not a verdict.
3. **Review and approve the plan.** Read the code plan and approve it like any other plan; approval
   saves it to GitHub.
4. **Drive it through the spine.** Take the saved plan through the ordinary
   implement → submit → land flow (see
   [How to drive a change through the full spine](drive-the-full-spine.md)). The code is changed
   during **implement**, not by the factory.
5. **Land it.** On land, the consumed `perk:learn` issues are closed and labelled
   `perk:consolidated`.

> **It is a plan factory.** Like [`/learn-docs`](../reference/in-session.md#learn-docs),
> `/learn-code` produces a plan to route through the spine — don't expect it to edit code directly.
> An empty inbox cross-hints `/learn-docs`, where doc-destined learnings are consolidated.

---

← Back to the [how-to router](index.md).
