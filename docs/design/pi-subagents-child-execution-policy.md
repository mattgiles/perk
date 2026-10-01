# Native child execution policy

**Status: accepted and implemented — the collapsed policy.** Perk's native-child policy is two
booleans: the pi-subagents **runner bit** and perk's constant **report restriction packet**. The
collapse was accepted through objective #2308's review-round decision "Floor narrowed to report
children" and landed by plan #2312's PR; that objective and plan are the acceptance record (no
merge-hash ledger is kept here). The historical measurements that motivated the original design —
the native capability protocol, outcomes and disposable sources — live in the
[characterization archive](archive/pi-subagents-child-capability-characterization.md).

## The two booleans

**The runner bit.** `PI_SUBAGENT_CHILD === "1"`, read at every `session_start` by
`extension/substrate/childRestrictions.ts::isRunnerChild`. pi-subagents stamps it on every
background (runner-hosted) child; it is the only kind of child in which perk's extension activates.

**The report restriction packet.** `extensionBindings: {"perk.parent-restrictions/1": {readOnly:
true}}`, a constant every `ReportWave` child receives. With the runner bit it is the whole
authorization input for the child's read-only floor; without the runner bit it is inert.

## Producer

`extension/waves/reportWave.ts::renderWaveScript` embeds the module constant on every rendered
child item, together with `worktree: false` (caller-checkout placement, so the plan-ref-dependent
readers — `/pr-review`, the `/address` classifier — keep working without a per-request policy).
Nothing is sampled from the parent gate, handoff, task or assignment data; explicit field
selection plus whole-array `JSON.stringify` keep hostile task text and extra assignment
properties inert. `createReportWave(bus)` takes no supplier and has no capture-failure arm.

## Consumer

`decodeReadOnlyFloor(runner, raw)` over `PI_SUBAGENT_EXTENSION_BINDINGS` has three outcomes:

- **No packet ⇒ no floor.** `raw === undefined`, or an object envelope with no
  `perk.parent-restrictions/…` key at all (the delegation-dispatched writer's case).
- **Malformed ⇒ floor (fail closed).** Invalid JSON, a non-object envelope, any
  `perk.parent-restrictions/` key other than exactly `/1`, or `/1` with anything but exactly
  `{readOnly: boolean}`. The unsupported-family-version clause stays because an envelope carrying
  only `perk.parent-restrictions/2` would otherwise decode as "no packet" and un-floor the child
  under producer/consumer version skew — what was dropped is the six-reason *classification*, not
  the fail-closed posture.
- **Valid ⇒ the boolean.** `ReportWave` never sends `false`; the case exists so a foreign
  producer's honest `false` is not silently floored.

A non-runner never gets a floor, whatever the envelope. Unrelated namespaces are opaque.

`extension/index.ts` reads both booleans at the top of every `session_start` and **latches** the
floor for the activation (`readOnlyFloor ||= …`): a same-activation `session_start` re-emit, a
gate `exit()`, or a `session_tree` navigation cannot clear it; a `/reload` re-runs the factory and
re-reads the env. The floor composes into `extension/substrate/toolGating.ts` unchanged:
`isActive = active || hasFloor()`, a floor-refused `exit()`, and the all-names `tool_call`
backstop that blocks anything the eligibility formula makes ineligible under the gate (§8.40)
even if the toolset rebuild failed. A
throwing floor supplier is restrictive for that observation.

`session/lifecycle.ts::reflectSessionReadOnlyFloor` keeps the child's persisted mode honest: on an
established non-read-only outcome it appends one verified `{mode: "read-only"}`; an unexpected
failure is reported once (`could not persist child read-only restriction; in-memory restriction
remains active`) and startup continues — enforcement never depended on the reflection.

## Runner children provision no scratch and receive no authoring guidance

`registerAgentScratch(pi, provisioner, eligible)` takes one predicate the composition root builds
as `!gating.isActive() && !runnerChild`. A runner child — every perk report child — never
provisions `.perk/workflow/scratch/runs/<run_id>/agent/` or receives the hidden scratch block, even
without a floor; the module knows nothing about agent names. Authoring and plan-adapter guidance
suppression rides the same runner bit through `installInjectedContext`'s runner fence
(`extension/pi/v1/contextInjection.ts`): every injected authoring/adapter context takes the
composition root's `() => runnerChild` closure as its third argument, and a runner child selects
nothing — no injection, every owned copy retired — before any caller's selector runs.

## Report children survive compaction

**The failure.** A report child's subject rides verbatim in its first user message (`Task: Angle: …`
+ `<untrusted_draft>…</untrusted_draft>` for a draft reviewer; a diff, brief or manifest for the
others), and the lane cannot re-fetch it. A heavy-reading lane fills its context window, Pi
auto-compacts the child mid-run, and the first user message is replaced by a summary; from then on
the lane reconstructs "byte-exact" quotes from memory. Observed on a 63 KB plan's four-lane
draft-review wave in a consumer repo — only the two compacted lanes misquoted:

| lane | tool calls | peak context | compacted mid-run | phrases found in any draft version |
| --- | --- | --- | --- | --- |
| grounding | 209 | 200,845 tok | yes → 20,316 | 0/5 |
| risk | 191 | 206,345 tok | yes → 34,916 | 0/2 |
| decision-completeness | 17 | 72,958 | no | 3/3 |
| ponytail | 46 | 113,015 | no | 2/2 |

The delivery path preserved bytes end to end, `context: "fresh"` was pinned at spawn, and no lane
read a draft-like file. pi-subagents exposes no per-child compaction knob (Pi's
`compaction.enabled` is a settings-global toggle), so the fix lives perk-side, in the extension
that already runs inside every report child.

**Pi's ordering.** Pi runs threshold compaction while preparing the next model request
(`prepareNextTurnWithContext`), and pi-agent-core re-polls steering after preparation — so a steer
queued by a `session_compact` handler there normally reaches the very next request. Pi also runs
a post-run compaction check (`_checkCompaction`) after the run ended, **including after a
`terminate: true` tool result**; if a steer is queued when that compaction finishes, the post-run
loop calls `agent.continue()`.

**The three hooks** (`extension/pi/v1/childTaskRestore.ts` over the pure
`extension/substrate/childTaskRestore.ts`; all inert without a latched floor, so parents and the
floor-less writers keep Pi's ordinary compaction):

- `tool_result` latches **acceptance** — an executed `structured_output` whose result is not an
  error (pi-subagents throws on a schema rejection; a blocked call never executes).
- `session_compact` (every reason) queues the restore: the first user prompt byte-for-byte behind
  a role-neutral preamble, as a visible `perk:task-restore` steer.
- `tool_call` on `structured_output` is the **backstop and re-delivery point**: it queues when
  nothing is in flight and blocks while the prompt is not live in Pi's own projection (typed
  evidence — user content or `perk:task-restore` content carrying the whole prompt; a summary
  quoting it never counts). It covers a restore that was delayed, dropped by a context edit, or
  never sent — a reload onto an already-compacted branch fires no `session_compact`.

The verdict is evaluated in order: accepted ⇒ allow; no prompt ⇒ allow; live ⇒ allow; oversized ⇒
refuse; a restore queued for this compaction and not yet on the branch ⇒ hold; attempts spent ⇒
refuse; otherwise queue.

**Why the acceptance latch.** Without it, a lane that reports as its last act and then crosses the
threshold would get a restore queued by the post-run compaction, and Pi would `agent.continue()` a
lane that is already done. The latch short-circuits the verdict first, so after an accepted report
nothing is ever queued and the post-run loop ends.

**Two bounds, two jobs.** `TASK_RESTORE_MAX_BYTES` (256 KiB) refuses a prompt that could never
fit — every perk report task is far below it. `TASK_RESTORE_MAX_ATTEMPTS` (3 per activation) is the
**loop bound**: a task that fits but keeps being compacted away on a small window cannot cycle
unboundedly. Neither measures live headroom; a bounded count is simpler and guarantees termination.
A refused lane is told to stop without reporting; the parent records it as uncovered — a report
reconstructed from a summary cannot be faithful.

**The once-only clause.** Every def says "call `structured_output` once and stop". A blocked call
captured nothing, so it is not the once; the block reason says exactly that, delivered only to the
child that needs it, only when it applies. The defs stay unedited — no dead prose in every lane,
and the def-prose pins stay put.

**Rejected: cancelling compaction.** A `session_before_compact` `{cancel: true}` in report children
would also prevent fabrication, and is simpler — but it converts a long grounding review into a
forced early report or an overflow `lane-failed` on large plans and repos. The restore keeps deep
reviews viable at the cost of one prompt-sized re-injection per compaction.

## Report definitions

Two layers of invariant apply, and they have different owners.

**Definition-level (the def owns it).** Every report agent — the ten shipped `agents/*.md`
definitions other than the writer, plus the repo-local `perk-dev.session-auditor` at
`.pi/agents/perk-dev/session-auditor.md` — is `async: true`, `systemPromptMode: replace`, inherits no global/project context or skills, sets no
`defaultContext`, and has the read-only tool posture `read, grep, find, ls, bash`. The shipped
ten are pinned by `tests/test_subagent_agents.py::test_native_child_profile`; the auditor by
`tests/test_repo_local_agents.py::test_auditor_is_a_background_report_outside_delivery`.

