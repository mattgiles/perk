---
title: "Remote and utility commands"
description: "Exact reference for perk worktree, state, registry, skills, workflow run supervision, and release-notes."
sidebar:
  order: 3016
---

# Remote and utility commands

This page holds the exact reference for the utility groups — `perk worktree`, `perk state`,
`perk registry`, `perk skills`, the `perk workflow` dispatched-run supervisor, and
`perk release-notes`. For the full command map and shared conventions, start at the
[CLI commands hub](../cli.md).

## Worktrees

### `perk worktree` (alias `wt`)

Create, list, remove, and check out git worktrees: `checkout` (`co`), `create` (`new`),
`list` (`ls`), `remove` (`rm`), `wipe`.

### `perk worktree checkout NAME` (alias `co`)

Print or activate the worktree `NAME`. A subprocess can never `cd` its parent shell, so bare
invocation prints the worktree's absolute path on **stdout** (nothing else) plus a copyable hint
on stderr — it composes as `cd "$(perk wt co NAME)"`. To actually switch directories in the
current shell, source the `--script` mode's emitted `cd` script:

```bash
source <(perk wt co plan-3 --script)
```

A failed `--script` resolution still sources cleanly but returns non-zero, so `&&` chains break
as expected. `NAME` `root` navigates back to the main checkout, and a bare plan number (`3` or
`#3`) resolves to the `plan-3` worktree (a literal name match always wins over the number sugar).

### `perk worktree create NAME` (alias `new`)

Create a worktree `NAME` under the configured worktree root. `--branch` sets the branch to create
(default: the worktree name). Runs the `[worktree] setup` hook marker-gated, exactly like the
stage launchers: a failed setup exits non-zero and leaves the worktree in place with the
pending-setup marker — re-running the same `worktree create NAME` retries the hook.

### `perk worktree list` (alias `ls`)

List the repo's worktrees.

### `perk worktree remove NAME` (alias `rm`)

Remove the worktree `NAME`. `--force` removes even with uncommitted changes. After removal it also
prunes the worktree's stale admin entry, so a worktree a prior interrupted removal left half-removed
is still cleared.

### `perk worktree wipe`

Remove all merged, safe-to-delete `plan-<N>` worktrees (and their branches). Each wiped worktree's
**remote** branch on `origin` is also deleted (best-effort — already-deleted remote branches, e.g.
from GitHub's auto-delete-head-branch-on-merge, are tolerated; an offline run just skips the remote
step). Worktree removal and branch cleanup are parallelized/batched for speed. Removal **self-heals**
slow/huge worktrees (a `rm -rf` over large gitignored trees that would otherwise time out) and broken
worktrees (a prior interrupted run left the `.git` gitlink missing) by falling back to a direct
directory removal, then prunes the stale admin entries those leave behind — so a wipe is effective
even on worktrees a half-removed prior run left in place. `--dry-run` previews removals; `--force`
bypasses the safety guards (removes even if dirty or pending-learn).

Wipe also sweeps two kinds of leftovers git no longer tracks:

- **Residue dirs** — unregistered `plan-*` directories under the worktree root (what a timed-out
  removal plus a later `git worktree prune` leaves behind). An unregistered dir with **no** `.git`
  entry is provably not a worktree and is removed regardless of PR state (the sweep is fully
  offline — no backend needed); an unregistered dir that still *has* a `.git` is skipped with a
  reason (use `git worktree` / `perk worktree remove` manually).
- **Stranded branches** — local `plan-*` branches not checked out in **any** worktree. A stranded
  branch is deleted (locally, and on `origin` via the same batched remote step) only when its
  plan's PR is provably **MERGED**; an unmerged or undeterminable one is kept, and an offline run
  skips them all. Reported as one aggregate line, not per branch.

## Run state

### `perk state` (alias `st`)

Inspect the local workflow cache and mint run ids (a dev/CI/doctor surface): `new-run` (`nr`),
`show` (`s`), `prune` (`gc`).

### `perk state new-run` (alias `nr`)

Mint a `run_id`, write its handoff blob, and print the id on stdout. `--handoff` supplies a
handoff JSON object (or `@file`) for the extension to claim.

### `perk state show` (alias `s`)

Show a run's handoff and scratch, or list known runs and markers. `--run-id` shows one run; omit
it to list all.

### `perk state prune` (alias `gc`)

Prune stale `.perk/workflow/` run dirs and handoff blobs (terminal-stage and age rules).
`--max-age-days` sets the age threshold (default 14); `--dry-run` previews removals; `--json`
emits a machine-readable payload.

## Registry

