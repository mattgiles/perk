# Re-verify: pi-subagents 0.75.0 — the `script` spawn key, the pin move, trust forwarding, and the headless exit

**Status:** dated evidence record. Measured 2026-10-05 (D2 00:48 local; D5, D7 and D8 13:20–13:59Z;
D6's plan-door leg 17:32–17:40Z and PR-door leg 19:04–19:09Z, appended by node 2.1); authored
2026-10-05. It implements plan #2659 (Objective #2656, node 1.2): perk's report-wave RPC
spawn moves from `workflowScript` to pi-subagents' `script` key, the consumer pin
(`SUBAGENTS_PACKAGE`) and the guidance stamp (`_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`) move from
0.73.1 to 0.75.0, and the 0.74.0 "known incompatible" doctor ceiling is retired. The templates are
[`pi-subagents-0.73.1-reverify.md`](pi-subagents-0.73.1-reverify.md) (matrix, source facts,
decisions, live leg) and [`pi-1.0.0-characterization.md`](pi-1.0.0-characterization.md) (verbatim
quotes, scrubbed environment, watchdog, teardown proof). The procedure is
`docs/developers/pi-subagents-reverify.md`.

**Verdict: PASS on the source, offline, doctor and scout halves and on the Pi 1.0.0 trust matrix;
plan-door browser half PASS (node 2.1's planning session, `perk objective plan 2656`, Pi 0.99.2
host); PR-door browser half PASS (PR #2663, Pi 0.99.2 host)** (D6).

- **The stamp moved on that evidence** (one commit with its test pin). The owner's
  `/pr-review-browser` on this change's PR is the merge gate: PASS ⇒ its outcome is appended here
  and the PR merges; a second FAIL holds the PR, reverts the stamp and its pin to 0.73.1, and
  rewrites the baseline-asserting prose. **Correction (2026-10-05):** #2661 merged on 2026-10-05
  (15:28Z) without the PR-door outcome. Node 2.1 (PR #2663) carried both browser legs
  (D6), and the docs that claimed a PR-door pass were corrected there.
- **The restriction packet reaches its consumer under trust forwarding.** In every trusted
  parent state measured on the 1.0.0 host (`--approve`, remembered trust, `defaultProjectTrust:
  "always"`, and the production SDK-worker factory), the child carried
  `perk.parent-restrictions/1` and printed perk's `[READ-ONLY MODE]` notice. An untrusted parent
  loads neither perk nor pi-subagents. The fix arm's ladder therefore stops at its first rung:
  **nothing adopted** (`requireForAllRunners` evaluated, below).
- **The A11x headless non-exit is answered and routed, not fixed.** The SDK worker parent exits
  after `dispose()` in every row. A print-mode CLI parent exits after a lane whose model does not
  resolve, but loops until killed after a lane refused at worktree admission. It loops the same
  way on the Pi 0.99.2 host and with perk absent, so it is neither a 1.0.0 regression nor
  perk-attributable: out of scope, filed as follow-up #2660.

Measured rows quote command output. Source-derived statements cite the installed compiled 0.75.0
(`.pi/npm/node_modules/pi-subagents/src/**/*.js` in `$WT`, the primary witness; upstream `.ts`
module names are used where the anchor survives compilation) or Pi `<path>@v1.0.0` in the tagged
library mirror (`docs/library/source-code/github.com/earendil-works/pi`, tag `v1.0.0` =
`a13d35a742c6ef8462812a28fbe1d8c8b7431c32`, read with `git show v1.0.0:<path>`). A passing test is
never quoted as observed live behaviour.

**Path abbreviations in quotes:** `$MAIN` = `/Users/mattgiles/dev/github/mattgiles/perk`.
`$WT` = the implement worktree, `$MAIN/.worktrees/plan-2659` (D2–D5; the plan's D7 text also
says `$WT` for the throwaway — this record writes `$TW` there to keep the two apart).
`$TW` = the throwaway detached worktree `$MAIN/.worktrees/pi-subagents-0.75.0-reverify`.
`$SCRATCH` = `$TW/.perk-characterization`. `$AUTHED`, `$HERMETIC` and `$EMPTY` are the D7
throwaway dirs (`/var/folders/90/…/T/perk-pi1x-{authed,hermetic,emptyroot}.*`); `$D5AUTHED` and
`$D5SCRATCH` are D5's (`…/T/perk-d5-{authed,scratch}.*`). `$MODEL` = `anthropic/claude-opus-5-5`.
Apart from these substitutions, quotes are verbatim.

## The matrix

| Component | Version / value | Provenance |
|---|---|---|
| perk | 3.9.0 — producer migration + pin at `99c1a529`, comment fix `9aa2ad10` (the throwaway's HEAD), stamp at `415390ba`, prose at `b143af81` | `git log --oneline` on branch `plan-2659` |
| Pi (host, D2–D5, X2) | 0.99.2, `~/.local/share/mise/installs/node/26.3.0/bin/pi` | `which pi`, `pi --version` |
| Pi (throwaway, D7) | 1.0.0 — `@earendil-works/{pi-coding-agent,pi-ai,pi-agent-core,pi-tui,pi-client,pi-server}` exact 1.0.0 as throwaway edits (`package-lock.json` 453 lines changed, as in 1.1); `which pi` = `$TW/node_modules/.bin/pi` → `$TW/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js` | `npm install --save-dev --save-exact …@1.0.0`; each `package.json` `version` |
| pi-subagents (installed, now pinned) | 0.75.0 in `$WT` (independent copy of `.pi/npm`, inode 461007794, link count 1) and in `$TW` (independent copy, inode 461387694) | `package.json` after `rm -rf` + `npm install pi-subagents@0.75.0 --prefix .pi/npm --legacy-peer-deps` |
| pi-subagents (main checkout) | 0.73.1, untouched during D2–D8 | `$MAIN/.pi/npm/node_modules/pi-subagents/package.json` |
| Browser-door host, plan-door (D6) | Pi 0.99.2 PATH host (`~/.local/share/mise/installs/node/26.3.0/bin/pi`); pi-subagents 0.75.0 in `$MAIN/.pi/npm` (after #2661 merged); perk 3.9.0 at the planning session's HEAD `9c4e52c0` (#2661's merge commit); session format `version: 3` | `which pi`, `pi --version`, `$MAIN/.pi/npm/node_modules/pi-subagents/package.json` at planning time; the session header and its `perk:workflow-state` `perk_version` |
| Browser-door host, PR-door (D6) | Pi 0.99.2 PATH host (`~/.local/share/mise/installs/node/26.3.0/bin/pi`); pi-subagents 0.75.0 in the implement worktree's own `.pi/npm` (`$MAIN/.worktrees/plan-2662`); perk 3.9.0 at the reviewed head `a9dfecdc`; doctor `✓ subagent-compat: pi-subagents 0.75.0 — the guidance-verified version — report-only — the install is pinned by settings-wiring (npm:pi-subagents@0.75.0)` | from the implement worktree: `node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version"` → `0.75.0`; `which pi`, `pi --version` → `0.99.2`; `uv run perk doctor --verbose`; the session's `perk:workflow-state` `perk_version` |
| npm registry (D7 start, 2026-10-05T13:31Z) | pi-coding-agent ends `1.0.1, 1.0.2, 1.0.3`; pi-subagents ends `0.75.0, 0.76.0` — **0.76.0 is published and NOT adopted**; the subject stays exact 0.75.0 | `npm view … versions --json` |
| node | v26.3.0 | `node --version` |
| `$MODEL` | `anthropic/claude-opus-5-5` (lane and parent model for every spawn leg) | `$PI_PROVIDER/$PI_MODEL` of the implement session |
| MAIN staging hashes (D2 before, D2 after the install, D7 start, D8 after teardown: identical) | `package.json` `eb487ac3…8444ad0`; `package-lock.json` `3efbddc2…ec93f6c6`; `node_modules/.package-lock.json` `a44bd4b4…eeb00fd`; `node_modules/pi-subagents/package.json` `12ddb985…7e193` | `shasum -a 256` |
| Previous baseline | 0.73.1 (last source re-read 0.73.1) | `docs/learned/pi/subagents.md` § Sources before this pass |

## Source facts (D1 — the installed compiled 0.75.0)

The how-to's step-2 walk, re-read in `$WT/.pi/npm/node_modules/pi-subagents/`:

- **The RPC spawn key** — `src/extension/rpc.js::spawnParams` (line 375): `const { script,
  ...input } = assertRecordParams(params, "spawn");` then `if (Object.hasOwn(input,
  "workflowScript")) throw new SubagentRpcError("invalid_params", "RPC spawn workflowScript was
  removed; pass inline script text as script.");` (the same for `workflowScriptPath`); a
  non-empty string is required, `script` cannot be combined with `workflow`, and `input.workflowScript
  = script;` hands the text to the executor's internal carrier. Identical at raw tag `v0.75.0`
  (`src/extension/rpc.ts:523–546`).
- **Public normalization** — `src/extension/public-execution.js::normalizePublicSubagentExecution`
  rejects only resource/permit, internal fan-out and internal workflow-child fields, legacy
  orchestration inputs and removed forms. None of the fields perk sends (`mission`, `context`,
  `acceptance`, `intercomBridge`, `outputSchema`, `model`, `timeoutMs`, `async`) is among them.
- **Workflow defaults** — `src/runs/foreground/subagent-executor.js`: the async workflow path
  (line 5311) strips `args`, `action`, `agent`, `task`, `timeoutMs`, `mission`, … from the request
  and keeps the rest as `workflowChildDefaults`; `prepareWorkflowLaunchParams` (line 4348)
  spreads `...workflowDefaults` then `...childParams`, so `acceptance`, `intercomBridge`,
  `outputSchema`, `model` and `context` still reach every child.
- **Progress updates discarded** — `src/intercom/native-supervisor-channel.js:114`
  `const expectsReply = params.reason !== "progress_update";`; `src/intercom/intercom-bridge.js:115`
  returns `"bridge mode is off"`.
- **Wake rules** — `src/runs/background/notify.js:235–238`
  `incrementalChildCompletionTriggersTurn`: `if (child.workflowRunning && child.outcome ===
  "completed") return false;` — every other outcome wakes (unless the schedule origin is quiet).
  It is used at `subagent-executor.js:5530`, which sends the `subagent-incremental-child-notify`
  custom message with `{ triggerTurn: … }`. This is the failed-child wake the A11x rows exercise.
- **Removed-field throw** — still only `fallbackModels` (`src/agents/agents.js:1931`); no perk
  def carries it (`grep -l fallbackModels agents/*.md` → none).
- **Package agent discovery** — `src/agents/agents.js::collectPackageSubagentPaths` (line 325)
  gathers the project root (scope `root`), `<project>/.pi/npm/node_modules` and
  `<agentDir>/npm/node_modules`; `extractSubagentPathsFromPackageRoot` (line 236) reads the
  top-level `"pi-subagents"` record; `src/agents/agent-selection.js::mergeAgentsForScope` keeps
  `builtin < package < user < project`; `skillPath` resolves against `path.dirname(agent.filePath)`
  (`src/runs/foreground/execution.js:1668`, `src/api/preflight.js:197`) and
  `src/agents/skills.js:402` skips a missing entry.
- **Child tool plan** — `src/runs/shared/child-tool-plan.js:234` `internalTools =
  (input.structuredOutput ? ["structured_output"] : [])…`: `structured_output` stays a top-level
  child tool (0.74.0 only removed it from codemode scripts, and perk's gate suspends codemode
  under the floor anyway). No host-builtin intersection (`getHostBuiltinToolNames` /
  `PI_BUILTIN_TOOL_NAMES` → 0 matches).
- **Acceptance** — `src/runs/shared/acceptance.js::inferLevel` (line 53) keys on a declared
  `acceptanceRole`; `explicitAcceptanceCanDisable` (line 202) still accepts `{level: "none",
  reason}` with a non-empty reason (`WAVE_ACCEPTANCE`).
- **Fork-context repair present** — `context_edit` handling in `src/shared/fork-context.js:57`
  and `src/shared/pruned-fork.js:99,210`; perk children stay on `context: "fresh"`.
- **The child prompt-runtime path** — `src/runs/shared/child-session.js:76`
  `const CHILD_PROMPT_RUNTIME_EXTENSION_PATH = "<inline:pi-subagents:prompt-runtime>";` equals
  perk's `extension/substrate/toolPolicy.ts::SYNTHETIC_PATH_TOOL_POLICY` key. New in 0.75.0: a
  second inline extension, `pi-subagents:commands` (`child-session.js:357`), which registers a
  wrapped `bash` and `subagent_command`. It loads only when the child's tools include both `bash`
  and `subagent_command` (`child-session.js:322–326`). No perk agent declares `subagent_command`
  (`grep -n '^tools:' agents/*.md .pi/agents/perk-dev/*.md`), so it never loads in a perk child
  and the gate needs no new row. A future perk agent that declared it would need one.
- **`toolActivation`** — `src/extension/tool-activation.js`: `eager` returns before registering
  the loader; `dynamic` always selects it; `auto` goes eager only for an empty session on a model
  that cannot add tools mid-conversation, and otherwise behaves like `dynamic`. The loader's
  `before_agent_start` pushes `subagents_enable` into `selectedTools` only when it is selected and
  absent. `extension/substrate/ownNamesActivation.test.ts` models the loader-present
  (`dynamic`) shape. The eager shapes register or select no loader, and perk's own-names-only
  reconciliation (`toolPolicy.ts::reconcileTarget` + `hiddenDeclarationsFor`) touches no
  pi-subagents name in any mode. Contracts §8.40's "owners edit `selectedTools` only when their
  loader is absent" holds at 0.75.0 and was re-dated.
- **`./node` optional** (B3 re-read) — `src/runs/background/runner-aliases.js:20`
  `{ specifier: "@earendil-works/pi-agent-core/node", …, optional: true }` and line 146–147: an
  optional subpath the package does not declare is skipped; a declared but missing file still
  fails.
- **Reserved resource names** — `src/workflows/workflow-resources.js:174`
  `STRUCTURED_WORKFLOW_RESOURCE_NAMES = ["tasks", "chain"]`, checked only in
  `registerWorkflowResource` (line 40; exported as `pi-subagents/workflow-resources`). perk never
  registers a workflow resource, and `reports` is a script-local binding in perk's rendered
  script (`const reports = await runs.all(…)`), not a resource name. No collision; a code comment
  at `renderWaveScript` records it.
- **`requireForAllRunners`** — `src/shared/required-child-extensions.js::registerRequiredChildExtensions`
  (line 60) takes `{sessionId, extensions: [{id, path}], requireForAllRunners?}` and is exported
  as `pi-subagents/required-child-extensions` (`package.json` `exports`). A required extension is
  loaded into each native child from its explicit path, and a load error refuses the launch
  (`child-session.js`: `Required child extension failed to load: …`). Since 0.75.0 a
  `session_start` throw also refuses it. `requireForAllRunners: true` additionally refuses
  non-native runners and machine placements (`assertRequiredChildExtensionsAdmitted`, line 82).
  Every perk lane is a native Pi child, so the flag adds no refusal today. Adopting the
  registration would need a bare `pi-subagents/required-child-extensions` import, which
  `extension/bareImportGuard.test.ts` forbids. **Evaluated, not adopted:** the trust rows passed
  (the fix arm's first rung is reached only on a FAIL).
- **Workflow reuse** — `src/workflows/workflow-reuse.js::findWorkflowReuseSource` (line 72) walks
  the same session's recent terminal runs. It takes the newest workflow with the same
  `scriptDigest`/`argsDigest`, and reuses it only when its `stopCause` is `runtime-replaced`
  (`/reload`, a resume, a pi-web project switch). `matchWorkflowReuse` reuses only succeeded
  settled children and waits on started ones; failed or stopped children run again. **perk's
  cancel/collect/reload semantics:** perk's `ReportWave` pending map is per-activation, so a wave
  launched before `/reload` cannot be collected afterwards — unchanged. The one freshness nuance
  is that an identical relaunch after `/reload` (same rendered script and args) reuses the replaced
  run's finished lanes instead of re-running them.
- **Stop** — `src/extension/rpc.js::stopAsyncRun` (line 441) resolves `id`/`runId`/`dir`.
  0.74.0 fixed stops by short id, tool-call id or directory; perk always stops by the full
  `asyncId` (`rpcAdapter.ts`: `call("stop", { id: handle.asyncId }, …)`), which was never broken.
- **Headless auto-drain** — `src/extension/index.js:686–689`: on `agent_end` with `!ctx.hasUI`,
  `drainOutstandingWork` (`src/runs/background/auto-drain.js`, default 30 min) waits with
  `failOnFailedRuns: true` and throws when a run failed.
- **`disabledFeatures`** — `src/shared/disabled-features.js::disabledFeatureUseError` (line 85).
  With `workflow-scripts` disabled, the RPC refuses before normalization with `RPC spawn workflow
  scripts are disabled by config disabledFeatures "workflow-scripts".` (`rpc.js:392`). The RPC's
  `executePublic` (`subagent-executor.js:7394`) also refuses any disabled feature whose parameter
  is present. perk sends `mission: false`, so `missions` refuses every wave. `admitEnabledWorkflowChildren`
  (line 4639) refuses a child whose params carry a disabled parameter, and every perk lane carries
  `extensionBindings`, so `extension-bindings` refuses every lane before launch (fail closed, never an
  unfloored child). perk surfaces the engine's `code: message` verbatim as the `spawn-failed`
  or run-failed detail.
- **Trust forwarding** — `subagent-executor.js:303–304` `sessionProjectTrust(ctx)` returns
  `ctx.isProjectTrusted()`; the async path carries it (`async-execution.js:1273,1881` →
  `subagent-runner.js` → `child-launch.js:213`) into `child-session.js:327`
  `pi.SettingsManager.create(launch.cwd, agentDir, { projectTrusted: launch.projectTrusted })`.
  Pi's `SettingsManager.create` defaults `projectTrusted ?? true`
  (`packages/coding-agent/src/core/settings-manager.ts@v1.0.0:442`; dist 0.99.2
  `settings-manager.js:214` the same).
- **Pi package root** — `src/runs/background/async-execution.js:75–76`
  `resolveAsyncPiPackageRoot` = `resolvePiPackageRoot()` (the argv walk) ||
  `PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT` || installed-package resolution — the basis of W1d.

Release notes (`CHANGELOG.md`, `## [0.75.0] - 2026-10-02`, `## [0.74.0] - 2026-09-30`), as far as
perk is concerned. 0.74.0 brings the `workflow` field and the `script` RPC key, children that
follow the parent's project trust, workflow survival and reuse across `/reload`, `disabledFeatures`,
`toolActivation`, short-id stop fixes, and codemode no longer able to call the subagent tools.
0.75.0 brings background children on Pi 1.0.0, `requireForAllRunners`, required extensions that
refuse on a `session_start` throw, virtual-model children, and async runs recorded in
`run-history.jsonl`. No perk-side change follows beyond the key migration.

## Decisions

- **Migrate, no shim.** `WaveSpawnParams.script` and `WaveScriptSpec.script` replace
  `workflowScript`; no retry under a second parameter dialect. The fake responder mirrors 0.75.0's
  `Object.hasOwn` rejection. A boundary regression (`reportWaveRpc.test.ts`) pins that the producer
  sends `script` with no `workflowScript` key, and that a hand-built `workflowScript` spawn, with
  either a value or `undefined`, is rejected verbatim. A 0.73.1 engine fails a `script` spawn
  loudly (its `spawnParams` has no `script` handling), so pin and producer must travel together.
- **Pin 0.75.0** (`SUBAGENTS_PACKAGE`, `.pi/settings.json`); delete the 0.74.0 ceiling constant
  and its warn clause. No replacement floor constant: the pin plus Pi's reinstall of a ranged
  source (`package-manager.ts@v1.0.0:1507` `installedNpmMatchesConfiguredVersion` →
  `satisfies(installedVersion, source.range)`) is the floor. Four version facts stay separate: the
  dev pins (0.99.2, untouched), the host floor, the supplier pin and the guidance stamp. The
  `borrowed-packages` capability summary carries no version (unchanged).
- **Model-facing `workflow: true` is never used** for perk's machine-generated waves; the docs
  that describe a user's own `subagent` calls now show the `workflow` forms.
- **Trust:** nothing adopted (T-rows below). `requireForAllRunners` was evaluated (source facts).
- **A11x:** routed (X-rows below).
- **Retired the prose-map `workflow-property` selector path.** Its only production input was the
  transport field, and it was never model-facing prose.

## The live leg

### Offline, doctor, scout (D2–D5; implement worktree, Pi 0.99.2 host)

| Row | Procedure | Observation | Verdict |
|---|---|---|---|
| D2 | `rm -rf "$WT/.pi/npm" && cp -R "$MAIN/.pi/npm" "$WT/.pi/npm"`; `rm -rf …/pi-subagents`; `npm install pi-subagents@0.75.0 --prefix .pi/npm --legacy-peer-deps` | `added 1 package, and changed 1 package in 42s`; installed `0.75.0`; `$WT/.pi/npm/package.json` inode 461007794 (link count 1; main's 147622898, link count 15, before); MAIN hashes identical (`MAIN-HASHES-IDENTICAL`); main stays `0.73.1`. The owner then quit and resumed the session (`perk resume`) | PASS |
| D3 | one run-all `run_ci` | `perk CI: all checks passed.` — `lint-py`, `lint-js`, `typecheck-py`, `typecheck-js`, `test-py-fast` (242 s), `test-py-slow` (131 s; runs `test_native_sdk_bridge_live.py` — installed == pin), `test-js` (158 s) green; `typecheck-prose-review`, `docs-check`, `changelog-check` glob-skipped | PASS |
| D3 | `node --test extension/substrate/nativeSdkBridge.test.ts` | `✔ census drift guard: the installed consumers import exactly NATIVE_SDK_CENSUS (1917.246458ms)`; `ℹ tests 32` / `ℹ pass 32` / `ℹ fail 0` / `ℹ skipped 0` | PASS |
| D4a | `uv run perk doctor --verbose`, before the stamp moved | `⚠ subagent-compat: pi-subagents 0.75.0 installed — perk's guidance was verified against 0.73.1 — npm:pi-subagents@0.75.0 is the settings pin (settings-wiring); mechanics perk's guidance leans on are source-read-derived at the verified version and unverified at the installed one` (no ceiling clause); `✓ settings-wiring: settings-wiring converged`; `✓ artifact-health: 7 managed artifacts up-to-date` | PASS (expected warn) |
| D4b | same, after the verification commit (`415390ba`) | `✓ subagent-compat: pi-subagents 0.75.0 — the guidance-verified version — report-only — the install is pinned by settings-wiring (npm:pi-subagents@0.75.0)`; `✓ settings-wiring: settings-wiring converged` | PASS |
| D5 | bare, unscoped session in `$WT`: `$SCRUB PERK_SKIP_VERSION_CHECK=1 PI_CODING_AGENT_DIR=$D5AUTHED PI_SUBAGENTS_TEMP_ROOT=$D5SCRATCH/subagents-tmp pi --approve --model $MODEL --mode json -p "<prompt>"` (one `run_scout_wave`, two named read-only briefs) | first headless attempt; the model called `run_scout_wave` once with `spawn-key` and `fake-rejection`; tool result `details.ok: true`, 2 reports, attempt `runId` `1b251862-6ac3-4703-8a80-66761fdd04fb`, `state: "complete"`, both children `success: true`, `agent: "perk.scout"`; `status.json` `complete`/`workflow`, `workflow.value` two `{ok: true, error: null, report: {…}}` rows; each child's `output-0.log` carries `[READ-ONLY MODE] (unscoped)` and its descriptor `"extensionBindings": {"perk.parent-restrictions/1": {"readOnly": true}}`; the model's final line: "The wave was complete: it returned 2 reports and 0 failures."; exit 0 after 58 s; stderr 0 bytes | PASS |

`config: config missing — .perk/local.toml` is the one ✗ in both doctor runs: the per-user
gitignored overlay is not materialized into worktrees (pre-existing; the 0.73.1 and 1.1 records
classify the same red).

The D5 reports themselves (untrusted data, checked against the checkout) read
`extension/waves/transport.ts:150` — "The WaveSpawnParams field carrying inline script text is
`script`." — and `extension/testing/fakeSubagents.ts:152-160` — error code `invalid_params`,
message "RPC spawn workflowScript was removed; pass inline script text as script.". Both match
the files.

### The 1.0.0 throwaway (D7)

Scaffold: `git worktree add --detach "$TW" HEAD` (HEAD `9aa2ad10`, the committed migration +
pin), `uv sync --all-packages && npm ci`, the six dev pins to exact 1.0.0, an independent
`cp -R "$MAIN/.pi/npm"` with pi-subagents reinstalled at 0.75.0 (MAIN hashes re-checked
unchanged), `PATH="$TW/node_modules/.bin:$PATH"`, `$AUTHED` = a throwaway agent dir holding a
copy of `auth.json` only. `$HERMETIC` was created but no row needed it. Every probe row ran under
`run-bounded.sh` (GRACE 60 s, CAP 330 s) with `$SCRUB PERK_SKIP_VERSION_CHECK=1
PI_CODING_AGENT_DIR=$AUTHED PI_SUBAGENTS_TEMP_ROOT=$SCRATCH/subagents-tmp`. Row order: T, W, X.

#### Trust matrix — restriction-packet delivery

CLI rows: `pi [trust flag] --mode json -e .perk-characterization/probe-spawn.ts -p "/probe-spawn
script $MODEL restricted"` on the 1.0.0 host.

| Row | Parent trust state | Observation | Verdict |
|---|---|---|---|
| T1 | `--approve` | spawn `success: true` (handle `77cddcf3…`, `scriptDigest` `0d3a89d8…`); workflow `complete`, lane `{"key": "probe", "ok": true, "error": null, "report": null}`; child `17047c59…` runner `pid` 47415, instance `69b6b8aa…`, `status.json` `complete`; descriptor `"extensionBindings": {"perk.parent-restrictions/1": {"readOnly": true}}`; `output-0.log` (1616 bytes) carries `[READ-ONLY MODE] (unscoped)` before `OK`; `launchResolvedExtensions.effective: ["sha256:a2912d16496611db"]`; 0 `Failed to load extension`; exit 0 after 35 s (first launch in the throwaway) | PASS |
| T2 | remembered trust: no flag; `$AUTHED/trust.json` = `{"$TW": true}` (key = `realpathSync($TW)`, Pi's `canonicalizePath`) | key form self-validated first: `pi --mode json -p /perk-selfcheck` (no flag) → `perk: selfcheck — 3.9.0: ok; … bridge=installed`, per source `npm:pi-subagents@0.75.0=3`. The row: child `a00c5789…` (pid 47941), lane `ok: true`, bindings + notice as T1; exit 0 after 8 s | PASS |
| T3 | `defaultProjectTrust: "always"`: no flag, `trust.json` removed, `$AUTHED/settings.json` = `{"defaultProjectTrust": "always"}` | child `afc44f1f…` (pid 48260), lane `ok: true`, bindings + notice as T1; no `trust.json` written; exit 0 after 8 s | PASS |
| T4 | negative: `--no-approve` (settings removed) | `probe: ping {"error": {"code": "probe-timeout", "message": "ping"}}` and the same for `spawn` — pi-subagents, a project package, did not load; no run directory. `pi --no-approve --mode json -p /perk-selfcheck`: no `perk: selfcheck` line (perk not loaded); in print mode the unknown command went to the model as a plain prompt, which explored read-only (`rg`, `read`, a nested `pi`) until the 120 s cap killed the group (exit 143) | PASS (structural negative) |
| T5 | session-only trust | Source-derived. `trust-manager.ts@v1.0.0:85` offers `{ label: "Trust (this session only)", trusted: true, updates: [] }`. `project-trust.ts@v1.0.0:92` calls `saveProjectTrustPromptResult`, which writes nothing for empty `updates` (line 40–44), and returns `selected.trusted`. The same `SettingsManager` trust then follows, as in T1 | PASS (source) |
| T6 | the SDK worker | Source-derived. `extension/worker/sdkAdapter.ts::constructRuntime` calls `SettingsManager.create(worktree, agentDir)` with no trust option, which defaults to `true` (`settings-manager.ts@v1.0.0:442`). `agent-session.js:2719` `isProjectTrusted: () => this.settingsManager.isProjectTrusted()`, so 0.75.0 forwards `true`. W2 is the measured row | PASS (source) |

Resolution order (`project-trust.ts@v1.0.0:46–96`): override (`--approve`/`--no-approve`) →
no trust-requiring project resources ⇒ trusted → `project_trust` extension event → `trust.json`
→ `defaultProjectTrust` → no UI ⇒ untrusted → the interactive prompt (including the session-only
options).

**Fix arm: PASS → nothing adopted.** Every trusted state delivered the packet into a child that
loaded perk and applied the floor, and the untrusted state hosts no perk wave at all.

#### SDK-worker rows (the production factory)

The driver `$SCRATCH/worker-probe.ts` (verbatim below) imports `$TW/extension/worker/sdkAdapter.ts`
and does `resolveWorkerModel($MODEL)` → `defaultCreateRuntime($TW, selection)` →
`createDriveSession(runtime, listener).bind()` → poll `PERK_PROBE_DONE` → `dispose()`. The probe
was copied to `$TW/.pi/extensions/` (native project-extension discovery) for the W rows and
removed afterwards. It auto-fires from `session_start` via
`PERK_PROBE_AUTO`. Run as `node worker-probe.ts` under `run-bounded-worker.sh` (the watchdog keyed
on `worker-probe: disposed|fatal`). Scope: the production worker factory, the explicit headless
bind and pi-subagents' in-process workflow host, without `runStage`'s model loop; the remote
worker adds the budget watchdog and terminal predicates on top.

| Row | Lane | Observation | Verdict |
|---|---|---|---|
| W2 | `script $MODEL restricted` | `perk worker: model anthropic/claude-opus-5-5`; `bound 56 registered tools`; spawn `success: true` (handle `cea4227d…`); workflow `complete`, lane `ok: true`; child `1c54b683…` (pid 49373) descriptor bindings + `[READ-ONLY MODE] (unscoped)` notice; `disposed` at +22639 ms; two `perk worker: extension error — [object Object]` lines; exit 0 after 35 s wall (cold start). Re-run with the diagnostic driver (W2b): child `1a60b2cd…` (pid 50277), same evidence; after `disposed` (+7851 ms) the pair `{extensionPath: <boundary>, event: turn_end, error: turn_end could not resolve the persisted assistant entry ID}` / `{extensionPath: $TW/extension/index.ts, event: agent_settled, error: This extension ctx is stale after session replacement or reload. …}`, then `process-exit code=0` at +7852 ms | PASS |
| W1 | `script $MODEL badmodel` (per-item `model: "perk-probe/does-not-exist"`) | spawn `success: true` (handle `96ec76c9…`); workflow `complete`; lane `{"ok": false, "error": "Unknown subagent model 'perk-probe/does-not-exist' in the active Pi model registry."}`; **no child directory at all** (the workflow dir only: `control events.jsonl run-fanout-budget.json status.json workflow-children.jsonl workflow-receipt.json`); bind → probe → dispose completed (`disposed` +4816 ms); four extension-error lines; exit 0 after 22 s wall. Diagnostic re-runs W1b/W1c: `disposed` +4959 / +4827 ms, `process-exit code=0` +11406 / +10146 ms; W1c decodes the four as two pairs — `<boundary>` `turn_end` + perk stale ctx on **`context`**, then `<boundary>` `turn_end` + perk stale ctx on `agent_settled` (a turn began after `dispose()`); no stage event observed before `dispose()` | OBSERVED (exits) |
| W1d | `script $MODEL` with `PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT=$EMPTY` (empty `mkdtemp`; the argv walk finds no Pi package for a driver under the repo) | the A11 signature: lane `ok: false`, `Run fan-out: 1/64 used, 63 remaining` / `Failed to start async run 'd5457cc3-…': Background children require the host npm package (@earendil-works/pi-coding-agent) with its dependencies; $EMPTY does not provide @earendil-works/pi-coding-agent, @earendil-works/pi-agent-core, @earendil-works/pi-agent-core/node, …`; child dir `d5457cc3…` holds only `recovery-descriptor.json` + `run-fanout-budget.json` (pre-spawn); `disposed` +5140 ms, the same two pairs, `process-exit code=0` +13841 ms | OBSERVED (exits) |

**A11x, worker parent: it exits.** After a pre-spawn lane failure of either shape, the production
factory's parent completes bind → probe → `dispose()` and exits 0 within 5–9 s of `dispose()`.
Its stderr shows one wake turn more than a completed lane does. No extra turn was observed before
`dispose()`. Whether a post-dispose turn sends a provider request was not established: the session
is disposed, and the driver no longer observes events.

#### A11x CLI rows (print-mode parent)

Glossary: a **pre-spawn lane failure** is a `runs.all` item that fails in the parent before any
runner process exists (1.1's A11: the child directory holds only `recovery-descriptor.json` /
`run-fanout-budget.json`, or — measured here — no child directory at all).

| Row | Host / method | Observation | Verdict |
|---|---|---|---|
| X1 | 1.0.0, `--approve`, `badmodel` | lane `ok: false`, `Unknown subagent model …`, no child directory (pre-spawn); one `subagent-incremental-child-notify` custom message (the failed-child wake); 4 `turn_end could not resolve the persisted assistant entry ID`, 6 perk stale-ctx, 2 `perk: loadout presentation failed`; 0 assistant `message_start`; **exit 0 after 53 s**. Replicate X1-r2: 2 / 2 / 0, exit 0 after 14 s | OBSERVED (exits) |
| X1b | 1.0.0, `--approve`, `missingbase` (per-item `worktree: true, baseRef: "refs/heads/perk-probe-missing"`) | lane `ok: false`, `Worktree admission failed for 'probe' at $TW: worktree isolation requires a clean git working tree. …` (the throwaway's dev-pin edits make the tree dirty) — no child directory (pre-spawn); the wake message, then one assistant `message_start`; stderr loops 21× `turn_end could not resolve …`, 21× perk stale-ctx, 20× `perk: loadout presentation failed`; `watchdog: pi still running 60s after the probe's terminal line (elapsed 65s) — TERM pgid 51281`; exit 143 after 70 s. Replicate X1b-r2: 19 / 37 / 18, watchdog, exit 143 | OBSERVED (does not exit) |
| X2 | **0.99.2 PATH host** control, `--approve`, `missingbase` | `which pi` = mise 0.99.2; same lane error; 20 `turn_end …`, 39 stale-ctx, 19 loadout-presentation failures; watchdog TERM at 65 s; exit 143 | OBSERVED (does not exit) |
| X3 | 1.0.0, **perk absent** (throwaway edit dropping `".."` from `$TW/.pi/settings.json`; pi-subagents kept), `--approve`, `missingbase` | same lane error; **18 `turn_end could not resolve …` and nothing else** (0 perk lines — perk not loaded); watchdog TERM at 68 s; exit 143. Restored with `git -C "$TW" checkout -- .pi/settings.json`; `pi --approve --mode json -p /perk-selfcheck` → `perk: selfcheck — 3.9.0: ok; …`, per source `..=37 … npm:pi-subagents@0.75.0=3` | OBSERVED (does not exit) |

**A11x, CLI parent: it depends on the failure, and the loop is not perk's.** The failed-child
wake fires in every row (the custom message with `triggerTurn`). After a model-resolution failure
the parent runs a few post-command turns and exits. After a worktree-admission refusal it loops
until killed: on the 1.0.0 host, on the 0.99.2 host (X2), and with perk absent (X3). It is
therefore neither a Pi 1.0.0 regression nor perk-attributable. perk's stale-ctx lines (including
`prepareLoadout`'s `perk: loadout presentation failed`, `extension/substrate/toolGating.ts`) are a
symptom of the loop, not its cause: X3 loops with no perk handler present. **Routing (owner
decision): out of scope — follow-up.** A one-file perk guard would not stop the loop, so no fix
lands here. Follow-up #2660 references this record and also notes the worker's `[object Object]`
`onError` formatting (`extension/worker/sdkAdapter.ts`). A11's own trigger (0.73.1's `./node` refusal
on 1.0.0) is gone with 0.75.0 (B3, T1).

#### 1.1's rows this node owns — dispositions

| 1.1 row | Disposition |
|---|---|
| A10 (0.73.1 resolver `missing: [".../node"]`) | Resolved by the pin: 0.75.0's alias is optional (D1, B3 re-read); children start on 1.0.0 (T1 runner `pid` 47415) |
| A11 (0.73.1 real spawn refused pre-spawn on 1.0.0) | Resolved by the pin (T1–T3, W2 launch and complete) |
| D10 (= A10 + A11) | Resolved with them |
| A11x (headless parent did not exit after a refused lane) | Answered (W1/W1d exit; X1 exits; X1b/X2/X3 loop; not perk-attributable) and routed |
| B3 (0.75.0 `./node` optional) | Re-confirmed in source (`runner-aliases.js:20,146–147`) |
| B4 (0.75.0 rejects `workflowScript`) | Done: producer sends `script`; the fake mirrors the rejection; offline pins |
| B5a / B5b (0.75.0 launches + completes a child on 1.0.0) | Re-observed by T1 (runner start witness + `OK`) |
| B6 (packet under `--approve`) | Re-observed by T1 and extended to T2, T3, W2 |
| B7a (doctor warns with the 0.74.0+ ceiling text) | Retired: D4a's warn has no ceiling clause; D4b ✓ |

### Browser doors (D6)

**Appended 2026-10-05 (node 2.1, PR #2663).** #2661 merged before either browser leg was
recorded, so node 2.1 carried both. The instrument for each leg is three kinds of tool result in
the session JSONL. The launch tool's result carries the manifest (`launch.requested` /
`launch.runnable` / `launch.preflightFailures`) and the run handle. The collect tool's result
carries `complete`, `covered`, `failures` and `attempts`; collection settles the wave marker and
carries no delivery outcome. The per-angle `push_annotations` calls show `angle` and `replace` in
their arguments, and their receipts carry `pushed`, `held` and `held_batches`. PASS needs all of:
(1) every requested lane runnable with no preflight failure; (2) `complete: true`, N/N covered, no
failures; (3) exactly one `replace: true` push per covered angle, every receipt the ok arm with
`held == 0` and `held_batches == 0` (an empty replacement's `pushed: 0` is healthy); (4) the
browser decision after the last push receipt in file order; (5) the owner's observation of the
`perk:wave` marker and the annotations. A DENY is a valid decision: the leg measures the door, not
the verdict.

- **Plan-door browser wave — PASS.** Host: Pi 0.99.2 PATH host, pi-subagents 0.75.0 in
  `$MAIN/.pi/npm`, perk 3.9.0 at `9c4e52c0` (matrix). Session: node 2.1's planning session
  (`perk objective plan 2656`, run `01M46BHY259EYTNF86152ER374`, Pi session
  `01a10cb8-fb7c-716c-8602-f7c2d8194607`). Its JSONL is
  `$MAIN/.pi/agent/sessions/--Users-mattgiles-dev-github-mattgiles-perk--/2026-10-05T15-40-12-028Z_01a10cb8-fb7c-716c-8602-f7c2d8194607.jsonl`
  (211 lines, header `version: 3`, sha1 `39010981f2731c303ff6c7fefd9481bd531a40cd`). The
  `planning-session/main` artifact of `perk learn evidence --json`, run from the implement
  worktree, is a byte-identical copy. The leg is the first review round's `/plan-review-browser`,
  the only wave in the session; the second round (`plan_review`, line 205 → "plan APPROVED by
  reviewer." at line 211) ran none.
  - **Launch (criterion 1).** Line 178 calls `start_draft_review_wave {"angles": ["grounding",
    "decision-completeness", "risk"]}`. Its result (line 179, 17:32:57Z) reads "Draft-review
    workflow accepted with 4/4 post-preflight runnable lane(s) — grounding,
    decision-completeness, risk, ponytail (asyncId 8002b79a-4ef3-460a-8a1e-0131d3a76d0e)."
    `details.launch`: `requested` and `runnable` are both `["grounding",
    "decision-completeness", "risk", "ponytail"]`, and `preflightFailures` is `[]`.
  - **Collect (criterion 2).** Collection followed the matching workflow-completion notice (line
    185). The result (line 187, 17:37:29Z) reads "Draft-review wave complete: covered 4/4
    lane(s)." with `complete: true`, all four angles in `covered`, and `failures: []`. It records
    one attempt (`state: "complete"`) whose four `perk.draft-reviewer` children are each
    `success: true`.
  - **Delivery (criterion 3).** One assistant entry (line 188) carries four `push_annotations`
    calls, one per covered angle, each with `replace: true`. The receipts are lines 189–192
    (17:37:48Z), and each is the ok arm (`ok: true`, `mode: "plan"`, `skipped: []`):

    | Angle | Findings sent | Receipt | `pushed` | `held` | `held_batches` | `deleted` |
    |---|---|---|---|---|---|---|
    | grounding | 2 | "Annotations — perk:grounding: pushed 2." | 2 | 0 | 0 | 0 |
    | decision-completeness | 1 | "Annotations — perk:decision-completeness: pushed 1." | 1 | 0 | 0 | 0 |
    | risk | 1 | "Annotations — perk:risk: pushed 1." | 1 | 0 | 0 | 0 |
    | ponytail | 0 | "Annotations — nothing to push." | 0 | 0 | 0 | 0 |

    The risk lane reported two findings. The planner's reconciliation folded the second, which
    was anchored on the same phrase as decision-completeness's finding, into that annotation's
    body. All five reviewer findings therefore reached the browser as four annotations.
  - **Decision order (criterion 4).** The owner **DENIED** in the browser. The DENY feedback turn
    is line 201 (17:40:37Z), after the last push receipt (line 192). It quotes all four
    annotations back ("I've reviewed this plan and have 4 pieces of feedback").
  - **Owner observation (criterion 5).** Asked once while this row was written, the owner
    confirmed that the `perk:wave` marker showed after launch and cleared at collection, and that
    all four annotations were visible in the browser before the DENY.
  - The planner's post-collection `PLAN-DOOR-LEG-OUTCOME:` line (line 193) and the plan's
    Assumptions bullet served as finders; neither is the instrument.
- **PR-door browser wave — PASS.** Host: Pi 0.99.2 PATH host, pi-subagents 0.75.0 in the
  implement worktree's own `.pi/npm`, perk 3.9.0 at the reviewed head `a9dfecdc` (matrix).
  Session: node 2.1's implement session (run `01M46JPEYM9FXBAZP0P84D7AJC`, Pi session
  `01a10d2c-ed9a-77d1-b4f7-22be85b2b129`), where the owner ran `/pr-review-browser` on PR #2663 in
  active mode (the worktree's own PR, no separate checkout). Its JSONL is
  `$MAIN/.pi/agent/sessions/--Users-mattgiles-dev-github-mattgiles-perk-.worktrees-plan-2662--/2026-10-05T17-46-50-651Z_01a10d2c-ed9a-77d1-b4f7-22be85b2b129.jsonl`;
  the line numbers below are file lines in it (the log is append-only).
  - **Launch (criterion 1).** Line 213 calls `start_review_wave {"angles": ["claimed-intent",
    "correctness", "quality"], "pr": 2663, "worktree": "$MAIN/.worktrees/plan-2662"}`. Its result
    (line 214, 19:04:00Z) reads "Review workflow accepted with 4/4 post-preflight runnable lane(s)
    — claimed-intent, correctness, quality, ponytail (asyncId
    1e61dcc1-ab96-4004-b298-419f24801239)." `details.launch`: `requested` and `runnable` are both
    `["claimed-intent", "correctness", "quality", "ponytail"]`, and `preflightFailures` is `[]`.
  - **Collect (criterion 2).** Collection followed the matching workflow-completion notice (line
    220, 19:05:49Z). The result (line 222, 19:05:51Z) reads "Review wave complete: covered 4/4
    angle(s)." with `complete: true`, all four angles in `covered`, and `failures: []`. It records
    one attempt (`flow: "adversarial-review"`, `state: "complete"`) whose four
    `perk.adversarial-reviewer` children are each `success: true`.
  - **Delivery (criterion 3).** One assistant entry (line 223) carries four `push_annotations`
    calls, one per covered angle, each with `replace: true`. The receipts are lines 224–227
    (19:06:00Z), and each is the ok arm (`ok: true`, `mode: "review"`, `skipped: []`):

    | Angle | Findings sent | Receipt | `pushed` | `held` | `held_batches` | `deleted` |
    |---|---|---|---|---|---|---|
    | claimed-intent | 1 | "Annotations — perk:claimed-intent: pushed 1." | 1 | 0 | 0 | 0 |
    | correctness | 0 | "Annotations — nothing to push." | 0 | 0 | 0 | 0 |
    | quality | 0 | "Annotations — nothing to push." | 0 | 0 | 0 | 0 |
    | ponytail | 1 | "Annotations — perk:ponytail: pushed 1." | 1 | 0 | 0 | 0 |

    The two findings anchored on different lines (this record's PR-door row, and
    `tests/test_learn_normalize.py:744`), so reconciliation merged nothing. The claimed-intent
    finding named this row's then-pending status, which this append resolves.
  - **Decision order (criterion 4).** The owner platform-posted a COMMENT review from the browser
    ("proof of work", GitHub review `5419347262` on commit `a9dfecdc`, submitted 19:09:30Z) with
    both annotations as inline comments; perk posted nothing. The door's respond ("Pull request
    reviewed on GitHub: …") is line 229 (19:09:32Z), after the last push receipt (line 227).
  - **Owner observation (criterion 5).** Asked once while this row was written, the owner
    confirmed that the `perk:wave` marker showed after launch and cleared at collection, and that
    both annotations were visible in the browser before the review was posted.

## Operator notes — the host move is per checkout

Pi reconciles the supplier install against the checkout's own committed `.pi/settings.json`,
never against perk's constant, and the old producer travels with the old pin on any branch that
predates this change. A checkout is ready for Pi 1.0.0 only when its branch contains this change
(the `script` producer and the `npm:pi-subagents@0.75.0` entry): main after merge, rebased plan
worktrees, and `review-<N>` worktrees of PRs built on it. Older plan worktrees keep 0.73.1 +
`workflowScript`, and their waves refuse on a 1.0.0 host, so finish or rebase them before moving
the host. Consumer repos upgrade perk and run `perk init` or `perk doctor --fix`; the next Pi
launch installs 0.75.0 and `subagent-compat` reports ✓.

## Falsified planning-time assumptions

1. **`registerWorkflowResources`** — the export is `registerWorkflowResource` (singular;
   `src/workflows/workflow-resources.js:25`, `pi-subagents/workflow-resources`). The code comment
   names it correctly.
2. **"`badmodel` yields the A11-shaped pre-spawn lane failure."** The per-item model does fail the
   lane before any runner, but it leaves no child directory at all. The A11 signature came from
   the `PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT` fallback (worker only; the CLI's argv walk
   finds Pi, so the variable is never read there).
3. **The working hypothesis** "a failed child wakes a headless parent and Pi 1.0.0 print mode
   keeps running the triggered turns" — half right. The wake is confirmed in every row, but the
   non-exit is neither 1.0.0-specific (X2) nor universal across pre-spawn failures (X1 exits),
   and the worker parent always exits.
4. **"`/perk-selfcheck` is unknown" (T4)** — confirmed, but in print mode an unknown slash command
   becomes a model prompt; the T4 selfcheck ran a model loop until the cap.
5. **D5's expected `complete: true`** — `run_scout_wave`'s result details carry `ok`, `reports`
   and `attempts` (no `complete` key); completeness is `ok: true` with 2/2 reports.
6. **Not anticipated by the plan:** pi-subagents 0.76.0 was published before the experiment
   (not adopted); 0.75.0 adds the `pi-subagents:commands` inline child extension (unreachable from
   perk's agents); `missions` and `extension-bindings` in `disabledFeatures` refuse perk waves
   alongside `workflow-scripts`.

Confirmed as planned: the `spawnParams` messages and `Object.hasOwn` checks; trust forwarding into
`SettingsManager.create`; `projectTrusted ?? true`; the resolution order; the reserved names apply
to registration only; workflow reuse needs `runtime-replaced`; `requireForAllRunners` sits behind a
subpath export; the `borrowed-packages` capability summary is version-free.

## Methodology appendix

### Deviations from the plan's procedure

- **No `timeout` binary on macOS.** D5 ran under a small `bounded.sh` (own process group, hard
  cap) instead.
- **D2 relaunch.** The owner quit and resumed the session after D2, as the plan asks.
- **X1 misfire.** The first X1 attempt ran without `--approve` after T4 had cleared the trust
  state (`probe-timeout` on `ping`: pi-subagents never loaded). It was discarded and re-run with
  `--approve`.
- **Extra rows.** X1-r2 and X1b-r2 replicate their rows. X1b (`missingbase`) ran although X1
  exited, because X1's lane failure lacked the A11 directory signature. W1d is the worker's A11
  signature via the env fallback. **X2/X3 were triggered by X1b's non-exit and used X1b's
  method**: the plan's trigger was read on the method that reproduced the non-exit.
- **Driver instrumentation (W2b, W1b–W1d).** These rows add an observation-only stage-event
  listener, an exit hook, and an `Object.prototype.toString` override for the extension-error
  object, so its `[object Object]` becomes quotable. No production code changed.
- **Probe auto-fire.** It waits 1 s after `session_start` and retries `spawn` on
  `no_active_session` (no retry fired).

### Launch environment

`$SCRUB` (prepended to every manually launched `pi`/`node`):

```sh
env -u PERK_RUN_ID -u PERK_PROFILE_HANDOFF -u PERK_SELFCHECK -u PERK_DISABLE_NATIVE_SDK_BRIDGE \
  -u PERK_CLI_VERSION -u PI_SUBAGENT_CHILD -u PI_SUBAGENT_CHILD_AGENT -u PI_SUBAGENT_EXTENSION_BINDINGS \
  -u PI_SESSION_FILE -u PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u PI_REASONING_LEVEL -u PI_CODING_AGENT
```

After the scrub, the probe's `env` dump shows only `PI_CODING_AGENT_DIR`, `PERK_SKIP_VERSION_CHECK`,
`PI_SUBAGENTS_TEMP_ROOT` and the in-process `PI_CODING_AGENT: "true"`. The W rows add
`PROBE_WORKTREE`, `PROBE_MODEL`, `PERK_PROBE_AUTO`, `PERK_PROBE_DONE`, and for W1d
`PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT`. No credential is env-borne.

### The probe extension (`$SCRATCH/probe-spawn.ts`, verbatim)

```ts
// .perk-characterization/probe-spawn.ts — throwaway; drives pi-subagents' v1 RPC exactly as
// extension/waves/rpcAdapter.ts does (same envelope; the run handle lives in data.details), with
// the spawn key, a pinned lane model and a lane mode, and waits for the run to settle so the
// in-process workflow host is not killed by print-mode exit.
//   /probe-spawn <script|workflowScript> <provider/model> [restricted|badmodel|missingbase]
// Auto-fire (SDK worker rows): PERK_PROBE_AUTO="<key> <model> [mode]" runs the same ping → spawn →
// settle from session_start and writes PERK_PROBE_DONE (a JSON file) when it finishes.
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const REQUEST = "subagents:rpc:v1:request";
const REPLY = "subagents:rpc:v1:reply:";
const log = (label: string, value: unknown) =>
  console.error(`probe: ${label} ${JSON.stringify(value, null, 2)}`);

interface Reply {
  success?: boolean;
  data?: { text?: string; details?: { asyncId?: string; asyncDir?: string } };
  error?: { code?: string; message?: string };
}

function call(pi: ExtensionAPI, method: string, params?: unknown, timeoutMs = 30_000): Promise<Reply> {
  const requestId = randomUUID();
  return new Promise((resolve) => {
    const off = pi.events.on(`${REPLY}${requestId}`, (data: unknown) => {
      clearTimeout(timer);
      off();
      resolve(data as Reply);
    });
    const timer = setTimeout(() => { off(); resolve({ error: { code: "probe-timeout", message: method } }); }, timeoutMs);
    pi.events.emit(REQUEST, { version: 1, requestId, method, ...(params === undefined ? {} : { params }), source: { extension: "perk-probe" } });
  });
}

const TERMINAL = new Set(["complete", "completed", "failed", "partial", "stopped", "cancelled", "error"]);
async function settle(asyncDir: string, timeoutMs = 180_000): Promise<unknown> {
  const statusPath = join(asyncDir, "status.json");
  const until = Date.now() + timeoutMs;
  let last: unknown = null;
  while (Date.now() < until) {
    if (existsSync(statusPath)) {
      last = JSON.parse(readFileSync(statusPath, "utf8"));
      const state = (last as { state?: string }).state ?? "";
      if (TERMINAL.has(state)) return last;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  return { probeTimeout: "settle", last };
}

async function probe(pi: ExtensionAPI, key: string, model: string, mode: string): Promise<{ outcome: string; asyncDir?: string; reply?: Reply }> {
  const item = {
    key: "probe", agent: "perk.scout", label: "probe", worktree: false,
    model: mode === "badmodel" ? "perk-probe/does-not-exist" : model,
    task: "Reply with exactly the single word OK and nothing else. Do not read any file.",
    ...(mode === "restricted" ? { extensionBindings: { "perk.parent-restrictions/1": { readOnly: true } } } : {}),
    ...(mode === "missingbase" ? { worktree: true, baseRef: "refs/heads/perk-probe-missing" } : {}),
  };
  const script =
    `const reports = await runs.all(${JSON.stringify([item], null, 2)});\n` +
    "return reports.map(({key, ok, error, structuredOutput}) => ({key, ok, error: error ?? null, report: structuredOutput ?? null}));";
  log("env", Object.fromEntries(Object.entries(process.env).filter(([k]) => /^(PI_|PERK_)/.test(k))));
  log("ping", await call(pi, "ping"));
  let reply: Reply = {};
  for (let attempt = 1; attempt <= 10; attempt += 1) {
    reply = await call(pi, "spawn", {
      [key]: script, async: true, mission: false, context: "fresh", model,
      acceptance: { level: "none", reason: "characterization probe" },
      intercomBridge: { mode: "off" }, timeoutMs: 120_000,
    });
    if (reply.error?.code !== "no_active_session") break;
    log("spawn-retry", { attempt, reply });
    await new Promise((r) => setTimeout(r, 1000));
  }
  log(`spawn(${key}, ${model}${mode ? `, ${mode}` : ""})`, reply);
  if (reply.success !== true) return { outcome: "spawn-rejected", reply };
  const details = reply.data?.details;
  if (typeof details?.asyncId !== "string" || typeof details?.asyncDir !== "string") {
    log("probe-error", "success reply without data.details.asyncId/asyncDir — handle extraction wrong, fix the probe");
    process.exitCode = 2;
    return { outcome: "probe-error", reply };
  }
  log("status", await settle(details.asyncDir));
  return { outcome: "settled", asyncDir: details.asyncDir, reply };
}

export default function (pi: ExtensionAPI) {
  pi.registerCommand("probe-spawn", {
    description: "characterization probe: ping + spawn one scout lane via the v1 RPC",
    handler: async (args) => {
      const [key = "script", model = "", mode = ""] = args.trim().split(/\s+/);
      if (!model) { log("probe-error", "usage: /probe-spawn <script|workflowScript> <provider/model> [restricted|badmodel|missingbase]"); process.exitCode = 2; return; }
      await probe(pi, key, model, mode);
    },
  });
  const auto = process.env.PERK_PROBE_AUTO;
  if (auto) {
    let fired = false;
    pi.on("session_start", () => {
      if (fired) return;
      fired = true;
      const [key = "script", model = "", mode = ""] = auto.trim().split(/\s+/);
      const done = process.env.PERK_PROBE_DONE ?? "probe-done.json";
      log("auto", { key, model, mode, done });
      setTimeout(() => {
        void probe(pi, key, model, mode).then(
          (result) => writeFileSync(done, JSON.stringify({ at: new Date().toISOString(), ...result }, null, 2)),
          (error: unknown) => writeFileSync(done, JSON.stringify({ at: new Date().toISOString(), outcome: "probe-threw", error: String(error) }, null, 2)),
        );
      }, 1000);
    });
  }
}
```

### The worker driver (`$SCRATCH/worker-probe.ts`, final form, verbatim)

W2 and W1 ran the same file without the `toString` override, the exit hook and the stage-event
listener (`createDriveSession(runtime, () => {})`).

```ts
// .perk-characterization/worker-probe.ts — throwaway; the production worker factory + the explicit
// headless bind, nothing else: resolveWorkerModel → defaultCreateRuntime (throwaway agentDir,
// disk-layered settings over the worktree) → createDriveSession(...).bind() (emits session_start,
// which auto-fires the project-discovered probe via PERK_PROBE_AUTO) → poll PERK_PROBE_DONE →
// dispose → return. No prompt, no runStage model loop.
import { existsSync, readFileSync } from "node:fs";
import {
  createDriveSession,
  defaultCreateRuntime,
  resolveWorkerModel,
} from "../extension/worker/sdkAdapter.ts";

const t0 = Date.now();
const say = (label: string, value: unknown) =>
  console.error(`worker-probe: ${label} ${typeof value === "string" ? value : JSON.stringify(value)} (+${Date.now() - t0}ms ${new Date().toISOString()})`);
// Diagnostic only: the headless binding's onError stringifies the extension-error object; give
// that one object shape a readable String() so the record can quote it.
const objectToString = Object.prototype.toString;
Object.prototype.toString = function (this: unknown): string {
  if (this !== null && typeof this === "object" && "extensionPath" in this && "error" in this) {
    const e = this as { extensionPath: unknown; event?: unknown; error: unknown };
    return `{extensionPath: ${String(e.extensionPath)}, event: ${String(e.event)}, error: ${String(e.error)}}`;
  }
  return objectToString.call(this);
};
process.on("exit", (code) => say("process-exit", `code=${code}`));
const worktree = process.env.PROBE_WORKTREE ?? "";
const done = process.env.PERK_PROBE_DONE ?? "";
try {
  const resolved = await resolveWorkerModel(process.env.PROBE_MODEL);
  if (!resolved.ok) throw new Error(`model: ${resolved.error}`);
  const runtime = await defaultCreateRuntime(worktree, resolved.selection);
  say("runtime", "constructed");
  // Observation only: count the perk-translated stage events (turns) the session emits.
  const handle = createDriveSession(runtime, (event) => say("stage-event", event));
  await handle.bind();
  say("bound", (handle.registeredToolNames() ?? []).length + " registered tools");
  const until = Date.now() + 240_000;
  while (!existsSync(done) && Date.now() < until) await new Promise((r) => setTimeout(r, 1000));
  say("done-file", existsSync(done) ? JSON.parse(readFileSync(done, "utf8")) : "absent (240s bound expired)");
  await handle.dispose();
  say("disposed", "returning");
} catch (error) {
  say("fatal", String(error instanceof Error ? error.stack : error));
  process.exitCode = 1;
}
```

`run-bounded.sh` is 1.1's watchdog verbatim (`pi-1.0.0-characterization.md`, methodology
appendix); `run-bounded-worker.sh` differs only in its terminal-line test,
`grep -qE '^worker-probe: (disposed|fatal)' "$log"`.

### Teardown proof (D8)

```text
=== 2026-10-05T13:58:52Z 8.1 pgrep (before)
  pgrep -fl $SCRATCH → (none) pgrep exit=1
  pgrep -fl pi-subagents-0.75.0-reverify → (none) pgrep exit=1
  pgrep -fl perk-pi1x → (none) pgrep exit=1
  pgrep -fl perk-d5 → (none) pgrep exit=1
  ls $TW/.pi/extensions → No such file or directory   (the W-row probe copy was removed before X1)
=== 8.2 git worktree remove --force $TW   exit=0
  git worktree prune exit=0
  rm -rf agent dirs + D5 scratch exit=0   ($TW, $HERMETIC, $AUTHED, $EMPTY, $D5AUTHED, $D5SCRATCH: No such file or directory)
=== 8.1 re-check (after) → (none) pgrep exit=1 for all three patterns
=== 8.3 MAIN staging hashes (after teardown)
eb487ac34430113f7a9b0889cc9e6390d13f619bf77c92cdf3df32d0d8444ad0  $MAIN/.pi/npm/package.json
3efbddc27643abb1b4befc5bcd15fdfdc0901f0731e318ba78c4064aec93f6c6  $MAIN/.pi/npm/package-lock.json
a44bd4b4f6af44715fc0383f19e99edb2f84898694291f121323d08feeeb00fd  $MAIN/.pi/npm/node_modules/.package-lock.json
12ddb98564785d4d012c308a07fe286aa2f0d463fe8af70012813af4cf17e193  $MAIN/.pi/npm/node_modules/pi-subagents/package.json
  (identical to the D2 baseline and the D7 start)
=== git -C $MAIN status --porcelain → (empty)
=== git worktree list → 141 entries, 0 matching pi-subagents-0.75.0-reverify
=== ls $MAIN/.worktrees → identical to the pre-experiment listing
=== git -C $WT status --porcelain → (empty before this record was written)
```

Removing the worktree deleted `$SCRATCH` with the experiment-local pi-subagents temp root, the
probe, the driver, the watchdogs, the logs and the throwaway `package*.json` /
`.pi/settings.json` edits. Removing the agent dirs deleted their sessions and `auth.json` copies.
`$WT/.pi/npm` stays an independent 0.75.0 copy (gitignored).
