# Changelog

All notable changes to perk are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

<!-- As of 5ad2afa -->

### Added

- `run_harvest_wave` — the flow-scoped harvest analyst wave: inside a `perk learn harvest` session the tool fans one read-only `perk.harvest-analyst` lane per manifest lane over the run's harvest manifest (multi-lane manifests only — a single-lane manifest is refused toward direct in-session analysis) and returns per-lane ranked opportunities (≤ 5 + `omitted_count`) with each pointer stamped `pointer_status: resolved/unresolved`; the `manifest_path` argument is structurally bound to the session's claimed run-scoped manifest (any other path refused), the manifest is strictly re-validated — including resolved-symlink `docs/learned/` containment — before any spawn, and a failed lane is an explicitly-reported skip (best-effort, one attempt, no retry) (9e51f253)
- `perk learn harvest` — the objective-factory cold door that mines `docs/learned/` as lenses into the code: it fast-forwards the invocation checkout when it cleanly can (a guarded, best-effort sync), gathers the selected docs into a run-scoped versioned manifest (`commit_sha` = HEAD at gather time), and launches a read-only objective-authoring session that grounds every mined opportunity and curates ONE bounded improvement objective (a single-lane selection is analyzed directly in-session; a multi-lane selection fans through the `run_harvest_wave` analyst wave, with failed lanes reported honestly — no retry — and a failed or report-less wave surfaced as an incomplete harvest recommending a bounded `--from` re-run; ≤ 8 roadmap nodes, backlog-with-reasons, honest zero-opportunity stop) (b05e3699)
- The stacked-delivery recovery & control surface (contracts §8.49/§8.51): `perk objective stack sync` grows `--dry-run` (a side-effect-free cascade preview), `--adopt NODE` (accept one layer's manually-pushed remote head and cascade above it, refused as `adopt_blocked` when there is nothing safe to adopt), and `--continue`/`--abort` (resume a human-resolved rebase conflict under the interrupted operation's identity, or discard the retained continuation behind a confirmation that names exactly what will be deleted); the new `perk objective stack recover` concludes unresolved operations (fresh-authority classification, deterministic all-after roll-forward, confirmed abandon-with-proof) and sweeps orphaned sync residue (manifest-protected, fail-safe on any unparseable manifest); `stack status` reports every unresolved operation, the pending continuation, and an honest orphaned-residue observation; and the warm surface lands as `/objective-stack`, `/objective-sync`, `/objective-recover` plus the four typed `objective_stack_*` tools (preview-first, consent-gated, soft-refused in read-only sessions) (85e4809a)
- `perk objective stack sync` — published-suffix synchronization for stacked delivery trains (contracts §8.49): after amending a published layer's branch (or when the objective base advances — `--base`), the transactional cascade rewrites every published successor from the lowest change upward — candidates computed by rebase in an isolated disposable worktree (user branches/worktrees never move), the rendered cascade confirmed on stderr (`--yes` auto-approves; non-interactive without it refuses), journaled first, pushed as ONE atomic multi-ref push under exact per-ref leases, verified with a bounded PR settle poll, and checkpointed bottom→top; drift/dirty-worktree/active-remote-writer preflights refuse before anything moves, a mid-cascade rebase conflict is retained under a lineage-keyed continuation manifest (fresh syncs refuse until it is cleared), and `stack status` now reports the live base observation (`observed_base_head_sha` + `base_advanced`/`base_unobserved` notices) (3b8d839a)
- Stacked delivery is now a supported authoring choice: `perk objective create --delivery stacked` / the reviewed `objective_draft` choice save and publish without any development opt-in — the live three-layer publication dogfood gate passed (native stack create AND append proven end-to-end; evidence in `docs/design/stacked-publication-dogfood.md`), so the temporary `PERK_DEV_STACKED_DELIVERY=1` write gate and its `stacked_delivery_gated` refusals are removed; incremental stays the recommended default, and the docs state stacked's explicit limitations (no published-suffix sync or atomic landing yet — never land stacked layers individually) (43c2d4c0)
- Stacked plans now publish through `/submit`: a plan carrying a `delivery_lineage` routes `perk pr submit` into the delivery module's new publish operation (contracts §8.47) — exact-lease branch publication, a draft PR opened/converged onto the parent layer's branch, native stack create/append with prepared-operation idempotency (one bounded retry, `Retry-After` honored), a full remote postcondition refetch, and the plan-header checkpoint pair written only after verification; failures leave a recoverable journal operation that a re-run resumes/rolls forward, the top published layer supports republish/no-op convergence, and the `--json` envelope gains additive `delivery`/`stack`/`operation_id` fields (null on incremental — the incremental path is byte-identical) (c502e290)
- `run_ci` now streams a live one-line progress indicator while checks run — per-check `✓`/`✗`/`⊘`/`…` glyphs in declared order plus a ticking elapsed-seconds counter, replaced in place on the tool row via pi's partial-result channel (UI-only; the deterministic final report is unchanged and supersedes it) (e69388aa)
- `/objective-review-browser`: the streaming browser review of the working objective draft — from an objective-authoring session the human summons a plannotator plan-review browser on the RENDERED draft (prose + Delivery line + roadmap table), the 2–3-angle draft-reviewer wave (plus an optional custom lane defined by the door argument) streams phrase-anchored findings in via `push_annotations`, and the browser decision routes back automatically (APPROVE auto-saves the objective behind a stale guard on the raw structured artifact bytes; browser Direct Edits are never auto-applied — they return as an `objective_draft` revise round; DENY returns the feedback for an `objective_draft` revision round) (bc7e736b)
- `/plan-review-browser`: the summonable streaming draft review — from a plan-authoring session the human summons a plannotator plan-review browser on the working plan draft, a 2–3-angle draft-reviewer wave (plus an optional custom lane defined by the door argument) streams phrase-anchored findings into the browser via `push_annotations`, and the browser decision routes back automatically (APPROVE auto-saves through the normal pipeline with Direct Edits mechanically applied; DENY returns the feedback for a `plan_draft` revision round); the companion `start_draft_review_wave`/`collect_draft_review_wave` tools review the door-primed draft only — the model picks angles but can never substitute the reviewed bytes (363f3115)

