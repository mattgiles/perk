# Re-verify: pi-subagents 0.68.0 — `fallbackModels` rejected, progress updates discarded, the host-builtin census fixed

**Status:** dated evidence record (2026-09-15) — the guidance-baseline re-verify that moved
`_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` from `0.65.1` to `0.68.0` and retired perk's provisional
finding-streaming protocol. The template is
[`pi-subagents-native-baseline-dogfood.md`](pi-subagents-native-baseline-dogfood.md); the
procedure is `docs/developers/pi-subagents-reverify.md`.

## The matrix

| Component | Version | Provenance |
|---|---|---|
| perk | 3.3.0 @ branch `plan-2451` (this change, pre-merge) | the implementation this record trails |
| Pi (pinned dev toolchain) | `@earendil-works/pi-coding-agent` 0.85.1 | `package.json` devDependencies |
| pi-subagents (installed, unpinned) | 0.68.0 (npm latest) | `.pi/npm/node_modules/pi-subagents` — `npm install pi-subagents@0.68.0` in the worktree's `.pi/npm` (the lazy-install root); the package ships its TypeScript sources (`pi.extensions: ["./index.ts"]`), so every anchor below is a `src/**/*.ts` path read in place |
| Previous baseline | 0.65.1 (last source re-read 0.67.0) | `docs/learned/pi/subagents.md` § Sources before this pass |

## Source facts (file/function anchors, verified in the installed 0.68.0)

- **`fallbackModels` rejected at load** — `src/agents/agents.ts::loadAgentsFromDefinitionFiles`:
  `if (frontmatter.fallbackModels !== undefined) throw new Error(\`Agent '${filePath}' uses
  removed frontmatter field 'fallbackModels'. Configure one model instead.\`)`. Fires on key
  presence; the throw aborts the whole load, so every def in the discovery set fails and every
  wave is 0/N. No replacement field (same-launch model switching removed upstream).
- **Parent-side `progress_update` discarded** — `src/intercom/native-supervisor-channel.ts::poll`:
  `if (!request.expectsReply) { /* Progress is already visible through child activity; do not
  inject a parent message or trigger a parent model turn. */ removeRequestFile(…); continue; }`.
  The child side still sets `expectsReply = params.reason !== "progress_update"` and returns
  "queued". No opt-in.
- **Per-launch bridge override** — `SubagentParamsLike.intercomBridge?: IntercomBridgeConfig`
  ("It replaces the global config for this launch only", `src/runs/foreground/subagent-executor.ts`);
  `resolveIntercomBridge({config, override: params.intercomBridge, …})` at both the direct spawn
  site and the RPC-spawn site; `prepareWorkflowLaunchParams` resolves
  `childParams.intercomBridge ?? workflowDefaults.intercomBridge` for every workflow child. The
  RPC `SubagentParams` TypeBox schema (`src/extension/schemas.ts`) does not set
  `additionalProperties: false`, so the field passes `assertSubagentParams`;
  `normalizePublicSubagentExecution` (`src/extension/public-execution.ts`) strips only
  resource/permit fields. `{mode: "off"}` → `resolveIntercomBridge` returns `active: false` →
  no `contact_supervisor`, no appended `DEFAULT_INTERCOM_BRIDGE_TEMPLATE`.
- **Routine child completions no longer wake the parent** —
  `src/runs/background/notify.ts::incrementalChildCompletionTriggersTurn`: `if
  (child.workflowRunning && child.outcome === "completed") return false;` — failed/paused/stopped
  children and the workflow completion still wake.
- **Host-builtin census counts wrapped core slots** — `src/runs/shared/child-tool-plan.ts`
  (`getHostBuiltinToolNames`): `return source === "builtin" || PI_BUILTIN_TOOL_NAMES.has(tool.name)`
  (0.67.x: `source === "builtin" || (source === "auto" && PI_BUILTIN_TOOL_NAMES.has(name))`).
  The intersection itself still runs; only the classification changed.
- **`PI_SUBAGENT_CACHE_RETENTION`** — `src/shared/child-cache-retention.ts`, documented in the
  package's `docs/configuration.md`: environment-only child cache-retention tier overriding
  `PI_CACHE_RETENTION` for children.

