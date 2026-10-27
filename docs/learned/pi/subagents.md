---
title: perk's subagent orchestration — the two-boolean child floor, agent-def delivery, and the pi-subagents engine mechanics perk leans on
read_when: You change perk's child floor or an agent def (add, ship, model, ceiling), rely on a pi-subagents engine fact (spawn, structured output, wakes, RPC stop proof), or bump the supplier pin
cluster: subagent-orchestration
---

# perk's subagent orchestration

perk delegates fresh-context work — PR review, review classification, objective exploration,
conflict resolution, draft review, harvest/dream/learn analysis — to subagents through the borrowed
`pi-subagents` engine. perk's defs (`agents/*.md`) ship in the `@mgiles/perk` npm package and the
engine discovers them as package agents; the flow tools (`run_pr_review_wave`, `run_scout_wave`,
`explore_objective_node`, …) spawn them over the report-wave module. This doc owns perk's child
policy and the engine mechanics perk leans on; `workflow/report-waves.md` owns the perk-side wave
module and `pi/tool-loadout.md` the tool-policy tables (the child-engine row included) —
cross-link them, never restate. Conventions: **One Code Rule** — files + behavior, never
reproduced source; **Provenance** — engine mechanics reflect the engine source at the version
`## Sources` records; body version numbers are event stamps, never currency claims; **No in-body
history** — a superseded rule is corrected in place (or its section deleted) and becomes ONE dated
`## History (dated)` row whose evidence lives in an archive record — never an `> **Update**`
blockquote, a `(historical)` `##` section, or WAS-tensed primary text
(`workflow/doc-reconciliation.md` § "Correction shapes").

## Distillation

- A perk child's authorization is TWO booleans — the runner bit `PI_SUBAGENT_CHILD=1` + the
  constant packet `perk.parent-restrictions/1 = {readOnly: true}` — decoded fail-closed, latched
  per activation; in-child engine tools ride the child-engine provenance row; every def denies
  descendants with a blank `allowedAgents:` line — "Native child execution — the two-boolean
  policy". A floored report child survives compaction — "Report children survive compaction".
- Agent defs ship in the npm package (`agents/*.md`), discovered as `source: "package"`; adding
  one walks the `agents/*.md` ↔ `SUBAGENT_KEYS` ↔ `SubagentsTable` census — "Agent-def delivery".
- Model knob: `[models.subagents] <agent>` as the workflow-level `model` at spawn; builtins OFF,
  re-enable only at PROJECT scope; never `agentOverrides` — "Models, overrides and builtins".
- Report children are read-only reporters and the PARENT mutates once; the two foreground
  writers are the exception; `context: "fresh"` is the only isolation guarantee — "Read-only
  children, parent mutates".
- `outputSchema` injects `structured_output`; a covered lane is `ok: true` AND a schema-valid
  report; every wave spawn disables acceptance inference — "Execution surfaces and structured
  output".
- Every perk spawn surface runs bridge-off; the completion notice is itself the waking custom
  message, and perk promises nothing about it across a same-session `/reload` — "Supervisor
  channel".
- The RPC `stop` projects a typed `WaveStopOutcome`, then ONE `status` read projects the terminal
  proof class (`observed`/`pending`/`unknown`/`unavailable`) — an acknowledgement is never proof
  and `unknown` is final; a per-launch `args.launch` token defeats workflow reuse; foreign seams
  follow the pre-digest recipe — "The v1 extension RPC seam".
- perk reaches the engine only through public surfaces and doctor `subagent-compat` is a version
  tripwire — "Engine-coupling posture"; supplier `runnerLaunchers` are characterized NO-GO —
  "Runner launchers"; a broken global companion graph fails every lane — "Lane craft".
- `## Sources` names the pin and stamp constants, their chains and the re-verify procedure;
  superseded rules are one dated row each, pointing at archive records — "History (dated)".

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
`extension/pi/activation.ts::activatePerk` (the composition root) reads both at every
`session_start` and **latches** the floor
(`readOnlyFloor ||= …` — a re-emitted `session_start`, a gate `exit()` or `session_tree` navigation
cannot clear it); `toolGating.ts` composes it as `isActive = active || hasFloor()` plus the all-names
`tool_call` backstop; a throwing floor supplier is restrictive.

**The JSON-boundary gotcha:** "exactly one own key" ≠ "the expected key". The decoder asserts the
named key with `Object.hasOwn` *before* honoring the value — a polluted `Object.prototype.readOnly`
would otherwise satisfy `keys.length === 1 && value.readOnly === false` and un-floor the child. Every
decoder reading a named property off parsed JSON should do the same.

