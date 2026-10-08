---
title: Headless Pi session construction & driving — the SDK runtime-factory recipe
read_when: You are constructing or driving a headless (non-TUI) Pi session via the SDK — the runtime-factory path, a single-prompt drive, compaction replay, sendUserMessage persistence, or offline determinism.
cluster: pi-extension
---

# Headless Pi session construction & driving

The stage worker (`extension/worker/stageExecution.ts`, `runStage` — the public drive seam over the
private SDK adapter `extension/worker/sdkAdapter.ts`) constructs a headless, read-WRITE Pi
session at the SDK level and drives a single stage to completion with no human in the loop. This doc
captures the non-obvious shape of that construction — distilled so the next SDK-drive surface starts
from the right path instead of rediscovering it.

> **One Code Rule.** Everything below names files and describes behavior. It deliberately does **not**
> paste constructor bodies — read the source at the pointers.

## Distillation

- One live SDK recipe — the read-WRITE worker (`sdkAdapter.ts`) with the real extension; seed a
  side session through its `SessionManager`; unset `PERK_RUN_ID` in probes and in-session cold
  doors — "Two construction paths", "Seeding a side session…", "Probe scripts … unset it".
- The worker supplies Pi's `codemode` (`models: false`) + `tool-search` builtins with
  `builtin: true` (it joins the discovery cohort); MCP stays absent; `applyOverrides` before the
  services is discarded — assert knobs on live getters — "The runtime-factory path builds the
  loader internally".
- Model error rides `turn_end` (replaced per turn); the token census is per-`turn_end` (assistant +
  tool results) + per-`compaction_end` usage = `getSessionStats().tokens`; `cacheWarming` is
  global-only — "`session.subscribe()` event facts".
- The drive is a SINGLE `session.prompt(...)` spanning retry and compaction continuations (idle ≠
  done) — "Single-prompt drive, NOT a `loop.ts` loop".
- `runStage` samples the abort twice and subscribes once; init failures classify on the bind
  boundary; the turn cap stops through the agent's `finishTurn` hook (the loop ignores
  `signal.aborted` between turns) — "The `runStage` outcome boundary".
- The model-call policy: advisory textual screen + the hard `WORKER_CODEMODE_MODELS = false`;
  `toolErrorMessage` has four steps — "The structured run-event stream".
- Model selection runs inside the runtime factory after the services load (services →
  diagnostics → `selectWorkerModel` → session → bind); never default to `getAvailable()[0]` —
  "Never default the model…" → "Native-provider availability at initial model selection".
- `no_model` pins need a recording stub over the registration surface — "Offline-test
  determinism for model availability".
- Offline e2e drives the REAL runtime with a faux model; reuse `runDrive`, `observeSessionEvents`,
  `summarizationRouter`, `observeLive`, `assertWorkerKnobs`; slow tier only — "Driving the real
  runtime offline with a faux model".
- Probes, compaction replay and `sendUserMessage` joining — "Headless probe and dogfood-session
  craft", "Replaying a recorded session's compaction headlessly", "`sendUserMessage` persists ONE
  newline-joined text block". "Sources" holds the pin-bump audit list; history is inline.

## Two construction paths — pick by isolation axis

There were two SDK-level construction recipes in the tree, differing on **one axis**: read-only
vs. read-write isolation. Only the read-write half has a live carrier today.

