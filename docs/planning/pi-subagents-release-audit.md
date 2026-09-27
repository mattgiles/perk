# pi-subagents release audit — 0.72.1

Audit date: **September 27, 2026**. Perk snapshot:
[`c9c0c59ef4564173abfd51d68295b3d28c3976d2`][p-snapshot] (3.7.0).
This memo proposes follow-up work; it does not upgrade packages or certify a new
compatibility baseline.

**Handle the SDK census drift and reconcile tool activation first.** The release
does not require a new RPC envelope or a replacement for ReportWave. It does expose
one definite import-census mismatch, while its more dependable lazy tool activation
makes an existing conflict with perk's tool policy worth fixing. Cost reporting is
promising but currently misses the entry types perk uses for its own waves.

| Question | Assessment |
| --- | --- |
| What breaks or needs handling? | The published package adds `typebox/value`, outside perk's SDK census. A composed source probe also reproduces conflicting ownership of `subagent` activation and an advertised-but-blocked `subagents_enable` call. |
| What can be simplified? | Narrow perk's ownership of the borrowed tool's activation. Keep the SDK bridge, completion correlation, structured-report validation, and child restrictions. Earlier completion-guard and FFF cleanups already landed. |
| What is worth adopting? | Native lifecycle/terminal diagnostics and explicit descendant-agent restrictions are useful bounded follow-ups. Investigate Fleet inspectors when a concrete viewer is needed. Resolve RPC-wave attribution before presenting native cost totals as perk wave spend. |

## 1. Release identity and integration map

### The comparison has three different baselines

| Item | Audited value |
| --- | --- |
| Installed pi-subagents; last source reread in learned guidance | **0.71.0**; release commit `4af5e85a427b9f87334585ae8d0eb365d4dd2a1e` |
| New behavior release | **0.72.0**; `fe1b898898339c3a1efcd9c7744ff422da9d1c94`; npm publication September 27, 03:03:47 UTC |
| Audited npm artifact and supplied source HEAD | **0.72.1**; `fece3cea193f47593685668b3969167a09cdf60c`; npm publication September 27, 03:58:07 UTC |
| Perk doctor guidance stamp | **0.70.1**, deliberately separate from installation and source-review versions |
| Perk's installed development SDK | Pi **0.87.0** |
| Other consumer covered by the SDK census | Installed pi-web-access **0.31.0** |

The [0.71.0-to-target comparison][s-compare] changes 82 files. Between the
0.72.0 tag and the audited HEAD, only the release workflow, changelog, and package
version metadata change. The [0.72.1 release notes][s-changelog] describe the
republish as restoring npm provenance. GitHub's latest release query returned
[v0.72.0][s-release], published September 27 at 03:12:14 UTC; npm's published
[0.72.1 metadata][s-metadata] identifies the later commit. The changelog uses the
maintainer's September 26 date. These are consistent timestamps, not different
runtime releases.

The [Pi settings][p-settings] still request unpinned `npm:pi-subagents`; this audit
preserves that policy. An unversioned entry does not itself refresh an existing
installation at launch. The [doctor constant][p-doctor] remains 0.70.1, and the
[learned source record][p-learned-subagents] explicitly leaves live verification
owed after its 0.71.0 reread. Neither this audit nor passing tests against the
installed 0.71.0 package closes that debt.

The [September 21 assessment][p-previous] supplies carryovers, checked against
current code rather than copied into a new backlog. The main integration sources
are the learned notes on [subagents][p-learned-subagents],
[report waves][p-learned-waves], and [SDK identity][p-learned-sdk], plus the
[binding child policy][p-child-policy] and [shared contracts][p-contracts].

### Current integration boundaries

