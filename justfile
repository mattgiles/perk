# perk dev tasks. Python: uv + ruff + ty. TypeScript: npm + biome + tsc. Run `just` to list.
set shell := ["bash", "-uc"]

# list available recipes
default:
    @just --list

# install both toolchains (python env + node dev deps), git hooks, and the `perk` CLI on PATH
setup: sync install hooks install-cli

# install the prek git pre-commit shim (ruff lint + format hooks; see prek.toml)
hooks:
    prek install

# create/refresh the python env (3.13) + deps + dev group. `--all-packages` installs every
# workspace member editable (incl. the dev-only `perk-dev`) so `import perk_dev` resolves.
sync:
    uv sync --all-packages

# install node dev dependencies (biome, tsc, types)
install:
    npm install

# install the `perk` CLI on PATH (editable: tracks this clone; re-run after dep changes)
install-cli:
    uv tool install --editable . --force

# refresh both lockfiles
lock:
    uv lock
    npm install --package-lock-only

# The two @earendil-works devDeps move in exact lockstep (nested-registry skew otherwise —
# guarded by tests/test_packaging.py::test_pi_toolchain_pin_lockstep). Settings-delivered pi
# extension packages (pi-web-access, …) and the remote runner's global pi are deliberately
# unpinned — they track latest and never need a bump here. If the typecheck fails after a bump,
# migrate the imports tsc flags (prefer @earendil-works/pi-ai/compat over API rewrites), then
# finish with `just ci`.

# bump the pinned pi toolchain to VERSION (lockstep devDeps + lock refresh + compat verification)
bump-pi version:
    npm install --save-dev --save-exact "@earendil-works/pi-coding-agent@{{version}}" "@earendil-works/pi-ai@{{version}}"
    npm run typecheck
    node --test extension/piAiCompatGuard.test.ts
    uv run pytest tests/test_packaging.py::test_pi_toolchain_pin_lockstep -q

# format everything (ruff + biome)
fmt:
    uv run ruff format src/perk packages/perk-dev/src tests
    npm run format

# lint python (ruff)
lint-py:
    uv run ruff check src/perk packages/perk-dev/src tests

# lint typescript (biome)
lint-js:
    npm run lint

# lint everything (ruff + biome)
lint: lint-py lint-js

# type-check python (ty)
typecheck-py:
    uv run ty check

# type-check typescript (tsc)
typecheck-js:
    npm run typecheck

# type-check everything (ty + tsc)
typecheck: typecheck-py typecheck-js

# run the python test suite (pytest)
test-py *args:
    uv run pytest {{args}}

# run the typescript test suite (node:test). Mild 2x core oversubscription: session
# construction is I/O-bound, so more in-flight files overlap their I/O waits.
test-js:
    node --test --test-reporter=dot --test-concurrency=$(( $(getconf _NPROCESSORS_ONLN) * 2 )) "extension/**/*.test.ts" "docs/site/src/**/*.test.mjs"

# run the test suite (python: pytest, typescript: node:test)
test *args:
    uv run pytest {{args}}
    node --test --test-reporter=dot --test-concurrency=$(( $(getconf _NPROCESSORS_ONLN) * 2 )) "extension/**/*.test.ts" "docs/site/src/**/*.test.mjs"

# build the python wheel + sdist (pinned to perk — perk-dev is never published)
build:
    uv build --package perk

# run perk in the project env, e.g. `just perk init`
perk *args:
    uv run perk {{args}}

# run perk-dev (dev-only maintainer tooling) in the project env, e.g. `just perk-dev smoke`
perk-dev *args:
    uv run perk-dev {{args}}

# run the docs-site dev server (Starlight)
docs-dev:
    npm run docs:dev

# build the static docs site to docs/site/dist (local-only; Pagefind included)
docs-build:
    npm run docs:build

# serve the built docs site (the Pagefind-accurate acceptance surface)
docs-preview:
    npm run docs:preview

# validate CHANGELOG.md structure (two-phase convention: markers, headers, hash tokens)
changelog-check:
    uv run perk-dev changelog-check

# validate release state (changelog structure + version lockstep + tag agreement; --for-publish adds clean-tree)
release-check *args:
    uv run perk-dev release-check {{args}}

# build + smoke both publish artifacts locally (uv build --package perk + twine + wheel smoke; npm ci + npm pack --dry-run)
release-build:
    uv run perk-dev release-build

# publication preflight: release-check --for-publish + gh auth + origin-tag probe + release-build
publish-check *args:
    uv run perk-dev publish-check {{args}}

# full local CI: setup, lint, typecheck, test
ci: setup lint typecheck test changelog-check
