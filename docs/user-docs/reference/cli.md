# CLI commands

This page references the `perk` command-line interface — the session **exterior**: the commands
you run in your shell to scaffold a repo, manage worktrees, mint run ids, and launch primed `pi`
sessions for each stage of the plan workflow. It describes the surface; it does not teach a task
(those belong in [how-to/](../how-to/index.md)) or argue a design (those belong in
[explanation/](../explanation/index.md)). See the [user-docs router](../index.md) for how this
quadrant fits the whole.

Following the reference quadrant's rule, every entry is written against the command's real
`--help` output. Structural surface tests (`tests/test_cli_parity_smoke.py` and the
`tests/test_cli_help_sections.py` drift guard) catch real surface regressions; this prose is kept
current by hand against the canonical taxonomy (SSOT:
[`python-cli-guidelines.md` §11](../../guiding-principles/python-cli-guidelines.md)).

## Orientation

The `perk` surface is organized as **noun-groups** — `plan`, `objective`, `pr`, `learn`,
`worktree`, `state`, `registry`, `workflow` — each holding both **warm stage launchers** (a launch
opens a primed `pi` session for one workflow stage) and **cold deterministic workers** (`--json`
machine surfaces the warm in-session doors shell out to), separated by help sections. Three things
escape a group:

- **The one earned flat verb** `implement` (`impl`) — the heavy cold-only working stage, typed
  constantly, reads as a bare imperative.
- **The hot-path PR flat aliases** `submit` / `address` / `land` / `ready`, each aliasing its
  canonical `perk pr <verb>` (the canonical `pr` entry is authoritative; the flat alias is the
  ergonomic spelling).
- **Setup & Health**: `init` and `doctor` (which is itself a group).

**The launcher+worker merge.** Where a stage has *both* a real session-launcher half and a
deterministic worker half, they merge into **one** command: a session by default, the worker under
`--json` (the mode the warm door already shells). The genuinely merged commands are exactly
`pr submit`, `pr land`, and `plan save`. `pr address` is launcher-only; `pr ready` is worker-only;
each still gains its flat alias.

The in-session, warm `/…` commands and the model-facing tools you use *inside* a `pi` session are
a separate surface, documented in [In-session commands & tools](./in-session.md). This page covers
only the `perk` CLI you run from your shell.