| Perk responsibility | Public upstream contract and current policy |
| --- | --- |
| Report-wave launch | [RPC adapter][p-rpc] uses v1 event envelopes and capability discovery. [Transport][p-transport] fixes async, fresh-context, non-mission execution, acceptance `none`, and intercom bridge `off`. |
| Reports and coverage | [ReportWave][p-wave] renders keyed config-object `runs.all` items, validates schemas and identities, and keeps failure, valid evidence, and coverage separate. Native partial results do not authorize a complete review. |
| Child authority | Every report child receives `worktree: false` and the constant read-only extension binding. [Restriction decoding][p-restrictions] and [tool gating][p-gate] enforce the runner child's latched floor. |
| Conflict resolution | The [resolver engine][p-resolver] sends foreground structured delegation with fresh context, canonical worktree cwd, cancellation, and termination-dependent lock release. |
| Agent delivery | [Package metadata][p-package] declares `agents/` through `pi-subagents.agents`. Project definitions can shadow packaged definitions; the reviewer skill paths remain relative to the selected definition. |
| Host SDK identity | The [native bridge][p-sdk] redirects a closed import census to [host namespaces][p-host-sdk], installed before compiled native consumers. This also covers pi-web-access. |
| Parent tool availability | [Tool gating][p-gate] owns read-only eligibility and stage filtering; upstream now owns lazy activation of `subagent`. This is the overlapping responsibility examined below. |

## 2. Breakages and required handling

### A1. Extend the SDK census: confirmed artifact incompatibility

**Artifact probe.** The published 0.72.1 tarball adds a runtime import of
`typebox/value` in [binary-bootstrap][s-binary]. Perk's `NATIVE_SDK_CENSUS` and
`hostSdkNamespaces()` cover `typebox` and `typebox/compile`, but omit `/value`.
Scanning all 298 shipped JavaScript-family files, combined with the installed
pi-web-access source, produces exactly that one additional SDK specifier and no
missing old specifiers.

This breaks the equality assertion in the [installed-consumer census guard][p-sdk-test]
after upgrading pi-subagents in a checkout containing both consumers. That guard
skips when its consumer installations are absent, so a green bare CI checkout
does not prove the upgraded artifact passes it.

**Required follow-up:** extend the census and host namespace capture to
`typebox/value`, bump `BRIDGE_SCHEMA`, extend the bridge identity fixtures, and
admit the host-provided subpath in the [bare-import guard][p-bare-import]. Pi
0.87.0's installed extension loader already aliases this subpath. Update contracts
§8.73 with the changed census and verify both consumers against the new artifact.

The reproduction establishes a guard mismatch, **not a demonstrated failure of an
ordinary report wave**. The new import is in the binary-runner bootstrap, whereas
perk's normal Node parent and detached children follow different loading paths.
That distinction matters when choosing the smoke tests; it does not justify silently
weakening the explicitly package-wide census.

### A2. Reconcile lazy activation with perk's tool policy

**Focused probe; carryover from 0.71.0, reinforced by 0.72.0.** Upstream
[tool activation][s-activation] registers `subagents_enable`, hides `subagent` in
a fresh parent, restores recorded selections, and reintroduces the loader in
`before_agent_start`. The new release removes a stale package-local pi-ai probe
that could disable that behavior. It also accepts extra loader arguments.

Perk does not enumerate `subagents_enable` in its borrowed-tool or read-only
censuses. Its `resources_discover` reconciliation can restore `subagent` from the
earlier active-tool snapshot, undoing upstream's deliberate deactivation. Composing
the two real registration functions over a fake Pi API in their normal order gave:

| Scenario | Observed result |
| --- | --- |
| Fresh read-only `plan` | Upstream hides `subagent`; perk's reconciliation enables it again. Before the model turn, upstream advertises the loader, but perk's `tool_call` hook blocks `subagents_enable` as unallowlisted. |
| Fresh read-write `implement` | Perk restores the full `subagent` tool after upstream hides it, losing the intended prompt-size saving. |
| Read-write `gist-save` | The stage excludes `subagent`, but the unenumerated loader survives. Calling it enables `subagent` until another perk reconciliation. |

