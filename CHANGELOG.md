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

- Stage sessions now expose only their stage's perk tools to the model when read-write: an extension-owned per-stage active-tool map (`STAGE_TOOLS`) applied at the `session_start`/`session_tree` rebuild points drops e.g. the 8 authoring-tool schemas from every worktree-stage session (the five worktree stages share one PR-loop family; the read-only gate's allowlist, builtins, and borrowed-package tools are unchanged; sessions with no or an unknown stage keep everything). (bcebf51)
- `/review` and the `[providers]` review seam are retired — the surface-named doors ARE the selection (`/pr-review-terminal` = hunk, `/pr-review-browser` = plannotator); a leftover `review` key in `[providers]` now hard-fails config load with a pointer to the doors. The `open_plannotator_review` tool is deleted, `submit_pr_review` re-homes to its own door module with an unchanged contract, and the `perk-review` skill splits into `perk-pr-review-terminal` / `perk-pr-review-browser`. (1fafa93)
- New warm `/pr-review-browser` door — human-in-the-loop adversarial PR review on plannotator's browser UI with `/pr-review-terminal`'s arg semantics: the browser opens in the background (the session stays free while you review), reviewers fan out async and stream per-angle annotation waves into the live browser session, and **the posting flips** — plannotator's native platform-posting is now THE GitHub path (perk composes nothing by default; `submit_pr_review` only for a request-changes verdict or on explicit request, the read-back/dedupe contract deleted). `/pr-review-local` retires — its pre-PR since-base browser review is absorbed as the new door's no-PR mode. (0e168d4)
- `perk learn docs-check` now fails (exit 1) on any `docs/learned` `read_when` cue over 200 chars or carrying a YAML plain-scalar hazard (` #` silent truncation, `: ` parse failure, multi-line), and a pytest enforces the same cue budget in CI; freshness stays on-demand only. (e0f464e)
- The foreign-PR reviewer agent `perk.guest-reviewer` is renamed `perk.adversarial-reviewer` (re-scoped to any PR — the untrusted posture is the default; the `[models.subagents]` key renames with it and an old `guest-reviewer` key is now silently ignored), and `/pr-review-terminal` now streams findings live: reviewers fan out async and each finding batch is pushed into the hunk session as it arrives, with the final reports reconciled as the source of truth. (1a902a6)
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
