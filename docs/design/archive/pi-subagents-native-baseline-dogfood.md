# Baseline: pi-subagents 0.65.1 (the native-session transition) on the pinned dev toolchain

**Status:** dated evidence record (2026-09) — the tested compatibility baseline (R1) for perk's
unpinned `pi-subagents` integration, established by the compat-objective's node 1.1. It records
the re-verified upstream mechanics, the modernized doctor tripwire, and the FIRST live run of
`just subagents-smoke` — whose honest verdict is a **FAIL with a precise root cause**: at this
baseline pair, a report wave's lane children cannot launch. The baseline compensates for the
deliberate no-pin decision (owner-affirmed in the objective): pi-subagents stays unpinned, and
this record + the re-verify procedure (`docs/developers/pi-subagents-reverify.md`) are the
compensating control.

> **2026-09-05 scoped follow-up:** the repo-local five-package Pi 0.85.1 composition now
> passes host-alias resolution and a real background smoke. See
> [native-streaming dogfood](pi-subagents-native-streaming-dogfood.md) for that evidence and the
> separate live-streaming leg status. This does not rewrite the failing run below or certify
> global/consumer hosts.

## The baseline matrix

| Component | Version | Provenance |
|---|---|---|
| perk | 3.2.0 @ commit `0d6da34772da6e1010d1badb3ef4273bdfc11a3c` (clean tree) | the smoke-run SHA — the implementation this record trails |
| Pi (pinned dev toolchain) | `@earendil-works/pi-coding-agent` 0.84.1 | `package.json` devDependencies (`node_modules/.bin/pi`) |
| pi-subagents (installed, unpinned) | 0.65.1 | `.pi/npm/node_modules/pi-subagents` (pi lazy-install) |
| Date | 2026-09 | |

## The live smoke run (verbatim facts)

`just subagents-smoke` from the clean committed tree at the SHA above (a headless
`pi --mode json -p` session in the repo root; env-leak guard
`env_remove=("PERK_RUN_ID", "PI_SESSION_FILE")` through the `proc.run_captured` seam):

```
subagents-smoke: FAIL
perk 3.2.0 @ 0d6da34772da6e1010d1badb3ef4273bdfc11a3c
pi 0.84.1 (pinned dev toolchain) · pi-subagents 0.65.1 (installed, unpinned)
observed 1 explore_objective_node execution(s) · pi exit 0
failure: the explore_objective_node execution did not return a successful report (tool error or non-ok details)
```

What the captured event stream shows, step by step:

- The probe session made exactly ONE `explore_objective_node` call (the smoke harness's
  spawn/evaluate pipeline works end-to-end; tool gating stayed fail-open in the bare session as
  expected).
- The wave LAUNCHED: the RPC spawn succeeded, the async **workflow ran in-process** and settled
  (receipt identities: workflow run `ee4fc469-4ee3-42e2-b509-b665af0731ea`, asyncDir under
  `…/async-subagent-runs/ee4fc469-…`, `state: "complete"`,
  `children: [{key: "workflow", success: false}]`).
- The lane CHILD failed to launch. Verbatim engine error (via the wave's normalized
  `lane-failed` detail):

  > Failed to start async run 'a806efb1-03f4-4ad0-bdb5-231f450dc060': Background children
  > require pi installed as the npm package (@earendil-works/pi-coding-agent) with its
  > dependencies; …/node_modules/@earendil-works/pi-coding-agent does not provide
  > @earendil-works/chord, @earendil-works/chord/context, @earendil-works/pi-server,
  > @earendil-works/pi-server/unix, so the async runner cannot create child sessions. A
  > standalone pi binary cannot run background children.

- The failure normalized LOUDLY exactly as the report-wave module promises: `details.ok: false`,
  `error_type: "lane-failed"`, the receipt retained — no silent fallback, no phantom report.

## The headline finding: lane children cannot launch at this pair

Root cause, source-verified in the installed 0.65.1 tree:

1. **v0.65.1's omitted-child-async semantics route wave lane children to the BACKGROUND
   runner.** perk's renderer deliberately does not set child `async`
   (`extension/waves/transport.ts` — the explicit-mode policy is Phase 3's decision record);
   `asyncOmitted` in `src/runs/foreground/subagent-executor.ts` honors the engine default —
   globally background — while the workflow awaits (`workflowAwaitAsync: true`).
2. **The v0.65.0 native-session background runner requires host peer packages resolvable from
   the running pi's package root** (`resolveHostPeerAliases` in
   `src/runs/background/runner-aliases.ts`): among them `@earendil-works/chord` and
   `@earendil-works/pi-server`.
