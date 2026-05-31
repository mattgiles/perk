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

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
perk init            # idempotent; wires .pi/settings.json + workflow dirs
pytest               # thin deterministic tests
bash scripts/verify-t1.sh   # the T1 hard gate
```
