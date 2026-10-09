# Pre-pi-durable true-up

Date: **2026-10-09**. Grounded in perk **4.0.0** at `8eefff4d` and the completed
[Pi 1.0 objective #2656][objective]. This is an implementation roadmap, not a
claim that its target versions or proposed capabilities have been certified.

## Recommendation and decisions

**Adopt Pi 1.1.0 and pi-subagents 0.76.1, finish the concrete integration gaps,
and close the speculative proposals explicitly.** Pi 1.1.0 becomes both the exact
development/remote-install pin and the minimum supported host. Keep the current
Pi extension, SDK worker, report-wave RPC transport, Plannotator, and pi-web-access.

This document consolidates the Pi-related planning outside `docs/planning/pi-durable/`;
that directory was excluded from the investigation. It owns the sequencing below.
Earlier assessments remain historical evidence, and their unimplemented proposals
do not automatically become requirements. The operator chose useful work on the
current stack over new execution platforms or speculative feature expansion.

The scope decisions are:

- Enable restricted local-tool composition in **planning/refinement sessions only**.
  Keep report children on their explicit toolsets and keep MCP denied in restricted
  sessions and report children. A new server/tool grant system is deferred as a
  separate feature, not an obligation of this program.
- Add **project-only MCP to the SDK worker**, with an isolated resource directory,
  explicit configured credentials, and actionable refusal when OAuth sign-in is
  required. Do not reuse persistent user MCP OAuth credentials.
- Keep the existing review-feedback classifier and improve its evidence boundary.
  Do not run a native-classifier or model-routing experiment.
- Use Pi's existing diagnostics. Improve transcript interpretation and existing
  selfcheck/report surfaces; add neither a custom request observer nor a permanent
  per-turn recorder.
- Fix browser lifecycle defects and demonstrated feedback loss. Do not add rich
  thread/diagram feedback or a new per-child progress interface.
- Preserve manual plan-save's transcript fallback; review remains artifact-based.
- Retain tested upstream limitations, including constrained worker model calls and
  the absence of report collection across reload. Do not acquire accounting or
  recovery infrastructure to remove those limitations here.

## Baseline and evidence boundary

The release targets were rechecked through npm and GitHub on the date above.
[Pi v1.1.0][pi-release] was published on October 7 and names commit
`abe508e1b89912adde45528136c3221eb69acdd7`.
[pi-subagents v0.76.1][subagents-release] was published on October 6; its npm
`gitHead` is `7d072b91dca7e1aa915282f0159cec0175d65efa`.
Upstream behavior described below is source-derived unless it cites a dated
runtime record. This planning investigation performed no target-pair live
certification.

The release-source checks used Pi's [MCP factory][pi-mcp],
[model-runtime options][pi-model-runtime], [codemode factory][pi-codemode], and
[codemode execution][pi-codemode-execute], plus the supplier's
[delegation contract][supplier-delegation], [frontmatter parser][supplier-frontmatter],
[parent-wake implementation][supplier-wake], and [RPC handlers][supplier-rpc].
These links are fixed to the audited releases, not a moving source mirror.

| Version fact | Current state | Target / rule |
| --- | --- | --- |
| Development SDK pins | Four `@earendil-works/*` development dependencies at 1.0.0; installed root SDK agrees | All four at exact 1.1.0, installed and verified in the resolving checkout |
| Host floor | Pi ≥1.0.0 in `shared/host-floor.yaml` | Pi ≥1.1.0, applied independently to the PATH CLI and each loaded SDK |
| Remote installation pin | `REMOTE_PI_VERSION = "1.0.0"` | Exact 1.1.0 for the global CLI and consumer worker SDK; self-repo worker uses the development pins |
| Supplier installation pin | `SUBAGENTS_PACKAGE = "npm:pi-subagents@0.75.0"` and matching committed Pi settings | Exact 0.76.1 through the existing convergence owner |
| Supplier guidance stamp | `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION = "0.75.0"` | 0.76.1 only after required reverification passes |
| Node / TypeBox | Node ≥22.19.0; TypeBox 1.3.27 | Unchanged; the published Pi 1.1.0 requirements agree |

An exact pin, a minimum, and a guidance stamp remain different facts. Admission
does not require the CLI and SDK versions to equal each other. Wildcard host
peers and bare-clone loading remain supported. If a later release appears before
implementation, re-audit it explicitly rather than silently replacing these
targets or installing a floating `latest` as evidence.

Objective #2656 is closed and perk 4.0.0 has shipped. The
[Pi 1.0.0 certification record][certification] nevertheless remains **PENDING**:
43 of 46 required rows passed; **X5b** (PR browser door), **S7** (repeated
collection), and **I7b's PR-door launch proof** were deferred. Earlier supplier
browser passes on Pi 0.99.2 do not fill those cells. This program must fully prove
the new pair while preserving the historical record's actual observations.

## Source-to-disposition ledger

**Completed** means current implementation or dated evidence resolves the proposal.
**Implement** names a work package below. **Superseded** means a later decision or
implementation replaced the proposal. **Declined** means it is outside this
program by an explicit scope/value decision. **Retained constraint** names a
supported limitation and the evidence needed to revisit it.

### Existing integration and completed work

| Proposal and source | Current evidence / disposition | Owner or acceptance |
| --- | --- | --- |
| Establish a real compatibility baseline — [v3 R1][v3], [deep opportunities][deep] | **Implement.** Existing pins/floor are real; the target pair is not yet certified | WP1, WP7: actual installations and full target-pair matrix |
| Canonical context projection — [September 21 Pi assessment][pi-sep21], v3 R2 | **Completed.** `activeContextMessages` uses Pi's canonical session projection | WP7 preserves edit/compaction behavior |
| Session-only reads and startup facts — v3 R3 | **Completed.** `WorkflowSession`, named active-session reads, and resolved startup facts exist | Preserve their lifecycle ownership |
| Session picker, names, run-ID resume — [session-management plan][sessions] | **Completed.** Session-resume positioning and session-name modules implement them | WP7 resume/navigation regression coverage |
| `/btw` seeding and public summary streaming — September 21 assessment | **Completed.** The remaining private live-runtime probe is a separate retained adaptation | Retention table below |
| Shared model dispatch / LLM plan titles — v3 R5 | **Superseded.** LLM title generation and `completeStructured` were removed; titles use the first heading | Do not recreate a dispatch layer for the retired caller |
| Worker initialization and one terminal outcome — v3 R6 | **Completed.** `runStage` encloses initialization and produces the terminal envelope | WP7 preserves initialization/error/abort cases |
| Tool catalog, own-name activation, provenance, structured results, nested evidence — [September 29 assessment][pi-sep29] F1–F3 | **Completed.** `registerPerkTool`, policy/loadout seams, and bounded nested evidence landed | Extend existing seams in WP4/WP6; no second taxonomy |
| Initial deferred family, primers, `+tool_search` convergence — [Pi 1.0 recommendations][recommendations] | **Completed.** Native-discovery pilot and settings opt-outs landed | Preserve the adopted family; no blanket expansion |
| Supplier `workflowScript`→`script`, removed host alias — [RPC migration][rpc-fix], [Pi 1.0 updates][updates] | **Completed.** #2656 adopted 0.75.0 and the `script` payload | WP1 reverify; no legacy dialect retry |
| System-message grammar and branch ancestry — Pi 1.0 updates | **Completed.** String/null content is accepted without breaking ancestry | WP6 owns richer interpretation, not another parser repair |
| Late MCP restoration — Pi 1.0 updates | **Completed.** The [restoration-window repair][mcp-restoration] delays removals while preserving immediate enforcement | WP1/WP7 rerun against the target release |
| Worker registration-before-selection, discovery/codemode factories, tool/compaction usage, native retry/compaction — #2656 | **Completed.** SDK adapter and real-runtime worker tests implement them | WP5 extends resources; retain budgets and settings behavior |
| Shared floor, pre-import SDK admission, four-package pins, explicit remote pins, fullscreen seed removal — #2656 | **Completed.** Reuse those owners; explicit operator settings remain intact | WP1 updates values and target-release compatibility |
| perk 4.0.0 publication — #2656's former non-goal | **Completed.** Release commit follows certification work | Do not schedule the old release again |

### Unfinished work, narrowed proposals, and exclusions

| Proposal and source | Current evidence / disposition | Owner or acceptance |
| --- | --- | --- |
| Effective access and shared browser lifecycle — deep opportunities, recommendations follow-up 1 | **Implement.** Gate transitions return void; plan/objective coordination is duplicated; PR/stack cleanup is not fenced to its surface | WP3: truthful outcomes and successor-safe ownership |
| Full plan-save outcomes — [command-interface opportunities][commands] §2 | **Implement.** `renderSavePlanOutcome` drops `linkage`/`claimClear` facts from its result | WP3: preserve saved success and expose incomplete reconciliation |
| Restricted native composition — updates §4.2, recommendations follow-up 2 | **Implement, narrowed.** Planning/refinement local reads and eligible queries only | WP4: direct/nested policy and codemode `on`/`only` usability |
| Restricted/report MCP grants and report codemode — updates §4.1–4.2 | **Declined for this program.** New authorization/resource-loading complexity is not justified by current report tasks | Keep MCP denied and report toolsets unchanged |
| Worker MCP — #2656 node 3.3 and certification W3 | **Implement.** Worker supplies no MCP factory today | WP5: project-only resources, isolated global tier, headless refusal |
| System sections/tool deltas, model/usage visibility — recommendations follow-up 3 | **Implement.** Parser drops richer system data; selfcheck is a pre-filter projection | WP6: bounded interpretation and truthful existing surfaces |
| Outgoing-request observer and retained request evidence — deep opportunities, updates §4.4 | **Declined.** Use existing Pi diagnostics; no new recorder, storage policy, or provider-payload parser | WP6 must not call projected context proof of delivery |
| Native classifier/routing comparison — Pi assessments, recommendations follow-up 3 | **Declined.** No measured problem warrants another judgment path | Keep current classifier; WP6 fixes prepared-input identity/coverage |
| Prepared review-feedback classification — command-interface opportunities §1 | **Implement.** Child still fetches feedback and supplies identity/counts without binding to a prepared snapshot | WP6: code-owned membership, coverage, and totals |
| Explicit artifact migration — command-interface opportunities §4 | **Declined.** Manual-save transcript fallback is intentional compatibility | Keep review artifact-only and the manual fallback |
| Typed report waves and static flow migration — [supplier improvements][subagents-improvements] | **Completed.** `ReportWave` owns correlation, typed aggregation, completeness, receipts, and drain-once collection | Preserve its caller contract |
| Dynamic angle selection — supplier improvements | **Superseded.** Implemented and later retired with dynamic review | Do not recreate the retired workflow |
| Provisional supervisor streaming — [September 5 supplier assessment][subagents-sep05], supplier improvements | **Superseded.** Completion-only collection and final annotation delivery are the current contract | WP2/WP7 verify completion/wake behavior |
| Finished-sibling deadline retention — v3 R7, supplier improvements | **Completed.** Validated native partials are retained while the activation owns the wave | WP2/WP7 verify on the new pair; collection across reload is separate |
| Descendant ceilings — [September 21 supplier assessment][subagents-sep21], [0.72.1 audit][subagents-audit] | **Implement.** Existing leaf instructions are not enforced by `allowedAgents` | WP2: foreground/background denial and unchanged parent access |
| Required child-extension registration — September 21 supplier assessment, deep opportunities | **Retained constraint / conditional fix.** #2656's trust matrix passed using existing delivery; a new registration mechanism was evaluated and not adopted | WP1/WP2 must prove delivery or refuse launch; do not add a mechanism without a demonstrated gap |
| Foreground resolver intercom policy — [package release audit][packages-audit] | **Implement.** Foreground delegation still omits the per-launch override | WP2: explicit bridge-off for both writer callers, no global setting change |
| `fallbackModels`, `completionGuard`, forced FFF, obsolete host-tool diagnostic, SDK census additions — supplier assessments/audit | **Completed.** Obsolete controls were removed; the eight-specifier SDK census and lazy-activation composition exist | Reverify, rather than repeat the removals |
| Lifecycle/terminal diagnostics — v3 R8, 0.72.1 audit | **Implement, narrowed.** Failure and uncertain-termination reporting only | WP2; no duplicate of Fleet or full child-status UI |
| Wave spend attribution — 0.72.1 audit | **Retained constraint.** Supplier cost discovery does not reliably identify perk RPC waves | Show unavailable spend honestly; no artifact accounting scanner |
| Reload-safe report recovery — v3 R7, supplier audit | **Retained constraint.** References and pending results belong to the activation; public status is not a complete typed aggregate | Characterize freshness on relaunch; no persistence, automatic resume, or artifact recovery |
| Structured supplier / ordinary-SDK report executor comparison — recommendations follow-up 4 | **Declined replacement; keep decision grounded in source.** Structured delegation lacks the async/extension-binding report contract | Retain script RPC and foreground structured delegation for their existing roles |
| Approval-note loss, early subscription, pinned stack patch — [browser assessments][browser-sep05], [September 21][browser-sep21] | **Completed.** Existing handoff and static-patch stack review implement them | WP3/WP7 preserve feedback and source identity |
| Threaded metadata, diagram feedback, richer archives — browser assessments | **Declined expansion.** Fix existing feedback loss only when demonstrated | WP3: existing supported payloads and dedupe fidelity |
| Persistent browser recovery — September 5 browser assessment | **Superseded.** Review uses in-memory guards; restart recovery is rerunning the door | Do not introduce a persisted review controller |
| Inspector providers, adaptive exploration, extra writers/watchdogs, standalone packaging, named workflows, blanket tool deferral, cache tuning — supplier/Pi opportunity inventories | **Declined for this program.** No established task or measured benefit justifies the added surface | Preserve native configuration and current interfaces |
| Host/Harness/Chord migration, format-4/value migration, detached presentation — [first memo][memo1], [v2][memo2], v3 E1–E4 | **Declined for this program.** Separate architecture research | No prerequisite work imported from the excluded durable program |
| Objective conductor / unattended policy — [headless planning][headless], [Pi session driving][session-driving] | **Declined for this program.** A new execution product, not current-stack compatibility | Preserve existing worker isolation, budgets, and terminal evidence |
| Command-owned PR rebase/publication procedure — command-interface opportunities §3 | **Declined for this program.** Separate delivery redesign | Preserve current resolver modes and lock authority |

## Ordered work packages

Sequencing is owned by the approved roadmap of [Objective #2707][objective-2707], not by this document: WP1 is phase 1, a strict chain (1.1 → 1.2 → 1.3 → 1.4, the "pair adopted" gate); WP2–WP6 are phases 2–6, which fan out from node 1.4 and may be planned in parallel (within a phase, nodes chain in the order written here, except 2.4, which depends only on 1.4); WP7 is phase 7 and depends on every phase terminal. Each package is a bounded plan
or a small sequence of plans, rather than one combined upgrade/refactor PR.
Each phase ends with perk driving the next phase's first plan. Automatable
preconditions belong in the existing test suites.

| Package | Existing implementation boundary | Focused regression homes |
| --- | --- | --- |
| WP1 | Pin/convergence owners; [shared floor](../../shared/host-floor.yaml); CLI and SDK admission | `tests/test_packaging.py`, `tests/test_host_floor.py`, `tests/test_native_sdk_bridge_live.py`, `extension/substrate/hostAdmission.test.ts`, `extension/substrate/nativeSdkBridge.test.ts` |
| WP2 | [ReportWave](../../extension/waves/reportWave.ts) and [foreground delegation](../../extension/pi/v1/foregroundDelegation.ts) | `extension/waves/reportWaveRpc.test.ts`, `extension/pi/v1/foregroundDelegation.test.ts`, `extension/pi/v1/delivery/conflictResolverEngine.test.ts`, child task-restoration suites |
| WP3 | [ToolGating](../../extension/substrate/toolGating.ts), approval/save projections, existing browser doors | `extension/authoring/review/approvalGate.test.ts`, plan/objective browser tests, provider annotation/handoff tests, Python plan-save golden fixtures |
| WP4 | [Tool policy](../../extension/substrate/toolPolicy.ts) and [stack-status registration](../../extension/pi/v1/delivery/stackStatus.ts) | `extension/substrate/toolGating.test.ts`, `extension/substrate/toolPolicy.test.ts`, `extension/pi/v1/delivery/stackStatus.test.ts`, real-session composition cases |
| WP5 | [Worker entry](../../extension/workerMain.ts) and [SDK adapter](../../extension/worker/sdkAdapter.ts) | `extension/worker/stageExecutionE2e.test.ts`, SDK admission and model-call policy suites |
| WP6 | [Learning parser](../../src/perk/learn/session_jsonl.py) and [review classifier](../../extension/waves/reviewClassifierWave.ts) | `tests/test_learn_session_jsonl.py`, `tests/test_pr_feedback_cmd.py`, `extension/waves/reviewClassifierWave.test.ts`, selfcheck/worker fixtures |
| WP7 | Existing supplier reverification and certification procedure | Live matrix below; guidance-stamp assertion in `tests/test_doctor.py` |

### WP1 — Characterize and adopt the exact release pair

Start from the existing [supplier reverification procedure][reverify],
[Pi characterization][characterization], and certification matrix. Stage published
Pi 1.1.0 and pi-subagents 0.76.1 in an isolated installation. Record resolved CLI,
SDK, worker SDK, and supplier versions and paths; source inspection alone does not
prove a working installation.

Audit the entire released delta from the current pins, including these changes:

- Pi's tool selectors now preserve unmatched MCP tools; wildcard and additive
  selectors are supported. A builtin read allowlist is not an MCP exclusion.
- Loadout prompt guidelines now respect hidden declarations. New renderer fields
  and `agent_settled.aborted` require checking typed fixtures and cancellation
  translation. Settlement still does not establish perk workflow success.
- MCP project overrides, connection shutdown, OAuth cancellation, and timeout
  behavior changed. Preserve the existing restoration-window guarantees.
- The Azure provider was renamed to `azure`. Document applicable native migration
  guidance without rewriting user credentials or inventing provider aliases.
- Supplier 0.76.x changes headless completion delivery, normal prompt setup when a
  completion wakes its parent, queued-completion liveness across reload, and
  refusal of an in-process supplier-version change. Upgrade with a fresh process.

Then update the four development packages via `just bump-pi 1.1.0`, the resolving
installation and lockfile, `REMOTE_PI_VERSION`, the shared floor, supplier
convergence, and committed Pi settings. Regenerate managed remote artifacts
through their owner. Preserve package filters/order, explicit settings, the
existing `script` wire protocol, and separate remote consumer/self-repo installs.
Install the new development pins before raising SDK admission, so real-runtime
tests are never bypassed to make the floor change pass.

**Acceptance:** packaging/pin lockstep, CLI and pre-import SDK admission, malformed
and below-floor versions, independently admitted unequal CLI/SDK versions,
bare-clone loading, actual supplier import census, an in-process child identity
proof, and real-runtime worker suites pass. Historical fixtures stay historical.
The guidance stamp remains 0.75.0 until both browser legs and the other required
reverification evidence pass; WP7 owns any still-outstanding live legs. An interim
doctor warning is truthful, not grounds for an unevidenced stamp advance.

### WP2 — Enforce supplier policy and close lifecycle gaps

Use `ReportWave`, `WaveSpawnParams`, the existing RPC adapter, and foreground
delegation. Keep fresh context, caller checkout (`worktree: false`), the
`perk.parent-restrictions/1` packet, required skills, top-level structured output,
task restoration, and the explicit wave acceptance/intercom overrides.

Add an empty native `allowedAgents` ceiling to every leaf definition that already
forbids descendants: the current inventory is 11 shipped reports, conflict
resolver, librarian, and the repository auditor. Recount at implementation. The
supplier parser treats an empty `allowedAgents:` as the empty list; literal
`allowedAgents: []` is not equivalent. Test actual definition loading. Set
`intercomBridge: {mode: "off"}` explicitly in both foreground writer launch
contracts and dispatch, preserving each writer's authority and cancellation rules.

Exercise actual awaited-child notifications (`parentWorkflowRunId`,
`awaitedByWorkflow: true`, `triggerTurn: false`) before spawn replies and while
siblings remain active. Cover lazy loading, duplicate responders, same-version
reload with queued completions, required extension/skill delivery, parent wake
prompt preservation, structured failures, partial settlement, and stop after a
paused result has already been delivered. Unknown process termination must remain
unknown; a freed supplier capacity slot is not proof a writer stopped.

Reproduce [#2660][headless-loop] with the new pair and a no-perk control. Record
whether it persists and its supported-path impact; do not infer a fix from release
notes. The ancillary worker `[object Object]` error-formatting bug is already fixed.
An upstream-only reproduction outside perk's `worktree: false` report path remains
an explicitly attributed limitation, not a fabricated perk regression or repair.

**Acceptance:** descendant attempts fail in foreground/background children while
parent launch access and valid completion remain intact. Both resolver modes and
librarian success/blockers/cancellation preserve lock and filesystem boundaries.
Direct/nested MCP calls cannot escape the report floor on the new host. Do not
blindly add `excludeTools: mcp__*`: supplier exclusion/forwarding semantics are not
equivalent to Pi's selectors. Repeated collection drains once, finished partials
remain incomplete evidence, and reload/relaunch never silently presents reused
old reports as a fresh inspection. Preserve the no-collection-across-reload rule;
any freshness correction must stay within supported launch controls.

### WP3 — Truthful access/save outcomes and shared browser ownership

Change `ToolGating.enter`, `exit`, and `syncFromState` to report the effective
access and whether the requested transition applied, remained restricted, or
failed. Propagate the result through approval/save, mode toggles, and implement-here.
Keep persistence and installation failures fail-closed. A child floor must never
produce a “full tool access restored” notice or an unearned `gateExited` result.

Carry `SavePlanOutcome.linkage` and `claimClear` through the existing save-result
projection. Preserve the distinction between an issue successfully saved and local
session reconciliation that needs repair. Use the same facts in machine details
and human reporting, including real Python-producer/TypeScript-consumer fixtures.

Create one browser-operation owner above `DraftReviewSlot` and the existing
provider handoff. It owns readiness, decision observation, replacement fencing,
background tasks, console interception, and cleanup. Apply it to plan/objective
and PR/stack doors. An older PR review currently can clear a newer annotation
surface when it settles or degrades; reproduce this source-observed risk and fix
ownership rather than adding more independent flags.

Keep subject-specific save, direct-edit, destination, and publication rules with
their current callers. Preserve reviewed-byte identity, early-decision buffering,
and the distinction between aborting a wait and stopping a supplier server. Keep
all presentation through the surfaces module.

**Acceptance:** restricted/failed transitions produce truthful outcomes; a saved
issue survives a reported reconciliation failure; stale bytes/destinations,
replacement, early/late decisions, degradation, abort, and successor-safe cleanup
are tested. Test existing feedback coordinates/text and distinct findings at one
anchor; change metadata/dedupe behavior only for a demonstrated loss. No new rich
feedback product or persistent review recovery is part of the package.

### WP4 — Useful restricted composition for planning

*Deviation 3 (below) narrows the `only` arm.*

Use the existing tool catalog, eligibility policy, loadout host, and tool-call
gate. Make `objective_stack_status` eligible in planning/refinement sessions where
its existing objective/worktree preconditions hold. Do not add filesystem wrappers
just to populate a perk query catalog.

For nested execution, use Pi's `parentToolCallId` to admit eligible perk queries
and allowed builtin reads, including commands accepted by the existing bash
verdict. Direct workflow writer carve-outs do not become nested grants. Terminal,
interactive, and orchestration tools remain top-level/model-only. Tool hiding and
discovery do not constitute authorization; denied effects must fail at execution.

Prove that codemode `on` and `only` can perform useful local read work before
removing suspension in these planning sessions. Preserve opt-outs and the
restoration window. MCP remains denied under the gate; `readOnlyHint` never grants
access. Report child toolsets and `/btw` stay unchanged.

Model calls are a separate axis: the read-only guarantee is repository
non-mutation, not absence of all model/cache activity. Do not claim nested-tool
hooks govern the CLI builtin's `models.*` namespace. Preserve native interactive
model behavior and the SDK worker's hard `models: false` constraint; this package
adds no model-budget mechanism or report-child model capability.

**Acceptance:** an eligible planning query and local reads work in both codemode
modes; direct and nested writes, unsafe bash, terminal/orchestration calls, unknown
tools, and MCP remain denied. Child floors, stage transitions, reload/tree restore,
and discovery opt-outs keep their existing guarantees.

### WP5 — Project-only MCP in the SDK worker

*Deviation 1 (below) replaces the `PI_CODING_AGENT_DIR` mechanism described here.*

Extend the existing standalone worker process and `workerBuiltinExtensions`.
Set `PI_CODING_AGENT_DIR` once for the entire worker process to its throwaway agent
directory, then supply native `createMcpExtension()` beside discovery/codemode.
Preserve builtin identity and disable semantics. Pi's default MCP configuration,
credentials, refresh locks, and log then resolve inside that isolated directory,
while trusted project configuration and project-extension registrations remain
available.

Capture the original model-auth/model-config paths and pass them explicitly to
public `ModelRuntime.create({authPath, modelsPath})`. Model authentication remains
separate from resource inheritance. Do not toggle process environment around
concurrent in-process sessions or import private MCP config/store implementations.
Pi 1.1.0 exposes the factory but not those internal constructors as public package
entrypoints; process isolation avoids owning another config reader or token store.

Support project-configured stdio and HTTP servers with explicit environment/header
credentials. A server requiring unavailable OAuth credentials must report useful
headless sign-in guidance without opening a browser or hanging. Do not copy user
MCP credentials or connect user-global servers. Keep the directory alive through
native connection shutdown, then clean it up. Project extensions that deliberately
implement their own resource loading remain outside this factory guarantee.

**Acceptance:** real-runtime fixtures plant global servers/credentials and prove
they are untouched; project file and extension registrations work; disabled and
untrusted resources stay disabled/untrusted; missing auth refuses legibly; late
registration, reconnect, cancellation, and shutdown close transports before
cleanup. Existing provider selection, model authentication, retry/compaction,
count-once usage, and no-extra-request budget tests remain green.

### WP6 — Better existing evidence and classifier correctness

Extend `session_jsonl.py` and its existing projection pipeline to interpret bounded
system `sections`, `toolsAdded`, `toolsRemoved`, and compaction `systemMessage`
data. Keep branch ancestry and lenient parsing: malformed optional metadata must
degrade locally rather than discard an otherwise readable entry. System guidance
is never user authorization or a workflow terminal event.

Improve existing selfcheck/report output for selected versus physical model
identity and available fresh-token, cache, and monetary usage. Count each owned
usage source once; keep unavailable values distinct from zero and image/non-token
usage distinct from token budgets. A canonical pre-filter projection remains an
upper bound on context, not proof of the final outgoing request. Use Pi diagnostics
for request-level investigation; introduce no request observer, payload parser,
retained request log, or new control surface. RPC-wave cost remains unavailable
unless the supplier supplies authoritative owned-run attribution.

For `/address`, prepare feedback through the existing Python feedback command and
bind the classifier to that snapshot. Keep the current agent and useful summaries.
Validate returned PR/item identity, membership, uniqueness, and required coverage;
derive counts and other mechanical facts in code. A syntactically valid report
with invented or missing items is not accepted. Preserve the existing posture of
surfacing an invalid/incomplete classification rather than fabricating a result.

**Acceptance:** normal, malformed, oversized, historical, and compacted transcript
fixtures preserve ancestry and bounded evidence. Virtual-model cases distinguish
selection from physical execution; usage does not double count nested aggregates.
Classifier fixtures cover duplicates, unknown/missing IDs, wrong subjects,
inconsistent/negative supplied counts, resolved/outdated feedback, and discussion
comments. Existing classification vocabulary and authorization/terminal rules stay
unchanged. No alternative classifier benchmark is required.

### WP7 — Complete live certification and maintain the release procedure

Give the live legs a dedicated node using already-landed changes and an available
PR. A browser-door proof must not depend on reviewing its own not-yet-created
implementation. Run doctor/scout, both browser doors, repeated collection, PR-wave
launch, and the expanded capability matrix on the exact target pair. Move the
guidance stamp and its assertion only when all required supplier evidence passes.
Until then, support/guidance prose must state the narrower evidence available.

Use the five existing browser criteria: every requested lane is runnable, complete
coverage has no failures, each angle's final replacement push is receipted with
nothing held, the decision follows the last push, and the owner confirms the
surface. Required live failures hold the new support claim. The old 1.0.0 PENDING
cells stay historical; passing their equivalent scenarios on 1.1.0 closes current
coverage debt without retroactively certifying 1.0.0.

Reconcile current contracts, operator documentation, expert references, developer
reverification instructions, and design descriptions in the turns that change
their behavior. Correct the obsolete child-policy inventory/fork-fix wording and
the reverification guide's unconditional bare `just ci` instruction. Archive new
characterization/dogfood/certification evidence under `docs/design/archive/` with
exact versions and honest verdicts. Route new durable learnings through `/learn`.

Consolidate future upkeep into the existing reverification procedure: record the
current and target version facts, audit published deltas, update all pin surfaces,
run compatibility/identity/policy tests, elect live-leg owners, recheck adaptation
retirement conditions, and update evidence-contingent documentation. Do not add a
parallel dependency-update service or silently refresh version stamps.

## Deviations recorded by Objective #2707

Recorded by node 1.1 ([characterization record][characterization-1.1.0]); the prose above is the seed as written and is not rewritten here.

1. **Phase 5 mechanism (WP5).** Factory-scoped isolation through Pi's public `McpExtensionOptions` (`loadConfig`, `credentials`, `logPath`, `openUrl`, `updateConfig`) replaces the process-wide `PI_CODING_AGENT_DIR` override and the explicit `ModelRuntime.create({authPath, modelsPath})` — the seed assumed those options were private; they are public, and the override would break supplier-child model auth (pi-subagents' child factory calls a bare `ModelRuntime.create()` and `getAgentDir()`; background children inherit the process env) and worker session persistence (`SessionManager.create(worktree)` places the transcript under the directory the worker deletes at disposal).
2. **Lockfile rule in node 1.2 (WP1).** Pi ≥ 1.0.1 ships no `npm-shrinkwrap.json` (1.1.0 `_hasShrinkwrap: false`; the current lock's `hasShrinkwrap: true` describes the installed 1.0.0): the nested pi-coding-agent tree's removal/dedup is an intentional upgrade change to keep, not churn to revert; the learned pin-bump mechanics' "keep the shrinkwrapped tree" clause is 1.0.0-era and is corrected through `/learn`.
3. **Codemode `only` in node 4.3 (WP4).** Conditional: `only` is lifted only if a supported exposure/loadout treatment keeps the bounded writers (`plan_draft`, `objective_draft`, `objective_refinement_draft`) directly declared — Pi's `prepareCodemodeLoadout` hides every direct-exposure declared tool in `only` — instead of the seed's unconditional "on and only".

### Dispositions the characterization falsified

None — every disposition above survived the characterization.

## Retained adaptations and retirement conditions

| Adaptation or limitation | Why it stays / evidence needed to retire it |
| --- | --- |
| Host SDK bridge and consumer ordering | Pi 1.1.0's loader change adds renderer registration, not shared native-import identity. Require an actual replacement identity proof, including an in-process child and lazy imports. |
| `/btw` live-runtime probe and core-only resources | No public replacement preserves the parent's runtime auth overrides/providers. New image/classifier APIs do not supply that side-session contract. |
| Canonical projection plus perk delivery predicates | Pi owns projection; perk owns evidence that its guidance/task was delivered. Existing diagnostics do not collapse those responsibilities. |
| MCP restoration-window reconciliation | Remove only against a real delayed-registration control showing the supported host preserves selections without it. |
| Contextless/stale RPC responder guards | Reproduce duplicate supplier loading and prove removal safe. A fix in Pi's separate RPC client is insufficient. |
| Worker `finishTurn` cap | Pi 1.1.0 still lacks the required equivalent no-extra-provider-request guarantee. New settlement metadata is not a replacement. |
| Worker `models: false`, image/classifier refusal | Token usage still arrives at script completion; no public mid-script token meter or factory call bound exists. Preserve the absence-of-usage test and the current token/turn/time budget. |
| Activation-owned wave references | Public targeted status has terminal information and a preview, not the validated complete report aggregate. A new supported recovery contract is required; do not persist refs or scan artifacts here. |
| Unavailable RPC-wave spend | Native supplier cost discovery is not authoritative attribution for arbitrary perk RPC waves. Require an owned-run usage API before claiming totals. |
| Plannotator readiness, port, decision, and source-identity adaptations | Consolidate ownership in WP3; delete a workaround only after the installed provider demonstrates its exact replacement. |

## Acceptance and completion

| Area | Required evidence |
| --- | --- |
| Installations and admission | Resolved CLI/SDK/worker/supplier paths and versions; four-package and remote pin consistency; refusal before SDK symbol linking; bare-clone and native SDK identity proof |
| Supplier children | Leaf ceilings, fresh context, skills, restriction consumer delivery, direct/nested denial, awaited notifications, wake prompt preservation, deadline partials, cancellation, drain-once, and reload freshness |
| Access and browsers | Truthful transition/save results; all browser doors preserve source/decision identity; old operations cannot clear successors; existing feedback is not lost |
| Planning composition | Useful local reads and eligible queries in `on`/`only`; forbidden effects and MCP denied; report toolsets unchanged |
| Worker MCP | Project resources work without user-global MCP access; model auth remains intact; headless auth refusal, opt-outs, delayed connections, cancellation, and disposal are proven |
| Evidence and classification | Bounded tolerant system-data interpretation; honest projection/model/usage output; classifier membership/coverage bound to prepared feedback |
| Live certification | Both browser doors meet their receipt criteria; repeated collection and PR-wave launch pass on the new pair; no required row remains pending |

Use targeted pytest and node:test checks during implementation. In perk sessions,
the submission gate is one run-all `run_ci` immediately before submitting; its
green report is definitive. Pin/runtime changes also run `just test-js-slow`
explicitly because the run-all gate contains only the fast JavaScript tier. Reuse
the existing admission, SDK bridge, gate, browser, wave, worker, and learning suites;
do not substitute bespoke scripts for automatable regression coverage. Prose-tool
checks remain their separate opt-in suites when those tools themselves change.

The program is complete when all **Implement** rows have landed evidence, the new
pair is certified, current documentation agrees with the implementation, and every
other proposal has the explicit disposition above. Declined features and retained
upstream constraints are not unfinished implementation nodes. Starting the
pi-durable program is a separate planning decision.

[objective]: https://github.com/mattgiles/perk/issues/2656
[objective-2707]: https://github.com/mattgiles/perk/issues/2707
[headless-loop]: https://github.com/mattgiles/perk/issues/2660
[pi-release]: https://github.com/earendil-works/pi/releases/tag/v1.1.0
[subagents-release]: https://github.com/nicobailon/pi-subagents/releases/tag/v0.76.1
[pi-mcp]: https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/src/extensions/mcp/index.ts
[pi-model-runtime]: https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/src/core/model-runtime.ts
[pi-codemode]: https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/src/extensions/codemode/index.ts
[pi-codemode-execute]: https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/src/extensions/codemode/execute.ts
[supplier-delegation]: https://github.com/nicobailon/pi-subagents/blob/7d072b91dca7e1aa915282f0159cec0175d65efa/src/api/delegation.ts
[supplier-frontmatter]: https://github.com/nicobailon/pi-subagents/blob/7d072b91dca7e1aa915282f0159cec0175d65efa/src/agents/frontmatter.ts
[supplier-wake]: https://github.com/nicobailon/pi-subagents/blob/7d072b91dca7e1aa915282f0159cec0175d65efa/src/shared/parent-wake.ts
[supplier-rpc]: https://github.com/nicobailon/pi-subagents/blob/7d072b91dca7e1aa915282f0159cec0175d65efa/src/extension/rpc.ts
[memo1]: upcoming-pi-changes-memo.md
[memo2]: upcoming-pi-changes-memo-v2.md
[v3]: upcoming-pi-changes-memo-v3.md
[pi-sep21]: pi-assessment-2026-09-21.md
[pi-sep29]: pi-assessment-2026-09-29.md
[sessions]: pi-session-management.md
[deep]: deep-opportunities-pi-integration.md
[updates]: perk-updates-for-pinning-pi-1.md
[recommendations]: perk-recommendations-for-pinning-pi-1.md
[subagents-improvements]: pi-subagents-improvements.md
[subagents-sep05]: pi-subagents-assessment-2026-09-05.md
[subagents-sep21]: pi-subagents-assessment-2026-09-21.md
[subagents-audit]: pi-subagents-release-audit.md
[rpc-fix]: pi-subagents-rpc-fix.md
[packages-audit]: new-package-release-audit.md
[browser-sep05]: plannotator-assessment-2026-09-05.md
[browser-sep21]: plannotator-assessment-2026-09-21.md
[commands]: command-interface-and-structured-output-opportunities.md
[headless]: deepen-headless-execution/memo.md
[session-driving]: deepen-headless-execution/pi-session-driving.md
[reverify]: ../developers/pi-subagents-reverify.md
[characterization]: ../design/archive/pi-1.0.0-characterization.md
[characterization-1.1.0]: ../design/archive/pi-1.1.0-characterization.md
[certification]: ../design/archive/pi-1.0.0-certification.md
[mcp-restoration]: ../design/archive/pi-1.0.0-mcp-restoration.md
