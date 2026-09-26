---
title: perk's subagent orchestration — the two-boolean child floor, agent-def delivery, and the pi-subagents engine mechanics perk leans on
read_when: You are spawning a subagent, picking an agent's model, re-enabling a builtin, supervisor streaming, the two-boolean child floor, agent-def packaging and discovery, wave deadlines, scout lanes.
cluster: subagent-orchestration
---

# perk's subagent orchestration

perk delegates fresh-context work — PR review, review classification, objective exploration,
conflict resolution, draft review, harvest/dream/learn analysis — to subagents through the borrowed
`pi-subagents` engine. perk's defs (`agents/*.md`) ship in the `@mgiles/perk` npm package and the
engine discovers them as package agents; the flow tools (`run_pr_review_wave`, `run_scout_wave`,
`explore_objective_node`, …) spawn them over the report-wave module. `workflow/report-waves.md`
owns that perk-side module; this doc owns the engine mechanics perk leans on plus perk's child
policy. Conventions: **One Code Rule** — files + behavior, never reproduced source; **Provenance** —
engine mechanics reflect the engine source at the version `## Sources` records; body version
numbers are event stamps, never currency claims; **No in-body history** — a superseded rule is
corrected in place (or its section deleted) and becomes ONE dated `## History (dated)` bullet,
never an `> **Update**` blockquote, a `(historical)` `##` section, or WAS-tensed primary text
(`workflow/doc-reconciliation.md` § "Correction shapes").

## Distillation

- A perk child's authorization is TWO booleans — the runner bit `PI_SUBAGENT_CHILD=1` + the
  constant packet `perk.parent-restrictions/1 = {readOnly: true}` in
  `PI_SUBAGENT_EXTENSION_BINDINGS` — decoded fail-closed, latched per activation, composed into
  every gate observation; plan guidance rides the gate behind `isPlanGuidanceStage` + the runner
  fence — "Native child execution — the two-boolean policy".
- Agent defs ship in the npm package (`agents/*.md`, `pi-subagents.agents`), discovered as
  `source: "package"`; the census is `agents/*.md` ↔ `SUBAGENT_KEYS` ↔ `SubagentsTable`; no
  reconverge — "Agent-def delivery".
