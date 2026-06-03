# Phase 2 · Turn 13 — fix `/plan-save` no-op on re-save (cold-door upsert keyed on `run_id`)

> The decision-complete plan lives on GitHub plan **#27** (`plan-body` block). This doc records the
> prior-art pass, the decisions, and — written **after** it lands — the as-built **outcomes**. A
> small **corrective turn**: no new spine handler, one bug fix that turns the cold save door into an
> upsert.

## 1. Problem

Re-running `/plan-save` after revising a plan **silently no-ops**: the revised markdown is never
pushed and the title is never updated. Two-layer no-op:

1. `github.create_plan_issue` is idempotent on `run_id` — when an open `perk:plan` issue already
   carries that `run_id` it returns `PlanIssue(existed=True)` with **no write**.
2. `_plan_save_impl` only posted the `plan-body` comment when `not issue.existed` — so a re-save
   skipped the new markdown entirely, and the title (set only at create) never moved.

The warm `/plan-save` always passes the session's stable `run_id`, so the second in-session save
**always** dedups → no-op.

## 2. Decision

Make the **cold `perk plan-save` an upsert keyed on `run_id`**, in the Python plane. On the
idempotent-existing path, perk now **updates the existing issue in place** instead of skipping:
PATCH the `plan-body` comment with the new markdown + PATCH the issue title from the (possibly
revised) plan H1.

- **Upsert in the cold door, not a separate `/plan-update` command.** The reported UX is literally
  "re-running `/plan-save` no-ops" — a separate door the agent must remember does not fix that.
  perk has one save caller; create-vs-update is fully determined by the idempotency check, which
  lives in the cold door (AGENTS.md: logic in the plane that owns its lifecycle). The warm door
  stays dumb.
- **Anti-duplicate guarantee preserved.** `create_plan_issue` still dedups and never creates a
  second issue; the new behavior only *additionally* PATCHes the existing issue. A retry-loop
  re-invocation re-PATCHes identical content (harmless idempotent overwrite).
- **Comment-id discovery is find-by-marker, not a header backfill.** perk stores no plan-body
  comment id. The update path lists the issue's comments via REST and finds the one whose body
  contains the `plan-body` block (mirrors `get_plan_body`). This also repairs **legacy** plan
  issues; a header backfill would only help post-fix plans and still need the fallback. The REST
  list returns an **integer** comment id (the `gh issue view` GraphQL node string is unusable for
  the REST comment PATCH endpoint).

## 3. Prior-art pass (verified)

- `perk/github.py`: `create_plan_issue` (idempotent-on-`run_id`, left unchanged), `add_issue_comment`
  (REST POST), `_patch_comment_body` (REST PATCH `.../issues/comments/{id}`, reused), `update_plan_header`
  (the `PATCH .../issues/{n}` shape, here with `-f title=` instead of `-F body=@`), `get_plan_body`
  (the find-the-`plan-body`-comment read), `get_pr_feedback` (REST comment list returns integer ids).
- `perk/plan.py`: `extract_plan_body`, `render_plan_body`, `derive_title` (re-derived on re-save →
  fixes "title never updated").
- `perk/cli/commands/plan_save_cmd.py`: the `if not issue.existed and not dry_run:` branch to change;
  `PlanSaveResult`, `_result_to_dict`, `_render_human`.
- `extension/planSave.ts`: `savePlan` consumes `perk plan-save --json`; `PlanSaveDetails` carries
  `existed`.
- Tests: `tests/test_github.py` stubs `subprocess.run` via `_GhDispatch`; `tests/test_plan_save.py`
  monkeypatches `github.*`.

## 4. What was built

- **`perk/github.py`** — `PlanUpdate` dataclass (`number`, `body_updated`, `title_updated`,
  `dry_run`); `_find_plan_body_comment_id(issue, repo_root) -> int | None` (REST comment list, find
  by `plan-body` marker); `update_plan_issue(*, number, title, body_comment, repo_root, dry_run)` —
  PATCH the found comment (or POST a fresh one as a legacy fallback, `body_updated=False`) + PATCH
  the title. `create_plan_issue` unchanged.
- **`perk/cli/commands/plan_save_cmd.py`** — the create/update branch; `PlanSaveResult.updated`;
  `_result_to_dict` adds top-level `updated`; `_render_human` existed-verb → "Updated".
- **`extension/planSave.ts`** — `updated?` on `PlanSaveJson` + `PlanSaveDetails`; success text
  "Updated plan #N" on the re-save path.
- **Tests** — `test_github.py`: finder match/none, comment+title PATCH, fresh-comment fallback,
  dry-run-no-shell. `test_plan_save.py`: `test_plan_save_resave_updates_in_place` (replaces the old
  idempotent-no-op test) + `--json` reports `updated`/`existed` + fresh-create reports `updated:false`.
  `planSave.test.ts`: re-save fixture → `details.updated === true` + `/Updated plan #/`.
- **`scripts/verify-p2-t13.sh`** (offline) wired into `justfile` `verify`.
- **`shared/contracts.md`** §8.4 — the upsert note + `update_plan_issue` shape.

## 5. Out of scope / deferred

- No branch push of the plan (perk's plan storage is the GitHub issue only — no impl-context file).
- No `objective_id` re-link on update (the link is set at create; flagged, not silent).
- No comment-id header backfill — find-by-marker is the chosen mechanism; `PLAN_HEADER_FIELDS`
  unchanged.

## 6. Outcomes

Built as planned, no deviations. The `verify-p2-t13.sh` turn number was free (next sequential
Phase-2 turn). `just verify`/`just ci` green. The re-save path now writes the current plan content
(comment + title) instead of skipping; legacy issues update via find-by-marker with a fresh-comment
fallback.