- The fully-isolated **read-only** child (`createReadOnlySession`) was **deleted with the
  stage-execution confinement (PR #2100)** — no successor. Its loader-construction craft is kept
  here as a recipe with **no live production carrier**: bare `createAgentSession` + a
  **hand-built `DefaultResourceLoader`** with `no*` flags and a strict
  `["read","grep","find","ls"]` tool allowlist, calling `loader.reload()` manually.
- `extension/worker/sdkAdapter.ts` is the live **read-WRITE** recipe: read-write defaults + the
  **real perk extension** loaded from the worktree's `.pi/settings.json` via cwd-discovery, with the
  user-global tier locked out by a **throwaway `agentDir`** (`mkdtemp` under `tmpdir()`).

When building the next SDK-drive surface, start from the live read-write recipe and flip only the
isolation axis you need — don't reinvent both halves.

## Probe scripts launched from inside a perk session inherit the run-id env — unset it

An SDK-driven probe script (a `node probe.ts` using the `defaultCreateRuntime` recipe below)
launched from a shell **inside a perk session** inherits `PERK_RUN_ID`/`PI_SESSION_FILE`; the
probe's bound perk extension then tries to claim that run id against the main checkout (no handoff
there) and emits a loud-but-harmless `workflow-state linkage error`. Guard: launch probes with
`env -u PERK_RUN_ID -u PI_SESSION_FILE node probe.ts`. This is the **third victim** of the env-leak
family already documented in `pi/extension-api.md` (`pi --mode json -p` probes and headless probe
scripts that never call `loadPerkSession`; the node-test harness arm was resolved by
`loadPerkSession`'s `applyEnv` baseline — `pi/extension-api.md` § "The inherited `PERK_RUN_ID`
leak") — the guard belongs here because this doc carries the construction recipe probe authors
copy.

The same leak reaches **cold doors driven from an in-session shell**: `perk objective create` run
inside a session stamps that session's `PERK_RUN_ID` as the objective's `objective_run_id`, and the
node-engagement scratch writes then land under the *implement* run's directory. Run interactive door
legs (objective create/refine, plan authoring) from a separate terminal, not from the session's
`bash` tool.

## The runtime-factory path builds the loader internally

`createAgentSessionServices({ cwd, agentDir, …, resourceLoaderOptions })` builds the
`DefaultResourceLoader` **internally** — there is **no** hand-built loader and **no** manual
`loader.reload()` on this path (unlike `createReadOnlySession`). You achieve the asymmetric load
purely by what you pass: `cwd = worktree` (so project `.pi/settings.json` packages, managed
`AGENTS.md`/`APPEND_SYSTEM.md` resolve) + `agentDir = throwaway` (so the user-global tier is locked
out). Do **not** try to hand-build a loader for the runtime factory — that's the read-only path's
shape, not this one.

**SDK sessions load none of Pi's CLI built-in extensions unless the caller supplies them.** Since
Pi 0.99 the CLI loads `codemode`, `tool_search` and MCP as `builtin:<name>` extensions; an
SDK-constructed session loads them only through `extensionFactories` (the package's SDK guide,
`sdk.md`). The worker's current shape (verified 0.99.2 dev pins and the 1.0.0 source):

- `sdkAdapter.ts::workerBuiltinExtensions()` supplies `codemode` (built with
  `models: WORKER_CODEMODE_MODELS` = `false`) then `tool-search`, both with the CLI's exact
  `{ name, factory, replaceable: true, builtin: true }` identity, after the hidden
  `perk-worker-policy` inline extension. **`builtin: true` is load-bearing**: it yields the
  `builtin:<name>` path and `sourceInfo.source === "builtin"` provenance that the posture table and
  `isDiscoveryHost` key on, so the worker joins the discovery cohort (`pi/tool-loadout.md`).
- Both register inactive; configuration alone activates them (`defaultTools` `+tool_search` /
  `+codemode`); a project `extensions: ["-builtin:<name>"]` disables one.
- `/btw` still supplies none. MCP and `llama.cpp` are deliberately absent: Pi's
  `createMcpExtension` defaults its config, credential store and log to the GLOBAL `getAgentDir()`;
  isolating it is deferred, and the "no global MCP access" guarantee holds only because the factory
  is absent, not because anything enforces it.
- **Two diagnostic channels.** A replaced builtin shows only in
  `resourceLoader.getExtensions().warnings` (printed as `perk worker: extension warning —
  builtin:<name>: …`); bind-time `ExtensionError` objects (`{extensionPath, event, error, stack?}`)
  arrive at `bindExtensions({ onError })`, formatted by `formatExtensionError` (the old
  `String(err)` printed `[object Object]`). A project `pi.registerMcpServer()` with no MCP handler
  is a `register_mcp_server` bind error — the observable for "MCP factory absent".
  `ExtensionRunner.getExtensionPaths()` is the live loaded-extension census.
- Codemode's `models` option is observable from its registered description: a "Model API" section
  appears only with `models: true` (at 1.0.0 the description names `models` in a single Globals
  line instead) — assert against a `models: true` control.

**The `applyOverrides` correction (verified 0.99.2, identical at 1.0.0).**
`SettingsManager.applyOverrides` before `createAgentSessionServices` is silently discarded: the
services build a `DefaultResourceLoader` and `await reload()`, which recomputes the merged view from
the tiers — so the §8.11 "compaction-off + retry-off" worker invariant never held, though four
documents described it. The worker now follows the merged Pi settings (the project
`.pi/settings.json` over a throwaway global tier holding only `cacheWarming: "off"`); a repo opts
out via `compaction.enabled` / `retry.enabled`. Assert a knob on the live getters
(`session.autoCompactionEnabled`, `autoRetryEnabled`, `cacheWarmingStatus`), never on the
configuration call — the cross-cutting lesson is `workflow/vacuity-proof-tests.md` § "Assert where
values leave the subsystem".

## A pi SDK pin bump is a session-construction migration audit, not a "verified non-break"

pi 0.84 replaced the `AuthStorage`/`ModelRegistry` session-creation inputs with ONE async
canonical `ModelRuntime`: `createAgentSessionServices({ modelRuntime })`,
`resolveCliModel({ modelRuntime })`, and `ModelRegistry` demoted to a sync extension-facing
compat facade. The worker plane, `workerMain`, the e2e harness, and btw **all** broke on the
bump. Rule: treat a pi SDK pin bump as a migration audit of every `createAgentSession` /
`createAgentSessionServices` call site, never as a "probably compatible" re-verification.

Run the FULL `node:test` suite immediately after the bump commit, and audit faux/custom providers
alongside the `createAgentSession` sites: pi-ai 0.87 hands providers a `TranscriptContext` — tool
declarations ride system-message `toolsAdded`/`toolsRemoved` deltas and `context.tools` is gone, so
a faux provider reads the model-visible census with `getCurrentTools(context.messages)`
(`extension/substrate/stageTools.test.ts`).

### Extension-created child sessions must reuse the LIVE `ModelRuntime`

Since 0.84 `createAgentSession` takes `modelRuntime`, not a registry — `modelRegistry` is no
declared `CreateAgentSessionOptions` member, so it is silently **ignored**; an omitted runtime
silently builds a
default one whose credential state diverges from the live session's — runtime `--api-key`
overrides and extension-registered providers exist **only** on the live runtime. Extensions
receive only the compat facade, so btw recovers the live runtime via a feature-detected
structural probe of the facade's compile-time-private `runtime` field (`liveModelRuntime` in
`extension/vendor/btw/btw.ts`, graceful `undefined` fallback to the default runtime).
**Version-fragile by design** — the facade pin test breaks loudly if pi renames the field, but
only against the pinned SDK; re-verify the probe on every pi bump.

## Seeding a side session goes THROUGH its `SessionManager`

Pi ≥ 0.87 rebuilds `context.messages` from the manager on every `prepareRequest`, so assigning
`agent.state.messages` is silently overwritten (the `/btw` defect). The recipe
(`extension/vendor/btw/btw.ts::seedSessionManager`): read the parent projection with
`sessionManager.buildSessionProjection().messages`, drop `system` and perk's scratch customs, and
persist each role through its canonical append (`appendMessage` / `appendCompaction` /
`branchWithSummary`) into a fresh `SessionManager.inMemory()` handed to `createAgentSession` — no
`refreshContext()`.

## `bindExtensions` is still explicit on the runtime session

`createAgentSessionFromServices` only **loads** extensions (returns `extensionsResult`); **binding**
— which emits `session_start` and runs perk's claim path — happens only when the host calls
`runtime.session.bindExtensions({ uiContext: undefined, mode: "json", onError })`. `mode: "json"` ⇒
`ctx.hasUI === false` (see `pi/extension-api.md` for `ctx.mode`/`ctx.hasUI`). Loading is not binding;
nothing in perk's `session_start` engages until the explicit bind.

## `session.subscribe()` event facts

Verified against the bundled `agent-session.js` at the pinned dist — see `## Sources`.

