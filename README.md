# perk

A Pi-native, plan-oriented engineering workflow — a Python `perk` CLI (the session
*exterior*) plus a TypeScript Pi extension (the session *interior*), sequenced so that
**perk bootstraps itself**.

> Status: **Phase 0, Turn 1.** Skeleton + the minimal `perk init`. See
> [docs/index.md](docs/index.md) for the full plan, and
> [docs/phase-0-turn-1.md](docs/phase-0-turn-1.md) for this turn.

## Layout

- `perk/` — the Python CLI (`perk --version`, `perk init`).
- `extension/` — the TypeScript Pi extension (loaded into a running `pi` session).
- `shared/` — cross-plane contracts, bundled into both build artifacts.
- `docs/` — research, roadmap, and per-turn plans.

## Develop

Two pinned toolchains:

- **Python** — [uv](https://docs.astral.sh/uv/) (3.13, pinned in `.python-version`),
  [ruff](https://docs.astral.sh/ruff/) (lint/format), [ty](https://docs.astral.sh/ty/) (types).
- **TypeScript** — npm (Node ≥ 22, `.npmrc`), [Biome](https://biomejs.dev/) (lint/format),
  `tsc` (types).

With [`just`](https://github.com/casey/just):

```bash
just setup        # uv sync + npm install
just fmt          # ruff format + biome format
just lint         # ruff check + biome check
just typecheck    # ty + tsc
just test         # pytest
just verify       # the Phase-0 Turn-1 hard gate
just ci           # setup + lint + typecheck + test
just perk init    # run perk in the project env
```

Without `just`: `uv run …` for Python (`uv run perk init`, `uv run pytest`,
`uv run ruff check perk tests`, `uv run ty check`) and `npm run …` for TypeScript
(`npm run lint`, `npm run typecheck`).
