---
title: Pi extension API — getSystemPromptOptions, ctx.mode, injected-message persistence
read_when: You need live system-prompt inputs, command vs lifecycle-event handlers, session_compact, pi.exec, onUpdate partials, pi git:-package loading, dogfooding extension code, or harness offline-testing.
cluster: pi-extension
---

# Pi extension API

Facts verified against the dist source of `@earendil-works/pi-coding-agent` 0.78.x and re-checked
at 0.80.5 (the one notable 0.80 change is the pi-ai `/compat` split — the global pi-ai API moved
off the root; see `headless-session-drive.md`). These are the non-obvious API contours an agent
can't derive from the package's root type exports.

## `getSystemPromptOptions()` is command-context-only

`getSystemPromptOptions()` lives on `ExtensionCommandContext` **only**, not on the plain
`ExtensionContext` passed to event handlers (`session_start` / `session_tree`). Anything that needs
the live system-prompt construction inputs (`appendSystemPrompt`, `contextFiles`, `skills`) **must
run as a command handler**, not a lifecycle-event handler. perk's `/perk-selfcheck` is a command
precisely for this reason.

What it exposes:

- **`appendSystemPrompt`** = the loader's `.pi/APPEND_SYSTEM.md` content joined with `\n\n`
  (verbatim; `undefined` when absent).
- **`contextFiles`** = the loaded `AGENTS.md` files as `{path, content}`.
- The base options are populated by the time `bindExtensions` resolves (tool registration →
  `setActiveToolsByName` → `_rebuildSystemPrompt`), so a command handler reads real loaded content.

**Sensitivity:** it exposes the whole system prompt — log only derived booleans/counts, never the
raw text.

## `ctx.mode` vs `ctx.hasUI`

- `ctx.mode` is `"tui" | "rpc" | "json" | "print"`, defaults to `"print"`, set via
  `bindExtensions({ mode })`. Use it when print-vs-rpc-vs-json matters.
- `ctx.hasUI` is the binary UI gate (`true` for tui+rpc). Orthogonal to `ctx.mode` and coarser.

`ExtensionMode` is **not re-exported from the package root** — only from the deep
`./core/extensions/index`, which `package.json` `exports` does not expose as a subpath. **Restate the
union locally** (`type ExtensionMode = "tui" | "rpc" | "json" | "print"`, structurally assignable to
`ExtensionBindings.mode`). Generalizes: **check the root `dist/index.d.ts` export list before
importing a Pi type by name; deep-only types must be mirrored locally.**

The counterpoint: **`formatSkillsForPrompt`, `Skill`, and `ToolInfo` ARE package-root exports** —
the payload census measures the exact skills-section prompt contribution with pi's own formatter
(no local mirror), and the formatter filters `disableModelInvocation` skills itself, so passing
the full skill list measures the visible contribution. Check the root export list *before*
mirroring — the rule cuts both ways.

## Injected custom messages ARE persisted to the branch

A `before_agent_start` injected custom message (`{ message: { customType, content, display } }`) is
pushed into the turn's `messages` and persisted on `message_end` via
`sessionManager.appendCustomMessageEntry(...)`. So on later turns `getBranch()` includes it — this is
what lets a branch-scan dedup work **without extra state** (see `workflow/skill-bindings.md`).
`display: false` controls **UI rendering only**; the model still sees the content.

## `before_agent_start` fires BEFORE the submitting prompt is persisted (the first-turn hole)

At `before_agent_start`, pi builds the turn's `messages` array locally (user message first),
emits the event, appends extension customs to that local array, and only afterwards persists the
turn — so the just-submitted prompt is **not yet on `ctx.sessionManager.getBranch()`** when the
event fires (verified in pi `dist/core/agent-session.js`).

Consequence: any branch-scan dedup keyed on a marker the submitting prompt carries has a
**first-turn hole** — it misses a cold seed's marker exactly on the launch turn and
double-delivers. Fix pattern: scan `event.prompt` for the marker **beside** the branch scan
(realized in `extension/substrate/bindingDelivery.ts`; contracts.md §8.9).

The first-turn blindness exists in every `before_agent_start` injector, but it only becomes a bug
when a cold twin seeds the same marker into the launch prompt.

## The `context` event runs on EVERY provider call

The `context` event (= SDK `transformContext`) runs on **every** provider call over the **full
message list** — not once per session. So an *unconditional* strip of an injected custom type would
remove it even on its own injection turn (defeating delivery). Any strip of injected context must be
**conditional** — see `pi/context-injection.md` for the inject-and-conditionally-strip pattern.