- The subscribe listener receives the session-level **`AgentSessionEvent`** union — agent-core
  `AgentEvent`s passed through (`agent_end` re-emitted with a `willRetry` flag) plus session-only
  variants (`agent_settled`, `queue_update`, `compaction_start`/`compaction_end`,
  `entry_appended`, …) — **not** the extension `ExtensionEvent` (translated separately). The
  planes share `type` strings, so the names match even though the payload shapes differ.
- `tool_execution_end` carries `result` = the tool's return object; for perk tools `result.details`
  is the `SubmitDetails` / `ResolveDetails` block — so the PR comes straight off the captured event
  (**no** new Python `find-pr-for-branch` command needed).
- **A model error rides `turn_end`** (verified 0.99.2 and 1.0.0): it carries the turn's assistant
  message for error turns too (`stopReason: "error"`, `errorMessage`) — that is the hook for
  `model_error`, not `message_end`. The worker's fold **replaces** the recorded error every turn, so
  an error Pi recovers from (auto-retry → a new turn, or overflow compaction + continue) is cleared
  by the recovery turn; only a last-turn error is terminal; `budget.turns` counts failed attempts.
- **The token census identity**: per-`turn_end` (assistant `input + output` + Σ tool-result
  `input + output` — Pi has already folded every nested call's usage into each
  `toolResults[i].usage` before any listener runs, so never also sum nested `tool_execution_end`)
  + per-`compaction_end` `result.usage` = `getSessionStats().tokens.input + output`. Use Pi's census
  as the **test oracle** only — its persistence runs in an async listener and may lag at
  `finishTurn`. One helper (`freshTokensOf`, `sdkAdapter.ts`) serves the fold and the turn gate.
- **Retry events**: `auto_retry_start { attempt, maxAttempts, delayMs, errorMessage }` and
  `auto_retry_end { success }`.
- **Compaction events**: `compaction_end { reason, result?, aborted, willRetry }` (`result.usage` is
  the summarization usage Pi also persists on the `compaction` entry); `compaction_start` fires only
  when a cut point exists; an aborted or failed compaction has no result and leaves no entry.
- **Pre-request compaction runs inside `prepareRequest`.** An abort from the synchronous
  `compaction_end` listener is refused before provider dispatch, yet the loop still records a
  zero-usage `turn_end` with `stopReason: "error"` ("This operation was aborted"). The run
  classifies `budget_exhausted` only because `classify` checks `terminationReason === "budget"`
  before `evaluateTerminal` — keep that ordering invariant.
- **`cacheWarming` is read from GLOBAL settings only** (`applyOverrides` cannot reach it): the
  worker seeds `{ "cacheWarming": "off" }` into its throwaway agentDir — warming would be the only
  out-of-turn usage source and `session.abort()` does not cancel it. Check via
  `session.cacheWarmingStatus`.

## Single-prompt drive, NOT a `loop.ts` loop (idle ≠ done)

What shipped is a single `await session.prompt(initialPrompt)` — the **SDK owns turn iteration**; the
worker only **observes** (the subscribe listener) plus a turns/tokens/wall-clock **budget watchdog
that hard-aborts**. Do not frame the drive as an iterate-until-terminal loop.

**No settle race after `prompt()` resolves.** `await session.prompt(...)` spans settlement: it
resolves only after `_runAgentPrompt`'s full post-agent-run continuation loop (auto-retry,
compaction retry, `agent_end`-queued follow-ups) AND the `finally`-emitted `agent_settled` — so
`runStage`'s post-`prompt()` classification cannot observe an unsettled run — auto-retry and
compaction continuations included, since the worker now follows the merged retry/compaction
settings. The SDK's `waitForIdle()` is redundant on this path.

**Residual gap (tracked in objective #137 prose):** a *premature idle* — the agent stops before the
success predicate holds — becomes terminal `failed/agent_idle_incomplete` with **no in-drive
re-engagement**. Headless, there is no human to nudge "keep going." Whether to nudge-and-continue vs.
fail-fast-and-resurface to whole-stage retry is an empirical call deferred to 4.1 traces / 3.2 retry.
Future worker/runner work must **not** assume the drive self-recovers from a stall.

## The structured run-event stream

`runStage` emits an **additive** `RunEvent` union (`run_started` / `step_marker` / `tool_outcome`
/ `run_finished`) through an injectable `RunEventSink` (default = a fail-soft NDJSON file at
`runEventsPath`). **Status note:** `step_marker` is since **deprecated/never-emitted** — the
checkpoints marker protocol died with the checkpoints removal; the variant stays in the
grammar for historical `events.ndjson` files (contracts §8.12). `RunOutcome`'s shape was
**unchanged** (`§8.11` frozen); contract `§8.12` added the stream. One `finish()` helper routes **every** terminal exit through exactly one `run_finished`.

- **Two fail-soft tiers when adding an injected seam to a never-throws worker.** The default sink
  wraps each file append in try/catch (logs + swallows), **AND** the emitter independently
  try/catches the `sink(...)` call — so a *throwing injected* sink also can't abort the drive.
  Belt-and-suspenders is deliberate: the injected-seam contract can't assume callers are fail-soft.
  **Guard at the seam boundary, not just inside the default implementation.**
- **The route-don't-relay / double-delivery split generalizes to any emitted stream.** Full ordered
  narrative in the structured channel (the NDJSON file / array sink), bounded model-visible surface
  (per-event `EVENT_SUMMARY_CAP`, reusing `capForModel` from `extension/substrate/modelVisible.ts`). Co-locate the
  durable artifact under the gitignored `scratch/runs/<runId>/` cache tier, and make the file sink a
  **no-op when `run_id` is empty** so existing offline drive tests (which set no `PERK_RUN_ID`) stay
  write-free with **zero** changes. This confirms the project's established idiom for new run-detail
  surfaces — the same discipline as the route-don't-relay material above.
- A small private `toolErrorMessage(event)` helper derives the pre-cap `tool_outcome.summary`
  text in four steps: `details.error` → a bare string result → the result's text blocks (a blocked
  call's reason, a codemode "Script error") → the generic `"tool <name> failed"` fallback.
- **The model-call policy.** The textual screen — `worker/modelCallPolicy.ts::codemodeCallRefusal`
  (a pure decision) registered by `pi/v1/toolCallRefusal.ts::toolCallRefusalHook` (a reusable
  registration seam) — is advisory: an aliased `models` slips past by design. The hard layer is
  `WORKER_CODEMODE_MODELS = false`. A `tool_call` `block` fires before the tool runs whatever the
  factory options, so a test exercising real `models: true` must alias (`const m = models`).
- **Codemode model facts (0.99.2 and 1.0.0):** `models` defaults to `true`; mid-script
  `tool_execution_update` partials carry `cost` but never tokens, so no public interface trips a
  token cap mid-script (retirement trigger: an e2e test fails when Pi starts adding `usage` to
  partials). `session.abort()` kills the sandbox; the model runtime's auth step calls
  `throwIfAborted` first (an already-aborted queued call never reaches the provider); a call
  completing after the script result is dropped and uncounted. A project-registered codemode
  (default `models: true`) or a `ctx.modelRegistry.classify` caller is bounded only by the
  turn-end token cap, the turn cap and the wall clock.

Building the emitter hit a tsc gotcha — `Omit<RunEvent, "seq"|"t">` collapses the discriminated union
— fixed with a distributive `Omit`; see `docs/learned/toolchain/biome.md`.

### The `runStage` outcome boundary (`extension/worker/stageExecution.ts`)

The drive later hardened its outcome boundary; five facts generalize to any never-throws driver
over an external `AbortSignal`:

1. **`AbortSignal` never replays an already-dispatched abort to a late listener** — so "sample
   twice, subscribe once": sample `signal.aborted` at entry (return the `aborted`/`external_abort`
   verdict with zero turns, nothing resolved/constructed/bound) and again **immediately before**
   `prompt()` (an idle session has nothing to abort — no `session.abort()` call), then register the
   listener synchronously with **no intervening `await`** (no check-then-subscribe window). Never
   install the listener during init: an abort that lands mid-init takes effect when init completes,
   in program order, via the pre-prompt sample.
