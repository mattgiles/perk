---
title: perk's subagent orchestration — the two-boolean child floor, agent-def delivery, and the pi-subagents engine mechanics perk leans on
read_when: You are spawning a subagent, picking an agent's model, re-enabling a builtin, supervisor streaming, the two-boolean child floor, the ≥ 0.67.0 host-builtin intersection, scout lanes, or agent defs.
cluster: subagent-orchestration
---

# perk's subagent orchestration

perk delegates fresh-context work — PR review, review classification, objective exploration,
conflict resolution, draft review, harvest/dream/learn analysis — to subagents through the borrowed
`pi-subagents` engine. perk's defs (the `PERK_AGENTS` tuple, `src/perk/convergence/init/agents.py`)
reach consumer repos via `perk init`; the flow tools (`run_pr_review_wave`, `run_scout_wave`,
`explore_objective_node`, …) spawn them over the report-wave module. `workflow/report-waves.md`
owns that perk-side module; this doc owns the engine mechanics perk leans on plus perk's child
policy. Conventions: **One Code Rule** — files + behavior, never reproduced source; **Provenance** —
engine mechanics reflect the engine source at the version `## Sources` records; body version
numbers are event stamps, never currency claims.

## Distillation

- A perk child's authorization is TWO booleans — the runner bit `PI_SUBAGENT_CHILD=1` + the
  constant packet `perk.parent-restrictions/1 = {readOnly: true}` in
  `PI_SUBAGENT_EXTENSION_BINDINGS` — decoded fail-closed, latched per activation, composed into
  every gate observation; plan guidance rides the gate behind `isPlanGuidanceStage` + the runner
  fence — "Native child execution — the two-boolean policy".
- Agent defs: the sorted `PERK_AGENTS` tuple is the SSOT (never restate counts); `perk init`
  delivers each byte-identical into the committed `.pi/agents/perk/` and prunes only there; adding
  or renaming an agent walks the widening-lockstep census — "Agent-def delivery".
- Model knob: `[models.subagents] <agent>` applied as the workflow-level `model` at spawn time (wins
  over the def's frontmatter however set); builtins are OFF in every perk repo, re-enable only at
  PROJECT scope; `agentOverrides` is never perk's mechanism — "Models, overrides and builtins".
- Children are read-only reporters and the PARENT mutates once after reconciling; def-level
  `completionGuard: false` is the report-only escape, `context: "fresh"` per spawn is the only
  isolation guarantee — "Read-only children, parent mutates".
- pi-subagents ≥ 0.67.0 intersects a child's declared tools with the HOST's builtins: a shadowed
  `grep`/`find` fails reviewer/scout lanes closed at launch — perk injects
  `PI_FFF_MODE=tools-and-ui`; doctor `subagent-host-tools` — "The ≥ 0.67.0 host-builtin intersection".
- `outputSchema` injects the engine-required `structured_output` call (covered lane ⟺ schema-valid
  report); every wave spawn disables acceptance auto-inference explicitly; `runs.all` is all-settled
  for config-object items only — "Execution surfaces and structured output".
- Supervisor progress updates are injected steer messages that wake an idle parent; the completion
  notice is a preview, never the report — collect via the typed wave tools (`report-waves.md`) —
  "Supervisor channel".
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
`structuredOutputFailed`. Hence `SUBAGENT_CHILD_TOOLS` sits in `READ_ONLY_TOOLS`
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
`PERK_AGENTS`** (the repo-local `perk-dev.session-auditor` separately).

Bounded posture: not an OS sandbox nor authentication against malicious host extensions; a manual
`subagent` call is outside the channel; losing the runner env across `/reload` is unsupported. An
adjacent trap: a feature with its **own** isolated `createAgentSession` (`/btw`) runs outside the
main session's `tool_call` hook — thread the gate state into its toolset (read-only ⇒ `["read"]`)
and into the side-session cache key.

## Agent-def delivery to consumer repos

`PERK_AGENTS` (kept sorted): `adversarial-reviewer`, `conflict-resolver`, `draft-reviewer`,
`dream-analyst`, `dream-reducer`, `harvest-analyst`, `learn-analyst`, `objective-explorer`,
`pr-reviewer`, `review-classifier`, `scout`. Never restate a count (`workflow/doc-reconciliation.md`).

### How pi-subagents discovers agents

Discovery (`src/agents/agents.ts`) is **recursive** over `<root>/.pi/agents` (+ legacy `.agents`);
the runtime name comes from **frontmatter** (`name` + `package`, `src/agents/identity.ts::
buildRuntimeName`), not the path — `.pi/agents/perk/<name>.md` with `package: perk` yields
`perk.<name>`. Installed npm packages are scanned only for **declared** agent dirs
(`collectPackageSubagentPaths` reads `pi-subagents.agents` / `pi.subagents.agents` in
`package.json`); hits load as `source: "package"`, lowest custom rank in `AGENT_SOURCE_PRIORITY`
(builtin < package < user < project), first-declaration-wins. perk's npm `package.json` declares
none, so the carrier is the Python wheel + `perk init` (a decision, not an impossibility). Discovery
runs per execution against the live filesystem with a fingerprint-validated snapshot
(`discoveryFingerprint`, `discoverAgents`): a def written mid-session is usable by the next wave, so
session-scoped temp defs are viable — their cleanup is yours ("Child artifacts and wave cleanup").

### Delivery design

Sources live **out of the discovered tree** — top-level `agents/<name>.md` (no leading dot), so pi
never double-loads them in perk's own repo. Bundling mirrors `shared/` → `perk/_shared`: a wheel
`force-include` maps `agents` → `perk/_agents`; npm `files` is unchanged (`test_packaging.py` asserts
the tarball lacks `agents/`). The resolver mirrors `shared_dir()`: package data `perk/_agents`, else
the editable-repo sibling `<repo>/agents`, else a `FileNotFoundError` naming both.

### The widening-lockstep census

Adding an agent touches, in lockstep: `agents/<name>.md` + `PERK_AGENTS` (sorted) + the commented
`[models.subagents]` sample + `SubagentsTable` (`src/perk/substrate/config.py`) + `SUBAGENT_KEYS`
(`extension/substrate/config.ts`) + `tests/test_config.py` / `extension/substrate/config.test.ts` /
`tests/test_packaging.py` + **this doc's listing** (the census is self-referencing — that keeps the
listing current). A **rename** walks the same census plus
a `git mv` of the source and a reconverge that prunes the old delivered def.