## `session_compact` is a first-class pi SDK event — no harness fiction

The `@earendil-works/pi-coding-agent` `ExtensionAPI.on` overloads already declare
`on("session_compact", …)`, and `SessionCompactEvent` (`{ type, compactionEntry, fromExtension }`) is
in the `SessionEvent` union — so `pi.on("session_compact", …)` typechecks natively in production. Only
the **test** harness needed work: `extension/testing/harness.ts` `emitLifecycle`'s union is
**type-only** (the runtime forwards any event via `emit(event as never)`), so adding
`session_compact` to it is a pure TS-surface change, not new runtime plumbing.

### The stale-`ctx` compaction race (why a compaction handler's catch arm diverges)

During compaction pi may replace the running session out from under an in-flight handler,
invalidating the extension runner's `ctx` proxy; the next read off it throws
`/stale after session replacement/`. That is **benign** — the replacement session's `session_start`
re-renders — so a `session_compact` handler may **swallow it silently** (an `isStaleCtxError` test on
`String(e)`), **diverging** from the uniform log-not-throw catch every other lifecycle handler uses.
Genuine replay bugs still log. Frame this as the general reason a compaction-time handler's error
handling differs from a normal lifecycle handler. (The handler otherwise mirrors `session_tree`:
rebuild + render, no re-seed.)

- **Export-wins when a "private" helper has a named unit-test obligation.** A helper specced
  module-private but separately required to be unit-tested ships **exported** — the test requirement
  wins (here `isStaleCtxError`; the same resolution as the `plan-review-flow.md` extracted-core
  recipe).
- **Residual caution:** an error-to-string utility doing `String(e)` throws `TypeError` on a
  null-prototype object (`String(Object.create(null))`) — not reachable when the arg is always
  pi-core's proxy error, but a general caution for any such utility.
- The checkpoints-specific charter survey is **not** duplicated here — it lives in
  `docs/design/checkpoints-rpiv-todo-comparison.md`.

## `ctx.ui.editor` facts (pi 0.78.x)

`editor(title, prefill) → Promise<string | undefined>`. Enter submits, Shift+Enter inserts a
newline, Esc resolves `undefined`, Ctrl+G opens `$EDITOR`. Two non-obvious contours:

- **It takes NO AbortSignal** (unlike `select`/`confirm`/`input`) — so a multi-dialog flow must
  check `signal?.aborted` *between* dialogs and let the aborted arm win over an in-flight dialog's
  result.
- **Key hints must ride the dialog *title*** — pi renders no other affordance for them.

The editor-dialog UX (long-plan scrolling, the Ctrl+G round-trip) is automation-untested — pinned
only by the type contract; first real interactive use should confirm.

## `registerTool` execute results details requirement

When registering custom tools via `registerTool`, the execute result object returned by the handler MUST
include a nested `details` object containing at least `ok: boolean` (e.g., `details: { ok: boolean, ... }`).
This is required to satisfy the TypeScript compiler type constraints for `AgentToolResult`.

## `onUpdate` partials are full results and mode-agnostic

Two contours of `registerTool` partial updates:

- **`AgentToolUpdateCallback<TDetails>` takes a full `AgentToolResult`** — content **and**
  details — so a partial emission must carry an honest `in_progress`-style marker on placeholder
  details rather than a misleadingly-final partial.
- **Partials are NOT TUI-only**: pi supplies `onUpdate` in JSON/RPC modes too — partial events
  serialize onto those streams. Design partial emissions mode-agnostic; never label them
  UI-facing.

## Read-only gating trap

Custom planning tools must be registered/listed in `READ_ONLY_TOOLS` in order to survive the
`setActiveTools` filter during planning phases, but they must be strictly **left out** of
`SDK_READ_ONLY_TOOLS`. Leaving them in the former allows them to remain active when planning, while
keeping them out of the latter ensures they aren't incorrectly classified as core SDK-restricted
read-only tools.

## Registration-time `process.cwd()` config reads make harness tests host-repo-sensitive

`registerPlanMode` (and any seam reading committed config at factory/registration time) resolves
from `process.cwd()`, **not** the harness `cwd` option. Dogfooding config commits to the perk repo
itself (e.g. `[providers] plan = "plannotator-plan"` in `.pi/perk.toml`) then silently vacate
flags/commands inside test runs — the host repo's committed config leaks into the suite.

**Rule:** any harness test exercising registration-time branching must `process.chdir()` into its
scaffold and restore in `finally`. Hit twice independently. Diagnosis shortcut: a harness test
failing only locally/on main → check committed `.pi/perk.toml` before suspecting the code.

