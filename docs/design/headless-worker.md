# Design: the headless stage-drive worker (in-process SDK pathway)

**Status:** design spike / audit (Objective #137, Node 1.1 — the deliverable is **documentation, not
code**)
**Motivation:** Objective #137 wants a **headless READ-WRITE stage worker** — a TypeScript SDK
entrypoint (node 1.2) that drives one stage (`implement`/`address`) end-to-end on a *prepared*
worktree, running the **same** perk extension package, with a locked `resourceLoader` and
auto-compaction/auto-retry off. This doc audits whether that is achievable against pi's
`createAgentSession`/`createAgentSessionRuntime`/`SessionManager` surface and the perk extension as
it stands today, enumerates the **gaps** node 1.2 must close (§A), and **locks the worker's
contract** (§B) so 1.2 implements against a settled spec and nodes 1.3 (the structured event stream)
and 4.1 (the e2e harness) consume a settled outcome shape.

This node ships the doc only. There is **no worker code, no tests, no registry change, and no
`shared/contracts.md` change** here — the registry already records the relevant truth (`implement`
and `address` carry `doors.cold_remote: true`; every other stage `false` — `shared/registry.yaml`),
and no cross-plane *behavior* changes in this node. **Node 1.2 amends `shared/contracts.md` when it
lands the worker.**

## Status / how the cold door works today (the pathway being replaced)

- **Today the cold door execs an interactive `pi`.** `perk/launch.py` `launch_stage(...)` mints a
  `run_id`, writes the handoff blob (`cache.write_handoff`), materializes the plan-ref
  (`cache.write_plan_ref`) and plan body (`_materialize_plan_body`) into the worktree, sets
  `PERK_RUN_ID` in the env, `os.chdir(wt)`, and `os.execvpe(<absolute pi path>, argv, env)` — "the CLI *becomes*
  pi — nothing after this runs." The session is **human-driven** in a TUI. The initial prompt is
  seeded by `_initial_prompt(stage, plan_ref)` (`_implement_prompt`/`_address_prompt`/`_learn_prompt`),
  and skill-binding nudges are appended via `render_cold_bindings`.
- **The remote door is resolved but not driven.** `resolve_target(stage, remote)` returns a local or
  remote `Target`; a `--remote` launch on a `cold_remote:true` stage surfaces a `RemoteTarget`
  descriptor over `--json` and exits `remote_not_driven` (`_surface_remote_target`).
  `docs/cli-vs-pi.md` §4.5 records: "Phase 2 builds and resolves the target; the Phase-3 worker
  drives it."
- **The prior-art reference (erk) drives a *subprocess* CLI, not in-process SDK.**
  erk's `.github/workflows/plan-implement.yml`'s "Run implementation" step is
  `claude --print --output-format stream-json --dangerously-skip-permissions /erk:plan-implement`,
  capturing the exit code as the success signal. perk's objective #137 chooses the **in-process SDK**
  pathway instead (`createAgentSession`/`SessionManager`), which is why this audit exists: the SDK
  drive has rebind/abort/resource-loader concerns a `--print` subprocess does not.