- Model knob: `[models.subagents] <agent>` applied as the workflow-level `model` at spawn time (wins
  over the def's frontmatter however set); builtins are OFF in every perk repo, re-enable only at
  PROJECT scope; `agentOverrides` is never perk's mechanism — "Models, overrides and builtins".
- Children are read-only reporters and the PARENT mutates once after reconciling; a report lane
  completes on its validated report (0.70.1 removed `completionGuard`), `context: "fresh"` per
  spawn is the only isolation guarantee — "Read-only children, parent mutates".
- `outputSchema` injects the engine-required `structured_output` call; covered lane ⟺ `ok: true`
  AND a schema-valid report (a valid report alone is evidence — since 0.71.0 it survives a later
  provider error/abort); every wave spawn disables acceptance auto-inference explicitly; `runs.all`
  is all-settled for config-object items only — "Execution surfaces and structured output".
- Waves are completion-only: every spawn carries `intercomBridge: {mode: "off"}` (0.68.0 discards
  parent-side `progress_update`); a successful child completion no longer wakes the parent; the
  completion notice is a preview — collect via the typed wave tools; engine deadline + 60 s
  settlement grace; reports ride only the completion `results[]` — "Supervisor channel".
- perk reaches the engine only through public surfaces (v1 RPC envelope pinned as module constants,
  delegation events, def frontmatter, package `exports`); doctor `subagent-compat` is a version
  tripwire, never a source probe; the accepted coverage gap is named — "Engine-coupling posture".
- `## Sources` records the guidance baseline (doctor constant) and the last engine source re-read;
  superseded claims live only under "History (dated)".

## Native child execution — the two-boolean policy

`docs/design/pi-subagents-child-execution-policy.md` is the binding record; this is the map. Two
booleans decide what a perk child may do:

- **The runner bit** — `PI_SUBAGENT_CHILD === "1"`, set by the engine's background runner
  (`src/runs/background/subagent-runner.ts`) on every runner-hosted child — the only kind in which
  perk's extension activates; read by `extension/substrate/childRestrictions.ts::isRunnerChild`.
- **The restriction packet** — the constant `extensionBindings`
  `{"perk.parent-restrictions/1": {readOnly: true}}` (`extension/waves/reportWave.ts::
  REPORT_CHILD_RESTRICTIONS`), on every rendered report child together with `worktree: false`
  (caller checkout); the engine serializes it into `PI_SUBAGENT_EXTENSION_BINDINGS`
  (`child-launch.ts::childProcessEnv`). Nothing is sampled from the parent gate, handoff or task.

`decodeReadOnlyFloor(runner, raw)` is the consumer (contracts §8.3): a non-runner never has a
floor; no env var ⇒ no floor (the delegation-dispatched writer's case); an object envelope with NO
`perk.parent-restrictions/…` key ⇒ **no floor** (unrelated namespaces are opaque); invalid JSON, a
non-object envelope, any `perk.parent-restrictions/` key other than exactly `/1`, or `/1` holding
anything but exactly `{readOnly: boolean}` ⇒ **floor (fail closed)**; valid ⇒ the boolean.
`extension/index.ts` reads both at every `session_start` and **latches** the floor
(`readOnlyFloor ||= …` — a re-emitted `session_start`, a gate `exit()` or `session_tree` navigation
cannot clear it); `toolGating.ts` composes it as `isActive = active || hasFloor()` plus the all-names
`tool_call` backstop; a throwing floor supplier is restrictive.

**The JSON-boundary gotcha:** "exactly one own key" ≠ "the expected key". The decoder asserts the
named key with `Object.hasOwn` *before* honoring the value — a polluted `Object.prototype.readOnly`
would otherwise satisfy `keys.length === 1 && value.readOnly === false` and un-floor the child. Every
decoder reading a named property off parsed JSON should do the same.

**The inherited gate vs the engine's child tools.** The engine injects `structured_output` and
`contact_supervisor` at extension **load time** — before perk's `session_start` gate sync — so a
gate sync that omits them deactivates them and an `outputSchema` child fails
`structuredOutputFailed`. Hence `SUBAGENT_CHILD_TOOLS` (both names — perk's own waves spawn
bridge-off so `contact_supervisor` is absent in their children, but the allowlist governs EVERY
gated adopted child, and an ad-hoc gated child with an active bridge must keep its supervisor
door; a review of the first cut caught the over-narrowing) sits in `READ_ONLY_TOOLS`
(`extension/substrate/toolGating.ts`) and in **neither** `PERK_TOOLS` nor `BORROWED_TOOLS` —
children are stage-unscoped, so gate membership is their only governance surface. A "missing
`structured_output`" is a **composition** defect: trace (a) the launch tool plan
(`resolvePiLaunchToolPlan` unions it when `outputSchema` is set), (b) ambient-extension loading
(`disableAmbientExtensions` = `capabilityCeiling.denyExtensions` OR an `extensions` key present on
the def — an empty array ≠ omitted), (c) perk's gate timing; never the def's `tools:`. Read-only
prose is not a sandbox: mutation prohibitions must be categorical ("never edit, never push"), never
softened by an explicit-task exception a poisoned task could satisfy.

**Gate-riding plan guidance.** Runner children provision no scratch and get no authoring guidance:
plan guidance rides the read-only gate behind ONE predicate,
`extension/pi/v1/contextInjection.ts::isPlanGuidanceStage` over `PLAN_GUIDANCE_EXCLUDED_STAGES`,
fenced by `installInjectedContext`'s `runnerChild: () => boolean` supplier. Two wiring lessons: when
one fence protects many call sites, prove the composition-root wiring end-to-end once (a constant
`() => false` supplier passes every unit test); pin set members directly — the read-write
`OBJECTIVE_SAVE_STAGE` exclusion is invisible to a test iterating only read-only stages.

**Execution profile.** Execution mode is orthogonal to scheduling: an omitted child `async` under
the engine's `workflowAwaitAsync: true` selects *background*; explicit `async: true` is *detached*.
All report roles run background (def `async: true`, child calls OMIT `async`,
`inheritGlobalContext: false`, `extensions`/`subagentOnlyExtensions` omitted). The writer
(`conflict-resolver`) runs foreground through the delegation bridge
(`extension/pi/v1/delivery/conflictResolverEngine.ts`: a `DELEGATION_EVENTS.request` with NO
`async` key — the bridge defaults foreground — typed `cwd` = the worktree, `context: "fresh"`, a
structured result schema, no packet ⇒ floor-less, no perk activation),
mode-discriminated between `pr-rebase` (`/submit`) and the retained stack-sync drive
(`workflow/mergeability-and-conflict-resolution.md`). Tests assert a **closed census independent of
the shipped def census** (the repo-local `perk-dev.session-auditor` separately). SDK-identity
boundary: a blocking `subagent` call shares the host SDK in-process, while the detached runner
and wave lanes run under pi-subagents' own peer-alias identity (`pi/native-sdk-bridge.md` §
"Which SDK identity a child runs under").

Bounded posture: not an OS sandbox nor authentication against malicious host extensions; a manual
`subagent` call is outside the channel; losing the runner env across `/reload` is unsupported. An
adjacent trap: a feature with its **own** isolated `createAgentSession` (`/btw`) runs outside the
main session's `tool_call` hook — thread the gate state into its toolset (read-only ⇒ `["read"]`)
and into the side-session cache key.

## Agent-def delivery to consumer repos

The defs are top-level `agents/*.md` shipped IN the `@mgiles/perk` npm package: `package.json`
declares `"pi-subagents": {"agents": ["./agents"]}`, and pi-subagents discovers them as
`source: "package"`. There is no second copy and no reconverge — edit `agents/<name>.md` and ship
a release. The listing (`adversarial-reviewer`, `conflict-resolver`, `draft-reviewer`,
`dream-analyst`, `dream-reducer`, `harvest-analyst`, `learn-analyst`, `objective-explorer`,
`pr-reviewer`, `review-classifier`, `scout`) is the shipped `agents/*.md` census — never restate a
count (`workflow/doc-reconciliation.md`).

### How pi-subagents discovers agents

Discovery (`src/agents/agents.ts`) is **recursive** over `<root>/.pi/agents` (+ legacy `.agents`);
the runtime name comes from **frontmatter** (`name` + `package`, `src/agents/identity.ts::
buildRuntimeName`), not the path — a def with `package: perk` yields `perk.<name>`. Installed npm
packages are scanned only for **declared** agent dirs (`collectPackageSubagentPaths` reads
`pi-subagents.agents` / `pi.subagents.agents` in `package.json`); hits load as `source: "package"`,
lowest custom rank in `AGENT_SOURCE_PRIORITY` (builtin < package < user < project),
first-declaration-wins — so a same-named project def SHADOWS a package def. Discovery runs per
execution against the live filesystem with a fingerprint-validated snapshot
(`discoveryFingerprint`, `discoverAgents`): a def written mid-session is usable by the next wave, so
session-scoped temp defs are viable — their cleanup is yours ("Child artifacts and wave cleanup").

**The Ponytail `skillPath` is two def-dir-relative candidates** — the installed layout
(`../../../@dietrichgebert/ponytail/…`, the def dir sitting inside the consumer's
`.pi/npm/node_modules/@mgiles/perk/agents/`) first, the dev layout (`../.pi/npm/node_modules/…`,
perk's own checkout) second; `collectFilesystemSkills` skips a missing candidate.

**The legacy directory.** An older perk wrote the defs into a committed `.pi/agents/perk/` in each
consumer repo; ranked `project`, a leftover copy shadows the shipped def. Doctor `subagent-engine`
`warn`s on it and `doctor --fix` removes it (`perk/convergence/doctor/legacy_agent_defs.py`; the
migration's shape is `workflow/init-doctor.md` § "Legacy-cleanup migrations model the retired
writer's shape").

### The widening-lockstep census

The census is `agents/*.md` ↔ `SUBAGENT_KEYS` (`extension/substrate/config.ts`, pinned by
`extension/substrate/config.test.ts`) ↔ the `SubagentsTable` aliases minus `session-auditor`
(`perk/substrate/config.py`, pinned by `tests/test_subagent_agents.py` and
`tests/test_packaging.py::test_packed_package_declares_discoverable_agent_census`). Adding an agent
touches, in lockstep: `agents/<name>.md` + the commented `[models.subagents]` sample +
`SubagentsTable` + `SUBAGENT_KEYS` + their pins + **this doc's listing** (the census is
self-referencing — that keeps the listing current). A **rename** walks the same census plus a
`git mv` of the source. The test seam for the packed artifact is `workflow/distribution.md`'s
(§ "init/doctor/launch own the `@mgiles/perk` npm install").

The prose layer the census does not guard: audit every cohort-wide design-doc universal for
def-level vs spawn-level truth — a def with no launcher breaks any "every spawn adds X" claim, and
the wave module owns `context: "fresh"` / `mission: false` / the acceptance disable **at spawn
time**. Coexistence claims (builtin `scout` beside `perk.scout`) are characterized by flipping the
builtin on and spawning both. `[models.subagents]` stays **fixed-key** (the shipped census) — user
agents set `model:` in frontmatter (`docs/user-docs/how-to/write-a-custom-subagent.md`).

### The repo-local `perk-dev` namespace

`.pi/agents/perk-dev/session-auditor.md` (`package: perk-dev`) lives outside the shipped census:
repo-local, never shipped, yet config-keyed via `[models.subagents] session-auditor`. Grow dev-only
agents here, not the shipped set.

### Editing a rubric

A perk agent's judgment lives **entirely** in its def — SSOT `agents/<name>.md` (e.g. the whole
reviewer rubric is `agents/pr-reviewer.md`; skill and door defer to it). Edit it and ship; perk's
own repo discovers the checkout's defs directly through its `..` local package entry
(`shipped_agent_defs_dir`'s self-repo arm). The wave def↔schema
lockstep tests (`extension/waves/draftReviewWave.test.ts`,
`extension/waves/adversarialReviewWave.test.ts`) regex-pin their defs' completion-protocol prose, so
a pure prose rewrite stays green **except** for those pinned clauses.

## Models, overrides and builtins

**The knob.** A committed frontmatter `model` default + `[models.subagents] <agent>` in
`.perk/config.toml` (overlaid by `.perk/local.toml`), applied by the wave module as the
**workflow-level `model` default** on every lane — single-child launches included. It is spawn-time
and wins over the def's model however set. Placement rule: a `[models.subagents]` key belongs beside
a **code-owned spawn surface** only; a hand-launched agent rides its frontmatter `model:` (the
only model field — 0.68.0 **rejects a def carrying `fallbackModels` at load**, `Agent '<path>' uses
removed frontmatter field 'fallbackModels'`, and every def in the discovery set fails with it; there
is no replacement, same-launch model switching is gone upstream). The two readers are the Pydantic `SubagentsTable`
(`src/perk/substrate/config.py`) and `SUBAGENT_KEYS`/`parseSubagentsSelection`
(`extension/substrate/config.ts`); no key has a Python-plane execution consumer (doctor's
`_models_check` scans `Config.subagents` generically) — the TS flow tools read at execute time.

**`agentOverrides`.** Since 0.64.0 `subagents.agentOverrides` applies the FULL override set to
custom agents too (`applyCustomAgentOverride`, `src/agents/agents.ts`) — displacing frontmatter-set
fields, `model` included; scopes layer user-then-project. It is **never perk's mechanism**: the
workflow-level `model` default is spawn-time and wins regardless.

**Builtins are OFF.** Every perk repo carries the managed `subagents.disableBuiltins: true`
(`settings.py::_converge_subagents` touches only that key; contracts §8.10) — perk ships its own
`perk.*` defs, so builtins are noise. Posture, not a config knob. Re-enable precedence
(`applyBuiltinOverrides`): a **project** per-agent `agentOverrides.<name>.disabled: false` works
(consulted before the project bulk flag); a **user-global** re-enable does not (the bulk branch
returns `{disabled: true}` first) — `workflow/borrowed-packages.md`, `workflow/init-doctor.md`.

## Read-only children, parent mutates

**Decision rule:** child-posts-own-mutation **iff** the spawned work's only output sink is the
external surface and there is no parent-side action; otherwise read-only child + parent mutates.
No live perk flow takes the first branch: read-only children report structured findings and the
**parent** reconciles and posts once — a posting agent run in parallel would spam duplicates. **D1:** the GitHub mutation is canonical in Python (`perk pr review-post` /
`review-submit`); a child never holds a token or composes the mutation; the fallback ladder is
`workflow/github-gateway.md`'s.

**Def-level `acceptance` and the ignored `completionGuard`:**

- `acceptance:` becomes the def's `defaultAcceptance`, copied onto a **single-agent** launch that
  omits `acceptance` (`applySingleAgentLaunchDefaults`; explicit call values win); `level: "none"`
  requires a non-empty `reason` (`validateAcceptanceInput`, `src/runs/shared/acceptance.ts`).
- `completionGuard` is ignored (not rejected — unlike `fallbackModels`): the engine's completion
  mutation guard is gone, so perk's report defs carry no guard field and the lane completion
  contract is the validated `structured_output` report + perk's restriction floor + the rubric.
  The guard's arc is under "History (dated)".

**Isolation knob.** `context: "fresh"` is a clean session; `"fork"` branches parent history.
Precedence (`src/shared/fork-context.ts::resolveSubagentLaunchContext`): explicit spawn `context` >
configured `defaultSubagentContext` > def `defaultContext` > `fresh` (an implicit fork also needs a
persisted parent — `canPreferFork`). An isolation-requiring fan-out passes `context: "fresh"` **per
spawn** — a def-level default cannot guarantee isolation.

## Execution surfaces and structured output

**Surfaces.** Direct `{agent, task}` is the idiomatic one-child shape — a native structured single
mode (`normalizePublicSubagentExecution`; `output: true` by default; synchronous under
`asyncByDefault: false`). `workflowScript`, `workflowScriptPath` and named
`workflow` resources are the multi-agent surfaces; mixing execution fields is rejected (`action` has
`validate` / `schedule.create` exceptions). A
fan-out is ONE async workflow: `runs.all` over **config-object** items is all-settled — a failed lane
resolves `{key, ok: false, output, error}`, siblings never sink; `runs.run(…)` thenables instead run
permissive, where a failed child THROWS at the boundary (`RUNS_ALL_PERMISSIVE_WARNING`) — perk's
renderer passes config objects. A key reused with different launch params throws
(`Duplicate workflow key '<key>' used with incompatible launch params`); an identical reuse
returns the first launch's result. perk's `extension/waves/reportWave.ts::validateAssignments`
rejects a duplicate lane key itself. Run keys match
`/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/`; top-level `context`/`model`/`outputSchema` default onto every
child (`prepareWorkflowLaunchParams`, explicit child fields win); a child's `output` is its full
final message; the script's return persists as `workflow.value` in `<asyncDir>/status.json`. Async
workflows run **in-process** in the parent pi (`mode: "workflow"` status carries `pid: process.pid`;
only single/chain runs get the detached runner) ⇒ a wave dies with the parent. Omitted child `async`
= background under `workflowAwaitAsync: true`; explicit `async: true` = detached. A foreground
workflow returns the unsliced aggregate inline (30-minute default timeout).

**The workflow deadline and partial settlement.** The workflow timer arms
when the script STARTS — a few ms after the spawn reply, which is why a perk timer armed for the
same duration always won the race. `workflowFailureTerminalOutcome` maps the timeout to
`{state: "partial", reason: "timeout"}`; `workflowResultChildren` projects an unfinished child as
`{state: "running"}` with no `success`. The failure-path `status.json` carries NO `workflow.value`
and no per-step `structuredOutput` — finished lanes' reports travel ONLY in the completion
payload's `results[]`, so the consumer must still be accepting when it arrives. Runner children
inherit the workflow deadline. perk's side (the engine deadline, the settlement grace, deadline
partials) is `workflow/report-waves.md` § "Native partial settlement".

**`outputSchema`.** A top-level `outputSchema` injects a `structured_output` tool into the child
(`src/runs/shared/structured-output.ts`, `INTERNAL_TOOLS` in `permissions.ts`) regardless of the
def's `tools:`, plus prompt-runtime instructions making that call the final action ("Do not rely on
prose-only completion; if you do not call `structured_output`, the parent will fail this step." —
`subagent-prompt-runtime.ts`). The tool validates each call: a rejected call returns the error to
the child (which may retry), a valid one is captured and ends the step. An otherwise-successful
run fails `structuredOutputFailed` when no call validated — `Missing structured_output call; …`
only if the child never called the tool, else (since 0.71.0) a bounded rejection summary.
`structuredOutput` is populated only from a validated call, but since 0.71.0 it is **retained**
when a later provider error or abort fails the run. So engine status (`ok` / `success`), schema
evidence (`structuredOutput`) and perk coverage are three separate facts: on an `outputSchema` run
`ok: true` implies a valid report, never the reverse — a valid report is evidence, never proof of
an OK or covered lane. A covered lane is `ok: true` AND a schema-valid report: perk reads `ok`
first (`extension/waves/reportWave.ts::normalizeAssignments`; the partial-settlement projection
`extension/waves/rpcAdapter.ts::narrowRetainedEntries` maps `success` → `ok`), and
`extension/waves/reportWave.test.ts` pins an `ok: false` lane carrying a valid report as
`lane-failed` (`workflow/report-waves.md` § "Lane semantics — status ≠ validity ≠ coverage").
Spawn-time `output` is the persistence mechanism —
defs never restate it. Schema SSOTs are module constants (`PR_REVIEW_REPORT_SCHEMA`,
`extension/waves/prReviewWave.ts`; `REVIEW_CLASSIFIER_REPORT_SCHEMA`,
`extension/waves/reviewClassifierWave.ts`; `OBJECTIVE_EXPLORER_REPORT_SCHEMA`,
`extension/waves/objectiveExplorerWave.ts`), never prompt-transcribed.

