# Release Checklist

This is the step-by-step checklist for the first real perk release after objective
[#786](https://github.com/mattgiles/perk/issues/786).

The shape is:

- one git tag, `vX.Y.Z`
- one Python package on PyPI, `perk`
- one npm package, `@mgiles/perk`
- one GitHub Actions workflow, `.github/workflows/release.yml`
- PyPI publishes with trusted publishing, so there is no PyPI token
- npm currently publishes with a GitHub secret named `NPM_TOKEN`

Do not tag a production release until the one-time setup is complete.

## 0. Mental model

There are two distributed artifacts, but only one version line.

The Python CLI is published as `perk` on PyPI. Users install it with:

```bash
uv tool install perk
```

The Pi extension is published as `@mgiles/perk` on npm. A consumer repo does not install this by
hand: `perk init` writes a version-pinned `npm:@mgiles/perk@X.Y.Z` entry and `perk init` /
`perk doctor --fix` install that package under `.pi/npm/`.

The source version lives in `pyproject.toml`. The npm version in `package.json` must mirror it.
The tests enforce that parity. The release workflow also checks that the git tag matches both
versions before either registry publish runs.

## 1. One-time setup: accounts and package names

Do this once, before the first production tag.

### 1.1. Confirm local tools

From the repo root:

```bash
gh auth status
uv --version
npm --version
node --version
just --list
```

Expected:

- `gh` is authenticated as an account with admin access to `mattgiles/perk`.
- Node is new enough for this repo. CI uses Node 22.
- `uv`, `npm`, and `just` are available.

### 1.2. Check the package names before claiming anything

These checks are read-only:

```bash
npm view @mgiles/perk name version
```

Then open these pages in your browser:

- <https://pypi.org/project/perk/>
- <https://test.pypi.org/project/perk/>

Interpretation:

- If npm says `404 Not Found`, `@mgiles/perk` is not currently published. That is fine, but you
  still must control the npm `@mgiles` scope before publishing.
- If npm returns an existing package that is not yours, stop. Rename the npm package before
  releasing.
- If PyPI or TestPyPI already has a `perk` project that is not yours, stop. Rename the Python
  project before releasing.
- A PyPI pending publisher does not reserve the name. It only creates the project at first
  successful publish.

### 1.3. Create or verify the npm account and scope

The repo currently publishes `@mgiles/perk`, so you need an npm account that can publish under
the `@mgiles` scope.

In the npm website:

1. Create or log into the npm account that owns the `mgiles` user scope.
2. Enable two-factor authentication.
3. Confirm the account can publish packages under `@mgiles`.

If you cannot control the `@mgiles` scope, change `package.json` and all pinned package-name
references before cutting the first release. Do not publish a differently named package by
hand while the repo still says `@mgiles/perk`.

### 1.4. Create the npm automation token

The current workflow uses `NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}` for `npm publish`.

In npm:

1. Open your profile menu.
2. Go to **Access Tokens**.
3. Generate a new granular access token.
4. Give it read and write access to the `@mgiles` scope or the package once it exists.
5. Enable bypass for 2FA write actions if npm requires it for automation.
6. Set an expiration you can remember to rotate.
7. Copy the token immediately. npm will not show it again.

Then add it to GitHub:

1. Open `mattgiles/perk` on GitHub.
2. Go to **Settings -> Secrets and variables -> Actions**.
3. Add a repository secret named `NPM_TOKEN`.
4. Paste the npm token as the value.

Note: npm now supports trusted publishing through OIDC, which would remove this token. This
repo is not wired that way yet; switching npm to OIDC is a separate workflow change.

## 2. One-time setup: GitHub environments

The release workflow references three environments:

- `testpypi-publish`
- `pypi-publish`
- `npm-publish`

Create them in GitHub:

1. Open `mattgiles/perk`.
2. Go to **Settings -> Environments**.
3. Create `testpypi-publish`.
4. Create `pypi-publish`.
5. Create `npm-publish`.
6. Add required reviewers to each environment. For a solo repo, add yourself.

What these gates do:

- `testpypi-publish` approves a rehearsal upload to TestPyPI.
- `pypi-publish` approves the real PyPI upload.
- `npm-publish` approves the real npm upload.

The publish jobs will pause until the environment is approved. That is intentional.

## 3. One-time setup: PyPI trusted publishers

PyPI does not need an API token for this repo. GitHub Actions asks GitHub for a short-lived
OIDC identity, and PyPI accepts it only when the workflow identity matches the publisher
configuration.

### 3.1. TestPyPI pending publisher

Use TestPyPI first.

1. Create or log into a TestPyPI account.
2. Open account settings.
3. Open the publishing / trusted publishers area.
4. Add a pending GitHub Actions publisher.
5. Fill in:

```text
PyPI project name: perk
Owner: mattgiles
Repository name: perk
Workflow name: release.yml
Environment name: testpypi-publish
```

If TestPyPI says the project already exists, configure a normal trusted publisher on that
existing project instead, but only if you own it.

### 3.2. PyPI pending publisher

Repeat the same setup on production PyPI:

1. Create or log into a PyPI account.
2. Open account settings.
3. Open the publishing / trusted publishers area.
4. Add a pending GitHub Actions publisher.
5. Fill in:

```text
PyPI project name: perk
Owner: mattgiles
Repository name: perk
Workflow name: release.yml
Environment name: pypi-publish
```

If PyPI says the project already exists, configure a normal trusted publisher on that existing
project instead, but only if you own it.

## 4. Rehearse without publishing to production

Run the full local checks:

```bash
just ci
```

Build both publish surfaces locally:

```bash
rm -rf dist *.tgz
uv build
uvx twine check dist/*
wheel="$(ls dist/*.whl)"
uvx --from "$wheel" perk --help
npm pack --dry-run
```

Then run the TestPyPI rehearsal:

1. Open GitHub Actions.
2. Select the **Release** workflow.
3. Click **Run workflow**.
4. Run it from `main`.
5. Wait for `build-pypi` and `build-npm`.
6. Approve the `testpypi-publish` environment when prompted.
7. Confirm `publish-testpypi` succeeds.

This does not publish to production PyPI or npm. In this workflow, production publishes only
happen from a pushed `v*` tag.

## 5. Prepare a release PR

Pick the version.

For `0.x`, this repo's policy is:

- patch: fixes and docs only
- minor: may include breaking changes

Create a branch:

```bash
git switch main
git pull --ff-only
git switch -c release/vX.Y.Z
```

Bump the Python source of truth:

```bash
uv version X.Y.Z
```

Mirror it to npm:

```bash
npm version "$(uv version --short)" --no-git-tag-version
```

If your `uv` does not support `uv version --short`, read the version from `pyproject.toml`
and pass it to `npm version` manually.

Update `CHANGELOG.md` (the **two-phase changelog convention** — see
[releasing.md](./releasing.md#changelog-discipline) for the full convention):

1. Strip the parenthesized short-hash tokens from the released bullets (released sections carry no
   tokens).
2. Change `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`.
3. Add a fresh empty `## [Unreleased]` section above it **with a new `<!-- As of <hash> -->` marker
   at the release HEAD**.
4. Keep the existing change entries under the new release heading.

Run checks:

```bash
just ci
```

Open a normal release PR and merge it to `main`.

## 6. Tag the release

After the release PR is merged:

```bash
git switch main
git pull --ff-only
version="$(uv version --short)"
git tag -a "v${version}" -m "v${version}"
git push origin "v${version}"
```

The tag push starts `.github/workflows/release.yml`.

## 7. Approve the production release

Open the GitHub Actions run for the tag.

Expected order:

1. `validate-release-versions` checks the tag against `pyproject.toml` and `package.json`.
2. `build-pypi` builds the wheel and sdist, runs `twine check`, and smoke-tests `perk --help`.
3. `build-npm` runs `npm ci` and `npm pack`.
4. `publish-pypi` pauses for the `pypi-publish` environment.
5. `publish-npm` pauses for the `npm-publish` environment.
6. `github-release` creates the GitHub Release after both registries publish.

Approve `pypi-publish` only after the build jobs are green.
Approve `npm-publish` only after the build jobs are green.

Do not approve a publish job if `validate-release-versions` failed. Delete the bad tag, fix
the version mismatch, and tag again.

## 8. Verify the published release

After the workflow succeeds:

```bash
version="$(uv version --short)"
uvx --from "perk==${version}" perk --help
npm view "@mgiles/perk@${version}" name version repository
gh release view "v${version}" --repo mattgiles/perk
```

Then test a throwaway consumer repo:

```bash
tmp="$(mktemp -d)"
cd "$tmp"
git init
uv tool install "perk==${version}"
perk init
perk doctor
```

The important checks:

- `perk init` writes a pinned `npm:@mgiles/perk@X.Y.Z` entry.
- `.pi/npm/node_modules/@mgiles/perk/package.json` exists.
- `perk doctor` does not report extension-version drift.

## 9. If something fails

### Version validation failed

Cause: the pushed tag does not match `pyproject.toml` and `package.json`.

Fix:

```bash
git push origin ":refs/tags/vX.Y.Z"
git tag -d "vX.Y.Z"
```

Then fix the version files through a PR, merge, recreate the annotated tag, and push it again.

### PyPI trusted publishing failed

Check:

- PyPI project name is `perk`.
- GitHub owner is `mattgiles`.
- GitHub repository is `perk`.
- Workflow filename is `release.yml`, not `.github/workflows/release.yml`.
- Environment is exactly `pypi-publish` for production or `testpypi-publish` for rehearsal.
- The GitHub job has `permissions: id-token: write`.

The workflow already has the required `id-token: write`; most failures here are mismatched
publisher fields or approving the wrong environment.

### npm publish failed

Check:

- The `NPM_TOKEN` repository secret exists.
- The token has read and write access to the `@mgiles` scope or package.
- The token can bypass 2FA for write actions if your npm account requires it.
- The package is still named `@mgiles/perk`.
- The workflow is publishing with `npm publish --provenance --access public`.

For the first scoped public publish, `--access public` is required.

### PyPI published but npm failed, or npm published but PyPI failed

This is the awkward case. You may have one registry with `X.Y.Z` and the other without it.

Do not bump a new version unless you intentionally want to abandon `X.Y.Z` on one registry.
First fix the failing registry configuration, then rerun the failed GitHub Actions job for the
same tag if GitHub allows it. If rerun is not enough, push a no-op workflow rerun only after
understanding which registry already accepted the version.

Package registries generally do not allow overwriting an existing version. Treat a partial
publish as a release incident and keep notes in the GitHub Release or a follow-up issue.

## 10. Official references

- PyPI trusted publishers: <https://docs.pypi.org/trusted-publishers/>
- PyPI pending publishers: <https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/>
- PyPI publishing with GitHub Actions: <https://docs.pypi.org/trusted-publishers/using-a-publisher/>
- npm scoped public packages: <https://docs.npmjs.com/creating-and-publishing-scoped-public-packages/>
- npm access tokens: <https://docs.npmjs.com/about-access-tokens/>
- npm trusted publishing, for a future tokenless npm workflow: <https://docs.npmjs.com/trusted-publishers/>
- GitHub environments: <https://docs.github.com/actions/deployment/targeting-different-environments/using-environments-for-deployment>