The last row is a stage-tool-selection inconsistency. Stage filtering is not
perk's read-only authorization boundary; the read-only backstop remains enforced.
Code-owned report waves use RPC, so an unusable loader does not imply their launch
path is broken.

**Required follow-up:** give the loader the same stage eligibility as the tool it
enables, preserve upstream's lazy selection inside eligible stages, and ensure an
advertised loader can be called under the applicable gate. Prevent activation from
reintroducing a stage-excluded tool. Cover startup, resource reconciliation,
`before_agent_start`, gate exit, reload, and session-tree navigation together.
Adding a name to an allowlist alone does not resolve the competing snapshots.
Amend contracts §8.3/§8.40 and operator guidance with the chosen activation behavior.

This probe used upstream source at the audited commit, perk's current gate, and
perk's installed peers supplied by a process-local import hook. It did not run a
live Pi conversation or install an upstream dependency tree.

### A3. More completion events: current root correlation remains appropriate

**Source comparison and focused perk tests.**
[emitWorkflowAwaitedChildComplete][s-executor] now emits an async-completion event
for a workflow-awaited child, including its own id/directory,
`parentWorkflowRunId`, `awaitedByWorkflow: true`, and `triggerTurn: false`.
[Notification delivery][s-notify] ignores these events as user-facing completion
notices. The event repairs lifecycle accounting; it is not the workflow's final
aggregate and does not restore the old supervisor progress channel.

Perk's `startWaveScript` matches the launched workflow's `asyncId` or `asyncDir`.
Its adapter ignores unfamiliar fields, and foreign child identities do not settle
the wave. The [RPC integration tests][p-wave-rpc-test] exercise foreign events,
out-of-order completion, partial settlement, and cancellation.

**Disposition:** retain root correlation and completion-before-reply buffering.
In the compatibility follow-up, add the exact new child-event shape to the
existing fake-engine scenarios: emit it before the spawn reply and while siblings
remain active, then require the root completion before collection. Do not collect
early or treat lifecycle notifications as report data.

### Other compatibility checks

| Change or dependency | Finding and required verification |
| --- | --- |
| RPC and foreground delegation | The RPC implementation, delegation API, delegation request parser, and scripted-workflow implementation are unchanged between 0.71.0 and this target. No mandatory envelope migration found. The call paths still reach the same executor through the new readiness wrapper. [RPC][s-rpc], [delegation parser][s-delegation]. |
| Deferred discovery and executor imports | [Extension startup][s-extension] starts global discovery without blocking `session_start`; execution waits through `waitForAdvertisement()` and `getExecutor()`. [Global npm-root lookup][s-global-root] has a five-second default deadline and falls back to local discovery. Test immediate RPC/delegation after startup, failed global lookup, reload, and first-use import errors; do not increase perk's 30-second RPC timeout without evidence. |
| Packaged agents and skills | Discovery now accepts the asynchronously resolved global root. Package-agent declaration parsing, source precedence, and definition-relative skills remain in place. Verify actual `perk.*` discovery and Ponytail skill resolution on the upgraded installation. No new frontmatter removal affecting shipped perk definitions was found. [Discovery][s-agents], [skills][s-skills]. |
| Structured reports | 0.71.0 already retained valid structured output after a later failure. Perk already requires successful status plus a valid report for coverage. Keep the existing failed-status/valid-report regression; neither child completion events nor terminal proof relax that rule. [Normalization][p-wave], [structured output][s-structured]. |
| Child policy | Runner identity, extension-binding transport, caller-checkout placement, omitted-child-async behavior, and injected structured output remain the relevant contract. No replacement for perk's read-only floor was found. Foreground provider fixes do not make background report children superfluous: the floor depends on runner-hosted extension activation. [Child policy][p-child-policy], [executor][s-executor]. |
| PID namespaces | [Stale-run reconciliation][s-stale] changes a negative PID probe to unknown when the recorded namespace differs, retaining the existing stale-age fallback. Useful for shared container temp roots; it is not proof of process exit or a substitute for perk's own settlement deadline. |
| Capability checks before fork | The executor now checks agent admission before preparing a fork and rechecks after waits. Current perk calls explicitly use fresh context, so this is not a demonstrated break in either report waves or conflict delegation. |