### Changed

- Stacked delivery now converges through the ordinary PR loop: `/submit` automatically propagates a committed published-layer rewrite through its verified successor suffix, `/address` publishes before resolving review threads through the single `finalize_address` tool, `/ready` refuses structurally unsafe or unresolved trains, and the objective supervisor prioritizes repair plus lowest-layer actionable feedback before upper work; explicit stack sync remains the control surface for base advancement, adoption, preview, continuation, and operator repair (e28d14a1)
- A green run-all `run_ci` is now the definitive validation signal: the green report is scope-aware — a run-all closes with a terminal `Full gate green` line (no follow-up re-verification; glob-skipped checks disclosed as intentionally out of scope for the diff) while a green subset run reports `selected checks passed` and points at the run-all as the full gate — the tool guidance names `run_ci` canonical for check-level verification (narrow direct commands stay fine while iterating), and the implement launch prompt gains a Validation paragraph teaching the discipline: verify as you work, finish with ONE run-all `run_ci`, then commit and go straight to `/submit` (fe591fc2)
- The shared PR-review angle menu grows to seven fixed angles — **api-design** (API & interface design elegance), **code-organization** (code organization & repository design), and **idioms** (idiomatic language usage) join plan-fidelity/correctness/tests/quality — and both review flows widen to 2–4 lanes: `/pr-review` accepts 2–4 parent-picked angles, and `/pr-review-dynamic` caps at 3 selector-picked additional angles (`force_angles` 1–3) and now lets the selector propose at most ONE change-specific custom angle, structurally constrained in module code (validated kebab-case slug, whitespace-collapsed ≤300-char scope entering one reviewer task through a fixed scope-definition-only template, report schema locked to echo the custom slug; invalid proposals degrade to no-custom) (ed3faba6)
- `run_ci` / `/ci` now run the configured `[[ci.checks]]` concurrently (wall time drops from the sum of check durations to the max) while results still report in declared order — each row must be independently runnable (put an ordered sequence inside one row's `command`, e.g. `"build && test"`) — and the `check` argument accepts a comma-separated list of names to re-verify a failed subset in one call (d82f7e1f)
- The two human review doors' (`/pr-review-terminal`, `/pr-review-browser`) reviewer fan-out and the browser annotation delivery are now code-owned flow tools: ONE `start_review_wave` launch + `collect_review_wave`'s typed aggregate replace the model-authored workflowScript skeleton and the `status.json` read-back, `push_annotations` (door-primed; refuses outside a door-opened flow) replaces the curl annotation cheat sheet, and the adversarial-reviewer completes via the engine-injected `structured_output` call instead of a fenced-JSON block; operator-visible behavior (args, modes, posting) is unchanged (ad673358)
- The materialized plan body is repurposed as the per-worktree plan snapshot for review fidelity: launch narration warns now say `plan snapshot:` (was `checkpoints:`), and the extension's dead plan-body reader is removed (Python remains writer + reader) (86db2f25)
- The implement stage now teaches the todo checklist discipline: the plan's `## Steps` list seeds a dynamic, model-owned checklist kept live with the `todo` tool (prose plans: the implementer derives its own short checklist); the perk footer/status shows the objective segment only (d6eee90a)
- The todo checklist overlay is now built-in: `@juicesharp/rpiv-todo` becomes a required borrowed package installed for every repo (perk's checkpoints keep running alongside it; their removal is a separate change) (1ab7fa6)
- `ask_user_question` is now the built-in juicesharp questionnaire: `@juicesharp/rpiv-ask-user-question` becomes a required borrowed package installed for every repo, providing structured 1–4-question questionnaires with options, `multiSelect`, and per-option previews; headless sessions no longer carry the tool at all (the first-party no-user sentinel is gone — the package strips the tool when there is no interactive UI) (7816658)

### Removed

- perk checkpoints: `/checkpoints`, the `[WIP:n]`/`[DONE:n]` marker protocol, the generated-checklist machinery, the 📋 footer segment and standing widget, and the `perk:checkpoint` transcript marker — historical entries render as generic custom entries (14205bc7)
- The headless worker no longer emits `step_marker` run events (the marker scanning died with checkpoints); the `RunEvent` union keeps the variant deprecated so historical `events.ndjson` files still parse; accepted loss: headless runs have no granular per-step progress signal (cbd85c54)
- The `todo` provider seam and the `juicesharp-todo` adapter: the seam is retired to the required borrow above, and a leftover `[providers] todo` key now hard-fails config load with removal guidance (the TS plane silently ignores it) (1ab7fa6)
- The first-party `ask_user_question` tool and the `askuser` provider seam: the seam is retired to the required borrow above, and a leftover `[providers] askuser` key now hard-fails config load with removal guidance (the TS plane silently ignores it) (7816658)

### Fixed

- `perk plan save` now refuses a node-linked same-run-id re-save whose stored plan header names a *different* objective node (`error_type: node_conflict`, fail closed before any mutation) — previously a scripted node-linked save reusing the ambient workflow run ID silently rewrote the previous node's plan in place while the command succeeded; mint a fresh run ID per node (254bcbd1)
- The `/learn` evidence pipeline no longer crashes with a `UnicodeEncodeError` traceback when a session transcript or backend-fetched plan body/diff carries an escaped lone surrogate (e.g. `\ud800`) — session/backend-derived text is sanitized at compose time (the surrogate degrades to one replacement character, never the artifact) (82d14787)
- A malformed stored `shared/` YAML file (`bindings.yaml`/`registry.yaml`/`providers.yaml`) now fails as the loader's domain error with the file path in the message (was a leaked `yaml.YAMLError` traceback), and each loader's `schema_version` gate rejects YAML `true`/`1.0` instead of accepting them through loose int equality (91255642)
- The read-only gate no longer strips pi-subagents' engine-injected child-side tools (`structured_output`/`contact_supervisor`/`subagent_wait`) in spawned children that inherit read-only mode — previously the objective-plan explorer child completed its exploration and then failed with `Missing structured_output call` (c299566f)

## [2.3.0] - 2026-08-08

### Major Changes

- **pi-subagents v1 orchestration.** Every delegated workflow now uses pi-subagents' `workflowScript`-only API: `/pr-review`, `/pr-review-dynamic`, and `/learn` run code-owned, schema-validated report waves; `/address`, objective exploration, and conflict resolution use explicit foreground workflows; and the human review surfaces retain async streaming. This restores compatibility with the removed direct and `tasks[]` execution APIs, makes child failures explicit, and prevents incomplete review coverage from producing a clean verdict.

### Added

- `/pr-review-dynamic` (experimental): the selector-driven sibling of `/pr-review` — ONE perk-rendered workflow runs the mandatory plan-fidelity reviewer concurrently with a fresh `perk.review-angle-selector` lane, normalizes the selection deterministically in module-rendered code (allowlist filter, dedupe, operator `force_angles` first, 2-additional cap, correctness+tests fallback), fans out the selected reviewers in the same workflow (reviewers never see the selector's output), and applies the same one bounded retry; reconciliation and posting share `post_pr_review` and its clean guard, models ride the `[models.subagents] pr-reviewer` + `review-angle-selector` keys per-lane, and the baseline `/pr-review` is unchanged and canonical
- `perk doctor`: new informational `subagent-compat` check (`package` group) — reports the installed pi-subagents version and probes the installed source for the orchestration surfaces perk's guidance assumes (`workflowScript`, `outputSchema` → `structuredOutput`, `subagent_wait`, the supervisor channel, workflowScript-only execution, and the v1 RPC); `info` when the package is not installed, a loud warn (never a fail) on divergence, no `--fix` arm — pi-subagents stays unpinned
- Perk-launched sessions now borrow `@ff-labs/pi-fff` for pre-indexed, frecency-ranked local search: FFF-backed `find`/`grep` run in override mode by default, the additional search tools remain available across stages and read-only exploration, and `PI_FFF_MODE` can override the default.

### Changed

- `/pr-review`: the reviewer fan-out now runs as one code-owned pi-subagents `workflowScript` report wave over the v1 RPC — stable per-angle keys, the `[models.subagents] pr-reviewer` model applied to every lane, engine-validated structured reports (`outputSchema`) replacing fenced-JSON scraping, and a strict completeness policy (a failed required angle gets one targeted retry, then the review is incomplete — never a clean verdict from partial coverage); parent reconciliation and the single `post_pr_review` post are unchanged
- `/learn`: the multi-angle analyst fan-out now runs through the code-owned `run_learn_wave` report wave with engine-validated structured reports; failed analysts are surfaced as explicitly skipped angles rather than failing or silently weakening the pass.
- `/address`, optional objective-plan exploration, and `/submit` conflict resolution now use explicit-return foreground `workflowScript` runs instead of the removed direct child-execution API; the two read-only report flows also use engine-validated structured output rather than fenced-JSON parsing.
- `perk init` and `perk doctor --fix` now seed pi's experimental fullscreen TUI mode into `.pi/settings.json` when `tuiMode` is absent; any existing value is preserved, so committing `"tuiMode": "regular"` remains a durable opt-out.

### Fixed

- `/pr-review-terminal` / `/pr-review-browser`: the reviewer fan-out now launches one async pi-subagents `workflowScript` (all-settled `runs.all`, stable angle keys) with completion reports retrieved from the run's `status.json` — the grouped `tasks[]` shape those doors previously instructed was removed upstream (pi-subagents 0.41.0–0.42.1) and had broken both doors; the `subagent_wait` streaming relay, dedupe ledger, and human-owned triage/posting are unchanged

## [2.2.0] - 2026-08-06

### Major Changes

- **Gists: lightweight statements of intent.** Capture plan- or objective-sized ideas in GitHub or Linear before they deserve a full planning session, review and save them through a read-only authoring flow, list the unconsumed backlog, and later adopt each gist in place as a plan or objective. This keeps worthwhile intent durable without prematurely committing to implementation details.

### Added

- `/commit-and-compact`: New human-only warm command available in every perk session — drives one model turn to commit the work completed so far (real staging judgment + a real commit message), then compacts the session with instructions referencing the new commit(s) once HEAD has actually advanced; clean-tree and read-only sessions compact immediately, and an undeterminable git state or a no-commit turn skips compaction with a loud warning naming pi's `/compact` (never compact away uncommitted work)
- Plannotator: Honor the browser review's **Direct Edits** — an approved plan review now auto-applies the reviewer's `# Direct Edits` diff to the draft and saves the edited bytes (falling back to a verbatim save plus a loud warning when the diff cannot be applied); an approved objective review carrying direct edits skips the save and routes one `objective_draft` fold-in + confirming re-review; denials keep handing the diff to the agent as feedback

## [2.1.0] - 2026-07-13

### Major Changes

- Linear: **Native metadata attachments.** Plan, learn, and objective bookkeeping now lives in native issue attachments instead of descriptions and project overviews, keeping human-facing prose clean and enabling direct cross-machine lookup. This is a clean break: artifacts written by earlier perk versions must be re-saved or recreated.

### Added

- Add perk-owned `perk-grill` and `perk-domain-modeling` skills, making one-question-at-a-time pre-review stress testing and domain-model capture part of plan and objective authoring

### Fixed

- Linear: Anchor `[issues]` backend selection to the main checkout so detached or stale linked worktrees cannot silently switch canonical writes to GitHub

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
