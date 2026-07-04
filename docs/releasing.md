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
> environment), and a `github-release` capstone job that creates the GitHub Release once both
> planes publish, with the tagged version's curated changelog section as the Release body. The
> tag build also asserts the changelog was rolled for the tagged version before either registry
> publish runs.

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
| `.perk/required-perk-version` managed pin | `src/perk/convergence/init/version_pin.py` (written by `perk init` / `perk doctor --fix`; consumed by the runtime CLI-vs-repo warning in `src/perk/cli/version_check.py` and the report-only `cli-version` doctor check) | — |
| `.perk/managed-state.toml` `[managed].version` + per-artifact `version` stamps | written by `perk init` / `perk doctor --fix` (`src/perk/convergence/managed_state.py`) | — |

### Release-time markers (maintainer, at release)

| Surface | Owner / how it moves |
| --- | --- |
| git tag `vX.Y.Z` | `perk-dev release-tag [--push]` (derived from the SSOT, annotated); asserted == both planes by `validate-release-versions` (`.github/workflows/release.yml`) |
| `CHANGELOG.md` release headers `## [X.Y.Z] - YYYY-MM-DD` | `perk-dev bump-version` (the release roll) |
| `<!-- As of <hash> -->` cursor | `perk-dev changelog-apply` during accrual; `perk-dev bump-version` re-seats it at the release HEAD |
| GitHub Release `vX.Y.Z` | the `github-release` capstone, after both registries publish |

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
4. **Apply + advance the marker** — `perk-dev changelog-apply --proposal <file>` appends the
   approved entries under their categories with the ` (hash)` token and advances the
   `<!-- As of <hash> -->` marker to the proposal's `head_commit`. `--dry-run` prints the intended
   new `[Unreleased]` section without writing anything.
5. **Validate** — `just changelog-check` (or `perk-dev changelog-check`) structurally lints the
   result (pinned categories, the ` (hash)` token discipline).

The **facts + lint + apply** tooling (`changelog-commits`, `changelog-check`, `changelog-apply`)
**now exists**, and classification follows the categorizer doc. The **release phase** is tooled
too: `perk-dev bump-version` performs the roll (with the version bump), `perk-dev release-check`
judges the resulting release state, `perk-dev release-build` rehearses both publish artifacts
locally, and `perk-dev release-tag` cuts the annotated tag at release time.

## Release runbook (coordinated dual-plane)

1. **Bump + roll:** `perk-dev bump-version X.Y.Z` (or `--bump patch|minor|major`). One command
   covers the whole release edit: `pyproject.toml` + `uv.lock` via `uv version --no-sync`,
   `package.json` + `package-lock.json` via `npm version --no-git-tag-version`, and the CHANGELOG
   roll (tokens stripped from the released bullets, `[Unreleased]` → `[X.Y.Z] - <date>`, a fresh
   `[Unreleased]` with a new `<!-- As of <hash> -->` marker at the release HEAD). The env sync is
   deferred: the next `uv run` re-syncs, so `perk.__version__` catches up on its own. `--dry-run`
   prints the intended new sections without writing anything. After the bump, run
   `perk doctor --fix` (or `perk init`) to reconverge the version-stamped managed files (the
   AGENTS `perk version:` stamp and `.perk/required-perk-version`) into the release commit.
