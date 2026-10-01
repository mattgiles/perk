# Verification: Pi 0.99.2 as perk's minimum supported baseline

**Status:** dated evidence record (2026-10-01) — the upgrade verification behind moving perk's six
`@earendil-works/*` development pins from `0.87.0` to `0.99.2` and naming 0.99.2 the supported
minimum. The procedure is the 2026-09-29 assessment's verification matrix
(`docs/planning/pi-assessment-2026-09-29.md`); the pi-subagents half has its own record
([`pi-subagents-0.73.1-reverify.md`](pi-subagents-0.73.1-reverify.md)).

**Baseline choice:** 0.99.2, not 0.99.1 (owner decision). 0.99.2 (2026-09-30, npm `latest`)
carries the native-provider saved-credential fix (`fddc968` — an ancestor of `v0.99.2`, not of
`v0.99.1`), which this record's model-selection checks pin.

**Verdict: PENDING** — offline evidence complete; legs 1–6, 8 and 9 PASS in the session relaunched
on the 0.99.2 host. Leg 7 (the owner's `/pr-review-browser` on this change's PR) is the one leg
still open — it needs the PR to exist. Every leg must read PASS before merge; OWED is not an
admissible verdict here.

## Snapshot matrix

| Component | Version | Provenance |
|---|---|---|
| perk | 3.9.0 @ branch `plan-2641` (pre-merge) | this change |
| Pi dev pins | `@earendil-works/{pi-agent-core,pi-ai,pi-client,pi-coding-agent,pi-server,pi-tui}` 0.99.2; `typebox` 1.3.27; `typescript` 6.0.3 | `package.json` devDependencies |
| Root dist on disk | `node_modules/@earendil-works/pi-coding-agent/package.json` 0.99.2; nested `pi-coding-agent/node_modules/@earendil-works/{pi-ai,pi-agent-core,pi-tui,pi-mcp,pi-codemode,chord,pi-telemetry}` 0.99.2; nested + top-level `typebox` 1.3.27; jiti 2.7.0 | each package's own `package.json`, read after `npm install` (never `npm ls` alone) |
| `npm ls` agreement gate | every resolved copy of pi-coding-agent / pi-ai / pi-tui / pi-agent-core at 0.99.2, typebox at 1.3.27 | `npm ls @earendil-works/pi-coding-agent @earendil-works/pi-ai @earendil-works/pi-tui @earendil-works/pi-agent-core typebox` |
| Lockfile | new transitive `pi-mcp`, `pi-codemode`, `quickjs-wasi`, nested `openai`; `openai` 6.40.0 → 7.19.0 (pi-ai 0.99.2 pins it exactly); no incidental `"peer": true` / bin-path rewrites. openai 7's new optional peer edges (`@aws-sdk/credential-provider-node`, `@smithy/signature-v4`, `ws`) made npm re-resolve 21 AWS/Smithy/`ws` entries to newer patch releases; those were trimmed back to the base resolutions, which still satisfy every declared range and stay put under `npm install --package-lock-only` | `package-lock.json` diff against the base; `npm ci` + the `npm ls` gate after the trim |
| Host `pi` | 0.87.1 before the upgrade; 0.99.2 for the live ledger | `pi --version` (0.99.2 after the owner's `npm install -g` and the session relaunch) |
| `node` | v26.3.0 | `node --version` |
| pi-subagents | 0.73.1 (pinned) | `.pi/npm/node_modules/pi-subagents/package.json` |
| pi-web-access | 0.33.0 | `.pi/npm/node_modules/pi-web-access/package.json` |
| Plannotator | 0.27.21 | `.pi/npm/node_modules/@plannotator/pi-extension/package.json` |

## Offline evidence (0.99.2 dist)

- `npm run typecheck` (tsc 6.0.3, `skipLibCheck`) — green after three repairs: `fakeTool` gains
  `exposure: "direct"` (`ToolInfo.exposure` is required at 0.99); `tools/prose-map/selector.ts`'s
  `satisfies`-pinned `TOOL_FIELD_POLICIES` classifies the six new `ToolDefinition` keys
  (`outputSchema` as a schema; `exposure`/`annotations`/`defaultActive` non-prose;
  `namespace`/`prepareLoadout` prose so a governed tool adopting one surfaces instead of passing
  silently). tsc 6.0.3 parsed the TS7-emitted `.d.ts`; no `typescript` bump was needed.
- `npm run lint` — green.
- Full `node:test` suite — 3577 / 3577 pass, 0 skipped (the host-SDK census drift guard ran
  against the worktree's `.pi/npm`). One unplanned repair: `extension/pi/v1/childTaskRestore.test.ts`'s
  faux router keyed on `<conversation>`, but Pi 0.99 frames the split-turn-prefix summary with a
  `# Conversation` heading — the router now keys on the shared summarization system prompt.
- `extension/piAiCompatGuard.test.ts`, `extension/substrate/hostSdk.test.ts`,
  `extension/substrate/nativeSdkBridge.test.ts` (32/32, census guard live: `specifiers=8`,
  schema 2), `tests/test_native_sdk_bridge_parity.py`,
  `tests/test_packaging.py::test_pi_toolchain_pin_lockstep` — green.
- `tests/test_launch.py`, `tests/test_implement_cmd.py`, `tests/test_run_worker.py` — green.
- `tests/test_native_sdk_bridge_live.py` on the **0.87.1** host (pre-upgrade) — green after its
  per-source regex learned the version-pinned `npm:pi-subagents@0.73.1` source label; the 0.99.2
  host run is leg 1's live half.

**Fake-session vs real-runtime coverage (leg 5).** `extension/worker/stageExecution.test.ts` covers
abort and budget over a `FakeSession`; `extension/worker/stageExecutionE2e.test.ts` now drives both
on the REAL 0.99.2 runtime with the faux provider: an external abort fired on the first
`tool_outcome` → `aborted` / `external_abort`, monotonic `seq`, the scripted `submit` never runs;
a `maxTurns: 1` budget → `budget_exhausted` / `budget`, no tool past the cap executes, and
`outcome.budget.turns` is **cap + 1** (below). `extension/worker/sdkAdapter.test.ts` adds the
native-provider saved-credential case over a real `ModelRuntime` (synchronous availability +
`hasConfiguredAuth` + `resolveAuth` non-null; a credential-less control available only after the
async refresh; a saved non-first default `faux-2` honoured beside a no-default control selecting
`faux-1`).

## Dist facts re-verified (session construction)

Every `createAgentSession` / `createAgentSessionServices` / `createAgentSessionFromServices` /
`createAgentSessionRuntime` call site (`extension/worker/sdkAdapter.ts`,
`extension/testing/harness.ts`, `extension/vendor/btw/btw.ts`, `extension/pi/v1/contextEvidence.ts`)
needed no migration. Recorded in `docs/learned/pi/headless-session-drive.md` (restamped at 0.99.2):
`registerNativeProvider` → `markProvisionallyConfigured` (synchronous configured status for a
stored credential or configured key); SDK sessions load no CLI built-ins unless `extensionFactories`
supplies them; `findInitialModel` honours the saved default only when its provider
`hasConfiguredAuth`, then curated per-provider defaults, then the first available; the worker's
`resolveAuth` runs before extension resources load; `ModelRegistry` keeps its private `runtime`
field (btw's `liveModelRuntime` probe); `seedSessionManager`'s exhaustive role switch still
typechecks; `DefaultResourceLoaderOptions` is still not root-exported.

## Live-leg ledger

| Leg | Driver | Procedure | Observation | Verdict |
|---|---|---|---|---|
| 1 Cold + warm launch | implementer (+ owner toggles `/plan`) | `tests/test_native_sdk_bridge_live.py` on the 0.99.2 `pi`; the relaunched session (cold); `/perk-selfcheck`; `/plan` on → off | `tests/test_native_sdk_bridge_live.py` passes on the 0.99.2 PATH `pi` (`bridge=installed`, both consumer roots, both suppliers registering tools, no load failure); this implement session was relaunched cold on the 0.99.2 host with perk's tools, the read-write stage scoping and the borrowed suppliers live; the in-session `/perk-selfcheck` reads `ok; shared=ok; ambient=reached (append=5359c); agents=reached (files=1); bridge=installed`, `tools: 40 active / 65 registered`, both consumer roots, `specifiers=8`. Warm doors: the owner's `/plan` turned the read-only gate on (`run_scout_wave` offered — leg 6) and a second `/plan` turned it off, returning the session to the read-write implement stage (`edit`/`write` usable again — this record's own update was written after it). Leg 2's `/reload`, `/tree` and `perk resume` complete the warm-door evidence | PASS |
| 2 `/reload`, `/tree`, `/resume` | owner | `/reload` → `/perk-selfcheck` (bridge `reused`, `live=1`, gate unchanged); `/tree` away and back → `/perk-selfcheck`; quit + `perk resume` → `/perk-selfcheck` | All three selfchecks read summary `ok; … bridge=installed`, `tools: 40 active / 65 registered`, `binding-header-copies=2` and the same `perk contexts:` line (`perk:agent-scratch ×2 (850c) live=1; perk:binding-context ×1 (126c) live=1; perk:plan-adapter-plannotator ×1 live=0; perk:plan-context ×1 live=0`). `/reload` → bridge `installed (roots=2, specifiers=8, reused)` (branch 652). `/tree` to an earlier node and back to the leaf → bridge still `reused`, nothing re-injected (branch 658). Quit + `perk resume` → bridge `installed (roots=2, specifiers=8)` — a fresh process installs it again, so no `reused` — with the gate and live projection carried over (branch 665) | PASS |
| 3 Context edits + compaction | owner + implementer | `/compact`, one ordinary turn, `/perk-selfcheck`: guidance `live=1` while historical `×copies` ≥ 2 | Owner `/compact`, then one ordinary turn ("Continue", which re-injected the scratch block), then `/perk-selfcheck`: summary unchanged (`ok; … bridge=installed`); `branch: 644 entries; binding-header-copies=2`; `perk contexts: perk:agent-scratch ×2 (850c) live=1; perk:binding-context ×1 (126c) live=1; perk:plan-adapter-plannotator ×1 (1682c) live=0; perk:plan-context ×1 (1688c) live=0`. The guidance is projected once while its historical copies doubled, and the leg-6 `/plan` injections sit behind the compaction boundary at `live=0` — the projection, not the branch count, bounds what the model sees. `live=` is read before extension `context` filters (an upper bound — a filter can still drop a projected copy; agent-scratch's own filter keeps exactly one current copy), which is the reading this leg needs: at most one scratch block reaches the request | PASS |
| 4 `/btw` seed + summary | owner | two-turn `/btw` over main-context facts; "Inject summary into main chat" lands as a user turn | Owner `/btw`, two turns that both depended on the main chat: (1) leg 3's agent-scratch reading, answered `perk:agent-scratch ×2 (850c) live=1` with the pre-compaction `×1 (425c)` and the commit `f3546fdf` — seeded from the main context, not re-derived; (2) the remaining legs, answered with the ledger state at that point (passed 1, 2, 3, 5, 6, 8 + doctor; 4, 9, 7 open; the plan-door browser half pending confirmation). "Inject summary into main chat" landed in the main session as an ordinary user turn ("Summary of my BTW side conversation: …") that the main agent read on its next turn | PASS |
| 5 Worker success / cancel / budget | implementer | offline real-runtime e2e tier (above) | success, external abort and budget trip pass on the real 0.99.2 SDK runtime | PASS |
| 6 Report waves | owner + implementer | `/plan` on → `run_scout_wave` ≥ 2 briefs → N/N → `/plan` off; parent `bridge=installed` | Parent `/perk-selfcheck`: `bridge=installed`. Owner `/plan` on → `run_scout_wave` with two briefs (`unpinned-prose`, `exact-string-tests`, `perk.scout` on pi-subagents 0.73.1) → **2/2** validated reports, then `/plan` off. The workflow-completion notice capped its return preview ("truncated; full return value … `status.json` (`workflow.value`)") while the tool read both full reports from `status.json → workflow.value` — the 0.73.0 cap touches display text only. One finding acted on (a stale "unpinned engine" sentence in `docs/learned/workflow/mergeability-and-conflict-resolution.md`); the other confirmed no test asserts the bare `npm:pi-subagents` spec | PASS |
| 7 Browser-review lifecycle | owner | `/pr-review-browser` on this PR: readiness, wave marker, N/N lanes, `perk:*` annotation POST/DELETE, decision correlation | — | PENDING |
| 8 Suppliers + bridge identity | implementer | `/perk-selfcheck` (`bridge=installed`, both roots, `specifiers=8`, suppliers loaded, no load errors); `web_enable` → `fetch_content`; Plannotator commands listed | Headless `pi --approve --mode json -p /perk-selfcheck` on the 0.99.2 host: `selfcheck — 3.9.0: ok; shared=ok; ambient=reached (append=5359c); agents=reached (files=1); bridge=installed`; `native sdk bridge: installed (roots=2, specifiers=8)`, host `…/node_modules/@earendil-works/pi-coding-agent/dist/index.js`, roots `.pi/npm/node_modules/pi-subagents` + `pi-web-access`; per-source rows `npm:pi-subagents@0.73.1=3`, `npm:pi-web-access=1`, no `Failed to load extension`. In this session `web_enable` enabled `web_search`/`source_check`/`fetch_content`/`get_search_content`; `fetch_content` of `https://en.wikipedia.org/wiki/Node.js` returned the article (the first try, `https://example.com/`, was refused by pi-web-access's "content appears incomplete" heuristic — a too-short page, not a load fault). A `-e` command probe lists Plannotator's `plannotator-plan-mode`, `plannotator-review`, `plannotator-annotate`, `plannotator-last` and `skill:plannotator` | PASS |
| 9 Theme / TUI | owner | footer/status/widgets readable under the default theme | Owner inspection on the 0.99.2 host across this session (including the `/plan` toggle, the scout-wave run, `/compact`, `/reload`, `/tree`, `perk resume` and `/btw`): footer, status line and perk widgets all readable under the default theme — nothing clipped, illegible or mis-coloured | PASS |

## Pi 0.99 built-ins observed

The CLI registers `builtin:llama.cpp`, `builtin:codemode`, `builtin:tool-search` and
`builtin:mcp` (`dist/extensions/index.js::builtInExtensions`); `codemode` and `tool_search`
register with `defaultActive: false`. Observed live on the 0.99.2 host with a throwaway `pi -e`
probe in this checkout (`getAllTools()` against `getActiveTools()`): `codemode` and
`tool_search` are registered, **inactive**, exposure `model-only`, source `builtin`; the `/llama`
and `/mcp` commands are registered (source `builtin`). `/perk-selfcheck`'s census reported
`tools: 52 active / 65 registered` headless; its `builtin=4` per-source row counts Pi's active core
tools (`read`, `bash`, `edit`, `write`), since the built-in extensions share the `builtin` source
label. perk neither enables nor manages them in this
release; its read-only gate blocks them like any unlisted tool (tool-policy work is later nodes).

## Decisions

- **Baseline 0.99.2** (above); no Pi version gate is added — perk still names a documented minimum.
- **No tool-policy change** rides this baseline move (gating lists, perk-tool `exposure`,
  activation rules are later work).
- **Consumers pinned to pi-subagents 0.73.1** — the pi-subagents record's decision; it lands here
  because a fresh consumer install on 0.74.0 would break every perk wave on the new baseline.
- **The real-runtime budget count is recorded, not changed.** The watchdog trips on the cap's
  `turn_end`, but Pi's agent loop does not re-check the abort signal between turns: the next turn
  starts, its stream ends `aborted`, and that turn still emits a `turn_end` the counters record —
  so `RunOutcome.budget.turns` reads cap + 1 on the real runtime (a `FakeSession` stops at the cap).
  No tool past the cap executes. The e2e test pins the observed count.

## Falsified planning-time assumptions

- "Only `selfcheck.test.ts::fakeTool` breaks under tsc" — `tools/prose-map/selector.ts`'s
  exhaustive `ToolDefinition` policy registry also failed (by design: a new SDK field forces a
  policy decision).
- "The budget trip reports `turns` equal to the cap" — the real runtime reports cap + 1 (above).
- The full `node:test` suite was expected green after the type repairs; the split-turn-prefix
  summary's new `# Conversation` framing broke one faux router.

## Follow-ups

1. pi-subagents 0.74.0 migration (RPC `spawn` `workflowScript` → `script`, reserved
   `chain`/`tasks`, child project trust) — then move the pin and re-verify.
2. Full 0.99.2 re-audit of `docs/learned/pi/extension-api.md` and `docs/learned/pi/tui-surfaces.md`.
3. Footer routed-model display under Pi 0.99 virtual models (`session.routedModel`), if perk adopts
   them.