The prose layer the census does not guard: audit every cohort-wide design-doc universal for
def-level vs spawn-level truth — a def with no launcher breaks any "every spawn adds X" claim, and
the wave module owns `context: "fresh"` / `mission: false` / the acceptance disable **at spawn
time**. Coexistence claims (builtin `scout` beside `perk.scout`) are characterized by flipping the
builtin on and spawning both.

### The committed convergence and doctor

`_converge_subagent_agents` delivers each def **byte-for-byte** into `.pi/agents/perk/` (plus a
`.gitkeep`) and prunes stray `*.md` **inside that subdir only** — a user-owned `.pi/agents/<mine>.md`
is out of reach. It computes the identical change-list for `apply=True`/`apply=False` (the
managed-convergence invariant) and has **no `self_repo` param**. Because `.pi/agents/perk/` is
**tracked**, linked worktrees inherit the defs via `git checkout` — no worktree mirror (contrast
skills' `materialize_skills`; `workflow/init-doctor.md`). Doctor: `subagent-engine` enumerates
`.pi/agents/perk/*.md` (informational); `subagent-agents` owns drift. `[models.subagents]` stays
**fixed-key** (the `PERK_AGENTS` set) — user agents set `model:` in frontmatter
(`docs/user-docs/how-to/write-a-custom-subagent.md`).

### The repo-local `perk-dev` namespace

`.pi/agents/perk-dev/session-auditor.md` (`package: perk-dev`) lives outside `PERK_AGENTS`:
repo-local, never delivered, untouched by the prune, yet config-keyed via `[models.subagents]
session-auditor`. Grow dev-only agents here, not the delivered set.

### Editing a rubric — the reconverge ritual

A perk agent's judgment lives **entirely** in its def — SSOT `agents/<name>.md` (e.g. the whole
reviewer rubric is `agents/pr-reviewer.md`; skill and door defer to it). After editing: re-run `perk init`,
commit **both** copies byte-identical. Worktree gotchas: `perk init` may fail the skills-sync step
after printing `Converged before failure:` with the agent copy `updated` — non-fatal for an
agent-only edit; it also creates the gitignored `.pi/perk.local.toml`, so **stage explicit paths,
never `git add -A`**. The flat `.pi/agents/<name>.md` spelling is always stale. The wave def↔schema
lockstep tests (`extension/waves/draftReviewWave.test.ts`,
`extension/waves/adversarialReviewWave.test.ts`) regex-pin their defs' completion-protocol prose, so
a pure prose rewrite stays green **except** for those pinned clauses.

