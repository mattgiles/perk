---
title: Pi 0.78.x extension API — getSystemPromptOptions, ctx.mode, injected-message persistence
read_when: You need live system-prompt inputs in an extension, are choosing a command vs lifecycle-event handler, importing a Pi type, or reasoning about whether an injected custom message persists.
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
