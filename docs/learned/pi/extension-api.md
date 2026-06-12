---
title: Pi 0.78.x extension API — getSystemPromptOptions, ctx.mode, injected-message persistence
read_when: You need live system-prompt inputs in an extension, are choosing a command vs lifecycle-event handler, importing a Pi type, reasoning about whether an injected custom message persists, using `ctx.ui.editor` (no AbortSignal, title-borne key hints), testing `pi.events`-bridge logic / flag-shortcut non-registration from the harness, asserting a `pi.sendUserMessage` injection offline (the spy is mandatory for seed-turn `invokeCommand` tests), hitting the `headfulUIContext` select/input/editor gap, a harness test failing only locally/on main (registration-time cwd config reads), or unexplained run-id stderr in local node tests (the `PERK_RUN_ID` leak).
---

# Pi extension API (0.78.x)

Facts verified against the dist source of `@earendil-works/pi-coding-agent` 0.78.x. These are the
non-obvious API contours an agent can't derive from the package's root type exports.

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

## Injected custom messages ARE persisted to the branch

A `before_agent_start` injected custom message (`{ message: { customType, content, display } }`) is
pushed into the turn's `messages` and persisted on `message_end` via
`sessionManager.appendCustomMessageEntry(...)`. So on later turns `getBranch()` includes it — this is
what lets a branch-scan dedup work **without extra state** (see `workflow/skill-bindings.md`).
`display: false` controls **UI rendering only**; the model still sees the content.

## The `context` event runs on EVERY provider call

The `context` event (= SDK `transformContext`) runs on **every** provider call over the **full
message list** — not once per session. So an *unconditional* strip of an injected custom type would
remove it even on its own injection turn (defeating delivery). Any strip of injected context must be
**conditional** — see `pi/context-injection.md` for the inject-and-conditionally-strip pattern.

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
capture/no-op (the existing recipe in `extension/doors/learnDocs.test.ts` /
`objectivePlan.test.ts`) in every such test, and plan authors writing test specs for warm-door
commands should call for the spy explicitly rather than just waiving the assertion.

## `headfulUIContext` fakes only `notify`/`setStatus`/`setWidget`

The test harness's headful UI fake has **no `select`/`input`** — and **no `editor`** either — so a
registered-tool-level UI-interaction test isn't possible offline. The workaround is the exported
pure decode + pure core pattern — the handler stays a thin wiring layer and the decode + core are
tested directly with a fake UI (see `pi/tool-param-decode.md`). Editor-dialog flows specifically
can only be harness-tested for arms that never reach a dialog (headless / bad_input / no_plan /
bridge); dialog arms test via an extracted core + a scripted UI fake — see
`workflow/plan-review-flow.md` for the realized recipe.

## Sources

- `@earendil-works/pi-coding-agent` dist (`agent-session.js`, `dist/index.d.ts`) — verified at
  0.78.x. Re-verify against the installed version before relying on a deep-source detail; pin checks
  matter (see `pi/context-system.md` on the read-only allowlist and `toolchain/worktree-node-modules.md`
  on resolving the *installed* SDK in a worktree).

## Cross-references

- `extension/selfcheck.ts` — `getSystemPromptOptions` consumer (a command handler by necessity)
- `docs/learned/pi/context-injection.md` — conditional strip on the every-call `context` event
- `docs/learned/workflow/skill-bindings.md` — branch persistence powering the cold↔warm dedup
- `docs/learned/toolchain/worktree-node-modules.md` — getting the right installed SDK in a worktree
- `docs/learned/pi/tool-param-decode.md` — the pure-decode export that works around the
  `headfulUIContext` gap
- `docs/learned/workflow/session-data.md` — the run-id lifecycle behind the `PERK_RUN_ID` leak
- `docs/learned/workflow/plan-review-flow.md` — the `ctx.ui.editor` consumer + its testing split