2. **Every await that can reject before a normalized outcome lives inside the try that owns the
   outcome.** Auth resolution, runtime construction and `bind()` moved inside it; `run_started` is
   hoisted to drive entry so one emit site + one `finish()` site guarantee the §8.11/§8.12
   `run_started`/`run_finished` pair **by construction** on every path (pre-aborted, init failure,
   no model, preflight, pre-prompt abort, the drive).
3. **Init failures classify on the bind boundary**: a rejection before the session is bound →
   `runtime_init`; after → `drive_error`. A single shared `EXTERNAL_ABORT_VERDICT` constant keeps
   the three abort routes (entry sample, pre-prompt sample, the drive's abort termination)
   byte-identical.
4. **When abort semantics change, audit tests asserting the OLD side effect**, not just the
   outcome — a pin on `abortCalls >= 1` encoded "we called `session.abort()` on an idle session",
   which the pre-prompt sample deliberately stopped doing.
5. **pi-agent-core's loop does not check `signal.aborted` between turns** (verified 0.99.2 and
   1.0.0) — a watchdog abort on the cap's `turn_end` yields cap + 1 turns and one more provider
   operation, which a `FakeSession` hides. The sanctioned stop is the agent's public `finishTurn`
   hook returning `{ action: "end" }`, which runs BEFORE `turn_end` — so the deciding code computes
   post-turn counters itself (`endRunAfterTurn` adds `turns + 1` plus the turn's fresh tokens via
   the shared `freshTokensOf`). AgentSession installs its own wrapper once and chains; perk wraps
   after it (`createDriveSession`), removes the wrapper on rebind/dispose, and installs only when
   `session.agent` exists. Real-runtime divergence is a defect signal, not a fixture update —
   never loosen a plan-specified pin to match what you observed.

## Never default the model to `getAvailable()[0]` — leave it undefined

`ModelRegistry.getAvailable()` copies the runtime's availability snapshot in **catalog order** —
provider registration order, then each provider's own model order; no sort at the pinned dist —
so `[0]` is an arbitrary catalog position, never a curated default. On the first live remote run
it picked a since-removed dated Haiku and the drive 404'd on turn 1 (defect B7 in
`docs/design/archive/remote-runner-e2e-dogfood.md`, against an earlier dist that sorted
alphabetically and so surfaced the *oldest* model — dated history, not the live mechanism; the
workflow-level story is in `docs/learned/workflow/remote-runner.md`).

The correct shape: pass `model: undefined` to `createAgentSessionFromServices`/`createAgentSession`.
That engages the SDK's **own initial-model resolution** (`findInitialModel`) — the saved settings
`defaultProvider`/`defaultModel` (only when that provider `hasConfiguredAuth`) → pi's curated
per-provider defaults → first available — which picks a current-generation model. Mechanism fact:
the package root exports the CLI/scope resolvers (`resolveCliModel`,
`resolveModelScopeWithDiagnostics`) but NOT `findInitialModel` / `defaultModelPerProvider`
(deep-only in `dist/core/model-resolver.d.ts`), so deferring via an undefined `model` option
remains the only sanctioned route to the initial-model chain. The explicit `--model` flag now
resolves through `resolveCliModel` (fuzzy matching, `provider/pattern`, `:thinking` — parity with
interactive launch; `resolveWorkerModel` in `extension/worker/sdkAdapter.ts`); keep the
zero-available-models fail-fast unchanged — only the *default* defers to the SDK.
Because the chain ends in a first-available fallback, a one-model fixture cannot tell "honoured
the saved default" from "fell back" — pin a saved default with a NON-first model beside a
no-default control (`sdkAdapter.test.ts`, the native-provider saved-credential section).

Landed shape: `extension/worker/sdkAdapter.ts` — a nominal, unresolved `WorkerModelRequest` (the
raw `--model` pattern + an optional test-injected runtime) resolved by `selectWorkerModel` inside
the runtime factory; the deferred pick still passes `model: undefined`. An unknown `--model` is a
zero-turn `RunOutcome` (exit 1), not a pre-`run_started` exit 2, and `ModelRuntime.create()` runs
inside the outcome boundary (a rejection is `runtime_init`). Because the SDK may have picked the
model, the worker logs `perk worker: model <provider>/<id>` **post-creation** — read the pick off
`session.model`, don't recompute it.