- **perk already has one in-process SDK session, but it is the *inverse* of the worker.**
  `extension/readOnlySession.ts` (`createReadOnlySession`/`runReadOnlyChild`) spins a **read-only,
  fully-isolated** child via `createAgentSession` with `DefaultResourceLoader` `no*` flags (loads
  *nothing* — explicitly NOT perk's extension) and `SDK_READ_ONLY_TOOLS = ["read","grep","find","ls"]`.
  The worker needs the opposite: **read-write tools + the SAME perk extension loaded**, but still
  locked against *user* config. This inversion is the central tension of the worker.

---

## §A — The gap list

Each gap is stated as **requirement → what exists → the gap → the resolution 1.2 implements**, all
anchored to real symbols.

### Gap 1 — The `createAgentSessionRuntime` rebind rule

- **Requirement:** the worker must survive session replacement (re-subscribe its event listeners +
  re-`bindExtensions` on the new `AgentSession`).
- **What exists:** `extension/readOnlySession.ts` uses **bare `createAgentSession`** and never
  replaces the session, so **no existing perk code honors the rebind rule.** Pi's SDK doc
  (`docs/sdk.md`, "createAgentSessionRuntime() and AgentSessionRuntime") states the rule explicitly:
  after `newSession()`/`switchSession()`/`fork()`/`importFromJsonl()`, `runtime.session` changes,
  "event subscriptions are attached to a specific `AgentSession`, so re-subscribe after replacement,"
  and "if you use extensions, call `runtime.session.bindExtensions(...)` again for the new session."
- **The gap:** the worker observes the agent through a `session.subscribe(...)` listener (to detect
  the terminal signal — Gap 6); a session replacement mid-drive would silently orphan that listener
  and unbind perk's extension. A bare `createAgentSession` cannot express the rebind.
- **Can replacement actually fire during a headless drive?** One perk path replaces the session:
  `extension/lifecycleGates.ts` `registerLifecycleGates`'s warm `/implement` in-worktree handoff
  calls `ctx.newSession(...)`. But (a) it is **headless-guarded** — it requires `ctx.hasUI` for the
  confirm/handoff and otherwise logs to stderr and returns (`"a fresh-context /implement handoff
  needs an interactive session"`), and (b) the worker's seeded prompt instructs `/submit`, never
  `/implement`. Objective budget compaction uses `ctx.compact(...)` (`extension/pi/v1/objective.ts`
  `turn_end`), which is **in-place and does NOT replace the session**. So replacement is not
  expected on the happy path.
- **Resolution (1.2):** the worker is built on
  **`createAgentSessionRuntime(createRuntime, { cwd, agentDir, sessionManager })`** (the
  `createAgentSessionFromServices`/`createAgentSessionServices` factory shape from `docs/sdk.md`),
  **not** bare `createAgentSession` — even though the happy path never replaces — so the rebind rule
  is honored *defensively*: a small `bindAndSubscribe(runtime.session)` helper (capture the loaded
  extension set once from the `LoadExtensionsResult.runtime`, call `bindExtensions`, attach the
  terminal-detection listener) is invoked once at startup and **re-invoked after any runtime
  mutation method**. The worker treats an unexpected mid-drive replacement as a loud structured-log
  event (it should not happen given the guards above).

### Gap 2 — Abort / signal propagation

- **Requirement:** the worker is bounded by a budget/timeout and must be cancellable; cancellation
  must reach in-flight tool execs.
- **What exists:** `AgentSession.abort(): Promise<void>` (`docs/sdk.md`). perk tools already thread
  `ctx.signal` into shelled work — e.g. `extension/submit.ts` calls
  `pi.exec(perkBin, ["pr","submit","--json"], { cwd: ctx.cwd, signal: ctx.signal })`.
  `extension/readOnlySession.ts` `runReadOnlyChild` already models an external
  `opts.signal: AbortSignal`, checking `signal.aborted` before start and after the task. **But there
  is no existing code wiring an external `AbortSignal` → `session.abort()` for a full read-write
  drive** — the read-only child never aborts an in-flight prompt; it only short-circuits around
  `runTask`.
- **The gap:** the worker must own the budget→abort wiring: a wall-clock/turn/token budget that, when
  exhausted, calls `session.abort()` and resolves the drive as a terminal failure with a typed
  reason — and the abort must propagate to a running `submit`/`subagent`/`bash` exec via the
  pi-internal `ctx.signal` chain.
- **Resolution (1.2):** the worker constructs an `AbortController`; the budget watchdog (max turns
  from `turn_end` counting, token budget from `ctx.getContextUsage()`/usage summation à la
  `extension/pi/v1/objective.ts` `sumAssistantTokens`, and a wall-clock timeout) aborts it; the worker
  `await session.abort()` and returns `status: "aborted"` or `status: "budget_exhausted"` (Gap 7).
  Abort is **hard** (does not wait for the terminating tool). The contract (§B) documents that perk's
  already-`ctx.signal`-aware tools (`submit`, `finalize_address`, `run_ci`) propagate the
  cancellation into their shelled `perk …` subprocesses.

### Gap 3 — Compaction-off + retry-off determinism

- **Requirement:** deterministic single-stage drive — no auto-compaction, no auto-retry mutating the
  run.
- **What exists:** `SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled:
  false } })` is the exact recipe (`docs/sdk.md` Settings Management), and
  `extension/readOnlySession.ts` `createReadOnlySession` **already uses it verbatim**.
  `PromptOptions`/`prompt()` semantics: `prompt()` "resolves only after the full accepted run
  finishes, **including retries**" — so with retry off there are no hidden retries and a
  post-acceptance model/network error surfaces through the event/message stream (not
  `preflightResult(false)`, which fires only for pre-acceptance preflight rejection).
- **The gap — the objective-compaction bypass:** the settings flag does **not** govern perk's own
  threshold compaction. `extension/pi/v1/objective.ts`'s `turn_end` handler calls `ctx.compact(...)`
  directly (the `trigger-compact.ts` pattern), bypassing `SettingsManager.compaction.enabled`. Left
  unaddressed, an active objective in the drive session would re-introduce non-determinism.
- **Verified-safe resolution:** that handler is **inert unless an objective is active** — its first
  line is `if (activeObjective(ctx) === null) return;` (verified in `extension/pi/v1/objective.ts`).
  `active_objective` is set **only** by `/objective <id>` and the `objective_save` tool — **never**
  by the `implement`/`address` cold-door positioning (`perk/launch.py` writes only
  `{stage, mode, …handoff_extra}` to the handoff; it sets no objective field). So a prepared
  `implement`/`address` worktree session has `active_objective == null` and `ctx.compact` never
  fires.
- **Resolution (1.2) — make it a contract invariant:** the worker sets
  `SettingsManager.inMemory({ compaction:{enabled:false}, retry:{enabled:false} })`, AND the contract
  (§B) records the **hard invariant that the drive session must never have an active objective** (the
  worker must not call `/objective`/`objective_save` in the driven session, and must not seed an
  `objective_id` into the *driven* run's workflow-state). Together these two give determinism:
  settings-off kills SDK auto-compaction; objective-inactivity kills perk's threshold compaction.

### Gap 4 — Locked-down `resourceLoader` (fixed resource set, no user config)

- **Requirement:** the worker runs the **SAME perk extension package** but with a **fixed resource
  set and no user config** (no arbitrary user-global extensions/skills/prompts/settings).
- **What exists — and the inversion:** `extension/readOnlySession.ts` proves the isolation primitive
  but in the *wrong direction*: its `DefaultResourceLoader` sets
  `noExtensions/noSkills/noPromptTemplates/noThemes/noContextFiles` (loads nothing — its own comment:
  this is "**NOT** `extensionFactories: []`… the `no*` flags keep perk's machinery out of the
  child"). `docs/sdk.md` (ResourceLoader / Directories) documents the discovery split: with a
  `DefaultResourceLoader`, **`cwd`** drives *project* resources (`.pi/extensions/`,
  `.pi/settings.json` extension sources, `.agents/skills/`, `AGENTS.md` walking up) and **`agentDir`**
  drives *global/user* resources (`~/.pi/agent/extensions/`, global `settings.json`, `models.json`,
  `auth.json`, `~/.agents/skills/`).
- **The gap:** there is no existing perk loader that keeps the **project tier** (perk's own extension
  via the worktree's managed `.pi/settings.json`, plus the worktree `AGENTS.md` managed block + the
  `.pi/APPEND_SYSTEM.md` ambient index) while excluding the **user-global tier**. The worker needs
  exactly that asymmetric load.
- **Resolution (1.2):** the worker constructs a `DefaultResourceLoader` with
  **`cwd = <prepared worktree>`** (so project extensions/skills/context — including perk's
  `@mgiles/perk` extension referenced by the managed `.pi/settings.json`, and the managed
  `AGENTS.md`/`APPEND_SYSTEM.md` — load) and **`agentDir = <throwaway temp dir>`** (so NO user-global
  extensions/settings/skills/models/auth leak in — the same throwaway-`agentDir` trick
  `createReadOnlySession` already uses for a different purpose). It calls `await loader.reload()`
  before `createAgentSessionRuntime` (custom loaders are not auto-reloaded). **Open item the contract
  pins for 1.2 to verify (not a decision — a verification step):** confirm under test
  (`SessionManager.inMemory()` harness) that a throwaway `agentDir` still resolves the *project*
  `.pi/settings.json` perk package (it should, since project-package discovery is `cwd`-driven and
  the package is installed locally under `.pi/npm/node_modules`), and that auth/model resolution
  still works (auth comes from the `ModelRuntime`/env per Gap 5, not from the throwaway `agentDir`).

### Gap 5 — Model / auth in a headless (CI) context

- **Requirement:** the drive needs a model with a valid key without a user's interactive `auth.json`.
- **What exists:** `ModelRuntime` resolution priority (pi ≥ 0.84's canonical model/auth runtime,
  which absorbed the earlier `AuthStorage`/`ModelRegistry` pair): runtime
  override → `auth.json` → **env vars (`ANTHROPIC_API_KEY`, etc.)** → fallback resolver.
  `modelRuntime.setRuntimeApiKey(provider, key)` is the not-persisted CI override.
  `extension/structuredOutput.ts` `resolveModelAuth` shows the in-session fallback path
  (`ctx.modelRegistry.getApiKeyAndHeaders(model)`; pi ≥ 0.84 prefers registry dispatch —
  `ctx.modelRegistry.complete`).
- **The gap:** the cold door's interactive `pi` inherits the user's `auth.json`; a headless worker
  with a throwaway `agentDir` (Gap 4) has none.
- **Resolution (1.2, restated for pi 0.84):** the worker builds `await ModelRuntime.create()`
  (offline by default — `allowModelNetwork` defaults false) and relies on **env-var key
  resolution** (CI sets `ANTHROPIC_API_KEY`/equivalent), optionally `setRuntimeApiKey` from an
  explicit worker input. Model selection: explicit worker input (a stage→model mapping is
  2.2/2.4's concern), else the SDK's own default resolution at session creation (settings
  `defaultModel` → pi's per-provider defaults → first available — never a pre-pinned
  alphabetically-first pick). The contract lists `model` + `auth` as inputs.

### Gap 6 — `ctx.mode` print/json and `ctx.hasUI === false` — extension behavior headless

- **Requirement:** under a headless drive every perk extension surface must behave correctly with
  **`ctx.hasUI === false`**, and the worker must establish a non-TUI mode.
- **What exists:** the mode/UI matrix (`docs/extensions.md` "Mode Behavior"): `tui`→hasUI true;
  `rpc`→hasUI true; **`json`→hasUI false (UI methods no-ops)**; **`print` (`-p`)→hasUI false
  ("extensions run but can't prompt")**. perk's extension is **already audited headless-safe**:
  `extension/index.ts` records `ctx.mode ?? null` as `run_mode` and guards the load notify with
  `ctx.hasUI`; every UI call across the extension is `ctx.hasUI`-guarded with a `console.error`
  fallback (verified in `address.ts`, `submit.ts`, `land.ts`, `learn.ts`, `objective.ts`,
  `checkpoints.ts`, `planMode.ts`, `lifecycleGates.ts`, `objectivePlanning.ts`,
  `objectiveAuthoring.ts`, `learnDocs.ts`, `ready.ts`, `selfcheck.ts`). The session-lifecycle linkage error path is
  explicitly headless-safe (`extension/index.ts` `reportError`; test `sessionLifecycle.test.ts` "a
  missing handoff is reported, not thrown"). The CI executor **fails closed headless**
  (`decideCiScope` → `"refuse"` when `!hasUI && !flag`).
- **The gaps to record:**
  1. **`ctx.mode` is undefined in a bare SDK drive.** `extension/index.ts` already writes
     `ctx.mode ?? null` — i.e. the SDK session may present `ctx.mode === undefined`. The worker must
     establish a mode where `ctx.hasUI === false`. (The driving model is irrelevant — perk gates on
     `ctx.hasUI`, not on `ctx.mode`, everywhere except the `run_mode` observability sentinel.)
  2. **"Print mode can't prompt" does NOT block the worker.** The warm *command* turn-drivers
     (`/address`, `/objective-plan`, `/learn-docs`, `/objective-save`, bare `/learn`) drive a turn
     via `pi.sendUserMessage`/`ctx.newSession`; in headless they early-return or log (e.g. `learn.ts`
     "headless can't drive a turn", `learnDocs.ts` headless early-return). **The worker does not use
     these command turn-drivers** — it seeds the initial prompt itself via `session.prompt(...)`
     (mirroring `perk/launch.py._initial_prompt`), and the stage's *tools* (`submit`,
     `classify_review_feedback`, `finalize_address`) are called by the model in response. So the
     "can't prompt" limitation is irrelevant to the worker's path.
  3. **Subagent-under-worker is the one untested headless dependency.** The `address` drive's seeded
     prompt (`perk/launch.py._address_prompt`) instructs the model to classify via the
     `classify_review_feedback` tool, whose wave runs the `perk.review-classifier` child through
     the report-wave module over the borrowed `pi-subagents` v1 extension RPC — so the worker
     still needs the full settings-resolved package set (the RPC responder). `shared/contracts.md`
     (§8.3, T6) records the **open-#6 spike** ("runs cleanly headlessly") as the standing question
     and explicitly **defers the "runs under the worker" live smoke to Phase-3 `doctor workflow`**
     (the fake-RPC e2e validates perk's adapter, not the real pi-subagents workflow host under the
     headless worker). This is the single behavioral dependency the `address` drive carries that
     is not yet proven headless.
- **Resolution (1.2):** the worker establishes a headless mode such that **`ctx.hasUI === false`**
  for the driven session (json-equivalent; the worker writes structured events to its own channel —
  1.3 — not pi's stdout JSON stream). The contract records `hasUI=false` as a required property of
  the drive. The `address`-path subagent dependency is carried into 1.2 as a known risk and into the
  Phase-3 `doctor workflow` live smoke.

### Gap 7 — Run-id claim & the prepared-worktree assumption

- **Requirement:** the driven session must claim its `run_id` and link its workflow-state exactly as
  a cold `pi` would, so checkpoints/plan-ref/gating all engage.
- **What exists:** `extension/index.ts` `session_start` reads `process.env.PERK_RUN_ID`, verifies
  `handoff/<run_id>.json` (establish-before-consume), appends `perk:workflow-state`, marks the
  handoff consumed, reconciles `active_plan_ref` for ref-consuming stages, and syncs tool gating from
  `mode`. `perk/launch.py` already materializes the handoff + plan-ref + plan body into the worktree
  before exec.
- **The gap:** the worker runs **on a prepared worktree** (node 1.2's wording) — i.e. positioning
  (worktree create, handoff/plan-ref/plan-body materialization, `run_id` mint) is done by the
  cold-door/runner *before* the worker starts; the worker must **not** re-mint or re-materialize. It
  must inherit `PERK_RUN_ID` in its env so the extension's `session_start` claim path runs unchanged.
- **Resolution (1.2):** the worker is invoked with `PERK_RUN_ID` already set and the worktree already
  materialized (by `perk/launch.py` positioning, factored so the runner can position-without-exec).
  The worker sets `cwd`/`SessionManager`/`agentDir` accordingly and lets the extension's existing
  `session_start` claim engage. Read-write mode (from the handoff `mode`) means tool gating imposes no
  restriction, so `edit`/`write`/`bash`/`submit` are available. The contract lists the prepared
  worktree + `PERK_RUN_ID` as inputs.

---

## §B — The worker contract

This is the spec node 1.2 builds and nodes 1.3 / 4.1 consume.

### Inputs

| input | shape | source |
|---|---|---|
| `worktree` | absolute path, already positioned | the cold-door/runner positioning (`perk/launch.py` `resolve_worktree` + materialization), not the worker |
| `stage` | `"implement" \| "address"` | the only `doors.cold_remote: true` read-write stages (`shared/registry.yaml`) |
| `run_id` | ULID, present as `PERK_RUN_ID` in env | minted by positioning; the worker inherits it (Gap 7) |
| handoff/plan-ref/plan-body | files under `<worktree>/.pi/workflow/` | materialized by positioning; the worker does not re-write them |
| `initialPrompt` | string | re-derive via the `perk/launch.py._initial_prompt(stage, plan_ref)` shape (+ resolved skill bindings); the worker seeds it with `session.prompt(initialPrompt)` |
| `model` + `auth` | `Model` + `ModelRuntime` | explicit worker input or env-var key resolution (Gap 5) |
| `budget` | `{ maxTurns, maxTokens, wallClockMs }` | worker input; the watchdog that drives abort (Gap 2) |
| `signal` | `AbortSignal` | external cancellation; OR'd with the budget watchdog |
| resource policy | `cwd=worktree`, `agentDir=throwaway`, compaction-off, retry-off, `hasUI=false`, no active objective | fixed by the worker (Gaps 3/4/6); not caller-tunable |

### Terminal-signal definition

The drive terminates on the **first** of:

1. **Terminating-tool success (the primary signal).** For `implement`: the model calls the `submit`
   tool, which returns `terminate: true` with `details.ok === true` and a `pr` (`extension/submit.ts`
   `SubmitResult.terminate` + `SubmitDetails.pr`; pi's terminate semantics: the follow-up LLM call is
   skipped when every finalized result in the batch is terminating — `docs/extensions.md` "Early
   termination"). The worker detects this via its `session.subscribe` listener observing a
   `tool_execution_end` for `submit` with the success `details`. → `status: "completed"`.
   For `address`: the terminating `finalize_address` tool must succeed, append
   `perk:workflow-state.last_review_batch`, and carry successful effective submit evidence with
   `mergeable !== false`; a later clean standalone submit from conflict resolution supersedes the
   nested finalizer submit, while a later failed submit cannot complete the drive. →
   `status: "completed"` when the predicate holds at idle.
2. **Driving `prompt()` resolved (agent idle) — verified against the success predicate.**
   `session.prompt(initialPrompt)` resolves when the agent stops (`docs/sdk.md`). Because the agent
   can stop **without** completing the stage (asked a question, gave up), idle is **not** itself
   success: the worker must verify the stage predicate from durable state (PR opened for `implement`
   via `SubmitDetails`/`find_pr_for_branch`; threads resolved for `address` via `last_review_batch`).
   Idle without the predicate → `status: "failed"` with reason `incomplete`.
3. **Budget/timeout/abort.** The watchdog or external `signal` fires → `session.abort()` →
   `status: "budget_exhausted"` (budget) or `status: "aborted"` (external signal).
4. **Post-acceptance error.** With retry off, a model/network error after prompt acceptance surfaces
   through the event/message stream (`agent`'s `errorMessage`/an error event), not
   `preflightResult(false)` → `status: "failed"` with the captured error.

### Outcome shape

Lock now; 1.3 builds the event stream that carries it, 4.1 asserts it.

```jsonc
{
  "run_id": "<ULID>",
  "stage": "implement" | "address",
  "status": "completed" | "failed" | "aborted" | "budget_exhausted",
  "terminal_signal": "submit_tool" | "address_resolved" | "agent_idle_incomplete"
                    | "budget" | "external_abort" | "model_error",
  "pr": { "number": 0, "url": "" } | null,   // populated on a completed implement; from SubmitDetails
  "budget": { "turns": 0, "tokens": 0, "elapsed_ms": 0 },
  "error": { "type": "string", "message": "string", "summary": "string" } | null
}
```

- `error.summary` is the **terminal failure summary** node 1.3 requires (a short, model-free
  synthesis of why the drive failed — capped, à la the `route-don't-relay`/double-delivery
  discipline; the full detail stays in the 1.3 structured event channel, not in the model-visible
  surface).
- The shape is **additive-stable**: 1.3 may add fields; existing fields keep their meaning.

### Construction recipe (the shape 1.2 instantiates — pins the resolved choices)

- **Runtime:** `createAgentSessionRuntime(createRuntime, { cwd: worktree, agentDir: throwaway,
  sessionManager: SessionManager.create(worktree) })`, with the
  `createAgentSessionServices`/`createAgentSessionFromServices` factory (Gap 1). A
  `bindAndSubscribe(runtime.session)` helper binds perk's extension and attaches the
  terminal-detection listener; re-invoked after any runtime replacement.
- **Resource loader:** `DefaultResourceLoader({ cwd: worktree, agentDir: throwaway })` (project tier
  in, user-global tier out), `await loader.reload()` before runtime creation (Gap 4).
- **Settings:** disk-layered — `SettingsManager.create(worktree, throwawayAgentDir)` +
  `applyOverrides({ compaction: { enabled: false }, retry: { enabled: false } })` (Gap 3; the SDK's
  "with overrides" shape). The overrides ride the merged view only; package resolution reads the
  per-scope raws, so the managed `.pi/settings.json` `packages` list resolves — the project tier
  actually loads perk + the borrowed packages. (Superseded the original `SettingsManager.inMemory`
  recipe, which never read the disk package list — the remote-worker tool-loading gap.); the
  no-active-objective invariant holds because positioning never sets one (Gap 3).
- **Preflight:** post-bind, the stage's terminating perk tool (`submit` /
  `finalize_address`) must be registered, else a zero-turn `failed` outcome with
  `error.type "no_extension_tools"` under the `model_error` terminal signal (contracts.md §8.11).
- **Env:** `PERK_RUN_ID` inherited; `cwd` is the worktree so the extension's `session_start` claim
  path runs unchanged (Gap 7).
- **Drive:** `await session.prompt(initialPrompt)`; the listener resolves the terminal signal; the
  budget watchdog + `signal` can `session.abort()`.
- **Mode:** the session presents `ctx.hasUI === false` (Gap 6).

---

## Forward notes

- **Node 1.2 builds the worker** and amends `shared/contracts.md` in the same turn (this node makes
  no cross-plane behavior change, so it does not touch the contract). 1.2 also discharges the Gap 4
  verification step (throwaway-`agentDir` still resolves the project perk package + auth) under the
  `SessionManager.inMemory()` harness.
- **The `address`-path subagent-under-worker headless smoke is deferred to the Phase-3
  `doctor workflow`** (the standing open-#6 dependency in `shared/contracts.md` §8.3, T6). 1.2
  carries it as a known risk.
- **The outcome shape (§B) is the substrate** node 1.3 (the structured event stream) and node 4.1
  (the e2e harness) consume — additive-stable, asserted there.
- **Node 2.1 turns the remote door into a real drive.** The "resolved but not driven" status above
  is superseded: `perk/launch.py` `_drive_remote_target` (the dispatch driver) + `perk/runner.py`
  (the runner-agnostic `Runner` contract) persist the `run_id→plan` dispatch record
  (`.pi/workflow/scratch/runs/<run_id>/dispatch.json`), verify it, then trigger a runner
  (contracts.md §8.13). The position-without-exec entrypoint the CI workflow consumes (Gap 7) is
  **Node 2.2** — the dispatcher positions nothing locally.

---

## Outcomes (Node 1.2 — landed)

*Additive reconciliation note; the audit body above is the historical record and is not rewritten.*

Node 1.2 landed the worker as **`extension/worker.ts`** (the `driveStage` primitive + the pure
`evaluateTerminal`/`assembleOutcome`/`applyEvent` helpers, the `createBindManager` rebind manager,
`initialPromptFor`, and the runtime/budget/abort wiring) and **`extension/workerMain.ts`** (the thin
runnable entrypoint shim). The worker contract is recorded in `shared/contracts.md` §8.11.

**Two recipe corrections applied** (verified against `@earendil-works/pi-coding-agent@0.78.1`
`.d.ts`), already folded into §B above's intent:

1. The runtime-factory path does **not** accept a pre-built `resourceLoader`.
   `createAgentSessionServices({ cwd, agentDir, …, resourceLoaderOptions })` builds the
   `DefaultResourceLoader` **internally**. The worker achieves the asymmetric load by passing
   `cwd = worktree` + `agentDir = throwaway` — not a hand-built, manually-`reload()`ed loader.
2. `bindExtensions(...)` is still called **explicitly** on the runtime session.
   `createAgentSessionFromServices` only *loads* extensions; binding (which emits `session_start`
   and runs perk's claim path) happens when the host calls
   `runtime.session.bindExtensions({ uiContext: undefined, mode: "json", onError })`.

**Gap-4 verification discharged.** `extension/worker.test.ts` ("Gap-4: a bound perk session
registers the worker's terminal tools and claims its run") proves under the offline
`loadPerkSession` harness that a throwaway `agentDir` still loads + binds the project `@mgiles/perk`
extension: the `submit` and `finalize_address` tools register, and the `session_start` claim
engages for a planted handoff + `PERK_RUN_ID` (the rebuilt `perk:workflow-state.run_id` matches).
*Update (2026-09): the dedicated harness test (whose filename above was already historical) was
retired as superseded — the pin now lives in the real-factory tier + the named suites:
`extension/worker/stageExecutionE2e.test.ts` (the implement/address HAPPY scenarios complete only
if the real extension registered the terminal tools; the NO-EXTENSION-TOOLS scenario pins the
negative), `extension/sessionLifecycle.test.ts` ("claim: fresh session with PERK_RUN_ID + handoff
claims the run"), and `extension/pi/v1/delivery/address.test.ts` (registration parity, including
the `resolve_review_threads` absence).*

**Deferred, as planned:** the live model-driven e2e (Node 4.1), the structured event stream (Node
1.3, which carries this outcome shape), remote dispatch / the GitHub Actions runner (2.1/2.2), and
the `address`-path subagent-under-worker live smoke (Phase-3 `doctor workflow`, open-#6).

---

## Outcomes (Node 1.3 — landed)

The structured run-event stream shipped as a **purely additive** layer over the Node 1.2 worker (the
`RunOutcome` shape is unchanged; §8.11 stays frozen). What landed:

- A small, additive-stable `RunEvent` discriminated union (`run_started` / `step_marker` /
  `tool_outcome` / `run_finished`), each carrying a monotonic `seq` + elapsed `t` (the same clock as
  `RunOutcome.budget.elapsed_ms`). The terminal `run_finished` carries the full frozen `RunOutcome`
  — `error.summary` is the terminal failure summary. See `shared/contracts.md` §8.12.
  **Status note:** `step_marker` is since **deprecated/never-emitted** — the `[WIP:n]`/`[DONE:n]`
  marker protocol died with the checkpoints removal; the variant stays in the grammar for
  historical `events.ndjson` files (contracts §8.12).
- A dual-delivery `RunEventSink` seam (`DriveStageDeps.eventSink`): tests inject an array sink; the
  default is a fail-soft, run-scoped NDJSON **file** sink at `runEventsPath(cwd, runId)` =
  `<cwd>/.pi/workflow/scratch/runs/<runId>/events.ndjson` (a gitignored cache-tier artifact). The
  default sink is a **no-op when `run_id` is empty**, so the offline drive tests stay write-free.
- `driveStage` emits `run_started` after bind/before prompt, folds `step_marker`/`tool_outcome` into
  the existing single subscribe listener (alongside the unchanged `applyEvent`/budget-trip), and
  routes **every** terminal exit (verdict, budget/abort, drive-error catch, `no_model`) through one
  `finish()` helper so exactly one `run_finished` is emitted per drive. `workerMain` adds a stderr
  breadcrumb (`perk worker: run events → <path>`); stdout/exit-code are unchanged.
- Route-don't-relay: per-event free text is capped (`EVENT_SUMMARY_CAP = 2 KiB`); the structured
  channel carries the narrative, not raw tool payloads. The worker only *writes* the stream — no
  GitHub mutation (Node 2.3) and no live model-driven e2e (Node 4.1) here.

**Still deferred, as planned:** GitHub progress/terminal reporting (Node 2.3), the live e2e worker
harness that asserts these events end-to-end (Node 4.1), remote dispatch / the runner (2.1/2.2), and
the `address`-path subagent-under-worker live smoke (open-#6, Phase-3 `doctor workflow`).

---

## Outcomes (Node 3.1 — stage-execution confinement; landed)

*Additive reconciliation note; the audit body above is the historical record and is not rewritten —
paths and symbol names in it are as-of-audit.*

The worker's landed shape moved behind a confined seam (Objective #2083, contracts §8.11):

- `extension/worker/worker.ts` → **`extension/worker/stageExecution.ts`**; `driveStage` →
  **`runStage`**; `DriveStageOptions`/`DriveStageDeps` → `StageRunOptions`/`StageRunDeps`. The
  SDK-typed `model`/`thinkingLevel`/`modelRuntime` input triple collapsed into one opaque nominal
  `WorkerModelSelection`.
- Every `@earendil-works` import on the drive path — construction (`defaultCreateRuntime`),
  raw session events, prompt/abort, token accumulation — lives in the **private
  `extension/worker/sdkAdapter.ts`** (the `createBindManager` rebind manager grew into its
  drive-session handle). `workerMain.ts` keeps its name (the §8.14 entry pin) and imports no SDK.
- The read-only child runner this audit contrasted against (`readOnlySession.ts` —
  `createReadOnlySession`/`runReadOnlyChild`) was **deleted as dead code**; its model-visible
  capping helpers live on in `extension/substrate/modelVisible.ts`.
