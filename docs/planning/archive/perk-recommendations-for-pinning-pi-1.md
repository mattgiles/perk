# Recommendations for Perk's Pi 1.0 pin

Date: **2026-10-03**. Grounded in Perk 3.9.0 at
`2d8d635a47aaa6abe44064e26e9fcdcad12dc0ed`. This is a recommendation for future
implementation, not a claim of Pi 1.0.0 certification.

## Recommendation

**Ship the 1.0 pin after a bounded compatibility program and three SDK-worker
improvements.** Keep the shared SDK bridge and the recently modernized tool
system. Schedule the broader access, review-lifecycle, observability, and execution
work as independent follow-ups.

This memo supersedes the pre-pin sequencing in
[the updates document][updates]. That document remains the detailed source and
opportunity inventory. Its requirement to finish broad native-capability adoption,
browser consolidation, and supplier comparisons before the floor would turn a
dependency upgrade into several architecture projects. Those projects have value;
their completion should not determine when Perk can support Pi 1.0.

The release rule is: repair compatibility and evidence defects, preserve existing
workflow guarantees, take small deletions justified by the new baseline, and
complete the explicitly bounded worker addition. New authorization policy,
replacement executors, and new workflow intelligence belong in follow-ups.
**Pi-durable remains deferred.**

## Start from what has already landed

The six recent tool PRs are the foundation of this recommendation:

| Landed work | Consequence |
| --- | --- |
| #2644 — `registerPerkTool`, the catalog, derived stage/gate policy, and exposure rules | Reuse the registration and policy seam. No second tool taxonomy or metadata migration. |
| #2646 — own-name activation, foreign provenance policy, and `perk_stage` presentation | Preserve native owners' selections and the distinction between presentation and enforcement. |
| #2648 — structured results and nested `/learn` evidence | Preserve query schemas, action failure semantics, and bounded nested-call records. These are implemented. |
| #2650 — adopted native discovery, four deferred tools, primers, and live evidence | Preserve the adopted family and its measured acceptance criteria. Additional deferral requires its own benefit. |
| #2653 — loadout-host prose governance | Keep the presentation-only host visible to the source census without adding model-facing guidance. |
| #2655 — default `+tool_search` convergence and opt-outs | Keep the existing init/doctor behavior. No new discovery-default implementation is needed. |

The [pilot record][discovery] explicitly excluded the SDK worker, `/btw`, and report
children from the Perk discovery cohort. Its [worker E2E test][worker-test] asserts
that `tool_search` is not even registered despite the opt-in. The worker additions
below extend that deliberately bounded adoption. They do not reopen the tool
architecture or characterize the six PRs as incomplete.

### Keep the shared SDK for its actual purpose

The [bridge learning][bridge-learning] explains the motivating failure: compiled
JavaScript supplier entries can bypass Pi's jiti aliases and load another SDK graph
through Node. The historical census measured SDK modules outside the host root
falling from 2,799 to zero after bridging. That single-sample measurement explains
the investment; it is not a current performance benchmark.

Keep three distinct requirements clear:

- **Shared module identity within a supported host:** the bridge makes native
  supplier imports use the host's SDK namespaces and avoids the duplicate graph.
- **Shared live model state for a side session:** `/btw` needs the parent's runtime
  API-key overrides and extension providers. Reconstructing a runtime from disk
  does not reproduce that state. See the [headless-session learning][headless].
- **Isolation between processes and session roles:** detached report runners have
  their own loader/alias setup; the SDK worker deliberately excludes global
  extension resources. Sharing SDK code does not mean sharing every resource,
  credential context, or process-global flag.

**Retain and reverify the bridge.** Preserve its package ordering, scoped consumer
roots, namespace census, and supported-host boundaries. A working report wave
proves parent-side launch; an in-process blocking child is a separate identity
proof. Pi 1.0's retained loader behavior supplies no demonstrated replacement.
Removing the bridge would reacquire a problem Perk has already measured and solved.

## The release package

### 1. Upgrade the supplier and its protocol together

