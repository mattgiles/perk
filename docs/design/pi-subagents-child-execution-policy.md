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
properties inert. `createReportWave(bus)` takes no supplier and has no capture-failure arm. The
byte-pinned golden is `shared/subagents/representative-wave-script.js`.

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
backstop that blocks anything outside `READ_ONLY_TOOLS` even if the toolset rebuild failed. A
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
suppression rides the same runner bit through `extension/substrate/contextPolicy.ts`.

## Report definitions

Every report agent (`agents/*.md` except the writer) is `async: true`, `completionGuard: false`,
`systemPromptMode: replace`, inherits no global/project context or skills, and has the read-only
tool posture `read, grep, find, ls, bash` — pinned by `tests/test_subagent_agents.py`. Every spawn
adds `context: "fresh"`, `mission: false` and `WAVE_ACCEPTANCE` (acceptance disabled) — pinned by
`extension/waves/reportWave.test.ts`.

## The writer

`perk.conflict-resolver` is dispatched foreground through the delegation door with no
`extensionBindings` at all, so it never gets a floor; it edits and writes by design.

## Not claimed

- Not an OS sandbox and not authentication between host extensions: the packet is a spawn-time
  policy for perk-owned report waves, not continuous revocation.
- Foreground children have no perk activation; manual `subagent` calls are outside the channel.
- User-shadowed definitions and installations missing the consumer are not certified.
- Losing the runner env across a `/reload` is unsupported (the reload re-reads what is there).

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
| Plan-bound readers run in the caller checkout; the packet is constant | `extension/waves/reportWave.test.ts` profile + hostile-fields tests; `reportWaveRpc.test.ts` round-trip; the regenerated golden (doctor's `validateWorkflowScript` arm reads it) |
| Producer → consumer composition | `extension/pi/v1/waveIsolation.test.ts` "real composition: the rendered packet floors a child…" (fake RPC bus → rendered item → child session → `write` blocked, parent and handoff untouched) |
| Report agents keep async/fresh/mission/acceptance posture | `tests/test_subagent_agents.py::test_native_child_profile`; `reportWave.test.ts` spawn pins |
| Reflection failure stays loud | `extension/sessionLifecycle.test.ts` "escaping reflection exception reports safely…" |
