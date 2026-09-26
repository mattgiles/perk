---
title: Pi extension API — getSystemPromptOptions, ctx.mode, injected-message persistence
read_when: You need live system-prompt inputs, command vs lifecycle-event handlers, session_compact, pi.exec, onUpdate partials, pi git:-package loading, dogfooding extension code, or harness offline-testing.
cluster: pi-extension
---

# Pi extension API

Facts verified against the dist source of `@earendil-works/pi-coding-agent` at the version
`package.json` pins — `## Sources` names the pin SSOT, the last full re-verification, and the
re-verify-at-each-pin-bump rule; body version numbers are event stamps ("since 0.84 …"), never
currency claims. Two hops reshaped these facts: 0.80's pi-ai `/compat` split (the global pi-ai
API moved off the root) and 0.84's `ModelRuntime` consolidation of the session-creation inputs —
both covered in `headless-session-drive.md`. These are the non-obvious API contours an agent
can't derive from the package's root type exports.

## Distillation

- `getSystemPromptOptions()` exists only on COMMAND contexts — lifecycle-event handlers don't
  get it — "`getSystemPromptOptions()` is command-context-only".
- `ctx.mode` (interactive/print) and `ctx.hasUI` answer different questions — pick per use —
  "`ctx.mode` vs `ctx.hasUI`".
- `before_agent_start` fires BEFORE the submitting prompt is persisted, so a first-turn
  transcript read misses it — "`before_agent_start` fires BEFORE the submitting prompt is
  persisted (the first-turn hole)".
- The `context` event runs on EVERY provider call (keep handlers cheap + idempotent) — "The
  `context` event runs on EVERY provider call".
- `pi.sendUserMessage` is void fire-and-forget — the PERSISTED session entry is the only
  delivery evidence (spy on the session instance to assert it offline) — its own section +
  "Asserting `pi.sendUserMessage` injection offline".
- Abort outranks every resolved result: forward `opts.signal` and re-check `aborted` after EVERY
  await — "`ctx.ui.editor` facts".
- Pi's own compaction lands BEFORE `agent_settled`; a driven-compaction door observes
  `session_compact` and arbitrates — "Pi's own compaction runs BEFORE `agent_settled`".
- Pi sanitizes session names only for newlines; strip terminal controls yourself —
  "`setSessionName` / `getSessionName` facts".
- Seam-forwarding + sink tests never prove registration — "A new Pi registration needs a live
  factory/harness assertion".
- How pi resolves/loads a `git:`-package extension (clone root, package-manager internals) —
  "How pi loads a `git:`-package extension".
- Body version numbers are event stamps, never currency claims — "Sources" names the pin SSOT,
  the last full re-verification, and the re-verify-at-each-pin-bump rule.

## `getSystemPromptOptions()` is command-context-only

`getSystemPromptOptions()` lives on `ExtensionCommandContext` **only**, not on the plain
`ExtensionContext` passed to event handlers (`session_start` / `session_tree`). Anything that needs
the live system-prompt construction inputs (`appendSystemPrompt`, `contextFiles`, `skills`) **must
run as a command handler**, not a lifecycle-event handler. perk's `/perk-selfcheck` is a command
precisely for this reason.

What it exposes:

- **`appendSystemPrompt`** = the loader's `.pi/APPEND_SYSTEM.md` content joined with `\n\n`
  (verbatim; the empty string `""` when absent — the declared type stays optional, so consumers
  still coalesce `?? ""`).
- **`contextFiles`** = the loaded `AGENTS.md` files as `{path, content}`.
- The base options are populated by the time `bindExtensions` resolves (tool registration →
  `setActiveToolsByName` → `_rebuildSystemPrompt`), so a command handler reads real loaded content.

**Sensitivity:** it exposes the whole system prompt — log only derived booleans/counts, never the
raw text.

## `ctx.mode` vs `ctx.hasUI`

- `ctx.mode` is `"tui" | "rpc" | "json" | "print"`, defaults to `"print"`, set via
  `bindExtensions({ mode })`. Use it when print-vs-rpc-vs-json matters.