**Acceptance hazard.** With `acceptance` omitted the engine infers a contract from the def's
declared `acceptanceRole` alone (`inferLevel`, `src/runs/shared/acceptance.ts`): `writer` ⇒
`checked`, `read-only` ⇒ `none`, anything else ⇒ `attested` — and perk's defs declare no role.
Any level but `none` injects an `## Acceptance Contract` completion instruction
(`formatAcceptancePrompt`) demanding an acceptance report — under an `outputSchema`, an
`acceptanceReport` object inside the final `structured_output` call; otherwise a fenced
`acceptance-report` block — a COMPETING contract once observed steering a child into
acceptance-shaped `structured_output` attempts (schema-rejected, run failed). perk's report-wave
module therefore passes `acceptance: {level: "none", reason}` on EVERY wave spawn
(`extension/waves/transport.ts::WAVE_ACCEPTANCE`; `explicitAcceptanceCanDisable`) —
`report-waves.md` § "The fixed spawn contract carries an explicit acceptance disable".

## Supervisor channel

**Perk waves run with the bridge off.** The intercom bridge appends `contact_supervisor` to a
nonempty explicit allowlist when active (`src/intercom/intercom-bridge.ts::applyIntercomBridgeToAgent`)
AND appends `DEFAULT_INTERCOM_BRIDGE_TEMPLATE` to the child's system prompt — a template that itself
tells the child to send `contact_supervisor({reason: "progress_update"})` on meaningful progress.
Since 0.68.0 the parent-side channel **discards** every non-reply request
(`native-supervisor-channel.ts::poll`: `if (!request.expectsReply) { removeRequestFile(…);
continue; }` — no `sendMessage`, no event, no storage; upstream #2229, deliberate, no opt-in) while
the child tool still returns "Supervisor progress update queued." — so a streaming child burns tool
calls on batches nobody receives. Perk therefore passes the per-launch override
`intercomBridge: {mode: "off"}` on EVERY wave spawn (`extension/waves/transport.ts::WAVE_INTERCOM_BRIDGE`,
beside `WAVE_ACCEPTANCE`; `SubagentParams.intercomBridge` "replaces the global config for this launch
only", honored on RPC `spawn` and spread onto every workflow child via `workflowDefaults`):
`resolveIntercomBridge` yields `active: false` → no tool, no template. The retired provisional
finding-streaming protocol (fenced-JSON `progress_update` batches, the `streamed` report field, the
uncovered-source clear, the `subagent-bridge-config` doctor check) is gone end to end; review waves
are completion-only and the browser doors show a code-owned `perk:wave` marker instead. A settings-
scope `subagents.intercomBridge.mode` no longer affects any perk flow. A **decision-type** request
from a lane was always a lane-design smell (unanswerable at parent-turn latency).

**Wakes.** Completion notices (`"subagent-notify"` overall; `"subagent-incremental-child-notify"`
per settled child) are previews — a 1,000-char return slice plus up to 8 child previews of 4 KiB,
per-item `triggerTurn` — never the report. Since 0.68.0 `incrementalChildCompletionTriggersTurn`
(`src/runs/background/notify.ts`) returns `false` for a `completed` child while the workflow is
still running: a routine successful child completion does NOT wake the parent; failed/paused/stopped
children and the workflow completion still do — only the matching WORKFLOW completion authorizes
collection. `bg_wait` exists upstream for non-notifying background work; perk does not adopt it. The
parent collection protocol, grace/drain and browser reconciliation are `workflow/report-waves.md`
§ "Session-scoped guard state" / § "Lane semantics". Lesson: the planning session reads subtle
dependency source and pre-digests it into the plan.

## The v1 extension RPC seam

`src/extension/rpc.ts` is an extension-to-extension bridge on pi's in-process event bus; perk's
`extension/waves/rpcAdapter.ts` is the consumer.

- **Envelope**: requests on `subagents:rpc:v1:request` as `{version: 1, requestId, method, params?,
  source?}`; one reply on `subagents:rpc:v1:reply:<requestId>` as `{…, success: true, data}` or
  `{…, success: false, error: {code, message}}`. Methods: the `SUBAGENT_RPC_METHODS` roster (at the
  last re-read `ping`, `status`, `manage`, `spawn`, `steer`, `interrupt`, `stop`, `resume`, and
  since 0.71.0 `cost` — versioned parent-plus-child spend); a `subagents:rpc:v1:ready` event
  carries the ping data (`events.ready`). perk's adapter uses `ping`, `spawn` and a best-effort
  `stop` (errors swallowed — the run may already be terminal).
- **`ping` is the capability check** — works with no session context, returns `{methods[],
  capabilities: {asyncSpawn, …}, events: {…}}`. `events.asyncComplete`
  (`SUBAGENT_ASYNC_COMPLETE_EVENT`, `"subagent:async-complete"`) is taken from ping, never pinned.
- **`spawn` is async-only** (`async: false` ⇒ `invalid_params`); params pass through
  `normalizePublicSubagentExecution`; success `data.details` carries `asyncId` + `asyncDir`.
- **The async-complete payload** spreads the result-file data plus `runId`/`triggerTurn`; match via
  `asyncDir` (fall back to `id`). Its `results[]` becomes output-free receipt children
  (`output`/`summary`/`structuredOutput` never copied; malformed rows dropped); assignment identity
  rides `workflowChildren.children[].childId` (`src/workflows/workflow-child-summary.ts`) correlated
  by unique child `runId` — a malformed, mismatched or ambiguous inventory **withholds** correlation;
  only an inventory-absent payload falls back to the overloaded `agent` name. Receipts are
  telemetry: missing correlation changes neither coverage nor posting authority.
- **`<asyncDir>/status.json`** survives completion: `state`, `error`, `workflow.value`,
  `steps[0].durationMs`. **`mission: false`** is a valid spawn param — every wave passes it.
- `pi-subagents` is not an allowed bare import (absent from `ALLOWED_PACKAGES`,
  `extension/bareImportGuard.test.ts`), so the v1 literals are pinned as module constants in
  `rpcAdapter.ts` — the versioned envelope exists for exactly this.
- pi's `EventBus.on` returns an unsubscribe function — per-request reply subscriptions dispose
  cleanly (`extension/pi/v1/providers/plannotator.ts::requestPlannotatorPlanReview` does the same).
- **Pi 0.85.1's pre-trust extension leak — a second responder.** Without `--approve`, pi's
  two-phase trust load loads user-scope packages' extensions pre-trust, dedupes by package
  identity (project wins) and drops the user copy WITHOUT `runtime.invalidate()`, so `pi.events`
  subscriptions made at load survive as an orphan RPC bridge that never sees `session_start` and
  answers every non-ping request `no_active_session`; `/reload` does not clear it. perk's own repo
  never sees it (`[pi] agent_dir` sidelines user-global settings). Record:
  `docs/design/archive/pi-pre-trust-extension-leak.md`. perk's answer is the wave adapter's
  context-less hold (`workflow/report-waves.md` § "The context-less RPC hold") + doctor
  `subagent-package-scope`.

## Engine-coupling posture — public surfaces only

perk reaches pi-subagents only through public surfaces: the v1 RPC envelope, the delegation events,
def frontmatter, and the package `exports` subpaths (`./agents`, `./delegation`, `./child-tool-plan`,
`./preflight`, `./intercom-bridge`, `./control-channel`, `./capability-ceiling`,
`./workflow-resources`, `./shared-types`, …). The installed-engine test harnesses over the package's
`src/**` are deleted; the one bounded read of installed consumer sources that remains is the
host-SDK bridge's census drift guard (`extension/substrate/nativeSdkBridge.test.ts`, contracts
§8.73), which lexes the import *specifiers* of the installed `pi-subagents`/`pi-web-access` files —
a structural fact of the shipped artifact, never engine mechanics. Two guards:
`extension/bareImportGuard.test.ts` (above) and `extension/installedPackageGuard.test.ts` — no
extension source spells a `.pi/npm/node_modules/` path except two sanctioned roots, Ponytail's
manifest-declared preflight root and the bridge's consumer install root
(`NATIVE_CONSUMER_INSTALL_ROOT` in `extension/substrate/nativeSdkBridge.ts`, which verifies
consumer roots by manifest identity and reads only their `package.json`), each matched as a
**whole path token with equality** (a prefix-strip check would admit `…/ponytail-evil`; the test
carries that control).

**The accepted coverage reduction, stated plainly:** no automated engine-level proof exists that
a guard-less report-only lane completes on its validated `structured_output` report (the engine
has had no completion guard to disable since 0.70.1), that the runner stamps
`PI_SUBAGENT_CHILD=1`, or that `extensionBindings` reaches the child env — `run_ci` cannot catch an
upstream change there. Mitigations: the `subagent-compat` `warn`, the fake-RPC composition
proofs (`report-waves.md` § "Test machinery"), and the live report wave in the re-verify how-to.
`subagent-compat` (`_subagent_compat_check`) is a **version tripwire**: `info` when the package is
absent, `warn` when the `package.json` version is unreadable OR differs from
`_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`, `ok` at that version; it never reads engine source. A
wrong-typed `{"version": 123}` is *unreadable*, never a *mismatch*.

## Lane craft — evidence pitfalls, routing tokens, prompts

### Lane evidence pitfalls

Three traps from live `perk.scout` lanes (`docs/design/archive/scout-launcher-*`), each a confident
wrong answer, not a failure: the pi `grep` tool returns "No matches found" for a
slash-containing glob (`perk-*/SKILL.md`) against a prefixed path — use `**/…` or a bare filename
glob (a lane reported a *false refutation* as `verified`); a `verified` basis records how the lane
believes it looked, not that it looked correctly — re-read every `pointer` a lane returns
and treat a no-match as "not found by that query", never evidence of absence; a parent on a
`worktree: none` stage runs in the MAIN checkout even when invoked from a linked worktree
(`workflow/cold-door-launch.md`) — briefs name the target worktree by **absolute path**.

**Routing tokens are an injection surface.** Any parent-interpolated value from repo/user data (a
lane id from a directory name) needs explicit untrusted-DATA coverage in the def AND
validate-or-fail-closed use: byte-exact match against a trusted manifest, empty report on no-match
(`agents/harvest-analyst.md` is the precedent). **Parent-prepares large evidence**: the parent
aggregates deterministically and hands lanes bounded, line-oriented inputs via absolute-path
manifests — lanes that improvised their own aggregation failed.

**The judgment-agent prompt anti-pattern** (any judgment prompt). A reviewer's "always clean" bias
was structural in the prompt: (1) a verdict falling through to a default, (2) "decide the verdict
first" anchoring before findings are enumerated, (3) anti-noise framing with no counterweight.
Antidote: an explicit "earned, not defaulted" statement, enumerate-findings-first → derive the
verdict, adversarial axes / investigation license — the binary posting bar unchanged.

## Child artifacts and wave cleanup

Placement is `ArtifactDirPreference = "project" | "session" | "temp"` (`src/shared/artifacts.ts`,
`getArtifactsDir`): default `session` ⇒ `<session dir>/subagent-artifacts/`; `project` ⇒
`.pi/subagents/…` in the checkout (`PROJECT_SUBAGENTS_RELATIVE_DIR`); no session file ⇒
`TEMP_ARTIFACTS_DIR`. Names: `<runId>_<agent>_{input.md,output.md,transcript.jsonl,meta.json}`
(`getArtifactPaths`). `_meta.json` carries aggregate usage + model but **no duration** —
`status.json`'s `steps[0].durationMs` is the timing source; transcript assistant records carry
per-message `usage` (`input`/`cacheRead`/`cacheWrite`). Observation (not re-verified live):
back-to-back spawns of one agent show cross-process cache-prefix affinity as first-message
`cacheRead`. Cleanup: a wave receipt is an **identity trail, not an inventory** —
`artifactPaths` names child session JSONLs under the parent store while the artifact set lives
run-id-keyed elsewhere; derive BOTH sets, validate every path against approved roots, never
glob-delete. A temp-def wave must delete the def AND check `git status` (`.pi/subagents` and
`/.pi-subagents/` are gitignored; anything else blocks the submit gate).

## History (dated)

- **#660** — `/pr-review`'s child posted its own review (the "sole output sink" shape); reshaped to
  report-only + parent posts, `write` dropped from the reviewer.
- **pre-0.52 → 0.64.0** — `agentOverrides` reached builtins only; 0.52–0.63 a frontmatter-sensitive
  fill for custom agents; 0.64.0 applied the full set. A contracts note calling the classifier model
  "overridable via `agentOverrides`" was wrong when made.
- **0.41–0.43, 0.49** — grouped `tasks[]`/`chain[]` removed (0.41.0–0.42.1; live-broke both review
  doors, no test tripped); direct `{agent, task}` removed at 0.43 (perk's one-child flows became
  explicit-return `runs.run` scripts), restored as a native single mode at 0.49.0.
- **0.61** — `subagent_wait` removed; the 0.52-era held-turn relay loop
  (`docs/design/archive/streaming-doors-dogfood.md`) is a characterization, not a native-wake proof.
- **0.65.0 / 0.65.1** — env stamps + `pi-args.ts` replaced by typed `ChildRuntimeConfig`;
  `workflowAwaitAsync` repaired "workflow children default to foreground". The 0.65.1 baseline
  failed background launch on missing host peers
  (`docs/design/archive/pi-subagents-native-baseline-dogfood.md`); dev host resolved at `52c4fde5`
  (`docs/design/archive/pi-subagents-native-streaming-dogfood.md`).
- **0.66.0** — artifacts moved from cwd `.pi-subagents/artifacts/` to the session dir.
- **0.67.0** — the host-builtin intersection (source-classified) failed reviewer/scout lanes under a
  pi-fff `grep`/`find` override; `PI_FFF_MODE=tools-and-ui` injected at both launch seams.
- **0.68.0 (2026-09)** — `fallbackModels` rejected at def load (all 12 perk defs failed, every wave
  0/N); parent-side `progress_update` discarded (provisional finding streaming retired; waves spawn
  with the bridge off; `subagent-bridge-config` retired; the `perk:wave` marker added); wrapped core
  slots count as host builtins (the `subagent-host-tools` range closed at 0.68.0; FFF injection
  kept); routine successful child completions stop waking the parent; the bundled `pi-server` copy
  dropped (Pi ≥ 0.85.1 required for background children). Record:
  `docs/design/archive/pi-subagents-0.68.0-reverify.md`.
- **0.70.0 / 0.70.1 (2026-09)** — the host-builtin intersection removed from `child-tool-plan`
  (perk's `PI_FFF_MODE` injection and the `subagent-host-tools` doctor check retired; pi-fff's own
  precedence now decides its mode). Its mechanics while live: reviewer/scout agents failed closed
  when a requested repository-inspection tool was host-omitted, others silently lost it; 0.68.0's
  "wrapped core slots count" refinement counted any core-named slot as a host builtin regardless
  of source, and the retired report-only check gated on the half-open
  `_SUBAGENTS_HOST_INTERSECTION_AFFECTED = ("0.67.0", "0.68.0")` range (`workflow/init-doctor.md`
  § "Report-only checks gated on an installed package's version range"). 0.70.1 removed the
  completion mutation guard (`completionGuard` ignored; dropped from every perk report def — a
  0.68–0.70.0 engine may still fail a guard-less report lane whose task reads as implementation)
  and tightened acceptance inference to a declared `acceptanceRole` alone (the agent-name
  inference — `/\b(?:reviewer|oracle|scout|researcher|analyst)\b/` read-only, `/\bworker\b/`
  writer — retired); the Pi 0.87 fork-context repair is NOT in the 0.70.1 artifact (perk children
  stay on `context: "fresh"`). Record:
  `docs/design/archive/pi-subagents-0.70.1-reverify.md`.
- **0.71.0 (2026-09) — source re-read, baseline stamp unmoved** — a validated `structured_output`
  now survives a later provider error or abort (upstream #2411), retiring the valid-report ⟺
  OK-lane biconditional for status ≠ schema evidence ≠ coverage (perk's normalizer already keyed
  coverage on `ok`); a rejected call reports a validation summary, the missing-call error only
  when the tool was never called; the RPC gained `cost`; the Pi 0.87 fork-context repair ships
  (`context_edit` handling in `src/shared/fork-context.ts` / `pruned-fork.ts`) — perk children
  still spawn `context: "fresh"` for isolation. By owner decision the guidance baseline stays
  0.70.1, so `subagent-compat` warns by design; the full re-verify, browser-door live leg
  included, is owed.
- **Agent-def delivery (#2455)** — agent defs moved from the wheel + `perk init` `.pi/agents/perk/`
  delivery to pi-subagents package discovery; the legacy dir is a doctor migration.
- **Two-boolean landing** — deleted: the `<active_agent>` prefix parser + `childIdentity.ts`,
  `nativeSessionKey.ts`, the sampled `parentReadOnly` supplier, `ReportWaveRequest.execution`, the
  six-reason classification, the ten-name report-only census.
- **Retirements** — `ADDRESS_MODEL_CLAUSE` with the two-plane classifier prompt;
  `review-angle-selector` with `/pr-review-dynamic` (#2109); `perk-dev.analyst` promoted to
  `perk.scout`; the SDK in-process child (#2100).
- **Schema mistranscription** — a hand-copied `outputSchema` nested `counts` wrongly, rejecting every
  child payload (`Missing structured_output call`); schemas became module constants and `/address`
  classify + the explorer moved off model-authored scripts onto flow tools.
- **`conflict-resolver`** — began as a guidance-instructed one-child `runs.run` with a compact
  `{key, ok, error, output}` projection; now code-dispatched through the delegation bridge with a
  structured result schema.
- **Review-context sweep** — `perk pr review-context` once wrote `formatted_context.json` /
  `pr_diff.diff` into the worktree CWD, where `git add -A` swept them into commits; it now writes
  under the run scratch dir (`src/perk/cli/commands/pr/review_context_cmd.py`).
- **Superseded notes** — `results[].agent` as assignment identity (now `childId`); "`.pi/subagents/`
  not ignore-covered"; "three Python-parsed keys unused"; "duplicate workflow keys throw" (only an
  incompatible reuse does — corrected at the 0.71.0 re-read).

## Sources

- The borrowed `pi-subagents` engine at `.pi/npm/node_modules/pi-subagents/` — `src/agents/`,
  `src/runs/{foreground,background,shared}/`, `src/intercom/`, `src/extension/rpc.ts`,
  `src/workflows/{scripted-workflow,workflow-child-summary}.ts`,
  `src/shared/{artifacts,types,fork-context,pruned-fork}.ts`, `CHANGELOG.md`. The package is
  deliberately **unpinned** — and an unpinned `npm:` source does NOT refresh at launch: pi's
  `installedNpmMatchesConfiguredVersion` accepts any installed version for an unranged source
  (installs a missing package, never refreshes an installed one); the guidance baseline is the
  doctor constant
  `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` (`src/perk/convergence/doctor/checks.py`, pinned by
  `tests/test_doctor.py::test_subagent_compat_verified_version_stamp_is_pinned`), and `perk doctor`'s
  `subagent-compat` warns whenever the installed version differs from it.
- **Re-verify at each bump.** A new installed version silently re-asserts every engine fact here:
  follow `docs/developers/pi-subagents-reverify.md` (source re-read, `just ci`, a live report wave
  from a read-write session, the constant bump + its test pin, an archive record). Body version
  numbers are event stamps, never currency claims. Guidance baseline (doctor constant): 0.70.1
  (`docs/design/archive/pi-subagents-0.70.1-reverify.md` — stamped on the source re-read + the
  doctor, scout-lane and offline conflict-engine halves of the leg; the browser-door half is owed
  from the owner's post-submit `/pr-review-browser` run, as it was for 0.68.0). The baseline was
  deliberately NOT moved at the 0.71.0 source re-read (owner decision): `perk doctor`'s
  `subagent-compat` warns by design until the full re-verify runs for 0.71.0, whose browser-door
  live leg is owed. Last source re-read of the mechanics in this doc: the installed 0.71.0
  (compiled `src/**/*.js`; body paths name the upstream `.ts` modules, whose anchors survive
  compilation) — provenance, not a currency promise.

## Cross-references

- `extension/waves/reportWave.ts` (+ `rpcAdapter.ts`, `transport.ts`; test double
  `extension/testing/memoryAdapter.ts`) — the report-wave module over the v1 RPC seam
- `extension/substrate/childRestrictions.ts`, `extension/substrate/toolGating.ts`,
  `extension/pi/v1/contextInjection.ts` — the two booleans' consumer, the gate, the guidance fence
- `extension/pi/v1/delivery/conflictResolverEngine.ts`; `extension/waves/scoutWave.ts` /
  `extension/pi/v1/scoutWave.ts`
- `perk/convergence/init/extension_install.py::shipped_agent_defs_dir`,
  `perk/convergence/doctor/legacy_agent_defs.py`, `perk/convergence/doctor/checks.py`, `agents/*.md`
- `docs/design/pi-subagents-child-execution-policy.md`; `docs/developers/pi-subagents-reverify.md`;
  `docs/learned/workflow/report-waves.md` (the boundary partner)
- `shared/contracts.md` §8.3 (two-boolean decode), §8.10 (`disableBuiltins` / re-enable), §8.35
  (the packet producer); the `pi-subagents` skill
