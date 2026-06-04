# Bug: `/plan-save` no-ops on re-save instead of updating the plan in place

**Status:** confirmed, unfixed
**Surfaced:** during dogfooding — save a plan, tell the agent to make changes, re-run `/plan-save`.
**Severity:** real UX gap. Plan edits after the first save are silently stranded — there is no way
to push them to the GitHub issue.

## Symptom

If you `/plan-save` a plan, then ask the agent to revise it and `/plan-save` again, perk **no-ops**:
the existing issue is returned untouched. The revised plan markdown is never written to GitHub, and
the issue title is never updated. Nothing surfaces an error — it reports "found existing."

## Root cause — a two-layer no-op

1. **`create_plan_issue`** (`perk/github.py:325-327`) is idempotent on `run_id`: it calls
   `find_plan_issue(run_id=…)`, and if an open `perk:plan` issue already carries that `run_id` in its
   `plan-header` block, it returns that issue with `existed=True` — **no write**.

2. **`_plan_save_impl`** (`perk/cli/commands/plan_save_cmd.py:155-159`) only attaches the plan-body
   comment on a *fresh* create:

   ```python
   # Only attach the plan-body comment when we freshly created the issue (idempotent re-save
   # returns the existing one untouched; a dry run shells nothing).
   if not issue.existed and not dry_run:
       github.add_issue_comment(issue=issue.number, body=body_comment, …)
   ```

   On a re-save `issue.existed` is `True`, so the new plan markdown is **skipped entirely**. The
   title is set only at create, so it is never updated either. The `plan-body` comment keeps its
   original content.

The warm `/plan-save` passes the session's stable `run_id`
(`extension/planSave.ts:120,129` — `--run-id <runId>` from the rebuilt workflow-state), so a second
`/plan-save` in the same session **always** dedups → no-op. The only thing that changes is the local
`cache.plan-ref`, which is rewritten pointing at the same untouched issue.

## Comparison with erk

erk's `plan-save` **also** no-ops on re-save — deliberately:

- `erk exec plan-save` dedups by `session_id + plan title` and returns `skipped_duplicate: true` /
  *"This session already saved PR #N. Skipping duplicate creation."*
  (`src/erk/cli/commands/exec/scripts/plan_save.py:431-449`). This is an intentional anti-duplicate
  defense for retry loops (see erk `docs/learned/planning/session-deduplication.md`).

But **erk splits create from update** — it has a separate command perk never ported:

- **`erk exec plan-update --plan-number N`** (`src/erk/cli/commands/exec/scripts/plan_update.py`):
  *"updates the plan content comment on an existing GitHub issue"* + *"Update issue title from plan
  H1 heading."* This is the explicit in-place update path.
- Plus a higher-level `erk pr replan` workflow.

**perk ported the `plan-save` (dedup) half but never built the `plan-update` half.** So in erk you
update a saved plan with `plan-update` (not by re-running `plan-save`); in perk there is *no* command
that pushes plan edits to the issue at all.

## Fix feasibility — the building blocks exist

- **`_patch_comment_body(comment_id, body, repo_root)`** (`perk/github.py:619`) — the comment-PATCH
  primitive built for objectives in T11. Reusable directly.
- The plan body lives in a `plan-body` metadata block (`<!-- perk:metadata-block:plan-body -->`,
  `perk/plan.py:36`) in the issue's first comment.

One wrinkle: perk does **not** store the plan-body comment id (unlike objectives, which keep
`objective_comment_id` in their header). `add_issue_comment` (`perk/github.py:354`) posts without
capturing the id, and `PLAN_HEADER_FIELDS` (`perk/plan.py:41`) has no comment-id field. So an update
path would either:
- (a) list the issue's comments and find the one containing the `plan-body` marker, or
- (b) start backfilling the comment id at create time (mirroring the objective two-step create).

## Proposed fixes (decision pending)

1. **Port erk's split (recommended, faithful).** Add a `perk plan-update` worker + a warm
   `/plan-save`-on-existing path (or a `plan_update` tool) that, when `existed`, re-finds the
   `plan-body` comment and `_patch_comment_body`s the new markdown (+ optionally PATCHes the title).
   Keeps `plan-save`'s dedup contract intact (no duplicate-creation regressions). Reuses
   `_patch_comment_body`.

2. **Make `/plan-save` an upsert.** Flip `_plan_save_impl` so that on `existed` it *updates* the body
   comment instead of skipping. Simpler surface, but it changes the deliberate idempotency contract
   erk and perk both rely on — a re-save would then always write.

**Recommendation:** option 1 — it matches erk, preserves the anti-duplicate guarantee, and reuses the
existing comment-PATCH primitive. A real fix should ship as a turn that amends the plan-save contract
(`shared/contracts.md`) and adds a verify gate.

## References

- perk: `perk/cli/commands/plan_save_cmd.py:155-159`, `perk/github.py:325-327` (`create_plan_issue`),
  `perk/github.py:354` (`add_issue_comment`), `perk/github.py:619` (`_patch_comment_body`),
  `perk/plan.py:36` (`PLAN_BODY_KEY`), `perk/plan.py:41` (`PLAN_HEADER_FIELDS`),
  `extension/planSave.ts:120,129`.
- erk: `src/erk/cli/commands/exec/scripts/plan_save.py:431-449` (dedup),
  `src/erk/cli/commands/exec/scripts/plan_update.py` (in-place update),
  `docs/learned/planning/session-deduplication.md`.
