# Characterization: delayed MCP restoration on published Pi 1.0.0 (perk vs a control)

**Status:** dated evidence record. Measured 2026-10-05 (21:45–22:11Z); authored 2026-10-05. It
measures perk 3.9.0 at revision `f178a0e30836b521dbb42771908db72e8ebf73a3` (the implement
worktree's HEAD before the fix) and at the fix commit `d1a7d26331d4e0a8b81a89e12f5724e403b2e85b`
against **published** Pi 1.0.0 in a throwaway detached worktree,
`$MAIN/.worktrees/pi-1.0.0-mcp-restoration` (removed at teardown), with the implement worktree's
0.99.2 dev pins as the baseline host. It implements plan #2664 (Objective #2656, node 2.2). The
precedent is [`pi-1.0.0-characterization.md`](pi-1.0.0-characterization.md) (ledger row D8 names
the pending-restoration set this record measures).

**Verdict: perk-induced loss demonstrated on rows W1-L1, W1-L2b, W1-L3, W1-L4, W1-L5 and W1-L6 —
fixed by the restoration-window rule; residual rows: none.**

- **Pre-fix, on 1.0.0**, perk's first reconciliation after `/reload` cleared Pi's pending set at
  every automatic point whose landing needed a removal. That was six rows: cohort unscoped,
  nonparticipant-turned-cohort, stage-scoped, read-only, read-only with codemode, and the
  mixed-exposure server that reconnects during the MCP extension's `before_agent_start` wait. In
  each row the matched control session without perk kept the MCP tool. The two in-window gesture
  rows (a `/plan` gate entry, a stage change by `/tree`) were `RULE-PARITY`: Pi's own deactivating
  control also lost the tool there.
- **Post-fix, on 1.0.0**, every former `PERK-INDUCED LOSS` row reads `FIXED` (`PARITY`), and both
  gesture rows read `PARITY` too. No automatic row is `BLOCKING`, so the floor decision is not
  held and 5.1 is not blocked.
- **0.99.2** has no window (0 occurrences of `_pendingToolNames` at `v0.99.2`). Every row is
  `NO-WINDOW`, with both arms LOST, before and after the fix. The 0.99.2 RESULT lines are
  byte-identical pre- and post-fix.
- **SDK/CLI resume (S1) is `NO-WINDOW` on 1.0.0 too**: the control loses the tool, as the source
  reading predicted.
- **The fix adds one presentation residual, measured on both hosts.** The first request after a
  cohort `/reload` carries the deferred family's prompt snippets (for the members eligible in the
  stage) and guidelines in its system prompt. Its declarations are hidden. The second request is
  clean. Before the fix that first request was clean. See [Residual](#residual-measured).
- **What changed in the PR:** the rule in `extension/substrate/toolGating.ts`, regression pins on
  both framework hosts (fake host + Mode A, green on 0.99.2 and on the 1.0.0 throwaway), the swept
  pins, contracts §8.40, `model-tools.md`, the pilot record's §2, and a CHANGELOG `### Fixed`
  bullet. No pin, lockfile, `src/`, `toolPolicy.ts` or golden-matrix change.

Measured rows and source-derived statements are kept separate. A **measured** row quotes output
of a command run in this experiment. A **source-derived** statement cites `<path>@v1.0.0` in the
tagged library mirror (`docs/library/source-code/github.com/earendil-works/pi`, tag `v1.0.0` =
`a13d35a742c6ef8462812a28fbe1d8c8b7431c32`, `v0.99.2` =
`005af57d88ee23b33778f343a9595b32e67ff788`), anchored by symbol, never by line.

**Path abbreviations in quotes:** `$MAIN` = `/Users/mattgiles/dev/github/mattgiles/perk`.
`$IMPL` = `$MAIN/.worktrees/plan-2664`. `$WT` = `$MAIN/.worktrees/pi-1.0.0-mcp-restoration`.
`$SCRATCH` = `$IMPL/.perk-characterization`. Quotes are verbatim apart from these substitutions.

## Snapshot matrix

| Component | 0.99.2 host (`$IMPL`) | 1.0.0 host (`$WT`) | Provenance |
|---|---|---|---|
| perk | 3.9.0 @ `f178a0e3` (pre-fix), `d1a7d263` (post-fix) | detached at `f178a0e3` (pre-fix), then `git checkout --detach d1a7d263` (post-fix) | `git rev-parse HEAD` |
| `VERSION` (printed by the script) | `HEADER VERSION=0.99.2 node=v26.3.0` | `HEADER VERSION=1.0.0 node=v26.3.0` | script header |
| pi-coding-agent | `$IMPL/node_modules/@earendil-works/pi-coding-agent/package.json version=0.99.2` | `$WT/node_modules/@earendil-works/pi-coding-agent/package.json version=1.0.0` | script header |
| pi-mcp `./testing` | `…/pi-coding-agent/node_modules/@earendil-works/pi-mcp/dist/testing/index.js version=0.99.2` (nested) | `…/pi-coding-agent/node_modules/@earendil-works/pi-mcp/dist/testing/index.js version=1.0.0` (nested) | script header |
| Dev pins | the committed 0.99.2 set (`[worktree] setup`'s `npm ci`) | `npm install --save-dev --save-exact` of the six `@earendil-works/*` packages at **1.0.0**, a throwaway edit to `package.json` + lockfile that was never committed | `$SCRATCH/wt-pins.log` |
| Top-level on-disk (1.0.0 host) | — | pi-agent-core, pi-ai, pi-client, pi-coding-agent, pi-server, pi-tui **1.0.0**; **pi-protocol 1.0.4, chord 1.0.4, pi-telemetry 1.0.3** (floating transitive) | each `package.json` `version` |
| Nested under pi-coding-agent (1.0.0 host) | — | chord, pi-agent-core, pi-ai, pi-codemode, pi-mcp, pi-telemetry, pi-tui all **1.0.0** | each nested `package.json` |
| `npm ls` gate (1.0.0 host) | — | every pi-coding-agent / pi-ai / pi-tui / pi-agent-core copy 1.0.0, typebox 1.3.27 deduped, exit 0 (pre- and post-fix) | `npm ls @earendil-works/pi-coding-agent @earendil-works/pi-ai @earendil-works/pi-tui @earendil-works/pi-agent-core typebox` |
| Extension order, PERK arm | `HEADER perk-order=["$IMPL/extension/index.ts","builtin:tool-search","builtin:mcp"]` | `HEADER perk-order=["$WT/extension/index.ts","builtin:tool-search","builtin:mcp"]` | script header; every PERK arm also asserts it |
| Extension order, CONTROL arm | `HEADER control-order=["builtin:tool-search","builtin:mcp"]` | same | script header |
| `pi` on PATH | 0.99.2 (`~/.local/share/mise/installs/node/26.3.0/bin/pi`), never launched | not used; the harness is the host | `pi --version`, `which pi` |
| npm registry | `1.0.0`, `1.0.1`, `1.0.2`, `1.0.3`; the subject stays exact 1.0.0 | | `npm view @earendil-works/pi-coding-agent versions --json \| tail -5` |
| `node` | v26.3.0 | v26.3.0 | `node --version` |

No `.pi/npm` staging, agent-dir copy or `pi` launch was used. The script sets
`PI_CODING_AGENT_DIR` to a scratch directory before Pi loads, and gives every MCP extension an
explicit `logPath`, so `getAgentDir()` never resolves the operator's `~/.pi/agent`.

## The window (source-derived)

All of this was read in the tagged mirror. It is not a measurement.

- **Populated.** In `packages/coding-agent/src/core/agent-session.ts@v1.0.0`, `reload()` adds every
  currently active name to `_pendingToolNames` just before `_buildRuntime` rebuilds the registry.
  `_restoreToolsFromTranscript()` replaces the set with the current system message's `toolsAdded`.
  `navigateTree` calls it after the leaf moves and before `session_tree` handlers. The constructor
  calls it only when `initialActiveToolNames === undefined`.
- **Consumed.** `_refreshToolRegistry()` pushes the pending names into the next active set on every
  registration (`nextActiveToolNames.push(...this._pendingToolNames)`). `_setActiveTools` then
  deletes the names that resolve to registered tools.
- **Cleared.**
  - `setActiveToolsByName` clears the set whenever a previously active name is absent afterwards:
    "A loadout that deactivates a tool replaces the restored one, whose pending tools are dropped.
    One that only adds tools, like activating tool_search, keeps them."
  - `_runAgentPrompt` clears it as well, before `agent.prompt`. Inside `prompt()`, that call follows
    `emitBeforeAgentStart`, which awaits every extension's handler in extension order (`ExtensionRunner.emitBeforeAgentStart@v1.0.0`), and `_preparePromptAndToolLoadout`.
- **A second run entry.** `sendCustomMessage(…, { triggerTurn: true })` calls `_runAgentPrompt`
  directly while idle, or queues it on `_deferredSettledActions` during settle. No
  `before_agent_start` runs on this path.
- **`agent_start` comes after Pi's clear, but too late for the first request's declarations.**
  `Agent.createContextSnapshot()` (`packages/agent/src/agent.ts@v1.0.0`) copies `state.tools`.
  `runAgentLoop` (`packages/agent/src/agent-loop.ts@v1.0.0`) runs `declareToolChanges(context,
  prompts)` and only then `await emit({ type: "agent_start" })`. `runLoop` re-runs
  `declareToolChanges` after `prepareNextTurn`, so every later request follows the live set. The
  same order holds at `v0.99.2`: in the installed `pi-agent-core` dist, `declareToolChanges` comes
  before `agent_start`, and `AgentSession._emitExtensionEvent` awaits `agent_start`.
- **The hidden-declaration mask.** `_applyToolLoadout` runs the `prepareLoadout` hook of every
  active tool that has one and unions their `hiddenDeclarations` into a fresh `Set`. Names are not
  checked against the declared list. The result is assigned to `_hiddenDeclarations`, replacing the
  previous mask. `_installHiddenDeclarationsProjection` filters the current mask's names out of
  every system message's `toolsAdded`/`toolsRemoved` at `transformContext` time. Two consequences:
  a hook result that depends on the declared list forgets a name as soon as it is removed, and a
  name the hook returns is masked whether or not it is declared.
- **The SDK/CLI resume path.** `core/sdk.ts@v1.0.0::createAgentSession` always computes
  `initialActiveToolNames` as an array, and `createAgentSessionFromServices` delegates to it
  (`core/agent-session-services.ts@v1.0.0`). So resume never reaches the restore.
- **The MCP extension** (`extensions/mcp/index.ts@v1.0.0`) handles `session_start`,
  `before_agent_start`, `tool_call`, `turn_start`, `mcp_servers_change` and `session_shutdown`. It
  has no `session_tree` handler.
  - `ensureDiscoveryActive` adds `tool_search` when a `deferred` server exists.
  - `waitForDirectServers` makes the next prompt wait for servers whose `configuredExposures`
    include `direct`. The flag that skips the wait is reset on every `session_start`.
  - Every `session_start` bumps `generation` and schedules new connections.
- **Extension order** (`core/resource-loader.ts@v1.0.0`, same at `v0.99.2`): CLI
  `additionalExtensionPaths` first, then `builtin:<name>` in factory order. Production and harness
  Mode B both load perk first (asserted above).
- `extensions/codemode/index.ts@v1.0.0` registers `codemode` with `defaultActive: false`.

## The matrix (measured)

**Arms.** PERK is a Mode B harness session (perk by path, so it loads before the builtins, as in
production). CONTROL uses the same factories, settings and gestures, without perk:

- `C-cohort` = `[toolSearch(), mcp()]` + `COHORT_SETTINGS`. It serves L1, L3, L4, G1, W2 and S1.
- `C-nosearch` = `[mcp()]`.
- `C-latesearch` = `[toolSearch(), mcp()]` with no cohort settings.
- `C-codemode` = `[toolSearch(), codemode(), mcp()]` + `+tool_search,+codemode`.
- `C-mixed` = `[toolSearch(), probe(), mcpMixed()]` + `COHORT_SETTINGS`.
- Gesture rows add CONTROL-DEACTIVATING (`CD`, drops `read` in-window) and CONTROL-ADDITIVE
  (`CA`, adds `grep` in-window).

**The tool and the server.** The MCP tool is `mcp__docs__search`, a `deferred`-exposure tool of
an in-memory server built on Pi's own `createInMemoryTransportPair`. Only the responder is
hand-written. The server's `initialize` is held until `release()`.

**Outcome rules.** The outcome is `KEPT` iff the tool is active once it re-registers. `declared=`
comes from the next census request; for L6 it comes from the measured prompt's own first request.
Every liveness guard in the script passed on both hosts in all four runs (`ℹ pass 12`,
`ℹ fail 0`).

### RESULT lines — 0.99.2 (`$SCRATCH/baseline-0.99.2.log`; `$SCRATCH/postfix-0.99.2.log` is byte-identical)

```
RESULT W1-L1 PERK LOST declared=no
RESULT W1-L1 CONTROL LOST declared=no
RESULT W1-L2 PERK LOST declared=no
RESULT W1-L2 CONTROL LOST declared=no
RESULT W1-L2b PERK LOST declared=no
RESULT W1-L2b CONTROL LOST declared=no
RESULT W1-L3 PERK LOST declared=no
RESULT W1-L3 CONTROL LOST declared=no
RESULT W1-L4 PERK LOST declared=no
RESULT W1-L4 CONTROL LOST declared=no
RESULT W1-L5 PERK LOST declared=no
RESULT W1-L5 CONTROL LOST declared=no
RESULT W1-L6 PERK LOST declared=no
RESULT W1-L6 CONTROL LOST declared=no
RESULT W1-G1 PERK LOST declared=no
RESULT W1-G1 CONTROL LOST declared=no
RESULT W1-G1-CD CONTROL LOST declared=no
RESULT W1-G1-CA CONTROL LOST declared=no
RESULT S1 PERK LOST declared=n/a
RESULT S1-C CONTROL LOST declared=n/a
RESULT W2-T1 PERK LOST declared=n/a
RESULT W2-T1-C CONTROL LOST declared=n/a
RESULT W2-T2 PERK LOST declared=n/a
RESULT W2-T2-C CONTROL LOST declared=n/a
RESULT W2-T2-CD CONTROL LOST declared=n/a
RESULT W2-T2-CA CONTROL LOST declared=n/a
```

### RESULT lines — 1.0.0 pre-fix (`$SCRATCH/prefix-1.0.0.log`, `$WT` at `f178a0e3`)

```
RESULT W1-L1 PERK LOST declared=no
RESULT W1-L1 CONTROL KEPT declared=yes
RESULT W1-L2 PERK KEPT declared=yes
RESULT W1-L2 CONTROL KEPT declared=yes
RESULT W1-L2b PERK LOST declared=no
RESULT W1-L2b CONTROL KEPT declared=yes
RESULT W1-L3 PERK LOST declared=no
RESULT W1-L3 CONTROL KEPT declared=yes
RESULT W1-L4 PERK LOST declared=no
RESULT W1-L4 CONTROL KEPT declared=yes
RESULT W1-L5 PERK LOST declared=no
RESULT W1-L5 CONTROL KEPT declared=yes
RESULT W1-L6 PERK LOST declared=no
RESULT W1-L6 CONTROL KEPT declared=yes
RESULT W1-G1 PERK LOST declared=no
RESULT W1-G1 CONTROL KEPT declared=yes
RESULT W1-G1-CD CONTROL LOST declared=no
RESULT W1-G1-CA CONTROL KEPT declared=yes
RESULT S1 PERK LOST declared=n/a
RESULT S1-C CONTROL LOST declared=n/a
RESULT W2-T1 PERK KEPT declared=n/a
RESULT W2-T1-C CONTROL KEPT declared=n/a
RESULT W2-T2 PERK LOST declared=n/a
RESULT W2-T2-C CONTROL KEPT declared=n/a
RESULT W2-T2-CD CONTROL LOST declared=n/a
RESULT W2-T2-CA CONTROL KEPT declared=n/a
```

Diagnostics from the same run:

- **W1-L2b** shows the cohort flip. Before the reload: `DIAG W1-L2b PERK startup-cohort=no`,
  `DIAG W1-L2b PERK before-reload-active:objective_stack_status=yes`. After it:
  `DIAG W1-L2b PERK after-reload-active:objective_stack_status=no`, so perk removed the family at
  the reload's `session_start`.
- **W1-L5**: the reload did not re-activate the codemode that perk had suspended
  (`DIAG W1-L5 PERK before-reload-active:codemode=no`,
  `DIAG W1-L5 PERK after-reload-active:codemode=no`).
- **W1-L6**: the mixed server's `direct` tool was activated on registration in both arms
  (`DIAG W1-L6 PERK status-active=yes`). Only the deferred tool depends on the pending set.

### RESULT lines — 1.0.0 post-fix (`$SCRATCH/postfix-1.0.0.log`, `$WT` at `d1a7d263`)

```
RESULT W1-L1 PERK KEPT declared=yes
RESULT W1-L1 CONTROL KEPT declared=yes
RESULT W1-L2 PERK KEPT declared=yes
RESULT W1-L2 CONTROL KEPT declared=yes
RESULT W1-L2b PERK KEPT declared=yes
RESULT W1-L2b CONTROL KEPT declared=yes
RESULT W1-L3 PERK KEPT declared=yes
RESULT W1-L3 CONTROL KEPT declared=yes
RESULT W1-L4 PERK KEPT declared=no
RESULT W1-L4 CONTROL KEPT declared=yes
RESULT W1-L5 PERK KEPT declared=no
RESULT W1-L5 CONTROL KEPT declared=yes
RESULT W1-L6 PERK KEPT declared=yes
RESULT W1-L6 CONTROL KEPT declared=yes
RESULT W1-G1 PERK KEPT declared=no
RESULT W1-G1 CONTROL KEPT declared=yes
RESULT W1-G1-CD CONTROL LOST declared=no
RESULT W1-G1-CA CONTROL KEPT declared=yes
RESULT S1 PERK LOST declared=n/a
RESULT S1-C CONTROL LOST declared=n/a
RESULT W2-T1 PERK KEPT declared=n/a
RESULT W2-T1-C CONTROL KEPT declared=n/a
RESULT W2-T2 PERK KEPT declared=n/a
RESULT W2-T2-C CONTROL KEPT declared=n/a
RESULT W2-T2-CD CONTROL LOST declared=n/a
RESULT W2-T2-CA CONTROL KEPT declared=n/a
```

`declared=no` on the PERK arm of W1-L4, W1-L5 and W1-G1 is the read-only presentation, not a
loss. A foreign MCP tool is `unknown`-posture: under the gate it is active but hidden, and the
backstop blocks it. The outcome is the active set. In the post-fix L2b run, perk deferred the
family's removal (`DIAG W1-L2b PERK after-reload-active:objective_stack_status=yes`), and the
family was inactive after the census prompt.

### Classification (1.0.0 only feeds the ladder)

| Row | Kind | C | P pre | CD | CA | Pre-fix | P post | Post-fix |
|---|---|---|---|---|---|---|---|---|
| W1-L1 | automatic | KEPT | LOST | | | `PERK-INDUCED LOSS` | KEPT | `FIXED` |
| W1-L2 | automatic | KEPT | KEPT | | | `PARITY` | KEPT | `PARITY` |
| W1-L2b | automatic | KEPT | LOST | | | `PERK-INDUCED LOSS` | KEPT | `FIXED` |
| W1-L3 | automatic | KEPT | LOST | | | `PERK-INDUCED LOSS` | KEPT | `FIXED` |
| W1-L4 | automatic | KEPT | LOST | | | `PERK-INDUCED LOSS` | KEPT | `FIXED` |
| W1-L5 | automatic | KEPT | LOST | | | `PERK-INDUCED LOSS` | KEPT | `FIXED` |
| W1-L6 | automatic | KEPT | LOST | | | `PERK-INDUCED LOSS` | KEPT | `FIXED` |
| W1-G1 | gesture | KEPT | LOST | LOST | KEPT | `RULE-PARITY` | KEPT | `FIXED` (`PARITY`) |
| S1 | automatic | LOST | LOST | | | `NO-WINDOW` | LOST | `NO-WINDOW` |
| W2-T1 | automatic | KEPT | KEPT | | | `PARITY` | KEPT | `PARITY` |
| W2-T2 | gesture | KEPT | LOST | LOST | KEPT | `RULE-PARITY` | KEPT | `FIXED` (`PARITY`) |

The control stayed the same before and after the fix, as it should: perk is absent from it.
Every 0.99.2 row is `NO-WINDOW` (C LOST) both times. No 0.99.2 control kept the tool, so nothing
goes under falsified assumptions. W2-T2 is classified as a gesture row because the plan supplied
CD/CA controls for it: the `/tree` navigation that opens the window is also the stage change.
W2-T1 has no CD/CA and stayed `PARITY`.

## Pi's documented rule and perk's rule

**Pi's rule (source-derived).** `test/suite/agent-session-mcp.test.ts@v1.0.0` pins "drops" and
"keeps" with `"%s restored tools when an extension sets the loadout before they register"`. An
extension calling `pi.setActiveTools(["read"])` at `session_start` drops the restored tool; one
that only adds keeps it ("Like plan mode restoring its tools, or an extension adding one to the
current loadout."). The suite also pins "does not activate restored tools that register after the
next prompt starts". Pi's own example `examples/extensions/plan-mode/index.ts@v1.0.0` calls
`pi.setActiveTools(getPlanModeTools(…))` from its `session_start` handler through
`enablePlanModeTools()`. Pi therefore treats an extension-imposed loadout at `session_start` as
legitimate, and it drops restored tools.

**perk's rule.** perk goes further than Pi's own extensions. From a `session_start` with reason
`reload` (or a `session_tree`) until the next `agent_start`, every perk install only adds:

- A removal-bearing reconciliation installs the live set plus its additions. That is one install,
  and an identical list is included, so Pi re-runs the loadout hooks for the new landing.
- The removals land at `agent_start`: the cohort's family deferral, the stage diet and the
  codemode suspension.
- Gate enforcement is immediate.
- A prime inside the window lifts the member's pending deferral, so the member survives the close.

The reason is that perk's removals happen at automatic points the user never chose. A `/reload`
in a cohort session would otherwise lose every restored MCP tool, which is what rows L1–L6 showed.
The gesture rows that were `RULE-PARITY` are fixed by the same rule, since a gesture's
deactivation waits as well.

## The fix

`extension/substrate/toolGating.ts`, inside `registerToolGating`:

- **The `restorationWindow` flag.** It is set by gating's own `session_start` handler
  (`reason === "reload"`) and `session_tree` handler. Both are registered before index.ts
  subscribes its handlers, so the flag is set before that event's `syncFromState`.
- **The `agent_start` handler (the closing point).** It closes the window and calls
  `apply(active, stageId)` in its own `try/catch`. It is idempotent: a run that opened no window
  installs nothing, so the zero-call pins stay green.
- **`apply`.** When the window is open and the target has removals, it installs
  `live ∪ additions`. It leaves the `suspended` and `pendingDeferral` memos for the closing apply.
- **`prepareLoadout` hides by name.** It hides `hiddenDeclarationsFor(every registered name, …)`
  plus every `deferred` member that the applied loadout does not declare. `hiddenDeclarationsFor`
  itself is untouched.
- **`primeDeferred`.** It lifts a live member's pending deferral and returns it. When nothing else
  needs adding, it makes an identical install.

**Regression pins.**

- `toolGating.test.ts` (fake host) covers:
  - the window openers;
  - one only-adding install for a join, a stage sync and a codemode-suspending gate entry;
  - in-window presentation;
  - the closing install hiding every removed name;
  - unmasking on activation;
  - the close landing the pre-change target and clearing the memos;
  - the in-window prime;
  - startup staying shut;
  - a bare session's `agent_start` installing nothing;
  - a throwing close keeping the deferral pending;
  - the swept "hides every ineligible registered name per landing" pin.
- `restorationWindow.test.ts` (Mode A) covers:
  - an inline late-registering `deferred` tool across `/reload` in a cohort `implement` session
    and a read-only `objective-plan` session;
  - the `PerkInstall { names, before }` record, used to prove every in-window install only adds;
  - the version-gated `late_probe` restoration;
  - the first census request clean of every removed name;
  - a `sendMessage`-triggered turn inside the window.

**Swept pins.**

- `discoveryPilot.test.ts`: "reload (A)" and "priming resets (A)".
- The `ownNamesActivation.test.ts` (B) landing helper.
- `stageTools.test.ts` "tree navigation: gate/stage recompute across mode entries". This one was
  not in the plan's list. It asserted an immediate removal after `navigateTo`.

**Measured pin runs:**

- 0.99.2: the full extension suite before the stageTools sweep read `ℹ tests 3590` /
  `ℹ pass 3589` / `ℹ fail 1`, the one failure being that pin; the run-all `run_ci` gates the
  final state.
- 1.0.0 throwaway: `node --test …/toolGating.test.ts …/discoveryPilot.test.ts
  …/ownNamesActivation.test.ts …/stageTools.test.ts …/restorationWindow.test.ts` gave
  `ℹ tests 77` / `ℹ pass 77` / `ℹ fail 0`, with the version gate at
  `1.0.0 restoresPending= true` (`$SCRATCH/postfix-1.0.0-pins.log`). So the version-gated
  `late_probe` assertions ran there.
- `restorationWindow.test.ts` alone on 1.0.0 passed 2/2 (`$SCRATCH/postfix-1.0.0-regression.log`).
- On 0.99.2 the same gate is false and those assertions are skipped.

**Vacuity proofs (measured, 0.99.2).** With `toolGating.ts` reverted to `f178a0e3`, the two Mode A
tests, four of the five fake-host window pins (all but "stays shut at startup") and the swept
hidden-name pin fail (`ℹ pass 28` / `ℹ fail 7` over the two files).
With the window rule kept but `prepareLoadout` reverted to the declared-list mask, both Mode A
tests fail on the first-request check (`implement read-write: objective_stack_status undeclared in
the first request`).

### Considered and rejected

- **`defaultActive: false` registration**, with perk adding the eligible set. It still needs an
  in-window removal for the nonparticipant→cohort flip (L2b) and for landing changes. It also turns
  every startup into an additive install, which breaks the zero-call pins.
- **Closing at `before_agent_start`.** Pi's clear comes after every `before_agent_start` handler,
  so perk's removal there clears the set during the MCP extension's `waitForDirectServers` wait.
  Row W1-L6 is exactly that interval. This option also misses `sendMessage`-triggered turns.
- **The declared-list mask** (the existing `hiddenDeclarationsFor(declared, …)`, or
  `declared ∩ pendingDeferral`). The hook run inside the closing install sees the post-removal
  declared list and forgets exactly the names the first request still declares. This was measured
  failing on 0.99.2 (vacuity proof above).

### Residual (measured)

The first request after a cohort `/reload` is built before the close. `$SCRATCH/residual-*.log`
is a scratch probe: cohort `implement`, a census, `/reload`, then two censuses. Its output,
identical on 0.99.2 and 1.0.0 post-fix:

```
RESIDUAL objective_stack_status declared(first)=false snippet(baseline)=false snippet(first)=true snippet(second)=false guideline(baseline)=false guideline(first)=true guideline(second)=false
RESIDUAL collect_review_wave declared(first)=false snippet(baseline)=false snippet(first)=true snippet(second)=false guideline(baseline)=false guideline(first)=true guideline(second)=false
RESIDUAL collect_draft_review_wave declared(first)=false snippet(baseline)=false snippet(first)=false snippet(second)=false guideline(baseline)=false guideline(first)=true guideline(second)=false
RESIDUAL push_annotations declared(first)=false snippet(baseline)=false snippet(first)=true snippet(second)=false guideline(baseline)=false guideline(first)=true guideline(second)=false
```

The probe (scratch, disposed with the scaffold):

```ts
// Scratch probe (not committed): does the first request after a cohort /reload carry the family's
// prompt snippets / guidelines (presentation residual of the restoration-window rule)?
import { before, test } from "node:test";
import {
  COHORT_SETTINGS,
  recordingRuntime,
  staged,
  toolSearch,
} from "../extension/testing/harness.ts";
import { ensureToolCatalog } from "../extension/testing/toolCatalog.ts";
import { discoveryFamily } from "../extension/substrate/toolPolicy.ts";

before(ensureToolCatalog);

test("snippet residual", async () => {
  const rt = await recordingRuntime();
  const h = await staged("implement", "read-write", {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    extraExtensions: [toolSearch()],
    settings: COHORT_SETTINGS,
  });
  try {
    rt.census();
    await h.session.prompt("census");
    const baseline = rt.last();
    await h.reload();
    const before = rt.requests.length;
    rt.census();
    await h.session.prompt("census");
    const first = rt.requests[before];
    rt.census();
    await h.session.prompt("census");
    const second = rt.last();
    for (const name of discoveryFamily()) {
      const snippetLine = `- ${name}: `;
      const guidelines = h.registeredTool(name)?.promptGuidelines ?? [];
      console.log(
        `RESIDUAL ${name} declared(first)=${first?.tools.includes(name)} snippet(baseline)=${baseline.prompt.includes(snippetLine)} snippet(first)=${first?.prompt.includes(snippetLine)} snippet(second)=${second.prompt.includes(snippetLine)} guideline(baseline)=${guidelines.some((g) => baseline.prompt.includes(g))} guideline(first)=${guidelines.some((g) => first?.prompt.includes(g))} guideline(second)=${guidelines.some((g) => second.prompt.includes(g))}`,
      );
    }
  } finally {
    h.dispose();
  }
});
```

On pre-fix code (0.99.2) every field read `false`. So for one request, the fix moves the family's
guidelines and the eligible members' snippets into that first request's system prompt. Their
declarations stay hidden. The guidelines of every name the close removes behave the same way:
Pi renders a hidden-but-active tool's guidelines, which is the existing presentation contract. The
alternative of editing `selectedTools` in `before_agent_start` would drop a tool that registers
during a later handler's wait (L6), so the residual is accepted. It is recorded in §8.40 and in
`model-tools.md`.

## Falsified planning-time assumptions and deviations

- **Falsified, from the plan's own drafting** (each re-verified against the mirror; the last one
  measured here):
  - The first draft assumed harness Mode A matched production order. It is reversed; Mode B
    matches.
  - The first draft assumed `before_agent_start` was Pi's close. Pi clears in `_runAgentPrompt`,
    after every `before_agent_start` handler.
  - The second draft assumed the declared-list mask would hide the removed names. It does not, as
    measured on 0.99.2.
- **Every row prediction held** on both hosts. No 0.99.2 control kept the tool.
- **Not anticipated:** the [first-request prompt residual](#residual-measured).
- **Deviations from the plan's procedure:**
  - The script awaits a `fake.held()` arrival promise before `release()`. On W1 rows the MCP
    connection is created after `reload()` returns (`setImmediate`, then the transport), so this is
    deterministic and uses no timers.
  - Every W2/S1 arm runs over a fresh copy of the planted session file, so appends and navigation
    never leak across rows.
  - The W2-T2 CD/CA handlers are armed only for the restoring navigation.
  - Each arm emits `session_shutdown` before `dispose()`.
  - DIAG lines were added.
  - The plan's Step 4.5 expected a `/reload` sentence in `native-discovery-pilot.md`. There was
    none, so §2 gained one sentence instead. Rows P2/P3 are untouched.
  - The 1.0.0 host resolved newer floating transitive packages than node 1.1 did (pi-protocol
    1.0.4, chord 1.0.4, pi-telemetry 1.0.3).
- **Not material:** each node:test process stayed alive for some seconds after its last test
  (open handles). Durations were 6–16 s and no result depended on it.

## Consumers

- **5.1 "EVIDENCE AND RESTORATION — delayed MCP registration vs control"** re-runs the script
  below, from this record, on a published-1.0.0 host.
- **3.3** inherits the fake-server shape (Pi's `createInMemoryTransportPair`, a responder that
  holds `initialize`) and the isolation lesson: set `PI_CODING_AGENT_DIR` before Pi loads, and give
  `createMcpExtension` an explicit `logPath`.
- **contracts.md §8.40** (**Restoration window**, the reconciliation points, **The loadout host**,
  the codemode exception, **Ordering facts**, **Resets**) is the binding consumer.

## The script (verbatim)

Run from a worktree root as `node --test .perk-characterization/mcp-restoration.test.ts`. It was
byte-identical on both hosts (`cmp` before the post-fix run).

```ts
// Throwaway measurement script (record-only): does perk's first reconciliation after `/reload` or a
// `/tree` restore clear Pi's pending-restoration set, against a CONTROL session without perk?
// Each matrix row is one `test()`; the script PRINTS `RESULT <row> <arm> <KEPT|LOST> declared=…`
// lines and asserts only fixture liveness. Classification is the record's, never the script's.
//
// Run from the worktree root: `node --test .perk-characterization/mcp-restoration.test.ts`.

import assert from "node:assert/strict";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

// Global-tier isolation BEFORE Pi loads: `getAgentDir()` must never resolve the operator's agent dir.
const scratch = mkdtempSync(join(tmpdir(), "perk-mcp-restoration-"));
process.env.PI_CODING_AGENT_DIR = join(scratch, "agent");
mkdirSync(process.env.PI_CODING_AGENT_DIR, { recursive: true });

const pca = await import("@earendil-works/pi-coding-agent");
const harness = await import("../extension/testing/harness.ts");
const {
  createAgentSession,
  createCodemodeExtension,
  createMcpExtension,
  DefaultResourceLoader,
  SessionManager,
  SettingsManager,
  VERSION,
} = pca;
const {
  COHORT_SETTINGS,
  loadAt,
  PERK_EXTENSION_PATH,
  plantSession,
  recordingRuntime,
  scaffoldRepo,
  staged,
  toolSearch,
} = harness;

type AgentSession = InstanceType<typeof pca.AgentSession>;
type InlineExtension = import("@earendil-works/pi-coding-agent").InlineExtension;
type PerkSession = import("../extension/testing/harness.ts").PerkSession;
type Recorder = Awaited<ReturnType<typeof recordingRuntime>>;

const TOOL = "mcp__docs__search";
const MCP_PATH = "builtin:mcp";
const PROBE_PATH = "builtin:probe";

// --- the fake MCP server (Pi's own in-memory transport pair; only the responder is hand-written) ---

const pcaIndex = fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"));
const pcaRoot = resolve(dirname(pcaIndex), "..");
const pcaPkg = JSON.parse(readFileSync(join(pcaRoot, "package.json"), "utf8")) as {
  version: string;
};

async function loadMcpTesting(): Promise<{
  createInMemoryTransportPair: () => { client: McpTransport; server: McpTransport };
  from: string;
  version: string;
}> {
  const nested = join(pcaRoot, "node_modules", "@earendil-works", "pi-mcp");
  const root = existsSync(join(nested, "package.json"))
    ? nested
    : resolve(dirname(fileURLToPath(import.meta.resolve("@earendil-works/pi-mcp"))), "..");
  const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as {
    version: string;
    exports: Record<string, { import: string }>;
  };
  const entry = pkg.exports["./testing"]?.import;
  const from = entry === undefined ? `${root} (no ./testing export)` : join(root, entry);
  try {
    assert.ok(entry !== undefined, "pi-mcp exports ./testing");
    const mod = (await import(pathToFileURL(from).href)) as {
      createInMemoryTransportPair: () => { client: McpTransport; server: McpTransport };
    };
    assert.equal(typeof mod.createInMemoryTransportPair, "function");
    return { createInMemoryTransportPair: mod.createInMemoryTransportPair, from, version: pkg.version };
  } catch (error) {
    throw new Error(`fixture preflight: pi-mcp testing export failed to load from ${from}: ${error}`);
  }
}

type JsonRpc = { jsonrpc: "2.0"; id?: number | string; method?: string; params?: { protocolVersion?: string } };
type McpTransport = {
  start(): Promise<void>;
  send(message: unknown): Promise<void>;
  close(): Promise<void>;
  onMessage(listener: (message: JsonRpc) => void): () => void;
};

const mcpTesting = await loadMcpTesting();

type McpTool = { name: string; description: string; inputSchema: Record<string, unknown> };
const SEARCH: McpTool = {
  name: "search",
  description: "Search the docs index for pages matching a query.",
  inputSchema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
};
const STATUS: McpTool = {
  name: "status",
  description: "Report the docs index status.",
  inputSchema: { type: "object", properties: {} },
};

type Fake = {
  connections: number;
  /** Hold the NEXT connection's `initialize`; returns a promise that resolves when it arrives. */
  holdNext(): void;
  /** Resolves when the held `initialize` has arrived at the server. */
  held(): Promise<void>;
  /** Answer the held `initialize`. */
  release(): void;
  client(): McpTransport;
};

function fakeServer(tools: readonly McpTool[]): Fake {
  let holdArmed = false;
  let arrived: Promise<void> = Promise.resolve();
  let markArrived: (() => void) | undefined;
  let releaseHeld: (() => void) | undefined;
  const fake: Fake = {
    connections: 0,
    holdNext() {
      holdArmed = true;
      arrived = new Promise((r) => {
        markArrived = r;
      });
    },
    held: () => arrived,
    release() {
      const release = releaseHeld;
      releaseHeld = undefined;
      assert.ok(release !== undefined, "fixture: a held initialize to release");
      release();
    },
    client() {
      fake.connections += 1;
      const { client, server } = mcpTesting.createInMemoryTransportPair();
      let gate: Promise<void> | undefined;
      if (holdArmed) {
        holdArmed = false;
        gate = new Promise((r) => {
          releaseHeld = r;
        });
      }
      const signal = markArrived;
      markArrived = undefined;
      server.onMessage(async (message) => {
        if (message.id === undefined || typeof message.method !== "string") return;
        let result: unknown = {};
        if (message.method === "initialize") {
          if (gate !== undefined) {
            signal?.();
            await gate;
          }
          result = {
            protocolVersion: message.params?.protocolVersion,
            capabilities: { tools: {} },
            serverInfo: { name: "docs", version: "1.0.0" },
          };
        } else if (message.method === "tools/list") {
          result = { tools };
        } else if (message.method === "tools/call") {
          result = { content: [{ type: "text", text: "ok" }] };
        }
        await server.send({ jsonrpc: "2.0", id: message.id, result }).catch(() => {});
      });
      void server.start();
      return client;
    },
  };
  return fake;
}

// --- the factories --------------------------------------------------------------------------------

let logSeq = 0;
function mcp(fake: Fake, mixed = false): InlineExtension {
  return {
    name: "mcp",
    factory: createMcpExtension({
      loadConfig: () => ({
        servers: [
          {
            name: "docs",
            config: {
              url: "http://unused.invalid",
              exposure: "deferred",
              ...(mixed ? { toolExposure: { status: "direct" } } : {}),
            },
            source: "scratch",
          },
        ],
        errors: [],
      }),
      createTransport: () => fake.client() as never,
      logPath: join(scratch, `mcp-${++logSeq}.log`),
    }),
    builtin: true,
  } as InlineExtension;
}

type Probe = { arm(): Promise<void>; extension: InlineExtension };
function probe(): Probe {
  let resolveCurrent: (() => void) | undefined;
  return {
    arm() {
      return new Promise<void>((r) => {
        resolveCurrent = r;
      });
    },
    extension: {
      name: "probe",
      factory: (pi) => {
        pi.on("before_agent_start", () => {
          const r = resolveCurrent;
          resolveCurrent = undefined;
          r?.();
        });
      },
      builtin: true,
    } as InlineExtension,
  };
}

const codemode = (): InlineExtension =>
  ({ name: "codemode", factory: createCodemodeExtension({ mode: "on" }), builtin: true }) as InlineExtension;

// --- arms -----------------------------------------------------------------------------------------

type Arm = {
  label: "PERK" | "CONTROL";
  session: AgentSession;
  rt: Recorder;
  fake: Fake;
  h?: PerkSession;
  dispose(): Promise<void>;
};

type Landing = { stage?: string; mode: "read-only" | "read-write" };

async function perkArm(opts: {
  landing: Landing;
  fake: Fake;
  extensions: InlineExtension[];
  settings?: Record<string, unknown>;
  over?: { cwd: string; file: string };
}): Promise<Arm> {
  const rt = await recordingRuntime();
  const base = {
    headful: false,
    packages: [],
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    extraExtensions: opts.extensions,
    ...(opts.settings !== undefined ? { settings: opts.settings } : {}),
  };
  const h =
    opts.over !== undefined
      ? await loadAt(opts.over.cwd, {
          ...base,
          sessionManager: SessionManager.open(opts.over.file),
          env: { PERK_RUN_ID: undefined },
        })
      : opts.landing.stage !== undefined
        ? await staged(opts.landing.stage, opts.landing.mode, base)
        : await loadAt(scaffoldRepo(), { ...base, env: { PERK_RUN_ID: undefined } });
  const paths = h.session.extensionRunner.getExtensionPaths();
  const perkAt = paths.indexOf(PERK_EXTENSION_PATH);
  assert.ok(perkAt !== -1, `fixture: perk bound by path (${paths.join(", ")})`);
  assert.ok(perkAt < paths.indexOf(MCP_PATH), `fixture: perk precedes ${MCP_PATH} (${paths.join(", ")})`);
  if (paths.includes(PROBE_PATH))
    assert.ok(paths.indexOf(PROBE_PATH) < paths.indexOf(MCP_PATH), "fixture: probe precedes mcp");
  const state = h.workflowState();
  assert.equal(state.stage ?? undefined, opts.landing.stage, "fixture: the perk arm's stage");
  assert.equal(state.mode ?? "read-write", opts.landing.mode, "fixture: the perk arm's mode");
  assert.equal(h.sentinel()?.mode ?? "read-write", opts.landing.mode, "fixture: the mode sentinel");
  return {
    label: "PERK",
    session: h.session,
    rt,
    fake: opts.fake,
    h,
    async dispose() {
      await shutdown(h.session);
      h.dispose();
    },
  };
}

async function controlArm(opts: {
  fake: Fake;
  extensions: InlineExtension[];
  settings?: Record<string, unknown>;
  over?: { cwd: string; file: string };
}): Promise<Arm> {
  const rt = await recordingRuntime();
  const cwd = opts.over?.cwd ?? mkdtempSync(join(tmpdir(), "perk-mcp-control-cwd-"));
  const agentDir = mkdtempSync(join(tmpdir(), "perk-mcp-control-agent-"));
  const resourceLoader = new DefaultResourceLoader({
    cwd,
    agentDir,
    extensionFactories: opts.extensions,
  });
  await resourceLoader.reload();
  const { session } = await createAgentSession({
    cwd,
    agentDir,
    model: rt.reg.getModel() as never,
    modelRuntime: rt.reg.modelRuntime,
    resourceLoader,
    sessionManager:
      opts.over !== undefined ? SessionManager.open(opts.over.file) : SessionManager.inMemory(cwd),
    settingsManager: SettingsManager.inMemory({
      compaction: { enabled: false },
      retry: { enabled: false },
      ...(opts.settings ?? {}),
    }),
  });
  await session.bindExtensions({
    mode: "print",
    onError: (err) => console.error(`control: extension error in ${err.event}: ${err.error}`),
  });
  const paths = session.extensionRunner.getExtensionPaths();
  assert.ok(!paths.includes(PERK_EXTENSION_PATH), "fixture: the control carries no perk");
  if (paths.includes(PROBE_PATH))
    assert.ok(paths.indexOf(PROBE_PATH) < paths.indexOf(MCP_PATH), "fixture: probe precedes mcp");
  return {
    label: "CONTROL",
    session,
    rt,
    fake: opts.fake,
    async dispose() {
      await shutdown(session);
      session.dispose();
    },
  };
}

async function shutdown(session: AgentSession): Promise<void> {
  try {
    await session.extensionRunner.emit({ type: "session_shutdown", reason: "quit" } as never);
  } catch {}
}

// --- observation helpers --------------------------------------------------------------------------

const isRegistered = (s: AgentSession) => s.getAllTools().some((t) => t.name === TOOL);
const isActive = (s: AgentSession, name = TOOL) => s.getActiveToolNames().includes(name);
const yn = (b: boolean) => (b ? "yes" : "no");

async function registration(s: AgentSession): Promise<void> {
  const deadline = Date.now() + 5000;
  while (!isRegistered(s)) {
    if (Date.now() > deadline) throw new Error(`fixture: ${TOOL} never registered`);
    await new Promise((r) => setTimeout(r, 5));
  }
}

function result(row: string, arm: string, kept: boolean, declared: string): void {
  console.log(`RESULT ${row} ${arm} ${kept ? "KEPT" : "LOST"} declared=${declared}`);
}

function diag(row: string, arm: string, key: string, value: unknown): void {
  console.log(`DIAG ${row} ${arm} ${key}=${typeof value === "string" ? value : JSON.stringify(value)}`);
}

/** Load the tool into the active set and the transcript, then assert it is live. */
async function seed(arm: Arm, via: "tool_search" | "set"): Promise<void> {
  await registration(arm.session);
  if (via === "tool_search") {
    arm.rt.callThenStop("tool_search", { query: "search the docs" });
    await arm.session.prompt("load");
  } else {
    arm.session.setActiveToolsByName([...arm.session.getActiveToolNames(), TOOL]);
    arm.rt.census();
    await arm.session.prompt("save");
  }
  assert.ok(isActive(arm.session), "fixture: the tool is active before the window opens");
}

/** A census prompt; returns whether its first request declared the tool. */
async function census(arm: Arm): Promise<string> {
  const before = arm.rt.requests.length;
  arm.rt.census();
  await arm.session.prompt("census");
  const request = arm.rt.requests[before];
  assert.ok(request !== undefined, "fixture: the census made a request");
  return yn(request.tools.includes(TOOL));
}

// --- W1: /reload ----------------------------------------------------------------------------------

async function w1(
  row: string,
  arm: Arm,
  opts: { via: "tool_search" | "set"; gesture?: (arm: Arm) => Promise<void>; watch?: string[] } = {
    via: "tool_search",
  },
): Promise<void> {
  try {
    await seed(arm, opts.via);
    for (const name of opts.watch ?? []) diag(row, arm.label, `before-reload-active:${name}`, yn(isActive(arm.session, name)));
    const connections = arm.fake.connections;
    arm.fake.holdNext();
    await arm.session.reload();
    diag(row, arm.label, "in-window-registered", yn(isRegistered(arm.session)));
    for (const name of opts.watch ?? []) diag(row, arm.label, `after-reload-active:${name}`, yn(isActive(arm.session, name)));
    await arm.fake.held();
    assert.equal(arm.fake.connections, connections + 1, "fixture: exactly one new connection");
    if (opts.gesture !== undefined) await opts.gesture(arm);
    assert.ok(!isRegistered(arm.session), "fixture: unregistered immediately before release");
    arm.fake.release();
    await registration(arm.session);
    assert.equal(arm.fake.connections, connections + 1, "fixture: the held connection registered it");
    const kept = isActive(arm.session);
    const declared = await census(arm);
    result(row, arm.label, kept, declared);
    diag(row, arm.label, "active-after-census", yn(isActive(arm.session)));
  } finally {
    await arm.dispose();
  }
}

const cohortExt = (fake: Fake) => [toolSearch(), mcp(fake)];

test("header", async () => {
  console.log(`HEADER VERSION=${VERSION} node=${process.version}`);
  console.log(`HEADER pi-coding-agent=${join(pcaRoot, "package.json")} version=${pcaPkg.version}`);
  console.log(`HEADER pi-mcp/testing=${mcpTesting.from} version=${mcpTesting.version}`);
  const fp = fakeServer([SEARCH]);
  const p = await perkArm({ landing: { mode: "read-write" }, fake: fp, extensions: cohortExt(fp), settings: COHORT_SETTINGS });
  console.log(`HEADER perk-order=${JSON.stringify(p.session.extensionRunner.getExtensionPaths())}`);
  await p.dispose();
  const fc = fakeServer([SEARCH]);
  const c = await controlArm({ fake: fc, extensions: cohortExt(fc), settings: COHORT_SETTINGS });
  console.log(`HEADER control-order=${JSON.stringify(c.session.extensionRunner.getExtensionPaths())}`);
  await c.dispose();
});

// W1-L1: cohort, unscoped, read-write (the converged default). Control C-cohort.
test("W1-L1", async () => {
  const fp = fakeServer([SEARCH]);
  await w1("W1-L1", await perkArm({ landing: { mode: "read-write" }, fake: fp, extensions: cohortExt(fp), settings: COHORT_SETTINGS }));
  const fc = fakeServer([SEARCH]);
  await w1("W1-L1", await controlArm({ fake: fc, extensions: cohortExt(fc), settings: COHORT_SETTINGS }));
});

// W1-L2: nonparticipant, no tool_search registered. Control C-nosearch.
test("W1-L2", async () => {
  const fp = fakeServer([SEARCH]);
  await w1("W1-L2", await perkArm({ landing: { mode: "read-write" }, fake: fp, extensions: [mcp(fp)] }), { via: "set" });
  const fc = fakeServer([SEARCH]);
  await w1("W1-L2", await controlArm({ fake: fc, extensions: [mcp(fc)] }), { via: "set" });
});

// W1-L2b: nonparticipant at startup; the MCP extension activates tool_search after perk's
// session_start, so the reload flips perk into the cohort. Control C-latesearch.
test("W1-L2b", async () => {
  const fp = fakeServer([SEARCH]);
  const p = await perkArm({ landing: { mode: "read-write" }, fake: fp, extensions: cohortExt(fp) });
  diag("W1-L2b", "PERK", "startup-cohort", yn(p.h?.toolInfo("objective_stack_status")?.exposure === "deferred"));
  await w1("W1-L2b", p, {
    via: "tool_search",
    watch: ["tool_search", "objective_stack_status"],
  });
  const fc = fakeServer([SEARCH]);
  await w1("W1-L2b", await controlArm({ fake: fc, extensions: cohortExt(fc) }), {
    via: "tool_search",
    watch: ["tool_search"],
  });
});

// W1-L3: cohort, implement/read-write. Control C-cohort.
test("W1-L3", async () => {
  const fp = fakeServer([SEARCH]);
  await w1("W1-L3", await perkArm({ landing: { stage: "implement", mode: "read-write" }, fake: fp, extensions: cohortExt(fp), settings: COHORT_SETTINGS }));
  const fc = fakeServer([SEARCH]);
  await w1("W1-L3", await controlArm({ fake: fc, extensions: cohortExt(fc), settings: COHORT_SETTINGS }));
});

// W1-L4: cohort, objective-plan/read-only, codemode absent. Control C-cohort.
test("W1-L4", async () => {
  const fp = fakeServer([SEARCH]);
  await w1("W1-L4", await perkArm({ landing: { stage: "objective-plan", mode: "read-only" }, fake: fp, extensions: cohortExt(fp), settings: COHORT_SETTINGS }));
  const fc = fakeServer([SEARCH]);
  await w1("W1-L4", await controlArm({ fake: fc, extensions: cohortExt(fc), settings: COHORT_SETTINGS }));
});

// W1-L5: cohort, objective-plan/read-only, codemode registered and suspended before the reload.
// Control C-codemode.
test("W1-L5", async () => {
  const settings = { defaultTools: ["+tool_search", "+codemode"] };
  const fp = fakeServer([SEARCH]);
  await w1("W1-L5", await perkArm({ landing: { stage: "objective-plan", mode: "read-only" }, fake: fp, extensions: [toolSearch(), codemode(), mcp(fp)], settings }), {
    via: "tool_search",
    watch: ["codemode"],
  });
  const fc = fakeServer([SEARCH]);
  await w1("W1-L5", await controlArm({ fake: fc, extensions: [toolSearch(), codemode(), mcp(fc)], settings }), {
    via: "tool_search",
    watch: ["codemode"],
  });
});

// W1-L6: cohort implement/read-write with a mixed-exposure server: the reconnect completes during
// the MCP extension's `before_agent_start` wait of the measured prompt. Control C-mixed.
async function l6(arm: Arm, pr: Probe): Promise<void> {
  try {
    const seeded = pr.arm();
    await seed(arm, "tool_search");
    await seeded;
    arm.fake.holdNext();
    await arm.session.reload();
    diag("W1-L6", arm.label, "in-window-registered", yn(isRegistered(arm.session)));
    const waitStarted = pr.arm();
    const before = arm.rt.requests.length;
    arm.rt.census();
    const run = arm.session.prompt("census");
    await waitStarted;
    await arm.fake.held();
    assert.equal(arm.rt.requests.length, before, "fixture: no request before the release");
    assert.ok(!isRegistered(arm.session), "fixture: unregistered immediately before release");
    arm.fake.release();
    await run;
    assert.equal(arm.rt.requests.length, before + 1, "fixture: the measured prompt made one request");
    assert.ok(isRegistered(arm.session), "fixture: registered during the wait");
    const request = arm.rt.requests[before];
    assert.ok(request !== undefined);
    result("W1-L6", arm.label, isActive(arm.session), yn(request.tools.includes(TOOL)));
    diag("W1-L6", arm.label, "status-active", yn(isActive(arm.session, "mcp__docs__status")));
  } finally {
    await arm.dispose();
  }
}

test("W1-L6", async () => {
  const fp = fakeServer([SEARCH, STATUS]);
  const pp = probe();
  await l6(
    await perkArm({ landing: { stage: "implement", mode: "read-write" }, fake: fp, extensions: [toolSearch(), pp.extension, mcp(fp, true)], settings: COHORT_SETTINGS }),
    pp,
  );
  const fc = fakeServer([SEARCH, STATUS]);
  const pc = probe();
  await l6(await controlArm({ fake: fc, extensions: [toolSearch(), pc.extension, mcp(fc, true)], settings: COHORT_SETTINGS }), pc);
});

// W1-G1: cohort implement/read-write; a gate entry (/plan) inside the window. Controls: C-cohort,
// CONTROL-DEACTIVATING (drops `read`), CONTROL-ADDITIVE (adds `grep`).
test("W1-G1", async () => {
  const fp = fakeServer([SEARCH]);
  await w1("W1-G1", await perkArm({ landing: { stage: "implement", mode: "read-write" }, fake: fp, extensions: cohortExt(fp), settings: COHORT_SETTINGS }), {
    via: "tool_search",
    gesture: async (arm) => {
      await arm.h?.invokeCommand("plan");
      assert.equal(arm.h?.workflowState().mode, "read-only", "fixture: the gate entered in-window");
    },
  });
  const fc = fakeServer([SEARCH]);
  await w1("W1-G1", await controlArm({ fake: fc, extensions: cohortExt(fc), settings: COHORT_SETTINGS }));
  const fd = fakeServer([SEARCH]);
  await w1("W1-G1-CD", await controlArm({ fake: fd, extensions: cohortExt(fd), settings: COHORT_SETTINGS }), {
    via: "tool_search",
    gesture: async (arm) => {
      arm.session.setActiveToolsByName(arm.session.getActiveToolNames().filter((n) => n !== "read"));
    },
  });
  const fa = fakeServer([SEARCH]);
  await w1("W1-G1-CA", await controlArm({ fake: fa, extensions: cohortExt(fa), settings: COHORT_SETTINGS }), {
    via: "tool_search",
    gesture: async (arm) => {
      arm.session.setActiveToolsByName([...arm.session.getActiveToolNames(), "grep"]);
    },
  });
});

// --- W2 (/tree) and S1 (SDK/CLI resume): over a planted cohort implement session ------------------

let planted: { cwd: string; file: string; leaf: string; first: string } | undefined;
let copies = 0;

async function plantedSession(): Promise<{ cwd: string; file: string; leaf: string; first: string }> {
  if (planted !== undefined) return planted;
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ stage: "implement", mode: "read-write" }]);
  const fake = fakeServer([SEARCH]);
  const arm = await perkArm({
    landing: { stage: "implement", mode: "read-write" },
    fake,
    extensions: cohortExt(fake),
    settings: COHORT_SETTINGS,
    over: { cwd, file },
  });
  let leaf: string;
  try {
    await seed(arm, "tool_search");
    await census(arm);
    const id = arm.session.sessionManager.getLeafId();
    assert.ok(id !== null);
    leaf = id;
  } finally {
    await arm.dispose();
  }
  assert.ok(readFileSync(file, "utf8").includes(TOOL), "fixture: the session file names the tool");
  planted = { cwd, file, leaf, first: "c0" };
  return planted;
}

/** A fresh copy of the planted file for one arm (navigation and appends never leak across rows). */
async function copyOfPlanted(): Promise<{ cwd: string; file: string; leaf: string; first: string }> {
  const p = await plantedSession();
  const file = join(p.cwd, `copy-${++copies}.jsonl`);
  copyFileSync(p.file, file);
  return { ...p, file };
}

async function navigate(arm: Arm, id: string): Promise<void> {
  if (arm.h !== undefined) await arm.h.navigateTo(id);
  else {
    await arm.session.navigateTree(id);
    await new Promise((r) => setTimeout(r, 50));
  }
}

async function finishTree(row: string, arm: Arm, connections: number): Promise<void> {
  assert.equal(arm.fake.connections, connections + 1, "fixture: exactly one new connection");
  assert.ok(!isRegistered(arm.session), "fixture: unregistered immediately before release");
  arm.fake.release();
  await registration(arm.session);
  assert.equal(arm.fake.connections, connections + 1, "fixture: the held connection registered it");
  result(row, arm.label, isActive(arm.session), "n/a");
}

test("S1", async () => {
  for (const label of ["PERK", "CONTROL"] as const) {
    const p = await copyOfPlanted();
    const fake = fakeServer([SEARCH]);
    fake.holdNext();
    const arm =
      label === "PERK"
        ? await perkArm({ landing: { stage: "implement", mode: "read-write" }, fake, extensions: cohortExt(fake), settings: COHORT_SETTINGS, over: p })
        : await controlArm({ fake, extensions: cohortExt(fake), settings: COHORT_SETTINGS, over: p });
    try {
      await fake.held();
      await finishTree(label === "PERK" ? "S1" : "S1-C", arm, 0);
    } finally {
      await arm.dispose();
    }
  }
});

test("W2-T1", async () => {
  for (const label of ["PERK", "CONTROL"] as const) {
    const p = await copyOfPlanted();
    const fake = fakeServer([SEARCH]);
    fake.holdNext();
    const arm =
      label === "PERK"
        ? await perkArm({ landing: { stage: "implement", mode: "read-write" }, fake, extensions: cohortExt(fake), settings: COHORT_SETTINGS, over: p })
        : await controlArm({ fake, extensions: cohortExt(fake), settings: COHORT_SETTINGS, over: p });
    try {
      await fake.held();
      await navigate(arm, p.first);
      await navigate(arm, p.leaf);
      await finishTree(label === "PERK" ? "W2-T1" : "W2-T1-C", arm, 0);
    } finally {
      await arm.dispose();
    }
  }
});

/** An inline control extension whose armed `session_tree` handler drops `read` or adds `grep`. */
function treeGesture(kind: "CD" | "CA"): { armed: { on: boolean }; extension: InlineExtension } {
  const armed = { on: false };
  return {
    armed,
    extension: {
      name: `tree-${kind}`,
      factory: (pi) => {
        pi.on("session_tree", () => {
          if (!armed.on) return;
          const live = pi.getActiveTools();
          pi.setActiveTools(kind === "CD" ? live.filter((n) => n !== "read") : [...live, "grep"]);
        });
      },
    } as InlineExtension,
  };
}

test("W2-T2", async () => {
  for (const label of ["PERK", "CONTROL", "CD", "CA"] as const) {
    const p = await copyOfPlanted();
    const fake = fakeServer([SEARCH]);
    fake.holdNext();
    const gesture = label === "CD" || label === "CA" ? treeGesture(label) : undefined;
    const arm =
      label === "PERK"
        ? await perkArm({ landing: { stage: "implement", mode: "read-write" }, fake, extensions: cohortExt(fake), settings: COHORT_SETTINGS, over: p })
        : await controlArm({
            fake,
            extensions: [...cohortExt(fake), ...(gesture !== undefined ? [gesture.extension] : [])],
            settings: COHORT_SETTINGS,
            over: p,
          });
    try {
      await fake.held();
      const toPlan = arm.session.sessionManager.appendCustomEntry("perk:workflow-state", { stage: "plan" });
      await navigate(arm, p.first);
      if (gesture !== undefined) gesture.armed.on = true;
      await navigate(arm, toPlan);
      const row = label === "PERK" ? "W2-T2" : label === "CONTROL" ? "W2-T2-C" : `W2-T2-${label}`;
      await finishTree(row, arm, 0);
      if (arm.h !== undefined) assert.equal(arm.h.workflowState().stage, "plan", "fixture: the stage changed");
    } finally {
      await arm.dispose();
    }
  }
});
```

## Teardown proof

`$SCRATCH/teardown-wt.log`:

```
== git worktree remove --force $WT
exit=0
== git worktree prune
exit=0
== rm -rf scratch agent dirs (the script's own mkdtemp prefixes)
     140
       0
== git worktree list | grep -c pi-1.0.0-mcp-restoration
0
== ls $MAIN/.worktrees | grep -c pi-1.0.0-mcp-restoration
0
== test -e $WT
absent
== git -C $MAIN status --porcelain
 M docs/planning/pi-durable/decision-foundation.md
 M docs/planning/pi-durable/pi-durable-v2.md
 M docs/planning/pi-durable/pi-durable-workflows.md
 M docs/planning/pi-durable/pi-in-the-sky.md
 M docs/planning/pi-durable/vision.md
?? docs/Pi-Durable-Technical-Manual.pdf
```

The main checkout's porcelain is **not** empty. It lists the owner's concurrent
`docs/planning/pi-durable/*` edits and an untracked PDF (mtimes 17:39–17:44 local on the day of
the run). This experiment never wrote to `$MAIN`: every command ran in `$IMPL` or `$WT`, and the
library mirror was only read through `git show`/`git rev-parse`. None of those paths is a file
this PR touches. After the scratch directory was removed, `git -C $IMPL status --porcelain` listed
only this record (below), and it was clean after the commit.

```
$ git -C $IMPL status --porcelain
?? docs/design/archive/pi-1.0.0-mcp-restoration.md
$ git worktree list | grep -c pi-1.0.0-mcp-restoration
0
$ ls $MAIN/.worktrees | grep -c pi-1.0.0-mcp-restoration
0
```