## Dogfooding just-changed extension code — cwd repo-root loading + `/reload`

pi loads the extension from the **cwd's repo root at session start**; the self-repo wires the
extension as the path package `..`. Three consequences:

- A headless measurement of branch-only code must run **from the worktree** — the main checkout
  still loads main's code.
- A live session that started before an edit runs the **old** code — pi's `/reload` hot-reloads
  extensions mid-session and is the sanctioned way to exercise just-committed extension code in
  the same session.
- `perk plan` launched from a worktree cwd stays in that worktree (verified via
  `perk plan --dry-run`) and loads its extension — enabling a sacrificial pre-merge plan-shape
  session, safe because plan launches mint their own run id (per-run handoff files) and never
  touch `plan-ref.json`.
- **A live session keeps its startup tool registrations.** A post-implementation door call in
  the same session still enforced the pre-change schema — it rejected a widened `maxItems`
  selection the new code allowed. `/reload` or a fresh session is required before dogfooding a
  just-changed tool schema. The same trap covers render/prose changes: a live in-session tool
  runs the extension **loaded at session start**, so dogfooding a just-edited render change
  through the in-session tool shows the pre-edit behavior. The observation path that works
  without `/reload`: import the edited module **directly in a subprocess** (e.g.
  `node -e 'import("./extension/doors/ciExecutor.ts")…'`) and exercise the changed function —
  Node's native type-stripping runs the edited `.ts` as-is.
- **When a session's own diff registers a NEW tool, the running extension predates it**
  (`Tool … not found`). Hand-authoring the retired fallback path "works" but validates nothing
  about the migration — and re-runs the exact hazard the migration killed. Reload/restart (or
  plan for the stale-session arm) before trusting guidance that names the new tool.

## pi print mode executes slash commands fully offline

`session.prompt()` handles `/`-commands **before any provider call**, so
`env -u PERK_RUN_ID pi --mode json -p "/perk-selfcheck"` is a zero-cost offline probing surface
(stderr carries `report()` output). It is also the faithful subagent-shape proxy — pi-subagents
spawns children with baseArgs `--mode json -p`, ± `--no-skills`. (The `env -u` guards the
`PERK_RUN_ID` leak — see the harness section below.)

## The harness inherits the agent's own `PERK_RUN_ID`

node-test runs launched from inside a perk session inherit the session's exported `PERK_RUN_ID`.
Harness tests that pass no `env` then take the **cold-claim path** and emit linkage-error stderr
naming a ULID you don't recognize — and the leak *persists across tests* via the harness env
save/restore (a later test's `applyEnv` snapshots the ambient leaked value and faithfully restores
it on dispose). This looks exactly like a regression from run-id code and costs a debugging detour
if you don't know it.

- Diagnosis: `echo $PERK_RUN_ID`.
- CI is unaffected (no perk session env). Run locally with `env -u PERK_RUN_ID node --test …` for
  representative output.
- Hardening candidate (not done): default `PERK_RUN_ID: undefined` in `loadPerkSession`'s
  `applyEnv` baseline (alongside `PERK_SELFCHECK`/`PERK_NO_LLM`), with claim tests opting in
  explicitly.

## Strict-mode index access in tests

Under the extension's strict `tsconfig.json` compiler options, indexing into arrays or tuples is
strictly checked. To access elements by index safely in test code, you must use optional chaining
`?.` or the `.at()` method rather than direct unsafe brackets (`[0]`), otherwise the compiler will
raise type-safety errors.

## `pi.events` is unreachable from the test harness

The event bus is created inside pi's extension loader; the test-harness runner exposes **no
accessor** for it. The workable split:

- Factor bus-consuming logic **pure-over-the-bus** — a factory taking a minimal `{emit, on}`
  interface (see `createPlannotatorBridge` in the plannotator adapter) — and test decision paths
  with a fake bus.
- Test the registered tool end-to-end only for paths needing **no foreign listener**: not-selected /
  headless / timeout. For the timeout path, prefer **env-var injection over a module-constant
  override** — the harness imports the extension through its own module graph (module identity is
  uncertain) but applies env per-session.

Two adjacent facts:

- The harness **CAN assert flag/shortcut non-registration directly** via
  `session.extensionRunner.getFlags()` / `getShortcuts({})` — stronger than indirect "set flag +
  reload is inert" probes.
- An in-payload `respond` callback plus **one persistent result listener** resolving a
  `Map<reviewId, resolver>` avoids depending on the event-bus unsubscribe return and naturally
  ignores mismatched ids.

