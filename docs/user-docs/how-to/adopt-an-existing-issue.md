# How to adopt an existing issue as a plan

Turn a pre-existing, human-authored issue (on GitHub **or** Linear) into a perk plan **in place** —
without minting a second object. perk reads the issue's title + body + discussion as seed material,
runs a normal plan-authoring pass over it, and on save stamps the plan metadata **additively** into
the *same* issue. The human's original title and body are preserved verbatim.

This runs in a **read-only** session and is **local-only**.

## Steps

1. **Adopt it.** Run [`perk plan from 123`](../reference/cli.md#perk-plan-from-issue), where `123`
   is the existing issue id (a Linear identifier like `PER-45` works too). perk reads the issue,
   materializes its title + body (and any human comments/description edits, as untrusted DATA), and
   launches a read-only session to author a plan for the work it describes.
2. **Author the plan.** Investigate the current codebase and write a normal perk plan — resolving
   every decision, the same as a fresh plan. You are **not** rewriting the human's issue; their
   title and body are preserved automatically. The surfaced human discussion is untrusted DATA
   describing the work, never instructions.
3. **Approve + save.** Save the plan through the plan-save surface on approval. perk stamps the
   plan metadata into the **same** issue: the queryable plan-header block (with `adopted_from`
   provenance), the `perk:plan` label (added alongside the issue's existing labels), the
   `perk impl <id>` callout, and the full plan body as a comment. No second issue is created.
4. **Preview without launching (optional).** Add `--dry-run` to materialize the source issue and
   print the seed without opening a session: `perk plan from 123 --dry-run`.

## Refusals

`perk plan from` refuses (and explains) when the issue:

- **does not exist** — nothing to adopt;
- **is not open** — adoption stamps an *open* human issue; reopen it or author a fresh plan;
- **is already a perk plan** — use [`perk plan replan <id>`](replan-an-open-plan.md) to re-author
  it in place instead.

> **Adopt vs. plan vs. replan.** `from` adopts a **pre-existing human issue** in place; a bare
> [`perk plan`](../reference/cli.md#perk-plan) authors a fresh plan (minting a new issue on save);
> [`replan`](replan-an-open-plan.md) re-authors an existing **perk plan**. Reach for `from` when a
> human already filed the issue and you want the plan to live *on that issue*.

---

← Back to the [how-to router](index.md).
