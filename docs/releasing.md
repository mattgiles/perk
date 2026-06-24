# Releasing perk

Maintainer-facing release policy + runbook for perk's two published planes:

- **`perk`** — the Python CLI, published to PyPI.
- **`@perk/pi`** — the TypeScript Pi extension, published to npm.

Both planes **always release at the same version, from one tag.** This document is the human
runbook; the publish workflows (PyPI + npm) enact it and hang their publish jobs off the
`validate-release-versions` gate in `.github/workflows/release.yml`.

> **Status:** until the PyPI/npm publish jobs land, `release.yml` **only validates** version
> agreement on a tag push — it does not publish anything.

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
   plane versions. On success the (future, publish) jobs run behind a deployment-environment human
   approval gate.

## Failure modes

If `validate-release-versions` fails, the tag disagrees with the code. Delete the bad tag, fix the
version (re-run `uv version` + `npm version`) or retag, and re-push. **Never publish around the gate
by hand.**