### `perk registry` (alias `reg`)

Inspect and validate the shared stage registry (`shared/registry.yaml`): `check` (`ch`), `show`
(`s`).

### `perk registry check` (alias `ch`)

Validate the bundled registry (shape, graph, state-key vocabulary); exits 0 when valid, 1 on any
error. `--json` emits a machine-readable result.

### `perk registry show` (alias `s`)

Print the stages and their transitions (a dev/doctor convenience).

## Skills

### `perk skills` (alias `sk`)

Ergonomic sugar over the upstream [`skills`](https://github.com/mattgiles/skills) CLI for managing
this repo's skills. **Every verb is a thin pass-through to the `skills` binary** (inheriting its
stdio and propagating its exit code) **except `remove`** (edits `.agents/manifest.yaml` directly)
**and the repo-authored-skill verbs `scaffold`/`create`/`refine`/`delete`** (which manage this repo's *own*
`.perk/skills/*/SKILL.md` skills and the perk-managed `.agents/manifest.d/perk-repo-skills.yaml`
fragment). The `skills` CLI must
be on `PATH` (and the repo initialized via `perk init`, which runs `skills init`); otherwise the
verbs surface a clean error.

For the task-oriented lifecycle of the repo-authored verbs (scaffold → author → commit-push-resync →
refine → delete), see [How to author a repo-specific skill](../../how-to/author-a-repo-skill.md).

- **`perk skills list` (alias `ls`)** — list skills discoverable across this repo's sources
  (→ `skills skill list`).
