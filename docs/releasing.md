# Releasing perk

Maintainer-facing release policy + runbook for perk's two published planes:

- **`perk`** — the Python CLI, published to PyPI.
- **`@mgiles/perk`** — the TypeScript Pi extension, published to npm.

Both planes **always release at the same version, from one tag.** This document is the human
runbook; the publish workflows (PyPI + npm) enact it and hang their publish jobs off the
`validate-release-versions` gate in `.github/workflows/release.yml`.

For the first real release, use the step-by-step
[release checklist](./release-checklist.md) before following the shorter runbook below.

> **Status:** both planes are wired. **PyPI:** an always-on `build-pypi` job (build + `twine check`
> + wheel smoke) on every PR/`main`/tag, a tag-gated `publish-pypi` (OIDC trusted publishing behind
> the `pypi-publish` environment), and a `workflow_dispatch` TestPyPI rehearsal. **npm:** an
> always-on `build-npm` job (`npm ci` + `npm pack` + tarball artifact), a tag-gated `publish-npm`
> (`npm publish --provenance --access public`, `NPM_TOKEN` auth behind the `npm-publish`
> environment), and a `github-release` capstone job that creates the GitHub Release (with generated
> notes) once both planes publish.

## Versioning policy

perk follows [semantic versioning](https://semver.org/). **Pre-1.0 caveat (`0.x`):**

- A **minor** bump (`0.y` → `0.(y+1)`) may include breaking changes.
- A **patch** bump (`0.y.z` → `0.y.(z+1)`) is fixes and docs only.

This is policy, documented here — it is not enforced in code.

## Version graph

`pyproject.toml` `[project] version` is the **single source of truth**, bumped with `uv version`.
Everything else derives from or mirrors it: **hatchling** reads `[project] version` for the
wheel/sdist build; **`perk.__version__`** derives from the installed package metadata
(`importlib.metadata.version("perk")`), with a `tomllib` fallback that reads the sibling
`pyproject.toml` `[project] version` for a raw (uninstalled) source tree; **`package.json`**
`version` mirrors the SSOT; and `perk init` wires the consumer's `@mgiles/perk` npm entry pinned
to the running `perk` version. The table below names **every** version-bearing surface and its
owner so the graph doubles as a guard map (the **Guard** column names the lockstep test that
pins a surface, where one exists).

### SSOT & mirrors

| Surface | Role | Owner / how it moves | Guard |
| --- | --- | --- | --- |
| `pyproject.toml` `[project] version` | **SSOT** | `uv version` | `test_version_lockstep` |
| `package.json` `version` | mirror | `npm version` | `test_version_lockstep` |
| `perk.__version__` (`perk/__init__.py`) | derived | `importlib.metadata` + `tomllib` fallback | `test_version_lockstep` |

### Lockfiles (auto-maintained)

| Surface | Owner / how it moves |
| --- | --- |
| `uv.lock` | regenerated from `pyproject.toml` by `uv` |
| `package-lock.json` | regenerated from `package.json` by `npm` |

### Derived / stamped surfaces (all flow from `__version__`)

| Surface | Owner | Guard |
| --- | --- | --- |
| `perk --version` | `perk/cli/cli.py` (`click.version_option`) | — |
| AGENTS managed stamp `perk version: {…}` | `perk/convergence/init/blocks.py` (written by `perk init`) | — |
| consumer npm pin `npm:@mgiles/perk@{…}` | `perk/convergence/init/settings.py` | `test_npm_pin_lockstep` |
| extension-install pin `@mgiles/perk@{…}` | `perk/convergence/init/extension_install.py` | `test_npm_pin_lockstep` |
| remote-runner PyPI pin `uv tool install perk=={…}` | `perk/run/workflow_artifacts.py` | — |
| `PERK_CLI_VERSION` launch env var (informational) | `perk/run/launch/__init__.py` | — |
| materialize splash `perk v{…}` | `perk/run/launch/materialize.py` | — |
| extension self-version via `perkVersion()` | `extension/substrate/resources.ts` (reads the shipped `@mgiles/perk` `package.json`; compared against `PERK_CLI_VERSION` for the soft drift signal) | — |

### Release-time markers (maintainer, at release)

| Surface | Owner / how it moves |
| --- | --- |
| git tag `vX.Y.Z` | maintainer; asserted == both planes by `validate-release-versions` (`.github/workflows/release.yml`) |
| `CHANGELOG.md` release headers `## [X.Y.Z] - YYYY-MM-DD` | maintainer at release |
| `<!-- As of <hash> -->` cursor | maintainer (manual now; Phase 2 tooling later) |
| GitHub Release `vX.Y.Z` | the `github-release` capstone, after both registries publish |

### Planned (Phase 5)

| Surface | Status |
| --- | --- |
| `.perk/required-perk-version` | a managed file pinning the consumer's required perk version — **not yet built** (objective #1010, node 5.1) |

## One-time publishing setup

The publish jobs assume trusted publishing + deployment environments are configured out-of-band. A
maintainer does this once:

- **On PyPI:** configure a *trusted publisher* for project `perk` — owner `mattgiles`, repo `perk`,
  workflow `release.yml`, environment `pypi-publish`.
- **On TestPyPI:** the same trusted-publisher config, environment `testpypi-publish`.
- **On npm:** create a granular publish token for the `@mgiles` scope/package and store it as the
  GitHub Actions repository secret `NPM_TOKEN`.
- **In GitHub repo settings → Environments:** create `pypi-publish`, `testpypi-publish`, and
  `npm-publish` (with **required reviewers** — these are the human approval gates).

PyPI/TestPyPI use OIDC trusted publishing, so no PyPI API token is stored. The current npm workflow
uses `NPM_TOKEN`; moving npm to OIDC trusted publishing is a separate workflow change.

## CHANGELOG discipline

Every user-facing change updates `CHANGELOG.md` (root) under `## [Unreleased]`. The changelog
follows a **two-phase convention**:

**Accrual phase (`[Unreleased]`).** The `[Unreleased]` section carries a `<!-- As of <hash> -->`
marker directly under the heading recording the **last covered commit** — the cursor for "what is
already in the changelog". Every new entry bullet ends with a **parenthesized short-hash token**
of the commit it summarizes, e.g. `- Added the foo door (abc1234)`. As entries land, advance the
marker to the newest covered commit.

**Release phase.** **Strip** the parenthesized hash tokens from the now-released bullets (released
sections carry **no** tokens), rename `## [Unreleased]` → `## [X.Y.Z] - YYYY-MM-DD`, and add a
fresh empty `## [Unreleased]` above it with a **new** marker at the release HEAD.

These changelog steps are performed **manually until the Phase 2 tooling (`perk-dev
changelog-*`) exists**.

## Release runbook (coordinated dual-plane)

1. **Bump the SSOT:** `uv version --bump patch` (or `minor`, or `uv version X.Y.Z`). This edits
   `pyproject.toml`, re-locks `uv.lock`, and refreshes the editable install (so `perk.__version__`
   reflects it).
2. **Mirror to npm:** `npm version "$(uv version --short)" --no-git-tag-version` (updates
   `package.json` + `package-lock.json`; no git commit/tag). If a given `uv` lacks `--short`, read
   the bare version from `pyproject.toml` `[project] version` instead.
3. **Roll the CHANGELOG:** strip the parenthesized hash tokens from the released bullets, rename
   `[Unreleased]` → `[X.Y.Z] - <date>`, and add a fresh empty `[Unreleased]` above it **with a new
   `<!-- As of <hash> -->` marker at the release HEAD**.
4. **Verify locally:** `just test` (so `test_version_lockstep` proves
   `pyproject == package.json == __version__`).
5. **Land the release commit** on `main` via the normal PR flow.
6. **Tag:** create + push an **annotated** tag `vX.Y.Z` on the merged commit
   (e.g. `git tag -a v0.1.0 -m "v0.1.0" && git push origin v0.1.0`).
7. The tag push triggers `release.yml`: `validate-release-versions` asserts the tag matches both
   plane versions. On success, `publish-pypi` and `publish-npm` run behind their deployment
   environment approvals; the GitHub Release is created only after both registries publish.

> **Rehearsal:** before cutting a real tag, maintainers can validate the publish path end-to-end
> via **Actions → Release → "Run workflow"** (`workflow_dispatch`), which runs `publish-testpypi`
> against TestPyPI (behind the `testpypi-publish` environment) with zero production risk.

## Failure modes

If `validate-release-versions` fails, the tag disagrees with the code. Delete the bad tag, fix the
version (re-run `uv version` + `npm version`) or retag, and re-push. **Never publish around the gate
by hand.**
