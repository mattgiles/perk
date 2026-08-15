---
title: "Plan commands"
description: "Exact reference for the perk plan group — authoring, save, resume, replan, from, and watch."
sidebar:
  order: 3012
---

# Plan commands

This page holds the exact reference for the `perk plan` group — plan authoring, the save
boundary, and the revision launchers. For the full command map and shared conventions, start at
the [CLI commands hub](../cli.md).

### `perk plan`

Author and revise plans. Bare `perk plan` launches the read-only `plan` stage (a primed `pi`
session for exploration + plan authoring); the verbs below are the save boundary and the revision
launchers. Help renders the launchers and the merged save together as the group's commands. As a
read-only launcher, bare `perk plan` runs the hub's
[pre-launch fast-forward](../cli.md#pre-launch-fast-forward-read-only-planningauthoring) before
launch; `--no-sync` opts out.

### `perk plan save`

Persist the plan to GitHub — the read-only → read-write boundary. The **merged** launcher+worker:
bare `perk plan save` opens a primed `pi` session for the `save` stage; `--json` runs the
deterministic save worker instead (the mode the warm `/plan-save` door shells). As a launcher it
takes `--worktree`, `--dry-run`, and `--remote`; local-only (`cold_remote:false`). As the worker
(`--json`) it keeps the full
plan-write flag set: `--plan-file` (the plan markdown to save), `--run-id`, `--title`,
`--objective-id`/`--node-id` (link to an objective and advance the node), `--consumed-learn` (the
perk:learn ids a docs plan consumes), and `--dry-run` (compose + print, no GitHub). The plan's
target branch is *derived* at save time (the linked objective's base → `[workflow] base` → the
GitHub default) and pinned — there is no `--base` flag here; see
[Target a non-default base branch](../../how-to/target-a-non-default-base-branch.md).

When a plan issue is first created, perk prepends a **copyable command callout** to the top of the
issue body — a one-click-copy ` ```perk impl <id>``` ` block (where `<id>` is the plan's ref id:
the GitHub issue number, a Linear `ENG-N` identifier, or a Linear project UUID) — so opening the
plan surfaces the exact command to start implementing it. Anywhere perk accepts an id, you may paste
the issue/objective **URL** instead (GitHub `.../issues/N`; Linear `.../issue/IDENT` or
`.../project/SLUG`) — perk peels the id from it. It renders with a copy button on both
GitHub and Linear and is added only once (re-saving never duplicates it).

### `perk plan resume PLAN`

Resume `PLAN` (a plan issue id, or the plan's issue URL) at its current lifecycle stage, relaunching
it with fresh context. perk classifies the plan's canonical state into its **next action**:

| plan state | next action |
| --- | --- |
| no PR yet | launches `implement` |
| PR open, **draft** | the ready-for-review gate (yours: mark it ready, then `/land`) |
| PR open, actionable review feedback | launches `address` |
| PR open, clean | awaiting the human review/land gate |
| PR merged, learn pending | launches `learn` |
| PR merged and learned | done — nothing to resume |
| PR closed unmerged | needs human attention (reopen it or replan) |

Gate outcomes (draft / awaiting review / closed / done) are **reported, never launched** — resume
names the human gate instead of opening a session at the wrong stage. `--dry-run` resolves and
prints the outcome without launching; `--remote` dispatches to CI only when the resolved stage is
remotely runnable (`implement`/`address`) — gate and `learn` outcomes stay local; `--json` emits a
machine-readable report carrying the verdict in a `next_action` field. A merged plan's
learn-vs-done resolution reads the canonical plan-header `learn_state` field (so it works from any
machine or a fresh clone); the local pending-learn marker is only the fallback for legacy plans
that predate the field. An existing issue with no plan-header refuses before any classification
or launch (`issue_kind_mismatch` — positive plan identification; a GitHub objective issue's
refusal names `perk objective plan <N>`).

### `perk plan replan PLAN`

Re-author the open plan `PLAN` (a plan issue id or its issue URL) against the current codebase, in
place (read-only). Local-only
(`cold_remote:false`); `--dry-run` materializes the prior plan and prints the seed without
launching; `--worktree` and `--json` are also accepted. It runs the hub's
[pre-launch fast-forward](../cli.md#pre-launch-fast-forward-read-only-planningauthoring) before
launch (`--no-sync` opts out). The materialized prior plan also includes
the plan issue's human engagement (comments + description edits) as untrusted DATA when present
(Linear-first; honest on GitHub where the primitive exists), so the rewrite can incorporate human
feedback, not only landed PRs.

### `perk plan from ISSUE`

Adopt a pre-existing, human-authored issue `ISSUE` (a GitHub number, a Linear identifier like
`PER-45`, or the issue's URL) **in place** as a perk plan: perk reads the issue's title/body (and any human discussion)
as untrusted seed DATA, authors a plan over it in a read-only session, and on save stamps the plan
metadata **additively** into the *same* issue — the plan-header block (with `adopted_from`
provenance), the `perk:plan` label, the impl callout, and the plan-body comment — preserving the
human title/body verbatim and **never minting a second object**. Local-only (`cold_remote:false`);
`--dry-run` materializes the source issue and prints the seed without launching; `--worktree` and
`--json` are also accepted. It runs the hub's
[pre-launch fast-forward](../cli.md#pre-launch-fast-forward-read-only-planningauthoring) before
launch (`--no-sync` opts out). Refuses when the issue is not found, not open, already a perk plan
(use [`perk plan replan`](#perk-plan-replan-plan) for the latter), or a perk **objective**
(`issue_kind_mismatch` — objectives are not adoptable as plans; on GitHub the message names
`perk objective plan <N>`). See
[Adopt an existing issue as a plan](../../how-to/adopt-an-existing-issue.md).

`ISSUE` may also be a path to a **local file** (relative to your shell's cwd, or absolute). When the
argument resolves to an existing file, perk runs **seed-from-file** mode instead: it reads the
file's contents as untrusted seed DATA, primes the read-only authoring session with it, and on save
mints a **fresh** `perk:plan` issue (no in-place adoption — the file on disk is never modified, and
there is no `adopted_from` stamp). A non-existent path falls through to the issue-id path unchanged.

### `perk plan watch PLAN`

Live-watch plan `PLAN`'s implementation diff in [hunk](https://github.com/modem-dev/hunk)'s
watch mode while the plan is being implemented. perk positions the plan's `plan-<id>` worktree
through the shared validated positioner
(`PLAN` is backend-agnostic: a GitHub number, a Linear identifier like `SAV-456`, or the plan's
issue URL), computes the diff base, then chdirs into the worktree and **execs**
`hunk diff <sha12> --watch [HUNK_ARGS…]` — the terminal becomes a live, auto-reloading view of
everything the plan has changed (commits **and** uncommitted edits). A valid local worktree is
reused as-is; a **missing** one is restored from the existing `origin/plan-<id>` branch (then
the `[worktree] setup` hook runs, marker-gated); an existing checkout that fails validation
(unbound, wrong branch, bound to another plan) is a typed refusal — watch never rebinds or
resets a checkout.

The diff base resolves by a first-match ladder:

1. **Stacked layer parent** — for a stacked objective plan, the worktree's recorded layer parent
   (the sha the layer was cut from), when it resolves locally: you watch the layer's *own* delta,
   not its predecessors'. A stale record degrades to the next arm with a warning.
2. **Since-base merge-base** — the plan's pinned base branch (else the detected trunk), after a
   best-effort `git fetch`: `merge-base(HEAD, origin/<branch>)` — the plan's full growing
   changeset, matching `/pr-review-terminal`'s semantics.
3. **Working tree only** — when no base resolves, a bare `hunk diff --watch` (uncommitted changes
   only), with a loud warning.

**The watch feedback bridge.** A perk-launched watch loads a bundled hunk extension, and
**saving a human note in the diff sends it to the live implement session** — save is the send
boundary (no extra command or confirmation; deleting a saved note does not retract it). Hunk
shows *“Feedback queued for the implementation session”* when the note is durably queued;
delivery happens when an eligible implement session for that plan is (or next comes) live —
queued means “written to the worktree's local outbox”, delivered means “the note reached the
session transcript” (never that the agent agreed). Notes arrive as one real user message
carrying the note text plus its diff anchor; the agent is told to verify anchors against the
current code before acting. Degradations are loud, never silent: an incompatible hunk
extension-API generation or an unwritable outbox disables feedback with a visible warning while
the watched diff stays fully usable, and an oversized or empty note is refused (never truncated,
never falsely “queued”). See [How to send feedback from a hunk
watch](../../how-to/send-feedback-from-hunk-watch.md) and the in-session
[feedback receiver](../in-session.md#ancillary-in-session-features).

**Pass-through grammar.** perk owns exactly two tokens — `--dry-run` and `--help` — recognized
only before the first bare `--`. Every other token (unknown options like `--theme dark`, and
positionals) is appended to the hunk argv after `--watch` and perk's bundled `--extension`, in
order. The first bare `--` is consumed as the end-of-options marker, so: to hand hunk its own
pathspec separator, type it twice (`perk plan watch 42 -- -- src/ui`); to pass a perk-owned
token to hunk (e.g. a literal `--dry-run`), put it after the first `--`. A user-supplied
`--extension` composes with the bundled one (hunk's flag is repeatable — yours loads *with*
perk's, never instead). One token is refused outright wherever it appears: **`--no-extensions`**
(hunk's hard-off switch for on-disk extensions — it would silently disable the feedback bridge;
for an extension-free watch, run `hunk diff <base> --watch --no-extensions` in the worktree
yourself).

`--dry-run` resolves and prints the worktree + the composed hunk command (including the absolute
bundled `--extension` path) without launching, minting, creating, or **fetching** anything
(exit 0): for an existing worktree the command composes from local refs only (degrading to the
working-tree-only fallback with a note when the base is unresolvable offline); for a missing
worktree it reports the planned restore + setup and an explicit "command unavailable until
restoration" status. A real
run **hands the process off to hunk** — perk becomes hunk, and the terminal ultimately receives
hunk's exit status. Pre-launch refusals exit 1 (2 outside a git repo).

Offline-capable for a valid local worktree (no issue-backend read; the fetch is best-effort —
offline falls back to
the last-known `origin/*` ref with a warning — canonical/backend reads happen only on a real run
that must restore a missing checkout), and correct from **anywhere in the repo**,
including from inside a linked worktree (the worktree root is resolved against the main
checkout). Failure arms: a missing `plan-<id>` worktree with no restorable remote branch is a
typed `worktree_restore_failed` error (run `perk implement <id>` first if the plan was never
pushed); a
missing `hunk` binary names the install hint (`npm i -g hunkdiff`); a missing bundled feedback
extension means a broken perk installation (reinstall perk — `perk doctor` reports it as the
`watch-feedback` check).