Aliases are noted inline next to each command. Common flags: launcher commands accept `--worktree`
(position a worktree), `--dry-run` (print the resolved launch plan without exec'ing `pi`), and
`--remote` (dispatch the stage to a CI runner instead of running locally); worker commands accept
`--json` (emit a machine-readable report).

## Setup & Health

### `perk init`

Scaffold or converge the current repo for perk (idempotent; safe to re-run). Wires
`.pi/settings.json` and the borrowed package set, creates the `.pi/workflow/` cache, scaffolds
config, manages `.gitignore` and the `AGENTS.md` managed block, and verifies GitHub access
without mutating it. It also checks for the optional `ast-grep` CLI (structural code search) —
non-fatal: a missing `ast-grep` is a `⚠️` warning, never a blocking failure. `--force` re-seeds
the user-editable config to defaults; `--no-interactive`
never prompts (CI/supervisor); `--json` emits a machine-readable report.

### `perk doctor`

Diagnose the perk-managed repo, reporting a grouped health view. `--fix` re-converges drifted
managed pieces (and seeds missing config) without ever mutating GitHub or overwriting your config
edits. `--fix` also **reinstalls the perk extension's Node dependencies** in pi's git-clone of
perk (under `.pi/git/`) when they are missing or partial — running `npm install` there (respecting
your `.pi/settings.json` `npmCommand`) — and **reconciles perk's own git-package ref** in
`.pi/settings.json` to the version this perk wants (e.g. a stale pinned `@v0.0.1` → `@main`). The
`environment` group reports required tools as `fail` when missing and optional tools
(e.g. `ast-grep`) as `warn`. `--verbose` shows every check, not just failures; `--json` emits a machine-readable report.
This is a group whose bare invocation runs the health report.

### `perk doctor workflow`

Diagnose the remote-runner subsystem: static prerequisites plus an optional live CI smoke.

### `perk doctor workflow check`

Run the static remote-runner prerequisite checks (GitHub readiness, runner prereqs, the managed
workflow file). `--verbose` shows every check; `--json` emits a machine-readable report.

### `perk doctor workflow smoke-test`

Dispatch a throwaway CI run (a smoke short-circuit) to prove the runner is live. `--wait` polls
the dispatched run to completion; `--verbose` shows every prereq check; `--json` emits a
machine-readable report.

## Stage launchers (the earned flat names)

The flat top-level launchers: the one earned working verb `implement`, plus the hot-path PR
aliases. Each opens a primed `pi` session and accepts `--worktree`, `--dry-run`, and `--remote`;
passthrough `pi_args` are forwarded to `pi`.

### `perk implement [PLAN]` (alias `impl`)

Do the work on a branch; requires fresh context (cold-only). `PLAN` is an optional plan issue id
(`42`, `#42`, or `ENG-123`); omit it to implement the active saved plan in this repo. The worktree
branch is cut from the plan's pinned base (`origin/<base>`) when the plan declared one, else
`origin/<trunk>` (see
[Target a non-default base branch](../how-to/target-a-non-default-base-branch.md)). Adds `--base`
to override the start-point with a ref of your choosing (e.g. to stack on an unlanded branch); the
flag wins verbatim over the plan's pinned base but does not change the PR's merge target.

### `perk submit`

Flat alias for [`perk pr submit`](#perk-pr-submit) (the canonical entry). Push the branch and open
a draft PR (the implement → submit boundary); a session by default, the worker under `--json`.

### `perk address`

Flat alias for [`perk pr address`](#perk-pr-address) (the canonical entry). Classify PR review
feedback in an isolated child and resolve the threads (launcher-only); `--preview` classifies the
feedback and takes no action.

### `perk land`

Flat alias for [`perk pr land`](#perk-pr-land) (the canonical entry). Merge the ready/approved PR
and reconcile, setting the pending-learn marker (submit → land); a session by default, the worker
under `--json`.

### `perk ready`

Flat alias for [`perk pr ready`](#perk-pr-ready) (the canonical entry). Mark the active plan's
draft PR ready for review (the deliberate review gate) — a worker-only command (`--dry-run` /
`--json`).

## Command groups

### `perk plan`

Author and revise plans. Bare `perk plan` launches the read-only `plan` stage (a primed `pi`
session for exploration + plan authoring); the verbs below are the save boundary and the revision
launchers. Help renders the launchers and the merged save together as the group's commands.

### `perk plan save`

Persist the plan to GitHub — the read-only → read-write boundary. The **merged** launcher+worker:
bare `perk plan save` opens a primed `pi` session for the `save` stage; `--json` runs the
deterministic save worker instead (the mode the warm `/plan-save` door shells). As a launcher it
takes `--worktree`, `--dry-run`, and `--remote`. As the worker (`--json`) it keeps the full
plan-write flag set: `--plan-file` (the plan markdown to save), `--run-id`, `--title`,
`--objective-id`/`--node-id` (link to an objective and advance the node), `--consumed-learn` (the
perk:learn ids a docs plan consumes), and `--dry-run` (compose + print, no GitHub). The plan's
target branch is *derived* at save time (the linked objective's base → `[workflow] base` → the
GitHub default) and pinned — there is no `--base` flag here; see
[Target a non-default base branch](../how-to/target-a-non-default-base-branch.md).

### `perk plan resume PLAN`

Resume `PLAN` (a plan issue id) at its current lifecycle stage, relaunching it with fresh context.
`--dry-run` resolves and prints the stage without launching; `--remote` dispatches to CI; `--json`
emits a machine-readable report.

### `perk plan replan PLAN`

Re-author the open plan `PLAN` against the current codebase, in place (read-only). Local-only
(`cold_remote:false`); `--dry-run` materializes the prior plan and prints the seed without
launching; `--worktree` and `--json` are also accepted.

### `perk objective` (alias `obj`)

The objective group. Help renders **Launchers** (each opens a primed `pi` session: `author`,
`save`, `plan`) and **Workers** (the deterministic dev/CI/T10 storage + mechanics surface, not an
agent affordance: `create` (`new`), `show` (`s`), `node`, `reconcile` (`rec`), `next` (`n`), `run`
(`r`)). Bare `perk objective` shows this group help.

### `perk objective author`

Draft a new objective and roadmap in a read-only authoring session. Local-only
(`cold_remote:false`); adds `--json`.

### `perk objective save`

Persist the drafted objective to GitHub — the read-only → read-write objective boundary (the
`objective-save` stage). Local-only; adds `--json`.

### `perk objective plan [NUMBER]`

Select the next objective node and author a bounded plan (read-only). `NUMBER` is the objective
issue id (required — a cold session has no active objective); `--node` plans a specific node id
instead of the next actionable one. Local-only; adds `--json`.

### `perk objective create` (alias `new`)

Mint a `run_id` and create the perk:objective issue from authored markdown. Reads the required
`--body` file; `--title`, `--roadmap` (a JSON array of nodes, preferred over embedding YAML),
`--base` (the target branch this objective's node plans inherit — else `[workflow] base`, else the
GitHub default; see
[Target a non-default base branch](../how-to/target-a-non-default-base-branch.md)), `--run-id`,
`--dry-run`, and `--json` tune the create.

### `perk objective show NUMBER` (alias `s`)

Show an objective's header, roadmap, summary, and next actionable node.

### `perk objective node NUMBER`

Update one roadmap node (explicit-status-only). `--node` selects the node id (required); `--status`
sets its status (never inferred from `--pr`); `--pr` sets or clears the PR backlink;
`--description` updates the node description; `--dry-run` validates without writing.

### `perk objective node-add NUMBER`

Insert a **new** roadmap node into a phase (auto-assigned `<phase>.<n>`, appended after that phase's
last node). `--phase` (int, required) and `--description` (required) define the node; `--status`
sets its initial status (default `pending`); `--slug` overrides the auto-derived slug;
`--depends-on` (repeatable) adds a dependency edge; `--comment` attaches a note; `--dry-run`
validates without writing. Used **sparingly** during reconciliation, when a genuinely-new unit of
work emerged.

### `perk objective reconcile NUMBER` (alias `rec`)

Reconcile an objective's Reconcilable prose region against the merged diff — rewriting only the
marker-bounded region, never the roadmap table or Immutable notes. Reads the required `--body`
file; `--dry-run` composes without writing.

### `perk objective next NUMBER` (alias `n`)

Print the next plannable node (pending, or a resumable `planning` claim).

### `perk objective run NUMBER` (alias `r`)

Advance an objective's backlog one autonomously-safe step, then pause at the human gate.
`--remote` sets the runner ref for remote dispatches; `--wait` polls an in-flight run to
completion then re-evaluates; `--dry-run` resolves and reports the decision only.

### `perk objective doctor NUMBER` (alias `doc`)

Detect (and optionally repair) **drift** between a Linear-Project objective's persisted
`objective-manifest` and its live state (node-issues, blocking relations, milestones). Detect-only
by default; `--fix` applies the **safe, unambiguous** repairs (a missing manifest is backfilled, a
missing node-issue or phase milestone is recreated, a missing blocking relation is re-added) in a
deterministic order, stopping at the first failed write; `--dry-run` (with `--fix`) plans the
repairs without writing. Report-only conditions perk has no authority to auto-resolve (duplicate
ids, an unexpected extra relation, a renamed milestone, a relation cycle) are surfaced but never
touched. GitHub objectives have no divergence surface, so the report is always empty. `--json`
emits the full drift + fix report. See
[How to check an objective for drift](../how-to/check-an-objective-for-drift.md).

### `perk pr`

PR lifecycle group: the submit/land launchers, the address launcher, and the review workers.
`submit` and `land` open a primed `pi` session by default and run the deterministic worker under
`--json` (the merged commands); `address` is launcher-only; `ready` and the rest are cold-door
workers the warm TS doors delegate to, each running from inside the plan's worktree (reading the
local `cache.plan-ref`) and accepting `--json`.

### `perk pr submit`

Open a draft PR for the active plan's branch (the implement → submit boundary). The **merged**
launcher+worker: a primed `pi` session by default, the deterministic worker under `--json`.
`--dry-run` follows the mode (print the launch plan, or compose without pushing/hitting GitHub).
Flat alias: [`perk submit`](#perk-submit).

After opening the PR, the worker probes mergeability against the target branch (a local
`git merge-tree` probe) and adds three fields to the `--json` report: `base` (the target branch),
`mergeable` (`true` clean / `false` conflicts present / `null` undetermined — the probe is
fail-open and never changes the exit code), and `conflicts` (the conflicted paths). `--dry-run`
stays fully offline (`base: ""`, `mergeable: null`).

### `perk pr address`

Classify PR review feedback (in an isolated child) and resolve the threads — launcher-only (no
merged `--json` worker; its mechanics are `pr feedback` + `pr resolve-threads`). `--preview`
classifies the feedback only and takes no action (the warm `/address --preview` gesture; local-only,
inert on `--remote`). Flat alias: [`perk address`](#perk-address).

### `perk pr land`

Merge the active plan's PR and set the pending-learn semaphore (submit → land). The **merged**
launcher+worker: a primed `pi` session by default, the deterministic worker under `--json`.
`--dry-run` follows the mode (print the launch plan, or compose without touching GitHub). Flat
alias: [`perk land`](#perk-land).

### `perk pr ready`

Mark the active plan's draft PR ready for review (the deliberate review gate) — a **worker-only**
command (not a merged L+W: `ready` is not a registry stage and has no launcher). `--dry-run`
resolves the PR without marking it ready; `--json` emits a machine-readable report. Flat alias:
[`perk ready`](#perk-ready).

### `perk pr check`

Validate the active plan's PR checkout footer (the deterministic `pr check`).

### `perk pr feedback`

Fetch the active plan's PR review feedback (read-only; the classify child runs this).

### `perk pr resolve-threads`

Reply-then-resolve a batch of PR review threads (the parent's resolve step). Reads the batch from
the required `--batch` JSON file (an array of `{thread_id, comment?}` objects); `--dry-run`
validates without touching GitHub.

### `perk pr review-context`

Fetch the active plan's PR review context (read-only; the pr-reviewer child runs this).

### `perk pr review-post`

Submit a `/pr-review` verdict to the active plan's PR. Reads the review from the required
`--batch` JSON file (`{verdict, summary, comments?}`); an `actionable` verdict posts an advisory
COMMENT review, a `clean` verdict posts a single thumbs-up reaction. `--dry-run` validates without
touching GitHub.

### `perk learn`

Capture and consolidate learnings. Bare `perk learn` launches the `learn` stage (a primed `pi`
session); its `capture` and `docs` verbs are the cold workers the warm doors delegate to.

### `perk learn capture`

Create the perk:learn issue from captured learnings and clear pending-learn (land → learn). Reads
the markdown from the required `--body` file; `--dry-run` composes without creating an issue or
clearing.

### `perk learn docs`

Consolidate open perk:learn issues into a `docs/learned` plan (a read-only factory). `--gather`
materializes the inbox and emits `{inbox_path, learn_numbers}` without launching (the warm path);
`--worktree`, `--dry-run`, `--remote` (local-only), and `--json` are also accepted.

### `perk worktree` (alias `wt`)

Create, list, and remove git worktrees: `create` (`new`), `list` (`ls`), `remove` (`rm`), `wipe`.

### `perk worktree create NAME` (alias `new`)

Create a worktree `NAME` under the configured worktree root. `--branch` sets the branch to create
(default: the worktree name).

### `perk worktree list` (alias `ls`)

List the repo's worktrees.

### `perk worktree remove NAME` (alias `rm`)

Remove the worktree `NAME`. `--force` removes even with uncommitted changes.

### `perk worktree wipe`

Remove all merged, safe-to-delete `plan-<N>` worktrees (and their branches). Each wiped worktree's
**remote** branch on `origin` is also deleted (best-effort — already-deleted remote branches, e.g.
from GitHub's auto-delete-head-branch-on-merge, are tolerated; an offline run just skips the remote
step). Worktree removal and branch cleanup are parallelized/batched for speed. `--dry-run` previews
removals; `--force` bypasses the safety guards (removes even if dirty or pending-learn).

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

Prune stale `.pi/workflow/` run dirs and handoff blobs (terminal-stage and age rules).
`--max-age-days` sets the age threshold (default 14); `--dry-run` previews removals; `--json`
emits a machine-readable payload.

### `perk registry` (alias `reg`)

Inspect and validate the shared stage registry (`shared/registry.yaml`): `check` (`ch`), `show`
(`s`).

### `perk registry check` (alias `ch`)

Validate the bundled registry (shape, graph, state-key vocabulary); exits 0 when valid, 1 on any
error. `--json` emits a machine-readable result.

### `perk registry show` (alias `s`)

Print the stages and their transitions (a dev/doctor convenience).

### `perk workflow` (alias `wf`)

Supervisor surface over dispatched runs (a dev/CI/supervisor surface, not an agent affordance):
the `run` subgroup.

### `perk workflow run`

Observe and (Node 3.2) control dispatched runs: `list` (`ls`), `cancel`, `retry`.

### `perk workflow run list` (alias `ls`)

Enumerate dispatched runs, correlating `run_id ↔ plan ↔ PR` with a live GitHub overlay.
`--no-refresh` skips live GitHub reads (durable dispatch-record state only); `--limit` caps the
display (default 50); `--json` emits a machine-readable report.

### `perk workflow run cancel RUN_ID`

Cancel an in-flight (queued/in_progress) dispatched run by its perk `run_id`.

### `perk workflow run retry RUN_ID`

Re-run a completed/failed dispatched run by its perk `run_id`. `--failed` re-runs only the failed
jobs.
