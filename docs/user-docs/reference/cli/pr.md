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
issue URL — or the plan's **PR**: its number or pasted `.../pull/N` URL, resolved to the plan it
records (you're usually looking at the PR when you decide to address it; the PR's `plan-<id>`
head names the candidate plan, and the plan's own recorded PR must corroborate it) — it selects
the plan canonically, drives the launch directly, and on
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

Ready a plan's PR — the **deterministic, non-launching worker** (not a merged L+W: `ready` is
not a registry stage). The flat spelling `perk ready` is a **different command** — the
continuation wrapper that runs these exact worker mechanics and then, on a successful stacked
stamp in an interactive terminal, launches the ready-time reconcile session (see
[`perk ready`](../cli.md) and the failure/retry story below). For an **incremental** plan this
marks the draft PR ready for
review (the deliberate review gate). For a **stacked** layer it is the deliberate
**post-review human handoff**: review happens on the draft layer PR, and after review +
address this gesture stamps the exact verified current head into the delivery journal — on
draft AND non-draft PRs alike (mark-ready mechanics first, then the journal append) — and the
recorded stamp **unblocks planning of the layer's direct dependents** (the handoff gate).
It is
never routine post-submit choreography: supervisors and factories name it, they never run it.
`PLAN` is an
optional plan issue id or pasted issue URL — or the plan's **PR**: its number or pasted
`.../pull/N` URL, resolved to the plan it records — it selects the plan canonically,
so `perk pr ready 1699` works from the repository root — ready needs no source files, no
worktree, and never writes the active-plan selector; omitted, the invoking checkout's own saved
plan is used (inside a plan worktree, that worktree's binding). An explicit `PLAN` naming an
existing issue with no plan-header refuses typed (`issue_kind_mismatch`). `--dry-run` is an
offline validation preview: it parse-checks an explicit `PLAN` and confirms a saved plan exists
on the no-argument form, but performs no backend or GitHub read — no PR is resolved or marked,
no stamp is appended (and nothing is kind-classified). Because the preview is offline it
refuses a PR-URL selector (`invalid_input` — a PR cannot be resolved to its plan without a
read; pass the plan issue id or drop `--dry-run`), and a **bare** PR number is
indistinguishable offline, so it previews as a plan id — the offline preview is **syntax
validation only, never validated identity** (a real run may resolve a different plan id via
the PR fallback). For a stacked plan, the worker
reconstructs the train and
fetches the projection-correlated PR: the target must be exactly published; marking a draft also
requires no unresolved operation and no structural train blocker (unrelated operational drift does
not block). An already-ready PR revalidates target identity/publication but skips those global
mutation vetoes — and still stamps (the append sits outside the one-unresolved-operation gate,
keeping the re-run paths convergent). A target the projection classifies as merged, closed,
wrong-base, or otherwise drifted refuses as `layer_not_published`; if the projection still says
published but the freshly fetched PR closed after reconstruction, that race refuses as
`pr_not_open`. Other typed failures include `unresolved_operation` and `structural_blockers` (plus
`no_pr` for a vanished correlated PR).

The stamp failure contract: a failed or ambiguous stamp append exits nonzero with
`error_type: ready_stamp_failed` while the envelope still reports the truthful `pr` and
`was_draft`. The message carries per-cause remediation — an ambiguous or transient append
converges on an idempotent re-run (the deterministic stamp key); a corrupt journal, a
stored-state mismatch, an oversize record, or a nonconforming id names its own repair (a
re-run alone will not converge). An unconstructable stamp (missing lineage, marker-unsafe id)
refuses **before** any mutation — the PR is never flipped when the handoff cannot be recorded.

`--json` emits the grown envelope: the original `success, error_type, message, pr, was_draft,
dry_run` plus the tail-additive continuation facts `stacked, objective, node, stamped_head,
stamp_advanced, reconcile_notice, reconcile_retry, plan, parent_checkpoint` (all null on the
offline dry-run; `stacked: false` with the rest null on an incremental plan; all populated on
stacked success — `reconcile_notice` reports that the ready-time reconcile pass was **not**
launched because this worker is deterministic and non-launching, naming `perk ready <plan>` in
an interactive terminal as the launcher; `reconcile_retry` carries the copyable re-run;
`plan` and `parent_checkpoint` are the continuation evidence — with `stamped_head` they pin
the accepted diff range `parent_checkpoint..stamped_head`).

**The `perk ready` wrapper on top of this worker**: identical options (`PLAN`, `--dry-run`,
`--json`), identical failure envelopes and exit codes, and byte-identical `--json` output. Its
one addition is the launching arm — an interactive (stdin AND stdout TTY), non-JSON,
non-dry-run run whose stacked stamp succeeded (an already-stamped re-run included) launches the
seeded ready-time reconcile session in the main checkout (borrowing the `objective-save` stage;
the session judges the pinned accepted range and may only rewrite Reconcilable prose, update
node descriptions, or add guarded `pending` tail nodes). A launch failure after a successful
stamp is a second reported outcome: loud stderr, exit 1 — the stamp stands, nothing is rolled
back, and re-running `perk ready <plan>` retries the pass.

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

Fetch PR review context (read-only). Automated active-plan reviewer tasks use
`--expected-pr <n>`: it preserves the active plan snapshot/body, resolves the plan branch's PR,
and compares that number before fetching context. Drift fails `review_target_changed`.
`--pr <n>` instead resolves an arbitrary PR plan-ref-free (`plan_body` is null; a nonexistent PR
is `pr_not_found`). The two flags are mutually exclusive; values must be positive integers.

`--pr <top> --stack` is the **stacked** reviewer-context arm (`--stack` requires `--pr` and
excludes `--expected-pr`): it re-resolves the whole stack from the given PR via the base-ref
chain walk (a perk train *is* a base-ref chain; the same single-PR/fork/depth refusals as the
stack checkout, so reviewer children and the doors refuse consistently), keeps the top-level
fields on the top PR, and adds per-member `stack[]` sections (`{pr, base_ref, head_ref, title,
body, diff, plan_body}` — `plan_body` enriched for `plan-<N>` head branches) plus
`combined_diff` (the base→top diff every stack reviewer works in, re-validated against the
same fail-closed ancestry gate as the checkout and fetched through a per-invocation temp-ref
namespace so concurrent reviewer lanes never collide).

### `perk pr review-post`

Submit a `/pr-review` verdict to the active plan's PR. Reads the review from the required
`--batch` JSON file (`{verdict, summary, comments?, fyi?, expected_pr?}`); an `actionable` verdict
posts an advisory COMMENT review, while a `clean` verdict posts one thumbs-up reaction. Optional
`expected_pr` is a strict positive integer used by recorded automated waves: on a real post it is
compared with the freshly resolved active PR before any GitHub mutation, with drift failing
`review_target_changed`. `--dry-run` validates the full batch including that field but stays
offline. Invoked by the warm **`post_pr_review`** tool (the parent reconciles the reviewers and
posts once); reviewer children never call it directly.

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

**The `--stack` arm** checks out a whole PR stack for combined-diff review: `--stack --pr <n>`
resolves the stack via the base-ref **chain walk** from any member PR; `--stack --objective
<id>` via the objective's **delivery train**; bare `--stack` uses the worktree plan-ref's
linked objective (`--pr`/`--objective` are mutually exclusive under `--stack`; `--objective`
without `--stack` refuses). One fetch pins every member head plus the stack base; the commit
topology is validated **fail-closed before any checkout** (every lower head must be an ancestor
of the head above it — a violation or indeterminate probe is `stack_topology_broken`); the
**top** head is checked out at `review-<top>` (so `cleanup --pr <top>` works unchanged) and
`base_sha` becomes the merge-base of `origin/<stack base>` and the top head. The envelope adds
the pinned snapshot: `stack[]` (`{pr, url, branch, head_sha, base_ref, node_id, plan_id}`,
bottom→top) and `stack_notes[]` (resolution warnings + recorded-vs-observed head drift —
warnings only); the top-level `base_ref` is the stack base. Typed refusals: `not_a_stack` (fewer than 2 open members — use the
single-PR flow), `stack_too_deep` (over 20 members), `fork_unsupported`, `ambiguous_stack`
(more than one open same-repo child), `stack_cycle` (the base-ref graph loops),
`not_stacked`/`stack_discontiguous`/`no_objective`
(objective arm), `stack_topology_broken`.

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

## Related

- **Do:** [How to address review feedback on a PR](../../how-to/address-review-feedback.md) — the address loop these commands launch.
- **Do:** [How to review a PR human-in-the-loop](../../how-to/review-a-foreign-pr.md) — run the review workers on any PR safely.
- **Look up:** [Review and authoring](../in-session/review-and-authoring.md) — the in-session review surfaces behind these launchers.