Adopt **pi-subagents 0.75.0** and change Perk's code-owned RPC spawn payload from
`workflowScript` to `script`. The 0.73.1 npm-host runner requires the
`pi-agent-core/node` export removed in Pi 1.0; 0.75.0 repairs that dependency.
The new supplier also rejects the old RPC key. The
[compatibility analysis][supplier-analysis] records the released source evidence.

Keep the existing `ReportWave` and RPC transport for this release. Update managed
convergence, committed package wiring, doctor guidance, and reverification together,
following the [borrowed-package recipe][borrows]. Preserve fresh context, caller
checkout, the report restriction packet, top-level structured output, task
restoration, acceptance/intercom overrides, deadline partials, and cancellation.
The [subagent][subagents] and [wave][waves] learnings explain why these are load-bearing.

Prove restriction delivery under the supplier's new trust behavior. If it fails,
make a supported required-extension mechanism part of the compatibility fix or
refuse the affected launch before child work. Do not solve the failure by granting
project trust or rewriting the supplier's private configuration. A broader child
capability redesign stays outside the pin.

### 2. Enforce and certify the minimum

Use one shared minimum declaration, consumed by both planes. Refuse a Pi below
**1.0.0** at the resolved CLI launch boundary and at the loaded extension/worker SDK
boundary. Keep init, doctor, help, and repair guidance usable. A PATH executable,
the development SDK, and a worker's loaded SDK are separate observations.

Align the Node requirement with **22.19.0**, make remote install/test versions
explicit, and preserve wildcard host peers and bare-clone loading. Keep exact
development pins distinct from minimum admission. Certify **published Pi 1.0.0**;
a later patch or the source mirror's main branch cannot establish that floor.

Remove the unused direct `pi-client` and `pi-server` development pins after the
import/packaging census confirms their absence. Update the bump recipe, lockfile,
and lockstep test accordingly. Retain pins needed to prevent stale direct peer
resolutions. The [installation learning][install-learning] distinguishes those
requirements from the separate `.pi/npm` supplier installation.

### 3. Repair evidence and characterize restoration

**Fix valid system messages being rejected by `/learn`.** Accept the string-content
arm and preserve entry IDs, parent links, and bounded system content. Keep the
existing lenient parser and nested-call handling. Branch integrity is the release
requirement; richer section/tool-delta analysis belongs in follow-up 3. This gap
was explicitly recorded in the discovery pilot's follow-ups.

**Characterize delayed MCP restoration on exactly 1.0.0.** Pi retains pending tool
selections while servers register, but its active-set setter can clear pending
restoration when Perk removes one of its own tools. The recent own-name policy
protects visible foreign selections; this proposed test concerns names that have
not registered yet. Compare Perk reconciliation with a control, within Pi's
restoration window, before alleging a regression.

If the test demonstrates Perk-induced selection loss, fix the narrow activation
interaction through public 1.0 interfaces before declaring support. Retain the
existing enforcement policy. If no supported fix preserves the required behavior,
hold the floor decision rather than treating an upstream-main fix as a 1.0 fix.
This does not require a new MCP permission system.

### 4. Finish three worker capabilities

This is the release's one deliberate capability expansion. Keep it confined to
the existing [SDK adapter and stage-execution boundary][worker-adapter]:

| Addition | Required behavior |
| --- | --- |
| Native factories | Supply Pi's public discovery, codemode, and MCP factories through the services resource loader, preserving builtin identity, configuration, and disable semantics. Bind the session explicitly. Reuse Perk's existing discovery cohort and primers. |
| Registration before selection | Load authorized project extension providers/native providers/virtual models before explicit model resolution and the no-model check. Preserve Pi's default-selection chain and stage model/thinking overrides. Never select the first catalog entry as a new default. |
| Model-tool usage | Count tool-driven model usage once, including incurred usage on failed calls. Avoid nested/parent duplication and reasoning-token double counting. Preserve token, turn, and wall-clock limits; keep monetary or non-token usage distinct. |

