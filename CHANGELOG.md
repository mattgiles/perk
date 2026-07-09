# Changelog

All notable changes to perk are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

<!-- As of 6d7816b -->

### Major Changes

- **Breaking: config schema v2.** `.perk/config.toml` was restructured from first principles — every top-level header answers one operator question, types are honest (native booleans/floats), and model precedence is visible as nesting. **No migration tooling, no dual-read:** legacy spellings hard-fail every `perk` command with a pointer to the new home. Overlay semantics are unchanged per knob (committed-converged keys ignore `.perk/local.toml`; runtime-read keys honor it). Rename map below. (e67c9ce)

  | Old | New |
  | --- | --- |
  | `[models] model = "…"` | `[models] default = "…"` |
  | `[stages.<id>]` | `[models.stages.<id>]` |
  | `[subagents]` | `[models.subagents]` |
  | `[[ci]]` | `[[ci.checks]]` |
  | `[trust] ci = "true"` | `[ci] trusted = true` (native boolean) |
  | `[objective] compact_threshold = "0.8"` | `[compaction] objective_threshold = 0.8` (native float) |

### Changed

- `perk learn docs-check` now fails (exit 1) on any `docs/learned` `read_when` cue over 200 chars or carrying a YAML plain-scalar hazard (` #` silent truncation, `: ` parse failure, multi-line), and a pytest enforces the same cue budget in CI; freshness stays on-demand only. (e0f464e)
- pi-subagents' builtin agents are now disabled in every perk repo: `perk init` / `perk doctor --fix` converge the constant `subagents.disableBuiltins: true` into the managed `.pi/settings.json` slice (engine-only borrow — perk ships its own `perk.*` agents); re-enable one builtin via a project-settings per-agent `agentOverrides.<name>.disabled: false` entry, which the merge never touches. (1c7953d)

## [1.1.0] - 2026-07-04

### Major Changes

- **Remote-runner reliability and observability.** perk now treats GitHub Actions runs as the canonical record for dispatched stages, loads the same managed extension package set in headless workers, preserves run diagnostics, and handles fresh-plan remote implements. This makes remote runs discoverable and controllable from any checkout instead of depending on the dispatching machine's local cache.

### Added

- Record managed artifact hashes during `perk init` and `perk doctor --fix`, and add a report-only `doctor` artifact-health view that distinguishes up-to-date, locally-modified, changed-upstream, missing-state, and not-installed managed pieces.
- Add `perk release-notes` plus upgrade-awareness surfaces: the managed `.perk/required-perk-version` pin, soft CLI-vs-repo version warnings, a report-only doctor check, and a one-line post-upgrade notice pointing to the bundled changelog.
- Add canonical plan-header `learn_state` tracking and `perk learn skip`, so post-merge learn/capture/skip state is visible from any machine instead of relying only on local pending-learn markers.
- Add `/implement-here`, a human-only plan-mode exit that turns off read-only mode and implements the reviewed draft in the current checkout without saving an issue.

### Changed

- Make `perk plan resume` and `perk objective run` share one next-action classifier, reporting draft, awaiting-review, closed, and done gates instead of relaunching the wrong stage and exposing the verdict as `next_action` in JSON.
- Improve cold-door narration: launch banners now appear before lookup/gather output, and long-running CLI I/O renders as explicit start/done/warn progress lines.

### Fixed

- Allow warm `/objective-plan` sessions to call `objective_node` while read-only so saved plans keep their objective-node backlink.

## [1.0.1] - 2026-06-24

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

See [docs/releasing.md](docs/releasing.md) for the release policy, runbook, and the two-phase
changelog convention.