**The inherited gate vs the engine's child tools.** The engine registers its in-child tools
(`structured_output`, `contact_supervisor`, `wait`) through one named inline factory, so they are
classified by provenance — the exact-path child-engine row
`SYNTHETIC_PATH_TOOL_POLICY["<inline:pi-subagents:prompt-runtime>"]` in
`extension/substrate/toolPolicy.ts`: stage-blind (adopted children are stage-unscoped) and
gate-allowed (the gate IS inherited by adopted children). perk never deactivates a foreign tool, so
gate timing cannot strip them; an allowlisted report child (a def `tools:` filter) registers no perk
tool at all. Detail: `docs/learned/pi/tool-loadout.md`. A "missing `structured_output`" is a
**composition** defect: trace (a) the launch tool plan (`resolvePiLaunchToolPlan` unions it when
`outputSchema` is set), (b) ambient-extension loading (`disableAmbientExtensions` =
`capabilityCeiling.denyExtensions` OR an `extensions` key present on the def — an empty array ≠
omitted), (c) its provenance (a namesake from any other path is `unknown` and blocked under the
gate); never the def's `tools:`. Read-only
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
`inheritGlobalContext: false`, `extensions`/`subagentOnlyExtensions` omitted). The **two
write-capable foreground writers** — `perk.conflict-resolver` and `perk.librarian` — share one
profile: fresh-context, no read-only floor, def `async` absent, `inheritProjectContext` and
`inheritSkills` true, writer tools `read, grep, find, ls, bash, edit, write`. Both ride the shared
transport `extension/pi/v1/foregroundDelegation.ts` (a `DELEGATION_EVENTS.request` with NO `async`
key — the bridge defaults foreground — typed `cwd`, `context: "fresh"`, a structured result
schema, no packet ⇒ floor-less, no perk activation; ownership is
`workflow/mergeability-and-conflict-resolution.md` § "The transport"). The conflict-resolver is
mode-discriminated between `pr-rebase` (`/submit`) and the retained stack-sync drive; the
librarian (`extension/pi/v1/librarianEngine.ts`, reached by `run_librarian`) writes only under
the gitignored library of the main checkout.
`tests/test_subagent_agents.py::test_native_child_profile` asserts the writer profile for the
writer set and the report profile for every other def — a **closed census independent of the
shipped listing** that owns the number (the config-key census subtracts the repo-local
`perk-dev.session-auditor`). SDK-identity boundary: a blocking `subagent` call shares the host
SDK in-process, while the detached runner and wave lanes run under pi-subagents' own peer-alias
identity (`pi/native-sdk-bridge.md` § "Which SDK identity a child runs under").

**Descendant ceiling — the blank `allowedAgents:` line.** Every perk def, the two writers
included, carries a blank `allowedAgents:` line — the only safe "deny all descendants" form:
pi-subagents' own frontmatter parser turns a literal `[]` into the one-item list `["[]"]`, which
fails the ceiling regex and silently drops the def from discovery, while PyYAML reads the blank as
`None` — so `tests/_agent_defs.py::assert_descendant_ceiling` pins the raw text layout, not the
parsed value. The ceiling matters only where nesting is granted (perk grants none, so it is the
engine backstop behind the prose prohibition); it is applied after tool planning, never governs
the child's own launch, has one refusal text for foreground and background, and the engine's own
files (`recovery-descriptor.json`/`status.json` background, `subagent-artifacts/*_meta.json`
foreground) confirm it without a model. Record:
`docs/design/archive/pi-subagents-descendant-ceilings.md`.

Bounded posture: not an OS sandbox nor authentication against malicious host extensions; a manual
`subagent` call is outside the channel; losing the runner env across `/reload` is unsupported. An
adjacent trap: a feature with its **own** isolated `createAgentSession` (`/btw`) runs outside the
main session's `tool_call` hook — thread the gate state into its toolset (read-only ⇒ `["read"]`)
and into the side-session cache key.

## Report children survive compaction

A floored report child can be compacted mid-run, and pi-subagents has no per-child compaction knob
(`compaction.enabled` is a global setting). The normative policy is contracts §8.3 "Runner task
restore" and `docs/design/pi-subagents-child-execution-policy.md`; in summary
(`extension/substrate/childTaskRestore.ts`):

- After a compaction the child's first user prompt is re-injected byte-for-byte as a
  `perk:task-restore` steer, and `structured_output` is blocked while that prompt is not live in
  Pi's projection (the liveness rule — Pi's projection plus typed evidence — is
  `docs/learned/pi/context-injection.md` § "Dedup against Pi's own live projection"). An accepted
  report ends the policy.
- The one-call-only rule for `structured_output` counts accepted calls only — a blocked call
  captured nothing and its block reason tells the model so. pi-subagents' `structured_output`
  throws on schema rejection (an error result) and returns `terminate: true` on success.
