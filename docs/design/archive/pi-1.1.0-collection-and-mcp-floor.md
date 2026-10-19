# Record: collection semantics and the report floor on Pi 1.1.0 + pi-subagents 0.76.1

**Status:** measured. Authored 2026-10-19 (UTC) on branch `plan-2721` (base `8e5166ce`). It
implements plan #2721 (Objective #2707, node 2.3) on the adopted pair (development pins and floor
at Pi 1.1.0, supplier pin at pi-subagents 0.76.1). This node moves no pin, floor, stamp,
agent-definition body, setting or doctor check.

It covers three things:

1. **Relaunch freshness.** This is the one production change: every wave spawn carries a
   per-launch **launch token**.
2. **Partials and repeated collection.** Pins only.
3. **The report floor against MCP on Pi 1.1.0's tool-selector semantics.** Proven offline on real
   sessions that register an MCP tool, and measured live.

**Verdict:**

- Every required live leg passed (L1, L2, and the F1 treatment).
- L3, which corroborates, passed.
- The F1 control **reproduced the hazard**: before the fix, an identical relaunch after `/reload`
  reused all three lanes of the replaced run and returned their reports as a fresh wave.
- No leg is DEFERRED.

The one deviation from the plan's pass-criteria wording is L1/L2's `contact_supervisor`. It comes
from the launch vehicle, and the wave's own children do not show it. It is recorded below rather
than rounded off.

## Versions

