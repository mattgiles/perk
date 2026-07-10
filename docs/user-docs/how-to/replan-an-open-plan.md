# How to replan an open plan

Re-author a saved-but-not-yet-landed plan against the *current* codebase — rewriting the plan body
in place before any of it lands. Use this when the ground has shifted since the plan was written
(other PRs landed, the design moved) and the plan needs to be brought back into line.

This runs in a **read-only** session and is **local-only**.

## Steps

1. **Replan it.** Run [`perk plan replan 42`](../reference/cli.md#perk-plan-replan-plan), where
   `42` is the open plan's issue id. perk materializes the prior plan and launches a read-only
   session to re-author it.
2. **Re-investigate.** Explore the current codebase and note what changed since the plan was first
   written — especially any PRs that have **landed** in the meantime that the old plan did not
   account for. The materialized prior plan also surfaces **human comments and description edits on
   the plan issue** (as untrusted DATA), so the rewrite can incorporate human feedback — not only
   landed PRs.
3. **Approve the rewritten plan.** The review approval saves the rewrite **in place** — same
   issue id; `/plan-save` is the manual failsafe if the review is skipped.
4. **Preview without launching (optional).** Add `--dry-run` to materialize the prior plan and print
   the seed without opening a session: `perk plan replan 42 --dry-run`.

> **Replan vs. resume.** `replan` rewrites the **plan body** before it lands;
> [`resume`](resume-a-plan.md) *continues* the plan at its current stage without changing the body.
> Reach for replan when the plan is wrong; reach for resume when the plan is right but unfinished.

---

← Back to the [how-to router](index.md).