### Native-provider availability at initial model selection

Since Pi 0.99.2 `ModelRuntime.registerNativeProvider` marks the provider configured
**synchronously** (`markProvisionallyConfigured`) when the runtime's snapshot already lists a
stored credential for it (`storedProviders`, rebuilt from the credential store by the async
`refresh()`) or its config carries a configured key — so a `getAvailableSnapshot()` /
`hasConfiguredAuth()` read right after registration (what initial model selection does) sees
its models. Earlier dists set no provisional entry: the provider became available only after
the registration's own fire-and-forget `refresh({ allowNetwork: false })` settled, so initial
selection could read an unconfigured snapshot and fall back or warn. A provider with neither a
stored credential nor a configured key still becomes available only through that async
refresh (the path `fauxModelRuntime` relies on). Pinned in `sdkAdapter.test.ts` against a real
`ModelRuntime`, with a credential-less control.

**The selection ladder** (Pi's own CLI order, `main.ts`; verified 0.99.2 and 1.0.0):
`createAgentSessionServices` (project extensions load; queued `registerProvider` config/native and
`registerVirtualModel` registrations apply to the worker-minted `ModelRuntime`; refresh) → print
non-`info` `services.diagnostics` + `services.resourceLoader.getExtensions().errors` (moved BEFORE
selection so a refusal's cause — an extension that failed to load registers nothing — is visible)
→ `selectWorkerModel` (explicit resolution miss → `model_not_found`; deferred + empty snapshot →
`no_model`; an explicit model failing `hasConfiguredAuth || await checkAuth !== undefined` →
`model_auth`) → `createAgentSessionFromServices` (`model: undefined` on the deferred path = Pi's
`findInitialModel`) → bind. The e2e order pin is `stageExecutionE2e.test.ts` "no_model is decided
AFTER extension registration".

- **Typed early-out from an SDK-owned factory**: a `CreateAgentSessionRuntimeFactory` must resolve
  to a session or reject (there is no "typed no"), so the refusal throws a private sentinel
  (`WorkerModelRefusal`), `defaultCreateRuntime` `instanceof`-converts it at the boundary it owns
  (`RuntimeConstruction { ok: false, refusal }`), and rethrows everything else.
- **Explicit vs default.** Only an explicit `--model` is admission-checked. A converged default
  whose provider lacks auth is silently skipped by `findInitialModel` — the worker drives a
  different model and only the post-creation log line tells. Prose about "refusal" must say which.
- **Residuals:** a virtual model whose physical target lacks credentials is admitted and fails at
  the first request as `drive_error`; `model_not_found`/`model_auth` under `model_error` have no
  Python consumer enumerating them yet; a refusal on a session replacement (`/new`, `/resume`,
  fork) surfaces as the SDK's own replacement error.

## One real prompt turn is load-bearing when observing `hasUI`-keyed tool reconciliation

Tools stripped via `setActiveTools` on `before_agent_start` (e.g. `ask_user_question`'s headless
reconcile) still appear in a bind-only registered census — `getAllRegisteredTools()` is the wrong
surface for "what the model sees". Drive one `session.prompt(...)` turn and read the model-visible
tool set instead.

## Offline-test determinism for model availability

A "no model available" test must **inject a stub runtime** — NOT delete `ANTHROPIC_API_KEY`/etc.:
a default-constructed runtime also reads the dev machine's credential store, so env-var deletion
is **not** deterministic, and real runtimes are unusable for `no_model` (builtin providers resolve
ambient env keys). Since selection moved after the services, an empty-snapshot stub no longer
suffices: `no_model` pins need a **recording stub** over the whole registration surface
(`registerProvider`/`registerNativeProvider`/`registerVirtualModel`/`refresh`/`getModels`/
`getRegisteredProviderIds`/`hasConfiguredAuth`/`checkAuth`, logged with snapshot reads into one
ordered list — `recordingStubRuntime` in `stageExecutionE2e.test.ts`), typed `as never` so a new
runtime method breaks the pin loudly (part of the pin-bump audit).

- **Credential-gated fixture provider**: Pi's `fauxProvider` is always configured, so pair a
  `createProvider` whose `apiKey.resolve` returns auth only for a stored `api_key` with
  `bareModelRuntime({ credentials })` (`extension/testing/harness.ts`).
- **Plant a real extension to e2e-test registration**: a project-tier `.ts` extension on disk
  (`plantWorkerProviderExtension`) resolves `@earendil-works/pi-ai` through the loader alias map to
  pi-coding-agent's own copy, so its native provider streams on the worker's runtime.
- Faux models need `reasoning: true` for a `:thinking` suffix to survive (Pi clamps the level for
  non-reasoning models); `resolveCliModel`'s message ends with a period (normalize before
  composing); virtual-model identity is observable — `session.model` reports `router/auto`, the
  branch's assistant entry records the physical target.

The asymmetric-load verification (throwaway `agentDir` still loads + binds the project `@mgiles/perk`
extension, `session_start` claim engages) is provable **fully offline** via the existing
`loadPerkSession` harness — assert `getAllRegisteredTools()` includes `submit` /
`finalize_address` and that the rebuilt `workflow-state.run_id` matches the planted handoff.

## Driving the real runtime offline with a faux model (the e2e worker tier)

The e2e worker tier (`extension/worker/stageExecutionE2e.test.ts` + `extension/testing/harness.ts`) drives a full
stage through the production `defaultCreateRuntime` against the real `@mgiles/perk` extension and a
faux pi-ai model, GitHub-free at the `PERK_BIN` seam. Three load-bearing assumptions were wrong;
the corrections are the durable knowledge.

- **pi 0.84: compat `registerFauxProvider` (the global api-registry) no longer reaches a real
  `AgentSession`** — sessions stream through `ModelRuntime.prepareRequest` → the provider's own
  stream closures, not a compat api-registry lookup. The working recipe is a **hermetic per-run
  runtime**: `ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
  refreshOnCreate: false })` + `registerNativeProvider(fauxProvider().provider)` — realized in
  `extension/testing/harness.ts` (`fauxModelRuntime`). Because the runtime is per-run and
  self-contained, there is nothing global to register or restore — the pre-0.84
  "seed `AuthStorage.inMemory` with a dummy key + unregister the faux provider in `finally`"
  teardown is gone with `AuthStorage` itself (the runtime's in-memory credential store satisfies
  the credential resolution a real runtime still performs even for a faux provider).
- **pi-coding-agent bundles its own nested `@earendil-works/pi-ai`** — pi-ai module state is
  **per instance**, so the faux core must still be built from pi-ai *as pi-coding-agent sees it*:
  `import.meta.resolve` the package, probe its nested `node_modules` for pi-ai, and
  dynamic-`import()` that path (CJS `require.resolve` throws `ERR_PACKAGE_PATH_NOT_EXPORTED` —
  pi-ai exposes only the `import` export condition), falling back to the top-level when deduped.
  Faux message builders are instance-agnostic plain objects; only the provider + the `getModel()`
  it returns must come from the runtime's instance. **Generalize:** ANY module-global SDK state
  is per-instance — resolve singletons through pi-coding-agent when driving the real
  `AgentSession`.
- **pi-ai ≥ 0.80 moved the global API off the root onto the `/compat` entrypoint** — value
  imports (`getModel`, …) must come from `@earendil-works/pi-ai/compat` (types stay on the
  root): pi's extension loader aliases the pi-ai root → the compat entry at runtime, but tsc and
  plain `node --test` resolve the real root. The compat export is still guarded
  (`extension/piAiCompatGuard.test.ts` — unpinned settings-delivered packages import it); only
  the compat api-registry's *registration* role for session driving died at 0.84 (see the
  hermetic-runtime bullet above).
