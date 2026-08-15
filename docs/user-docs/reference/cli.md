---
title: "CLI commands"
description: "The command-map hub for the perk CLI — the stage-launcher spine, shared conventions, and the map to six exact-detail family references."
sidebar:
  order: 3010
---

# CLI commands

This page references the `perk` command-line interface — the session **exterior**: the commands
you run in your shell to scaffold a repo, manage worktrees, mint run ids, and launch primed `pi`
sessions for each stage of the plan workflow. It describes the surface; it does not teach a task
(those belong in [how-to/](../how-to/index.md)) or argue a design (those belong in
[explanation/](../explanation/index.md)). See the [user-docs router](../index.mdx) for how this
quadrant fits the whole.

Following the reference quadrant's rule, every entry is written against the command's real
`--help` output. Structural surface tests (`tests/test_cli_parity_smoke.py` and the
`tests/test_cli_help_sections.py` drift guard) catch real surface regressions, and the
bi-directional `tests/test_user_docs_cli_reference.py` guard keeps the documented inventory
complete against the live CLI: every documented command must exist, and every operator-facing
command must be documented on exactly one of these pages. The one deliberate exception is
`run-worker` — the internal CI worker entrypoint, allowlisted out of the inventory and the
command map below.

## Orientation

The `perk` surface is organized as **noun-groups** — `plan`, `objective`, `pr`, `learn`,
`worktree`, `state`, `registry`, `skills`, `workflow` — each holding both **warm stage launchers** (a launch
opens a primed `pi` session for one workflow stage) and **cold deterministic workers** (`--json`
machine surfaces the warm in-session doors shell out to), separated by help sections. Four things
escape a group:

- **The one earned flat verb** `implement` (`impl`) — the heavy cold-only working stage, typed
  constantly, reads as a bare imperative.
- **The hot-path PR flat aliases** `submit` / `address` / `land` / `ready`, each aliasing its
  canonical `perk pr <verb>` (the canonical `pr` entry is authoritative; the flat alias is the
  ergonomic spelling).
