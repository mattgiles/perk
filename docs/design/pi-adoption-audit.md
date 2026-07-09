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

## §2 pi 0.80.4 feature evaluations

Every pi-behavior claim in this section was verified against the pinned 0.80.5 dist/docs
(`node_modules/@earendil-works/pi-coding-agent/...`); perk claims carry file + symbol anchors.

### §2.1 `agent_settled` (+ `agent_start`/`agent_end` clarified semantics)

**What pi ships (verified @ 0.80.5).** `AgentSettledEvent` exists in
`dist/core/extensions/types.d.ts` (`AgentSettledEvent`, doc comment: "Fired after an agent run
has fully settled and no automatic retry, compaction, or queued continuation will run") with an
`on("agent_settled", ...)` overload on `ExtensionAPI`. `docs/extensions.md#agent_start--agent_end--agent_settled`
clarifies: `agent_end` fires when a low-level run ends "but Pi may still auto-retry, auto-compact
and retry, or continue with queued follow-up messages"; `agent_settled` is for "status
integrations that need to know Pi will not continue running automatically", and `ctx.isIdle()` is
true inside it unless another extension started a new run. Mechanism (from
`dist/core/agent-session.js`): `_runAgentPrompt` loops `while (await this._handlePostAgentRun())
await this.agent.continue();` — the post-run handler covers retryable-error retry, compaction
retry, and agent_end-queued messages — and its `finally` awaits `_emitAgentSettled()`. The same
release adds session-level idle waiting: `AgentSession.waitForIdle()`
(`dist/core/agent-session.d.ts`) plus the clarified `isIdle` getter ("no active agent run, retry,
auto-compaction, or queued continuation").

**(a) `registerObjective`'s budget recompute (`extension/factories/objective.ts`,
`pi.on("agent_end", ...)` → `renderStatus`).** This is literally the "status integration" case
the pi docs route to `agent_settled`. Today's `agent_end` handler recomputes the objective budget
after *every low-level run* — including mid-retry and mid-compaction-retry runs, where the branch
is about to change again. The recompute is a stateless rebuild from the branch (idempotent), so
this is a correctness-*polish* + efficiency win, not a bug fix: on `agent_settled` the recompute
runs exactly once per settled run, on the final branch state. **Verdict: adopt-later** (fold into
the lifecycle follow-up plan). Sketch: in `registerObjective`, change the event name
`"agent_end"` → `"agent_settled"` (handler body unchanged — it ignores the event payload; the
`AgentEndEvent.messages` field is unused). Update the module doc-comment lines that enumerate the
budget-accounting events. Host-compat: see (d).

**(b) The six `isIdle()` + `deliverAs: "followUp"` reactive-drive sites**
(`doors/submit.ts` `driveConflictResolution`, `doors/land.ts` `driveReconcileAfterLand`,
`doors/prReviewLocal.ts` `routePrReviewOutcome`, `doors/reviewPlannotator.ts`,
`factories/implementHere.ts`, `vendor/btw/btw.ts`). These are *active drivers* inside
command/tool handlers deciding **delivery mode at emission time** — immediate turn when idle,
queued follow-up when streaming. `agent_settled` is a *passive observation* hook; rewriting these
sites onto it would invert their shape (park the message, wait for settlement, then send) for no
correctness gain: `docs/extensions.md` documents `deliverAs: "followUp"` as "Waits for agent to
finish. Delivered only when agent has no more tool calls", and the agent loop drains the queued
follow-ups itself before emitting `agent_end` (comment in `dist/core/agent-session.js`
`_handlePostAgentRun`: "The agent loop drains both queues before emitting agent_end") — the
queued message is never lost to a retry/compaction window. The current idiom is the simpler,
sanctioned shape. **Verdict: decline** (no change; record so the
question doesn't reopen).

**(c) `driveStage`'s post-`prompt()` classification (`extension/worker/worker.ts`).** The
concern: can classification observe an unsettled run (auto-retry/auto-compaction pending)?
**No — verified against the pinned dist:** `AgentSession.prompt()` awaits `_runAgentPrompt`,
whose retry/compaction/follow-up continuation loop AND the `finally`-emitted `agent_settled` all
complete before the `prompt()` promise resolves (`dist/core/agent-session.js`,
`_runAgentPrompt`). So `await session.prompt(...)` already spans settlement, and `driveStage`'s
natural-idle classification cannot race an unsettled run. (Belt-and-suspenders note: the worker
additionally disables auto-compaction and auto-retry via
`settingsManager.applyOverrides({ compaction: { enabled: false }, retry: { enabled: false } })`
in `defaultCreateRuntime`, shrinking the post-run loop to agent_end-queued messages only.) The
new `waitForIdle()` (#6363) is redundant on this path. **Verdict: decline** for `driveStage`
(no gap to close); the finding upgrades `docs/learned/pi/headless-session-drive.md` — a
follow-up doc touch, not code.

**(d) Host-compat posture.** perk's extension runs on whatever pi the operator installed (the
remote runner installs evergreen pi — always ≥0.80.4 now; local operators may lag). A handler
registered for an event an older host never emits is **inert** — pi's extension runner only
invokes handlers for events it emits, so `pi.on("agent_settled", ...)` on a pre-0.80.4 host
simply never fires (and registration itself is a string-keyed subscription — no startup error).
Consequence for (a): *moving* (not duplicating) the budget recompute off `agent_end` means on a
pre-0.80.4 host the budget stops updating per-run, degrading to the `session_start`/
`session_tree` renders. Minimum host pi implied by the move: **0.80.4**. perk currently has no
pi-version floor mechanism (the managed `.perk/required-perk-version` pin covers perk itself,
not pi) — the follow-up plan should either accept the graceful degradation (budget still renders
on session events; recommended) or add a doctor-level pi-version note, rather than keeping a
dual `agent_end`+`agent_settled` registration (double recompute on new hosts).

### §2.2 `before_provider_headers`

**What pi ships (verified @ 0.80.5).** `docs/extensions.md#before_provider_headers`: fired after
outgoing HTTP headers are assembled; handlers mutate `event.headers` in place (string to
add/override, `null` to delete); runs once per provider request, retries reuse the same headers.
`BeforeProviderHeadersEvent` is in `dist/core/extensions/types.d.ts` and the root export map.

**perk's header-injection needs.** Surveyed the plausible cases:

- *Gateway tracing/attribution for remote runs* — the only candidate with any substance: tagging
  provider requests from `driveStage` workers with a run id (e.g. `x-session-id`, the docs' own
  example). But perk's remote runs already have a canonical, richer observability record — the
  GitHub Actions run + the worker's `RunOutcome`/run-report artifacts
  (`docs/learned/workflow/remote-runner.md`) — and perk fronts no gateway of its own that could
  read such headers. Nothing consumes the header on the other end.
- *Auth/header workarounds* — perk deliberately owns **no** provider transport configuration
  (auth is pi's: `AuthStorage`/`ModelRegistry` in the worker, the operator's `auth.json`
  interactively). Injecting headers would cross into pi's ownership for no perk feature.
- *Stripping tracking headers* — an operator preference, settable by the operator's own global
  extension; not perk's workflow concern.

**Verdict: decline.** perk has no header-injection need; recording the rationale here so the
question doesn't reopen. Revisit trigger: only if perk ever fronts its own provider gateway for
remote runs (no roadmap item does).

### §2.3 Entry renderers (`pi.registerEntryRenderer` + `pi.appendEntry` pairing)

**What pi ships (verified @ 0.80.5).** `pi.registerEntryRenderer(customType, renderer)`
(`dist/core/extensions/types.d.ts`: `EntryRenderer<T> = (entry: CustomEntry<T>, options:
EntryRenderOptions, theme: Theme) => Component | undefined`) renders persisted display-only
custom entries in the interactive transcript without sending them to the model
(`docs/extensions.md#piregisterentryrenderercustomtype-renderer`). The renderer returns a pi-tui
`Component` (the docs example builds `Box`/`Text` and honors an `expanded` option). 0.80.4 also
fixed ordering for custom entries appended during assistant streaming (changelog: "render before
the live assistant message, matching persisted session order"). Headless behavior: rendering is
an interactive-mode concern; in `mode: "json"`/RPC the renderer is simply never invoked.

**perk's display-only entries today (all invisible in the transcript):**

| Entry type | Appended by | Content |
| --- | --- | --- |
| `perk:workflow-state` | `extension/index.ts` (stage transitions), `substrate/toolGating.ts` (read-only/read-write flips), `factories/objective.ts` (active-objective set/clear) | workflow-state deltas |
| `perk:checkpoint` | `checkpoints/checkpoints.ts` (seed + updates) | the steps checklist |
| `perk:objective-budget` | `factories/objective.ts`, `factories/objectiveSave.ts` | budget activation/config |
| `btw-thread-entry` / `btw-thread-reset` | `vendor/btw/btw.ts` | side-chat thread state |

Rendering these would give the transcript durable, scroll-back-visible markers ("entered
read-only mode", "checkpoint 3/8 done", "objective #N activated — budget X") where today the
only surfaces are the ephemeral footer/widget and `report()` notices. Genuine operator value,
especially for post-hoc session reading (and `/tree` navigation context).

**The policy question (must be answered explicitly): is a TUI entry renderer a rich-UI call the
surfaces module must own?** **Yes.** The rendered output is themed TUI componentry — exactly the
class of surface the charter routes through `extension/surfaces/` (AGENTS.md: "Rich UI goes
through the surfaces module"; `extension/surfacesGuard.test.ts` currently confines
`ui.notify`/`setStatus`/`setWidget`/`setFooter`/`setWorkingMessage` to
`surfaces/report.ts` + `surfaces/surfaces.ts`). `pi.registerEntryRenderer` is a `pi.*` call the
guard does not yet match, so adopting renderers without a policy extension would silently open an
unguarded rich-UI channel. Proposed seam shape (mirrors the existing pattern):

- `extension/surfaces/surfaces.ts` exports a builder per entry family —
  `checkpointEntryRenderer(...)`, `workflowStateEntryRenderer(...)`, etc. — owning all pi-tui
  imports, glyphs (the existing `GLYPHS` vocabulary), and theming; feature modules pass data
  accessors only.
- Registration stays at the feature module (`pi.registerEntryRenderer(CHECKPOINT_TYPE,
  checkpointEntryRenderer(...))`) — registration is wiring, not rendering, matching how
  `installPerkFooter` is called from `index.ts` while the factory lives in surfaces.
- Extend `surfacesGuard.test.ts` `RULES` with `{ pattern: /\bregisterEntryRenderer\(/, ... }` —
  but allowlisting the *registering* modules would defeat the point; instead guard the renderer
  *bodies*: add a rule that pi-tui component imports (`from "@earendil-works/pi-tui"`) stay
  confined to the surfaces module (a new pattern, same mechanism), which structurally forces
  renderer factories into `surfaces/`.

**Verdict: adopt-later** — real operator value, zero model-context cost, but it is pure polish
gated on the surfaces-policy extension above; group with the lifecycle plan or a dedicated
"transcript renderers + surfaces policy" plan (see §4). Host-compat: `registerEntryRenderer`
does not exist on pre-0.80.4 hosts — unlike an unknown *event name*, calling a missing *method*
throws `TypeError`, so adoption must feature-detect (`typeof pi.registerEntryRenderer ===
"function"`), which also keeps the harness/worker paths (json mode) inert-safe.

### §2.4 `InlineExtension` named factories

**What pi ships (verified @ 0.80.5).** `InlineExtension` (`docs/sdk.md#inlineextension`,
exported from the root): `{ name: string; factory: (pi) => ... }` accepted anywhere
`extensionFactories` takes a bare factory function; startup/error surfaces then display
`<inline:my-name>` instead of `<inline:1>`. Bare functions remain accepted.

**perk's exposure.** Exactly one production-adjacent site passes inline factories:
`testing/harness.ts` (`loadPerkSession`) — `extensionFactories: [perk,
...(opts.extraExtensions ?? [])]` into a hand-built `DefaultResourceLoader`.
`worker/readOnlySession.ts` deliberately passes none (isolation comes from `no*` flags, per its
header comment). The benefit is confined to test-failure diagnostics: an extension load error in
the harness would name `<inline:perk>` instead of `<inline:1>`.

**Verdict: adopt-later (trivial).** Sketch: in `testing/harness.ts`, wrap the perk factory as
`{ name: "perk", factory: perk }` (and optionally accept `InlineExtension` in
`extraExtensions`' type). Type-only change riding the devDep pin — no host-compat concern (the
harness binds the pinned SDK, not the operator's pi). Fold into whichever follow-up plan next
touches the harness or worker; not worth a standalone plan.

### §2.5 Project-local resource configuration (`pi config -l`, Tab scope switching, enable/disable overrides)

**What pi ships (verified @ 0.80.5).** `pi config` gains project-mode startup (`pi config -l`)
and Tab switching between global (`~/.pi/agent/settings.json`) and project-local
(`.pi/settings.json`) scopes, with inherited global resources dimmed
(`docs/packages.md#enable-and-disable-resources`). **Which settings keys the override management
writes** (traced in `dist/modes/interactive/components/config-selector.js`):

1. *Top-level resources* (`setProjectTopLevelOverride` → `SettingsManager.setProject{Extension,
   Skill,PromptTemplate,Theme}Paths`): the project `extensions` / `skills` / `prompts` / `themes`
   **arrays**, written as `+<pattern>` (project load) / `-<pattern>` (project unload) entries,
   plus the bare path for inherited-global items (legacy `!` negation entries are recognized and
   replaced).
2. *Package resources* (`togglePackageResource`): the **`packages` array entry itself** — a
   string entry is **converted to object form** `{ source, extensions?/skills?/prompts?/themes? }`
   with `+`/`-` patterns in the per-resource filter arrays; when the last filter is removed the
   entry collapses back to a string. Scope-dependent: written into project or global `packages`
   via `setProjectPackages`/`setPackages`.

**Does `_converge_settings` preserve these keys?** (`src/perk/convergence/init/settings.py`)

- *Top-level `extensions`/`skills`/`prompts`/`themes` arrays*: **preserved byte-for-byte** —
  `_converge_settings` reads and rewrites only `packages`, `compaction`, the three top-level
  model keys, and `subagents`; all other keys survive the JSON round-trip untouched. ✅
- *Object-form conversion of a **provider-managed** package* (e.g. `npm:pi-web-access`):
  **preserved** — `_converge_provider_packages` computes identity via `_package_identity`, which
  handles object-form entries (reads `source`), so the entry is recognized as present/desired and
  left alone (including the user's filter arrays). ✅
- *Object-form conversion of **perk's own** entry (`npm:@mgiles/perk@X`) or a **borrowed** entry
  (`npm:@tombell/pi-diff`, `npm:pi-subagents`)*: **⚠ duplicate-append hazard.**
  `_merge_static_packages` builds its presence sets from **string entries only** (`have_npm` /
  `have_local` filter on `isinstance(p, str)`), so once `pi config -l` rewrites the entry to
  object form, the next `perk init` / `perk doctor --fix` no longer *sees* it and **appends a
  second, string-form entry** with the same identity. For perk's own package that means the
  user's disable-filter object AND a fresh pinned string entry coexist (pi's scope-dedup rules in
  `docs/packages.md#scope-and-deduplication` govern which wins — identity-equal entries in the
  *same* scope are not something perk should be producing). The `_merge_static_packages`
  docstring already names hand-written object-form perk entries a "documented limitation" —
  0.80.4 upgrades that limitation from a hand-edit corner case to something any user can reach
  through a supported TUI flow. This is the concrete doctor-probe trigger below.

**Does disabling a perk-critical resource strand a stage session?**

- *Headless worker*: **fails fast — already handled.** `driveStage` preflights the stage's
  terminating perk tool post-bind and exits zero-turn with `errorType: "no_extension_tools"`
  instead of burning budget on a tool-less session (`extension/worker/worker.ts`, the post-bind
  preflight + its rule helper), and `defaultCreateRuntime` loudly logs extension load errors and
  settings errors. A project-scope `-` filter on perk's extension would surface exactly there. ✅
- *Interactive stage session*: **degrades silently.** With perk's extension filtered off, a
  `perk implement`-launched session comes up as plain pi — no stage tools, no footer, no
  checkpoints, no gates. Nothing fails loudly; the operator discovers it when `/submit` doesn't
  exist. Launch (`_build_argv`) has no preflight that the extension will load — and shouldn't
  grow one (the exterior can't cheaply evaluate pi's resource-filter semantics). The right
  detection point is `perk doctor`.

**Should `perk doctor` grow a probe?** Yes — one report-only check with two arms:
(1) *object-form perk entry*: warn when the project `packages` array carries perk's own identity
(`_package_identity(...) == _npm_name(NPM_PACKAGE)`) in object form — both because init would
duplicate it (hazard above) and because its filters may be disabling perk resources; offer
`doctor --fix` normalization back to the pinned string entry only with explicit messaging (the
user *chose* those filters; auto-stripping them is hostile — report, don't rewrite, by default).
(2) *disable-pattern sweep*: warn when any project-scope top-level array or perk-package filter
carries a `-`/`!` pattern matching perk's extension or a `perk-*` skill. Additionally,
`_merge_static_packages` should learn to *recognize* object-form entries by identity for the
presence check (fixing the duplicate-append at the root — a small, testable change that keeps
Invariant 2 "perk never *writes* object form for its own package" intact).

**Do user docs / `perk-expert` need a section?** Yes — a short "scoping perk's resources
per-project" note: `pi config -l` is the sanctioned way to disable a *borrowed* or *provider*
package resource per-repo; filtering perk's own extension breaks every stage; top-level override
arrays are safe and survive `perk init`. (Deferred to the follow-up plan per this plan's
assumptions — no docs changes here.)

**Verdict: adopt-now** (the only item in this audit with a latent-corruption path reachable
through a supported pi flow). Sketch: one follow-up plan touching
`src/perk/convergence/init/settings.py` (`_merge_static_packages` object-form identity
awareness), a `doctor` probe (report-only, both arms), pytest coverage for the
object-form-entry convergence, and the user-docs/`perk-expert` section.

### §2.6 `showCacheMissNotices` + prompt-cache visibility

Static analysis only (per plan); the live measurement is specified as a protocol appendix
([§2.6.3](#263-measurement-protocol-appendix-for-the-follow-up-plan)).

**What pi ships (verified @ 0.80.5).** Two orthogonal cache-visibility surfaces:

- *Footer `CH` display* (0.79.0): pi's **default** footer shows the latest prompt cache-hit rate.
  Computation (`dist/modes/interactive/components/footer.js`): per assistant message,
  `cacheRead / (input + cacheRead + cacheWrite) * 100`, rendered `CH<pct>%` from the latest
  usage-bearing entry.
- *`showCacheMissNotices`* (0.80.4): a `Settings` key (`dist/core/settings-manager.d.ts`,
  `showCacheMissNotices?: boolean`, default off) + `/settings` toggle that surfaces *significant*
  cache misses as transcript notices. The supporting analysis lives in
  `dist/core/cache-stats.d.ts` (`CacheMiss` — missed tokens, missed **cost**, idle-gap ms,
  model-changed flag; `CACHE_TTL_MS` notes Anthropic's 5-minute TTL) — note these helpers are
  **not** exported from the package root (verified: no `cache-stats` re-export in
  `dist/index.d.ts`), so perk cannot import them.

**(a) Operator ergonomics — perk's footer suppresses pi's only always-on cache surface.**
Confirmed: `installPerkFooter` (`extension/surfaces/surfaces.ts`) replaces pi's default footer
wholesale (charter D2, sole-owner law), and `composeFooterLine`'s `FooterParts` has no cache
member — perk repos lost the `CH` display when perk took the footer. Options:

1. *Add a cache segment to `perkFooter`* — **recommended.** Sketch: extend `FooterParts` with
   `cache?: string`; compute it in a new `PerkFooterDeps` closure (`getCacheHitRate()`), wired
   from `index.ts` beside the existing `getThinkingLevel`/`getContext` deps, reading the latest
   assistant usage off `ctx.sessionManager` exactly as pi's footer.js does (the formula above is
   4 lines; the helpers being unexported means reimplementing it, same as the existing
   `sanitizeGuestStatus` precedent). Drop-order: insert `cache` in the right group's D9 drop
   sequence before `context` (drop cache before context — context is the operationally critical
   one). Cost: one closure + one segment; fully offline-testable via the existing
   `composeFooterLine` tests.
2. *Converge `showCacheMissNotices: true` via init* — **not recommended.** The
   `[compaction]`/`[models]` write-when-present precedent converges *repo policy*; cache-miss
   notices are an *operator diagnostic preference* (transcript noise for everyone in the repo if
   perk forces it on). It also composes poorly with (1): the footer segment is ambient and free,
   notices are episodic and loud. Document instead (see below).
3. *Document* — yes, alongside whichever ships: a perk-expert/user-docs note that pi's `CH`
   footer display is superseded by perk's footer and how to enable `showCacheMissNotices`
   per-user for diagnosis. (Deferred to the follow-up plan.)

**(b) perk's own performance — which perk machinery plausibly causes prompt-cache misses.**
Reasoned from code; each site mutates messages *early* in the context window, invalidating the
provider's prefix cache from that point on the next call (`docs/learned/pi/context-injection.md`:
the `context` event runs on **every** provider call over the full message list):

| Mechanism | Site | When it mutates early context |
| --- | --- | --- |
| Plan-mode guidance strip | `factories/planMode.ts` (`context` handler) | once, when the read-only gate turns off (plan-mode exit) — removes an early injected message |
| Objective-author guidance strip | `factories/objectiveAuthor.ts` | once, at authoring-stage exit (same pattern) |
| Binding-context strip | `substrate/bindingDelivery.ts` | once, when the stage stops rendering non-empty bindings (stage transition) |
| Adapter context injections/strips | `adapters/planAdapterPlannotator.ts`, `planAdapterTombell.ts`, `todoAdapterJuicesharp.ts` | per adapter lifecycle — inject on delivery turn, strip on staleness |
| Steady state (no toggle) | all of the above | **no mutation** — the strips are conditional (keyed on live state), so a stable stage filters identically on every call, which is cache-*stable* |

Expected shape: perk costs a bounded number of **transition misses** (one per gate flip /
stage hand-off / delivery turn), not a per-turn cache burn. Two perk-adjacent notes: perk's
`pi.appendEntry` families are context-invisible (custom *entries*, not messages) and cannot cause
misses; and idle-gap misses (`CacheMiss.idleMs`, TTL expiry while the human thinks) will dominate
in interactive dogfoods — the protocol below separates them so perk isn't blamed for TTL decay.

**Verdict: adopt-later**, two-part: (1) the footer cache segment (option 1 sketch) and (2) the
measurement protocol run, grouped as one "cache visibility" follow-up plan;
`showCacheMissNotices` stays a documented per-user toggle, not converged.

#### §2.6.3 Measurement-protocol appendix (for the follow-up plan)

Bounded protocol; executes in a dogfood repo on pinned pi ≥0.80.4:

1. *Enable*: user-scope `showCacheMissNotices: true` (via `/settings`), leave repo settings
   untouched.
2. *Session A — plan-mode toggle*: launch a plan session (`perk plan …`), author ≥6 turns, exit
   plan mode, run 2 more turns. Record per turn: the footer/`/session` usage numbers and any
   cache-miss notice (missed tokens, missed cost, idle-gap, model-changed).
3. *Session B — bindings implement*: launch an implement stage with ≥1 skill binding, run ≥8
   turns crossing a binding-delivery turn and a stage transition.
4. *Session C — control*: plain pi session in the same repo, same turn count, no perk stages.
5. *Attribute*: for each notice, classify — (i) transition miss (timestamp aligns with a gate
   flip/delivery/strip turn), (ii) idle-gap miss (`idleMs` ≳ 5 min TTL), (iii) unexplained.
   Compare miss counts/costs A/B vs C.
6. *Acceptance*: perk-attributable misses ≈ the predicted transition count (one per flip) ⇒
   document as expected cost; any *per-turn* recurring miss in A/B but not C ⇒ file it as a
   defect against the responsible strip (it means a strip is mutating on every call, violating
   the conditional-strip pattern).
