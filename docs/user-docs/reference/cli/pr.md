---
title: "PR commands"
description: "Exact reference for the perk pr group — submit, address, land, ready, the review workers, and the review checkouts."
sidebar:
  order: 3014
---

# PR commands

This page holds the exact reference for the `perk pr` group — the canonical submit/address/land/
ready entries behind the flat spine aliases, the review workers, and the ephemeral review
checkouts. For the full command map and shared conventions, start at the
[CLI commands hub](../cli.md).

### `perk pr`

PR lifecycle group: the submit/land launchers, the address launcher, and the review workers.
`submit` and `land` open a primed `pi` session by default and run the deterministic worker under
`--json` (the merged commands); `address` is launcher-only; `ready` and the rest are cold-door
workers the warm TS doors delegate to, each running from inside the plan's worktree (reading the
local `cache.plan-ref`) and accepting `--json`.

### `perk pr submit`

Open a draft PR for the active plan's branch (the implement → submit boundary). The **merged**
launcher+worker: a primed `pi` session by default, the deterministic worker under `--json`; the
launcher is local-only (`cold_remote:false`). `--dry-run` follows the mode (print the launch
plan, or compose without pushing/hitting GitHub). Flat alias: [`perk submit`](../cli.md#perk-submit).

After opening the PR, the worker probes mergeability against the target branch (a local
`git merge-tree` probe; stacked submit probes the verified published head SHA rather than a
possibly-stale local trigger branch) and adds three fields to the `--json` report: `base` (the target
branch),
`mergeable` (`true` clean / `false` conflicts present / `null` undetermined — the probe is
fail-open and never changes the exit code), and `conflicts` (the conflicted paths). `--dry-run`
stays fully offline (`base: ""`, `mergeable: null`).

When the branch already has a PR (a replan reuses the `plan-<n>` branch), submit reuses it: an
**open** PR is decorated as before, a **closed** PR is reopened first (a loud `reopened closed PR
#n` note), and an **already-merged** PR is refused with `error_type: pr_already_merged` (there is
nothing to submit — start a fresh plan/branch).

A plan that is a **stacked delivery layer** (its plan-ref or plan header carries a
`delivery_lineage`) routes through the delivery module's publish operation instead of the plain
push-and-open path. The stacked route publishes the layer branch under an
exact `--force-with-lease` expectation, opens the draft PR **onto the parent layer's branch**
(not the objective base — the `--json` `base` field carries the parent), registers the PR in the
native GitHub stack, verifies every remote postcondition, and only then writes the plan-header
checkpoints. On failure the prepared operation stays recorded in the objective's journal and is
recoverable: re-running submit resumes/rolls the same operation forward. Re-submitting a
checkpoint-claimed lower layer automatically invokes the same transactional sync operation for the
suffix: only that plan's committed head is a local source, every successor starts from its verified
published head, and submit authorizes the cascade without a second prompt. Typed sync failures and
recovery guidance pass through unchanged. The `--json` report gains additive `delivery`
(`"stacked"` or null), `stack` (`{number, size, position}` or null), `operation_id`, and the
cascade-only `operation {kind, operation_id, abandoned_operation_id, resumed, no_op, affected[],
notes[]}` block; flat `operation_id` remains the compatibility alias. Incremental plans are
untouched (the fields are null).

### `perk pr address [PLAN]`

Classify PR review feedback (in an isolated child), publish committed fixes, then resolve the
threads — launcher-only (no merged `--json` worker; its warm finalizer runs `pr submit` before the
unchanged `pr resolve-threads` mechanical half). `PLAN` is an optional plan issue id or pasted
issue URL: it selects the plan canonically (one backend read), drives the launch directly, and on
a real launch updates only the main-checkout selector; omit it to address the active saved plan
(inside a plan worktree, that worktree's own binding). `perk address 1699 --remote` dispatches
exactly the selected plan; `--worktree` + `--remote` is refused. A missing `plan-<id>` checkout
is restored from the existing `origin/plan-<id>` branch; typed refusals (`plan_not_found`,
`issue_kind_mismatch` (an existing issue with no plan-header — positive plan identification),
`worktree_unbound`, `worktree_branch_mismatch`, `worktree_plan_mismatch`,
`worktree_restore_failed`) exit 1 before any launch. `--preview`
classifies the feedback only and takes no action (the warm `/address --preview` gesture; local-only,
inert on `--remote`). pi args go after the bare `--` (the shared pass-through grammar). Flat
alias: [`perk address`](../cli.md#perk-address-plan).

### `perk pr land`

Merge the active plan's PR and set the pending-learn semaphore (submit → land) — except for a
learn-docs consolidation plan, which is exempt from the land→learn cycle (no marker;
`pending_learn: false` in the envelope). The **merged**
launcher+worker: a primed `pi` session by default, the deterministic worker under `--json`; the
launcher is local-only (`cold_remote:false`). `--dry-run` follows the mode (print the launch plan, or compose without touching GitHub). The
worker also stamps the canonical `learn_state` field onto the plan-header (`pending`, or `skipped`
for a learn-docs consolidation plan; an already-`captured`/`skipped` plan is never downgraded) —
fail-open: a failed stamp warns and reports `learn_state: null` in the `--json` envelope. Refuses
a stacked-delivery plan (`delivery_lineage` on the cached plan-ref or the plan header — header
wins) before any mutation as `stacked_plan`: stacked layers land only as one atomic train, never
individually (`--dry-run` refuses on the cached ref while staying offline). Flat
alias: [`perk land`](../cli.md#perk-land).

### `perk pr ready [PLAN]`

Mark a plan's draft PR ready for review (the deliberate review gate) — a **worker-only**
command (not a merged L+W: `ready` is not a registry stage and has no launcher). `PLAN` is an
optional plan issue id or pasted issue URL: it selects the plan canonically with one backend
read, so `perk pr ready 1699` works from the repository root — ready needs no source files, no
worktree, and never writes the active-plan selector; omitted, the invoking checkout's own saved
plan is used (inside a plan worktree, that worktree's binding). An explicit `PLAN` naming an
existing issue with no plan-header refuses typed (`issue_kind_mismatch`). `--dry-run` is an
offline validation preview: it parse-checks an explicit `PLAN` and confirms a saved plan exists
on the no-argument form, but performs no backend or GitHub read — no PR is resolved or marked
(and nothing is kind-classified). For a stacked plan, the worker reconstructs the train and
fetches the projection-correlated PR: the target must be exactly published; marking a draft also
requires no unresolved operation and no structural train blocker (unrelated operational drift does
not block). An already-ready PR revalidates target identity/publication but skips those global
mutation vetoes and succeeds idempotently. A target the projection classifies as merged, closed,
wrong-base, or otherwise drifted refuses as `layer_not_published`; if the projection still says
published but the freshly fetched PR closed after reconstruction, that race refuses as
`pr_not_open`. Other typed failures include `unresolved_operation` and `structural_blockers` (plus
`no_pr` for a vanished correlated PR).
`--json` emits the unchanged machine shape. Flat alias: [`perk ready`](../cli.md#perk-ready-plan).

### `perk pr check`

Validate the active plan's PR checkout footer (the deterministic `pr check`).

### `perk pr feedback`

Fetch the active plan's PR review feedback (read-only; the classify child runs this).

### `perk pr resolve-threads`

Internal cold-door half of `finalize_address`: reply-then-resolve a batch of PR review threads
only after the normal submit operation has published the committed fixes. It reads the batch from
the required `--batch` JSON file (an array of `{thread_id, comment?}` objects); `--dry-run`
validates without touching GitHub. Because a reply can succeed before resolution fails, retry only
the finalizer's reduced `retry_threads` batch when per-thread results are available; it omits
successful rows and strips replies already reported as posted. Models use `finalize_address`, not
this command directly.

### `perk pr review-context`

Fetch the active plan's PR review context (read-only; each angle-specialized pr-reviewer child runs
this). `--pr <n>` resolves an arbitrary PR by number instead, plan-ref-free (`plan_body` is null;
a nonexistent PR is a clean `pr_not_found` error).

### `perk pr review-post`

Submit a `/pr-review` verdict to the active plan's PR. Reads the review from the required
`--batch` JSON file (`{verdict, summary, comments?}`); an `actionable` verdict posts an advisory
COMMENT review, a `clean` verdict posts a single thumbs-up reaction. `--dry-run` validates without
touching GitHub. Invoked by the warm **`post_pr_review`** tool (the parent reconciles the reviewers'
findings and posts once) — the reviewer children no longer call it directly.

### `perk pr review-submit`

Submit **one atomic review** (inline comments + body + formal event) to PR *N* — the review
doors' submission substrate, **consumed by the warm `submit_pr_review` posting tool, not
human-CLI-first** (the structural human gate for formal events lives at the warm layer). `--pr <n>` and
`--batch <file>` are required; `--event` is `approve`, `request-changes`, or `comment`
(default `comment` — an omitted flag can never accidentally post a verdict). The batch is strict
JSON: `{body: str, comments?: [{path, line, side?, body}]}` — `side` defaults to `RIGHT` (`LEFT`
anchors a deleted line), `line` is non-nullable (unanchorable findings are folded into the review
body upstream, during triage curation), and a stray key (including `fyi`) is a `bad_batch`.

Before anything touches GitHub, every comment's `path`/`line`/`side` anchor is **validated against
the PR diff** (the merge-base 3-dot diff GitHub validates review anchors against): any failure
exits 1 with `error_type: bad_anchors` and per-comment `invalid[]` detail — nothing is submitted.
`--dry-run` runs the full validation and stops before the mutation (`mode: "validated"`) — unlike
`review-post`'s fully-offline dry-run it **requires `gh` + auth** (it fetches the PR diff); the
repair loop is: fix the anchors, re-run `--dry-run` until it exits 0.

A real run submits one atomic review through the gateway's event-aware ladder: a failed `comment`
review degrades to a discussion comment (`comment_fallback`); a failed formal event is retried
once with the comments folded into the review body and the **event preserved** (`review_folded`) —
never converted to a non-review comment, never a silent verdict drop. Approving or requesting
changes on your own PR is the clean `own_pr` error arm.

### `perk pr review`

The ephemeral review-checkout subgroup — the review doors' foreign-mode checkout substrate:
`checkout` creates a detached checkout of a PR's head (investigation material, so reviewers read
real surrounding code at head), `cleanup` removes it. Both verbs are detailed below.

### `perk pr review checkout`

Create an ephemeral, **detached** checkout of PR *N*'s head at `<worktree_root>/review-<n>` —
investigation material for the review doors' foreign mode (reviewers read real surrounding code
at head, not just the diff). `--pr <n>` is required. The `--json` envelope carries `path`
(absolute), `pr`, `url` (the PR's GitHub URL — feeds `/pr-review-browser`), `head_sha` (the
fetched PR head), `base_sha` (the local **merge-base** of `origin/<base_ref>` and the head — the
3-dot base GitHub's PR diff uses, *not* REST `base.sha`), and `base_ref` (the PR's base branch).

Semantics:

- **Refresh** — an existing `review-<n>` (registered worktree or leftover dir) is force-removed
  and re-created at the *current* head; a failed fetch leaves an existing checkout untouched.
- **GC backstop** — stale sibling `review-<n>` checkouts (older than 7 days, or broken residue
  missing their `.git` gitlink) are reaped before creating; failures warn and continue.
- **Untrusted-code posture** — the head is foreign code: the door **never runs
  `[worktree] setup` and never installs anything**. Any PR state (OPEN/MERGED/CLOSED) is
  checkout-able; a non-OPEN state only adds a stderr note.

Review checkouts live outside the `plan-<N>` namespace, so `perk worktree wipe` never touches
them; `perk worktree list` shows them and `perk worktree remove` is the manual fallback.

### `perk pr review cleanup`

Remove PR *N*'s review checkout (`--pr <n>` required). Single-PR and **idempotent**: nothing to
remove is success (`removed: false`, exit 0). Fully offline — no GitHub calls. A dirty checkout
is still removed (it is disposable by construction), and a leftover `refs/perk/review/<n>` temp
ref is deleted best-effort. The `--json` envelope carries `pr`, `path`, and `removed`.

### `perk pr url`

Resolve the active plan's PR number and URL — the read-only active-PR locator. Run from inside
the plan's worktree: it resolves the worktree's local `cache.plan-ref` to the plan branch and
locates that branch's PR; nothing on GitHub is mutated. The warm `/pr-review-browser` and
`/pr-review-terminal` doors consume it in their active modes. `--json` emits
`{success, error_type, message, pr: {number, url}}`. Refusals: no saved plan in the worktree is
`no_plan_ref` (run `/plan-save` then `perk implement` first); no PR for the plan branch is
`no_pr` (run `/submit` first); a GitHub read failure is `github_error`. Exit `0` ok · `1`
refusal/failure · `2` not-a-repo.
