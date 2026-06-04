# Phase 3 · Turn 3 — selfcheck as a session-wiring verifier (+ `run_mode`)

GitHub plan **#64**. Two new Pi APIs (shipped in `@earendil-works/pi-coding-agent` **0.78.1**) map
cleanly onto perk's two-plane model:

- **`ctx.getSystemPromptOptions()`** (on a *command* context) exposes the live
  `BuildSystemPromptOptions` — including `appendSystemPrompt` (the joined `.pi/APPEND_SYSTEM.md`
  content) and `contextFiles` (the loaded `AGENTS.md` files as `{ path, content }`).
- **`ctx.mode`** (`tui`/`rpc`/`json`/`print`) on every context — finer than perk's binary
  `ctx.hasUI`.

perk converges two pieces of session context onto disk and *trusts* Pi to splice them into the
prompt, but had no way to confirm the splice actually happened — `perk doctor` only checks disk.
This turn closes that blind spot: **doctor checks disk; `/perk-selfcheck` checks the prompt.**

## Decisions (locked)

- **B (centerpiece) — turn the liveness-only `/perk-selfcheck` into a session-wiring verifier.**
  New `extension/selfcheck.ts` with pure probes — `readAmbientIndex`, `ambientIndexProbe`,
  `managedAgentsProbe`, `buildSelfcheckReport` — wired via `registerSelfcheck(pi, {version,
  sharedOk})`. The command handler (command context → has `getSystemPromptOptions()`) confirms the
  on-disk ambient index reached `appendSystemPrompt` (trimmed-substring probe — Pi loads it
  verbatim) and the `<!-- BEGIN perk managed -->` block reached `contextFiles`. Logs only derived
  booleans/counts — never the raw prompt text (the options expose the whole system prompt).
- **A (complement) — record `ctx.mode` as `run_mode`** in the `.pi/workflow/.perk-t3.json`
  diagnostics sentinel, distinct from the workflow `mode` (read-only/read-write) that drives tool
  gating. `run_mode` is observability `hasUI` (a binary) can't express; written from `ctx.mode` on
  both `session_start` and `session_tree`.
- **Bump Pi 0.78.0 → 0.78.1** (`pi-ai` + `pi-coding-agent` in lockstep) — the precondition for both
  APIs. `ExtensionMode` is only re-exported from a deep package path, so the harness restates the
  union locally rather than importing it.
- **Harness gains a `mode?` forward to `bindExtensions`** (it otherwise pins Pi's default `print`),
  plus `Sentinel.run_mode` and `getSystemPromptOptions`/`mode` on the synthesized command/tool ctx
  stubs.
- **Rejected (documented so they aren't re-litigated):** TUI-only `custom()` component guards via
  `mode === "tui"` (perk renders no TUI components); a `decideCiScope` tui-vs-rpc refinement
  (`hasUI` already captures the gate that matters); authoring-context dedup via `skills` (the
  `stage` field already disambiguates plan vs objective-author).

## Findings (verified against Pi 0.78.1 source)

- `getSystemPromptOptions()` lives on `ExtensionCommandContext` only (not the plain
  `ExtensionContext`), returning `agent-session`'s `_baseSystemPromptOptions`. `appendSystemPrompt`
  is the loader's `getAppendSystemPrompt()` joined with `\n\n` (so absent ⇒ `undefined`);
  `contextFiles` is `getAgentsFiles().agentsFiles`. The base options are populated by the time
  `bindExtensions` resolves (tool registration triggers `setActiveToolsByName` →
  `_rebuildSystemPrompt`).
- `ctx.mode` defaults to `print`; `bindExtensions({ mode })` sets `_extensionMode`, surfaced via
  `setUIContext(uiContext, mode)`.
- The `<!-- BEGIN perk managed -->` marker is now **cross-plane**: written by `perk init`
  (`perk/init.py` `AGENTS_BEGIN`), read by `extension/selfcheck.ts` (`MANAGED_AGENTS_MARKER`).
  Recorded as a contract in `shared/contracts.md` §8.7.

## Outcomes (what actually landed)

- `extension/selfcheck.ts` (new) + `extension/selfcheck.test.ts` (18 cases: pure probe/report twins
  + two live integrations driving a real bound session through `getSystemPromptOptions()`, + two
  `run_mode` sentinel cases). `extension/index.ts` swaps the inline command for
  `registerSelfcheck`, and `writeT3Sentinel` gains a `run_mode` arg fed from `ctx.mode` on both
  lifecycle handlers.
- `extension/testing/harness.ts`: `mode?` forward, `Sentinel.run_mode`, ctx stubs, local
  `ExtensionMode` alias.
- `shared/contracts.md` §8.7 documents the cross-plane markers + the `run_mode` sentinel field.
- `package.json` / `package-lock.json` bumped to Pi 0.78.1.
- Full suite green: 195 node:test cases, 392 pytest, lint + typecheck clean.

No deviations from plan #64's intent. The plan's full markdown was never persisted to GitHub (the
authoring session lacked the `plan_save` tool); this turn reconstructs it faithfully from the saved
summary, verified line-by-line against Pi 0.78.1's source.