- **`SettingsManager.inMemory` is NOT layered over disk** — a runtime built on it never resolves
  the project `.pi/settings.json` `packages`, so a worktree-cwd launch registers **zero** extension
  tools. Production `defaultCreateRuntime` now layers disk settings
  (`SettingsManager.create(worktree, throwawayAgentDir)`), and the e2e
  tier drives that disk path directly: the scaffold's `.pi/settings.json` local-path package IS the
  load path (offline — no npm), `PI_OFFLINE=1` belt-and-suspenders. The
  tier no longer injects perk through `resourceLoaderOptions.extensionFactories` (that was the
  in-memory-settings workaround); production passes the hidden `perk-worker-policy` inline
  extension plus the two builtins through it. (The production-side story lives in
  `docs/learned/workflow/remote-runner.md`.)
  - **Generalize before scoping extension delivery for ANY headless/worker session: audit the
    stage prompts it will drive for capabilities sourced from borrowed packages.** Loading only
    perk (`extensionFactories: [perk]`-style scoping) is the trap — e.g. the address stage's
    seeded prompt (`prompts/stages/address/action.md`) instructs ONE `classify_review_feedback`
    call, a perk tool whose wave rides `pi-subagents`' v1 extension RPC responder — which only
    comes up when the full settings-resolved package set loads (the tool soft-fails
    `unavailable` without it; before the wave migration the same seed named the borrowed
    `subagent` tool directly and the failure was **silent**: the model idled without its tools
    and burned the whole budget — which is why the worker's post-bind terminating-tool preflight
    (`extension/worker/stageExecution.ts`) fails fast instead).
- **Injected `eventSink` and the default NDJSON file sink are mutually exclusive per drive** — to
  assert both the in-process stream and the on-disk NDJSON, drive the scenario twice.
- **A faux script that must answer Pi's compaction requests keys on the summarization system
  prompt, not the transcript framing.** The history summary wraps the transcript in
  `<conversation>`; since 0.99 the split-turn-prefix summary uses a `# Conversation` heading, so
  a `<conversation>`-keyed router miscounts the turn-prefix request as a model turn. Both share
  `SUMMARIZATION_SYSTEM_PROMPT` (`dist/core/compaction/utils.js`), which the faux provider sees
  as a `system` message (`extension/pi/v1/childTaskRestore.test.ts`).

**Reusable helpers and recipes** (`extension/worker/stageExecutionE2e.test.ts`; verified at the
0.99.2 pins, re-run status on 1.0.0 per `docs/design/archive/pi-1.0.0-certification.md`):

- `runDrive({ contextWindow })` — sets a per-drive `PI_CODING_AGENT_DIR` (a temp worktree does not
  isolate `getAgentDir()`) through its env save/restore and returns it as `globalAgentDir`;
  `observeSessionEvents`; `summarizationRouter` (keyed on the summarization system prompt; counts
  summaries, lane requests and unexpected requests); `compactionEntries` / `compactionUsageSum`;
  `firstAssistantUsage`; `assertWorkerKnobs` (the live getters).
- **Reading live state inside a scripted reply**: `runStage` disposes the runtime before `runDrive`
  returns, so use `observeLive().at(reply)` plus the `liveSession` option (declared tools,
  provenance, `getExtensionPaths()` per request); the cast stays test-side.
- **The compactable recipe**: `contextWindow: 120_000`, a ≈9,500-line prompt,
  `reserveTokens: 60_000`, `keepRecentTokens: 0`; measured turn 1 ≈43.8k fresh tokens, compaction
  ≈31.6k. A cap pinned between the two (60,000) is checked post-hoc against live usage every run,
  so fixture drift fails loudly — the measured-constant pin pattern.
- **Scripted errors retry.** `"overloaded"`/`429`/`5xx`/`rate limit` are retryable under pi-ai's
  root-exported `isRetryableAssistantError`: assert it as a vacuity guard, set
  `retry: { baseDelayMs: 1 }` via `extraSettings`, and always assert `providerCalls` (a single-reply
  script otherwise drains into the faux "No more faux responses queued").
- **Count turns and requests around terminators.** `submit` ends the run through the `finishTurn`
  gate, so scripted replies after it are never requested.
