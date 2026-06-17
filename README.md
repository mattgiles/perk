# perk

A Pi-native, plan-oriented engineering workflow — a Python `perk` CLI (the session
*exterior*) plus a TypeScript Pi extension (the session *interior*), sequenced so that
**perk bootstraps itself**.

> perk is in active development, dogfooded on its own repo. **Using perk on your own repo?**
> Start at [`docs/user-docs/`](docs/user-docs/index.md).

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

`perk init` requires a git repo + `git`, `gh`, `node ≥ 22`, `ast-grep`, and `pi` on PATH. GitHub auth
is verified but never required (it is reported, never fatal).

For the guided first run, follow
[Get started with perk](docs/user-docs/tutorials/get-started.md).

## Documentation

The operator-facing docs live under [`docs/user-docs/`](docs/user-docs/index.md), organized as
the four [Divio](https://docs.divio.com/documentation-system/) quadrants:

- **[Tutorials](docs/user-docs/tutorials/index.md)** — learning-oriented lessons; start with
  [Get started with perk](docs/user-docs/tutorials/get-started.md).
- **[How-to guides](docs/user-docs/how-to/index.md)** — goal-oriented recipes (resume a plan,
  address review feedback, switch to Linear, attach a skill, …).
- **[Reference](docs/user-docs/reference/index.md)** — the CLI surface, in-session commands &
  tools, the objective roadmap model, configuration, and providers & backends.
- **[Explanation](docs/user-docs/explanation/index.md)** — how perk thinks; headless/remote
  maturity.

perk's internal research and planning record lives under [`docs/`](docs/index.md) and is for
perk's own developers.

## Layout

- `perk/` — the Python CLI (the session exterior).
- `extension/` — the TypeScript Pi extension (the session interior).
- `shared/` — cross-plane contracts (the stage registry + specs), bundled into both build
  artifacts.
- `docs/` — research inputs, design notes, and durable learnings.

## Develop

Two pinned toolchains:

- **Python** — [uv](https://docs.astral.sh/uv/) (3.13, pinned in `.python-version`),
  [ruff](https://docs.astral.sh/ruff/) (lint/format), [ty](https://docs.astral.sh/ty/) (types).
- **TypeScript** — npm (Node ≥ 22, `.npmrc`), [Biome](https://biomejs.dev/) (lint/format),
  `tsc` (types).

With [`just`](https://github.com/casey/just):

```bash
just setup        # uv sync + npm install + git hooks + install-cli (the `perk` CLI on PATH)
just install-cli  # just the `perk` CLI on PATH (editable: tracks this clone)
just fmt          # ruff format + biome format
just lint         # ruff check + biome check
just typecheck    # ty + tsc
just test         # pytest + node:test (the regression gate)
just ci           # setup + lint + typecheck + test
```

After `just setup` (or `just install-cli`), call `perk` directly — no `uv run`. The install is
**editable**, so a `git pull` reflects Python changes live; re-run `just install-cli` after a
dependency change. It lands in uv's tool bin (`~/.local/bin`) — if `perk` isn't found, that dir
is not on your `PATH`; run `uv tool update-shell` (then restart your shell). Remove it with
`uv tool uninstall perk`.

`just setup` also runs `just hooks` (`prek install`), wiring a [prek](https://prek.j178.dev)
pre-commit hook that runs `ruff check` on staged Python (config in `prek.toml`; the ruff
env is built by prek from the remote ruff-pre-commit repo, so it never depends on a
system/`.venv` ruff). Re-run `just hooks` after a fresh clone.

Without `just`: `uv run …` for Python (`uv run perk init`, `uv run pytest`,
`uv run ruff check perk tests`, `uv run ty check`) and `npm run …` for TypeScript
(`npm run lint`, `npm run typecheck`).
