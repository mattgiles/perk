# perk

perk is a [Pi](https://pi.dev)-native workflow for plan-driven software engineering.

It combines a Python CLI that manages the **session exterior**, a TypeScript Pi extension
that governs the **session interior**, and an **issue backend** for durable workflow state,
GitHub by default. The workflow is organized around _planning_, _implementation_,
_code review_, and _learning_.

Workflow stages and surfaces can use perk’s built-in defaults or pluggable third-party
extensions, such as [plannonator](https://github.com/backnotprop/plannotator) for plan
review.

perk is built for work that may be interrupted, resumed elsewhere, superseded, or moved
across machines. Resumability, human feedback, and remote execution are not special cases;
they are part of the core model.

`perk` is inspired by `erk`, formerly maintained by the team at
[Dagster](https://github.com/dagster-io/dagster).

## What perk is

perk's unit of work is a **plan**: a reviewed, durable description of a change,
written before files are edited and saved as canonical workflow state. The core spine is
`plan -> save -> implement -> submit -> address -> land -> learn`; `address` only happens
when review feedback needs a response. Longer-running **objectives** can emit bounded plans
into the same spine.

The implementation is split across two planes:

- **exterior** — the Python `perk` CLI, which scaffolds repos, manages worktrees,
  mints run ids, and launches primed `pi` sessions;
- **interior** — a TypeScript Pi extension, which owns in-session stage transitions,
  tool gates, context, and warm `/...` commands.

Both planes read the language-neutral [`shared/`](shared/) registry and contracts directly.
There is no codegen layer to drift.

The operating model is deliberately simple: canonical state lives in GitHub by default
(Linear is supported), `.perk/workflow/` is a local cache, and session state is throwaway.
Cold doors launch fresh context from a shell (`perk implement`, `perk plan resume`); warm
doors keep context inside a session (`/submit`, `/land`, `/learn`). `implement` and
`address` can dispatch to CI; review, merge, and learning stay local.

## Quickstart

From the git repo you want to wire:

```bash
uv tool install perk
perk init
perk doctor
perk plan
```

`perk init` is idempotent and safe to re-run. `perk doctor` reports health;
`perk doctor --fix` repairs managed drift.

You need a git repo plus `git`, `gh`, `node >= 22`, `pi`, and `uv`. `ast-grep` is preferred
for structural search and reported when absent, but it is advisory. GitHub auth is verified
and reported by init; it becomes required when you drive real plans, PRs, and merges.

For the guided first run, follow
[Get started with perk](docs/user-docs/tutorials/get-started.md).

## Documentation

Operator docs live under [`docs/user-docs/`](docs/user-docs/index.md):

- **[Tutorials](docs/user-docs/tutorials/index.md)** — learn by doing; start with
  [Get started with perk](docs/user-docs/tutorials/get-started.md).
- **[How-to guides](docs/user-docs/how-to/index.md)** — recipes for specific jobs:
  resume a plan, address review feedback, switch to Linear, attach a skill, dispatch to CI.
- **[Reference](docs/user-docs/reference/index.md)** — CLI commands, in-session commands
  and tools, objectives, configuration, providers, backends, and schemas.
- **[Explanation](docs/user-docs/explanation/index.md)** — the mental model: plans,
  planes, state tiers, doors, and remote maturity.

Internal research, design notes, and durable learnings live under [`docs/`](docs/index.md).

## Layout

- `perk/` — Python CLI, the session exterior.
- `extension/` — TypeScript Pi extension, the session interior.
- `shared/` — stage registry and cross-plane contracts.
- `docs/` — operator docs, research, design notes, and learnings.

## Develop

Two pinned toolchains:

- **Python** — [uv](https://docs.astral.sh/uv/) (3.13, pinned in `.python-version`),
  [ruff](https://docs.astral.sh/ruff/) (lint/format), [ty](https://docs.astral.sh/ty/) (types).
- **TypeScript** — npm (Node ≥ 22, `.npmrc`), [Biome](https://biomejs.dev/) (lint/format),
  `tsc` (types).

With [`just`](https://github.com/casey/just):

```bash
just setup
just install-cli
just fmt
just lint
just typecheck
just test
just ci
```

`just setup` runs `uv sync`, `npm install`, `just hooks`, and `just install-cli`. The hook is
managed by [prek](https://prek.j178.dev) and runs `ruff check` on staged Python. Re-run
`just hooks` after a fresh clone if hooks are missing.

Without `just`: `uv run …` for Python (`uv run perk init`, `uv run pytest`,
`uv run ruff check perk tests`, `uv run ty check`) and `npm run …` for TypeScript
(`npm run lint`, `npm run typecheck`).
