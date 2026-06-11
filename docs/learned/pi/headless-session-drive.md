---
title: Headless Pi session construction & driving — the SDK runtime-factory recipe
read_when: You are constructing or driving a headless (non-TUI) Pi session via the SDK — the runtime-factory path, bindExtensions, session.subscribe event facts, a single-prompt drive + budget watchdog, offline determinism for model-availability, or driving the real runtime with a faux model (the nested-pi-ai per-instance registry trap).
---

# Headless Pi session construction & driving

The Node 1.2 worker (`extension/worker.ts`, `driveStage`) constructs a headless, read-WRITE Pi
session at the SDK level and drives a single stage to completion with no human in the loop. This doc
captures the non-obvious shape of that construction — distilled so the next SDK-drive surface starts
from the right path instead of rediscovering it.

> **One Code Rule.** Everything below names files and describes behavior. It deliberately does **not**
> paste constructor bodies — read the source at the pointers.

## Two construction paths — pick by isolation axis

There are two SDK-level construction recipes already in the tree, and they differ on **one axis**:
read-only vs. read-write isolation.

- `extension/readOnlySession.ts` (`createReadOnlySession`) is a fully-isolated **read-only** child:
  bare `createAgentSession` + a **hand-built `DefaultResourceLoader`** with `no*` flags and the
  stricter `["read","grep","find","ls"]` allowlist (`SDK_READ_ONLY_TOOLS`), and it calls
  `loader.reload()` manually.
- `extension/worker.ts` (`driveStage`) is the **read-WRITE inverse**: read-write defaults + the
  **real perk extension** loaded from the worktree's `.pi/settings.json` via cwd-discovery, with the
  user-global tier locked out by a **throwaway `agentDir`** (`mkdtemp` under `tmpdir()`).

When building the next SDK-drive surface, start from whichever is closer and **flip only the
isolation axis** — don't reinvent both.

## The runtime-factory path builds the loader internally

`createAgentSessionServices({ cwd, agentDir, …, resourceLoaderOptions })` builds the
`DefaultResourceLoader` **internally** — there is **no** hand-built loader and **no** manual
`loader.reload()` on this path (unlike `createReadOnlySession`). You achieve the asymmetric load
purely by what you pass: `cwd = worktree` (so project `.pi/settings.json` packages, managed
`AGENTS.md`/`APPEND_SYSTEM.md` resolve) + `agentDir = throwaway` (so the user-global tier is locked
out). Do **not** try to hand-build a loader for the runtime factory — that's the read-only path's
shape, not this one.

## `bindExtensions` is still explicit on the runtime session

`createAgentSessionFromServices` only **loads** extensions (returns `extensionsResult`); **binding**
— which emits `session_start` and runs perk's claim path — happens only when the host calls
`runtime.session.bindExtensions({ uiContext: undefined, mode: "json", onError })`. `mode: "json"` ⇒
`ctx.hasUI === false` (see `pi/extension-api.md` for `ctx.mode`/`ctx.hasUI`). Loading is not binding;
nothing in perk's `session_start` engages until the explicit bind.

## `session.subscribe()` event facts

Verified against the bundled `agent-session.js` (0.78.x) — see `## Sources`.

- The subscribe listener receives the **raw agent-core `AgentEvent`**, not the extension
  `ExtensionEvent` (the session translates agent→extension events separately). Both planes share the
  same `type` strings, so the names match even though the payload shapes differ.
- `tool_execution_end` carries `result` = the tool's return object; for perk tools `result.details`
  is the `SubmitDetails` / `ResolveDetails` block — so the PR comes straight off the captured event
  (**no** new Python `find-pr-for-branch` command needed).
- A **post-acceptance model error** (retry off) surfaces as a `message_end` whose assistant message
  has `stopReason === "error"` + `errorMessage` — that is the hook to detect `model_error`, **not** a
  dedicated error event.
- Token counting reuses the `sumAssistantTokens` pattern: sum `max(0,input) + max(0,output)` over
  assistant `turn_end` messages.

## Single-prompt drive, NOT a `loop.ts` loop (idle ≠ done)

What shipped is a single `await session.prompt(initialPrompt)` — the **SDK owns turn iteration**; the
worker only **observes** (the subscribe listener) plus a turns/tokens/wall-clock **budget watchdog
that hard-aborts**. Do not frame the drive as an iterate-until-terminal loop.