Preserve the throwaway agent directory, global-resource exclusion, explicit auth
boundary, compaction/retry choices, and workflow terminal predicates. Configuration
determines activation; registering native factories does not turn every feature
on or add servers. Any gated stage continues to use the current restricted policy.
Configured headless authentication must either work or refuse with useful guidance.

Replace the worker's deliberate discovery-nonparticipant assertion with capability
and opt-out cases. Test extension-backed model registration through the production
order, not just a provider manually seeded into a test runtime. Adding model-using
tools and their accounting is one deliverable; partial adoption must not make the
worker's budget silently undercount.

### 5. Take the native default and preserve proven adaptations

Stop seeding `tuiMode: "fullscreen"` now that Pi supplies that default. Preserve
every existing explicit value: Perk cannot distinguish an old seed from an
operator's choice. Keep `defaultTools` convergence and its opt-outs unchanged.

| Keep and reverify | Reason / retirement condition |
| --- | --- |
| Host SDK bridge | Removes duplicate SDK graphs and preserves identity. Retire only after the supported host loader demonstrably supplies those guarantees. |
| `/btw` live-runtime adaptation | Preserves runtime-only auth and providers. Retire when a public side-session interface preserves that state. |
| Canonical projection and Perk delivery predicates | Pi projects context; Perk verifies its owned guidance/task evidence. Keep both responsibilities. |
| RPC contextless/stale responder guards | Absorb a demonstrated trust/loading failure. A fix to a different Pi RPC client is not replacement evidence. |
| Worker turn-cap enforcement | Prevents an extra request beyond the cap. Replace only with a public mechanism proven to preserve that behavior and terminal evidence. |

Inherit native OAuth, cache, rendering, and appearance improvements through the
upgrade. Verify the settings and CLI assumptions listed in the updates document;
make targeted corrections where needed. Keep TUI work inside the surfaces module.

## Follow-ups, in priority order

These are recommended work, with their own acceptance criteria. They are not gates
on the 1.0 release above.

### 1. Truthful access and simpler review lifecycles

**Outcome:** callers can report the access actually applied, and browser doors
share ownership of the asynchronous review operation.

Start with effective-access results from gate transitions, then consolidate the
repeated readiness, decision, supersession, and cleanup protocol above the existing
review slot and provider handoff. Keep subject-specific save/publication decisions
at their current boundary. The [review learnings][review-learning] explain both the
race classes and the previous simplification from persisted coordination to
in-memory guards; preserve that simplification. Use the
[small-interface recipe][seams-learning] rather than a general session controller.

**Why separate:** this changes caller contracts and asynchronous ownership without
being required by the Pi release. **First deliverable:** typed effective-access
outcomes with truthful notices. **Done when:** the shared browser lifecycle deletes
the duplicated protocol and tests cover stale bytes/destinations, late approval,
replacement, abort, and successor-safe cleanup. Aborting a wait still must not be
reported as stopping the supplier's server.

### 2. Native capabilities in restricted sessions

**Outcome:** planning sessions and report children can use useful native composition
without weakening their existing authority boundaries; side-session capabilities
remain deliberate.

Start with one useful eligible query and implement the recorded read-only codemode
rule. Then define explicit MCP server/tool authorization and child resource delivery,
including required-extension failure. Preserve provenance-based decisions and
top-level-only terminal/orchestration tools. A hidden declaration is not an
execution restriction, and `readOnlyHint` is not a grant. Define model-namespace
access separately from nested tool calls.

The learned read-only bar is **repository non-mutation**, not absence of all cache,
network, or model activity. Apply that existing meaning; do not accidentally invent
a stricter sandbox claim. Use the [execution-parity rule][parity-learning] to name
intentional differences between workers, reports, and `/btw` instead of copying the
parent's full resource set into every session.

**Why separate:** authorization and capability expansion deserve an explicit design
and end-to-end proof. **First deliverable:** one useful gated query composed under
both codemode modes. **Done when:** allowed reads succeed, denied direct/nested
effects remain denied, opt-outs work, and each supported child/side-session path
has a tested resource and auth boundary. Keep the present suspension until then.