## Models, overrides and builtins

**The knob.** A committed frontmatter `model` default + `[models.subagents] <agent>` in
`.perk/config.toml` (overlaid by `.perk/local.toml`), applied by the wave module as the
**workflow-level `model` default** on every lane — single-child launches included. It is spawn-time
and wins over the def's model however set. Placement rule: a `[models.subagents]` key belongs beside
a **code-owned spawn surface** only; a hand-launched agent rides its frontmatter
`model:`/`fallbackModels:`. The two readers are the Pydantic `SubagentsTable`
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

**Def-level `acceptance` vs `completionGuard`** (both frontmatter fields):

- `acceptance:` becomes the def's `defaultAcceptance`, copied onto a **single-agent** launch that
  omits `acceptance` (`applySingleAgentLaunchDefaults`; explicit call values win); `level: "none"`
  requires a non-empty `reason` (`validateAcceptanceInput`, `src/runs/shared/acceptance.ts`).
- `completionGuard` is the engine's *mutation* guard (`src/runs/shared/completion-guard.ts`): an
  implementation-shaped task on a mutation-capable child expects a mutation; a mutation-expecting
  task on a child with no such tool is refused at launch. `bash` counts as mutation-capable, so a
  report-only def carrying `bash` rides `completionGuard: false` (a real frontmatter field), not a
  tools diet. Default: enabled unless the def says `false`; launches carrying an
  `AgentContract` enable it only when the def says `true` (`src/runs/foreground/execution.ts`).
  Disabling it removes only the mutation guard — `structured_output`, perk's floor and the rubric
  still enforce non-mutation.

**Isolation knob.** `context: "fresh"` is a clean session; `"fork"` branches parent history.
Precedence (`src/shared/fork-context.ts::resolveSubagentLaunchContext`): explicit spawn `context` >
configured `defaultSubagentContext` > def `defaultContext` > `fresh` (an implicit fork also needs a
persisted parent — `canPreferFork`). An isolation-requiring fan-out passes `context: "fresh"` **per
spawn** — a def-level default cannot guarantee isolation.

## The ≥ 0.67.0 host-builtin intersection (doctor `subagent-host-tools`)

Since 0.67.0 the launch tool plan (`src/runs/shared/child-tool-plan.ts`) intersects a child's
declared tools with the HOST session's builtins — a host tool counts as builtin when its
`source === "builtin"` OR (`source === "auto"` and its name is in `PI_BUILTIN_TOOL_NAMES`). Agents
matching `REVIEW_OR_SCOUT_AGENT_PATTERN` (`/\b(?:reviewer|scout)\b/i`) **fail closed at launch**
when ANY explicitly requested, still-permitted member of `REPOSITORY_INSPECTION_TOOLS` (`read, grep,
find, ls, bash, powershell`) is host-omitted (excluded or undefined tool lists never fail); every
other agent silently loses the tool with a `console.warn`-only warning (never in the RPC reply). The trigger is pi-fff's `override` mode re-registering `grep`/`find` as extension tools;
perk's answer is `PI_FFF_MODE=tools-and-ui` injected at both launch seams
(`src/perk/run/launch/__init__.py::FFF_MODE_ENV`; `workflow/cold-door-launch.md`,
`workflow/borrowed-packages.md`), the operator env winning. Doctor's `_subagent_host_tools_check`
gates on `_SUBAGENTS_HOST_INTERSECTION_AFFECTED = ("0.67.0", None)` — an **open upper bound** only
the re-verify how-to closes. The borrowed package is unpinned and refreshes at every pi launch, so
the installed version can move mid-session.

## Execution surfaces and structured output