3. **Neither pi install on the baseline machine provides them.** Running the installed
   resolver (`resolveHostPeerAliases`) against each pi package root:
   - pinned dev Pi 0.84.1 (`node_modules/@earendil-works/pi-coding-agent`): missing
     `@earendil-works/chord`, `@earendil-works/chord/context`, `@earendil-works/pi-server`,
     `@earendil-works/pi-server/unix`;
   - the operator's global Pi 0.85.1: missing `@earendil-works/pi-server`,
     `@earendil-works/pi-server/unix`, `@earendil-works/pi-client/unix` (the upstream
     supplemental fallback covers Pi **0.85.0 exactly** — "Pi 0.85.0 omitted this runtime
     dependency" — and does not engage at 0.85.1).

Consequence: **every perk report wave is live-broken at pi-subagents 0.65.1 on this machine's
pi installs** — not just the pinned smoke pair — because every wave lane child takes the
background path. The 2026-08-10 streaming-doors dogfood
(`docs/design/archive/streaming-doors-dogfood.md`) ran on the pre-native-session engine
generation and remains the bridge/streaming live evidence for THAT generation; it does not
certify 0.65.1.

Repair ownership (deliberately NOT this node's): Phase 2/3 of the compat objective decide the
child-mode policy (an explicit `async: false` on lane children would route them onto the
in-process foreground path) and/or a deliberate Pi pin bump to a version whose npm package
provides the host peers. This node's boundary — no transport spawn-param changes, no pin —
stands; the finding is recorded, not patched around.

## Re-verified findings (source-read against the installed 0.65.1 tree at implementation time)

The four probe divergences from the 0.52.1-era table, and their replacements (all confirmed by
the modernized `_SUBAGENT_COMPAT_PROBES`, which reports `ok` against the real installed tree):

1. `"subagent_wait"` has zero occurrences in `src/runs/background/wait-tool.ts` — the wait tool
   is `bg_wait` (scoped to work *without* native completion notification; window expiry is a
   non-error `window_elapsed`). perk deliberately does NOT adopt it; the wait tool is
   deliberately unprobed, and the new "async completion notification wake" row probes
   `"subagent-notify"`/`triggerTurn` in `src/runs/background/notify.ts` instead — the native
   completion wake Phase 2's relay repair rides (per-item `triggerTurn` default-true).
2. `"subagent_supervisor_request"` moved out of `src/intercom/native-supervisor-channel.ts` —
   it lives in `src/intercom/supervisor-ui.ts` as `SUPERVISOR_REQUEST_MESSAGE_TYPE`; the
   channel imports the constant and still injects with `triggerTurn: true` on every request
   (the per-batch wake).
3. `src/runs/shared/pi-args.ts` is deleted and the
   `PI_SUBAGENT_ORCHESTRATOR_SESSION_ID`/`PI_SUBAGENT_SUPERVISOR_CHANNEL_DIR` env stamps have
   zero occurrences — replaced by typed child runtime config (`orchestratorSessionId` +
   `supervisorChannelDir` in `src/runs/shared/child-runtime-config.ts`, stamped by
   `child-launch.ts`).
4. `async: params.async ?? false` is gone from `src/workflows/scripted-workflow.ts` — the
   omitted-async semantics live in `src/runs/foreground/subagent-executor.ts`
   (`asyncOmitted` → `workflowAwaitAsync: true`; mode honors the globally-background engine
   default). See the headline finding above for the live consequence.

Also re-verified:

- **Intercom bridge tool delivery** (`src/intercom/intercom-bridge.ts`):
  `resolveIntercomBridgeMode` defaults to `"always"`; `applyIntercomBridgeToAgent` appends
  `["contact_supervisor"]` to an explicit agent tool allowlist plus the bridge instruction to
  the system prompt — confirming perk's read-only reviewer defs receive `contact_supervisor`
  via the bridge without def edits. The prior live streaming observation (the
  objective-authoring draft-review wave; `streaming-doors-dogfood.md`) is the bridge's live
  evidence — Phase 2 owns the streaming live validation on the new engine generation.
- **Collection channel unchanged**: `src/extension/rpc.ts` still serves
  `subagents:rpc:v1:request/ready/reply`, and ping still advertises the async-complete channel
  (`SUBAGENT_ASYNC_COMPLETE_EVENT = "subagent:async-complete"` in `src/shared/types.ts`) — the
  advertised-not-pinned convention stands. The smoke's successful wave launch + in-process
  workflow settle exercised this channel live.
- **"Async workflows run in-process"** re-verified at the `pid: process.pid` site in
  `src/runs/foreground/subagent-executor.ts`: the literal sits on the `mode: "workflow"`
  running-status record — the workflow host is still the parent pi process (the smoke's
  workflow receipt confirms it live). The learned-doc claim needed no amendment; the CHILD
  launch policy beneath it changed (the headline finding).
- `validateWorkflowScript` is exported from `src/workflows/scripted-workflow.ts` and accepts
  perk's representative rendered wave script — now continuously verified by the doctor
  `subagent-compat` behavior arm over `shared/subagents/representative-wave-script.js`
  (jiti-loaded from the installed package; skip-note degradation when unevaluable).

## Standing decisions this record compensates for

- **pi-subagents stays unpinned** (owner-affirmed). The compensating control is: the doctor
  tripwire (substring probes + the behavior arm, `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION =
  "0.65.1"`), this recorded baseline, and the re-verify procedure
  (`docs/developers/pi-subagents-reverify.md`). A future pin is a separate one-line decision
  this record makes trivial — and the headline finding names exactly what the pin (or the
  Phase-2/3 repair) must satisfy.
- The smoke is opt-in and dev-only (`just subagents-smoke`; never part of `just ci`); its FAIL
  exit is the honest verdict, not a gate.
