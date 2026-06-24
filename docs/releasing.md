# Releasing perk

Maintainer-facing release policy + runbook for perk's two published planes:

- **`perk`** — the Python CLI, published to PyPI.
- **`@perk/pi`** — the TypeScript Pi extension, published to npm.

Both planes **always release at the same version, from one tag.** This document is the human
runbook; the publish workflows (PyPI + npm) enact it and hang their publish jobs off the
`validate-release-versions` gate in `.github/workflows/release.yml`.

> **Status:** the **PyPI** publish path is wired — an always-on `build-pypi` job (build + `twine
> check` + wheel smoke-test on every PR/`main`/tag), a tag-gated `publish-pypi` job that uploads to
> production PyPI via OIDC trusted publishing behind the `pypi-publish` environment approval gate,
> and a `workflow_dispatch` TestPyPI rehearsal (`publish-testpypi`). The **npm** half (build +
> `publish-npm` + the GitHub Release step) is still pending a future release stage.

## Versioning policy

perk follows [semantic versioning](https://semver.org/). **Pre-1.0 caveat (`0.x`):**

- A **minor** bump (`0.y` → `0.(y+1)`) may include breaking changes.
- A **patch** bump (`0.y.z` → `0.y.(z+1)`) is fixes and docs only.

This is policy, documented here — it is not enforced in code.

## The version SSOT chain

`pyproject.toml` `[project] version` is the **single source of truth**, bumped with `uv version`.
Everything else derives from or mirrors it:

- **hatchling** reads `[project] version` for the wheel/sdist build (the build backend is
  unchanged; it still force-includes top-level `shared/` → `perk/_shared` and `agents/` →
  `perk/_agents`).
- **`perk.__version__`** derives from the installed package metadata
  (`importlib.metadata.version("perk")`), with a `tomllib` fallback that reads the sibling
  `pyproject.toml` `[project] version` for a raw (uninstalled) source tree.
- **`package.json`** `version` mirrors the SSOT; equality across all three is guarded by
  `tests/test_packaging.py::test_version_lockstep`.

> **Future (objective node 2.2):** `perk init` will wire the consumer's `@perk/pi` npm entry
> pinned to the released version. Today the consumer pin is `@main`; the version-pinned npm
> wiring lands later in this objective.

## One-time publishing setup

The publish jobs assume trusted publishing + deployment environments are configured out-of-band. A
maintainer does this once:

- **On PyPI:** configure a *trusted publisher* for project `perk` — owner `mattgiles`, repo `perk`,
  workflow `release.yml`, environment `pypi-publish`.
- **On TestPyPI:** the same trusted-publisher config, environment `testpypi-publish`.
- **In GitHub repo settings → Environments:** create `pypi-publish` (with **required reviewers** —
  this is the human approval gate) and `testpypi-publish`.

No API tokens are stored anywhere — publishing is OIDC-only.

## CHANGELOG discipline

Every user-facing change updates `CHANGELOG.md` (root) under `## [Unreleased]`. At release, the
`[Unreleased]` heading is renamed to the version + date and a fresh empty `[Unreleased]` section
is added above it.

## Release runbook (coordinated dual-plane)

1. **Bump the SSOT:** `uv version --bump patch` (or `minor`, or `uv version X.Y.Z`). This edits
   `pyproject.toml`, re-locks `uv.lock`, and refreshes the editable install (so `perk.__version__`
   reflects it).
2. **Mirror to npm:** `npm version "$(uv version --short)" --no-git-tag-version` (updates
   `package.json` + `package-lock.json`; no git commit/tag). If a given `uv` lacks `--short`, read
   the bare version from `pyproject.toml` `[project] version` instead.
3. **Roll the CHANGELOG:** rename `[Unreleased]` → `[X.Y.Z] — <date>` and add a fresh empty
   `[Unreleased]` above it.
4. **Verify locally:** `just test` (so `test_version_lockstep` proves
   `pyproject == package.json == __version__`).
5. **Land the release commit** on `main` via the normal PR flow.
6. **Tag:** create + push an **annotated** tag `vX.Y.Z` on the merged commit
   (e.g. `git tag -a v0.1.0 -m "v0.1.0" && git push origin v0.1.0`).
7. The tag push triggers `release.yml`: `validate-release-versions` asserts the tag matches both
   plane versions. On success, `publish-pypi` runs and **waits on the `pypi-publish` environment
   approval** before uploading the built dist to production PyPI over OIDC.

> **Rehearsal:** before cutting a real tag, maintainers can validate the publish path end-to-end
> via **Actions → Release → "Run workflow"** (`workflow_dispatch`), which runs `publish-testpypi`
> against TestPyPI (behind the `testpypi-publish` environment) with zero production risk.

## Failure modes

If `validate-release-versions` fails, the tag disagrees with the code. Delete the bad tag, fix the
version (re-run `uv version` + `npm version`) or retag, and re-push. **Never publish around the gate
by hand.**