## Asserting `pi.sendUserMessage` injection offline: spy on the session instance

The keyless harness session makes a `pi.sendUserMessage` call fail **asynchronously** ("No API key
found") via the runner's error channel — the injected message never lands on the session branch, so
branch inspection can't prove the injection happened. The SDK's extension API delegates as
`this.sendUserMessage(...)` looked up **at call time** on the AgentSession instance, so an
instance-property override — assigning a capturing async function to `session.sendUserMessage` —
cleanly captures the injected guidance. This is the harness-level pattern for pinning a command's
guidance injection (prior tests only asserted notifies + side effects).

**The spy is MANDATORY for any `invokeCommand` test of a seed-turn command, even when the test
doesn't assert the injection.** The harness's `invokeCommand` drives a real `session.prompt`, so a
handler's `pi.sendUserMessage` queues a model turn the keyless offline session can't run — the
test fails for reasons unrelated to what it asserts. Overwrite `h.session.sendUserMessage` with a
capture/no-op (the harness export `spyInjections` in `extension/testing/harness.ts`) in every
such test, and plan authors writing test specs for warm-door
commands should call for the spy explicitly rather than just waiving the assertion.

## `headfulUIContext` fakes only `notify`/`setStatus`/`setWidget`

The test harness's headful UI fake has **no `select`/`input`** — **no `editor`**, and **no `confirm`**
either — so a registered-tool-level UI-interaction test isn't possible offline. The workaround is the
exported pure decode + pure core pattern — the handler stays a thin wiring layer and the decode +
core are tested directly with a fake UI (see `pi/tool-param-decode.md`). Editor-dialog flows
specifically can only be harness-tested for arms that never reach a dialog (headless / bad_input /
no_plan / bridge); dialog arms test via an extracted core + a scripted UI fake — see
`workflow/plan-review-flow.md` for the realized recipe.

The **`confirm` gap** has the same shape: a confirm-gated tool tests its dialog arms through an
exported **core function** given **structural fakes** — a `fakeCtx` carrying a scripted `confirm` that
*records* `{title, message}` and returns a canned answer — reserving the real harness for the
confirm-free arms. In-repo instance: `submitPrReview` in `extension/doors/submitPrReview.test.ts` (a declined
confirm proves no `exec`, an accepted one proceeds to the cold door, a `comment` event never
confirms). Extend the harness with a scripted confirm recorder only if a **third** consumer appears —
two is not yet worth the harness surface.

## `pi.exec` never throws on spawn failure

The SDK's `execCommand` (`dist/core/exec.js`, verified against the pinned SDK) returns a Promise that
**resolves on every path** — there is no rejection. A normal exit resolves
`{stdout, stderr, code, killed}`; a **spawn error** (ENOENT/EACCES — the binary is absent or not
executable) lands in `waitForChildProcess`'s `.catch` arm and resolves `{stdout, stderr, code: 1,
killed: false}`. Consequences:

- A `try/catch` around `pi.exec` is **dead-defensive** — fine as defense-in-depth, but the catch arm
  is unreachable through the real API.
- A **binary-absence probe** needs only the non-zero-exit arm: `const ok = !probe.killed && probe.code === 0`
  (the `hunk --version` refuse-at-start probe in `extension/doors/hunkHandoff.ts` is exactly this).
- **Tests should not try to exercise a throw arm** — it can't happen through the API. Model absence
  with a *failing fake* (see the next section), not a rejected promise.

## Offline-testing a hardcoded external-binary probe: fake executable + PATH prepend

When a door probes a **fixed binary name** (not `PERK_BIN`-style indirected), the offline-test pattern
is a **fake executable + PATH prepend** — the generalization of the `fakePerk`/`PERK_BIN` pattern
(which only covers the perk binary itself):

- Write an executable shell fake into a dir under the scaffold cwd (`fakeHunk` writes
  `<cwd>/fakebin/hunk`, `chmod 0o755`), then **prepend that dir to `PATH`** via `loadPerkSession`'s
  `env` override (`env: { PATH: \`${fakebin}:${process.env.PATH}\` }`).
- A **failing fake** (`exit 1`) deterministically **shadows any real global install**, so the
  refuse-at-start arm stays testable on a dev machine that happens to have the real binary. A
  **passing fake** (`exit 0`, echoing a version) unlocks the downstream flow. A `markerFile` the fake
  `touch`es lets a test prove the fake was (or was NOT) invoked — e.g. the plannotator arm asserting
  it never probes `hunk`.