**Residual gap (tracked in objective #137 prose):** a *premature idle* — the agent stops before the
success predicate holds — becomes terminal `failed/agent_idle_incomplete` with **no in-drive
re-engagement**. Headless, there is no human to nudge "keep going." Whether to nudge-and-continue vs.
fail-fast-and-resurface to whole-stage retry is an empirical call deferred to 4.1 traces / 3.2 retry.
Future worker/runner work must **not** assume the drive self-recovers from a stall.

## The structured run-event stream

`driveStage` emits an **additive** `RunEvent` union (`run_started` / `step_marker` / `tool_outcome`
/ `run_finished`) through an injectable `RunEventSink` (default = a fail-soft NDJSON file at
`runEventsPath`). `RunOutcome`'s shape was **unchanged** (`§8.11` frozen); contract `§8.12` added the
stream. One `finish()` helper routes **every** terminal exit through exactly one `run_finished`.

- **Two fail-soft tiers when adding an injected seam to a never-throws worker.** The default sink
  wraps each file append in try/catch (logs + swallows), **AND** the emitter independently
  try/catches the `sink(...)` call — so a *throwing injected* sink also can't abort the drive.
  Belt-and-suspenders is deliberate: the injected-seam contract can't assume callers are fail-soft.
  **Guard at the seam boundary, not just inside the default implementation.**
- **The route-don't-relay / double-delivery split generalizes to any emitted stream.** Full ordered
  narrative in the structured channel (the NDJSON file / array sink), bounded model-visible surface
  (per-event `EVENT_SUMMARY_CAP`, reusing `readOnlySession.ts`'s `capForModel`). Co-locate the
  durable artifact under the gitignored `scratch/runs/<runId>/` cache tier, and make the file sink a
  **no-op when `run_id` is empty** so existing offline drive tests (which set no `PERK_RUN_ID`) stay
  write-free with **zero** changes. This confirms the project's established idiom for new run-detail
  surfaces — the same discipline as the route-don't-relay material above.
- A small `toolErrorMessage(event)` helper (`details.error` string → raw `result` string → generic
  `"tool <name> failed"` fallback) derives the pre-cap `tool_outcome.summary` text; no contract
  impact.

Building the emitter hit a tsc gotcha — `Omit<RunEvent, "seq"|"t">` collapses the discriminated union
— fixed with a distributive `Omit`; see `docs/learned/toolchain/biome.md`.

## Offline-test determinism for model availability

A "no model available" test must **inject an empty `{ getAvailable: () => [] }` registry + auth
stubs** — NOT delete `ANTHROPIC_API_KEY`/etc. `ModelRegistry.getAvailable()` also reads the dev
machine's `auth.json`, so env-var deletion is **not** deterministic.

The asymmetric-load verification (throwaway `agentDir` still loads + binds the project `@perk/pi`
extension, `session_start` claim engages) is provable **fully offline** via the existing
`loadPerkSession` harness — assert `getAllRegisteredTools()` includes `submit` /
`resolve_review_threads` and that the rebuilt `workflow-state.run_id` matches the planted handoff.

## Driving the real runtime offline with a faux model (the e2e worker tier)

The e2e worker tier (`extension/workerE2e.test.ts` + `extension/testing/harness.ts`) drives a full
stage through the production `defaultCreateRuntime` against the real `@perk/pi` extension and a
faux pi-ai model, GitHub-free at the `PERK_BIN` seam. Three load-bearing assumptions were wrong;
the corrections are the durable knowledge.

- **pi-coding-agent bundles its own nested `@earendil-works/pi-ai`** — the api-provider registry is
  module-global **per instance**, so a faux provider registered via the top-level import is
  invisible to the session runtime (which streams through the nested instance). Fix pattern (the
  harness's faux-model registration): resolve pi-ai *as pi-coding-agent sees it* —
  `import.meta.resolve` the package, probe its nested `node_modules` for pi-ai, and
  dynamic-`import()` that path (CJS `require.resolve` throws `ERR_PACKAGE_PATH_NOT_EXPORTED` —
  pi-ai exposes only the `import` export condition), falling back to the top-level when deduped.
  Faux message builders are instance-agnostic plain objects; only provider registration + the
  `getModel()` it returns must come from the runtime's instance. **Generalize:** ANY module-global
  SDK registry is per-instance — resolve singletons through pi-coding-agent when driving the real
  `AgentSession`.
- **`defaultCreateRuntime` cannot discover extensions from on-disk `.pi/settings.json`** — it
  builds settings with `SettingsManager.inMemory`, which is NOT layered over disk, so project
  `packages` are empty and a worktree-cwd launch registers **zero** extension tools. Deliver
  extensions via the documented `resourceLoaderOptions.extensionFactories` seam while still driving
  the real factory. (The production-side implication lives in
  `docs/learned/workflow/remote-runner.md`.)
- **The real runtime resolves an API key even for a faux provider** — seed `AuthStorage.inMemory`
  with a dummy key for the faux provider id (the structured-output path sidesteps this; the full
  runtime does not).
- **Injected `eventSink` and the default NDJSON file sink are mutually exclusive per drive** — to
  assert both the in-process stream and the on-disk NDJSON, drive the scenario twice.

Process notes that held up: `git init -q` the temp worktree so the resource loader's ancestor
skills-walk stops there; save/restore every mutated `process.env` key and unregister the faux
provider in `finally`; real `tool_execution_end` events DO carry `result.details` — a "generic
tool failed" symptom is usually the missing-extension path, not a shape mismatch.

## `DefaultResourceLoaderOptions` is not exported from the package root

Derive the `resourceLoaderOptions` type via indexed access:
`CreateAgentSessionServicesOptions["resourceLoaderOptions"]`. (Tie to the `pi/extension-api.md` rule:
check the root export list before importing a Pi type by name; mirror/derive deep-only types locally.)

## Sources

- The `session.subscribe()` event facts above were verified by reading the bundled
  `agent-session.js` (Pi SDK 0.78.x) — the raw-`AgentEvent` translation, `tool_execution_end.result`,
  and the `message_end` `stopReason === "error"` hook are dist-confirmed, not inferred.

## Cross-references

- `extension/worker.ts` — `driveStage`, the runtime-factory construction + budget watchdog
- `extension/workerMain.ts` — the worker entrypoint
- `extension/readOnlySession.ts` — the fully-isolated read-only child this inverts
- `extension/workerE2e.test.ts` + `extension/testing/harness.ts` — the faux-model e2e tier
- `docs/learned/pi/extension-api.md` — `ctx.mode`/`ctx.hasUI`, the root-export-list rule
- `docs/learned/pi/context-system.md` — the read-only child it inverts
- `docs/learned/toolchain/biome.md` — the TS-stripping / Biome gotchas + the distributive-`Omit` gotcha hit building the emitter
- `docs/learned/toolchain/worktree-node-modules.md` — worktree SDK resolution + the stale-global smoke trap
