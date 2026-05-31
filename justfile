# perk dev tasks. Python: uv + ruff + ty. TypeScript: npm + biome + tsc. Run `just` to list.
set shell := ["bash", "-uc"]

# list available recipes
default:
    @just --list

# install both toolchains: python env (uv) + node dev deps (npm)
setup: sync install

# create/refresh the python env (3.13) + deps + dev group
sync:
    uv sync

# install node dev dependencies (biome, tsc, types)
install:
    npm install

# refresh both lockfiles
lock:
    uv lock
    npm install --package-lock-only

# format everything (ruff + biome)
fmt:
    uv run ruff format perk tests
    npm run format

# lint everything (ruff + biome)
lint:
    uv run ruff check perk tests
    npm run lint

# type-check everything (ty + tsc)
typecheck:
    uv run ty check
    npm run typecheck

# run the test suite
test *args:
    uv run pytest {{args}}

# build the python wheel + sdist
build:
    uv build

# the Phase-0 hard gates (all turns; cumulative)
verify:
    bash scripts/verify-t1.sh
    bash scripts/verify-t2.sh

# run perk in the project env, e.g. `just perk init`
perk *args:
    uv run perk {{args}}

# full local CI: setup, lint, typecheck, test
ci: setup lint typecheck test
