# How to run the learn-docs factory

Consolidate accumulated `perk:learn` issues into committed `docs/learned/` knowledge by running the
learned-docs plan factory.

## Steps

1. **Start the factory.** Inside a `pi` session run
   [`/learn-docs`](../reference/in-session.md#learn-docs), or from the shell run
   [`perk learn docs --gather`](../reference/cli.md#perk-learn-docs). It gathers the open
   `perk:learn` issues into an inbox and authors a **read-only** `docs/learned` consolidation
   **plan** — it does **not** write docs directly.
2. **Review and approve the plan.** Read the consolidation plan and approve it like any other plan;
   approval saves it to GitHub.
3. **Drive it through the spine.** Take the saved plan through the ordinary
   implement → submit → land flow (see
   [How to drive a change through the full spine](drive-the-full-spine.md)). The docs are written
   during **implement**, not by the factory.
4. **Land it.** On land, the consumed `perk:learn` issues are closed and labelled
   `perk:consolidated`.

> **It is a plan factory.** Like [`/objective-plan`](../reference/in-session.md#objective-plan),
> `/learn-docs` produces a plan to route through the spine — don't expect it to edit `docs/learned/`
> directly.

---

← Back to the [how-to router](index.md).