### 3. Context and model observability

**Outcome:** maintainers can explain what guidance and tools reached a request,
which model performed the work, and what it consumed.

Start with bounded outgoing-request evidence using the existing prose map,
canonical projection, and [learning pipeline][evidence-learning]. Add useful system
section/tool-delta interpretation, selected-versus-physical model information, and
usage visibility through existing reports/surfaces. The worker's accounting repair
ships with the pin; the broader explanation and analysis belong here.

Evaluate classifiers against one existing triage task with a fixed quality baseline.
Adopt a classifier only if the measured result warrants replacing that judgment
path. Native image generation needs availability/accounting where supported, not
a new Perk workflow tool. Keep routing, cache management, and projection with Pi.

**Why separate:** instrumentation and workflow intelligence need their own user and
quality criteria. **First deliverable:** explain a cold turn, a warm transition,
and a post-compaction turn from actual request evidence. **Done when:** the evidence
distinguishes historical presence from delivery, model identity from routing, and
token/cache/cost measures without double counting or exposing a new control plane.

### 4. Reduce report-execution coupling

**Outcome:** choose the smallest supported execution integration that preserves
Perk's report contract and reduces maintenance obligations.

Compare structured supplier delegation first. Evaluate ordinary Pi SDK execution
when the smaller surface cannot meet the contract or leaves the substantive burden
unchanged. Compare above the script-shaped transport, behind `ReportWave`; preserve
assignment identity, opaque references, drain-once collection, completeness, deadline
partials, and cancellation. Count agent/resource loading, credentials, restrictions,
compaction, supervision, packaging, and wake behavior as responsibilities acquired.

**Why separate:** replacing transport can become acquiring an execution platform.
**First deliverable:** a public-API feasibility and ownership comparison against
the upgraded RPC implementation. **Done when:** viable candidates face the same
behavior suite and an adopt/keep decision names obligations removed and acquired.
Keeping the supplier is a legitimate result. Do not commit to a replacement first.

Keep Plannotator and pi-web-access meanwhile. A Pi session SDK does not supply
browser review semantics, and native MCP does not itself supply equivalent web
search/extraction. Revisit either only with a concrete service-contract match.
The [provider-seam learning][provider-learning] supplies the existing criterion
for adding an adapter; a new capability alone does not justify another seam.

## Disposition of the updates document

| Updates proposal | Recommendation |
| --- | --- |
| Tool catalog, model-only boundaries, structured results, nested evidence, discovery/defaults | **Already landed.** Preserve and extend through their existing seams. |
| Work packages 1–2: exact-release characterization and supplier migration | **Pin.** Characterize the release and adapt the supplier together. |
| Work package 3: access/discovery policy | **Split.** Late-MCP restoration compatibility goes in the pin; effective-access outcomes go to follow-up 1; restricted composition and new grants go to follow-up 2. |
| Work package 4: evidence grammar and observation | **Split.** Valid system-message parsing/ancestry goes in the pin; richer deltas and outgoing-request observation go to follow-up 3. |
| Work package 5: capabilities across session types | **Split.** The three worker additions go in the pin; restricted/report/side-session expansion goes to follow-up 2; broader routing/usage presentation goes to follow-up 3. |
| Work package 6: browser operation owner | **Follow-up 1.** Preserve current review guarantees during the pin. |
| Work package 7: supplier/SDK and classifier comparisons | **Follow-ups 4 and 3.** Neither comparison delays the floor. |
| Work packages 8–9: packaging, enforcement, certification | **Pin.** Include the bounded dependency/default deletions and exact-floor proof. |
| Bridge, `/btw` runtime probe, RPC guards, projection, turn-cap wrapper | **Keep and reverify.** Remove only against a demonstrated replacement. |
| Larger deferred families, new MCP grants, workflow classifiers, new supplier replacements | **Follow-up.** Require usefulness and behavior evidence; no automatic expansion from API availability. |
| Pi-durable, experimental harness/host migration, new objective conductor | **Deferred outside this program.** |

