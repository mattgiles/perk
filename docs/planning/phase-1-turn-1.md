# Phase 1 · Turn 1 — The session test harness (de-risk first)

Detailed execution plan for **P1.T1** of [phase-1-plan.md](../phase-1-plan.md). T1 builds the
**command/extension test substrate**: a small TypeScript harness that drives a **real `pi`
`AgentSession`** through the SDK with the perk extension bound, so every later Phase-1 turn can
verify its interior end-to-end instead of only as isolated pure functions. The "real first target"
is the Phase-0 T3 `perk:workflow-state` lifecycle (claim / keep / fork / `session_tree` rebuild),
re-proven **through a live session**.

> **Scope discipline.** T1 ships **test infrastructure only** — a harness + live tests + the verify
> gate. It drives a session's **lifecycle and state plane** (`session_start`, `session_tree`,
> `appendEntry`, `getBranch`, command invocation) with **zero model inference and zero network**. It
> adds **no** workflow behavior, **no** new handlers, **no** Python, and changes **no** contract or
> registry field. LLM-in-the-loop assertions (the model *choosing* to call a tool) are explicitly
> deferred — they first matter in T3, and even there a command can be invoked directly.

---

## 1. Objective & the gate

**Goal.** Retire the single highest-uncertainty mechanic in Phase 1 — *"we have never driven a real
`pi` session through the SDK"* — by building a reusable harness and proving it against the existing
T3 interior. Phase 0 tested `extension/*.ts` only as isolated `node:test` units
(`workflowState.test.ts`, `cache.test.ts`); T1 proves the same logic **fires correctly when bound to
an actual `AgentSession`**.

**The key de-risking reframe (validated by the spike, §3).** The T3 target is driven entirely by
**session lifecycle events**, not by LLM inference. So the harness needs to create a session, **bind
the extension**, fire its lifecycle, and read/write its entry branch — **no API key, no model turn,
no network**. The "drive a real session" risk collapses to a mechanical wiring problem, which the
spike has already solved.

**Hard gate (must pass to land T1).** Via `scripts/verify-p1-t1.sh` on a fresh clone, **with all
provider API keys unset** (proving offline):

