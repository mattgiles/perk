# pi adoption audit — 0.80.4+ against perk's pi surface

An inventory-driven audit of every pi API surface perk touches, an in-depth evaluation of the
pi 0.80.4 feature set, and a back-scan of 0.79.0 → 0.80.3 for already-shipped-but-unadopted
features that map to known perk pain points. Every item ends in a verdict —
**adopt-now / adopt-later / decline** — with rationale and an implementation sketch, so each
adopt verdict can be lifted directly into a follow-up perk plan.

Verdicts are recommendations to the human, not commitments; follow-up plans re-validate before
implementing.

- [§0 Scope & version baseline](#0-scope--version-baseline)
- [§1 Usage inventory — perk's pi surface today](#1-usage-inventory--perks-pi-surface-today)
- [§2 pi 0.80.4 feature evaluations](#2-pi-0804-feature-evaluations)
- [§3 Back-scan: unadopted 0.79.0 → 0.80.3 features](#3-back-scan-unadopted-0790--0803-features)
- [§4 Recommendations](#4-recommendations)

## §0 Scope & version baseline

- **Audited pi version: 0.80.5** — the freshly pinned repo devDeps (`@earendil-works/pi-ai` +
  `@earendil-works/pi-coding-agent`, bumped in lockstep from 0.80.3). Every pi-side claim below
  was verified against the repo's own pinned dist
  (`node_modules/@earendil-works/pi-coding-agent/…` @ 0.80.5) or its bundled `docs/`, not the
  global install.
- **0.80.4 → 0.80.5 delta: none observed.** The pinned `CHANGELOG.md`'s `[0.80.5]` section is
  empty (a bare re-release header); all features under audit are listed under `[0.80.4]`. No
  behavioral delta was encountered during the audit.
- **Pin-bump record:** 0.80.3 → 0.80.5 required **zero mechanical fixes** — `just ci` (tsc +
  Biome + node:test + pytest) passed unchanged on the first run after `npm install`. The pi-ai
  ≥0.80 compat split (`@earendil-works/pi-ai/compat` for value imports, guarded by
  `extension/piAiCompatGuard.test.ts`) was already handled at 0.80.3 and stayed type-compatible.
  The lockfile diff needed hand-cleaning: npm rewrote unrelated entries (`"peer": true`
  annotations on `pi-tui@0.78.0` / `get-east-asian-width` / `marked` / `typebox`, and a
  `bin`-path normalization `./dist/cli.js` → `dist/cli.js` on the nested pi-ai entry that
  contradicts the shipped package.json) — those hunks were reverted so the committed diff is
  bump-only.
- **Evergreen installs left untouched:** the remote-runner action
  (`.github/actions/perk-remote-setup/action.yml`, `npm install -g
  @earendil-works/pi-coding-agent`) and the worker checkout install in
  `src/perk/run/workflow_artifacts.py` install pi **unpinned** — they track the latest published
  pi by design and need no change for this bump.
- **Future-bump note (worktree inertness):** a devDep pin bump is inert until `npm install` runs
  **in the checkout that resolves the modules** — a fresh worktree has no `node_modules`, so
  install there, not in the main checkout (`docs/learned/toolchain/worktree-node-modules.md`).

## §1 Usage inventory — perk's pi surface today

All counts are fresh greps of `extension/` (production + test files, `node_modules` excluded)
at implement time; anchors are file + symbol.

### §1.1 Extension interior (`extension/`)

**Events handled (35 `pi.on(...)` sites):**

| Event | Sites | perk call sites (file → registering function) |
| --- | --- | --- |
| `before_agent_start` | 8 | `adapters/planAdapterPlannotator.ts`, `adapters/planAdapterTombell.ts`, `adapters/todoAdapterJuicesharp.ts`, `checkpoints/checkpoints.ts` (`registerCheckpoints`), `factories/objectiveAuthor.ts`, `factories/planMode.ts`, `substrate/bindingDelivery.ts`, `substrate/toolGating.ts` |
| `context` | 7 | the same adapter/factory/substrate set minus checkpoints: `planAdapterPlannotator`, `planAdapterTombell`, `todoAdapterJuicesharp`, `objectiveAuthor`, `planMode`, `bindingDelivery`, `toolGating` (the inject-and-conditionally-strip pattern, `docs/learned/pi/context-injection.md`) |
| `session_start` | 5 | `checkpoints/checkpoints.ts`, `factories/objective.ts` (`registerObjective`), `factories/planMode.ts`, `index.ts` (workflow-state rebuild + footer install), `vendor/btw/btw.ts` |
| `session_tree` | 4 | `checkpoints/checkpoints.ts`, `factories/objective.ts`, `index.ts`, `vendor/btw/btw.ts` |
| `turn_end` | 3 | `checkpoints/checkpoints.ts` (marker scan), `factories/objective.ts` (threshold compaction), `vendor/whimsical/whimsical.ts` |
| `session_before_fork` | 2 | `doors/lifecycleGates.ts` |
| `session_before_switch` | 1 | `doors/lifecycleGates.ts` |
| `session_compact` | 1 | `checkpoints/checkpoints.ts` (rebuild + re-render; stale-`ctx` race swallowed via `isStaleCtxError`) |
| `session_shutdown` | 1 | `vendor/btw/btw.ts` |
| `agent_end` | 1 | `factories/objective.ts` (`registerObjective` — budget recompute; see [§2.1](#21-agent_settled--agent_startagent_end-clarified-semantics)) |
| `turn_start` | 1 | `vendor/whimsical/whimsical.ts` |
| `tool_call` | 1 | `substrate/toolGating.ts` (read-only enforcement) |

Zero uses of: `registerEntryRenderer`, `registerMessageRenderer`, `agent_start`, `agent_settled`,
`before_provider_headers`, `before_provider_request`, `after_provider_response`,
`session_info_changed`, `message_*`, `tool_execution_*`, `input`, `project_trust`,
`resources_discover`.

**`pi.*` APIs (call counts):**

| API | Count | Notes / representative sites |
| --- | --- | --- |
| `pi.on` | 35 | table above |
| `pi.sendUserMessage` | 24 | 15 files — every warm door's gesture emission (`doors/address.ts`, `doors/land.ts`, `doors/learn.ts`, `doors/learnFactory.ts`, `doors/prReview*.ts`, `doors/review*.ts`, `doors/submit.ts`, `factories/implementHere.ts`, `factories/objectivePlan.ts`, `factories/objectiveSave.ts`, `testing/harness.ts`, `vendor/btw/btw.ts`); six sites pair it with `ctx.isIdle()` + `deliverAs: "followUp"` (see [§2.1](#21-agent_settled--agent_startagent_end-clarified-semantics)) |
| `pi.registerTool` | 18 | 16 files — the terminating stage tools (`submit`, `ready`, `land`, `learn`, `plan_save`, …) plus `doors/askUser.ts`, `doors/ciExecutor.ts` (`run_ci`), the draft/review tools |
| `pi.appendEntry` | 12 | 7 files, four perk entry-type families: `WORKFLOW_STATE_TYPE` = `perk:workflow-state` (`index.ts`, `substrate/toolGating.ts`, `factories/objective.ts`), `CHECKPOINT_TYPE` = `perk:checkpoint` (`checkpoints/checkpoints.ts`), `OBJECTIVE_BUDGET_TYPE` = `perk:objective-budget` (`factories/objective.ts`, `factories/objectiveSave.ts`), btw's `btw-thread-entry`/`btw-thread-reset` (`vendor/btw/btw.ts`); none has a transcript renderer (see [§2.3](#23-entry-renderers-piregisterentryrenderer--piappendentry-pairing)) |
| `pi.exec` | 21 | 12 files — `substrate/coldDoor.ts` (the cold-door shell seam), `doors/ciExecutor.ts`, `doors/submit.ts`, `doors/ready.ts`, `doors/hunkHandoff.ts`, `doors/lifecycleGates.ts`, `substrate/terminalLaunch.ts`, `substrate/clipboard.ts`, `factories/objectivePlan.ts`, `testing/harness.ts`, + tests |
| `pi.events` | 10 | production: `adapters/planAdapterPlannotator.ts` (5), `doors/prReviewLocal.ts` (3), `doors/reviewPlannotator.ts` (1), `factories/planReview.ts` (1) — the plannotator/review bridge (`docs/learned/workflow/plan-review-flow.md`) |
| `pi.registerCommand` | 3 | `substrate/command.ts` (`registerPerkCommand`, the one seam every `/perk-*` command flows through), `vendor/btw/btw.ts` (`/btw`), + 1 test |
| `pi.getThinkingLevel` | 3 | `vendor/btw/btw.ts` (2), `index.ts` (footer dep closure) |
| `pi.getAllTools` | 3 | `doors/selfcheck.ts`, `substrate/toolGating.ts` (restore set) |
| `pi.setActiveTools` | 2 | `substrate/toolGating.ts` (the read-only gate) |
| `pi.registerFlag` / `pi.getFlag` | 2 / 2 | `factories/planMode.ts` (`--plan`), `doors/ciExecutor.ts` (`--allow-project-ci`) |
| `pi.getActiveTools` | 2 | `substrate/toolGating.ts`, `doors/selfcheck.ts` |
| `pi.registerShortcut` | 1 | `factories/planMode.ts` (Ctrl+Alt+P) |
| `pi.getCommands` | 1 | `doors/prReviewLocal.ts` (plannotator-command detection) |

**`ctx.*` members (grep-counted):** `cwd` (102), `hasUI` (25), `ui` (23 — confined to
`extension/surfaces/` by `surfacesGuard.test.ts`, plus the sanctioned `/btw` exception),
`signal` (14), `model` (10), `sessionManager` (8), `mode` (8), `isIdle` (6), `modelRegistry` (5),
`newSession` (2), `getContextUsage` (2), `agentDir` (2), `getSystemPromptOptions` (1),
`getSystemPrompt` (1), `compact` (1).

### §1.2 SDK/worker tier

| API | perk call sites |
| --- | --- |
| `createAgentSessionServices` / `createAgentSessionFromServices` / `createAgentSessionRuntime` | `worker/worker.ts` (`defaultCreateRuntime`) — the runtime-factory path; the loader is built internally from `cwd`/`agentDir` (`docs/learned/pi/headless-session-drive.md`) |
| `createAgentSession` + hand-built `DefaultResourceLoader` | `worker/readOnlySession.ts` (`createReadOnlySession` — `no*` flags + tools allowlist, manual `loader.reload()`); `testing/harness.ts` (`loadPerkSession`) |
| `session.bindExtensions` | `worker/worker.ts` (`DriveRuntimeLike.bindExtensions`, `mode: "json"`), `testing/harness.ts` |
| `session.subscribe` | `worker/worker.ts` (the terminal/budget listener via `attachRuntime`) |
| `AuthStorage` / `ModelRegistry` | `worker/worker.ts` (`resolveAuth`), `workerMain.ts` (`--model provider/id` exact lookup via `modelRegistry.find`) |
| `SettingsManager` | `worker/worker.ts` (`SettingsManager.create(worktree, throwawayAgentDir)` + `applyOverrides({compaction:{enabled:false}, retry:{enabled:false}})` + `drainErrors`), `worker/readOnlySession.ts` + `testing/harness.ts` (`SettingsManager.inMemory`) |
| `SessionManager.create` | `worker/worker.ts` (`defaultCreateRuntime`) |
| `extensionFactories` | `testing/harness.ts` (`extensionFactories: [perk, ...extraExtensions]` — bare factory functions; see [§2.4](#24-inlineextension-named-factories)) |
| `@earendil-works/pi-ai/compat` value imports | `testing/harness.ts` (`getModel`) — guarded by `extension/piAiCompatGuard.test.ts`; type-only imports (`Api`, `Model`) stay on the root entrypoint |

### §1.3 Python exterior

| Surface | perk site | pi surface consumed |
| --- | --- | --- |
| `pi` argv construction | `_build_argv` in `src/perk/run/launch/__init__.py` | `--approve` for worktree stages (project trust, 0.79.0 — adopted); `--model`/`--thinking` from `[models.stages.<id>]` (`_stage_model_argv`); `--skill`/`--no-skills` scoped-launch composition (`_skill_exposure_argv`); user `pi_args` last (pi parses last-wins) |
| Managed `.pi/settings.json` convergence | `_converge_settings` in `src/perk/convergence/init/settings.py` | Rewrites ONLY its owned keys: `packages` (static + provider + linear wiring), `compaction` (merge, write-when-present), `defaultProvider`/`defaultModel`/`defaultThinkingLevel` (per-key, write-when-present), `subagents.disableBuiltins` (constant). All sibling keys are preserved byte-for-byte via JSON round-trip |
| Evergreen pi installs | `.github/actions/perk-remote-setup/action.yml` (`npm install -g @earendil-works/pi-coding-agent`); `src/perk/run/workflow_artifacts.py` (the same global install in the generated workflow + an unpinned `@earendil-works/pi-coding-agent` devDep install in the worker checkout) | Latest published pi, by design |
| Session JSONL parsing | `src/perk/learn/session_jsonl.py`, `src/perk/learn/export.py` | pi CLI session-file grammar (coding-agent `SessionManager` v3 JSONL: header line + entry lines) — parsed structurally in Python, no TS exports involved (see [§2.8](#28-session-storage-exports--jsonl-header-custom-metadata-64176435)) |