**Surfaces.** Direct `{agent, task}` is the idiomatic one-child shape — a native structured single
mode (`normalizePublicSubagentExecution`; `output: true` by default; synchronous under
`asyncByDefault: false`). `workflowScript`, `workflowScriptPath` and named
`workflow` resources are the multi-agent surfaces; mixing execution fields is rejected (`action` has
`validate` / `schedule.create` exceptions). A
fan-out is ONE async workflow: `runs.all` over **config-object** items is all-settled — a failed lane
resolves `{key, ok: false, output, error}`, siblings never sink; `runs.run(…)` thenables instead run
permissive, where a failed child THROWS at the boundary (`RUNS_ALL_PERMISSIVE_WARNING`) — perk's
renderer passes config objects. Duplicate keys throw; run keys match
`/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/`; top-level `context`/`model`/`outputSchema` default onto every
child (`prepareWorkflowLaunchParams`, explicit child fields win); a child's `output` is its full
final message; the script's return persists as `workflow.value` in `<asyncDir>/status.json`. Async
workflows run **in-process** in the parent pi (`mode: "workflow"` status carries `pid: process.pid`;
only single/chain runs get the detached runner) ⇒ a wave dies with the parent. Omitted child `async`
= background under `workflowAwaitAsync: true`; explicit `async: true` = detached. A foreground
workflow returns the unsliced aggregate inline (30-minute default timeout).

**`outputSchema`.** A top-level `outputSchema` injects a `structured_output` tool into the child
(`src/runs/shared/structured-output.ts`, `INTERNAL_TOOLS` in `permissions.ts`) regardless of the
def's `tools:`, plus prompt-runtime instructions making that call the final action ("Do not rely on
prose-only completion; if you do not call `structured_output`, the parent will fail this step." —
`subagent-prompt-runtime.ts`). The run fails `structuredOutputFailed` when the tool is never called
or the payload is schema-invalid; `structuredOutput` is populated ONLY on a schema-valid run, so
covered lane ⟺ `ok: true` ⟺ a valid report. Spawn-time `output` is the persistence mechanism —
defs never restate it. Schema SSOTs are module constants (`PR_REVIEW_REPORT_SCHEMA`,
`extension/waves/prReviewWave.ts`; `REVIEW_CLASSIFIER_REPORT_SCHEMA`,
`extension/waves/reviewClassifierWave.ts`; `OBJECTIVE_EXPLORER_REPORT_SCHEMA`,
`extension/waves/objectiveExplorerWave.ts`), never prompt-transcribed.

**Acceptance hazard.** With `acceptance` omitted the engine auto-infers a contract: an agent name
matching `/\b(?:reviewer|oracle|scout|researcher|analyst)\b/` (unless the def declares
`acceptanceRole`) reads as read-only, `/\bworker\b/` as a writer — and injects a fenced
`acceptance-report` completion instruction, a COMPETING contract observed steering a child into
acceptance-shaped `structured_output` attempts (schema-rejected, run failed). perk's report-wave
module therefore passes `acceptance: {level: "none", reason}` on EVERY wave spawn
(`extension/waves/transport.ts::WAVE_ACCEPTANCE`; `explicitAcceptanceCanDisable`) —
`report-waves.md` § "The fixed spawn contract carries an explicit acceptance disable". An
`acceptance: auto` "no edits made" wobble never flips a schema-valid lane.

## Supervisor channel

The intercom bridge appends `contact_supervisor` to a nonempty explicit allowlist when enabled
(`src/intercom/intercom-bridge.ts::applyIntercomBridgeToAgent`) — a read-only reviewer streams
without def changes; bridge-off supplies nothing, so never infer delivery from a tool list.
`reason: "progress_update"` is one-way (`expectsReply` false; never enters `pending`; capped at
`MAX_MESSAGE_BYTES = 64 KiB`). Delivery is an injected message, nothing else
(`native-supervisor-channel.ts`): `pi.sendMessage({customType: SUPERVISOR_REQUEST_MESSAGE_TYPE})`
(`supervisor-ui.ts`) with the host default steer and `triggerTurn: true` — an idle parent wakes.
Owner match is session-scoped (`requestMatchesOwner` on `orchestratorSessionId`, a typed
`ChildRuntimeConfig` field), so RPC-spawned and model-called waves stream identically. Transport is
platform-split (fs watchers + safety scan, or a `CHANNEL_POLL_MS` ≤ 500 ms poller) — upstream
internals, not a parent prescription. A **decision-type**
request from a lane is a lane-design smell (unanswerable at parent-turn latency) — reviewer prompts
classify parent-owned execution evidence as out of scope (`agents/pr-reviewer.md`). The silent
killer is config: `subagents.intercomBridge.mode` `"off"` or `"fork-only"` (enum `off | fork-only |
always`; perk children are fresh-context) suppresses the channel — doctor `subagent-bridge-config`
warns on either scope (project + the launch-precedence agent dir via `launch_pi_agent_dir`), never
fails. Completion notices (`"subagent-notify"` overall; `"subagent-incremental-child-notify"` per
settled child) are previews — a 1,000-char return slice plus up to 8 child previews of 4 KiB,
per-item `triggerTurn` — never the report. `bg_wait` exists upstream for non-notifying background
work; perk does not adopt it. The parent collection protocol, grace/drain, `streamed` disclosure and
browser reconciliation are `workflow/report-waves.md` § "Session-scoped guard state" / § "Lane
semantics". Lesson: the planning session reads subtle dependency source and pre-digests it into the
plan.