- **Setup & Health**: `init` and `doctor` (which is itself a group).
- **The informational `release-notes`** — prints the bundled changelog's release notes (see
  [Remote and utility commands](./cli/remote-and-utility.md#perk-release-notes)).

This hub keeps the [stage-launcher spine](#stage-launchers-the-earned-flat-names) and the
[command map](#command-groups); exact per-command detail lives on six family references:
[Setup and health](./cli/setup-and-health.md) (`init`, `doctor`),
[Plan commands](./cli/plan.md), [Objective commands](./cli/objective.md),
[PR commands](./cli/pr.md), [Learn and gist commands](./cli/learn-and-gist.md), and
[Remote and utility commands](./cli/remote-and-utility.md) (`worktree`, `state`, `registry`,
`skills`, `workflow`, `release-notes`).

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
`--remote` (dispatch the stage to a CI runner instead of running locally — only the remotely
runnable stages, `implement` and `address`, dispatch; every other launcher rejects `--remote` as
local-only); worker commands accept `--json` (emit a machine-readable report).

## Stage launchers (the earned flat names)

The flat top-level launchers: the one earned working verb `implement`, plus the hot-path PR
aliases. Each opens a primed `pi` session and accepts `--worktree`, `--dry-run`, and `--remote`
(dispatching only for the remotely runnable stages, `implement` and `address`).

**Plan selection (one seam, fixed precedence).** The plan-selecting launchers resolve their plan
from, in order: an explicit positional `PLAN` (canonical issue authority — one backend read; a
real launch also updates the **main-checkout** active-plan selector for later no-argument runs) ›
an explicit existing `--worktree`'s own binding › the invoking checkout's active saved plan
(inside a plan worktree, that worktree's own plan). `--worktree NAME` changes only the checkout
*directory* — never plan identity or the `plan-<id>` branch — and cannot combine with `--remote`
(use the positional `PLAN`; no-argument `--remote` keeps the active-plan read). An existing
checkout is **validated before reuse** (registered worktree, correct `plan-<id>` branch, binding
equal to the selection) and refused with a typed error (`worktree_unbound`,
`worktree_branch_mismatch`, `worktree_plan_mismatch`) rather than ever silently rebound or reset.
A **missing** checkout for the reuse launchers (`submit`/`address`/`land` — not `learn`) is
**restored** non-destructively from the existing `origin/plan-<id>` branch (see the setup-hook
note in [Workflow and CI](configuration/workflow-and-ci.md#worktree)).

**Pass-through grammar (`implement`/`address`).** Before the first bare `--`, perk accepts only
its own options plus at most one positional `PLAN`; everything after the `--` is delivered to
`pi` verbatim, in order — e.g. `perk address 1699 -- --model provider/model`. Unknown or extra
pre-separator tokens are rejected with usage guidance.

perk-launched sessions run the borrowed [pi-fff](https://github.com/dmtrKovalenko/fff.nvim)
search extension in **override mode** (`find`/`grep` become FFF-backed — pre-indexed,
frecency-ranked) via an injected `PI_FFF_MODE=override` env default; your environment wins, so
export `PI_FFF_MODE=tools-and-ui` (or any valid mode) to override.

### `perk implement [PLAN]` (alias `impl`)

Do the work on a branch; requires fresh context (cold-only). `PLAN` is an optional plan issue id
(`42`, `#42`, or `ENG-123`) — or the plan's **issue URL** (GitHub `.../issues/N`; Linear
`.../issue/IDENT` or `.../project/SLUG`), which is peeled to the id; omit it to implement the active
saved plan in this repo (selection precedence and the strict `--` pass-through grammar are above).
An explicit `PLAN` drives the launch directly and updates only the main-checkout selector —
invoked from inside a linked worktree it never rewrites that worktree's own binding. An existing
issue that carries **no plan-header** refuses before any launch (`issue_kind_mismatch` — positive
plan identification; a GitHub objective issue's refusal names the right door,
`perk objective plan <N>`). The worktree
branch is cut from the plan's pinned base (`origin/<base>`) when the plan declared one, else
`origin/<trunk>` (see
[Target a non-default base branch](../how-to/target-a-non-default-base-branch.md)). Adds `--base`
to override the start-point with a ref of your choosing (e.g. to stack on an unlanded branch); the
flag wins verbatim over the plan's pinned base but does not change the PR's merge target.

### `perk submit`

Flat alias for [`perk pr submit`](./cli/pr.md#perk-pr-submit) (the canonical entry). Push the branch and open
a draft PR (the implement → submit boundary); a session by default, the worker under `--json`.

### `perk address [PLAN]`

Flat alias for [`perk pr address`](./cli/pr.md#perk-pr-address-plan) (the canonical entry). Classify PR review
feedback in an isolated child and resolve the threads (launcher-only); `--preview` classifies the
feedback and takes no action. `PLAN` selects the plan canonically (`perk address 1699` is a
selector, never a first user message).

### `perk land`

Flat alias for [`perk pr land`](./cli/pr.md#perk-pr-land) (the canonical entry). Merge the ready/approved PR
and reconcile, setting the pending-learn marker (submit → land); a session by default, the worker
under `--json`. A learn-docs consolidation plan is exempt: no marker, no learn pass.

### `perk ready [PLAN]`

Flat alias for [`perk pr ready`](./cli/pr.md#perk-pr-ready-plan) (the canonical entry). Mark a plan's
draft PR ready for review (the deliberate review gate) — a worker-only command (`--dry-run` /
`--json`). `PLAN` selects the plan canonically and works from the repository root (no worktree
needed); omitted, the invoking checkout's active saved plan is used.

## Command groups

One row per operator-facing root command (every visible root command except the internal
`run-worker`): its purpose, and the page carrying its exact reference. The five stage launchers
above are the spine; every other command's detail lives on its family reference page.

<!-- BEGIN perk cli command map -->

| Command | Purpose | Reference |
| --- | --- | --- |
| `perk init` | Scaffold or converge the repo for perk (idempotent). | [Setup and health](./cli/setup-and-health.md#perk-init) |
| `perk doctor` | Diagnose the perk-managed repo; `--fix` repairs drift. | [Setup and health](./cli/setup-and-health.md#perk-doctor) |
| `perk implement` (alias `impl`) | Do the work on a branch — the earned flat working verb. | [this page](#perk-implement-plan-alias-impl) |
| `perk submit` | Push the branch and open a draft PR. | [this page](#perk-submit) |
| `perk address` | Classify PR review feedback and resolve the threads. | [this page](#perk-address-plan) |
| `perk land` | Merge the ready/approved PR and reconcile. | [this page](#perk-land) |
| `perk ready` | Mark a plan's draft PR ready for review. | [this page](#perk-ready-plan) |
| `perk plan` | Author and revise plans: save, resume, replan, from, watch. | [Plan commands](./cli/plan.md) |
| `perk objective` (alias `obj`) | Author and drive objectives, incl. the stacked delivery train. | [Objective commands](./cli/objective.md) |
| `perk pr` | The canonical PR lifecycle group behind the flat spine aliases. | [PR commands](./cli/pr.md) |
| `perk learn` | Capture and consolidate learnings via the learn factories. | [Learn and gist commands](./cli/learn-and-gist.md) |
| `perk gist` | Track rough statements of intent upstream of plans. | [Learn and gist commands](./cli/learn-and-gist.md#perk-gist) |
| `perk worktree` (alias `wt`) | Create, list, remove, and check out git worktrees. | [Remote and utility commands](./cli/remote-and-utility.md#worktrees) |
| `perk state` (alias `st`) | Inspect the local workflow cache and mint run ids. | [Remote and utility commands](./cli/remote-and-utility.md#run-state) |
| `perk registry` (alias `reg`) | Inspect and validate the shared stage registry. | [Remote and utility commands](./cli/remote-and-utility.md#registry) |
| `perk skills` (alias `sk`) | Manage this repo's skills (sugar over the upstream skills CLI). | [Remote and utility commands](./cli/remote-and-utility.md#skills) |
| `perk workflow` (alias `wf`) | Supervise dispatched CI runs. | [Remote and utility commands](./cli/remote-and-utility.md#dispatched-runs) |
| `perk release-notes` | Show perk's bundled release notes. | [Remote and utility commands](./cli/remote-and-utility.md#perk-release-notes) |

<!-- END perk cli command map -->

### Pre-launch fast-forward (read-only planning/authoring)

The read-only planning and authoring launchers — `perk plan` (bare), `perk plan replan`,
`perk plan from`, `perk objective plan`, `perk objective author` (incl. `--from`),
`perk objective replan`, `perk gist author`, and `perk learn docs` — run in your **main checkout**
(not a fresh `plan-<id>` worktree). To avoid planning against a stale tree, they **fast-forward
the main checkout before launch** by default: a best-effort `git fetch`, then
`git merge --ff-only` of your branch's upstream — but **only** when the checkout is clean, on a
branch, has an upstream, and can fast-forward. Any other condition (dirty tree, detached HEAD, no
upstream, diverged history, no remote, offline) **warns and skips** — it never aborts the launch,
never creates a merge commit, and never touches a dirty or detached tree. Pass `--no-sync` to any
of these commands to opt out. (`perk plan resume` and `perk objective run` keep the default and
have no `--no-sync` flag.)

## Related

- **Look up:** [In-session commands & tools](in-session.md) — the other command surface: what runs inside a session.
- **Do:** [How to drive a change through the full spine](../how-to/drive-the-full-spine.md) — the stage launchers in one worked sequence.
- **Understand:** [How perk thinks](../explanation/how-perk-thinks.md) — why the commands are shaped around stages.
