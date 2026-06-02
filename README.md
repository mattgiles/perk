# perk

A Pi-native, plan-oriented engineering workflow — a Python `perk` CLI (the session
*exterior*) plus a TypeScript Pi extension (the session *interior*), sequenced so that
**perk bootstraps itself**.

> Status: **Phase 1 complete.** The in-session workflow **spine** (`plan → save → implement
> → submit → land → learn`) is closed end-to-end and **dogfooded — perk ships perk** (see
> [docs/planning/phase-1-gate.md](docs/planning/phase-1-gate.md)); any plan is resumable at
> its current stage via `perk resume`. Phase 2 deepens the loop (perk-owned plan mode,
> objectives, CI + the review/address loop). See [docs/index.md](docs/index.md) for the full
> plan and [docs/ROADMAP.md](docs/ROADMAP.md) for the phasing.

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
| `perk plan \| submit \| land \| learn` | Stage **launchers**: mint a `run_id` and `exec` a primed `pi` session for that stage (the in-session *handlers* live in the extension). `--dry-run` resolves a launch without side effects. |
| `perk implement [PLAN]` | Materialize the plan's worktree/branch and launch a fresh `pi` **primed to implement it**. Optional issue number selects a specific plan; omit it to use the active saved plan. |
| `perk plan-save` / `pr-submit` / `pr-land` | The cold/worker GitHub doors (the in-session twins are the `plan_save` / `submit` / `land` tools): create the plan issue, open the draft PR, and squash-merge it. `--json` + `--dry-run`. |
| `perk resume <plan>` | Resolve any plan to its current actionable stage (no PR → implement, open → submit, merged+pending-learn → learn) and launch it. |
| `perk worktree create/list/remove` | Manage git worktrees under the configured root. |
| `perk state` / `perk registry` | Inspect the local `.pi/workflow/` cache + run ids; inspect/validate the shared stage registry. |

The in-session **warm doors** (the perk extension): `/plan-save`, `/submit`, `/land`, `/learn`
(+ the `plan_save`/`submit`/`land`/`learn` tools), cross-stage lifecycle gates, and a guard-only
`/implement`.

## Where this is going

Phases 0–1 ship the **scaffolding** and the **thin loop**, still on the **borrow-then-own**
substrate: init borrows mature community Pi packages (plan mode, a todo overlay, a statusline,
diff review) while perk-owned pieces land. **Phase 2** deepens the loop *through* it — perk-owned
plan mode + the tool-gating primitive (retiring the borrowed `pi-plan`), objectives, the CI
executor, and the review/`address` loop. The phasing, dogfood gates, and locked decisions live in
[docs/ROADMAP.md](docs/ROADMAP.md); per-turn plans (and the Phase-1
[gate record](docs/planning/phase-1-gate.md)) live in [docs/planning/](docs/planning/).

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
just verify       # the cumulative hard gates (Phase 0 + Phase 1)
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