**Spawn-level (the perk-owned wave owns it).** Every `ReportWave` spawn adds `context: "fresh"`,
`mission: false`, `WAVE_ACCEPTANCE` (acceptance disabled) and the report restriction packet —
pinned by `extension/waves/reportWave.test.ts` for the agents that wave spawns — `perk.scout`
included: it is spawned by the perk-owned `run_scout_wave` wave (`extension/waves/scoutWave.ts`,
contracts §8.70), so its lanes carry the spawn-level facts and `REPORT_ROLES` pins it. A direct
`subagent` spawn of `perk.scout` (the contracts §8.3 leniency) remains reachable but sits OUTSIDE
the channel: the caller supplies `context: "fresh"` and the sanctioned acceptance disable itself
(the def's description says so), and such a child runs under the runner bit alone — no packet, no
floor (see "Not claimed"). The former repo-local `perk-dev.analyst`, which carried `defaultContext: fresh` and an `acceptance`
block in its frontmatter, was retired when it was promoted into `perk.scout`; those two facts moved
from the def to the caller so the def fits the closed profile.

## The writer

`perk.conflict-resolver` is dispatched foreground through the delegation door with no
`extensionBindings` at all, so it never gets a floor (the request-shape assertion in
`extension/pi/v1/delivery/conflictResolverEngine.test.ts` pins the packet's absence); it edits and
writes by design.

## Not claimed

- Not an OS sandbox and not authentication between host extensions: the packet is a spawn-time
  policy for perk-owned report waves, not continuous revocation.
- Foreground children have no perk activation; manual `subagent` calls are outside the channel.
- User-shadowed definitions and installations missing the consumer are not certified.
- Losing the runner env across a `/reload` is unsupported (the reload re-reads what is there).
- pi-subagents ≥ 0.70.0 no longer intersects a child's declared tools with the **host**
  session's builtin tools (the 0.67.x–0.69.x `child-tool-plan` intersection that failed
  review/scout-named agents closed on a pi-fff `override`-shadowed `grep`/`find` is gone), so
  pi-fff's search mode is irrelevant to lane launch: perk injects no `PI_FFF_MODE`, and the
  retired `subagent-host-tools` doctor check has no successor. The floor described here never
  depended on it.
- Pi 0.87's fork / pruned-fork context repair (the checkout-only fix in pi-subagents'
  development tree) is NOT in the installed 0.70.1 artifact. perk's waves and the conflict
  resolver spawn with `context: "fresh"`; fork context is unsupported for perk children until a
  pi-subagents release contains that fix — a support boundary, not a perk defect.

## Dropped mechanisms

| Mechanism | Why it went |
| --- | --- |
| The advisory `<active_agent>` prompt-prefix identity parser | spoofable; no reader of `ctx.getSystemPrompt()` is needed once no policy keys on agent names |
| The physical-session-key binding (`nativeSessionKey.ts`) | the floor is activation-scoped; there is no per-session snapshot to key |
| The six-reason envelope classification, 16 KiB size bound and warning buckets | a plain fail-closed boolean carries the same safety; the gate's `blocked` reasons are the visible signal |
| The ten-report scratch census (`REPORT_ONLY_CHILD_AGENTS`) | every perk report child is a runner child — the runner bit is the census |
| The `ReportWaveRequest.execution: "caller-read-only"` opt-in | every report child is read-only and caller-placed; no flow can select otherwise |
| The per-role execution profile table | one profile remains, described above |
| The installed-engine placement/interop compat harnesses | proved mechanisms that no longer exist; the fake-RPC composition proof replaces them |

## Regression suites

| Guarantee | Test |
| --- | --- |
| Runner + packet ⇒ monotone floor incl. backstop | `extension/sessionLifecycle.test.ts` "runner floor: latched for the activation, backstopped, and invisible to a sibling activation"; `extension/substrate/toolGating.test.ts` floor tests |
| No packet ⇒ no floor; malformed (incl. unsupported family version) ⇒ floor | `extension/substrate/childRestrictions.test.ts` decoder table |
| Runner children provision no scratch | `extension/substrate/agentScratch.test.ts` "a runner child provisions no scratch even without a floor" |
| Plan-bound readers run in the caller checkout; the packet is constant | `extension/waves/reportWave.test.ts` profile + hostile-fields tests; `reportWaveRpc.test.ts` round-trip |
| Producer → consumer composition | `extension/pi/v1/waveIsolation.test.ts` "real composition: the rendered packet floors a child…" (fake RPC bus → rendered item → child session → `write` blocked, parent and handoff untouched) |
| Report agents keep async/fresh/mission/acceptance posture | `tests/test_subagent_agents.py::test_native_child_profile` (the ten shipped defs); `tests/test_repo_local_agents.py::test_auditor_is_a_background_report_outside_delivery` (`perk-dev.session-auditor`); `reportWave.test.ts` spawn pins |
| Reflection failure stays loud | `extension/sessionLifecycle.test.ts` "escaping reflection exception reports safely…" |
| A compacted report child gets its task back; an accepted report is never restarted | `extension/substrate/childTaskRestore.test.ts` verdict table; `extension/pi/v1/childTaskRestore.test.ts` (planted compactions + two faux-runtime turns through Pi's real post-run compaction) |