## Release sequence and acceptance

Implement in this order: **supplier compatibility → evidence/restoration fixes →
bounded worker adoption → minimum enforcement and cleanup → exact-floor
certification/publication**. Stage an exact-1.0 test environment from the beginning;
the final compatibility claim follows the evidence. Each implementation phase ends
on the repository's Perk dogfood gate before the next starts.

| Acceptance area | Evidence required for the pin |
| --- | --- |
| Actual installations | Record resolved CLI/SDK/supplier versions and paths. Install the pinned development tree in the checkout being tested and stage suppliers separately. Exercise published 1.0.0, bare-clone loading, supported host identity, lazy imports/reload, and an in-process child. |
| Admission and setup | Old/malformed/skewed hosts refuse before workflow work; exact 1.0.0 works; Node and remote setup agree; recovery commands remain usable; init is idempotent and preserves explicit preferences. |
| Supplier children | Successful and failed siblings, deadline partials, cancellation/late events, repeated collection, trust/restriction delivery, structured completion, and task restoration behave as contracted. |
| Evidence and restoration | System entries preserve branch ancestry and bounded content; nested evidence remains intact; delayed MCP registration is tested against the host control and Perk reconciliation. |
| Worker | Observe native tools on a real first request and test opt-outs; load a provider from project resources before selection; preserve auth isolation, explicit/default model selection, terminal success, abort, and caps; count model-tool usage once. |
| Existing sessions and surfaces | Preserve interactive discovery and model-only boundaries, read-only suspension, resume/tree/compaction, `/btw` auth/context/summary, browser review and annotations, and readable regular/fullscreen surfaces. No follow-up feature is required to pass this row. |

Keep regression coverage in the existing `pytest` and `node:test` suites. Use narrow
checks while iterating and the normal final gate; in a Perk implementation session,
that is one run-all `run_ci` immediately before submission. Amend cross-plane
contracts and matching user docs with each behavior change; mirror configuration
changes into perk-expert. Follow [init/doctor ownership][init-learning] for desired
state and repairs. New live evidence belongs under `docs/design/archive/`.

**Evidence limit for this memo:** the targeted discovery-worker test was attempted
during planning, but failed at module import because this checkout's installed
coding-agent/ai/agent-core/tui packages were **0.87.0**, while the manifest pins were
**0.99.2**. The missing export was `createToolSearchExtension`; the test body did not
run. This establishes an installation mismatch, not a failure of the six landed
PRs. Current-code claims above come from source and test inspection; the earlier
0.99.2 dogfood record remains dated evidence. No fresh runtime pass or Pi 1.0
certification is claimed here. The [planning-facts learning][facts-learning] is the
rule for rechecking those observations at implementation time.

[updates]: perk-updates-for-pinning-pi-1.md
[supplier-analysis]: perk-updates-for-pinning-pi-1.md#11-upgrade-pi-subagents-and-migrate-the-report-protocol-together
[discovery]: ../design/native-discovery-pilot.md
[worker-test]: ../../extension/worker/stageExecutionE2e.test.ts
[worker-adapter]: ../../extension/worker/sdkAdapter.ts
[bridge-learning]: ../learned/pi/native-sdk-bridge.md
[headless]: ../learned/pi/headless-session-drive.md
[borrows]: ../learned/workflow/borrowed-packages.md
[subagents]: ../learned/pi/subagents.md
[waves]: ../learned/workflow/report-waves.md
[install-learning]: ../learned/toolchain/worktree-node-modules.md
[review-learning]: ../learned/workflow/plan-review-flow.md
[seams-learning]: ../learned/pi/extension-seams.md
[parity-learning]: ../learned/workflow/execution-path-parity.md
[evidence-learning]: ../learned/workflow/learn-evidence-pipeline.md
[provider-learning]: ../learned/workflow/provider-seam.md
[init-learning]: ../learned/workflow/init-doctor.md
[facts-learning]: ../learned/workflow/planning-time-facts-decay.md
