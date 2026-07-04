# Release Checklist

This is the **one-time publishing setup** a maintainer performs once — accounts, package names,
the npm scope + token, GitHub environments, PyPI/TestPyPI trusted publishers — plus the
**pre-release rehearsal**. Recurring releases live in
[releasing.md → Release runbook](./releasing.md#release-runbook-coordinated-dual-plane).

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

The Python CLI is published as `perk` on PyPI (`uv tool install perk`). The Pi extension is
published as `@mgiles/perk` on npm — a consumer repo does not install it by hand: `perk init`
writes a version-pinned `npm:@mgiles/perk@X.Y.Z` entry and `perk init` / `perk doctor --fix`
install that package under `.pi/npm/`.

The source version lives in `pyproject.toml`; the npm version in `package.json` must mirror it.
The tests enforce that parity, and the release workflow checks that the git tag matches both
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

The repo publishes `@mgiles/perk`, so you need an npm account that can publish under the
`@mgiles` scope.

In the npm website:

1. Create or log into the npm account that owns the `mgiles` user scope.
2. Enable two-factor authentication.
3. Confirm the account can publish packages under `@mgiles`.

If you cannot control the `@mgiles` scope, change `package.json` and all pinned package-name
references before cutting the first release. Do not publish a differently named package by
hand while the repo still says `@mgiles/perk`.

### 1.4. Create the npm automation token

The workflow uses `NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}` for `npm publish`.

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

When `publish-npm` later fails auth (`E401`/`ENEEDAUTH`), the usual causes are a token missing
read+write access to the `@mgiles` scope or a token that cannot bypass 2FA for write actions —
re-verify both whenever you rotate the token.

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

Two details that matter when filling in the publisher fields:

- The workflow name is the bare filename `release.yml`, **not** `.github/workflows/release.yml`.
- The workflow's publish jobs already carry the required `permissions: id-token: write`; an
  OIDC invalid-publisher failure almost always means mismatched publisher fields or approving
  the wrong environment.

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

Run the one-shot publication preflight:

```bash
just publish-check
```

`just publish-check` composes the release-state judgment and the local build rehearsal, plus a
`gh auth status` check and a best-effort origin probe for the `v{version}` tag (add
`--allow-dirty` to skip the clean-tree requirement while rehearsing) — see
[releasing.md → Release runbook](./releasing.md#release-runbook-coordinated-dual-plane) step 2
for the full description. The granular pieces remain runnable on their own:

```bash
just release-check
just release-build
```

`just release-check` structurally validates the changelog, the version lockstep, and local tag
agreement (add `--for-publish` to also require a clean tree). `just release-build` runs the
literal build steps in a temp dir — `uv build --package perk`, `twine check`, a `perk --help`
smoke from the built wheel, then `npm ci` and `npm pack --dry-run` with a tarball file check —
without publishing anything or touching your `dist/`.

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

## 5. Recurring releases

With the setup above complete, every release — including the first — follows
[releasing.md → Release runbook](./releasing.md#release-runbook-coordinated-dual-plane): bump +
roll (`perk-dev bump-version`), verify locally (`just publish-check`), land the release PR, tag
(`perk-dev release-tag --push`), approve the environment gates in order, and verify the
published release. When anything fails, go to
[releasing.md → Incident handling](./releasing.md#incident-handling) — symptom → state check →
recovery for the named scenarios.

## 6. Official references

- PyPI trusted publishers: <https://docs.pypi.org/trusted-publishers/>
- PyPI pending publishers: <https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/>
- PyPI publishing with GitHub Actions: <https://docs.pypi.org/trusted-publishers/using-a-publisher/>
- npm scoped public packages: <https://docs.npmjs.com/creating-and-publishing-scoped-public-packages/>
- npm access tokens: <https://docs.npmjs.com/about-access-tokens/>
- npm trusted publishing, for a future tokenless npm workflow: <https://docs.npmjs.com/trusted-publishers/>
- GitHub environments: <https://docs.github.com/actions/deployment/targeting-different-environments/using-environments-for-deployment>