## 3. Adaptations to remove, narrow, or keep

There is **no evidence-backed case to delete the SDK bridge or ReportWave** in
this release. The concrete simplification is to stop reconstructing the borrowed
tool's activation from stale perk snapshots while retaining perk's eligibility
policy. The other high-value simplification is avoiding new duplicate accounting
or inspection machinery when an upstream seam can be made sufficient.

| Adaptation | Disposition | Responsibility that remains; deletion or preservation criterion |
| --- | --- | --- |
| Borrowed-tool activation inside the gate | **Narrow**, per A2. | Upstream owns whether an eligible delegation tool has been activated. Perk owns mode/stage eligibility. A composed lifecycle test must preserve both without reactivating other owner-disabled tools. |
| Native SDK bridge and package ordering | **Keep and extend**, per A1. | Moving TypeBox to an optional peer removes its dedicated dependency; it does not make a compiled `.js` entry pass through Pi's virtual modules. The release still ships `index.js`, and pi-web-access remains a second consumer. Removal requires measured identity equivalence across supported host/loading paths, not just a manifest diff. [SDK rationale][p-learned-sdk]. |
| RPC `no_active_session` hold | **Keep.** | Upstream's earlier duplicate-notification repair does not prove that Pi's contextless pre-trust RPC responder is gone. The current RPC bridge still allows contextless ping and rejects work without a context. Preserve later-success selection and immediate propagation of other errors. [Adapter][p-rpc]. |
| Completion buffering, correlation, deadline grace | **Keep.** | Root identity may arrive after completion; native timeout partials arrive after the engine deadline. Child lifecycle events and process proof replace neither race handling nor keyed result validation. Preserve the existing bounded buffer and settlement tests. [Transport][p-transport]. |
| Acceptance `none`, bridge `off`, fresh context | **Keep.** | Perk intentionally owns report completion and parent actions. Fork compatibility and native provider improvements are capabilities, not reasons to inherit parent conversation or enable supervisor traffic. [Wave contract][p-learned-waves]. |
| Read-only binding and gate; resolver locks | **Keep.** | Tool/agent ceilings do not restrict the arguments of an allowed `bash` call. Async workflow terminal proof is not the foreground resolver's termination handshake. [Restrictions][p-restrictions], [resolver][p-resolver]. |
| Config-object `runs.all`, schemas, receipts, and parent posting | **Keep.** | Native orchestration supplies execution; perk supplies lane identity, completeness, blocked-report semantics, and review authorization. A named resource still needs those responsibilities. [ReportWave][p-wave]. |
| `completionGuard`, `fallbackModels`, forced FFF mode, host-tool-intersection diagnostic | **Already completed.** | Current agents omit the retired fields, launch code no longer injects the FFF workaround, and doctor no longer emits that row. Existing tests pin these retirements. Do not reopen the September 21 cleanup list. [Agent tests][p-agent-tests], [doctor tests][p-doctor-tests]. |

## 4. Useful capabilities and adoption limits

### Cost RPC: useful interface, incomplete attribution for perk

