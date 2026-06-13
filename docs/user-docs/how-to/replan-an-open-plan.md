# How to replan an open plan

Re-author a saved-but-not-yet-landed plan against the *current* codebase — rewriting the plan body
in place before any of it lands. Use this when the ground has shifted since the plan was written
(other PRs landed, the design moved) and the plan needs to be brought back into line.

This runs in a **read-only** session and is **local-only**.

## Steps

1. **Replan it.** Run [`perk replan 42`](../reference/cli.md#perk-replan-plan-alias-rp) (alias
   `perk rp 42`), where `42` is the open plan's issue id. perk materializes the prior plan and
   launches a read-only session to re-author it.
2. **Re-investigate.** Explore the current codebase and note what changed since the plan was first
   written — especially any PRs that have **landed** in the meantime that the old plan did not
   account for.
3. **Approve the rewritten plan.** Save the revised body through the plan-save surface on approval.
   The rewrite replaces the plan in place; the issue id stays the same.
4. **Preview without launching (optional).** Add `--dry-run` to materialize the prior plan and print
   the seed without opening a session: `perk replan 42 --dry-run`.

> **Replan vs. resume.** `replan` rewrites the **plan body** before it lands;
> [`resume`](resume-a-plan.md) *continues* the plan at its current stage without changing the body.
> Reach for replan when the plan is wrong; reach for resume when the plan is right but unfinished.

---

← Back to the [how-to router](index.md).