- **`perk skills status`** — show installed skill link status for this repo (→ `skills status`).
- **`perk skills add --source S --skill K [--source-url URL] [--ref R]`** — add a skill (and its
  source) and sync (→ `skills add S K [--url URL] [--ref R]`). `--source-url` is **optional** when
  the source alias is already declared; it is required for a brand-new source. `--ref` pins a git
  ref (defaults to the remote's default branch). `skills` owns the reuse/require-url/sync/rollback
  logic.
- **`perk skills remove` (alias `rm`) `--source S --skill K`** — remove a skill from
  `.agents/manifest.yaml` (dropping its source when no skills remain), then run `skills sync` to
  drop the now-undeclared link. **The single reimplementation** (no upstream removal command). It
  edits only the user's main manifest, **refuses perk-managed sources** (those declared in
  `.agents/manifest.d/perk.yaml` — re-run `perk init` after editing perk's source set instead), and
  restores the original bytes if `skills sync` fails. Note: the rewrite uses `yaml.safe_dump`, so
  the main manifest's comments/layout are not preserved.
- **`perk skills scaffold NAME`** — scaffold a repo-authored skill stub at `.perk/skills/NAME/SKILL.md`
  in the **main checkout** (resolved even when invoked from a linked worktree). Create-only —
  refuses if `.perk/skills/NAME/` already exists (no overwrite flag; edit the existing `SKILL.md`
  directly). Writes a TODO template — including a `stages: all` declaration with a narrowing TODO
  (a stage-id list, `all`, or `[]` for interactive-only) — then reconverges the
  `perk-repo-skills.yaml` fragment, skipping the heavy all-sources sync. `--json` emits a stable report. (The freshly-scaffolded skill is
  uncommitted, so the reconverge surfaces a non-fatal "not committed — commit it" warning; that is
  expected.)
- **`perk skills create NAME`** — a write-capable authoring cold door: pre-scaffolds
  `.perk/skills/NAME/SKILL.md` in the **main checkout** (the same write as `scaffold`, including
  the stub's `stages: all` declaration), then launches a
  session seeded to author the skill (following the `perk-skill-author` skill). Refuses if
  `.perk/skills/NAME/` already exists, pointing at `perk skills refine NAME`. The authoring scope
  (`.perk/skills/NAME/**` plus any directly-required docs/bindings) is a **soft scope** in the seed
  prompt, not a structural sandbox; committing is left to you. With **`--from <file|url>`** the
  authoring session is seeded from a source document (mirroring `objective author --from`): a **local
  file** (relative/absolute) is read as untrusted seed DATA and materialized into a gitignored
  scratch the session reads; an **http(s) URL** to a `SKILL.md` is handed to the session, which
  **fetches it (and any sibling `references/`/`scripts/` or linked files) in-session**, treats
  everything as DATA, and ports selectively. Either way it always creates a **fresh** skill (no
  in-place adoption) and the door stays **offline** (no network in the command — the agent does any
  fetching in-session). A non-URL, non-file `--from` fails `seed_file_error`. `--dry-run` prints the
  seed + intended path and scaffolds/launches nothing (the existence-refusal still runs). `--json`
  emits a stable report. Trailing args after `NAME` pass through to `pi`.
- **`perk skills refine NAME`** — a write-capable cold door that re-opens an **existing**
  repo-authored skill: it reads `.perk/skills/NAME/SKILL.md` in the **main checkout** and launches a
  session seeded to improve it in place (following the `perk-skill-author` skill). Refuses if the
  skill is absent, pointing at `perk skills create NAME`. Never scaffolds and skips sync (the file
  already exists); the door is read-only on the filesystem until the launched session edits. The
  refine scope (`.perk/skills/NAME/**` plus any directly-required docs/bindings) is a **soft scope**
  in the seed prompt, not a structural sandbox; committing is left to you. `--dry-run` prints the
  seed + intended path and launches nothing (the absent-skill refusal still runs). `--json` emits a
  stable report. Trailing args after `NAME` pass through to `pi`.
- **`perk skills delete NAME --yes`** — remove a repo-authored skill (`.perk/skills/NAME/`) in the
  **main checkout** and reconverge the fragment (skipping the heavy all-sources sync). Without
  `--yes` it prompts interactively when a TTY is present; under `--json`/non-interactive it refuses
  and prints the path that would be removed. Best-effort unlinks a dangling `.agents/skills/NAME`
  symlink. `--json` emits a stable report (with `symlink_removed`).
- **`perk skills sync`** — update all sources to newer commits and re-sync links
  (→ `skills update --sync`).

Repo-scoped only (no `--global`); for broader upstream flags use the `skills` CLI directly.

## Dispatched runs

### `perk workflow` (alias `wf`)

Supervisor surface over dispatched runs (a dev/CI/supervisor surface, not an agent affordance):
the `run` subgroup.

### `perk workflow run`

Observe and control dispatched runs: `list` (`ls`), `cancel`, `retry`.

### `perk workflow run list` (alias `ls`)

Enumerate runs, correlating `run_id ↔ plan ↔ PR`. **GitHub's own run enumeration is the existence
source** — the managed workflow's run-name embeds the stage, plan id, and perk `run_id`, so runs
dispatched from *any* machine appear here, even with an empty local cache. Local dispatch records
enrich the listing (plan URL, objective correlation, precise dispatch time) and keep
failed/never-triggered dispatches — plus runs older than the newest 100 — visible; each `--json`
row carries a `source` field (`"discovered"` / `"local"` / `"both"`) saying which side(s) knew the
run. `--no-refresh` skips **all** GitHub reads (the local-cache-only view); `--limit` caps the
display (default 50); `--json` emits a machine-readable report.

### `perk workflow run cancel RUN_ID`

Cancel an in-flight (queued/in_progress) dispatched run by its perk `run_id`. Works without a
local dispatch record — the run is recovered from GitHub's enumeration, so any machine can cancel
a run it did not dispatch.

### `perk workflow run retry RUN_ID`

Re-run a completed/failed dispatched run by its perk `run_id`. `--failed` re-runs only the failed
jobs. Like `cancel`, works without a local dispatch record (any machine).

## Release notes

### `perk release-notes`

Show perk's bundled release notes. By default it shows the notes for the perk version you are
running; `--all` shows every released version (newest first); `--version X.Y.Z` shows one
specific release (`--all` and `--version` are mutually exclusive). Notes are read from the
`CHANGELOG.md` bundled with the perk package, so the command works outside a git repo; the notes
print to stderr, and `[Unreleased]` entries are never shown. An unknown version or an unreadable
bundled changelog exits 1 with a clean `Error:` line — never a traceback.

After upgrading perk, the first **interactive** `perk` invocation prints a one-line stderr notice
pointing here (``perk updated to X.Y.Z; run `perk release-notes` for what's new.``) and records
the version in the user-level `~/.perk/last-seen-version` store. It follows the same suppression
rules as the version warning — never in `--json`/CI/non-TTY/worker paths, and
`PERK_SKIP_VERSION_CHECK` silences it — though unlike the warning it also fires outside a git
repo. Downgrades never re-trigger it (the store keeps the max version seen), and it is never
fatal: any store failure silently skips the notice.

## Related

- **Do:** [How to set up and verify the remote runner](../../how-to/set-up-the-remote-runner.md) — provision what the workflow commands supervise.
- **Do:** [How to recover a dirty worktree](../../how-to/recover-a-dirty-worktree.md) — the recovery moves behind `perk worktree`.
- **Understand:** [Headless and remote](../../explanation/headless-and-remote.mdx) — how remote runs coordinate through durable state.