| Component | Version |
| --- | --- |
| PATH `pi` (`pi --version`; mise-installed `@earendil-works/pi-coding-agent`) | `1.1.0` |
| Root SDK (`node_modules/@earendil-works/pi-coding-agent/package.json`) | `1.1.0` |
| Worktree engine (`.pi/npm/node_modules/pi-subagents/package.json`) | `0.76.1` |
| `@earendil-works/pi-mcp` (lockfile-held, hoisted top-level; the offline fixture's transport pair) | `1.1.0` |
| Node | `v26.3.0` |

The live legs ran inside the implement session (pid 83411; a fresh host process at launch). The
operator gave every `/reload` and `/plan` gesture. No supplier install happened under the session.

## Summary

| Clause | Offline | Source-derived (0.76.1 / Pi 1.1.0) | Live |
| --- | --- | --- | --- |
| A relaunch after `/reload` never reuses the replaced run | token pins in `reportWave.test.ts`, `reportWaveRpc.test.ts` (source pin), `waveIsolation.test.ts` (both reload tests) | `workflow-reuse.js::findWorkflowReuseSource` / `matchWorkflowReuse`; `subagent-executor.js` (`argsDigest = stableJsonDigest(args)`) | F1: control **reuse observed**; treatment **PASS** |
| Drain-once collection | existing pins; the draft-pair reload test's third collect | — | F1 treatment: second collect `no_wave` (S7-shaped, corroboration only) |
| `ok` is the sole lane-status fact; partial markers never read | `rpcAdapter.test.ts` (engine-exact `timed` row + hostile pair), `reportWaveRpc.test.ts` (partial-marked lane with a valid report → `lane-failed`) | `run-child-session.js` (`outputPartial` beside `exitCode: 1`), `subagent-runner.js` (`success: … exitCode === 0 …`), `workflowResultChildren` (no `outputPartial`) | — |
| MCP tool under a def-shaped allowlist: registered, nested-callable, inactive | `mcpReadOnlyFloor.test.ts` T1 | `agent-session.js::_isAllowedTool` / `_allowlistFiltersMcp` / `_getCallableTools` | — |
| Direct + nested MCP calls blocked under the child floor and the `/plan` gate | `mcpReadOnlyFloor.test.ts` T2–T4 (server call count 0 gated, ≥ 1 read-write) | `toolGating.ts` `tool_call` backstop (never reads `parentToolCallId`) | — (no gate-preserving live vehicle) |
| A perk report child registers no MCP tool | — | `child-session.js` (`builtinMcp` only for nonempty `builtinMcpTools`) | L1 **PASS**, L2 **PASS** |
| The gated parent request omits a registered MCP tool | `mcpReadOnlyFloor.test.ts` T4 | `hiddenDeclarationsFor` over `unknown` | L3 **PASS** |

## The source-derived facts

### Workflow reuse (pi-subagents 0.76.1)

- **The key.** `src/workflows/workflow-reuse.js::findWorkflowReuseSource(asyncDirRoot, sessionId,
  scriptDigest, argsDigest)` walks the session's recent terminal runs. It returns the child journal
  of the newest workflow run with the same `scriptDigest` and `argsDigest`, but only when that
  run's `workflow.stopCause === "runtime-replaced"`.
- **What is reused.** `matchWorkflowReuse` returns settled children only when `result.ok`. It
  re-attaches started children whose fingerprint matches.
- **Where the stop cause comes from.** The extension runtime's `cleanup()` (`src/extension/index.js`)
  aborts every live workflow controller with `runtimeReplacedAbortReason()` on `/reload`.
- **The digests.** `subagent-executor.js` computes `argsDigest = stableJsonDigest(args)` when the
  request carries `args`. Absent `args` yields the same digest every time: `{}` →
  `44136fa3…`, observed below.
- **The completion notice.** It says so itself: *"relaunch the same workflow script with the same
  args to reuse finished children and re-attach to running ones."*
- **Why perk was exposed.** Perk's rendered scripts are byte-identical for the same
  angles/draft/PR (`scriptDigest` `95295a64…` on every F1 launch below).
- **The control.** RPC `spawn` maps `script` onto the internal carrier and runs the request
  through `normalizePublicSubagentExecution`, which refuses `args` only without a workflow input.
  An inline-script spawn therefore accepts a plain-JSON `args`. The engine persists it as
  `status.json.workflow.args` / `argsDigest`.

### Partial markers

- `outputPartial: true` is set on a single run's result beside `exitCode: 1`
  (`run-child-session.js`, `foreground/execution.js`).
- The single-run `success` is `!stopped && !timedOut && … && exitCode === 0`
  (`subagent-runner.js`), so a partial row is always `success: false`.
- The workflow projection `workflowResultChildren` carries `success: child.ok` and per-row
  `terminalOutcome` on the failure path, never `outputPartial`.

### MCP attachment and Pi 1.1.0 selectors

- **When a child gets MCP.** `child-session.js::createDefaultChildSessionFactory` adds
  `builtin:mcp` only for a nonempty `launch.builtinMcpTools`, which is derived from `mcp:`
  selectors. SDK sessions install no CLI builtins.
- **A definition's `excludeTools` is inert beside an allowlist.** `child-launch.js` forwards it to
  the SDK only when the plan has no explicit allowlist:
  `!toolPlan.explicitToolAllowlist && excludeTools.length > 0`. `child-tool-plan.js` applies it as
  an exact-name set.
- **Pi 1.1.0 keeps MCP tools beside an allowlist.**
  - `agent-session.js::_isAllowedTool` keeps an MCP tool registered unless
    `_allowlistFiltersMcp`, which holds only for an empty allowlist or one naming an `mcp__`
    entry.
  - `_getCallableTools` keeps every `codemode`/`deferred` tool callable through
    `ctx.executeTool`.
- **Exposure mapping.** MCP's default `codemode` exposure registers as tool exposure `deferred`
  (`extensions/mcp/tools.js::toToolExposure`), the value T1 pins.

## What perk changed

- `extension/waves/transport.ts`: `WaveSpawnParams.args: { launch: string }`, documented. It is
  minted at `startWaveScript`'s one spawn site as `args: { launch: randomUUID() }`. It is not a
  `WaveScriptSpec` field and not caller-selectable. A module-header "RELAUNCH FRESHNESS" paragraph
  carries the engine fact. `rpcAdapter.ts`, the memory adapter and the fake are unchanged: the fake
  already sinks every spawn param.
- Hand-built spawn fixtures gain fixture-literal tokens.

## The offline evidence

- **Transport/logical tiers.**
  - `rpcAdapter.test.ts`: the engine-exact timed-out row projects `ok: false` with its report
    retained as DATA. The hostile `success: true` + `outputPartial` row projects `ok: true`,
    documenting the `ok`-only rule; the engine never emits that pair.
  - `reportWaveRpc.test.ts`: a partial-marked lane with a schema-valid report is `lane-failed`
    (detail `Subagent timed out.`), absent from `reports`, and the wave has `complete: false`. The
    extended source pin forbids
    `outputPartial|timedOut|reused|reusedFrom|stopCause` (beside the lineage/capacity names) in
    `rpcAdapter.ts`, `transport.ts` and `reportWave.ts`. It asserts `transport.ts` mints the token
    and that neither of the others mentions `args`.
  - `reportWave.test.ts`: the spawn-shape pin asserts a UUID token. A new test proves two spawns of
    one spec carry distinct tokens, neither derived from the script/spec, with the script bytes
    unchanged.
- **Harness (slow tier, `waveIsolation.test.ts`).**
  - The review-pair reload test asserts distinct tokens across the pre- and post-reload spawns.
  - A new draft-pair reload test covers the following, with mocked timers and the orphan transport
    drained through the fixed grace with no stop/status on the live responder:
    1. The pre-reload wave answers `no_wave`.
    2. The primed draft context is gone (`no_draft_context`).
    3. A re-prime through the real door plus a relaunch spawns a fresh-token wave.
    4. The orphan's late completion never settles it (`wave_running`).
    5. Its own completion yields its own reports.
    6. A third collect answers `no_wave`.

    Its fake plannotator binds the door's preset port and answers the readiness probe and the
    annotation pushes, so no door timer sleeps on the mocked clock.
- **The MCP floor on real sessions (`extension/substrate/mcpReadOnlyFloor.test.ts`, fast tier, ~2.1
  s).**
  - **Fixture:** Pi's public `createMcpExtension` loaded as `{ name: "mcp", factory, builtin: true }`
    over `@earendil-works/pi-mcp/testing::createInMemoryTransportPair`, plus a test-written
    JSON-RPC responder that counts `tools/call`.
  - **T1:** a def-shaped allowlist keeps `mcp__docs__search` registered (`source: "builtin"`,
    `path: "builtin:mcp"`, exposure `deferred`), nested-callable, inactive and non-activatable,
    while `edit`/`write` are filtered. An allowlist naming the tool makes it activatable. The Pi
    SDK denylist control (`excludeTools: ["mcp__*"]`) removes it. That control is labelled as
    Pi's `--exclude-tools`, not a def's frontmatter key.
  - **T2:** direct `tool_call` is blocked as not allowlisted under the floored child shape and the
    `/plan` gate, and not blocked read-write.
  - **T3:** nested `ctx.executeTool` is blocked with the parent call id kept under the floor and
    the gate. The two read-write controls reach the server (count 1).
  - **T4:** a direct-exposure tool is declared and runs read-write (count 1). Under the gate its
    declaration is hidden and the scripted call answers the block reason (count 0).
- `toolPolicy.test.ts`: `mcp__docs__search` and `list_mcp_resources` from `builtin:mcp` are
  `unknown`, ineligible read-only at every registry stage and unscoped, eligible read-write, and
  hidden in every gated landing.
- `tests/test_subagent_agents.py`, `tests/test_repo_local_agents.py`: `excludeTools` and
  `mcpDirectTools` are pinned absent on every definition.

## The live legs

**Instrument.** A scratch, untracked census observer (`<worktree>/.pi/extensions/tool-census.ts`)
was loaded ambiently by the parent and by every runner child whose cwd is the worktree. It wrote
samples to a scratch directory:

- at `session_start`;
- on every registration change for 15 s (a 250 ms poll);
- at every `before_provider_request`, with the model-facing tool names.

Scoring used each process's last sample and its first provider-request sample.

**Mid-session observer correction (L3 only).** Anthropic native mid-conversation tool changes
keep the request-level `tools` list fixed and carry later additions/removals as
`tool_addition`/`tool_removal` blocks in system messages (`pi-ai`
`anthropic-messages.js`, `DEFERRED_TOOL_PLACEHOLDER`). The first observer read only
`payload.tools`, so for the long-lived parent it under-reported the model-visible set: tools
activated mid-session were missing. It was corrected before the L3 gated measurement to replay
those blocks. The L1/L2 child scores are unaffected: each child's first request carries no
mid-conversation changes, and the children run an OpenAI-provider model.

The scratch stdio MCP server is reproduced verbatim at the end (§ "The scratch MCP server").

### F1 — relaunch freshness: control (pre-fix), then treatment

Vehicle: `start_review_wave {angles: ["claimed-intent", "tests"], pr: 2718, worktree: <this
worktree>}`, three lanes with Ponytail. PR #2718 had already landed.

**False start (recorded, not scored).** Wave `6b2df939…` completed in about 2.5 min, before the
operator could reload: the session waited for a first settled lane before prompting, and the wave
was fast. It was collected normally and carries no reuse evidence. Its `status.json` already
showed the pre-fix shape: `workflow.args: {}`, `argsDigest: 44136fa3…`.

**Control (pre-fix extension).**

| | Replaced run `7fde74b0-62ee-4fa5-ab8d-6524a5f5132f` | Relaunch `f617c292-e2d0-4c95-b726-69fed10b6748` |
| --- | --- | --- |
| `workflow.args` / `argsDigest` | `{}` / `44136fa3…` | `{}` / `44136fa3…` |
| `scriptDigest` | `95295a64…` | `95295a64…` |
| state after `/reload` | `stopped`, `stopCause: "runtime-replaced"` | — |
| `reusedFrom` | — | `7fde74b0-…` |
| children at relaunch +3 s | claimed-intent `23c18622` (settled ok), tests `cae1f49b`, ponytail `d99a1a83` (running) | claimed-intent `23c18622` `reused: true`; tests/ponytail re-attached (journal `start` rows with `cae1f49b`/`d99a1a83`) |
| children at completion | — | all three `23c18622`/`cae1f49b`/`d99a1a83`, each `reused: true` |

- `collect_review_wave` after the reload answered `no_wave`, naming the per-activation rule.
- The relaunch's `collect_review_wave` returned three complete reports. Every one came from a
  child launched by the replaced wave. This is the hazard, **MEASURED**.

**Treatment (post-fix extension, after `/reload`).**

| | Replaced run C `8029b89a-6886-4fb0-a396-434e7063aea2` | Relaunch D `d1079879-534f-4e95-802f-5073e2e78e34` |
| --- | --- | --- |
| `workflow.args.launch` | `cf460c88-f3a3-4283-8d52-22d68d942237` | `013d861b-a962-4b1a-8908-c9ffdfbd063c` |
| `argsDigest` | `751e6c82…` | `a2af88c4…` |
| `scriptDigest` | `95295a64…` | `95295a64…` (unchanged bytes) |
| state after `/reload` | `stopped`, `stopCause: "runtime-replaced"` (no lane settled) | — |
| `reusedFrom` | — | absent |
| children | `83790957`/`6ebf67e8`/`ee29e8dd` | `01e7f4fe`/`572809ca`/`6531ba89` (all new; no `reused` step; journal `start` rows only for the new run ids) |

- `collect_review_wave` after the reload answered `no_wave`.
- D's collect returned three complete reports. The journal's `settle` rows and the steps name only
  D's child run ids.
- A second collect answered `no_wave`. This is drain-once, the S7-shaped observation; it is
  corroboration only, because the browser-door S7 row stays 7.1's.

**Verdict: control reproduced; treatment PASS.** Every orphan child was terminal before teardown:
the replaced runs' children `23c18622`/`cae1f49b`/`d99a1a83` and `83790957`/`6ebf67e8`/`ee29e8dd`
were all `complete`.

### L1 — a report child's tool list, no `mcp.json`

Vehicle: the native `subagent` tool from the implement session (plan decision Q4: launched by the
model, not by the wave renderer). The call was `agent: "perk.scout"`, `worktree: false`,
`context: "fresh"`, `extensionBindings: {"perk.parent-restrictions/1": {"readOnly": true}}`, and
`outputSchema` `{tools: string[]}`. Run `ab13bf2f-a440-444e-a53e-c9360b31892b`, child pid 90297.

| Sample | Registered (provenance) | Model tools |
| --- | --- | --- |
| seq 0 `session_start` 17:12:37.597Z | `read`, `bash`, `grep`, `find`, `ls` (`builtin:*`); `structured_output`, `contact_supervisor` (`<inline:pi-subagents:prompt-runtime>`) | — |
| seq 1 `before_provider_request` 17:12:37.922Z | same | `read`, `grep`, `find`, `ls`, `bash`, `structured_output`, `contact_supervisor` |

- No `mcp__*` tool and no `builtin:mcp` provenance at any sample.
- No `tool_search`, `codemode`, `edit`, `write`, or perk tool.
- The child's own report agreed. It listed the same names under the provider's `functions.`
  namespace, plus the provider-native `multi_tool_use.parallel` wrapper, which is not a
  registered tool.

**`contact_supervisor` (deviation from the plan's "exactly the five + `structured_output`").** The
native `subagent` tool launches with the intercom bridge active, so the prompt runtime registers
the supervisor door. perk's own waves spawn with `intercomBridge: {mode: "off"}`.

That claim is corroborated by the six perk-rendered wave children the observer also caught during
F1: pids 84624/84626/84627 (wave `6b2df939`) and 85366/85367/85368 (wave `7fde74b0`). Each
registered exactly `read`, `bash`, `grep`, `find`, `ls`, `structured_output`, declared exactly
those six to the model, and had no MCP at any sample.

The leg's FAIL condition (a child registers an MCP tool) did not occur. **Verdict: PASS.**

### L2 — a report child's tool list WITH a trusted-project `mcp.json`

Plant: `<worktree>/.pi/mcp.json`:

```json
{"mcpServers": {"scratch": {"command": "node", "args": ["<scratch>/mcp-scratch.mjs"], "exposure": "direct"}}}
```

**Parent control.** An env-scrubbed run: `env -u PERK_RUN_ID -u PI_SESSION_FILE -u PI_SESSION_ID
-u PI_SUBAGENT_* pi --approve --no-session -p "reply ok"` (pid 90544, exit 0, reply `ok`).

- seq 0 `session_start` 17:13:20.844Z: no MCP.
- seq 1 registration-change 17:13:21.200Z: no MCP.
- seq 2 `before_provider_request` 17:13:21.216Z: `mcp__scratch__echo` registered (`builtin:mcp`,
  exposure `direct`) and present in the model tools.
- seq 3 registration-change 17:13:21.453Z: still registered.

The fixture registers in a trusted parent, so the child arm is not vacuous.

**Child arm.** The same launch as L1: run `2914b11d-e156-4f07-9f27-120ea6f5d773`, child pid 90703.
seq 0 at 17:13:51.826Z and seq 1 at 17:13:52.142Z are **identical to L1**: the same seven
registered names and the same seven model tools, no `mcp__*` and no `builtin:mcp` anywhere. The
census observer, also a project-local resource, did load in the child, so the child saw the
trusted project tier. It simply never attaches MCP.

| | Parent control (pid 90544) | Child (pid 90703) |
| --- | --- | --- |
| `mcp__scratch__echo` registered | yes (`builtin:mcp`, `direct`) | no |
| `mcp__scratch__echo` in model tools | yes | no |
| `builtin:mcp` provenance anywhere | yes | no |

`calls.log` stayed absent throughout: nothing called the server. **Verdict: PASS.**

### L3 — parent presentation + read-write reach

With `.pi/mcp.json` present, the operator ran `/reload` (17:15:24Z). The session's samples:

- seq 0 `session_start`: no MCP.
- seq 1 registration-change 17:15:24.728Z: no MCP.
- seq 2 registration-change 17:15:25.248Z: `mcp__scratch__echo` registered (`builtin:mcp`,
  `direct`) and active.

Registration arrives about 0.8 s after `session_start`, asynchronously.

| Step | Observation |
| --- | --- |
| Read-write reach | The model called `mcp__scratch__echo {text: "x"}` → result `x`; `calls.log` gained exactly one line (`{"pid":83411,"args":{"text":"x"}}`, 17:16:30Z). |
| Read-write presentation (corrected observer, seq 14, 17:22:41Z) | `mcp__scratch__echo` registered, active, and in the model tools (37 names) |
| Gated presentation (`/plan` ON, one prompt; seq 15, 17:24:08Z) | registered **and active**, but **absent** from the 17 model tools — hidden like `edit`/`write` (also active, also absent); `calls.log` unchanged (1 line) |
| After `/plan` OFF (seq 16, 17:24:37Z) | declared again (36 names) |

The model made no call under the gate, so there is no bonus backstop observation. The backstop is
T2–T4's. **Verdict: PASS.**

## Teardown proof

- Stop-and-confirm before teardown:
  - every touched workflow (`6b2df939`, `7fde74b0`, `f617c292`, `8029b89a`, `d1079879`) is
    terminal, and so are their nine distinct children;
  - both scouts (`ab13bf2f`, `2914b11d`) are `complete`;
  - no perk runner PID was live. The one live `subagent-runner` belonged to another repository.
- Removed: `<worktree>/.pi/extensions/tool-census.ts`, `<worktree>/.pi/mcp.json`, and the scratch
  directory under `.perk/workflow/scratch/runs/<run>/agent/`, which is gitignored. The scratch MCP
  server process was the implement session's own MCP connection and ended with it.
- `git status --porcelain` lists none of the scratch paths. The state is recorded in the PR's
  final commit.

## Residuals / handoffs

- **To 3.3** (the browser-operation owner): after a `/reload` mid-wave, the browser still shows
  the pre-reload "Reviewer wave running" marker while that wave can never be collected. Annotation
  state is activation-local, and a persisted browser review controller is an objective non-goal.
- **To 7.1:** the browser-door S7 row (repeated collection at the PR door) stays its live cell. The
  F1 drain-once observation is corroboration only. Node 2.2's W1–W7b are untouched. No leg of this
  node is deferred.
- **To 7.2:** the reverify guide's broader rewrite, and
  `docs/design/pi-subagents-child-execution-policy.md` (the MCP-floor and launch-token facts as
  policy facts).
- **To 5.1** (optional reuse): the scratch stdio MCP server below, as a candidate committed fixture
  for the worker MCP matrix. That is 5.1's decision.
- **Accepted residual:** orphan children of a wave abandoned at `/reload` run to completion
  unobserved, bounded by the engine deadline. They are spend, never evidence. F1 measured both
  orphan sets finishing.
- **Vehicle residual:** L1/L2 used the native `subagent` tool, not the wave renderer. The child
  tool list does not depend on the launcher beyond the intercom bridge (the `contact_supervisor`
  difference above), and the six wave children corroborate the wave shape.

## `/learn` candidates

- `docs/learned/pi/subagents.md`:
  - workflow reuse and the `args` launch control (same session + script digest + args digest +
    `runtime-replaced`; settled-ok reused, running re-attached);
  - `outputPartial` reach (single-run only, `success: false`, dropped by the workflow projection);
  - `builtin:mcp` is attached only with `mcp:` selectors;
  - Pi 1.1.0's allowlist keeps MCP tools nested-callable;
  - a definition's `excludeTools` is inert beside an explicit allowlist.
- `docs/learned/pi/tool-loadout.md` § "Test craft":
  - the offline MCP fixture (`createMcpExtension` + `createInMemoryTransportPair`, hoisted
    top-level at 1.1.0);
  - registration arrives after `setImmediate`, so poll and never snapshot at `session_start`;
  - MCP `codemode` registers as tool exposure `deferred`;
  - a live census must replay Anthropic `tool_addition`/`tool_removal` blocks, because
    `payload.tools` is not the model-visible set mid-session.
- `docs/learned/workflow/report-waves.md`:
  - the launch token beside the acceptance/bridge invariants;
  - the control-then-treatment `/reload` dogfood shape (launch, end the turn immediately, the
    operator reloads while lanes are still running — a fast wave can finish before a delayed
    reload, as the false start showed);
  - a test fake plannotator that binds the preset port keeps door timers off a mocked clock.

## The scratch MCP server (verbatim)

```js
// Scratch stdio MCP server (newline-delimited JSON-RPC). One tool, echo {text}; every tools/call
// appends one line to calls.log beside this file.
import { appendFileSync } from "node:fs";
import { createInterface } from "node:readline";
const CALLS = new URL("./calls.log", import.meta.url);
const send = (msg) => process.stdout.write(JSON.stringify({ jsonrpc: "2.0", ...msg }) + "\n");
createInterface({ input: process.stdin }).on("line", (line) => {
  let msg;
  try { msg = JSON.parse(line); } catch { return; }
  if (msg.id === undefined) return; // notifications (notifications/initialized) are ignored
  switch (msg.method) {
    case "initialize":
      send({ id: msg.id, result: { protocolVersion: msg.params?.protocolVersion, capabilities: { tools: {} }, serverInfo: { name: "scratch", version: "1.0.0" } } });
      return;
    case "tools/list":
      send({ id: msg.id, result: { tools: [{ name: "echo", description: "Echo the text back.", inputSchema: { type: "object", properties: { text: { type: "string" } }, required: ["text"] } }] } });
      return;
    case "tools/call":
      appendFileSync(CALLS, JSON.stringify({ at: new Date().toISOString(), pid: process.ppid, args: msg.params?.arguments ?? null }) + "\n");
      send({ id: msg.id, result: { content: [{ type: "text", text: String(msg.params?.arguments?.text ?? "") }] } });
      return;
    case "ping":
      send({ id: msg.id, result: {} });
      return;
    default:
      send({ id: msg.id, error: { code: -32601, message: "method not found" } });
  }
});
```
