# Changelog

All notable changes to perk are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

<!-- As of 5004ced -->

## [2.0.0] - 2026-07-10

### Major Changes

- **Breaking: config schema v2.** `.perk/config.toml` was restructured from first principles — every top-level header answers one operator question, types are honest (native booleans/floats), and model precedence is visible as nesting. **No migration tooling, no dual-read:** legacy spellings hard-fail every `perk` command with a pointer to the new home. Overlay semantics are unchanged per knob (committed-converged keys ignore `.perk/local.toml`; runtime-read keys honor it). Rename map below.

  | Old | New |
  | --- | --- |
  | `[models] model = "…"` | `[models] default = "…"` |
  | `[stages.<id>]` | `[models.stages.<id>]` |
  | `[subagents]` | `[models.subagents]` |
  | `[[ci]]` | `[[ci.checks]]` |
  | `[trust] ci = "true"` | `[ci] trusted = true` (native boolean) |
  | `[objective] compact_threshold = "0.8"` | `[compaction] objective_threshold = 0.8` (native float) |

### Added

- New PR-review doors: `/pr-review-terminal` opens the hunk terminal TUI and streams reviewer findings as they arrive; `/pr-review-browser` launches plannotator's browser UI in the background, where native platform posting is the default GitHub path. `/pr-review-browser` also absorbs `/pr-review-local`'s since-base review mode.
- Layered skill exposure for cold stage launches. Declare a skill's target stages in SKILL.md frontmatter or `[skills.stages]`, optionally add directories or package skills, and keep bound skills available to their bound stages; repos that do not opt in retain pi's existing skill discovery.
- Interactive transcripts now show durable, display-only markers for perk workflow events such as run claims, mode changes, checkpoint progress, and `/btw` exchanges.
- The interactive perk footer now displays the prompt cache-hit rate once cache activity is available.

### Changed

- The ambient-prose diet: the managed AGENTS.md block shrinks to its three consumer-relevant conventions (re-run `perk init` to reconverge), and perk's injected context blocks (read-only mode, plan/objective authoring, adapter bridges) are rewritten tersely — the read-only block no longer enumerates the allowlisted tool names (the gated active-tool set already is that list).
- The skill-binding nudge is no longer double-delivered on cold stage launches: the warm injector now also checks the submitting turn's prompt for the delivery header (at `before_agent_start` the launch prompt is not yet on the branch, so the branch-scan dedup missed it).
- Stage scoping now covers borrowed-package tools: an enumerated census (`BORROWED_TOOLS` — the web-provider union, pi-mono-linear's 25 tools, pi-subagents' delegation family, `todo`, `plannotator_submit_plan`) joins perk's own tools in the gate-off per-stage filter — research tools (web + Linear reads) stay universal, delegation (`subagent`/`wait`) and `todo` ride only the worktree stages, and Linear's 6 mutating tools plus plannotator's submit tool leave every stage session (bare sessions, un-enumerated foreign names, and the read-only gate's allowlist are unchanged).
- TS provider resolution is hardened against catalog version skew: a seam with no `default: true` entry in the bundled catalog now resolves to a synthesized built-in reference with a loud issue instead of throwing — one seam's catalog gap can no longer silently collapse another seam's resolution (the plannotator plan_review no-launch incident) — and the four resolution fallback catches log the swallowed error to the session log.
- Read-only sessions can now run `gh search code …`: the destructive editor veto for `code` is command-position-anchored instead of matching the word anywhere in the command.
- Stage sessions now expose only their stage's perk tools to the model when read-write: an extension-owned per-stage active-tool map (`STAGE_TOOLS`) applied at the `session_start`/`session_tree` rebuild points drops e.g. the 8 authoring-tool schemas from every worktree-stage session (the five worktree stages share one PR-loop family; the read-only gate's allowlist, builtins, and borrowed-package tools are unchanged; sessions with no or an unknown stage keep everything).
- `/review` and the `[providers]` review seam are retired — the surface-named doors ARE the selection (`/pr-review-terminal` = hunk, `/pr-review-browser` = plannotator); a leftover `review` key in `[providers]` now hard-fails config load with a pointer to the doors. The `open_plannotator_review` tool is deleted, `submit_pr_review` re-homes to its own door module with an unchanged contract, and the `perk-review` skill splits into `perk-pr-review-terminal` / `perk-pr-review-browser`.
- `perk learn docs-check` now fails (exit 1) on any `docs/learned` `read_when` cue over 200 chars or carrying a YAML plain-scalar hazard (` #` silent truncation, `: ` parse failure, multi-line), and a pytest enforces the same cue budget in CI; freshness stays on-demand only.
- The foreign-PR reviewer agent `perk.guest-reviewer` is renamed `perk.adversarial-reviewer` (re-scoped to any PR — the untrusted posture is the default; the `[models.subagents]` key renames with it and an old `guest-reviewer` key is now silently ignored).
- pi-subagents' builtin agents are now disabled in every perk repo: `perk init` / `perk doctor --fix` converge the constant `subagents.disableBuiltins: true` into the managed `.pi/settings.json` slice (engine-only borrow — perk ships its own `perk.*` agents); re-enable one builtin via a project-settings per-agent `agentOverrides.<name>.disabled: false` entry, which the merge never touches.
- Read-only (gated) sessions can now delegate to subagents: the pi-subagents family (`subagent`/`wait` + the supervisor pair) joins the read-only allowlist so the gated `/objective-plan` explorer spawn works as documented — a deliberate leniency with no agent allowlist (spawned children run per their own agent definitions and are not gate-restricted).
- `perk plan replan` and both `perk plan from` flows now save through `plan_review` approval; `/plan-save` remains the manual fallback when review is skipped.
- Worktree setup hooks now keep successful command output out of launch narration and replay the full output only when a hook fails.
- `perk worktree wipe` now also removes unregistered residue `plan-*` directories and merged stranded `plan-*` branches, while preserving real or unmerged worktrees and branches.
- Adding a non-terminal node to a closed objective now reopens that objective automatically, except for superseded objectives.
- Landing a learn-docs consolidation plan now skips the pending-learn marker and follow-up learn pass, so its worktree is immediately releasable.

### Fixed

- Worktree stage scoping no longer strips the objective-reconcile tools: `reconcile_objective`, `add_objective_node`, and `objective_node` ride the shared worktree family (the post-land auto-reconcile drive and the manual `/objective-reconcile` land in worktree sessions), `objective_node` joins the objective-author/save stages, and a drive-coverage guard test pins every warm-door drive's named tools active in every stage the drive can land in.
- `perk init` and `perk doctor --fix` now preserve pi's object-form package entries and their per-project resource filters instead of re-adding duplicate package entries; `perk doctor` warns when an override disables perk's own resources.
- Remote stage drives now synchronize declared skills into the runner checkout and fail clearly if that delivery cannot complete.
- A corrupt local workflow cache no longer prevents a read-only session from engaging its safety gate; the session reports the cache problem instead.
- CI results shown to in-session workflows now retain the trailing failure output, where test and compiler summaries typically appear.

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