- In-repo instance: `fakeHunk` in `extension/doors/prReviewTerminal.test.ts`.

## Vendored-extension test/infra facts (#628)

Vendoring a TS-only feature surfaced the offline-test scaffolding facts:

- **Run one node:test file directly with `node --test <file>`** (Node 26 native TS) — there is **NO**
  *extension/testing/register.ts* import hook (that path does not exist; `--import` it and you get
  `ERR_MODULE_NOT_FOUND`). The full suite is `node --test "extension/**/*.test.ts"`.
- **A registration smoke** binds the real extension via the harness's
  `loadPerkSession({ cwd: scaffoldRepo() })` and asserts the command registers — proving
  `session_start` doesn't throw, **fully offline**.
- **The extracted-core pattern** keeps glyph/color/width-sweep assertions offline: move pure helpers
  into a `core.ts`, test them with a **tagging theme fake** (`fg:(c,t)=>...`) for glyph+color and a
  **seeded `Math.random`** for a deterministic random pick (export the pick helper + message list
  purely so the test can seed it).

## How pi loads a `git:`-package extension (package-manager internals)

perk itself ships via npm (see `workflow/distribution.md`), but this is still-current pi behavior
for **any** `git:` package — and perk still recognizes `git:` package identities via
`perk/convergence/init/settings.py::_git_identity`.

pi materializes a `git:` package as a clone at `.pi/git/<host>/<path>/` and loads the extension
from it via jiti, resolving the extension's imports through a **fixed host-alias set**
(`getAliases` in `dist/core/extensions/loader.js`; at 0.80.5: the pi-coding-agent /
pi-agent-core / pi-tui / pi-ai (+ `/compat`, `/oauth`) families under both the `@earendil-works`
and `@mariozechner` scopes, plus typebox (+ `/compile`, `/value`) and the `@sinclair/typebox`
twins) **plus** native `node_modules` walking. Three distinct gaps in
`@earendil-works/pi-coding-agent/dist/core/package-manager.js` can leave a consumer loading *no*
tools or *months-old* code:

- **(a) No self-heal install.** `installGit`/`ensureGitRef` run `npm install --omit=dev` **only**
  on a fresh clone OR when `localHead != targetHead`. A clone already present at the pinned ref
  returns early and never installs (`pi update` shares that early return) — so a clone can carry
  no / partial `node_modules` and pi cannot self-heal → `Cannot find module 'yaml'` at load.
- **(b) Unlocked lazy-clone race.** `resolvePackageSources` clones a missing `git:` package lazily
  and **UNLOCKED**. Two near-simultaneous launches against an absent clone race: the second sees
  the first's half-created dir, takes the `else` (collect) branch over an incomplete checkout, and
  the extension **silently fails to load** — none of its tools appear, it is absent from
  `[Extensions]`, and a throwing extension lands only in pi's `errors[]`.
- **(c) Frozen present clone.** A **present project-scoped** clone is left **frozen** — pi's
  branch for it only calls `collectPackageResources` with no `git fetch`/`reset`, so a months-old
  clone keeps loading months-old code (wrong import paths; a since-retired import → a hard load
  failure) while a static `doctor` reports green.

## Sources

- `@earendil-works/pi-coding-agent` dist (`agent-session.js`, `dist/index.d.ts`,
  `dist/core/extensions/loader.js`, `dist/core/package-manager.js`) — verified at 0.78.x,
  re-verified against the installed pinned pi 0.80.5. Re-verify against the installed version
  before relying on a deep-source detail; pin checks
  matter (see `pi/context-system.md` on the read-only allowlist and `toolchain/worktree-node-modules.md`
  on resolving the *installed* SDK in a worktree).

## Cross-references

- `extension/doors/selfcheck.ts` — `getSystemPromptOptions` consumer (a command handler by necessity)
- `docs/learned/pi/context-injection.md` — conditional strip on the every-call `context` event
- `docs/learned/workflow/skill-bindings.md` — branch persistence powering the cold↔warm dedup
- `docs/learned/toolchain/worktree-node-modules.md` — getting the right installed SDK in a worktree
- `docs/learned/pi/tool-param-decode.md` — the pure-decode export that works around the
  `headfulUIContext` gap
- `docs/learned/workflow/session-data.md` — the run-id lifecycle behind the `PERK_RUN_ID` leak
- `docs/learned/workflow/plan-review-flow.md` — the `ctx.ui.editor` consumer + its testing split
- `docs/design/context-payload-baseline.md` — the committed payload-census baseline these
  measurement surfaces produced