- **Faux usage vs compaction.** Faux usage counts the prompt as input and again as cacheWrite (≈2×
  Pi's `estimateProjectedContextTokens`) — place the threshold between the two so compaction runs
  post-run (`_handlePostAgentRun` → `_checkCompaction`), and keep usage below `contextWindow` to
  avoid the overflow path. With `keepRecentTokens: 0` a custom message after the user task is a turn
  start → two summarization requests, so route by shape, never a fixed script.
- **Steer delivery**: idle → `sendMessage({deliverAs: "steer"})` appends immediately; mid-run
  (including the post-run compaction check, where `isStreaming` stays true) → `agent.steer`; a
  compaction finishing with a queued steer → `agent.continue()`.
- **A planted project `codemode` silently replaces the worker's builtin** — tell them apart by
  `sourceInfo.path` (`builtin:codemode` vs the planted file); to test the hard layer, plant only
  the faux direct tool. For census-absence assertions first assert the census works (e.g.
  `perk-worker-policy` listed); capture stderr with `t.mock.method(console, "error")`.
- **Slow tier.** These scenarios run in `just test-js-slow` / `node --test
  extension/worker/stageExecutionE2e.test.ts`; `run_ci` does not run them.
- **SDK-worker harness without `runStage`**: reuse `defaultCreateRuntime`, then
  `createDriveSession(...).bind()` — construction fires no `session_start`; bind does.
- **Residual risks**: a post-dispose turn after a failed lane (stale-ctx errors on
  `context`/`agent_settled`; whether it sends a provider request is unmeasured); CLI print-mode
  non-exit depends on the pre-spawn failure kind (model resolution exits; a worktree-admission
  refusal loops — a perk-absent control settled it); a per-item unknown model fails a lane with no
  child directory — prove a runner started from `status.json`/logs, never from a directory
  existing.

Process notes that held up: `git init -q` the temp worktree so the resource loader's ancestor
skills-walk stops there; save/restore every mutated `process.env` key in `finally` (the hermetic
per-run runtime needs no unregistration); real `tool_execution_end` events DO carry
`result.details` — a "generic tool failed" symptom is usually the missing-extension path, not a
shape mismatch.

## Headless probe and dogfood-session craft

- `session.prompt("/command")` resolves when the command **settles** — but a follow-up-turn loop
  that disposes the session as soon as the promise resolves can still clip the command's
  terminating tool. Bound a wait for the terminating `tool_execution_end` event before disposing.
- A clone-local `.perk/local.toml` `[workflow] base` overlay pins a sacrificial plan's base onto
  a stacked train's tip **without committed config** — the cheap way to aim a dogfood drive at a
  train head.
- A headless `pi --mode json -p "<prompt>"` session is the cheap **capturable** proof that a
  registered-tool path works, streamed partials included — the JSON event stream is greppable
  evidence. Remember: Pi retains the registration graph loaded at session start, so a probe
  launched before a binding change cannot observe that change (a fresh session is required).
- Pi refuses to compact a small session (`Nothing to compact (session too small)`; the default
  `keepRecentTokens` — `DEFAULT_COMPACTION_SETTINGS` in `dist/core/compaction/compaction.js` —
  was 20,000 at the last audit) — inflate the session past that floor before a compaction smoke.
- RPC mode exposes no navigate command (a read-only `get_tree` exists; nothing moves the leaf) —
  `navigateTree` / `/tree` reach only extension command contexts — so branch/checkpoint evidence
  must come from tests over the real `branch` / `branchWithSummary` APIs, not a driven RPC session.
- Headless print/RPC output does not expose the post-`context`-filter LLM input; strip/keep
  behavior stays pinned by the consumer suites, not by a driven probe.
- The Python seam for the env-unset rule: `src/perk/substrate/proc.py`'s `env_remove` deletes
  inherited names *before* the overlay is applied — removal is not expressible as an overlay merge,
  so a launcher that must drop `PERK_RUN_ID`/`PI_SESSION_FILE` names them there.
- **Print mode sends an unknown slash command to the model as a prompt**, so a "not loaded"
  negative probe must assert an absent output line under a short cap.
- **Live-testing an authoring-only wave tool from an implement worktree**: bare
  `pi --approve --mode json -p "…"` in the worktree with a scrubbed env, `PERK_SKIP_VERSION_CHECK=1`,
  a throwaway `PI_CODING_AGENT_DIR`, and `PI_SUBAGENTS_TEMP_ROOT` outside the worktree. `/plan` only
  toggles the mode, and `perk plan` from a linked worktree positions in main.

## Replaying a recorded session's compaction headlessly

To re-run a failing session's compaction with different settings, fork instead of touching the live
file: `SessionManager.forkFrom(sourcePath, cwd)` (the live file is never written) →
`session.navigateTree(leafId, { summarize: false })` → `session.compact()` — the same
`AgentSession.compact` path the TUI `/compact` and `ctx.compact()` enter (identical `usage.input`
across replays proved byte-faithfulness). Dry-run the preparation before spending:
`prepareCompaction(sessionManager.getBranch(), settingsManager.getCompactionSettings())` is not
exported from the package root — deep-import `dist/core/compaction/compaction.js` — and assert
the first-kept entry id / `isSplitTurn` / `tokensBefore` match the original compaction entry, logging the
effective `reserveTokens`, before the first (paid) model call.

Run against the install the failing session actually ran, by absolute path (a worktree's
`node_modules` copy can lag the pin). `PI_CODING_AGENT_DIR=<main checkout>/.pi/agent` mirrors perk's
`[pi] agent_dir` injection so auth, `models.json`, and the session dir match;
`SettingsManager.create(cwd, agentDir)` with the checkout as `cwd` proves the project-tier
`.pi/settings.json` value is what the session sees. Bare `createAgentSession` + a hand-built
`DefaultResourceLoader` with the `no*` flags + a manual `reload()` is the isolation shape (the
read-only half of the recipe above); pin `model` via `resolveCliModel` and `thinkingLevel`
explicitly; launch with `env -u PERK_RUN_ID -u PI_SESSION_FILE`. Repeated replays can branch off the
same leaf in one fork (each compaction entry gets `parentId` = the leaf), so filtering the fork for
`compaction` entries reads every reading at once.

## `sendUserMessage` persists ONE newline-joined text block

`AgentSession.sendUserMessage(content[])` joins every text block with `"\n"` into a single string
on both the idle path and the streaming follow-up path. Any digest/evidence scheme that hashes the
*sent* block array can therefore never match its persisted evidence: construct the canonical single
block *before* recording the expectation and send it unchanged; never normalize inside the digest.

The real-transport regression recipe (`extension/pi/v1/draftReview.test.ts` — the
`injectDraftReviewResult` idle→plain / busy→followUp / joined-with-`\n` case — is the guard against
a future join change; there is no separate version-aware guard):

- Observe the send with a **forwarding wrapper** assigned as an own property on the session
  instance (the runner's bound action calls `this.sendUserMessage(...)` dynamically): read retained
  state before forwarding, forward the original args, retain the promise (idle → resolves at run
  settlement; followUp → at queue acceptance).
- Create genuine streaming with a one-shot `context`-event barrier (resolve a `streaming`
  deferred, await a `release` deferred once) so `session.isStreaming` is truthfully true and
  `deliverAs: "followUp"` lands in the follow-up queue — no sleeps, no forged idle flag.
- Prepare/register the review while idle, not mid-run: `ctx.signal` is the active run's abort
  controller, so a review prepared mid-run is interrupted at run end into
  `uncertain/delivery-unconfirmed`.
- The faux provider is microtask-paced when `tokensPerSecond` is unset, so assert the pre-forward
  snapshot and take live-state checkpoints only at deterministic points (the `tool_call` handler;
  after settlement).
- Surface-test fakes must mirror Pi: a hand-built branch fake's `persist()` joins text blocks with
  `"\n"` — correcting the fake exposed latent mismatches.

## `DefaultResourceLoaderOptions` is not exported from the package root

Derive the `resourceLoaderOptions` type via indexed access:
`CreateAgentSessionServicesOptions["resourceLoaderOptions"]`. (Tie to the `pi/extension-api.md` rule:
check the root export list before importing a Pi type by name; mirror/derive deep-only types locally.)

## Sources

- `@earendil-works/pi-coding-agent` dist —
  `dist/core/{agent-session,agent-session-services,sdk}.{js,d.ts}`,
  `dist/core/{model-registry,model-runtime,model-resolver,settings-manager,session-manager,resource-loader}.js`,
  `dist/core/model-resolver.d.ts`, the package's SDK guide (`sdk.md`),
  `dist/core/compaction/compaction.js`, `dist/modes/rpc/*`, and the nested `@earendil-works/pi-ai`
  (`package.json` `exports`, `dist/compat.d.ts`) — at the version `package.json` `devDependencies`
  pins. The `@earendil-works/*` devDependency pins move in lockstep (the set
  `tests/test_packaging.py::test_pi_toolchain_pin_lockstep` enforces), so the pin is the single version
  truth for every dist-scoped fact here; body version numbers ("pi 0.84 replaced …") are event
  stamps, never currency claims.
- **Re-verify at each pin bump — a bump is a session-construction migration audit** (its own
  section above): re-read every `createAgentSession` / `createAgentSessionServices` call site AND
  every dist-scoped fact here against the newly *installed* dist (resolved per
  `toolchain/worktree-node-modules.md`), correct or date what changed. Last full re-verification:
  the `0.99.2` dist — every call site above (`sdkAdapter.ts`, `harness.ts`, `btw.ts`,
  `contextEvidence.ts`) needed no migration; newly recorded: `registerNativeProvider`'s
  synchronous stored-credential configuration, SDK sessions loading no CLI built-ins,
  `findInitialModel`'s auth-gated saved default and first-available fallback, the worker's
  then-`resolveAuth`-before-extension-load order (since replaced by the selection ladder), and the
  turn-prefix summary's `# Conversation` framing; re-confirmed: the `createAgentSession` initial-state read from `buildSessionContext()`,
  the request-time `_installAgentRequestProjection` rebuild, `ModelRegistry.streamSimple` and its
  private `runtime` field, and the provider-facing `TranscriptContext` (`getCurrentTools`). The
  prior full pass was the `0.87.0` dist — provenance, not a currency promise; the pin is.
- **2026-10 restamp:** the facts added since were verified at `0.99.2` and re-checked at `1.0.0`
  where their sections say so — the worker builtins, compaction/retry and the `applyOverrides`
  correction, the `finishTurn` gate, the selection ladder.
- **Pin-bump audit list additions:** `finishTurn` still runs before next-turn prep and AgentSession
  still chains a pre-existing hook; the `recordingStubRuntime` registration surface;
  `satisfies`-exhaustive registries over Pi types (`tools/prose-map/selector.ts::TOOL_FIELD_POLICIES`);
  faux routers keyed on prompt/transcript text (the summarization router). Note that the
  `childTaskRestore` tests run in the *fast* tier.

## Cross-references

- `extension/worker/stageExecution.ts` — `runStage` (the public drive seam), stage policy, the
  budget watchdog
- `extension/worker/sdkAdapter.ts` — the private SDK adapter: runtime-factory construction +
  session creation
- `extension/workerMain.ts` — the worker entrypoint
- `extension/worker/modelCallPolicy.ts` + `extension/pi/v1/toolCallRefusal.ts` — the model-call
  policy (pure decision + registration seam)
- `docs/learned/pi/tool-loadout.md` — the discovery cohort the worker joins, builtin provenance
- `docs/learned/workflow/vacuity-proof-tests.md` § "Assert where values leave the subsystem" — the
  configured-but-never-observed lesson behind the `applyOverrides` correction
- `extension/worker/stageExecutionE2e.test.ts` + `extension/testing/harness.ts` — the faux-model e2e tier
- `docs/learned/pi/extension-api.md` — `ctx.mode`/`ctx.hasUI`, the root-export-list rule
- `docs/learned/pi/context-system.md` — context loading; `pi/read-only-bash-gate.md` — the read-only bash allowlist
- `docs/learned/toolchain/biome.md` — the TS-stripping / Biome gotchas + the distributive-`Omit` gotcha hit building the emitter
- `docs/learned/toolchain/worktree-node-modules.md` — worktree SDK resolution + the stale-global smoke trap
- `docs/design/archive/pi-adoption-audit.md` — the complete 0.80.5-verified adoption inventory + follow-up
  groupings; future pi-adoption planners should seed from its §4 table rather than re-auditing
- `docs/design/archive/borrowed-askuser-todo-dogfood.md` — the validation record that live-proved the
  zero-config borrowed-built-in reality (and the probe recipe with the env-leak guard applied)
