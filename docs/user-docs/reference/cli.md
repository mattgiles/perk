# CLI commands

This page references the `perk` command-line interface — the session **exterior**: the commands
you run in your shell to scaffold a repo, manage worktrees, mint run ids, and launch primed `pi`
sessions for each stage of the plan workflow. It describes the surface; it does not teach a task
(those belong in [how-to/](../how-to/index.md)) or argue a design (those belong in
[explanation/](../explanation/index.md)). See the [user-docs router](../index.md) for how this
quadrant fits the whole.

Following the reference quadrant's rule, every entry is written against the command's real
`--help` output and guarded by a pytest existence check, so a documented-but-missing command (or
an undocumented new one) fails CI.

## Orientation

The sections below mirror `perk --help`: **Setup & Health**, **Stage launchers**, **Other**, and
**Command groups**. Each stage launcher opens a primed `pi` session for one stage of the workflow
— the read-only authoring stages (`plan`, `objective-author`, `objective-plan`) and the
read-write boundaries (`save`, `objective-save`) and the working stages (`implement`, `submit`,
`address`, `land`, `learn`).

The in-session, warm `/…` commands and the model-facing tools you use *inside* a `pi` session are
a separate surface, documented in a later reference page (coming with Objective
[#453](https://github.com/mattgiles/perk/issues/453) Node 2.2). This page covers only the `perk`
CLI you run from your shell.

Aliases are noted inline next to each command. Common flags: launcher commands accept `--worktree`
(position a worktree), `--dry-run` (print the resolved launch plan without exec'ing `pi`), and
`--remote` (dispatch the stage to a CI runner instead of running locally); worker commands accept
`--json` (emit a machine-readable report).

## Setup & Health

### `perk init`

Scaffold or converge the current repo for perk (idempotent; safe to re-run). Wires
`.pi/settings.json` and the borrowed package set, creates the `.pi/workflow/` cache, scaffolds
config, manages `.gitignore` and the `AGENTS.md` managed block, and verifies GitHub access
without mutating it. `--force` re-seeds the user-editable config to defaults; `--no-interactive`
never prompts (CI/supervisor); `--json` emits a machine-readable report.

### `perk doctor`

Diagnose the perk-managed repo, reporting a grouped health view. `--fix` re-converges drifted
managed pieces (and seeds missing config) without ever mutating GitHub or overwriting your config
edits; `--verbose` shows every check, not just failures; `--json` emits a machine-readable report.
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

## Stage launchers

Each command here opens a primed `pi` session for one workflow stage. All accept `--worktree`,
`--dry-run`, and `--remote`; passthrough `pi_args` are forwarded to `pi`.

### `perk plan`

Explore the codebase and draft a plan in a read-only session (the `plan` stage).

### `perk save`

Persist the drafted plan to GitHub — the read-only → read-write boundary (the `save` stage).

### `perk submit`

Push the branch and open a draft PR (the `submit` stage).

### `perk address`

Classify PR review feedback (in an isolated child) and resolve the threads (the `address` stage).

### `perk land`

Merge the ready/approved PR and reconcile, setting the pending-learn marker (the `land` stage).

### `perk objective-save`

Persist the drafted objective to GitHub — the read-only → read-write objective boundary (the
`objective-save` stage).

### `perk implement [PLAN]` (alias `impl`)

Do the work on a branch; requires fresh context (cold-only). `PLAN` is an optional plan issue id
(`42`, `#42`, or `ENG-123`); omit it to implement the active saved plan in this repo. Adds
`--base` to branch off a ref other than `origin/<trunk>` (e.g. to stack on an unlanded branch).

### `perk objective-author` (alias `oauthor`)

Draft a new objective and roadmap in a read-only authoring session. Local-only
(`cold_remote:false`); adds `--json`.

### `perk objective-plan [NUMBER]` (alias `oplan`)

Select the next objective node and author a bounded plan (read-only). `NUMBER` is the objective
issue id (required — a cold session has no active objective); `--node` plans a specific node id
instead of the next actionable one. Local-only; adds `--json`.

### `perk learn`

Capture and consolidate learnings. The bare invocation launches the `learn` stage (a primed `pi`
session); its `capture` and `docs` verbs (below, under Command groups) are the cold workers the
warm doors delegate to.

## Other

### `perk resume PLAN` (alias `res`)

Resume `PLAN` (a plan issue id) at its current lifecycle stage, relaunching it with fresh context.
`--dry-run` resolves and prints the stage without launching; `--remote` dispatches to CI; `--json`
emits a machine-readable report.

### `perk replan PLAN` (alias `rp`)

Re-author the open plan `PLAN` against the current codebase, in place (read-only). Local-only;
`--dry-run` materializes the prior plan and prints the seed without launching; `--worktree` and
`--json` are also accepted.

### `perk plan-save` (alias `psave`)

Save a plan to GitHub as an issue (the queryable header plus the full body comment) — the save
worker the warm `/plan-save` door delegates to. Reads the plan from `--plan-file`; `--title`,
`--objective-id`/`--node-id` (link to an objective and advance the node), `--consumed-learn` (the
perk:learn ids a docs plan consumes), `--run-id`, `--dry-run`, and `--json` tune the save.

## Command groups

### `perk pr`

PR lifecycle workers (the cold doors) the warm PR commands delegate to: `submit`, `check`,
`ready`, `land`, `feedback`, `resolve-threads`, `review-context`, `review-post`. Each runs from
inside the plan's worktree (reading the local `cache.plan-ref`) and accepts `--json`.

### `perk pr submit`

Open a draft PR for the active plan's branch (the implement → submit boundary). `--dry-run`
composes the plan without pushing or hitting GitHub.

### `perk pr check`

Validate the active plan's PR checkout footer (the deterministic `pr check`).

### `perk pr ready`

Mark the active plan's draft PR ready for review (the deliberate review gate). `--dry-run`
resolves the PR without marking it ready.

### `perk pr land`

Merge the active plan's PR and set the pending-learn semaphore (submit → land). `--dry-run`
composes the plan without touching GitHub.

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

### `perk learn` (group)

The `learn` group hosts the cold learn workers; its bare invocation launches the `learn` stage
(see Stage launchers above).

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

Remove all merged, safe-to-delete `plan-<N>` worktrees (and their branches). `--dry-run` previews
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

### `perk objective` (alias `obj`)

Deterministic objective storage and mechanics (a dev/CI/T10 surface, not an agent affordance):
`create` (`new`), `show` (`s`), `node`, `reconcile` (`rec`), `next` (`n`), `run` (`r`).

### `perk objective create` (alias `new`)

Mint a `run_id` and create the perk:objective issue from authored markdown. Reads the required
`--body` file; `--title`, `--roadmap` (a JSON array of nodes, preferred over embedding YAML),
`--run-id`, `--dry-run`, and `--json` tune the create.

### `perk objective show NUMBER` (alias `s`)

Show an objective's header, roadmap, summary, and next actionable node.

### `perk objective node NUMBER`

Update one roadmap node (explicit-status-only). `--node` selects the node id (required); `--status`
sets its status (never inferred from `--pr`); `--pr` sets or clears the PR backlink;
`--description` updates the node description; `--dry-run` validates without writing.

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