## The v1 extension RPC seam

`src/extension/rpc.ts` is an extension-to-extension bridge on pi's in-process event bus; perk's
`extension/waves/rpcAdapter.ts` is the consumer.

- **Envelope**: requests on `subagents:rpc:v1:request` as `{version: 1, requestId, method, params?,
  source?}`; one reply on `subagents:rpc:v1:reply:<requestId>` as `{…, success: true, data}` or
  `{…, success: false, error: {code, message}}`. Methods: `ping`, `status`, `manage`, `spawn`,
  `steer`, `interrupt`, `stop`, `resume`; a `subagents:rpc:v1:ready` event carries the ping data
  (`events.ready`). perk's adapter uses `ping` and `spawn` only.
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

## Engine-coupling posture — public surfaces only

perk reaches pi-subagents only through public surfaces: the v1 RPC envelope, the delegation events,
def frontmatter, and the package `exports` subpaths (`./agents`, `./delegation`, `./child-tool-plan`,
`./preflight`, `./intercom-bridge`, `./control-channel`, `./capability-ceiling`,
`./workflow-resources`, `./shared-types`, …). The installed-engine test harnesses over the package's
`src/**` are deleted. Two guards: `extension/bareImportGuard.test.ts` (above) and
`extension/installedPackageGuard.test.ts` — no extension source spells a `.pi/npm/node_modules/`
path except Ponytail's manifest-declared preflight root, matched as a **whole path token with
equality** (a prefix-strip check would admit `…/ponytail-evil`; the test carries that control).

**The accepted coverage reduction, stated plainly:** no automated engine-level proof exists that
`completionGuard: false` still completes a report-only lane, that the runner stamps
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
  not ignore-covered"; "three Python-parsed keys unused".

## Sources

- The borrowed `pi-subagents` engine at `.pi/npm/node_modules/pi-subagents/` — `src/agents/`,
  `src/runs/{foreground,background,shared}/`, `src/intercom/`, `src/extension/rpc.ts`,
  `src/workflows/scripted-workflow.ts`, `src/shared/{artifacts,types}.ts`. The package is
  deliberately **unpinned**; the guidance baseline is the doctor constant
  `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` (`src/perk/convergence/doctor/checks.py`, pinned by
  `tests/test_doctor.py::test_subagent_compat_verified_version_stamp_is_pinned`), and `perk doctor`'s
  `subagent-compat` warns whenever the installed version differs from it.
- **Re-verify at each bump.** A new installed version silently re-asserts every engine fact here:
  follow `docs/developers/pi-subagents-reverify.md` (source re-read, `just ci`, a live report wave
  from a read-write session, the constant bump + its test pin, an archive record). Body version
  numbers are event stamps, never currency claims. Guidance baseline (doctor constant): 0.65.1.
  Last source re-read of the mechanics in this doc: the installed 0.67.0 — provenance, not a
  currency promise, and not a bump of the constant.

## Cross-references

- `extension/waves/reportWave.ts` (+ `rpcAdapter.ts`, `transport.ts`; test double
  `extension/testing/memoryAdapter.ts`) — the report-wave module over the v1 RPC seam
- `extension/substrate/childRestrictions.ts`, `extension/substrate/toolGating.ts`,
  `extension/pi/v1/contextInjection.ts` — the two booleans' consumer, the gate, the guidance fence
- `extension/pi/v1/delivery/conflictResolverEngine.ts`; `extension/waves/scoutWave.ts` /
  `extension/pi/v1/scoutWave.ts`
- `src/perk/convergence/init/agents.py`, `src/perk/convergence/doctor/checks.py`, `agents/*.md`
- `docs/design/pi-subagents-child-execution-policy.md`; `docs/developers/pi-subagents-reverify.md`;
  `docs/learned/workflow/report-waves.md` (the boundary partner)
- `shared/contracts.md` §8.3 (two-boolean decode), §8.10 (`disableBuiltins` / re-enable), §8.35
  (the packet producer); the `pi-subagents` skill