- `ctx.hasUI` is the binary UI gate (`true` for tui+rpc). Orthogonal to `ctx.mode` and coarser.
- **Interactive-only gating is `ctx.mode === "tui"`** (reconfirmed) — `hasUI` also admits RPC and
  is never the interactive gate.

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

`AgentSession.prompt` emits `before_agent_start` **before** it builds the turn's local `messages`
array — the user message, any pending next-turn messages, then the extension customs (plus a
leading system-prompt patch when the prompt/tool loadout changed) — and each message persists only
on its own `message_end` as the run streams, so the just-submitted prompt is **not yet on
`ctx.sessionManager.getBranch()`** when the event fires (`dist/core/agent-session.js`).

Consequence: any branch-scan dedup keyed on a marker the submitting prompt carries has a
**first-turn hole** — it misses a cold seed's marker exactly on the launch turn and
double-delivers. Fix pattern: scan `event.prompt` for the marker **beside** the branch scan
(realized in `extension/substrate/bindingDelivery.ts`; contracts.md §8.9).

The first-turn blindness exists in every `before_agent_start` injector, but it only becomes a bug
when a cold twin seeds the same marker into the launch prompt.

## The `context` event runs on EVERY provider call

The `context` event (= SDK `transformContext`) runs on **every** provider call over the **full
conversation** — every non-system message, injected customs included — not once per session.
(Since 0.87 its `messages` omit system messages: Pi restores the prompt and tool state after each
handler, and the later `context_with_system` event sees the full transcript, its result sent as
returned.) So an *unconditional* strip of an injected custom type would remove it even on its own
injection turn (defeating delivery). Any strip of injected context must be **conditional** — see
`pi/context-injection.md` for the inject-and-conditionally-strip pattern.

## `session_compact` is a first-class pi SDK event — no harness fiction

The `@earendil-works/pi-coding-agent` `ExtensionAPI.on` overloads already declare
`on("session_compact", …)`, and `SessionCompactEvent` (`{ type, compactionEntry, fromExtension,
reason, willRetry }` — `reason: "manual" | "threshold" | "overflow"` names what
triggered the compaction; `willRetry` is `true` when the aborted turn is retried after this
compaction, i.e. overflow recovery) is in the `SessionEvent` union — so
`pi.on("session_compact", …)` typechecks natively in production. Only
the **test** harness needed work: `extension/testing/harness.ts` `emitLifecycle`'s union is
**type-only** (the runtime forwards any event via `emit(event as never)`), so adding
`session_compact` to it is a pure TS-surface change, not new runtime plumbing.

### A captured `ctx` goes stale on session replacement — compaction is not one

Pi invalidates an extension runner on session replacement (`newSession` / `fork` /
`switchSession` dispose the old `AgentSession`) and on `/reload` (the runner is rebuilt); every
later read off a captured `ctx`, and every `pi.*` action, then throws the
`…stale after session replacement or reload…` error (`invalidate` / `assertActive` in
`dist/core/extensions/runner.js` and `loader.js`). Post-replacement work belongs in the
`withSession` callback's fresh ctx. Compaction is **not** a replacement: manual and automatic
compaction append a compaction entry inside the same `AgentSession` and runner, so a
`session_compact` handler's `ctx` stays live and a `ctx.compact` callback may use the captured `pi`
(`extension/pi/v1/drivenCompaction.ts` relies on this). The retired checkpoints handler's
swallow-the-stale-error `session_compact` catch arm (survey:
`docs/design/archive/checkpoints-rpiv-todo-comparison.md`) guarded a mid-compaction replacement the
pinned dist does not perform — never copy it as a compaction-handler default.

- **Export-wins when a "private" helper has a named unit-test obligation.** A helper specced
  module-private but separately required to be unit-tested ships **exported** — the test
  requirement wins (the same resolution as the `plan-review-flow.md` extracted-core recipe).
- **Residual caution:** an error-to-string utility doing `String(e)` throws `TypeError` on a
  null-prototype object (`String(Object.create(null))`).

### `ctx.compact` contains a throwing delegate via `onError`

