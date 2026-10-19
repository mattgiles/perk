# Record: the supplier lifecycle on pi-subagents 0.76.1 — offline evidence and deferred live legs

**Status:** offline evidence + deferred live legs. Authored 2026-10-19 (UTC) on branch `plan-2719`
(base `6550120b`). It implements plan #2719 (Objective #2707, node 2.2): perk's report-wave and
foreground writer transports, last re-verified against pi-subagents 0.75.0's lifecycle, are pinned
against the four lifecycle facts 0.76.1 changed — the **awaited-child completion event**, the
**parent wake prompt**, **queued-completion liveness across a same-session `/reload`**, and
**capacity/stop semantics** — and perk's own timeout/cancel diagnostics are narrowed to what the
engine actually answers. The precedents are [`pi-1.1.0-characterization.md`](pi-1.1.0-characterization.md)
§ "2.2 — supplier lifecycle" (T10d, T11, S2, S3, S11) and
[`pi-subagents-descendant-ceilings.md`](pi-subagents-descendant-ceilings.md) (node 2.1; its
instrument shape is what the deferred legs below reuse).

**Verdict: every node clause has offline evidence in the framework suites; no live measurement was
taken.** Per the operator decision recorded at planning (2026-10-19: live legs are "expensive in
time and effort"), every live leg the node implies is specified below as a protocol with pass
criteria and marked **DEFERRED → 7.1**. Each deferral cell is a deferral, never a PASS or FAIL. The
terminal-proof and stop-outcome projections are therefore **source-derived at 0.76.1** until W7a
runs.

| Clause | Offline | Source-derived | Live |
| --- | --- | --- | --- |
| Awaited-child events before the spawn reply / while siblings run | three `reportWaveRpc` tests over the exact payload | `emitWorkflowAwaitedChildComplete` | W1 — DEFERRED → 7.1 |
| Lazy loading | — | `started` precedes the lazy import; `ping` is import-free | W2 — DEFERRED → 7.1 |
| Duplicate responders on every method | ghost tests on spawn/stop/status | pi's two-phase trust load | W3 — DEFERRED → 7.1 |
| Same-version reload with queued completions | activation + late-event isolation, the `no_wave` clause | queued-wake retention, post-reload wake | W4 — DEFERRED → 7.1 |
| Required extension/skill delivery | existing pins restated (no new mechanism) | — | W5 (trust rows) — DEFERRED → 7.1 |
| Parent wake-prompt preservation | context chain in both gate states; task restore | `parent-wake.js` | (T10d measured the sequence) |
| Structured failures | failed child + aggregate row; typed stop refusal; decorated writer terminals | — | — |
| Partial settlement | existing pins; the stopped-workflow pin | — | W6 — DEFERRED → 7.1 |
| Stop after a delivered paused result | stopped-completion pin | the tool action's seal/refuse | W7b — DEFERRED → 7.1 |
| perk's own stop (acknowledged/refused + proof) | end to end over the fake RPC | `rpc.js::stopAsyncRun`, `workflow-terminal-proof.js` | W7a — DEFERRED → 7.1 |
| Unknown termination stays unknown; a freed slot is not proof | wording + source pins + decorated terminals | `abandonedSlotReleaseAfterMs` | — |

## Versions

| Component | Version |
| --- | --- |
| PATH `pi` (`pi --version`) | `1.1.0` |
| Root SDK (`node_modules/@earendil-works/pi-coding-agent/package.json`) | `1.1.0` |
| Worktree engine (`.pi/npm/node_modules/pi-subagents/package.json`) | `0.76.1` |
| Node | `v26.3.0` |

No later pi-subagents release was substituted; every anchor below was read in the installed
compiled sources (`.pi/npm/node_modules/pi-subagents/src/**/*.js`).

## The source-derived 0.76.1 facts

- **The awaited-child completion** (`src/runs/foreground/subagent-executor.js::emitWorkflowAwaitedChildComplete`,
  reached from `waitForWorkflowAsyncSingleResult` → `importWorkflowAwaitedChildResult`). It emits
  on `subagent:async-complete` — the channel `ping` advertises as `events.asyncComplete`, the one
  the wave transport subscribes — the payload `{id: <childRunId>, runId: <childRunId>, sessionId,
  completionOwnerId, asyncDir: <the CHILD's run dir>, agent, mode: "single", state: "complete" |
  "failed" | "stopped", success, timestamp, triggerTurn: false, awaitedByWorkflow: true,
  parentWorkflowRunId}`. The child's run dir is a sibling of the workflow's under the async root,
  so a child event's `id`/`asyncDir` never equals the workflow handle. The workflow's own
  completion is a separate event carrying the workflow's `id`/`asyncDir`, `results[]` and
  `workflowChildren`.
- **The notifier** (`src/runs/background/notify.js`). The async-complete subscriber returns early
  on `data.awaitedByWorkflow === true`; `incrementalChildCompletionTriggersTurn` keeps a completed
  child silent while its workflow runs; failed/paused/stopped children and the workflow completion
  wake. Queued wakes live in `globalThis[Symbol.for("pi-subagents.queued-completion-wakes.v2")]` (a
  `WeakMap` keyed by `SessionManager`); `bindSession` re-adopts them only for the same session id;
  `sessionShutdown(reason)` clears them unless `reason === "reload"`; `hasPendingDelivery()` counts
  them as host liveness. Result delivery is ownership-checked
  (`result-delivery-ownership.js::owns`), so a session switch never receives the previous session's
  notice.
- **The wake** (`src/shared/parent-wake.js`). `PARENT_WAKE_TEXT = "Subagent updates above."`; for a
  `triggerTurn: true` notice on an IDLE parent, `createParentWake.sendMessage` appends the notice
  with `triggerTurn: false` and then `pi.sendUserMessage(PARENT_WAKE_TEXT, {deliverAs: "steer"})`,
  once per 10 s reservation (`Symbol.for("pi-subagents.parent-wake-reservations.v1")`,
  reload-retained). A busy parent gets the notice as an ordinary queued message.
  `src/extension/index.js` binds both on `session_start` and clears on non-reload
  `session_shutdown`.
- **The RPC `stop`** (`src/extension/rpc.js::stopAsyncRun`, its own implementation). For a running
  in-process async workflow it stops the stoppable children and aborts the workflow controller
  (`"Workflow stopped by RPC."`), replying `{runId, asyncDir, previousState, state: "stopping",
  message: "Stop requested for async run <id>."}` — an in-memory request, never exit proof and never
  durable (this arm returns before the `deliverStopRequest` path that writes a control request for
  non-workflow runs). Refusals are typed
  `SubagentRpcError`s: `not_found` (`Async run not found or already completed; stop requires a live
  async run directory.`, a missing status file, or a run outside the active session),
  `invalid_state` (`Workflow <id> has no live run controller available to stop.` — controllers live
  in-process, so a persisted run dir cannot restore them after a reload; `Async run <id> is
  <state>; stop only supports running async runs.`), `execution_failed`.
- **The model-facing stop action is different** (`src/runs/foreground/async-stop-action.js::stopAsyncRun`
  → `sealPausedRun`, reached through the `subagent` tool / Fleet, never through perk's RPC). A
  paused whole run is sealed only against an observed, identity-matching process-terminal proof;
  otherwise `Stop request persisted for paused async run <id>, but terminal proof is not ready
  (<reason>). Retry stop after runner shutdown is observed.`
- **The `status` terminal proof** (`src/runs/background/run-status.js` sets
  `details.workflowTerminalProof` from `workflow-terminal-proof.js::readWorkflowTerminalProof`).
  `{version: 1, kind: "workflow", runId, state: "observed", dispatchClosed: true, observedAt,
  children[]}` only after dispatch closed AND every async child has resolved process evidence (an
  observed runner exit in `process-terminal.json`, or a recorded never-started launch failure);
  otherwise `{…, state: "pending" | "unknown", dispatchClosed, reason}` — e.g. `"Workflow dispatch
  is still open."` (pending, the immediate post-stop shape), `"async workflow child <key> is still
  running"`, `"… process-terminal proof is missing"`. The RPC reply is `{text, details, isError?,
  fleet, asyncSnapshot}`; an unknown id is the tool error `Async run not found. Provide id or dir.`
  wrapped as `success: false`, `execution_failed`. `status` needs session context (a context-less
  responder answers `no_active_session`).
- **Capacity** (`src/extension/config.js`). `capacity.abandonedSlotReleaseAfterMs` frees a slot
  after a dead PID + age even with `processProof: "unknown"` — capacity is never termination.
- **Spawn rejections** (`rpc.js::spawnParams`). `workflowScript` → `RPC spawn workflowScript was
  removed; pass inline script text as script.`; `workflowScriptPath` → `RPC spawn workflowScriptPath
  was removed; pass the file as workflow: "./path/to/script.js".` — both `invalid_params`, both
  `Object.hasOwn`.
- **Lazy loading.** The extension registers the RPC bridge at load; `beginAdvertisement` runs at
  `session_start`; `spawn`/delegation await `waitForAdvertisement()` then the executor import;
  `ping` needs neither. The delegation bridge (`src/slash/prompt-template-bridge.js`) emits the
  `started` tuple BEFORE `executeRequest`, so perk's 5 s `START_ACK_MS` never races the lazy
  import; the 30 s `WAVE_RPC_REPLY_TIMEOUT_MS` bounds the first spawn.

## What perk changed

- `extension/waves/transport.ts`: `WaveAdapter.stop` returns `WaveStopOutcome` (acknowledged, or
  refused with the engine's reason — never a throw); `WaveAdapter.terminalProof` is ONE `status`
  query after perk's own stop, projected as `WaveTerminationProof` (`observed` / `pending` /
  `unknown` / `unavailable`). The `timeout`/`cancelled` failure detail renders both facts
  (`stop requested` | `stop refused (<reason>)`; `child termination observed (engine
  process-terminal proof)` | `child termination unconfirmed (<state>: <reason>)`) and the receipt
  carries `termination: {stop, proof}`. "run stopped best-effort" left the vocabulary; the reason
  literals are unchanged.
- `extension/waves/rpcAdapter.ts`: `stop` maps every rejection to `acknowledged: false`;
  `narrowTerminalProof` + `terminalProof` over `status {id}`; the context-less hold applies to both.
  Correlation stays identity-only — the source never names the awaited-child lineage fields.
- Both collect tools' `no_wave` detail names the per-activation rule (same-session `/reload` vs a
  session switch).
- Test doubles: the memory adapter's `stopOutcome`/`terminalProof` knobs and `proofs` record; the
  shared fake's `status` method, typed `stop` replies (`stopReply`, `noLiveRunController`),
  `terminalProof`/`statusReply` knobs, `statuses` record, the `workflowScriptPath` rejection, and a
  reload-safe `extension(pi)` rebinding.
- `foregroundDelegation.ts` is unchanged (Decision 4: pinned, not modified).

## The offline evidence (framework suites)

**Awaited-child events** — `extension/waves/reportWaveRpc.test.ts`, whose pure test-local builder
`awaitedChildEvent(handle, {key, state})` produces the exact 0.76.1 payload (child id + a sibling
path string, `parentWorkflowRunId: handle.asyncId`) and feeds it through `fake.emit`:
- `rpc integration: an awaited-child event BEFORE the spawn reply is buffered then discarded; the root completion settles`
- `rpc integration: awaited-child events WHILE siblings remain active never settle — completed, failed and stopped children are ignored until the root completion`
- `rpc integration: a hostile awaited-child event copying the workflow's id as runId/parentWorkflowRunId but carrying its own identity never matches`
- `source pin: the transport modules never read the awaited-child lineage or capacity fields; the terminal proof is narrowed in rpcAdapter.ts only`

**perk's own stop + the terminal proof** —
- `reportWaveRpc.test.ts`: `timeout — stop acknowledged, then exactly ONE status query; both diagnoses render and ride the receipt`; `timeout — an observed proof renders as observed`; `timeout — a status miss renders unavailable with the engine's text`; `timeout — an unknown proof keeps the engine's reason`; `timeout — a REFUSED stop (invalid_state) with a successful status keeps both diagnoses`; `cancel after launch — the same stop request + one-shot proof`; `the complete arm issues NO stop and NO status query`.
- `reportWave.test.ts` (memory adapter): the receipt `termination` pins on `timed-out`/`cancelled`, its absence on `complete`/`failed`; `a refused stop and an observed proof both ride the receipt and the detail`; `a stop acknowledgement never upgrades an unconfirmed proof`; `a contract-breaking adapter whose stop/terminalProof throw still settles`.
- `rpcAdapter.test.ts`: `stop never throws: a rejecting responder yields acknowledged:false carrying code: message`; `stop: a success reply is acknowledged:true (the RPC data shape is not inspected)`; the `narrowTerminalProof` matrix; `terminalProof` over the bus (success, `success: false`, silence).
- `adapterContract.test.ts` (both adapters): `stop never throws and returns a typed outcome …`; `terminalProof never throws and yields one of the four states …`; `exactly one status request per terminalProof call`.

**Duplicate responders** — `rpcAdapter.test.ts` `hold: stop never throws — a held-then-timed-out reply yields acknowledged:false …` and `hold: a ghost no_active_session on stop and status then live successes …`; `reportWaveRpc.test.ts` `a ghost responder on the timeout arm — spawn, stop and status each resolve past a held reply, one notice per held request`. The reporter's once-per-activation latch is unchanged.

**Same-version reload** — `extension/pi/v1/waveIsolation.test.ts` `same-version reload: pending
waves are activation-local and a pre-reload wave's late completion never settles a wave launched
afterwards`, over a REAL bound session with perk + the shared fake under mocked `setTimeout`. Its
claims are limited to what the fake can show: the pre-reload wave answers `no_wave` with the
per-activation clause; wave A's late completion (emitted on the rebound bus) leaves a fresh wave B
`wave_running`, and B's own completion settles it with B's reports (the positive oracle); the new
activation issues no stop/status; A's orphan transport, drained through the engine deadline plus
the fixed settlement grace, settles without throwing and reaches nothing. During implementation the
orphan settle was observed once through a temporary print (not committed):
`{stop: {acknowledged: false, reason: "This extension ctx is stale after session replacement or
reload. …"}, proof: {state: "unavailable", reason: <the same>}}` — the stale `pi.events` wrapper
throws, and the never-throwing adapter turns it into data. **Queued-wake retention and the
post-reload `Subagent updates above.` delivery are source-derived** (`notify.js`,
`parent-wake.js`); the live arm is W4.

**Wake-prompt preservation** — `extension/pi/v1/contextInjection.test.ts` `composition: the parent
wake prompt and the completion notice survive perk's context chain byte-for-byte (gate on|off)`: a
`subagent-notify` custom message and the `Subagent updates above.` user turn (array and string
content) survive `emitContext` unchanged with perk active, gate on and gate off, while a
`[READ-ONLY MODE]`-carrying user turn is dropped only in the gate-OFF arm (the control). Task
restore keeps the FIRST prompt: `extension/substrate/childTaskRestore.test.ts` `firstUserPrompt: a
later wake-shaped user message … never displaces the first prompt …` and
`extension/pi/v1/childTaskRestore.test.ts` `a floored child restores its task, not a later
wake-shaped user message, after compaction`.

**Structured failures / partial / stopped** — the failed-child test above (aggregate `{ok: false,
error}` → `lane-failed` with the engine's text, the early child events contributing nothing);
`reportWaveRpc.test.ts` `a stopped workflow completion (state stopped, no terminalOutcome) is
run-failed with no retained reports and no perk stop/status`; the existing native-partial pins in
`reportWaveRpc.test.ts`/`reportWave.test.ts` are unchanged and green.

**A freed slot is never termination** — `extension/pi/v1/foregroundDelegation.test.ts` `a freed
supplier slot is never writer termination: a failed terminal decorated with process/capacity fields
still retains`, `a completed terminal decorated the same way still releases on status alone`, `source
pin: the writer transport never names engine capacity/slot state …`; the wave-side source pin above;
the wave detail renders only an `observed` proof as observed.

**The fake mirrors 0.76.1's RPC** — `reportWaveRpc.test.ts` `rpc spawn: a workflowScriptPath key …`
and `… an undefined-valued workflowScriptPath key …` (the engine's exact message).

## Required extension/skill delivery (no new mechanism)

No registration mechanism was added (the objective's boundary; no gap demonstrated). T11 of the
1.1.0 characterization proved the restriction packet and perk's extension reach a 0.76.1 runner
child under `--approve` (`[READ-ONLY MODE] (unscoped)` in the child log, `extensionBindings` in the
recovery descriptor). The refuse-launch half is the existing exact-source Ponytail preflight. The
pins restated, none added: `reportWaveRpc.test.ts` `rpc round-trip: every child carries the
constant packet and caller-checkout placement` (packet + `worktree: false` on every rendered
child); `reportWave.test.ts` `wave.run: failed required-skill preflight skips only that lane and
stays uncovered`, `all-skipped preflight never spawns`, `wave.start: launch reports ordered partial
preflight omissions truthfully`, and `the rendered script serializes opted-in skill but never
required-skill metadata` (`requiredSkill` never reaches a rendered item). `requireForAllRunners`
stays unused (its package import is outside perk's bare-import contract). The remaining trust rows
— remembered trust and `defaultProjectTrust: "always"`, last measured as T2/T3 in
[`pi-subagents-0.75.0-reverify.md`](pi-subagents-0.75.0-reverify.md) on 0.75.0 + Pi 1.0.0 — are
W5.

## Print-mode post-terminal side effects (attribution only)

The 2.1 record's L1 observed, after an awaited child completed in print mode, two perk stale-ctx
errors and Pi's `<boundary>` `turn_end` error. The planning-time explanation: Pi's
`AgentSession.dispose()` invalidates the runner BEFORE the aborted wake turn's end events dispatch,
and print mode's `finally` disposes right after `session.prompt` returns, while the engine's wake
turn is still in flight. This is a planning-time fact, not a measurement; print-mode attribution is
node 2.4's domain.

## Deferred live legs — DEFERRED → 7.1

**Deviation (operator decision, 2026-10-19).** This node ships no live measurement; node 7.1's
description absorbs W1–W7b, and the objective's post-landing reconcile records the deviation in
`docs/planning/pre-pi-durable-true-up.md` § "Deviations recorded by Objective #2707".

**Instrument (shared by every leg).** The 2.1 record's shape: `$SCRATCH` = the run's gitignored
scratch dir; `run-bounded.sh` extracted byte for byte from
[`pi-1.0.0-characterization.md`](pi-1.0.0-characterization.md) § "The watchdog added after A11"
(SHA-256 `1114155f63fdd2ecb8616dbdf9a890de09b693deb5f6f3cf4aa7bf6fd94b0843`); `AUTHED=$(mktemp -d)`
holding only a copy of `auth.json`; `PI_SUBAGENTS_TEMP_ROOT="$SCRATCH/subagents-tmp"`; the env scrub
(`PERK_RUN_ID`, `PERK_PROFILE_HANDOFF`, `PERK_SELFCHECK`, `PI_SUBAGENT_*`, the implementing
session's own `PI_SESSION_FILE`/`PI_SESSION_ID`/`PI_MODEL`/`PI_PROVIDER`/`PI_REASONING_LEVEL`/
`PI_CODING_AGENT`); `$MODEL` = the cheapest Anthropic model in the installed catalog; a scratch
`-e` probe extension (never committed, SHA-256 recorded) that drives perk's production
`createReportWave(pi.events)` `start` → print the handle → `collect`. Every leg is bounded by the
watchdog (`GRACE`/`CAP`), records exact versions, and ends with the stop-and-confirm below.

**Stop-and-confirm (every leg).** Before any deletion: list the leg's async run dirs and their
`status.json` states; confirm no runner PID from the leg is alive (`ps -p`); confirm no `.pi/`
settings or trust file outside `$AUTHED`/`$SCRATCH` changed (hash before/after); only then remove
`$SCRATCH` children.

| Leg | Procedure | Pass criteria |
| --- | --- | --- |
| **W1** awaited-child events on a 2-lane wave | Probe launches a two-lane wave; a second `-e` listener logs every `subagent:async-complete` payload's `id`/`asyncDir`/`awaitedByWorkflow`/`parentWorkflowRunId`/`state` with timestamps; collect after the workflow notice. | ≥ 2 child payloads with `awaitedByWorkflow: true`, `parentWorkflowRunId` = the handle's asyncId, `id`/`asyncDir` ≠ the handle's; the wave settles only after the workflow's own payload; `collect` returns both lanes; receipt children from the root completion. |
| **W2** lazy-loading first-use latency | Fresh process; probe timestamps the first `ping` reply, the first `spawn` reply, and (for a foreground writer) the `started` event relative to `session_start`. | `ping` < 5 s (`WAVE_RPC_PING_TIMEOUT_MS`); first `spawn` reply < 30 s (`WAVE_RPC_REPLY_TIMEOUT_MS`); `started` < 5 s (`START_ACK_MS`). |
| **W3** duplicate load under remembered trust (Pi 1.1.0) | `$AUTHED/settings.json` adds user-scope `npm:pi-subagents` beside the project entry; remembered trust (`trust.json` keyed by `realpathSync`); run a wave; capture perk's `perk: waves — …` warning and doctor `subagent-package-scope`. | Either outcome is recorded: with the ghost (expected — Pi 1.1.0's `loadFinalExtensionSet` still reuses the pre-trust runtime and drops a preloaded path absent from the final list without invalidating it), the wave completes, exactly one warning per activation, notices name `spawn`; without it, no warning. The never-executed pre-trust-leak dogfood is executed here. |
| **W4** same-session `/reload` with a queued completion | Interactive session (tmux) with a scratch `-e` probe registering `/probe-wakes`, which prints `ctx.sessionManager.getSessionId()` and `globalThis[Symbol.for("pi-subagents.queued-completion-wakes.v2")].get(ctx.sessionManager)?.wakes.length`. **Stage the queue:** launch a short wave, then immediately prompt a busy parent turn that outlasts it (one bounded `sleep 120` bash call), so the workflow completion arrives while the parent streams — Pi queues the triggering notice instead of appending it, and `notify.js` keeps its wake in `unstartedWakes` until the notice's `message_start`. **Observe before reload:** the workflow run dir's `events.jsonl` logs `subagent.workflow.completed`; the session `.jsonl` holds no `subagent-notify` entry yet; `/probe-wakes` (queued behind the turn, or run after interrupting it) reports ≥ 1 wake for this session id. Record the timestamps. **Reload while still queued:** `/reload` (interrupting the busy turn first if Pi will not reload mid-turn), re-checking `/probe-wakes` immediately before it. **After reload:** run `/probe-wakes` again, then let the session go idle. | Pre-reload: the completion is logged BEFORE the reload timestamp, no `subagent-notify` entry exists, and the probe shows ≥ 1 queued wake — otherwise the leg is **not staged** (a completion produced after the reload proves nothing) and is re-run, never scored. Post-reload: the probe shows the same session id with the wake re-adopted; the `subagent-notify` entry and the `Subagent updates above.` user turn then arrive exactly once, in the new runtime (no duplicate from the old one); `collect_*_wave` answers `no_wave` with the per-activation clause; no stale-ctx errors interactively. If interrupting the busy turn delivers or drops the queued notice before `/reload` can run, record that as the finding (the retention path is unreachable interactively), not a PASS. |
| **W5** trust rows T2/T3 | As 0.75.0's T2 (remembered trust, no flag) and T3 (`defaultProjectTrust: "always"`, `trust.json` removed) on Pi 1.1.0 + 0.76.1, one `restricted` lane each. | Child log shows `[READ-ONLY MODE] (unscoped)`; recovery descriptor carries `extensionBindings`; lane `ok: true`; no trust diagnostic. |
| **W6** live deadline partial | `PERK_WAVE_TIMEOUT_MS` tiny (e.g. 20 s) with one lane told to take longer. | Engine settles `partial/timeout` within the grace; the finished lane's report is retained; the slow lane is `lane-failed` (`lane still running at native partial settlement`); `complete: false`; perk issues no stop/status. |
| **W7a** perk's own RPC stop | (i) A wave whose collect is driven past perk's timeout (or cancelled) while running: record the stop reply and the projected proof; then issue a second manual `status {id}` later. (ii) `/reload` mid-wave, then drive an RPC `stop {id}` for the pre-reload run. | (i) stop `state: "stopping"` → detail `stop requested; child termination unconfirmed (pending: Workflow dispatch is still open.)`; the later manual `status` shows `observed`. (ii) `invalid_state … no live run controller available to stop.` surfaced as `stop refused (…)` with the proof still projected. |
| **W7b** the model-facing tool action (outside perk's paths) | Via the `subagent` tool: `interrupt` a child → paused; tool-action `stop` on the delivered paused run; observe the workflow completion. | The seal (on observed, identity-matching proof) or `terminal proof is not ready (<reason>)`; the workflow completion `stopped`; perk's wave `run-failed` with no reports, perk state untouched, no perk stop/status. |

## Residuals

- **Up to 60 s on timeout/cancel.** The stop and the status query are each bounded by the 30 s
  reply timeout, so a silent or ghost-only responder can delay a timeout/cancel settlement by up to
  60 s instead of 30 s. Recorded, not a knob.
- **Source-derived projections.** `stop`'s data/refusal shapes and the `status` proof shape are read
  from 0.76.1 sources; the live confirmation is W7a.
- **Activation-only reload proof.** The offline reload test proves isolation, not queued-wake
  retention or the post-reload wake (W4).
- **`observed` is quiescence.** A never-started child counts as resolved; the detail says
  "termination observed", never "exited".
- **Identity-only correlation** assumes the engine never reuses the workflow's `id`/`asyncDir` for a
  child (true at 0.76.1: child run dirs are siblings).

## `/learn` candidates

- `docs/learned/workflow/report-waves.md`: the post-stop read (stop outcome + one-shot terminal
  proof, diagnostics only); the stop outcome as data; the fake's `status`/`stopReply`/
  `terminalProof`/`statusReply` knobs and the reload-safe `extension(pi)`; the per-activation
  reload rule and the mocked-timer drive needed to drain an orphan transport through the fixed
  grace in a real-session harness test.
- `docs/learned/pi/subagents.md` § "Supervisor channel" / § "The v1 extension RPC seam": the wake
  prompt; the awaited-child event; the RPC stop vs the tool-action stop; `status`'s terminal proof;
  the 0.76.1 facts above.
