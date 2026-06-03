# perk

A Pi-native, plan-oriented engineering workflow — a Python `perk` CLI (the session
*exterior*) plus a TypeScript Pi extension (the session *interior*), sequenced so that
**perk bootstraps itself**.

> Status: **Phase 2 complete.** The in-session workflow **spine** (`plan → save → implement
> → submit → land → learn`) is closed *and deepened* — perk-owned plan mode + structural
> tool-gating, a post-edit formatter, in-process + spawned context-isolation, a read-only CI
> executor, the `/address` review loop, deepened submit/land/learn, and objectives as plan
> factories + reconciliation — all **dogfooded on perk's own repo** (see
> [docs/planning/phase-2-gate.md](docs/planning/phase-2-gate.md)); any plan is resumable at
> its current stage via `perk resume`. Phase 3 adds the headless worker + queue. See
> [docs/index.md](docs/index.md) for the full plan and [docs/ROADMAP.md](docs/ROADMAP.md) for
> the phasing.

## What perk is

perk ports the plan-oriented engineering workflow (explore read-only → save a plan →
implement on a branch → submit → land → learn) to [Pi](https://github.com/earendil-works),
split across **two planes**:

- the **exterior** — a Python `perk` CLI that scaffolds repos, positions worktrees, mints
  run ids, and launches primed `pi` sessions (everything that happens *outside* a session);
- the **interior** — a TypeScript Pi extension that drives stage transitions and state
  *inside* a running session.

A language-neutral [`shared/`](shared/) contract (the stage registry + cross-plane specs)
is the single source both planes read, so the two stay in lockstep without a codegen step.

perk is built to **bootstrap its own development**: each phase leaves perk capable of
driving the next, and perk's own repo is the first thing it scaffolds.

## Quickstart

perk targets any git repo. From the repo you want to wire:

```bash
uv tool install perk        # (or run from source — see Develop)
perk init                   # scaffold/converge Pi wiring (idempotent; safe to re-run)
perk doctor                 # report health; perk doctor --fix repairs drift
```

`perk init` requires a git repo + `git`, `gh`, `node ≥ 22`, and `pi` on PATH. GitHub auth
is verified but never required (it is reported, never fatal).

## The command surface (as built)

| Command | What it does |
| --- | --- |
| `perk init` | Scaffold/converge a repo for perk: `.pi/settings.json` packages, the `.pi/workflow/` cache layout, `.gitignore` + `AGENTS.md` managed blocks, and `.pi/perk.toml` config. Idempotent. `--json`/`--force`. |
| `perk doctor` | Diagnose the managed setup (six grouped checks); `--fix` repairs known drift; `--json` + stable exit codes for supervisors; `-v` expands the condensed view. |
| `perk plan \| submit \| address \| land \| learn` | Stage **launchers**: mint a `run_id` and `exec` a primed `pi` session for that stage (the in-session *handlers* live in the extension). `--dry-run` resolves a launch without side effects. |
| `perk implement [PLAN]` | Materialize the plan's worktree/branch and launch a fresh `pi` **primed to implement it**. Optional issue number selects a specific plan; omit it to use the active saved plan. |
| `perk objective-plan` | The **plan factory**: select the next actionable objective node (dependency-graph `next`), optionally explore it read-only, and emit a bounded plan through the `plan → save` spine. The new initial node of the deepened graph. |
| `perk objective create/show/node/next/reconcile` | Manage **objectives** (multi-plan roadmaps as GitHub issues): create an objective + its roadmap nodes, show it, advance a node's status, pick the next actionable node, and reconcile its prose against a merged diff. |
| `perk plan-save` / `pr-submit` / `pr-check` / `pr-ready` / `pr-land` | The cold/worker GitHub doors (the in-session twins are the `plan_save` / `submit` / `land` tools): create the plan issue, open + run CI on + flip-ready + squash-merge the draft PR. `--json` + `--dry-run`. |
| `perk pr-feedback` / `pr-resolve-threads` / `learn-capture` | The `/address` review-loop workers (classify PR feedback, reply-then-resolve threads) and the `/learn` capture worker. |
| `perk resume <plan>` | Resolve any plan to its current actionable stage (no PR → implement, open → submit, merged+pending-learn → learn) and launch it. |
| `perk worktree create/list/remove` | Manage git worktrees under the configured root. |
| `perk state` / `perk registry` | Inspect the local `.pi/workflow/` cache + run ids; inspect/validate the shared stage registry. |

The in-session **warm doors** (the perk extension): `/plan`, `/plan-save`, `/implement`, `/submit`,
`/ready`, `/address`, `/land`, `/learn`, `/checkpoints`, `/objective-plan`, `/objective-reconcile`
(+ the `plan_save`/`submit`/`land`/`learn`/`resolve_review_threads`/`objective_node`/`reconcile_objective`
tools), and cross-stage lifecycle gates.

## Where this is going

Phases 0–2 ship the **scaffolding**, the **thin loop**, and its **deepening** on the
**borrow-then-own** substrate. Phase 2 internalized the borrowed pieces: perk now owns plan mode
(retiring `@tombell/pi-plan`, P2.T2a) **and** implement-progress checkpoints (retiring
`@juicesharp/rpiv-todo`, P2.T12). The surviving borrows are `@tombell/pi-diff`, the
`@tombell/pi-status` statusline, and the `pi-subagents` **engine** (behind perk's thin seam — perk
owns the agent definitions). **Phase 3** adds the headless worker + queue (autonomy). The phasing,
dogfood gates, and locked decisions live in [docs/ROADMAP.md](docs/ROADMAP.md); per-turn plans (and
the [Phase-1](docs/planning/phase-1-gate.md) / [Phase-2](docs/planning/phase-2-gate.md) gate
records) live in [docs/planning/](docs/planning/).

## Layout

- `perk/` — the Python CLI (the session exterior).
- `extension/` — the TypeScript Pi extension (the session interior).
- `shared/` — cross-plane contracts (the stage registry + specs), bundled into both build
  artifacts.
- `docs/` — research, roadmap, and per-turn plans.

## Develop

Two pinned toolchains:

- **Python** — [uv](https://docs.astral.sh/uv/) (3.13, pinned in `.python-version`),
  [ruff](https://docs.astral.sh/ruff/) (lint/format), [ty](https://docs.astral.sh/ty/) (types).
- **TypeScript** — npm (Node ≥ 22, `.npmrc`), [Biome](https://biomejs.dev/) (lint/format),
  `tsc` (types).

With [`just`](https://github.com/casey/just):

```bash
just setup        # uv sync + npm install + prek install (git hooks)
just fmt          # ruff format + biome format
just lint         # ruff check + biome check
just typecheck    # ty + tsc
just test         # pytest
just verify       # the cumulative hard gates (Phase 0 + Phase 1 + Phase 2)
just ci           # setup + lint + typecheck + test
just perk init    # run perk in the project env
```

`just setup` also runs `just hooks` (`prek install`), wiring a [prek](https://prek.j178.dev)
pre-commit hook that runs `ruff check` on staged Python (config in `prek.toml`; the ruff
env is built by prek from the remote ruff-pre-commit repo, so it never depends on a
system/`.venv` ruff). Re-run `just hooks` after a fresh clone.

Without `just`: `uv run …` for Python (`uv run perk init`, `uv run pytest`,
`uv run ruff check perk tests`, `uv run ty check`) and `npm run …` for TypeScript
(`npm run lint`, `npm run typecheck`).
