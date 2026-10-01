# Re-verify: pi-subagents 0.73.1 — the consumer pin, the 0.74.0 RPC break, and the Pi 0.99.2 host

**Status:** dated evidence record (2026-10-01) — the guidance-baseline re-verify for pi-subagents
0.73.1, run beside the Pi 0.99.2 baseline move
([`pi-0.99.2-baseline-verification.md`](pi-0.99.2-baseline-verification.md)). It records the
decision to **pin consumers to `npm:pi-subagents@0.73.1`** (0.74.0 breaks perk's report waves) and
the evidence for moving `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` from `0.70.1` to `0.73.1`. The
template is [`pi-subagents-0.70.1-reverify.md`](pi-subagents-0.70.1-reverify.md); the procedure is
`docs/developers/pi-subagents-reverify.md`.

**Verdict: PENDING** — the source re-read, the offline halves, the doctor half and the scout wave
PASS on the Pi 0.99.2 host. Open: the PR-door browser wave (the owner's `/pr-review-browser` on
this change's PR) and the owner's confirmation of the plan-door half. The stamp moves only when
every half passes (owner decision: no owed half).

## The matrix

| Component | Version | Provenance |
|---|---|---|
| perk | 3.9.0 @ branch `plan-2641` (this change, pre-merge) | the implementation this record trails |
| Pi (pinned dev toolchain) | `@earendil-works/*` 0.99.2 (six pins) | `package.json` devDependencies, moved from 0.87.0 in the same change |
| Pi (host) | 0.87.1 at the source re-read; 0.99.2 for the live leg | `pi --version` — the owner upgrades the global `pi` mid-implementation |
| pi-subagents (installed, now pinned) | 0.73.1 | `.pi/npm/node_modules/pi-subagents/package.json`; `.pi/settings.json` carries `npm:pi-subagents@0.73.1`; compiled `src/**/*.js` read in place |
| pi-subagents (npm `latest`) | 0.74.0 (2026-09-30) | `gh release view v0.74.0 -R nicobailon/pi-subagents` — NOT adopted (below) |
| pi-web-access (installed) | 0.33.0 | `.pi/npm/node_modules/pi-web-access/package.json` |
| Plannotator (installed) | 0.27.21 | `.pi/npm/node_modules/@plannotator/pi-extension/package.json` |
| Previous baseline | 0.70.1 (last source re-read 0.71.0) | `docs/learned/pi/subagents.md` § Sources before this pass |

## Source facts (file/function anchors, verified in the installed compiled 0.73.1)

The runbook's standing mechanics, re-read:

- **Parent-side `progress_update` still discarded** — `src/intercom/native-supervisor-channel.js`
  (`expectsReply = params.reason !== "progress_update"`, ~line 113; a no-reply request returns
  without a reply lifecycle). Every perk wave keeps `intercomBridge: {mode: "off"}`.
- **Per-launch bridge override still spreads onto workflow children** —
  `src/runs/foreground/subagent-executor.js`: `resolveIntercomBridge({ config, override:
  input.params.intercomBridge ?? recoveryDescriptor?.intercomBridge, … })` (~line 1588) and
  `childParams.intercomBridge ?? workflowDefaults.intercomBridge` (~line 4324);
  `src/intercom/intercom-bridge.js` `inactiveReason` returns "bridge mode is off" for `mode: "off"`.
- **The RPC still accepts `workflowScript`** — `src/extension/schemas.js` keeps
  `workflowScript`/`workflowScriptPath` (~line 320) and `additionalProperties: true` on the spawn
  params; `src/extension/public-execution.js::normalizePublicSubagentExecution` still strips only
  the resource/permit fields. This is the parameter 0.74.0 removes.
- **Wake rules unchanged** — `src/runs/background/notify.js::incrementalChildCompletionTriggersTurn`
  (`if (child.workflowRunning && child.outcome === "completed") return false;`).
- **v1 RPC envelope unchanged** — `src/extension/rpc.js`: `subagents:rpc:v1:request` /
  `subagents:rpc:v1:ready` / `subagents:rpc:v1:reply:`.
- **Structured output** — `src/runs/shared/child-tool-plan.js` (~line 228): `internalTools =
  (input.structuredOutput ? ["structured_output"] : [])…`. No host-builtin intersection
  (`getHostBuiltinToolNames` / `PI_BUILTIN_TOOL_NAMES` → 0 matches).
- **Agent-definition parser** — the one removed-field throw is still `fallbackModels`
  (`src/agents/agents.js` ~line 1861); `completionGuard` appears nowhere (0 matches).
- **Package agent discovery unchanged** — `src/agents/agents.js::collectPackageSubagentPaths`
  gathers the project root plus `<project>/.pi/npm/node_modules` and `<agentDir>/npm/node_modules`;
  `extractSubagentPathsFromPackageRoot` reads the top-level `"pi-subagents"` record;
  `src/agents/agent-selection.js::mergeAgentsForScope` keeps `builtin < package < user < project`;
  `skillPath` resolves against `path.dirname(agent.filePath)` (`src/runs/foreground/execution.js`
  ~line 1647, `src/api/preflight.js` ~line 184) and `src/agents/skills.js` skips a missing entry
  (`if (!fs.existsSync(resolvedFile)) return;`).
- **Acceptance inference** — `src/runs/shared/acceptance.js::inferLevel` keys on a declared
  `acceptanceRole`; perk's waves still bypass it with `WAVE_ACCEPTANCE = {level: "none"}`.
- **The Pi 0.87 fork-context repair is in the artifact** (since 0.71.0) — `context_edit` handling
  in `src/shared/fork-context.js` (~line 57) and `src/shared/pruned-fork.js` (~lines 99, 210).
  perk children still spawn `context: "fresh"` (`extension/waves/transport.ts`) — adopting fork
  context is not in scope here.
- **The `subagents_enable` loader** — `src/extension/tool-activation.js`: `session_start` /
  `session_tree` replay the recorded selection; `before_agent_start` re-adds `subagents_enable`
  to `selectedTools` and the active set — the shape `extension/substrate/toolGating.ts`'s
  `LAZY_TOOL_LOADERS` comment describes, unchanged.

The 0.71.0 → 0.73.1 `CHANGELOG.md` deltas and their perk meaning:

- **0.73.1 — `advertised_subagents` prompt section** (replaces the system-prompt rewrite):
  `src/extension/index.js` (~line 788) sets `event.systemPromptOptions.sections.advertised_subagents`
  in its `before_agent_start` when `subagent` is selected. perk never reads or writes
  `systemPromptOptions.sections`, and its context-injection hooks strip only perk's own
  customTypes — untouched.
- **0.73.0 — `failureKind` on failed workflows** — written as `status.workflow.failureKind`
  (`subagent-executor.js` ~line 5653) and in foreground `details.workflow`. perk's
  `rpcAdapter.readAggregate` reads only `state`, `error` and `workflow.value` from `status.json`
  and ignores other keys, so a wave-level `run-failed` classification is unaffected.
- **0.73.0 — result caps** — `formatWorkflowResultText` (`subagent-executor.js` ~line 3214) caps
  the foreground Return/Emitted/Console *display text* at `DEFAULT_MAX_OUTPUT` (200 KB / 5000
  lines, `src/shared/types.js`); the terminal `status.json` write stores the uncut
  `workflow: { value: workflow.value, … }` (~line 5608). perk collects from `status.json →
  workflow.value`, so its reports are never truncated by the cap.
- **0.73.0 — `validate` / pre-launch agent-name check** — a misspelled literal agent name now fails
  before any child starts. perk's rendered scripts name agents that ship in the perk package; a
  wrong name would now fail the wave earlier, never differently.
- **0.72.0** — TypeBox is provided by Pi instead of bundled (pi-subagents now imports the host's
  `typebox`, which the host-SDK bridge census already carries: `typebox`, `typebox/compile`,
  `typebox/value`); startup no longer waits on global agent discovery (the first agent prompt and
  `subagents_enable` still wait); `subagents_enable` ignores extra arguments. No perk-side change.
- **0.71.0** (already recorded at the 0.71.0 re-read) — validated `structured_output` survives a
  later error/abort; RPC `cost`; the fork-context repair; `subagent` hidden behind
  `subagents_enable`.

## Decisions

- **pi-subagents 0.74.0 is not adopted.** Its release notes remove `workflowScript` /
  `workflowScriptPath` ("RPC `spawn` callers: pass inline script text as `script`"), reserve
  `chain`/`tasks`, and make children follow project trust. perk's wave module renders
  `workflowScript` (`extension/waves/reportWave.ts`) and `rpcAdapter.spawn` forwards the params
  unchanged, so every perk wave would fail on a fresh 0.74.0 install. The migration is a recorded
  follow-up.
- **Consumers are pinned to `npm:pi-subagents@0.73.1`** (`SUBAGENTS_PACKAGE` in
  `src/perk/convergence/init/settings.py`). Before this change `perk init` wrote the unversioned
  `npm:pi-subagents`, and Pi's `installedNpmMatchesConfiguredVersion` (pi-coding-agent 0.99.2
  `package-manager.ts`) accepts any installed version for an unranged source but reinstalls a
  ranged one that no longer matches — so a fresh consumer resolved latest (0.74.0) while existing
  installs were only accidentally safe. `_merge_static_packages` now version-reconciles every
  version-carrying desired spec forward (`_reconcile_pinned_entry`), so `perk init` rewrites an
  unversioned or stale entry in place and `perk doctor` reports it as `settings-wiring` drift that
  `--fix` repairs (contracts §8.6a).
- **The guidance stamp and the settings pin are distinct facts** — what perk's guidance was
  verified against vs. what consumers install. They coincide at 0.73.1 once the stamp moves.

## The live leg

Run from the implement session relaunched on the Pi 0.99.2 host, with the worktree-local
`.pi/npm` at pi-subagents 0.73.1. Every half is required.

- **Doctor half — PASS.** `uv run perk doctor --verbose` on the 0.99.2 host, before the stamp
  moved:

  ```
  ⚠ subagent-compat: pi-subagents 0.73.1 installed — perk's guidance was verified against 0.70.1 — npm:pi-subagents@0.73.1 is the settings pin (settings-wiring); … 0.74.0+ is known incompatible (it removed the workflowScript RPC spawn parameter perk's waves send)
  ✓ subagent-package-scope: pi-subagents configured in project scope only — report-only — the user-scope file is operator-owned
  ✓ ponytail-compat: Ponytail review skills compatible — …
  ```

  `settings-wiring` is ok on the pinned entry once `.pi/settings.json` regained the trailing newline
  a hand edit on `main` had dropped (pre-existing drift, repaired in this change). The remaining
  `config: config missing — .perk/local.toml` fail is the worktree environment — the per-user,
  gitignored overlay exists in the main checkout and is not materialized into worktrees.
- **Scout wave — PASS.** Under the owner's `/plan` toggle on the 0.99.2 host (the implement stage
  scopes `run_scout_wave` off), one `run_scout_wave` with two `perk.scout` briefs completed **2/2**
  with validated `structured_output` reports. The workflow-completion notice capped its return
  preview and pointed at `status.json` (`workflow.value`) — the 0.73.0 cap — while perk's tool
  collected both full reports from that file, as the source re-read predicted.
- **Conflict delegation — PASS (offline engine suite).**
  `extension/pi/v1/delivery/conflictResolverEngine.test.ts` (18 cases) passes on the 0.99.2 dist.
- **Plan-door browser wave — PENDING owner confirmation.** The planning session's
  `/plan-review-browser` draft-review wave ran on pi-subagents 0.73.1 to 4/4 lanes on the Pi 0.87.1
  host; the plan takes it as the plan-door half with that host caveat, for owner confirmation at
  review.
- **PR-door browser wave — PENDING.** The owner's `/pr-review-browser` on this change's PR (0.99.2
  host) to N/N with `perk:*` annotations posted.

## Falsified planning-time assumptions

- None in the source re-read: every runbook mechanic held at 0.73.1.