2. **Verify locally:** `just publish-check` is the one-shot publication preflight. It composes
   `release-check --for-publish` (changelog structure, version lockstep, local tag agreement,
   clean tree) and `release-build` (build + smoke both publish artifacts, publishing nothing),
   and adds two checks of its own: `gh auth status` and a best-effort origin probe for the
   `v{version}` tag (a tag already on origin warns and points at the
   [incident runbook](#incident-handling) — it never fails the preflight, since re-running
   post-tag pre-approval is a legitimate state). Pass `--allow-dirty` to skip the clean-tree
   requirement while rehearsing. The granular alternatives remain: `just release-check` judges
   the release state in one shot — the changelog structure, version lockstep across the three
   surfaces, and local tag agreement (run `just release-check --for-publish` before tagging to
   additionally require a clean tree) — and `just release-build` builds + smokes both publish
   artifacts locally (`uv build --package perk` + `twine check` + a wheel `perk --help` smoke;
   `npm ci` + `npm pack --dry-run` + a tarball file check), publishing nothing. Also run
   `just test` (so `test_version_lockstep` proves
   `pyproject == package.json == __version__`). `perk-dev release-info` (or `--json`) remains the
   judgment-free **facts** report — the version surfaces, the `v{version}` tag (local + origin),
   the latest release header, and whether the changelog marker is at HEAD — handy before and
   after the bump.
3. **Land the release commit** on `main` via the normal PR flow.
4. **Tag:** `uv run perk-dev release-tag --push` — the tag name is **derived** from the
   pyproject SSOT (`v{version}`; free-form names are refused structurally), the tag is
   **annotated**, and a re-run when the tag already sits at HEAD is a clean no-op. The manual
   equivalent is `git tag -a v0.1.0 -m "v0.1.0" && git push origin v0.1.0`.
5. The tag push triggers `release.yml`: `validate-release-versions` asserts the tag matches both
   plane versions **and** that `CHANGELOG.md` carries a rolled `## [X.Y.Z] - YYYY-MM-DD` section
   for the tagged version (a never-rolled changelog can no longer reach a registry). On success,
   `publish-pypi` and `publish-npm` run behind their deployment environment approvals; the GitHub
   Release is created only after both registries publish, with the tagged version's changelog
   section as its body (no longer auto-generated notes).

> **Rehearsal:** before cutting a real tag, maintainers can validate the publish path end-to-end
> via **Actions → Release → "Run workflow"** (`workflow_dispatch`), which runs `publish-testpypi`
> against TestPyPI (behind the `testpypi-publish` environment) with zero production risk.

## Incident handling

The standing law: **never publish around the gate by hand.** No manual `uv publish`, no manual
`npm publish`, no matter how stuck a run looks — every recovery below goes through `release.yml`.

Two facts shape every scenario:

- **Registries never overwrite a version.** Neither PyPI nor npm allows re-uploading an existing
  version (PyPI ignores re-uploads of byte-identical files; anything else is rejected). A version
  a registry has accepted is immutable — recovery is never "fix and re-publish X.Y.Z over itself".
- **The recovery primitive is re-running only the failed job** — `gh run rerun <run-id> --failed`
  or the Actions UI's "Re-run failed jobs". Environment approvals re-prompt on the re-run; jobs
  that already succeeded (including a publish the other registry accepted) are not re-executed.

State-check toolkit (all read-only) for establishing where a release actually stands:

```bash
uv run perk-dev release-info        # local/origin tag facts + version surfaces
gh run list --workflow release.yml  # recent runs; then: gh run view <run-id>
gh release view vX.Y.Z              # does the GitHub Release exist?
npm view @mgiles/perk@X.Y.Z version # did npm accept X.Y.Z?
# PyPI: check https://pypi.org/project/perk/ for X.Y.Z
```

### 1. One registry accepted, one failed (partial publish)

**Symptom:** `publish-pypi` or `publish-npm` failed; the other succeeded. **State check:**
`npm view` + the PyPI project page tell you which side has X.Y.Z. **Recovery:** fix the failing
side's configuration (token expiry and trusted-publisher mismatch below are the common causes),
then re-run only the failed publish job for the same tag. Never bump a new version to escape —
unless you deliberately abandon X.Y.Z on the accepted registry, in which case record the
abandonment in the GitHub Release or a follow-up issue.

### 2. Tag without publish

**Symptom:** the tag is pushed but both registries are still empty for X.Y.Z (an early job
failure, or the environment approvals were never granted). **State check:** `perk-dev
release-info` shows the tag on origin; `npm view` and the PyPI page show nothing. **Recovery:**
re-run (or approve) the same run. Alternatively — **only while both registries are empty for
X.Y.Z** — delete the tag, fix, and retag:

```bash
git push origin :refs/tags/vX.Y.Z && git tag -d vX.Y.Z
```

Never delete a tag once any registry has accepted the version.

### 3. Rolled changelog + deleted tag

**Symptom:** `CHANGELOG.md` says `[X.Y.Z]` but no tag or publish exists (scenario 2's tag-delete
arm, or a roll that never got tagged). **Recovery:** either re-tag the same version at the
release commit (safe — the registries never saw X.Y.Z), or abandon X.Y.Z: fold its entries back
into `[Unreleased]` (restoring their ` (hash)` tokens) and delete the stale release header.
`changelog-check` and the tag build's changelog-rolled gate keep either path honest.

### 4. npm token expiry

**Symptom:** `publish-npm` fails with `E401`/`ENEEDAUTH`. This is the most common cause of
scenario 1. **Recovery:** rotate the granular npm token, update the `NPM_TOKEN` repository
secret (checklist [§1.4](./release-checklist.md)), and re-run the failed `publish-npm` job.

### 5. PyPI trusted-publisher mismatch

**Symptom:** `publish-pypi` fails with an OIDC invalid-publisher error. **Recovery:** fix the
publisher fields on PyPI to exactly owner `mattgiles`, repo `perk`, workflow `release.yml`,
environment `pypi-publish` (checklist [§3](./release-checklist.md)), and re-run the failed
`publish-pypi` job.

### Version validation failed

If `validate-release-versions` fails, the tag disagrees with the code (or the changelog was never
rolled for the tagged version). Delete the bad tag (both registries are necessarily still empty —
the publish jobs never ran), fix the version (`perk-dev bump-version`) or retag, and re-push.
