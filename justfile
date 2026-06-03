# perk dev tasks. Python: uv + ruff + ty. TypeScript: npm + biome + tsc. Run `just` to list.
set shell := ["bash", "-uc"]

# list available recipes
default:
    @just --list

# install both toolchains: python env (uv) + node dev deps (npm) + git hooks (prek)
setup: sync install hooks

# install the prek git pre-commit shim (ruff lint + format hooks; see prek.toml)
hooks:
    prek install

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

# run the test suite (python: pytest, typescript: node:test)
test *args:
    uv run pytest {{args}}
    node --test extension/*.test.ts

# build the python wheel + sdist
build:
    uv build

# the Phase-0 hard gates (all turns; cumulative)
verify:
    bash scripts/verify-t1.sh
    bash scripts/verify-t2.sh
    bash scripts/verify-t3.sh
    bash scripts/verify-t4.sh
    bash scripts/verify-t5.sh
    bash scripts/verify-t6.sh
    bash scripts/verify-t7.sh
    bash scripts/verify-p1-t1.sh
    bash scripts/verify-p1-t2a.sh
    bash scripts/verify-p1-t2b.sh
    bash scripts/verify-p1-t3.sh
    bash scripts/verify-p1-t3b.sh
    bash scripts/verify-p1-t4a.sh
    bash scripts/verify-p1-t4b.sh
    bash scripts/verify-p1-t4c.sh
    bash scripts/verify-p1-t5a.sh
    bash scripts/verify-p1-t5b.sh
    bash scripts/verify-p1-t5c.sh
    bash scripts/verify-p1-t6.sh
    bash scripts/verify-p2-t1.sh
    bash scripts/verify-p2-t2a.sh
    bash scripts/verify-p2-t2b.sh
    bash scripts/verify-p2-t2c.sh
    bash scripts/verify-p2-t3.sh
    bash scripts/verify-p2-t4.sh
    bash scripts/verify-p2-t5.sh
    bash scripts/verify-p2-t6.sh
    bash scripts/verify-p2-t7.sh
    bash scripts/verify-p2-t8a.sh
    bash scripts/verify-p2-t8b.sh
    bash scripts/verify-p2-t8c.sh
    bash scripts/verify-p2-t9.sh
    bash scripts/verify-p2-t10.sh
    bash scripts/verify-p2-t11.sh
    bash scripts/verify-p2-t12.sh

# run perk in the project env, e.g. `just perk init`
perk *args:
    uv run perk {{args}}

# full local CI: setup, lint, typecheck, test
ci: setup lint typecheck test