1. **The harness loads and binds the perk extension into a real `AgentSession`** and `session_start`
   fires (proven by the extension's self-check sentinel + `notify`).
2. **claim** — a fresh session with `PERK_RUN_ID` set + a matching handoff claims the run
   (`appendEntry` → read-back → handoff `consumed: true`), `source: env`.
3. **keep (reload)** — `session.reload()` re-emits `session_start`; the run_id is preserved
   (`source: session`), no fork.
4. **fork** — a session whose `perk:workflow-state` carries a `pi_session_id` that differs from the
   session's own id derives a child `<run_id>.1` with the parent recorded (`source: fork`).
5. **`session_tree`** — `session.navigateTree(entryId)` fires the tree-rebuild handler
   (`source: tree`).
6. **command invocation** — `/perk-selfcheck` runs to completion offline.
7. **headless fail-safe** — with no `uiContext` (`ctx.hasUI === false`), a missing handoff is
   reported, **not thrown** (the session loads unclaimed; no crash).
8. **the existing unit suite still passes** (`node --test extension/*.test.ts`) — the live tests
   *complement*, never replace, the pure-function units.

`just verify` runs t1…t7 **+ p1-t1**; `just test` already globs `extension/*.test.ts` and picks up
the new live test with no change.

---

## 2. Grounding & doc lineage (what governs T1)

- **The phase plan.** [phase-1-plan.md](../phase-1-plan.md) §P1.T1: *spike then build the
  command/extension substrate on the SDK + `SessionManager.inMemory()`; determinism + isolation via
  in-memory settings + a `DefaultResourceLoader` override; prove it against the T3 claim/fork through
  a live session, exercising the rebuild on **both** `session_start` and `session_tree`.* T1
  discharges that line verbatim.
- **Pi mechanics (authoritative).** [pi--best-practices.md](../pi--best-practices.md) §2 (the SDK
  surface: `createAgentSession`, `SessionManager.inMemory()`,
  `SettingsManager.inMemory({ compaction:{enabled:false} })`, `DefaultResourceLoader` overrides) and
  §3–§4 (the event catalog: `session_start` rebuilds, `session_tree` rebuilds again). The
  [SDK reference](../../docs) and the installed examples under
  `@earendil-works/pi-coding-agent/examples/sdk/` are the ground truth — and the spike (§3) corrects
  one thing the prose understates (binding, not creation, emits `session_start`).
- **The target under test.** `extension/index.ts` (`session_start` claim/keep/fork +
  `session_tree`), `extension/workflowState.ts` (`decideClaim` / `rebuildWorkflowState` /
  `deriveForkRunId`), `extension/cache.ts` (handoff/scratch/markers). Contracts §8.2 (`PERK_RUN_ID`)
  and §8.3 (`perk:workflow-state`) define the behavior the live tests assert; T1 **changes none of
  it** (test infra only).
- **Repo conventions in force.** TS plane = npm + biome + tsc; tests = Node's built-in `node:test`
  running `.ts` directly (Node 22.19 strips types, zero new test-runner deps — the T3 finding still
  holds). No Python in this turn.

---

## 3. Spike findings (the empirical record)

A throwaway spike (`extension/_spike.ts` + a planted-file probe, both deleted) drove a real session
end-to-end. **The spike is essentially the harness** — the build is now mechanical, not exploratory.
Findings, in the order they reshaped the plan:

- **F1 — binding, not creation, emits `session_start`.** `createAgentSession()` *loads* extensions
  (returns `extensionsResult.extensions`) but does **not** bind them; the run modes do. The harness
  must call **`await session.bindExtensions({ uiContext?, commandContextActions?, onError? })`** — that
  is what emits `session_start` (confirmed in the SDK's `rpc-mode.js`). This was the load-bearing
  unknown.
- **F2 — `ctx.hasUI` tracks `uiContext` presence.** Pass a `uiContext` in the bindings → `hasUI ===
  true` (perk's `notify` fires); omit it → `hasUI === false`. **Headful vs headless is a one-flag
  knob**, so the fail-safe paths are directly testable.
- **F3 — fully offline.** `getModel("anthropic", …)` returns a `Model` without checking for a key;
  lifecycle tests never call `prompt()`, so there is **no network**. The spike ran with all API keys
  unset.
- **F4 — claim works end-to-end.** `source: env`, run_id claimed, handoff read + consumed,
  `registry=ok stages=6`, `shared=ok`.
- **F5 — keep via `reload()`.** `session.reload()` re-emits `session_start` (reason `reload`) **when
  bindings exist** and does **not** re-read entries from disk — so the claimed state survives and the
  keep branch fires (`source: session`). No persistence needed.
- **F6 — fork via a planted session file.** `runtime.fork()` is **not** reachable offline (it forks
  from *user-message* entries, which require an LLM turn → `"Invalid entry ID for forking"`). The
  clean alternative: **plant a session `.jsonl`** (header + a hand-written
  `{type:"custom", customType:"perk:workflow-state", data:{ run_id, pi_session_id }}` entry) whose
  `pi_session_id` ≠ the file's basename, then `SessionManager.open(file)`. Proven:
  `source: fork, run_id: 01RID.1, predecessor: 01RID`. `getBranch()` surfaces the hand-written custom
  entry intact.
- **F7 — `session_tree` fires** via `session.navigateTree(entryId)` (`source: tree`).
- **F8 — command invocation is offline.** `session.prompt("/perk-selfcheck")` runs the command
  handler without a model turn; `session.extensionRunner.getRegisteredCommands()` lists it.
- **F9 — isolation holds.** `new DefaultResourceLoader({ cwd: tmp, agentDir: tmp, extensionFactories:
  [perk] })` loads **only** perk (no `~/.pi` or repo-`.pi` bleed); `resources.ts` resolves `shared/`
  + the registry via `import.meta.url` (file location), independent of the temp cwd.

---

## 4. Design decisions (locked)

- **D1 — The harness primitive is bind, not create.** `loadPerkSession()` = `createAgentSession(…)`
  → **`session.bindExtensions({ uiContext? })`** → return handles. (F1)
- **D2 — Isolation by injection + empty discovery roots.** `DefaultResourceLoader({ cwd: tmp,
  agentDir: tmp, extensionFactories: [perk] })`, where `perk` is the default export of
  `extension/index.ts` imported directly (type-safe; no path resolution). cwd/agentDir point at empty
  temp dirs so discovery finds nothing. (F9)
- **D3 — Determinism + offline.** `SettingsManager.inMemory({ compaction: { enabled: false }, retry:
  { enabled: false } })`; a keyless `getModel(…)` that is never prompted for lifecycle tests; the
  verify gate runs with provider API keys unset. (F3)
- **D4 — Headful/headless = `uiContext` presence**, captured by a `headful` flag on the harness; both
  are tested. The headful `uiContext` records `notify` calls for assertion. (F2)
- **D5 — Decision fixtures are hermetic, no LLM, no `runtime.fork`, no disk persistence.**
  - **claim / keep** use `SessionManager.inMemory(cwd)` (currentSessionId is null → claim records
    `pi_session_id: undefined`; `reload()` then keeps via the `pi_session_id === undefined` branch). (F4/F5)
  - **fork** uses `SessionManager.open(plantedFile)` — a crafted `.jsonl` whose `pi_session_id` ≠ the
    file basename. Because the harness controls the filename, it controls the session id, so a single
    planting helper covers fork (mismatch) and, if wanted, an explicit keep-match variant. (F6)
- **D6 — File placement.** Reusable harness at **`extension/testing/harness.ts`**; live tests at
  **`extension/sessionLifecycle.test.ts`** (top-level, matched by the existing `node --test
  extension/*.test.ts` glob). Add **`!extension/testing/`** to package.json `files` so the dev-only
  harness is never published.
- **D7 — `@earendil-works/pi-ai` becomes an explicit devDependency** (for `getModel`). It is a
  peerDependency today; the harness imports it directly, so it must be resolvable as a dev dep.
- **D8 — `scripts/verify-p1-t1.sh`** (Phase-1 naming, distinct from Phase-0 `verify-t1.sh`) runs the
  live suite **offline** (API keys unset) and asserts the harness + test files exist; appended to
  `just verify` after `verify-t7.sh`.

---

## 5. Deliverables

| Path | What |
|---|---|
| `extension/testing/harness.ts` | The reusable harness: `loadPerkSession()`, a planted-session-file helper, a temp-cwd scaffold (mirrors the Python `git_repo`/temp fixtures), and small accessors (`getWorkflowState`, `sentinel`, `navigateTo`, `invokeCommand`, `reload`, `notifies`, `dispose`). |
| `extension/sessionLifecycle.test.ts` | The live tests: claim, keep (reload), fork (planted), `session_tree`, command invocation, headless fail-safe. |
| `package.json` | Add `@earendil-works/pi-ai` to `devDependencies` (D7); add `!extension/testing/` to `files` (D6). |
| `scripts/verify-p1-t1.sh` | The hard gate (§1); offline; appended to `just verify`. |
| `justfile` | `verify` recipe gains `bash scripts/verify-p1-t1.sh`. |

No Python files, no `shared/` files, no registry edits.

---

## 6. The harness API (sketch)

A thin wrapper — deliberately small, because the spike already proved the mechanics:

```ts
// extension/testing/harness.ts  (dev-only; excluded from the published tarball)
interface PerkSession {
  session: AgentSession;
  notifies: string[];            // captured ui.notify calls (headful only)
  getWorkflowState(): WorkflowState;          // rebuild from the live branch
  sentinel(): Record<string, unknown> | null; // the PERK_SELFCHECK sentinel
  navigateTo(entryId: string): Promise<void>; // fire session_tree
  invokeCommand(name: string): Promise<void>; // e.g. "perk-selfcheck"
  reload(): Promise<void>;                    // re-emit session_start
  dispose(): void;
}

// Create a temp cwd with a minimal .pi/workflow scaffold (+ optional handoff).
function scaffoldRepo(opts?: { handoff?: { runId: string; mode?: string } }): string;

// Plant a session .jsonl carrying workflow-state entries; returns its path.
// The basename is the session id, so callers control claim/keep/fork.
function plantSession(cwd: string, entries: Partial<WorkflowState>[], opts?: { piSessionId?: string }): string;

// createAgentSession(...) -> bindExtensions({ uiContext? }) -> PerkSession.
async function loadPerkSession(opts: {
  cwd: string;
  env?: Record<string, string>;     // e.g. { PERK_RUN_ID: "01RID", PERK_SELFCHECK: "1" }
  sessionManager?: SessionManager;   // default inMemory(cwd); plantSession callers pass open(file)
  headful?: boolean;                 // default true; false => ctx.hasUI === false
}): Promise<PerkSession>;
```

**Settings/loader are fixed inside `loadPerkSession`** (D2/D3): in-memory settings with compaction +
retry off, a `DefaultResourceLoader` injecting only `perk`, and a keyless model that is never
prompted.

---

## 7. The live test cases (mapping unit → end-to-end)

Each case has a `node:test` twin in `workflowState.test.ts`; the live test proves the **wiring**, not
the logic again.

1. **claim** — `scaffoldRepo({ handoff:{ runId:"01RID", mode:"read-only" } })`, `env:{ PERK_RUN_ID:
   "01RID" }`, headful. Assert: sentinel `source:env`, `getWorkflowState().run_id === "01RID"`,
   handoff `consumed:true`, `notifies` includes the load message.
2. **keep (reload)** — from the claimed session, `await reload()`. Assert: sentinel `source:session`,
   run_id preserved, no child id.
3. **fork** — `plantSession(cwd, [{ run_id:"01RID" }], { piSessionId:"OTHER" })` →
   `SessionManager.open(file)`, headful. Assert: sentinel `source:fork`, `run_id === "01RID.1"`,
   `predecessor === "01RID"`, the child scratch dir exists.
4. **`session_tree`** — claimed session, `await navigateTo(firstEntryId)`. Assert: the tree handler
   fired (sentinel `source:tree`).
5. **command** — `await invokeCommand("perk-selfcheck")` resolves; `getRegisteredCommands()` lists it.
6. **headless fail-safe** — `headful:false`, `env:{ PERK_RUN_ID:"01MISS" }` with **no** handoff
   planted. Assert: it does **not** throw, the session loads unclaimed, and `notifies` is empty
   (`ctx.hasUI === false`).

---

## 8. Acceptance — `scripts/verify-p1-t1.sh`

Mirrors the Phase-0 verify-script style (color pass/bad, `set -uo pipefail`, temp workdir, cumulative
under `just verify`). It:

- runs `node --test extension/sessionLifecycle.test.ts extension/*.test.ts` **with
  `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`GEMINI_API_KEY` unset**, asserting all pass (offline proof);
- asserts `extension/testing/harness.ts` and `extension/sessionLifecycle.test.ts` exist;
- (light structural check) greps the test for `bindExtensions(` — the proof that it drives a real
  bound session, not a re-import of the pure functions.

`just ci` (lint + typecheck + test) and `just verify` (t1…t7 + p1-t1) must stay green.

---

## 9. Explicitly out of scope for T1 (pointers)

- **`createAgentSessionRuntime` / rebind after session swap** — not needed (claim/keep/fork are
  reached via plant + `reload()`, no in-process swap). The rebind discipline lands when an in-process
  swap actually exists — Phase 2 (`/implement`'s warm path); the Phase-1 cold door is a fresh
  process.
- **LLM-in-the-loop assertions** (the model *deciding* to call a tool) — T3+, and even there a
  command/tool can be invoked directly.
- **Python / `CliRunner` work** — the exterior test surface already exists from Phase 0; T1 is the
  TS/SDK interior surface only (phase-1-plan "two test surfaces").
- **Contract or registry changes** — none; the `save`-stage registry fill is T2.
- **Worker / end-to-end tests** — Phase 3.

---

## 10. Definition of done

The eight gate checks in §1 pass via `scripts/verify-p1-t1.sh` on a fresh clone **with API keys
unset**; `extension/testing/harness.ts` + `extension/sessionLifecycle.test.ts` drive a real bound
`AgentSession` and prove claim / keep / fork / `session_tree` / command / headless end-to-end; the
existing `node:test` units still pass; `just ci` and `just verify` (t1…t7 + p1-t1) are green. T1
lands; **every later Phase-1 turn now has a way to verify its interior against a live session.**

---

## 11. Outcomes (recorded on landing)

**Status: landed, all green.** `just verify` runs **t1…t7 + p1-t1, all PASS**; `just ci` green —
ruff + ruff-format + ty + biome + tsc clean; **80 pytest + 17 `node:test`** (11 prior + 6 new live
cases). The harness drives a real bound `AgentSession` and proves claim / keep / fork /
`session_tree` / command / headless **offline** (gate run with all provider keys unset).

**Built (matches §5):**
- `extension/testing/harness.ts` — `loadPerkSession` (`createAgentSession` → `bindExtensions`),
  `scaffoldRepo`, `plantSession`, and the `PerkSession` accessors (`sentinel`, `workflowState`,
  `entryIds`, `registeredCommands`, `navigateTo`, `invokeCommand`, `reload`, `notifies`, `dispose`).
- `extension/sessionLifecycle.test.ts` — the six live cases of §7.
- `package.json` — `@earendil-works/pi-ai@0.78.0` added to `devDependencies` (D7); `!extension/testing/`
  added to `files` (D6, verified by the gate's `npm pack --dry-run` check).
- `scripts/verify-p1-t1.sh` — five offline checks; appended to `justfile` `verify` after `verify-t7.sh`.

**Deviations from the plan (recorded, not retro-edited):**
- **D5 — `entryIds()` instead of a raw `entries()` accessor**, and the keep test reloads with
  `PERK_RUN_ID` *explicitly unset* (`reload({ PERK_RUN_ID: undefined })`) to prove the run is
  restored from session state, not the env — even though `decideClaim` would keep regardless (the
  `state.run_id` branch precedes the env check). Faithful to the doc's intent, slightly stronger.
- **`onError` logs rather than throws** (harness §, vs the §6 sketch's implicit "surface"): a thrown
  `onError` risks an unhandled rejection from a fire-and-forget handler; logging keeps the failure
  visible while a real handler bug still fails the downstream sentinel assertion. perk's handlers
  wrap their own probes, so `onError` does not fire in any current case.
- **`headfulUIContext` is a minimal `{ notify, setStatus, setWidget }` cast** `as unknown as
  ExtensionUIContext` (no `any`; biome-clean): the SDK exposes no headless-UI helper and the full
  interface is ~20 methods; perk only calls `notify`, and the runtime only touched these three during
  bind (spike-confirmed).
- **Headless fail-safe case asserts `sentinel.source === "env"` with `run_id` unclaimed** — the
  claim *decision* is `env`, but the verified-linkage check fails (no handoff) so nothing is appended
  and no UI fires; `console.error` reports it (visible in the gate log), no throw. This is the
  intended Q3 establish-before-consume behavior.

**Dependency change:** one dev dependency added (`@earendil-works/pi-ai`, pinned to the SDK's
`0.78.0`); `package-lock.json` updated. No runtime deps, no Python deps, no contract or registry
change (test infra only, as scoped).

**Tree at handoff:** staged-clean for the user to commit — new files `extension/testing/harness.ts`,
`extension/sessionLifecycle.test.ts`, `scripts/verify-p1-t1.sh`, `docs/planning/phase-1-turn-1.md`;
modified `package.json`, `package-lock.json`, `justfile`, `docs/index.md`, `docs/phase-1-plan.md`.

**Unblocks T2:** plan-storage handlers can now be verified through a live session via the harness
(`loadPerkSession` + `plantSession` + tool/command invocation), the deferred LLM-in-the-loop surface
notwithstanding.