## Decisions

- **Streaming retired end to end.** Every wave spawns with `intercomBridge: {mode: "off"}`
  (`extension/waves/transport.ts::WAVE_INTERCOM_BRIDGE`, beside `WAVE_ACCEPTANCE`); the reviewer
  defs lose their streaming step and `streamed` field; both report schemas drop `streamed`; the
  collect cores drop the `streamed:false` disclosures; `SUBAGENT_CHILD_TOOLS` =
  `["structured_output"]`; one shared door-prompt partial (`prompts/common/review-wave-yield.md`
  — the first real `{% include %}` consumer) carries the completion-only yield/collect
  discipline for the seven review doors.
- **The early-decision window** the retirement widens is closed by policy + a code-owned marker:
  `push_annotations`'s reserved `perk:wave` source (`replaceWaveStatus`; the `wave` slug refused
  to the model) is written by both tool pairs at launch (running / failed) and at collect (cleared
  / incomplete); the door-open notice says to decide after the findings arrive; an early human
  decision stays authoritative and forgoes the findings.
- **`push_annotations` slimmed** to final pushes + hold/retry: the cross-source promotion
  machinery (`alternates`, `pendingClearSources`, `unstableSources`) is deleted; a post-readiness
  network failure retries in-call over `HELD_RETRY_DELAYS_MS = [1s, 3s, 6s]` and, exhausted,
  holds with a present-in-session result text.
- **`subagent-host-tools` range closed** at `("0.67.0", "0.68.0")` with two distinguishable `ok`
  arms; **`FFF_MODE_ENV` kept** (harmless additive default, protective on 0.67.x hosts).
- **`subagent-bridge-config` retired** (streaming-only); the stale `subagent-engine` detail fixed.
- **Declined after review:** a `subagent-def-compat` probe (the engine's load error already names
  file + field; `subagent-agents` reconverges perk's defs), a `subagent-pi-version` probe (PATH `pi`
  is not the engine's host resolution), and a `PI_SUBAGENT_CACHE_RETENTION` launch default (a
  `perk-expert` recipe instead).

## The live leg

Run from the implement session in this worktree after upgrading the worktree-local `.pi/npm` to
0.68.0.

**Doctor half — PASS.** `uv run perk doctor --verbose` (package group, verbatim rows):

```
⚠ subagent-compat: pi-subagents 0.68.0 installed — perk's guidance was verified against 0.65.1 …
✓ subagent-host-tools: pi-subagents 0.68.0 counts wrapped core slots as host builtins — a pi-fff
  override of grep/find no longer fails review/scout lanes — report-only — the package stays unpinned
✓ ponytail-compat: Ponytail review skills compatible …
✓ subagent-agents: subagent-agents converged
```

No `subagent-bridge-config` row (retired). The `subagent-compat` warn is the pre-bump state;
after the stamp moved it reads `ok`.

**Browser-door half — NOT EXERCISED in this pass.** The `/plan-review-browser` and
`/pr-review-browser` waves are `hasUI`-gated human-in-the-loop doors (the plannotator decision is
the human's), so the implementing agent could not drive them. The owner elected to move the stamp
on the source re-read + the doctor half rather than block submission; the completion-only
mechanics are pinned offline (every wave spawn's `intercomBridge` in the adapter-contract /
fake-RPC suites, the marker push/replace at launch and collect in the tool-pair tests, the def ↔
schema lockstep, the door-prompt pins). **Residual:** the first live 0.68.0 browser wave — marker
visible at launch, cleared at collect, N/N final annotations after `collect_*` — is still owed;
run it from a read-write session on a 0.68.0 host and append the outcome here. A FAIL there is a
new re-verify pass, not a stamp rollback by itself.

## Falsified planning-time assumption

The plan assumed the published package is compiled JS (`scripts/build-package.mjs` publishing
`src/**/*.js`) and that the source re-read would have to happen against the upstream tag. The
installed 0.68.0 ships `src/**/*.ts` with `pi.extensions: ["./index.ts"]`; the reverify how-to
was corrected to read in place.
