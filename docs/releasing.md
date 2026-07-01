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

> **Not a tracked surface:** `packages/perk-dev` is a never-published, dev-only workspace member.
> Its `[project] version` is a static `0.0.0` placeholder and is **intentionally not a
> tracked/version-bearing surface** (so no lockstep guard); `perk-dev --version` reuses
> `perk.__version__`.

### SSOT & mirrors

| Surface | Role | Owner / how it moves | Guard |
| --- | --- | --- | --- |
| `pyproject.toml` `[project] version` | **SSOT** | `uv version` | `test_version_lockstep` |
| `package.json` `version` | mirror | `npm version` | `test_version_lockstep` |
| `perk.__version__` (`src/perk/__init__.py`) | derived | `importlib.metadata` + `tomllib` fallback | `test_version_lockstep` |

### Lockfiles (auto-maintained)

| Surface | Owner / how it moves |
| --- | --- |
| `uv.lock` | regenerated from `pyproject.toml` by `uv` |
| `package-lock.json` | regenerated from `package.json` by `npm` |

### Derived / stamped surfaces (all flow from `__version__`)

| Surface | Owner | Guard |
| --- | --- | --- |
| `perk --version` | `src/perk/cli/cli.py` (`click.version_option`) | — |
| AGENTS managed stamp `perk version: {…}` | `src/perk/convergence/init/blocks.py` (written by `perk init`) | — |
| consumer npm pin `npm:@mgiles/perk@{…}` | `src/perk/convergence/init/settings.py` | `test_npm_pin_lockstep` |
| extension-install pin `@mgiles/perk@{…}` | `src/perk/convergence/init/extension_install.py` | `test_npm_pin_lockstep` |
| remote-runner PyPI pin `uv tool install perk=={…}` | `src/perk/run/workflow_artifacts.py` | — |
| `PERK_CLI_VERSION` launch env var (informational) | `src/perk/run/launch/__init__.py` | — |
| materialize splash `perk v{…}` | `src/perk/run/launch/materialize.py` | — |
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

### The accrual loop

Entries accrue between releases via a facts → classify → review → apply → lint loop:

1. **Gather facts** — `perk-dev changelog-commits` (or `--json`) reports the first-parent commits
   since the `<!-- As of <hash> -->` marker. It applies **no** judgment beyond dropping the two
   lockfiles.
2. **Classify** — an agent (or the maintainer) turns those facts into a reviewed changelog
   proposal following [`docs/release/changelog-categorizer.md`](./release/changelog-categorizer.md),
   which owns *all* inclusion/exclusion and categorization judgment (the user-visibility test, the
   pinned categories, roll-up, backend qualifiers, confidence flags) and pins the proposal-JSON
   output shape.
3. **Human review** — the maintainer reviews the proposal (the `confidence` / `backend` markers
   focus that review) and approves the entries to apply.
4. **Apply + advance the marker** — append the approved entries under their categories with the
   ` (hash)` token and advance the `<!-- As of <hash> -->` marker to the newest covered commit.
   `perk-dev changelog-apply --proposal <file>` will enact this — *forthcoming (node 3.2); until it
   ships, edit `CHANGELOG.md` by hand.*
5. **Validate** — `just changelog-check` (or `perk-dev changelog-check`) structurally lints the
   result (pinned categories, the ` (hash)` token discipline).

The Phase 2 **facts + lint** tooling (`changelog-commits`, `changelog-check`) **now exists**, and
classification follows the categorizer doc. The **apply + marker-advance** step (`changelog-apply`,
node 3.2) and the **release roll** (node 4.2) remain **forthcoming** and are done by hand until
then.

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
