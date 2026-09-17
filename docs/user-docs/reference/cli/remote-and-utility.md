---
title: "Remote and utility commands"
description: "Exact reference for perk worktree, state, registry, skills, workflow run supervision, perk resume (the Pi session picker), and release-notes."
sidebar:
  order: 3016
---

# Remote and utility commands

This page holds the exact reference for the utility groups — `perk worktree`, `perk state`,
`perk registry`, `perk skills`, the `perk workflow` dispatched-run supervisor, `perk resume`
(Pi's session picker for a checkout), and `perk release-notes`. For the full command map and
shared conventions, start at the [CLI commands hub](../cli.md).

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
- **`perk skills scaffold NAME`** — scaffold a repo-authored skill stub at `.perk/skills/<NAME>/SKILL.md`
  in the **main checkout** (resolved even when invoked from a linked worktree). Create-only —
  refuses if `.perk/skills/<NAME>/` already exists (no overwrite flag; edit the existing `SKILL.md`
  directly). Writes a TODO template — including a `stages: all` declaration with a narrowing TODO
  (a stage-id list, `all`, or `[]` for interactive-only) — then reconverges the
  `perk-repo-skills.yaml` fragment, skipping the heavy all-sources sync. `--json` emits a stable report. (The freshly-scaffolded skill is
  uncommitted, so the reconverge surfaces a non-fatal "not committed — commit it" warning; that is
  expected.)
- **`perk skills create NAME`** — a write-capable authoring cold door: pre-scaffolds
  `.perk/skills/<NAME>/SKILL.md` in the **main checkout** (the same write as `scaffold`, including
  the stub's `stages: all` declaration), then launches a
  session seeded to author the skill (following the `perk-skill-author` skill). Refuses if
  `.perk/skills/<NAME>/` already exists, pointing at `perk skills refine NAME`. The authoring scope
  (`.perk/skills/<NAME>/**` plus any directly-required docs/bindings) is a **soft scope** in the seed
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
  repo-authored skill: it reads `.perk/skills/<NAME>/SKILL.md` in the **main checkout** and launches a
  session seeded to improve it in place (following the `perk-skill-author` skill). Refuses if the
  skill is absent, pointing at `perk skills create NAME`. Never scaffolds and skips sync (the file
  already exists); the door is read-only on the filesystem until the launched session edits. The
  refine scope (`.perk/skills/<NAME>/**` plus any directly-required docs/bindings) is a **soft scope**
  in the seed prompt, not a structural sandbox; committing is left to you. `--dry-run` prints the
  seed + intended path and launches nothing (the absent-skill refusal still runs). `--json` emits a
  stable report. Trailing args after `NAME` pass through to `pi`.
- **`perk skills delete NAME --yes`** — remove a repo-authored skill (`.perk/skills/<NAME>/`) in the
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

## Session resumption

### `perk resume [TARGET]`

Browse and reopen Pi conversations for a checkout — perk positions itself in the chosen
checkout, composes the launch environment, and execs Pi's own session picker (`pi --resume`) —
or reopen one run's recorded conversation directly by its run id (`pi --session <file>`).
The picker is Pi's: its Current Folder / All scopes, search, empty lists, and cancellation are
Pi's own, and project trust for the reopened session follows **Pi's own trust flow** (perk
passes no `--approve`; a reopened `plan-<id>` worktree prompts for trust once).

```bash
perk resume                          # this checkout (a plan worktree resolves to itself)
perk resume --worktree plan-42       # an existing checkout under the worktree root
perk resume --worktree root          # the main checkout
perk resume 42                       # plan #42's bound worktree (plan-42)
perk resume 42 --worktree plan-42-b  # a named checkout that must be bound to plan #42
perk resume 42 --dry-run             # resolve + print the target, launch nothing
perk resume 01ARZ3NDEKTSV4RRFFQ69G5FAV  # reopen that run's recorded conversation
```

**Where the picker opens.** Precedence is an explicit `TARGET`, then `--worktree`, then the
checkout you ran the command from — the bare form never reads the main checkout's plan
selector. `--worktree NAME` names a directory under the configured `[worktree] root` (resolved
against the main checkout); `root` is a reserved word for the main checkout. `TARGET` is any plan
selector — an issue id (`42`, `#42`, `ENG-123`), a pasted issue URL, or the plan's PR number/URL —
and resolves to the plan's `plan-<id>` worktree (or, with `--worktree NAME`, a checkout that must
be bound to that plan). `TARGET --worktree root` is refused: the main checkout is never a plan's
implementation worktree.

**Reopening a run by id.** `TARGET` may also be a perk **run id** — a 26-character ULID,
optionally with `.<n>` fork suffixes (`01ARZ3NDEKTSV4RRFFQ69G5FAV`, `…FAV.1`). Run ids come from
the plan header's `run_id` (the planning run) and `impl_run_ids` (its implementation runs), or
from `perk state show`. Every perk session records the conversation it starts against its run id,
so `perk resume RUN_ID` skips the picker and reopens that run's **newest** recorded conversation
directly (`pi --session <file>`) in the checkout it was recorded in; when a run has several (a
`perk plan replan` reuses the run id), the others are listed on one stderr line. `--worktree` is
refused with a run id (the record already pins the checkout). This form reads no plan backend and
runs no `gh` — only the local run record — but composes the launch environment exactly like every
other arm (the same agent-directory precedence below). As everywhere, perk passes no `--approve`:
Pi's own trust flow governs the reopened checkout.

**What the picker shows.** perk names the sessions it launches
`<stage> | plan #N | objective #O / <node> | <title>` (segments omitted when unknown — e.g.
`implement | plan #42 | Add retry`), so the picker lists what each conversation *is* rather than
its first message. The name is refreshed when a session starts, when a working draft is written
(the draft's title), and when a plan or objective is saved (its `plan #N` / `objective #O`
segment, once the save has linked the session — a failed linkage leaves the segment for the next
successful link, e.g. a re-save); a different name you set with `/name` or `pi --name` is never
overwritten. Sessions perk did not launch (a hand-run `pi`, subagent children) stay unnamed. An
older perk-launched session that has no name yet gains one the next time you open it — provided
its record carries the stage it was launched for (sessions from before perk recorded the launch
stage stay unnamed).

**Never creates, restores, or rebinds.** A missing checkout is a typed `worktree_not_found`
naming the `perk implement` gesture that creates or restores it; an existing one must pass the
same fail-closed validation the stage launchers apply — `worktree_unregistered` (not a live
registered git worktree), and for the plan forms `worktree_unbound` / `worktree_branch_mismatch`
/ `worktree_plan_mismatch`. A bare `--worktree NAME` needs no plan binding. Other refusals:
`invalid_input` (a bad name, `TARGET --worktree root`, or `RUN_ID --worktree NAME`),
`pi_cli_missing`, `launch_failed`, and the plan selection's own errors (`plan_not_found`,
`issue_kind_mismatch`). The run-id form adds three: `run_not_found` (the run predates session
recording, its run state was pruned by `perk state prune`, or its record is unreadable — browse
the picker instead), `session_missing` (the recorded session file is gone — or Pi has not written
it yet: a new session's file appears only after its first assistant reply), and `checkout_missing`
(the recorded checkout no longer exists — `perk implement <PLAN>` recreates a plan worktree; it is
never restored here).

**What perk does not do.** No run id is minted, no handoff or plan selector is written, no
stage prompt or `[models.stages]` flags are added, nothing is materialized, no setup hook runs —
the reopened session keeps its own recorded identity (an inherited `PERK_RUN_ID` is dropped, so
a session that already carries one keeps it). The agent directory follows the launch precedence:
`PI_CODING_AGENT_DIR` → the main checkout's `[pi] agent_dir` → Pi's default, with the same
missing-directory warning and `pi_agent_dir_invalid` refusal as a stage launch. The launch
environment is otherwise the one a stage launch gets — including a `LINEAR_API_KEY` seeded from the
main checkout's gitignored `.perk/local.toml` when your shell does not export one. That key is
process environment, not per-project: a session you open from the picker's **All** scope in
another project inherits it, and a project you trusted earlier loads its extensions without a
new prompt — the same exposure as an exported key in a hand-run `pi`. Keep the key out of
`local.toml` (export it only when needed) if that matters to you.

**Terminal only.** Every form hands your terminal to an interactive Pi session — the picker is
a full-screen TUI that Pi constructs even on a pipe, and a run id's reopened conversation is Pi's
TUI too — so `perk resume` without `--dry-run` refuses `not_a_tty` unless both stdin and stdout
are terminals — decided right after the not-a-repo check and before any record, config, or
backend read. There is no
`--json` and no launch banner. Exit codes: `0` dry-run · `1` typed refusals · `2` not a repo · a
successful launch never returns (the terminal receives Pi's own exit status).

**`--dry-run`** prints the resolved `checkout` (plus the recorded `session` file on the run-id
form), the `agent dir` and its source (`env` / `config` / `default`), and the exact `command` to
stderr, then one JSON payload to stdout: `{"success": true, "checkout", "session_file",
"agent_dir", "agent_dir_source", "argv", "dry_run": true}` — `session_file` is `null` for the
picker forms.

`perk plan resume PLAN` at a review gate opens this same picker for the plan worktree — see
[Plan commands](./plan.md#perk-plan-resume-plan).

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
