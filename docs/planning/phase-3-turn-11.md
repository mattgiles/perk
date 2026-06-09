# Phase 3 · Turn 11 — End-to-end worker tests (Objective #137, Node 4.1)

Plan: GitHub #216.

## Problem

`driveStage` (Node 1.2) and its run-event stream (Node 1.3) were only covered through a hand-rolled
`FakeSession` injected via `deps.createRuntime` — no real Pi session, no real extension tools, no
real bind/subscribe loop. The ROADMAP deferred an **e2e worker tier**: drive a FULL stage
(`implement`/`address`) through the **real production runtime factory** (`defaultCreateRuntime`)
against the **real `@perk/pi` extension**, driven by a **faux pi-ai model**, with **no live GitHub**.

## Decisions

1. **Drive the real `defaultCreateRuntime`.** No `deps.createRuntime`; pass `model: reg.getModel()`
   (faux) + `deps.eventSink` (array sink). The injected-`FakeSession` tier stays in `worker.test.ts`.
2. **GitHub-free at the `PERK_BIN` seam.** A routing `fake-perk.sh` (`fakePerkRouter`) maps
   `pr-submit` / `pr-resolve-threads` to JSON; both terminating tools shell out through it.
3. **New file `extension/workerE2e.test.ts`** (matches the `extension/*.test.ts` glob); fixture
   builders (`scaffoldWorkerWorktree`, `fakePerkRouter`, `fauxModelRegistration`) added to
   `extension/testing/harness.ts`.
4. **Scenarios:** implement-happy (+ a file-sink twin), address-happy, implement-premature-idle,
   failing-tool (route-don't-relay cap), model_error. Budget/wall-clock/abort/no_model stay in the
   injected tier (timing-sensitive, already covered).
5. **Determinism:** `git init -q` the temp worktree (stops the ancestor `.agents/skills` walk);
   `PERK_NO_LLM=1`; save/restore every mutated `process.env` key; `reg.unregister()` in `finally`.

## Outcomes (what actually got built — deviations + findings)

- **Two load-bearing findings forced corrections to the plan's offline recipe (Discovery #1/#2).**

  1. **Faux provider must register in pi-coding-agent's *bundled* pi-ai instance.** `pi-coding-agent`
     ships its own nested `node_modules/@earendil-works/pi-ai`, a **separate module instance** from
     the top-level `@earendil-works/pi-ai` that `structuredOutput.test.ts` imports. The api-registry
     is module-global *per instance*, so a faux provider registered via the top-level import is
     invisible to the runtime's streamer → `No API provider registered for api: faux…`. Fix:
     `fauxModelRegistration()` resolves pi-ai **as pi-coding-agent sees it** (nested copy when
     present, else the deduped top-level) and registers there. (The `fauxAssistantMessage`/`fauxText`
     /`fauxToolCall` *message builders* are instance-agnostic — the faux stream re-stamps `api`/
     `provider` on clone — so those still import from the top-level package.)

  2. **`defaultCreateRuntime` cannot load `@perk/pi` via on-disk `.pi/settings.json` discovery.** The
     production factory builds its session with `SettingsManager.inMemory({compaction,retry})`, and
     `inMemory` settings are **not** layered over disk — `PackageManager` reads
     `settingsManager.getProjectSettings().packages`, which is empty. So the plan's Discovery #1
     (a temp worktree's `.pi/settings.json` `{"packages":[repoRoot]}` loads the real extension) is a
     **runtime impossibility, not a test artifact**: production discovery via inMemory settings drops
     disk packages entirely. Fix: deliver the extension through the documented
     `resourceLoaderOptions.extensionFactories` seam (`{ extensionFactories: [perk] }`, the same
     injection `loadPerkSession` uses) while STILL driving the real `defaultCreateRuntime` (real
     services → session → runtime, real bind/subscribe, real tools + `PERK_BIN` delegation).
     `scaffoldWorkerWorktree` still writes a real `.pi/settings.json` for fidelity, but it is **not**
     the extension load path here. **Open question flagged for the remote-runner seam:** whether
     production should inject `extensionFactories`/packages into the worker runtime, or layer disk
     project settings — `defaultCreateRuntime` as written would not load `@perk/pi` in a real launch.

  3. **One drive can't populate both an injected array sink AND the default file sink** (`deps.eventSink
     ?? defaultEventSink`). The "assert array + file in one drive" idea was split into two drives: the
     happy scenario runs once with the array sink and once with `fileSink: true` (no injected sink, so
     the production `runEventsPath` NDJSON sink runs) and reads it back.

- **Auth:** the faux model carries `provider:"faux"`; the real runtime resolves an API key for it, so
  each drive seeds `AuthStorage.inMemory({ faux: { type:"api_key", key:"x" } })` (offline; the faux
  provider ignores the key).

- **No `worker.ts` / Python / contract change.** §8.11/§8.12 already name Node 4.1 as the in-process
  array-sink consumer; this turn fulfills the existing contract. 6 new tests; suite green
  (`just lint`, `just typecheck`, `just test`).
