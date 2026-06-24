# Changelog

All notable changes to perk are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- PyPI release automation: a tag-gated `publish-pypi` job (OIDC trusted publishing via
  `pypa/gh-action-pypi-publish`, `pypi-publish` environment gate), an always-on PyPI
  build/check/smoke job, and a `workflow_dispatch` TestPyPI rehearsal in `release.yml`.
- npm release automation: an always-on `build-npm` job (`npm ci` + `npm pack` + tarball artifact),
  a tag-gated `publish-npm` job (`npm publish --provenance --access public`, `NPM_TOKEN` auth behind
  the `npm-publish` environment), and a `github-release` capstone (GitHub Release with auto-generated
  notes once both planes publish) in `release.yml`. Adds `repository`/`homepage`/`bugs` to
  `package.json` (npm provenance requires `repository.url`).

### Changed

### Fixed

---

`0.0.1` is the current unreleased baseline — there is no published release section yet. See
[docs/releasing.md](docs/releasing.md) for the release policy + runbook.