**Focused probe and source comparison; 0.71.0 interface with 0.72.0 accounting
repairs.** The public `cost` RPC returns versioned parent/child totals and
`unresolvedAsyncChildren`; [0.72.0's collector][s-cost] additionally accounts for
native async single/chain launches and avoids counting completed steps twice.

The important limitation is how runs enter that collector. `detailsFromSessionEntry`
accepts native `subagent`/`bg_wait` tool results and the package's slash-result
messages. It does not accept perk tool results. The [RPC executor wrapper][s-rpc]
returns results over the event bus; it does not create a native tool-result message.
Routine `subagent-notify` messages are not accepted cost entries either.

A synthetic entry with one child carrying `cost: 0.25` demonstrated the boundary:

| Same native-shaped details carried by | Child cost | Recognized children | Unresolved children |
| --- | --- | --- | --- |
| `subagent` tool result | 0.25 | 1 | 0 |
| `run_scout_wave` tool result | 0 | 0 | 0 |
| `subagent-notify` custom message | 0 | 0 | 0 |

This deliberately uses identical synthetic details to isolate entry selection;
it is not a measurement of a real scout's spend. Current perk receipts have their
own shapes as well. **Inference from this boundary and perk's RPC path:** a wave
without a recognized native accounting entry can be absent from totals even when
the unresolved count is zero. That count describes discovered runs, not universal
coverage of every extension's activity.

**Recommendation:** pursue a bounded upstream attribution improvement before
adding a perk cost display. Prefer session-owned tracking of RPC launches or a
public query accepting owned run ids; do not fabricate `subagent` messages or build
a second artifact scanner in perk. Then test real RPC waves, concurrent native
runs, foreground conflict delegation, branch navigation, and duplicate notices.
Read cost on collection/turn boundaries, not a polling timer. Label session totals
separately from wave totals and preserve the incomplete-accounting indication.

### Adoption shortlist

| Capability and release | Concrete use in perk | Recommendation and acceptance condition |
| --- | --- | --- |
| **Child lifecycle events**, introduced in 0.71.0 and paired for awaited children in 0.72.0 | Show which report lanes are running or finished without reopening the intercom bridge. | **Bounded follow-up.** Consume public event identities, correlate children to the owned workflow, and send concise state through perk's surfaces module. Subscription cleanup, foreign-event isolation, and unchanged final collection authority are required. No additional parent model turn per successful child. [Executor][s-executor], [RPC event advertisements][s-rpc]. |
| **Workflow/process terminal proof**, earlier capability with 0.71.0 workflow aggregation | Explain why a stopped/timed-out wave may still have live children. | **Diagnostics first.** Query targeted status for `details.workflowTerminalProof`; preserve `pending`/`unknown` as uncertainty. Test hanging children and missing proof. Do not use a complete report or `endedAt` as exit evidence, or substitute this async proof for the foreground resolver's lock-release protocol. [Run status][s-run-status], [proof contract][s-observability]. |
| **`allowedAgents`**, 0.70.0 carryover | Enforce the existing no-descendant instruction in report agents and the conflict resolver. | **Adopt in a separate small change.** The current defs do not set it. An empty frontmatter key `allowedAgents:` denotes the empty list; do not assume YAML-looking `[]` is equivalent. Verify denied nesting in foreground and background paths, preserved parent delegation, and successful structured output. Keep the read-only floor. [Parser and tests][s-frontmatter-tests]. |
| **Inspector provider registration**, new in 0.72.0 | Reuse Fleet's existing run inspection workflow if perk needs a particular terminal/viewer integration. | **Defer a custom provider until that viewer need exists.** The versioned `pi-subagents:inspector-register:v1` event is usable without a forbidden bare package import. Register after factories load, dispose on cleanup, and test reload/duplicate ownership, unavailable viewers, and headless behavior. Builtins retain preference; this API does not automatically add arbitrary perk report panels to Fleet. [API][s-inspectors], [registry][s-inspector-registry]. |
| **Broader `fast: true` model support**, 0.72.0 | Reduce latency for a deliberately selected native OpenAI-Codex review/scout model. | **Opt-in experiment through upstream configuration first.** It accepts the `openai-codex/` provider family, not every OpenAI model. Perk's spawn-time model override still wins, so validate the effective model together with `fast`. Measure latency and spend before adding another perk config field. [Child tool plan][s-tool-plan]. |
| **Required child extensions**, 0.68.0 carryover | Guarantee delivery of a narrow child-enforcement extension if ambient loading becomes insufficient. | **Defer pending a concrete delivery gap and a supported registration route.** The API is session-scoped and returns a disposer, but its package import is outside perk's bare-import contract. Inspector registration does not add an event seam for this separate API. Do not load the entire parent workflow into every child or write directly to upstream's private registry. [Required extensions][s-required], [import policy][p-bare-import]. |
| **Named workflow resources / runtime agents**, earlier public APIs | Replace repeated workflow setup or supply truly transient specialist definitions. | **Defer replacement of the existing renderer/package-agent delivery.** A named resource still resolves to a script and needs lifecycle-managed registration; perk's typed adapter would need a deliberate new request variant. Runtime agent registration has its own public event route, useful for transient definitions, but packaged defs already solve shipped-agent discovery. Require fewer responsibilities or less duplicated code before migrating. [Integration APIs][s-api], [resources][s-resources]. |
| **Child-launched external jobs and idempotent resume**, 0.72.0 | Future delegation to an external job provider, including nested follow-up work. | **Defer interface expansion.** These repair existing upstream paths; current perk report roles prohibit descendant delegation and rely on native child restrictions/structured tools. Require an explicit external-runner capability and result contract before exposing this as another report backend. Resume must retain the original child contract; it is not a generic retry substitute. [Executor][s-executor], [external-job bridge][s-external-job]. |

### Improvements received through the engine

- **Startup:** executor and Fleet modules load on demand; optional global discovery
  leaves `session_start` responsive. Upstream reports its startup module count
  falling from 264 to 199. That is an upstream measurement, not a measured perk
  latency result. Re-profile perk before removing any independent startup work.
  [Extension loading][s-extension], [release notes][s-changelog].
- **Providers and model names:** watchdog review, permission arbitration, and
  Prompt Audit now dispatch through the session model registry; model ids containing
  their provider prefix resolve correctly. These benefit configured users without
  a new perk selector. They do not require enabling watchdogs or changing report
  execution mode. [Provider dispatch][s-watchdog], [model resolution][s-models].
- **Status and presentation:** actual child context limits, UTF-8-safe worktree
  labels, steadier Fleet rendering, and visible supervisor questions improve native
  inspection. Keep perk receipts narrow until a consumer needs those fields.
  `/council`'s guide-based loading with skills disabled does not affect perk's
  code-owned waves or remove their explicit Ponytail skill requirements.
  [Release notes][s-changelog].

## 5. Ordered follow-up work

| Order | Bounded change | Acceptance criteria |
| --- | --- | --- |
| 1 | **SDK census compatibility** (A1). | `/value` is captured from the host; bridge schema/fixtures/import guard and contracts agree; census passes against 0.72.1 plus pi-web-access; exercise normal Node loading and distinguish the binary-host smoke from ordinary report execution. |
| 2 | **Tool activation composition** (A2). | The three reproduced scenarios are covered through both owners' lifecycle hooks. Eligible fresh parents keep lazy activation; excluded stages cannot acquire `subagent` through the loader; advertised loaders are usable under the intended gate; unrelated inactive tools remain inactive. Update contracts and user-facing tool guidance together. |
| 3 | **Complete release reverification.** | Upgrade deliberately, exercise packaged-agent/skill discovery and new completion-event shapes, then run the repository's submission gate and the documented live legs. Plan and PR browser waves reach N/N keyed coverage; timeout/cancel/partial handling and foreground conflict delegation retain their invariants. Move the doctor stamp only through the existing verification policy. |
| 4 | **Apply descendant-agent restrictions.** | Empty-list parsing is pinned; foreground/background descendants are refused while parent launch and report completion still work. Update the affected agent/config guidance and the perk-expert mirror if operator configuration changes. |
| 5 | **Add one useful diagnostic, or repair cost attribution upstream.** | Select a concrete consumer for lifecycle/terminal data. For cost, first demonstrate accounting of real perk RPC waves without duplicate or unrelated charges. New UI uses the surfaces module; new API boundaries validate untrusted results. |

Inspector providers, named resources, required extensions, and external-job
interfaces remain separate proposals. Their availability alone does not justify
adding a second dashboard, registry, accounting system, or execution mode to perk.
Revisit them when the stated use case or delivery gap is demonstrated.

## 6. Evidence, probes, and remaining verification

Evidence labels above distinguish source inspection, published-artifact inspection,
composed offline probes, and actual tests. **No live 0.72.1 child, browser review
wave, or compatibility-stamp update was performed.** Only this planning document
is added to perk; the installed engine remains 0.71.0.

### Published artifact

The [npm tarball][s-tarball] was downloaded and inspected in memory without
installation. Its SHA-512 matched npm metadata:

```text
sha512-htPj5cgSaSRwb1o69rlo+kl7i84PjzNPBqDq6MxKHqGhucMbpp5dlFZCEGS7w1eC0yT2EhctJunqRKR0R7DfZg==
```

The artifact declares `pi.extensions: ["./index.js"]`, exposes the compiled
`./inspectors` export, and declares TypeBox as an optional peer rather than a
runtime dependency. Perk's `extractSpecifiers` lexer found the A1 census delta in
the 298 shipped `.js`/`.mjs`/`.cjs` files, excluding nested `node_modules`; the
pi-web-access contribution was read from its existing installation.

Reproduce that check by fetching the exact version's npm metadata/tarball,
verifying its integrity, lexing the shipped sources with
`extension/testing/importGraph.ts::extractSpecifiers`, and comparing the union of
both consumers' SDK imports against `NATIVE_SDK_CENSUS`. Reading a missing `.ts`
file from this compiled package is not an installation failure.

### Composed source probes

- **Activation:** register perk's `registerToolGating` first, then upstream's
  `registerSubagentToolActivation`, on one fake API maintaining registered and
  active tools. Declare the real Pi 0.87.0 host root. Use an empty session history,
  apply `syncFromState`, dispatch upstream `session_start`, then
  `resources_discover`, `before_agent_start`, and the loader's `tool_call`.
  Exercise `plan`/read-only, `implement`/read-write, and `gist-save`/read-write;
  assert A2's table. The fake registry starts with `read`, `write`, `subagent`,
  and `subagent_supervisor`; registering the loader initially activates it.
- **Cost:** invoke `collectSubagentCost` with an in-memory session branch and one
  native-shaped single-child result (`input: 20`, `output: 10`, `turns: 1`,
  `cost: 0.25`). Change only the tool-result name between `subagent` and
  `run_scout_wave`; also try a `subagent-notify` custom message. Assert section 4's
  table. No child or billing request is made.

Both source probes used the audited upstream checkout with its bare dependencies
resolved to perk's installed peers by a temporary process-local Node resolve hook.
They establish composition/selection behavior, not an upstream lockfile install
or full Pi-host integration.

### Focused tests

Run from the perk checkout:

```sh
node --test extension/waves/rpcAdapter.test.ts extension/waves/reportWave.test.ts extension/substrate/nativeSdkBridge.test.ts
node --test extension/waves/reportWaveRpc.test.ts
```

**153 tests passed**: 136 in the first command and 17 in the second. The SDK
census test in that first command inspected the installed **0.71.0** engine;
the separate artifact probe is what demonstrates the new mismatch. The fake-engine
wave tests establish perk's existing invariants, not a successful 0.72.1 launch.

An upstream `node:test` selection was also attempted with its
`test/support/isolated-temp-root.mjs` preload: `advertisement-barrier`,
`agent-global-root-override`, `extension-lazy-loading`, `inspector-registration`,
`notify`, `package-manifest`, `stale-run-reconciler`, `tool-activation`, and
`tool-activation-stale-peer` under `test/unit/`. It reported **67 passes and 9
failures**. The failures were missing checkout dependencies/toolchain files
(`yaml`, Pi peers, and TypeScript), not demonstrated engine regressions. A
diagnostic rerun confirmed those causes; no dependencies were installed there.
The full upstream selection therefore remains unverified.

Follow the [reverification procedure][p-reverify] for the release certification
change. In a perk session, the repository instructions require one run-all
`run_ci` before submission; do not substitute bare `just ci`. The browser-door
leg remains outstanding unless the owner explicitly records the procedure's
alternative baseline election. This memo makes no such election and preserves
the standing unpinned-package policy.

[p-snapshot]: https://github.com/mattgiles/perk/tree/c9c0c59ef4564173abfd51d68295b3d28c3976d2
[p-settings]: ../../.pi/settings.json
[p-package]: ../../package.json
[p-doctor]: ../../src/perk/convergence/doctor/checks.py
[p-previous]: ./pi-subagents-assessment-2026-09-21.md
[p-learned-subagents]: ../learned/pi/subagents.md
[p-learned-waves]: ../learned/workflow/report-waves.md
[p-learned-sdk]: ../learned/pi/native-sdk-bridge.md
[p-child-policy]: ../design/pi-subagents-child-execution-policy.md
[p-contracts]: ../../shared/contracts.md
[p-rpc]: ../../extension/waves/rpcAdapter.ts
[p-transport]: ../../extension/waves/transport.ts
[p-wave]: ../../extension/waves/reportWave.ts
[p-restrictions]: ../../extension/substrate/childRestrictions.ts
[p-gate]: ../../extension/substrate/toolGating.ts
[p-resolver]: ../../extension/pi/v1/delivery/conflictResolverEngine.ts
[p-sdk]: ../../extension/substrate/nativeSdkBridge.ts
[p-host-sdk]: ../../extension/substrate/hostSdk.ts
[p-sdk-test]: ../../extension/substrate/nativeSdkBridge.test.ts
[p-bare-import]: ../../extension/bareImportGuard.test.ts
[p-wave-rpc-test]: ../../extension/waves/reportWaveRpc.test.ts
[p-agent-tests]: ../../tests/test_subagent_agents.py
[p-doctor-tests]: ../../tests/test_doctor.py
[p-reverify]: ../developers/pi-subagents-reverify.md
[s-compare]: https://github.com/nicobailon/pi-subagents/compare/v0.71.0...fece3cea193f47593685668b3969167a09cdf60c
[s-release]: https://github.com/nicobailon/pi-subagents/releases/tag/v0.72.0
[s-metadata]: https://registry.npmjs.org/pi-subagents/0.72.1
[s-tarball]: https://registry.npmjs.org/pi-subagents/-/pi-subagents-0.72.1.tgz
[s-changelog]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/CHANGELOG.md
[s-binary]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/runs/background/binary-bootstrap.ts
[s-activation]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/extension/tool-activation.ts
[s-executor]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/runs/foreground/subagent-executor.ts
[s-notify]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/runs/background/notify.ts
[s-rpc]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/extension/rpc.ts
[s-delegation]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/slash/delegation-request.ts
[s-extension]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/extension/index.ts
[s-global-root]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/agents/global-npm-root.ts
[s-agents]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/agents/agents.ts
[s-skills]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/agents/skills.ts
[s-structured]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/runs/shared/structured-output.ts
[s-stale]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/runs/background/stale-run-reconciler.ts
[s-cost]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/slash/subagent-cost.ts
[s-run-status]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/runs/background/run-status.ts
[s-observability]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/docs/observability.md
[s-frontmatter-tests]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/test/unit/agent-frontmatter.test.ts
[s-inspectors]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/api/inspectors.ts
[s-inspector-registry]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/inspectors/plugins.ts
[s-tool-plan]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/runs/shared/child-tool-plan.ts
[s-required]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/api/required-child-extensions.ts
[s-api]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/docs/extension-api.md
[s-resources]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/api/workflow-resources.ts
[s-external-job]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/runs/shared/external-job-bridge.ts
[s-watchdog]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/watchdog/review.ts
[s-models]: https://github.com/nicobailon/pi-subagents/blob/fece3cea193f47593685668b3969167a09cdf60c/src/runs/shared/model-resolution.ts
