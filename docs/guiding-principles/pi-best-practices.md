# Pi best practices, from the official examples

Distilled from the canonical examples in the Pi repo:
`~/dev/github/earendil-works/pi/packages/coding-agent/examples/` (`sdk/` for programmatic
usage, `extensions/` for ~70 worked extensions). Where `agent-stuff` is a real-world *style
guide* (see [agent-stuff-best-practices.md](./agent-stuff-best-practices.md)), this is the
**authoritative reference** — the patterns the Pi authors ship as exemplars. Evidence is
cited by example path.

This doc emphasizes what the official set adds beyond agent-stuff: the **SDK/embedding
surface**, the full **event/API catalog**, the canonical **mode/tool-gating** and
**subagent-spawning** patterns, **session-lifecycle gates**, **compaction/handoff**, and the
**two state-persistence channels**.

---

## 1. Two ways to use Pi — and when each

| Surface | Entry point | Use for |
|---|---|---|
| **SDK (programmatic)** | `createAgentSession()` / `createAgentSessionRuntime()` (`sdk/`) | embedding Pi in another process, the **headless worker**, tests, custom hosts |
| **Extensions** | `export default (pi: ExtensionAPI) => {}` (`extensions/`) | in-session behavior: tools, commands, modes, gating, UI |

For perk these are *both* load-bearing: the Python `perk` CLI launches `pi` as a subprocess
(see `cli-vs-pi.md`), but the headless worker and the test harness are SDK consumers, and
all in-session workflow is extensions. Know both.

---

## 2. The SDK surface (`sdk/`)

`createAgentSession(options)` returns `{ session }`. The option surface (`sdk/README.md`,
`12-full-control.ts`) is the whole embedding contract:

```ts
const { session } = await createAgentSession({
  model, thinkingLevel,                 // inference
  tools: ["read", "grep", "find", "ls"],// allowlist across built-in/extension/custom tools
  customTools: [myTool],
  authStorage, modelRegistry,           // credentials + models
  resourceLoader,                       // extensions/skills/prompts/themes (or overrides)
  sessionManager: SessionManager.inMemory(),
  settingsManager: SettingsManager.inMemory({ compaction: { enabled: false } }),
});
session.subscribe((event) => { /* message_update, tool_execution_start/end, agent_end */ });
await session.prompt("…");
session.dispose();
```

Lessons that matter for perk:

- **`tools: [...]` is the read-only knob at the SDK level.** A read-only session is just
  `tools: ["read","grep","find","ls"]` (`sdk/README.md`). The headless CI executor can be
  spun this way, not only via in-session gating.
- **`SessionManager` has explicit lifecycles** (`sdk/11-sessions.ts`): `inMemory()` (tests),
  `create(cwd)` (new persisted), `continueRecent(cwd)`, `open(path)`, `list(cwd)`. Sessions
  are addressable files — the basis for perk's resume/cold-door.
- **`DefaultResourceLoader` with overrides** (`sdk/06-extensions.ts`, `12-full-control.ts`)
  lets a host inject `extensionFactories`, `systemPromptOverride`, and replace
  skills/prompts/agents entirely — i.e. perk can run a *locked-down* resource set in CI
  without touching the user's config.
- **`createAgentSessionRuntime`** (`sdk/13-session-runtime.ts`) is the pattern for
  **replacing the active session** (new / resume / fork / import). Critical detail: after a
  swap, **rebind every session-local subscription and `session.bindExtensions({})`** to the
  new `runtime.session`. perk's CLI stage transitions that swap sessions must follow this.
- **Settings overrides** disable compaction/retry, etc. for deterministic runs
  (`12-full-control.ts`) — exactly what a reproducible CI/worker wants.

---

## 3. Extension anatomy & the authoritative event catalog

`export default function (pi: ExtensionAPI) { … }`. Events observed across the official set
(ranked by usage), with their best-practice purpose:

| Event | Purpose |
|---|---|
| `session_start` | **rebuild state**, restore mode, register dynamic tools, read flags |
| `session_tree` | **rebuild state again on branch navigation** (don't skip this) |
| `before_agent_start` | inject/append system prompt or a hidden context message |
| `agent_start` / `agent_end` | accounting, follow-up queueing, completion handling |
| `turn_start` / `turn_end` | transient status, checkpoints, threshold-triggered compaction |
| `tool_call` | **gate/block** a tool (`{ block, reason }`) |
| `tool_result` | augment output; track current leaf entry |
| `context` | filter the messages the model sees |
| `input` | transform the user's prompt before the turn |
| `user_bash` | intercept user `!` commands |
| `session_before_switch` / `session_before_fork` | **cancel** destructive session ops (`{ cancel: true }`) |
| `session_before_compact` | custom compaction (`{ compaction }`) |
| `resources_discover` | contribute skills/prompts/themes dynamically |
| `model_select` | react to model changes |
| `before_provider_request` / `after_provider_response` | low-level request/response hooks |
| `session_shutdown` | cleanup (sockets, watchers, temp files) |

Core `pi.*` API seen in the examples: `on`, `registerTool`, `registerCommand`,
`registerShortcut`, `registerFlag`/`getFlag`, `registerMessageRenderer`, `registerProvider`,
`setActiveTools`/`getActiveTools`/`getAllTools`, `setModel`/`setThinkingLevel`/
`getThinkingLevel`, `sendMessage`/`sendUserMessage`, `appendEntry`, `exec`, `events`
(emit/on), `setSessionName`/`getSessionName`, `setLabel`.

Core `ctx.*`: `ui.*`, `sessionManager.*`, `model`, `modelRegistry`, `cwd`, `hasUI`,
`newSession`, `compact`, `getContextUsage`, `getLeafEntry`, `navigateTree`, `shutdown`.

---

## 4. State persistence — two channels, restore on *both* entry points

The official examples codify **two** persistence channels (extensions/README.md "Key
Patterns"):

1. **Custom session entries** — `pi.appendEntry("my-state", data)`, read back by scanning
   `ctx.sessionManager.getBranch()` for `entry.type === "custom" && entry.customType === …`
   (`plan-mode`, `tools.ts`, `preset.ts`).
2. **Tool-result `details`** — state stored in a tool's returned `details` is persisted in
   the session and **survives forking**; reconstruct by scanning entries for that tool's
   messages (extensions/README.md). Prefer this when the state *is* the tool's output.

The non-negotiable discipline: **restore on `session_start` AND `session_tree`.** `tools.ts`
does exactly this ("persists across reloads and respects branch navigation") and so does
`plan-mode`. Skipping `session_tree` is the bug that makes state stale after the user
navigates the tree — the authoritative confirmation of perk's "rebuild on every entry point"
rule.

`plan-mode` adds a subtlety worth copying: when restoring an *execution* state, only re-scan
messages **after** the marker entry that started the current execution, so you don't pick up
stale `[DONE:n]` markers from a previous plan.

---

## 5. Modes & tool gating — the canonical pattern

`extensions/plan-mode/` is the reference implementation of a read-only mode, and it is
*exactly* perk's plan-mode / read-only-CI primitive. The recipe:

1. **Swap the tool allowlist** with `pi.setActiveTools(PLAN_MODE_TOOLS)` vs
   `NORMAL_MODE_TOOLS`.
2. **Enforce a bash sub-allowlist** in `tool_call`: if the command isn't allowlisted,
   `return { block: true, reason }`.
3. **Inject mode context** in `before_agent_start` as a hidden message
   (`display: false`, a `customType` you own).
4. **Strip stale mode context** in `context` when the mode is off (filter by `customType`
   and a sentinel like `[PLAN MODE ACTIVE]`).
5. **Track progress** (`turn_end` scans for `[DONE:n]`) and **persist + restore** the mode
   across `session_start`.
6. **Gate behind a `--plan` flag** (`registerFlag`) for headless starts.

`extensions/preset.ts` generalizes this into **named presets** (model + thinkingLevel +
tools + instruction append), merged from `~/.pi/agent/presets.json` and
`<cwd>/.pi/presets.json`, applied via `--preset`/`/preset`/cycle-shortcut, **snapshotting
the original state to restore on exit**. Its shipped example config literally defines `plan`
and `implement` presets — i.e. perk's mode system is a first-class, already-blessed Pi
pattern. Borrow the **snapshot-then-restore** and **project-overrides-global** mechanics
directly.

> For perk: build one generic "mode" primitive (`setActiveTools` + `tool_call` allowlist +
> `before_agent_start` injection + `context` strip + snapshot/restore + flag), parameterized
> for plan-mode and read-only-CI. This is precisely the "reusable gating primitive" the
> ROADMAP calls for, and plan-mode/preset are the working templates.

---

## 6. Tools — the full contract

```ts
pi.registerTool({
  name, label, description,
  promptSnippet, promptGuidelines,        // when/how the model should call it
  parameters: Type.Object({ … }),         // typebox; use StringEnum for string enums
  executionMode: "sequential",            // serialize calls that mutate shared state
  async execute(id, params, signal, onUpdate, ctx) {
    onUpdate({ content: […], details });  // stream partial results
    return { content: […], details, terminate: true, isError };
  },
  renderCall(args, theme, ctx) { … },     // custom collapsed call rendering
  renderResult(result, { expanded }, theme, ctx) { … }, // collapsed/expanded result UI
});
```

- **Dual return: `content` (model) + `details` (structured/persisted).** Universal across
  the examples. `details` doubles as forking-safe state (§4).
- **`terminate: true`** (`structured-output.ts`) ends the turn on the tool call — no extra
  LLM round-trip. Use for terminal actions (save-plan, emit-final-result).
- **`renderCall` / `renderResult`** are heavily used (24/22 occurrences) — collapsed vs
  `expanded` (Ctrl+O) views built from `pi-tui` (`Text`, `Container`, `Markdown`, `Spacer`).
  `subagent` is the master class; `structured-output` is the minimal one. *Omit them* to get
  the built-in renderer (syntax highlight, line numbers, truncation) — `tool-override.ts`
  relies on this.
- **Override built-ins by registering the same `name`** (`tool-override.ts` audits/blocks
  `read`; multi-edit overrides `edit`). Do access-control/logging in `execute`, then
  delegate.
- **`executionMode: "sequential"`** (`tic-tac-toe.ts`) prevents races when parallel tool
  calls touch shared state — relevant to perk tools mutating the plan/objective cache.
- **Dynamic registration** (`dynamic-tools.ts`): register at `session_start` or at runtime
  via a command; guard against duplicate names.
- **`StringEnum(["a","b"] as const)`** for string-enum params — `Type.Union([Literal…])`
  breaks Google compatibility (extensions/README.md, subagent).

---

## 7. Safety & session-lifecycle gates

Two distinct gate families:

**Tool gates** (`tool_call` → `{ block, reason }`):
- `permission-gate.ts` — confirm dangerous bash (`rm -rf`, `sudo`, `chmod 777`); **block by
  default when `!ctx.hasUI`** (can't confirm headless → fail safe).
- `protected-paths.ts` — block `write`/`edit` to `.env`, `.git/`, `node_modules/`.
- `plan-mode` — read-only command allowlist.
- Enforce inside `execute` too (`tool-override.ts`) — **defense in depth**, since gating and
  tools are separate layers (matches agent-stuff's `uv.ts` lesson).

**Session-lifecycle gates** (`session_before_switch` / `session_before_fork` →
`{ cancel: true }`):
- `confirm-destructive.ts` — confirm clear/switch/fork; distinguishes `reason === "new"`
  (clear) from `"resume"` (switch) and checks for unsaved work.
- `dirty-repo-guard.ts` — block switching/forking with uncommitted git changes (via
  `pi.exec("git", ["status","--porcelain"])`); **block by default headless**.
- `git-checkpoint.ts` — `git stash create` each `turn_start`, keyed by leaf entry id; offer
  restore on fork.

For perk: the lifecycle gates are the home for "commit before you leave this stage" hygiene
(erk's dirty-repo checks), and the fail-safe-headless rule (`!ctx.hasUI` ⇒ block) is exactly
right for the worker.

---

## 8. Subagents & spawning fresh sessions — the spawn contract

`extensions/subagent/` is the authoritative template for **isolated-context delegation** —
the model perk should follow for the read-only CI executor, a review sub-agent, and the
headless worker. Key mechanics:

- **Spawn `pi` as a subprocess in JSON mode**:
  `pi --mode json -p --no-session [--model …] [--tools …] [--append-system-prompt FILE] "Task: …"`.
  `--mode json` emits newline-delimited events on stdout; parse `message_end` (accumulate
  messages + `usage`) and `tool_result_end` to stream progress.
- **Agent definitions are markdown + frontmatter** (`name`, `description`, `tools`, `model`)
  discovered from `~/.pi/agent/agents/*.md` (user) and `.pi/agents/*.md` (project).
- **Security model**: default to **user-level agents only**; project-local agents are
  repo-controlled code and require `agentScope: "both"/"project"` **plus an interactive
  confirm** (`confirmProjectAgents`). perk must treat project-supplied agents/prompts as
  untrusted exactly this way.
- **Robustness**: write the system prompt to a temp file with mode `0o600` via
  `withFileMutationQueue`; resolve the `pi` invocation portably (`getPiInvocation`);
  **propagate abort** (`SIGTERM` then `SIGKILL` after 5s); **cap model-visible output**
  (50 KB/task) while keeping the full result in `details`; bound parallelism
  (max 8 tasks, 4 concurrent) with a concurrency-limited map.
- Single / parallel / chain modes, with `{previous}` placeholder for chaining.

`extensions/handoff.ts` is the in-process complement: `ctx.newSession({ parentSession,
withSession })` creates a **fresh focused session** seeded with a generated prompt — a
*lossless* alternative to compaction. This is the canonical "fresh context for the next
stage" move (perk's plan→implement transition), and `withSession` is where you do
post-switch UI work because the original `ctx` is stale after replacement.

---

## 9. Context, input transforms & compaction

- **`input` event** transforms the user's prompt before the turn. `inline-bash.ts` expands
  `!{cmd}`; `input-transform-streaming.ts` prepends `git diff --stat` *but skips the exec
  when `event.streamingBehavior === "steer"`* so mid-turn steering stays low-latency. perk's
  just-in-time context injection (diff/plan/branch) should respect `streamingBehavior`.
- **`context` event** filters/rewrites the messages the model sees — strip UI-only/control
  messages and stale mode context (`plan-mode`, and agent-stuff's `goal.ts`).
- **Custom compaction** (`custom-compaction.ts`): on `session_before_compact`, summarize
  with a **cheaper model** (Gemini Flash) using `serializeConversation(convertToLlm(...))`,
  return `{ compaction: { summary, firstKeptEntryId, tokensBefore } }`, and **fall back to
  default on empty/error**. Honor `signal` for cancel.
- **Threshold-triggered compaction** (`trigger-compact.ts`): watch `ctx.getContextUsage()`
  on `turn_end`, call `ctx.compact({ customInstructions, onComplete, onError })` when
  crossing a token threshold. perk's long objective/CI loops want this so they don't blow
  the window.

---

## 10. Secondary inference & helpers

For side-tasks (handoff prompts, summaries, classification), the pattern is consistent
(`handoff.ts`, `custom-compaction.ts`):

```ts
const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);   // or ctx.model
if (!auth.ok || !auth.apiKey) { /* degrade */ }
const res = await complete(model, { systemPrompt, messages }, { apiKey: auth.apiKey, headers: auth.headers, signal });
```

Useful exported helpers: `complete` (one-shot inference), `convertToLlm` /
`serializeConversation` (turn a branch into prompt text), `compact`, `getMarkdownTheme`,
`withFileMutationQueue`, `BorderedLoader`/`DynamicBorder`/pi-tui components, `Key.ctrlAlt`/
`Key.ctrlShift`. Always pass `signal` and **degrade gracefully** when auth/model is missing.

---

## 11. UI surfaces & headless discipline

- **Guard every rich-UI call with `ctx.hasUI`**; `ctx.ui.notify` is the safe baseline.
- Surfaces: `setStatus(key, text)` (footer, `status-line.ts`), `setWidget(key, lines)`
  (above/below editor, `plan-mode`/`widget-placement.ts`), `setFooter`/`setHeader`,
  `setWorkingMessage`/`setWorkingIndicator`, `setHiddenThinkingLabel`, `setEditorText`/
  `setEditorComponent` (`modal-editor.ts`), `confirm`/`select`/`editor`/`input`, and
  `ctx.ui.custom((tui, theme, keybindings, done) => component)` for full overlays.
- **Theme via `ctx.ui.theme.fg("accent", text)`**, never hardcoded colors.
- **`timed-confirm.ts`**: pass an `AbortSignal` to `confirm`/`select` to auto-dismiss —
  useful for a headless/worker timeout on an accidental prompt.

---

## 12. Resources, providers & packaging

- **`resources_discover` event** (`dynamic-resources/`) lets an extension contribute
  `skillPaths` / `promptPaths` / `themePaths` at runtime — how perk could surface
  project-config prompt-hooks or generated skills dynamically.
- **Extensions can ship their own `package.json` + deps** (`with-deps/`) with a `pi` field
  (`"extensions": ["./index.ts"]`); Pi resolves modules via jiti. Matches the agent-stuff
  packaging idiom.
- **Custom providers** via `pi.registerProvider` (`custom-provider-anthropic/`,
  `custom-provider-gitlab-duo/`) — out of perk's scope but the seam exists if a backend ever
  needs it.
- **Inter-extension bus**: `pi.events.emit/on` (`event-bus.ts`) — for coordinating perk's
  own multiple extensions (e.g. a mode extension and a status extension) without coupling.

---

## 13. Cross-cutting principles & gotchas

1. **One generic mode primitive**, parameterized — don't special-case plan vs CI
   (plan-mode + preset are the templates).
2. **Persist on every mutation; restore on `session_start` *and* `session_tree`.** Two
   channels: custom entries and tool-result `details` (forking-safe).
3. **Fail safe when headless** (`!ctx.hasUI` ⇒ block dangerous ops / interactive paths).
4. **Defense in depth**: gate at `tool_call` *and* inside `execute`.
5. **Isolate untrusted delegation** (project agents/prompts) behind scope flags + confirms.
6. **Cap model-visible output, keep full data in `details`.** (subagent's 50 KB rule.)
7. **Respect `streamingBehavior`** in `input` so steering stays fast.
8. **Degrade gracefully** on missing model/auth/platform; always pass `signal`.
9. **`StringEnum` for string enums; `executionMode: "sequential"` for shared-state tools.**
10. **`terminate: true`** to end cleanly on a terminal tool.
11. **After a session swap, rebind subscriptions and `bindExtensions`** (SDK runtime).

---

## 14. What perk takes directly

| Official example | perk use |
|---|---|
| `sdk/*` `createAgentSession` + `SessionManager` variants | the headless worker, the embedding/test harness, read-only sessions via `tools: […]` |
| `sdk/13-session-runtime.ts` | CLI stage transitions that replace the active session (resume/fork/import) |
| `plan-mode/` + `preset.ts` | the reusable mode/tool-gating primitive (plan-mode and read-only CI), snapshot/restore, `--plan`/`--preset` flags |
| `tool_call` block + `before_agent_start` inject + `context` strip | the structural enforcement of read-only modes |
| `subagent/` (`pi --mode json -p --no-session`) | the read-only CI executor, review sub-agent, headless worker spawn; the untrusted-project-agent security model |
| `handoff.ts` (`ctx.newSession`) | fresh-context stage transitions (plan→implement), the in-process cold door |
| `session_before_switch/fork` gates, `dirty-repo-guard` | commit-before-leaving-a-stage hygiene |
| tool-result `details` + restore on `session_tree` | the transient state tier, forking-safe; kills stale-marker bugs |
| `structured-output.ts` (`terminate`) | save-plan / emit-result terminal tools |
| `custom-compaction.ts` + `trigger-compact.ts` | keep long objective/CI loops within the context budget |
| `input-transform-streaming.ts` | just-in-time context injection that respects steering |
| `tool-override.ts` / `createBashTool` | write-policy / command-safety enforcement |
| `resources_discover` | dynamically surfacing project-config prompt-hooks |

Read `plan-mode/`, `preset.ts`, `subagent/`, `handoff.ts`, and the `sdk/` set before
implementing perk's modes (Phase 1), CI executor (Phase 2), and headless worker (Phase 3).
Together with [agent-stuff-best-practices.md](./agent-stuff-best-practices.md), these are the
concrete proof that everything in ROADMAP.md and [cli-vs-pi.md](./cli-vs-pi.md)
is built from primitives Pi already ships.