`ctx.compact` wraps its delegate in its own try/catch: a synchronously-throwing compaction
delegate surfaces through the `onError` callback (classified as a compaction failure), never as a
throw in the caller's settle handling — settle-time code around a `ctx.compact` call needs no
defensive try/catch for the delegate itself.

### Pi's own compaction runs BEFORE `agent_settled` — driven-compaction doors arbitrate

`AgentSession._runAgentPrompt` awaits `_handlePostAgentRun` (`_checkCompaction` →
`_runAutoCompaction`) before the `finally` emits `agent_settled`, so a door calling `ctx.compact`
from `agent_settled` races a compaction that already landed, and a second manual `compact()`
throws `Already compacted`. The recipe (`extension/pi/v1/drivenCompaction.ts`):

- observe `session_compact` while a record is armed — Pi emits it for automatic AND manual
  compaction;
- skip your own compaction and dispatch the continuation if one already landed;
- keep the flag set while yours is in flight, and still resume on a foreign landing when
  `ctx.compact` fails through `onError`.

`ctx.compact` from an extension aborts an in-flight foreign compaction. A seam's pending record is
process-local and lost on `/reload`.

## `setSessionName` / `getSessionName` facts

- Pi sanitizes only `\r\n` → space + trim, and writes the name into an OSC terminal-title sequence,
  so ESC/BEL/C1/bidi characters in a name break out of it — the extension strips them itself
  (`extension/session/sessionName.ts`). Enumerate control/format characters by Unicode property
  (`Bidi_Control` includes `U+061C`, outside General Punctuation), and collapse whitespace before
  stripping for prose fields, strictly for identifiers.
- `pi --name` appends its `session_info` entry BEFORE extensions load; `getSessionName()` walks
  entries newest-first.
- The runner's `setSessionName`/`appendEntry` resolve at call time, so harness tests override them
  as instance properties.

## `ctx.ui.editor` facts

`editor(title, prefill) → Promise<string | undefined>`. Enter submits, Shift+Enter inserts a
newline, Esc resolves `undefined`, Ctrl+G (`app.editor.external`) opens the external editor —
`SettingsManager.getExternalEditorCommand()`: the `externalEditor` setting, else `$VISUAL`, else
`$EDITOR`, else `nano`/`notepad`. Two non-obvious contours:

- **It takes NO AbortSignal** (unlike `select`/`confirm`/`input`) — so a multi-dialog flow must
  check `signal?.aborted` *between* dialogs and let the aborted arm win over an in-flight dialog's
  result. The full discipline (#1922): forward `opts.signal` through structural UI slices and
  re-check `signal?.aborted` after EVERY await — dialogs AND awaited openers — before
  interpreting any resolved value (abort outranks every resolved result); pin the forwarding by
  recording the dialog's options argument in the UI fake and asserting the exact signal.
- **Key hints must ride the dialog *title*** — pi renders no other affordance for them.

The editor-dialog UX (long-plan scrolling, the Ctrl+G round-trip) is automation-untested — pinned
only by the type contract; first real interactive use should confirm.

## `registerTool` execute results details requirement

`AgentToolResult<TDetails>` (pi-agent-core) requires `details` but leaves its type
unconstrained — `ToolDefinition` defaults `TDetails` to `unknown`; nothing in the SDK asks for
`ok`. The `details: { ok: boolean, … }` shape is **perk's own convention**: the warm-door
`Result<D, X>` union in `extension/substrate/result.ts` discriminates on `details.ok` (`ok()` /
`failFor()` build it) and door consumers branch on it. Keep it for every perk tool so those
consumers stay uniform.

## A new Pi registration needs a live factory/harness assertion (#1761)

A seam-forwarding test plus sink tests do not prove `extension/index.ts` registered the
implementation (the entry renderer was the caught instance) — every new Pi registration needs a
live factory/harness assertion resolving through `ExtensionRunner` and exercising the registered
implementation against a real appended entry.

## `onUpdate` partials are full results and mode-agnostic

Two contours of `registerTool` partial updates:

- **`AgentToolUpdateCallback<TDetails>` takes a full `AgentToolResult`** — content **and**
  details — so a partial emission must carry an honest `in_progress`-style marker on placeholder
  details rather than a misleadingly-final partial.
- **Partials are NOT TUI-only**: pi supplies `onUpdate` in JSON/RPC modes too — partial events
  serialize onto those streams. Design partial emissions mode-agnostic; never label them
  UI-facing.

## Read-only gating trap

A custom tool that must stay callable inside a read-only gate has to be named in that stage's
gate-ON allowlist in `extension/substrate/toolGating.ts` — `READ_ONLY_TOOLS`, or
`REFINEMENT_READ_ONLY_TOOLS` for the refinement stage (`gatedToolsFor` picks) — or the
`setActiveTools` filter drops it the moment the gate engages. (The second list this section once
named, the in-process read-only SDK child's `SDK_READ_ONLY_TOOLS`, retired with that child in
#2100.)

## Registration-time `process.cwd()` config reads make harness tests host-repo-sensitive

`installPlanMode` (and any seam reading committed config at factory/registration time) resolves
from `process.cwd()`, **not** the harness `cwd` option. Dogfooding config commits to the perk repo
itself (e.g. `[providers] plan = "plannotator-plan"` in `.perk/config.toml`) then silently vacate
flags/commands inside test runs — the host repo's committed config leaks into the suite.

**Rule:** any harness test exercising registration-time branching must `process.chdir()` into its
scaffold and restore in `finally`. Hit twice independently. Diagnosis shortcut: a harness test
failing only locally/on main → check committed `.perk/config.toml` before suspecting the code.

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
  `node -e 'import("./extension/delivery/ci.ts")…'`) and exercise the changed function —
  Node's native type-stripping runs the edited `.ts` as-is.
- **When a session's own diff registers a NEW tool, the running extension predates it**
  (`Tool … not found`). Hand-authoring the retired fallback path "works" but validates nothing
  about the migration — and re-runs the exact hazard the migration killed. Reload/restart (or
  plan for the stale-session arm) before trusting guidance that names the new tool.
- **`/reload` re-runs the extension factory from disk**, so a stateful session-scoped receiver
  (e.g. a lease-holding inbox consumer) re-claims **in place** under the new code — the
  sanctioned live-smoke path for such receivers (see
  `workflow/lease-outbox-delivery.md`).

## pi print mode executes slash commands fully offline

`session.prompt()` handles `/`-commands **before any provider call**, so
`env -u PERK_RUN_ID pi --mode json -p "/perk-selfcheck"` is a zero-cost offline probing surface
(stderr carries `report()` output). It is **not** a subagent-shape proxy: pi-subagents runs native
children as in-process `AgentSession`s — in the parent, or in its detached runner process — rather
than as `pi -p` subprocesses (`pi/native-sdk-bridge.md` § "Which SDK identity a child runs under").
(The `env -u` guards the inherited `PERK_RUN_ID` leak — see its section below.)

## The inherited `PERK_RUN_ID` leak — cleared in the harness, live in probes

Anything launched from inside a perk session inherits the session's exported `PERK_RUN_ID`; a bound
perk extension that sees it takes the **cold-claim path** and emits linkage-error stderr naming a
ULID you don't recognize — which looks exactly like a regression from run-id code.

- **Resolved in the harness (#2235):** `loadPerkSession`'s `applyEnv` baseline clears
  `PERK_RUN_ID` (and the `PI_SUBAGENT_*` child variables) beside `PERK_SELFCHECK` and restores the
  ambient values on dispose, so harness tests are hermetic unless one opts in through `env`.
- **Still live wherever that baseline is not in force:** `pi --mode json -p` probes, headless probe
  scripts, and node-tests that never call `loadPerkSession` inherit it — launch them with
  `env -u PERK_RUN_ID …`.
- Diagnosis: `echo $PERK_RUN_ID`. CI is unaffected (no perk session env).

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

## `pi.sendUserMessage` is void fire-and-forget — only the persisted entry is delivery evidence

`pi.sendUserMessage` returns void; while the agent streams it enqueues onto the session's
in-memory steering / follow-up queues (`deliverAs: "steer" | "followUp"`). `AgentSession.abort()`
does **not** drain them — `clearQueue()` is separate (the TUI abort handler calls it via
`restoreQueuedMessagesToEditor`; RPC exposes it as `clear_queue`), so a headless driver that
aborts must clear explicitly or the queue rides the next run. Call-return proves **nothing** —
the only acceptance evidence that a message was delivered is the message appearing as a
**persisted user-role `SessionMessageEntry` on the branch**. (The "spy on the session instance"
section below remains the offline assertion path for pinning that an injection was *attempted*.)

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

## `headfulUIContext` fakes no dialogs — no `select`/`input`/`editor`/`confirm`

The test harness's headful UI fake records only `notify`/`setStatus`/`setWidget` plus
`setFooter`/`setWorkingIndicator` captures — **no `select`/`input`**, **no `editor`**, and **no
`confirm`** — so a dialog reached through `invokeCommand` (a real `session.prompt`) isn't testable
offline. A registered tool's dialogs are testable: `invokeTool`'s `opts.ui` overlays scripted
answers on the recording UI (`plan_review`'s launch chooser in
`extension/pi/v1/planReview.test.ts`). The other workaround is the exported pure decode + pure
core pattern — the handler stays a thin wiring layer and the decode + core are tested directly
with a fake UI (see `pi/tool-param-decode.md`). The realized editor-dialog recipe
(`workflow/plan-review-flow.md`) harness-tests the arms that never reach a dialog (headless /
bad_input / no_plan / bridge) and tests the dialog arms via an extracted core + a scripted UI fake.

The **`confirm` gap** closes the same two ways: pass a recording `confirm` through `invokeTool`'s
`opts.ui` (`run_ci`'s accept/decline/latch tests in `extension/pi/v1/delivery/ci.test.ts`), or test
an exported **core function** given **structural fakes** — a `fakeCtx` carrying a scripted `confirm`
that *records* `{title, message}` and returns a canned answer. In-repo core instance: the
`submit_pr_review` formal-event gate in `extension/pi/v1/codeReview/submit.test.ts`
(`formalEventGateFor` scripts a recording confirm; a `comment` event never confirms; a headless
formal event refuses before any exec).

## `pi.exec` never throws on spawn failure

The SDK's `execCommand` (`dist/core/exec.js`) returns a Promise that **resolves on every
asynchronous path** — the exit arm and the spawn-error arm both resolve; the sole rejection is a
synchronous `spawn` argument-validation throw in the executor, unreachable from a well-formed
call. A normal exit resolves
`{stdout, stderr, code, killed}`; a **spawn error** (ENOENT/EACCES — the binary is absent or not
executable) lands in `waitForChildProcess`'s `.catch` arm and resolves `{stdout, stderr, code: 1,
killed: false}`. One throw sits in front of all that: the extension API's `pi.exec` calls
`assertActive()` first (`dist/core/extensions/loader.js`), so a captured `pi` used after session
replacement or `/reload` — or one whose extension failed to load — throws **synchronously**, before
any spawn. Consequences:

- A `try/catch` around `pi.exec` never sees a spawn failure — it can catch only that stale-API guard
  (see "A captured `ctx` goes stale on session replacement") or a malformed-argument throw.
- A **binary-absence probe** needs only the non-zero-exit arm: `const ok = !probe.killed && probe.code === 0`
  (the `hunk --version` refuse-at-start probe in `extension/pi/v1/codeReview/checkout.ts` is exactly this).
- **Tests should not model binary absence as a throw** — a spawn failure never throws through the
  API. Model absence with a *failing fake* (see the next section), not a rejected promise.

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
- In-repo instance: `fakeHunk` in `extension/pi/v1/codeReview/terminal.test.ts`.

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
(`getAliases` in `dist/core/extensions/loader.js` — read it for the live key set; at the
last audit: the pi-coding-agent / pi-agent-core / pi-tui / pi-ai (+ `/compat`, `/oauth`,
`/providers/all`) families under both the `@earendil-works` and `@mariozechner` scopes, plus
typebox (+ `/compile`, `/value`) and the `@sinclair/typebox` twins; both pi-ai root keys resolve
to the `/compat` entry) **plus** native `node_modules` walking. Three distinct gaps in
`@earendil-works/pi-coding-agent/dist/core/package-manager.js` can leave a consumer loading *no*
tools or *months-old* code:

- **(a) No load-time self-heal.** Since 0.84 the **install/update path self-heals**: `installGit`
  on a present clone delegates to `ensureGitRef` (fetch + head-compare; when heads match it
  completes an interrupted update via the `.pi-update-incomplete` marker or runs
  `repairMissingGitDependencies`) — the pre-0.84 "a clone already present at the pinned ref
  returns early and never installs" absolute is gone. But the **load path**
  (`resolvePackageSources`) still only collects a present project/user-scoped clone — no fetch,
  no repair — so a clone carrying no / partial `node_modules` still fails at load
  (`Cannot find module 'yaml'`) until an install/update pass runs.
- **(b) Unlocked lazy-clone race.** `resolvePackageSources` clones a missing `git:` package lazily
  and **UNLOCKED**. Two near-simultaneous launches against an absent clone race: the second sees
  the first's half-created dir, takes the `else` (collect) branch over an incomplete checkout, and
  the extension **silently fails to load** — none of its tools appear, it is absent from
  `[Extensions]`, and a throwing extension lands only in pi's `errors[]`.
- **(c) Frozen present clone.** A **present project-scoped** clone is left **frozen** — pi's
  branch for it only calls `collectPackageResources` with no `git fetch`/`reset`, so a months-old
  clone keeps loading months-old code (wrong import paths; a since-retired import → a hard load
  failure) while a static `doctor` reports green. Only `temporary` unpinned sources are refreshed
  at load (`refreshTemporaryGitSource`).

## Sources

- `@earendil-works/pi-coding-agent` dist — `dist/index.d.ts`, `dist/main.js`,
  `dist/core/{agent-session,sdk,session-manager,system-prompt,settings-manager}.js`,
  `dist/core/extensions/{types.d.ts,runner.js,loader.js}`, `dist/core/package-manager.js`,
  `dist/core/exec.js`, `dist/modes/interactive/interactive-mode.js`,
  `dist/modes/interactive/components/extension-editor.js`, `dist/modes/rpc/rpc-mode.js` — plus the
  nested `pi-agent-core` `dist/agent-loop.js` and `pi-tui` `dist/terminal.js` — at the version
  `package.json` `devDependencies` pins. The `@earendil-works/*` devDependency pins move in lockstep
  (the set `tests/test_packaging.py::test_pi_toolchain_pin_lockstep` enforces), so the pin is the
  single version truth for every dist-scoped fact here.
- **Re-verify at each pin bump.** A bump silently re-asserts every dist-scoped fact here: its
  plan re-reads each against the newly *installed* dist (resolved per
  `toolchain/worktree-node-modules.md`; deep-source reads need `pi/context-system.md`'s read-only
  allowlist) and corrects or dates changes. Last full re-verification: the `0.87.0` dist —
  provenance, not a currency promise; the pin is.

## Cross-references

- `extension/pi/v1/selfcheck.ts` — `getSystemPromptOptions` consumer (a command handler by necessity)
- `docs/learned/pi/context-injection.md` — conditional strip on the every-call `context` event
- `docs/learned/workflow/skill-bindings.md` — branch persistence powering the cold↔warm dedup
- `docs/learned/toolchain/worktree-node-modules.md` — getting the right installed SDK in a worktree
- `docs/learned/pi/tool-param-decode.md` — the pure-decode export that works around the
  `headfulUIContext` gap
- `docs/learned/workflow/session-data.md` — the run-id lifecycle behind the `PERK_RUN_ID` leak
- `docs/learned/workflow/plan-review-flow.md` — the `ctx.ui.editor` consumer + its testing split
- `docs/design/archive/context-payload-baseline.md` — the committed payload-census baseline these
  measurement surfaces produced