- The restore lives entirely in the child's extension runtime; the wave module carries none of it.
- **Residuals:** `TASK_RESTORE_MAX_ATTEMPTS = 3` is a total per activation, not per compaction (a
  fourth restore is refused — fail-closed, uncovered). Only draft reviewers carry their whole
  subject inline: PR-reviewer lanes fetch the diff themselves and analyst lanes receive manifest
  paths, so evidence fetched later survives only as a compaction summary (narrowing §8.3's wording
  is follow-up F9 of the closed #2705, never filed).

## Agent-def delivery to consumer repos

The defs are top-level `agents/*.md` shipped IN the `@mgiles/perk` npm package: `package.json`
declares `"pi-subagents": {"agents": ["./agents"]}`, and pi-subagents discovers them as
`source: "package"`. There is no second copy and no reconverge — edit `agents/<name>.md` and ship
a release. The listing (`adversarial-reviewer`, `conflict-resolver`, `draft-reviewer`,
`dream-analyst`, `dream-reducer`, `harvest-analyst`, `learn-analyst`, `librarian`,
`objective-explorer`, `pr-reviewer`, `review-classifier`, `scout`, `simplifier`) is the shipped
`agents/*.md` census — never restate a count (`workflow/doc-reconciliation.md`).

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
touches, in lockstep:

- **The def** — `agents/<name>.md`.
- **Python config** — the `SubagentsTable` field AND the `ConfigFileModel.to_domain` `subagents`
  enumeration row (`perk/substrate/config.py`; the exact-dict pin
  `tests/test_config.py::test_subagents_selection_parsed` catches a missed row).
- **TypeScript config** — `SUBAGENT_KEYS` only: `PerkConfig.subagents` is
  `Partial<Record<SubagentKey, string>>`, so the tuple is the single TS source of truth.
- **Samples/config** — the commented row in `perk/convergence/init/templates.py` + this repo's
  `.perk/config.toml` row.
- **Pins** — `tests/test_subagent_agents.py::_PROFILES` (+ its count and comment); for
  Ponytail-bound defs the `skillPath` exception set and the expected map in
  `test_ponytail_defs_source_bind_only_the_exact_skill_paths`, and the Ponytail tuple in
  `tests/test_packaging.py::test_packed_package_declares_discoverable_agent_census`; the
  parse-all-keys test in `extension/substrate/config.test.ts`; `REPORT_ROLES` in
  `extension/waves/reportWave.test.ts` (report roles only).
- **Prose** — `shared/contracts.md` §8.3's shipped-report paragraph with its **three spelled-out
  counts** (hand-maintained — every added def bumps all three plus the lists);
  `skills/perk-expert/references/configuration.md` + `customization-recipes.md`;
  `docs/user-docs/reference/configuration/models-and-compaction.md`.
- **Opt-in, outside `just ci`** — the `docs/design/prose-prompt-map.yaml` match row + the
  regenerated map.
- **This doc's listing** — the census is self-referencing, but a def-adding PR cannot edit
  `docs/learned/`; the `/learn` pass is where the listing update lands.

**When a census carries a hand-written type mirroring an `as const` tuple, derive the type from the
tuple** — that deletes a lockstep site instead of growing it. A **rename** walks the same census plus
a `git mv` of the source. The test seam for the packed artifact is `workflow/distribution.md`'s
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

**`agentOverrides`.** Since 0.63.0 `subagents.agentOverrides` applies the FULL override set to
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
No live perk flow takes the first branch (the original `/pr-review` child posted its own review
until #660 reshaped it): read-only children report structured findings and the **parent**
reconciles and posts once — a posting agent run in parallel would spam duplicates. **D1:** the
GitHub mutation is canonical in Python (`perk pr review-post` / `review-submit`); a child never
holds a token or composes the mutation; the fallback ladder is `workflow/github-gateway.md`'s.

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

**Writer-flow craft — report the observed state, never a promise.** Once a writer child has been
dispatched, every failure and withheld message must report the **observed** state of artifacts it
may have moved: a successful publish can move a staging directory into place before the parent's
corroboration fails. "Present" means left for inspection, "absent" means it may have published
(the library may have changed), "unknown" means unknown.
`extension/pi/v1/librarian.ts::stagingNote` renders exactly these three states.

## Execution surfaces and structured output

**Surfaces.** Direct `{agent, task}` is the idiomatic one-child shape — a native structured single
mode (`normalizePublicSubagentExecution`; `output: true` by default; synchronous under
`asyncByDefault: false`). The tool's `workflow` field is the multi-agent surface (`true` runs the
reply's ```` ```js workflow ```` block, a string with `/` loads a script file, any other string
names a workflow resource); the RPC `spawn` takes inline script text as `script`; mixing execution fields is rejected (`action` has
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
Spawn-time `output` is the persistence mechanism — defs never restate it. Schema SSOTs are module
constants (`PR_REVIEW_REPORT_SCHEMA`, `extension/waves/prReviewWave.ts`;
`REVIEW_CLASSIFIER_REPORT_SCHEMA`, `extension/waves/reviewClassifierWave.ts`;
`OBJECTIVE_EXPLORER_REPORT_SCHEMA`, `extension/waves/objectiveExplorerWave.ts`), never
prompt-transcribed. A hand-copied `outputSchema` once nested `counts` wrongly and rejected every
child payload (`Missing structured_output call`).

**Acceptance hazard.** With `acceptance` omitted the engine infers a contract from the def's
declared `acceptanceRole` alone (`inferLevel`, `src/runs/shared/acceptance.ts`): `writer` ⇒
`checked`, `read-only` ⇒ `none`, anything else ⇒ `attested` — and perk's defs declare no role.
Version history: 0.63.0 stopped injecting inferred acceptance into reviewer and read-only
prompts; 0.70.1 narrowed inference to the declared role, retiring the agent-name inference
(`reviewer`/`oracle`/`scout`/`researcher`/`analyst` names ⇒ read-only, `worker` ⇒ writer —
`docs/design/archive/pi-subagents-0.70.1-reverify.md`).
Any level but `none` injects an `## Acceptance Contract` completion instruction
(`formatAcceptancePrompt`) demanding an acceptance report — under an `outputSchema`, an
`acceptanceReport` object inside the final `structured_output` call; otherwise a fenced
`acceptance-report` block — a COMPETING contract once observed steering a child into
acceptance-shaped `structured_output` attempts (schema-rejected, run failed). perk's report-wave
module therefore passes `acceptance: {level: "none", reason}` on EVERY wave spawn
(`extension/waves/transport.ts::WAVE_ACCEPTANCE`; `explicitAcceptanceCanDisable`) —
`report-waves.md` § "The fixed spawn contract carries an explicit acceptance disable".

## Supervisor channel

**Every perk spawn surface runs with the bridge off.** The intercom bridge appends
`contact_supervisor` to a nonempty explicit allowlist when active
(`src/intercom/intercom-bridge.ts::applyIntercomBridgeToAgent`) AND appends
`DEFAULT_INTERCOM_BRIDGE_TEMPLATE` to the child's system prompt — a template that itself tells the
child to send `contact_supervisor({reason: "progress_update"})` on meaningful progress. Since
0.68.0 the parent-side channel **discards** every non-reply request
(`native-supervisor-channel.ts::poll` removes a non-reply request file and moves on — no
`sendMessage`, no event, no storage; upstream #2229, deliberate, no opt-in) while the child tool
still returns "Supervisor progress update queued." — so a streaming child burns tool calls on
batches nobody receives. Perk therefore passes the per-launch override
`intercomBridge: {mode: "off"}` on EVERY wave spawn
(`extension/waves/transport.ts::WAVE_INTERCOM_BRIDGE`, beside `WAVE_ACCEPTANCE`;
`SubagentParams.intercomBridge` "replaces the global config for this launch only", honored on RPC
`spawn` and spread onto every workflow child via `workflowDefaults`): `resolveIntercomBridge`
yields `active: false` → no tool, no template. The foreground writers send the same override
(`FOREGROUND_INTERCOM_BRIDGE` in `extension/pi/v1/foregroundDelegation.ts`, byte-equal to the wave
constant — pinned in `extension/pi/v1/foregroundDelegation.test.ts`) — audit BOTH spawn surfaces
(`extension/waves/transport.ts` and `foregroundDelegation.ts`) whenever a spawn invariant is added.
Measurement confound: the native `subagent` tool launches bridge-on, so its children carry
`contact_supervisor` — corroborate any bridge claim against real wave children. Review waves are
completion-only — the browser doors show a code-owned `perk:wave` marker; the provisional
finding-streaming protocol retired with 0.68.0 ("History (dated)"). A settings-scope
`subagents.intercomBridge.mode` affects no perk flow. A **decision-type** request from a lane is a
lane-design smell (unanswerable at parent-turn latency).

**Provider diagnostics (0.81.0).** Structured-delegation `:update`/`:response` payloads may carry
an optional `providerDiagnostics` snapshot (retry/backoff state). It replaces, never merges; it is
decoded once in `extension/substrate/providerDiagnostics.ts`, is display-only, and reaches the
foreground progress sink until *settlement* — the status-slot path is in
`workflow/mergeability-and-conflict-resolution.md` § The transport.

**Wakes (0.81.0).** Since 0.80 the completion notice is itself the waking custom message
(`subagent-notify`, sent with `triggerTurn`; Pi ≥ 1.2.0 required) — a preview (a return slice plus
bounded child previews), never the report. perk promises nothing about the notice across a
same-session `/reload` in either direction: persisted wakes (`subagent-notify-pending`) are written
only for a non-reload shutdown and replay at the next *fresh binding* of the session (a new process,
or a switch/resume back in the same process), while a reload re-adopts in-memory bookkeeping and
resends nothing. The Escape hold is binding-local (reset by `agentStarted`, compaction resume and
every `session_start`); a held notice is appended `triggerTurn: false` with a `Parent action:`
line. Pi refuses a mid-turn `/reload`, so a reload during a busy turn always follows an Escape.
Oracle facts: a failed/paused/stopped child wakes the parent while the workflow runs; a completed
child's incremental notice is `display: false` and wakes nothing — only the matching WORKFLOW
completion authorizes collection; wake turns usually hold more than one assistant message, so never
write an "exactly one assistant entry" oracle. Since wake turns are custom starts, they run perk's
per-prompt reconciliation and both injectors (`pi/extension-api.md` § `before_agent_start`).
`bg_wait` exists upstream for non-notifying background work; perk does not adopt it. The parent
collection protocol and browser reconciliation are `workflow/report-waves.md` § "Start/collect
pairs" (the collection protocol, the collect grace, the wake rule) and § "Delivery after
collection" (browser reconciliation). Meta-lesson: phrase a corrected supplier claim in the
supplier's own mechanism (`SessionManager` binding identity), not a proxy (process lifetime).

## The v1 extension RPC seam

`src/extension/rpc.ts` is an extension-to-extension bridge on pi's in-process event bus; perk's
`extension/waves/rpcAdapter.ts` is the consumer.

- **Envelope**: requests on `subagents:rpc:v1:request` as `{version: 1, requestId, method, params?,
  source?}`; one reply on `subagents:rpc:v1:reply:<requestId>` as `{…, success: true, data}` or
  `{…, success: false, error: {code, message}}`. Methods: the `SUBAGENT_RPC_METHODS` roster (at the
  last re-read `ping`, `status`, `manage`, `spawn`, `steer`, `interrupt`, `stop`, `resume`, and
  since 0.71.0 `cost` — versioned parent-plus-child spend); a `subagents:rpc:v1:ready` event
  carries the ping data (`events.ready`). perk's adapter uses `ping`, `spawn`, `stop` and
  `status`: `stop` projects a `WaveStopOutcome` (`acknowledged`, or a typed refusal `not_found` /
  `invalid_state` / `execution_failed` carried verbatim), then exactly ONE `status {id}` read
  (`terminalProof`) projects to the classes `observed` / `pending` / `unknown` / `unavailable`
  (contracts §8.35 — the CLASS is the contract, never the engine's reason text, which varies across
  releases and with the instant of the read).
- **`unknown` is final.** A stop acknowledgement, a dead pid, `endedAt` or a freed slot never
  upgrades it. Example — the never-started-writer stop: a stop landing after the runner pid exists
  but before `subagent.run.started` closes a runner that never started a writer, and
  `process-terminal.js` writes a permanent `unknown` (`writer-close-unverified`); perk renders
  `child termination unconfirmed (unknown: …)` — a supplier timing artifact, not a leaked process,
  never "fixed" by inferring termination. Stage any stop-a-running-writer leg on the child's
  `subagent.run.started` event in its own `events.jsonl`, never on `status.json` pid+running
  (procedure: `docs/developers/pi-subagents-reverify.md` step 5).
- **Vocabulary.** The RPC `stop` aborts a live in-process workflow's in-memory controller and
  returns before any durable control-request write — it is not a "persisted request" (that phrase
  belongs to the tool-action `stopAsyncRun`); trace the exact branch perk's call takes before
  borrowing words from a same-named function. `/reload` stops an in-process workflow
  (`stopCause: null`) and a later `stop` answers `invalid_state`.
- **Workflow reuse and the launch token.** `findWorkflowReuseSource` matches the newest terminal
  run with the same `scriptDigest` + `argsDigest` and `stopCause: "runtime-replaced"` (which
  `/reload` stamps on every live workflow), so an identical relaunch once returned the replaced
  wave's reports as fresh. perk defeats the key with a per-launch `args.launch` token (visible in
  `status.json.workflow.args`; `report-waves.md` § The fixed spawn contract); re-verify at each
  bump that the reuse key still includes `argsDigest`.
- **Partial and single-run facts.** Partial `results[]` omit still-running `runs.all` lanes (roster
  only — `report-waves.md` § Native partial settlement). `outputPartial` reaches only the
  single-run path; the workflow projection carries `success: child.ok`, so reading `ok` alone is
  correct.
- **Child MCP.** A supplier child gets `builtin:mcp` only for `mcp:` selectors, so perk report
  children register no MCP tool even with a trusted `.pi/mcp.json`; a def's `excludeTools` is inert
  beside an explicit `tools:` allowlist (perk pins both absent on every def).
- **Discovery.** `findPeerPackageDir` walks every ancestor `node_modules`, so global siblings
  resolve; untrusted-project discovery (0.77.0+) refuses at spawn preflight (`execution_failed` /
  `Unknown agent`), creating no workflow dir or lane; a scratch `PI_CODING_AGENT_DIR` does not
  isolate agent discovery (`~/.agents` is also read); 0.76.x refuses an in-process supplier version
  change — swap with Pi stopped.
- **Supplier-swap session boundary.** After installing a new supplier on disk a warm session still
  holds the old modules — use no subagent surface and do not `/reload`; warm `/submit`'s
  conflict-resolver guidance is not a process boundary (decline it; rebase by hand or hand off);
  credit the first fresh-process dogfood to the next session on a checkout carrying the pin.
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
- **The pre-digest recipe (foreign seams).** `pi-subagents` is not an allowed bare import (absent
  from `ALLOWED_PACKAGES`, `extension/bareImportGuard.test.ts`), so the planning session reads the
  unimportable dependency's source and pre-digests it into the plan, the versioned envelope's
  literals are pinned as module constants in `rpcAdapter.ts` (the versioned envelope exists for
  exactly this), and unversioned names stay advertised, never pinned (`events.asyncComplete`
  comes from `ping`).
- pi's `EventBus.on` returns an unsubscribe function — per-request reply subscriptions dispose
  cleanly (`extension/pi/v1/providers/plannotator.ts::requestPlannotatorPlanReview` does the same).
- **A second responder — Pi 0.85.1's pre-trust extension leak.** Without `--approve`, a
  user-scope package's extension loaded pre-trust and then deduped away keeps its `pi.events`
  subscriptions: an orphan RPC bridge that never sees `session_start` answers every non-ping
  request `no_active_session`, and `/reload` does not clear it (perk's own repo never sees it —
  `[pi] agent_dir` sidelines user-global settings). Record:
  `docs/design/archive/pi-pre-trust-extension-leak.md`; perk's answer is the wave adapter's
  context-less hold (`workflow/report-waves.md` § "The context-less RPC hold") + doctor
  `subagent-package-scope`.

## Runner launchers (0.81.0 `runnerLaunchers` — characterized, NO-GO)

- **Where a launcher lives.** Only in the user agent dir's `extensions/subagent/config.json`
  (follows `PI_CODING_AGENT_DIR`; `<main>/.pi/agent` in this repo); an agent file can only *name*
  one (`launcher:`) — `agentOverrides` and agent management reject it. It is argv composition, not
  a sandbox policy.
- **What it cannot wrap.** Foreground children (both perk writers), `machine:` placement and
  external runners.
- **Refusal shape.** An undefined launcher is refused before anything starts with no unwrapped
  fallback; perk projects one keyed `lane-failed` with the engine text, `complete: false`, no
  `run-failed` — `normalizeAssignments` already handles it.
- **Files.** `status.json` gains `launcher: {name, argv}` (never env); `pid` is the runner's
  self-reported pid (≠ the wrapper pid) and is absent until the startup handshake;
  `launcher-close.json` records the close. Stop/cancel work through an attached wrapper; the host
  `pi` spawns every wrapped runner and the child session runs in-process in the runner; the
  restriction packet and descendant ceilings are unchanged.
- **What a report role touches** (the isolation inventory a recipe inherits) — writes stay inside
  `PI_SUBAGENTS_TEMP_ROOT` + the agent dir; git, `rg` and `gh` read outside a linked worktree, and
  `gh`'s keychain token fails *silently* under a HOME read-deny; detail in the record below.
- **Verdict: NO-GO (B2 unattributable).** A recipe needs a denial source that drops no events and
  no env-token credentials. Record: `docs/design/archive/pi-subagents-0.81.0-launcher.md`; the
  seatbelt instrument craft is in `workflow/binding-design-records.md` § Characterization and
  dogfood nodes.

## Engine-coupling posture — public surfaces only

perk reaches pi-subagents only through public surfaces: the v1 RPC envelope, the delegation events,
def frontmatter, and the package `exports` subpaths (`./agents`, `./delegation`, `./child-tool-plan`,
`./preflight`, `./intercom-bridge`, `./control-channel`, `./capability-ceiling`,
`./workflow-resources`, `./shared-types`, …). The installed-engine test harnesses over the package's
`src/**` are deleted; the one bounded read of installed consumer sources that remains is the
host-SDK bridge's census drift guard (`extension/substrate/nativeSdkBridge.test.ts`, contracts
§8.73), which lexes the import *specifiers* of the installed `pi-subagents`/`pi-web-access` files —
a structural fact of the shipped artifact, never engine mechanics. Two guards:
`extension/bareImportGuard.test.ts` (§ "The v1 extension RPC seam") and
`extension/installedPackageGuard.test.ts` — no extension source spells a path into
`.pi/npm/node_modules/` (a literal, or `"npm", "node_modules"` segments) except Ponytail's
manifest-declared preflight root, the bridge's consumer install root
(`NATIVE_CONSUMER_INSTALL_ROOT` in `extension/substrate/nativeSdkBridge.ts`, which verifies
consumer roots by manifest identity and reads only their `package.json`) and the test harness's
fake-install fixture (it builds packages, never reads one); each exception is matched as a
**whole path token with equality** (a prefix check would admit `…/ponytail-fork/private`; the
test carries that control).

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

**Watch items (re-read at 0.81.0).** A second inline child extension exists: `child-session.js`
loads `pi-subagents:commands` only when a child's tools include BOTH `bash` and
`subagent_command`, and registers a *wrapped* `bash`. Unreachable today — no perk def declares
`subagent_command` — but a def that did would strip `bash`'s builtin provenance and classify it
`unknown` (a census guard is follow-up F6 of the closed #2705, never filed). The engine's
`disabledFeatures` refuses more than `workflow-scripts`: `missions` and `extension-bindings` each
refuse every perk wave (fail closed — perk spawns with `mission: false` and every lane carries the
restriction packet).

## Lane craft — evidence pitfalls, routing tokens, prompts

### Lane evidence pitfalls

**A broken host companion graph fails every lane.** When every lane fails with `Subagent runner
startup failed: … does not provide an export named …` (or `does not provide
@earendil-works/chord`), the host's global Pi companion graph is broken — detached children resolve
companions Node's way from the global install while the parent keeps working. `perk doctor` fails
the `pi` row as incoherent and `perk doctor --fix` repairs it; waves are unusable until then — say
so immediately rather than relaunching. Related: a bare project whose only package is
`npm:pi-subagents` cannot validate `structured_output` in an in-process foreground child (`Cannot
load typebox/compile`) — set `PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT`; under perk the native SDK
bridge serves `typebox` (`pi/native-sdk-bridge.md`).

**Live-probe hygiene.** The def loader requires `description:`; background structured output nests
one level deeper than foreground; the v1 RPC can answer `no_active_session` first from a duplicate
responder; scrub `PI_SESSION_FILE`/`PI_SESSION_ID`/`PI_MODEL`/`PI_PROVIDER`/`PI_REASONING_LEVEL`/
`PI_CODING_AGENT` plus the perk/`PI_SUBAGENT_*` variables before a probe.

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
`/.pi-subagents/` are gitignored; anything else blocks the submit gate). `perk pr review-context`
once wrote its scratch into the worktree CWD, where `git add -A` swept it into commits; it writes
under the run scratch dir now.

## History (dated)

Superseded rules and supplier events, one row each; the evidence lives in the cited record (the
pin and stamp chains are in § Sources).

- **0.67.0 → 0.70.0** — the host-builtin intersection read a pi-fff `grep`/`find` override as
  "host lacks grep/find" and failed reviewer/scout lanes; perk injected `PI_FFF_MODE=tools-and-ui`
  at both launch seams and ran a report-only `subagent-host-tools` doctor row (the pattern:
  `workflow/init-doctor.md` § "Report-only checks gated on an installed package's version
  range"); 0.70.0 removed the intersection and perk retired both
  (`docs/design/archive/pi-subagents-0.70.1-reverify.md`).
- **0.68.0** — a def carrying `fallbackModels` fails at load (every perk def did; waves ran 0/N);
  the parent discards `progress_update`, so waves spawn bridge-off, provisional finding streaming
  and the `subagent-bridge-config` check retired and the `perk:wave` marker replaced them;
  routine successful child completions stopped waking the parent; background children need
  Pi ≥ 0.85.1 (`docs/design/archive/pi-subagents-0.68.0-reverify.md`).
- **0.70.1** — the completion mutation guard removed (`completionGuard` ignored, dropped from
  every report def); acceptance inference narrowed to a declared role (**Acceptance hazard**)
  (`docs/design/archive/pi-subagents-0.70.1-reverify.md`).
- **0.71.0** — a validated `structured_output` survives a later provider error or abort, ending
  the valid-report ⟺ OK-lane biconditional; the RPC gained `cost`; the Pi 0.87 fork-context
  repair ships (perk children stay `context: "fresh"`); the stamp stayed 0.70.1 by owner decision
  (`docs/design/archive/pi-subagents-0.73.1-reverify.md` § "Source facts").
- **0.72–0.73.1** — TypeBox comes from Pi; `failureKind` on a failed workflow; the foreground
  display cap leaves `status.json`'s `workflow.value` uncut; consumers pinned to 0.73.1
  (2026-10-01) because 0.74.0 removed the `workflowScript` RPC spawn key
  (`docs/design/archive/pi-subagents-0.73.1-reverify.md`).
- **0.74.0–0.75.0** — the inline script key became `script`; parent project trust reaches each
  child; background workflows survive `/reload` and reuse finished children on an identical
  relaunch (perk's launch token defeats it); pin and stamp moved 2026-10-05
  (`docs/design/archive/pi-subagents-0.75.0-reverify.md`).
- **0.76.1** — pinned ahead of the stamp (`docs/design/archive/pi-subagents-0.76.1-pin.md`); the
  wake was a `custom_message` plus a steered `Subagent updates above.` turn
  (`docs/design/archive/pi-subagents-0.76.1-lifecycle.md`); certified HELD on Pi 1.1.0 —
  W4/W6/W7a FAIL, the stamp stayed 0.75.0 (`docs/design/archive/pi-1.1.0-certification.md`).
- **0.78.0–0.80** — Chord aliases became conditional; 0.80 requires Pi ≥ 1.2.0 and makes the
  completion notice itself the waking custom message (§ "Supervisor channel").
- **0.81.0 (2026-10-25)** — adopted with Pi 1.4.0 (`docs/design/archive/pi-1.4.0-adoption.md`);
  W4/W6/W7a re-specified and passed live, certified PARTIAL with the stamp moved
  (`docs/design/archive/pi-1.4.0-certification.md`); `runnerLaunchers` characterized NO-GO.
- **Next-bump hazard (0.82.0)** — from an `npm pack` read, never installed: `autoResume` defaults
  `true`, resuming reload/exit-interrupted workflows on reopen, which conflicts with
  per-activation wave collection unless perk pins it `false` (routed code follow-up;
  `docs/design/archive/pi-1.4.0-certification.md`, `docs/developers/pi-subagents-reverify.md`).
- **Agent-def delivery (#2455)** — defs moved from the wheel + `perk init`'s `.pi/agents/perk/`
  copy to package discovery; the leftover directory is a doctor migration ("The legacy
  directory").
- **Two-boolean landing** — deleted the `<active_agent>` prefix parser (`childIdentity.ts`),
  `nativeSessionKey.ts`, the sampled `parentReadOnly` supplier, `ReportWaveRequest.execution`,
  the six-reason classification and the ten-name census
  (`docs/design/pi-subagents-child-execution-policy.md` § "Dropped mechanisms").
- **Retirements** — `ADDRESS_MODEL_CLAUSE` with the two-plane classifier prompt;
  `review-angle-selector` with `/pr-review-dynamic` (#2109); the SDK in-process child (#2100);
  `perk-dev.analyst`, promoted to `perk.scout`.
- **Foreground writers (2026-09)** — `conflict-resolver` moved from a guidance-instructed
  one-child `runs.run` to code dispatch with a structured result schema; `perk.librarian` joined
  as the second writer and the shared transport moved into `foregroundDelegation.ts`.
- **Corrected claims** — `results[].agent` as assignment identity (now `childId`); "duplicate
  workflow keys throw" (only an incompatible reuse does); "a same-session `/reload` still delivers
  the queued notice" (source-derived at 0.76.1, never measured; refuted live by W4 at the Pi 1.1.0
  certification).
- **2026-10 dream audit (@6975188)** — the size watch here said ~46 KB against 63,803 bytes
  measured; the doc was distilled in place (chronology into these rows and their records)
  instead of split, and carries no byte label since (`workflow/curation-batch-craft.md`).

## Sources

- The borrowed `pi-subagents` engine at `.pi/npm/node_modules/pi-subagents/` — `src/agents/`,
  `src/runs/{foreground,background,shared}/`, `src/intercom/`, `src/extension/rpc.ts`,
  `src/workflows/{scripted-workflow,workflow-child-summary}.ts`,
  `src/shared/{artifacts,types,fork-context,pruned-fork}.ts`, `CHANGELOG.md`. The package is
  **pinned** by `SUBAGENTS_PACKAGE` (`src/perk/convergence/init/settings.py`, reconciled forward by
  `settings-wiring`); the guidance stamp is the doctor constant
  `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` (`src/perk/convergence/doctor/checks.py`, pinned by
  `tests/test_doctor.py::test_subagent_compat_verified_version_stamp_is_pinned`) — both 0.81.0,
  re-checked 2026-10-27. Pin-leads-stamp is a legitimate state in which `subagent-compat`'s WARN is
  the truthful signal. Pi's `installedNpmMatchesConfiguredVersion` accepts any installed version
  for an unranged source (installs a missing package, never refreshes an installed one) but
  reinstalls a ranged source that no longer matches the checkout's committed spec, so the pin walks
  an older install forward once a checkout's settings carry it.
- **Re-verify at each bump.** A new installed version silently re-asserts every engine fact here:
  follow `docs/developers/pi-subagents-reverify.md` (source re-read, `just ci`, a live report wave
  from a read-write session, the constant bump + its test pin, an archive record). Stamp chain:
  0.68.0 → 0.70.1 → 0.73.1 → 0.75.0 → 0.81.0; pin chain (consumers pinned since 2026-10-01):
  0.73.1 → 0.75.0 → 0.76.1 → 0.81.0 — 0.76.1 was pinned ahead of the stamp and its certification
  HELD, so the stamp never read 0.76.1. Current pair: 0.81.0, adopted with Pi 1.4.0 and certified
  PARTIAL with the stamp moved; both browser-door halves passed live (X5a plan door, X5b PR door),
  so no supplier half is owed (`docs/design/archive/pi-1.4.0-certification.md`); each event's
  record is its "History (dated)" row. Last source re-read of the mechanics here: the installed
  0.81.0 (compiled `src/**/*.js`; body paths name the upstream `.ts` modules) — provenance, not a
  currency promise. The offline source mirror under `docs/library/` is gitignored and
  per-checkout (its catalog `ref` names its version — v0.74.0 at the 2026-10 audit, older than
  the pin): never cite it for a pinned fact; cite supplier facts by release SHA
  (`skills/librarian/SKILL.md` § Source-mirror gotchas).
- **Browser-door re-verify criteria** — the push receipts are the instrument; a leg passes on all
  five: (1) launch — every requested lane runnable, `preflightFailures: []`; (2) collect —
  `complete: true`, N/N covered, `failures: []` (collect results carry no delivery outcome); (3)
  delivery — exactly one `replace: true` `push_annotations` per covered angle, every receipt the ok
  arm with `held == 0` AND `held_batches == 0` (either can be non-zero alone; `pushed: 0` on an
  empty replacement is healthy); (4) decision order — the browser decision entry comes after the
  last push receipt in file order; (5) owner observation of the `perk:wave` marker and the
  annotations, asked once. Cite JSONL line numbers from the planning session, readable as the
  `planning-session/main` byte copy in `perk learn evidence --json`.

## Cross-references

- `extension/waves/reportWave.ts` (+ `rpcAdapter.ts`, `transport.ts`; test double
  `extension/testing/memoryAdapter.ts`) — the report-wave module over the v1 RPC seam
- `extension/substrate/childRestrictions.ts`, `extension/substrate/toolGating.ts`,
  `extension/pi/v1/contextInjection.ts` — the two booleans' consumer, the gate, the guidance fence
- `extension/pi/v1/foregroundDelegation.ts` (the shared writer transport),
  `extension/pi/v1/delivery/conflictResolverEngine.ts`, `extension/pi/v1/librarianEngine.ts`;
  `extension/waves/scoutWave.ts` / `extension/pi/v1/scoutWave.ts`
- Foreign-tool governance (pi-subagents' `delegation` package row, the child-engine synthetic-path
  row) lives in `pi/tool-loadout.md` — do not restate it here.
- `perk/convergence/init/extension_install.py::shipped_agent_defs_dir`,
  `perk/convergence/doctor/legacy_agent_defs.py`, `perk/convergence/doctor/checks.py`, `agents/*.md`
- `docs/design/pi-subagents-child-execution-policy.md`; `docs/developers/pi-subagents-reverify.md`;
  `docs/learned/workflow/report-waves.md` (the boundary partner)
- `shared/contracts.md` §8.3 (two-boolean decode), §8.10 (`disableBuiltins` / re-enable), §8.35
  (the packet producer); the supplier-shipped `pi-subagents` skill (its `skills/pi-subagents/`
  directory in the installed package)
