# Perk updates before adopting a Pi 1.0.0 floor

Assessment date: **2026-10-03**. Status: proposed maintainer roadmap. This document
does not change dependency pins or claim that Perk has been certified on Pi 1.0.0.

## Recommendation and scope

Make this a coordinated modernization, followed by the floor bump. Repair the
supplier incompatibility first, finish Perk's adoption of native tool composition
and discovery across its execution paths, and simplify the integration where a
public Pi interface actually removes work. Publish **Pi 1.0.0 as an enforced
minimum** only after the resulting implementation passes on exactly that release.

The important immediate finding is that upgrading Pi alone is insufficient:
Perk's pinned **pi-subagents 0.73.1** requires an agent-core export removed in 1.0.
Moving to **pi-subagents 0.75.0** fixes that supplier dependency, but also requires
Perk to migrate its report-wave RPC payload from `workflowScript` to `script`.

The decisions governing this roadmap are:

- Finish the selected compatibility, simplification, and native-capability work
  before announcing the new floor; this is more than a dependency-only release.
- Refuse unsupported hosts at both the Python launch boundary and the TypeScript
  runtime boundary. Keep diagnostic and repair commands usable.
- Support native discovery, codemode, and MCP in interactive sessions, SDK workers,
  and restricted planning/report sessions, with explicit capability differences.
  Availability does not mean silently enabling every feature or server.
- Compare the existing suppliers with smaller supplier APIs and ordinary Pi SDK
  implementations. Require a demonstrated reduction in ownership before replacing
  a working supplier.
- Defer **pi-durable**, the removed experimental harness, detached-host migration,
  and a new objective conductor. None is a prerequisite for this upgrade.

The two-plane architecture remains the organizing contract: Python owns launch,
convergence, worktrees, and durable workflow operations; TypeScript owns session
behavior. Shared facts belong in `shared/`, consumed directly by both planes.
Pi owns agent execution and session projection. Perk still owns what constitutes
a reviewed plan, an authorized operation, and a completed workflow stage.

## Evidence and snapshots

| Subject | Inspected state |
| --- | --- |
| Perk | 3.9.0 at `2d8d635a47aaa6abe44064e26e9fcdcad12dc0ed`; clean checkout at assessment start |
| Development SDK and CLI | All six Pi development pins are 0.99.2; the installed `pi --version` also reports 0.99.2. These are separate installation surfaces. |
| Target Pi release | [v1.0.0][pi-release], published October 1, 2026 at 19:20:55 UTC; commit `a13d35a742c6ef8462812a28fbe1d8c8b7431c32` |
| Pi source mirror | `docs/library/source-code/github.com/earendil-works/pi`, HEAD `a276dabe57911253350bffb93cb7d7aff6a73261`; newer than the release |
| Pi documentation mirror | `docs/library/documentation/pi`, from `https://pi.dev/docs/latest`; the library check returned **unverifiable**, which is not evidence of staleness. Release-tag source controls release claims. |
| Installed suppliers | pi-subagents 0.73.1, pi-web-access 0.33.0, `@plannotator/pi-extension` 0.27.21 |
| Proposed subagent baseline | [v0.75.0][subagents-release], published October 2, 2026 at 20:28:54 UTC; commit `ad56bf92fe01a2a5abd962938c619eb2a22ca47d` |
| Historical subagent mirror | The library's pi-subagents mirror is 0.71.0. It is neither the installed baseline nor the proposed target; supplier conclusions use installed 0.73.1 and tagged 0.74/0.75 source. |

Evidence is **source-supported** unless identified otherwise. One read-only
resolver probe confirmed that 0.73.1's required `pi-agent-core/node` alias does not
resolve against the target export shape. It was not a complete child launch on a
published 1.0.0 host. The [0.99.2 certification][baseline-record] and
[discovery dogfood][discovery-evidence] are useful regression baselines, not 1.0.0
certification. All runtime acceptance below is work still to do.

Do not attribute later mirror changes to the floor. In particular, project MCP
overrides without a repeated command/URL, later OAuth changes, additional codemode
output caps, and removal of the published shrinkwrap belong to later source.
Tests against main or a later patch cannot establish a 1.0.0 minimum.

## Reconcile the earlier plans with current Perk

| Earlier work | Current disposition | Remaining work here |
| --- | --- | --- |
| [September 29 Pi assessment][assessment-099]: protect terminal tools, preserve native selections, retain nested evidence | Landed through the tool catalog, model-only exposure, provenance policy, own-name reconciliation, and nested `/learn` evidence | Test the new supplier and 1.0 paths; close the late-MCP restoration and system-message gaps below. Do not redo the original three fixes. |
| [Native-discovery pilot][discovery-record] | **ADOPT**, with four deferred tools and live evidence; the subsequent default-convergence change is already landed | Preserve `+tool_search` convergence and opt-outs. Extend session coverage and measure any additional candidates. The pilot's original “init does not converge it” description is historical. |
| [September 21 assessment][assessment-087] and [session-management plan][session-plan] | Canonical projection, `/btw` seeding/public summary streaming, and native resume/naming already landed | Retain their semantics; investigate only the remaining private runtime seam. |
| [TypeScript decomposition][decomposition] and [future-proofing proposal][future-proofing] | Feature modules, typed operations, worker adapter, surfaces, and `ReportWave` already provide real boundaries | Deepen specific interfaces rather than reorganizing the tree again. |
| [Deep integration opportunities][deep-opportunities] | Browser lifecycle, effective-access results, prompt observability, supplier comparisons remain relevant | Include bounded implementations/comparisons in this release program. |
| [Headless execution planning][headless-plan] | Ordinary SDK stage execution is the current path | Make its resources and models match the supported capability matrix; preserve stage completion evidence and budgets. |
| [Subagent reverification][subagents-record] | The 0.73.1 pin deliberately avoided the 0.74 RPC break | Supersede that recommendation by adapting to the new API and certifying 0.75.0. Preserve the dated record. |
| [Upcoming Pi memo v3][pi-memo], v1, and v2 | Useful historical questions about host ownership; their harness direction is not a released 1.0 integration target | Carry forward only ordinary SDK questions. Defer durable/experimental-host work. |

## 1. Compatibility changes that must precede publication

### 1.1 Upgrade pi-subagents and migrate the report protocol together

Pi 1.0 [removes the experimental agent harness and its package subpaths][pi-agent-package],
including `@earendil-works/pi-agent-core/node`. Perk itself does not import that
subpath. The installed 0.73.1 supplier does: its background runner alias resolver
treats `./node` as required, and its npm-host spawn path refuses to proceed when
any required alias is missing. This establishes a concrete incompatibility for
**npm-host background children**, including Perk's asynchronous report workflows;
the supplier's binary-host path has different alias handling.

[0.75.0's resolver][subagents-aliases] makes that alias optional when the host no
longer exports it, while still rejecting an exported but missing target. Adopt
0.75.0 as the initial supplier pin, subject to full reverification. Do not patch
0.73.1's installed files or resurrect removed Pi exports.

The coordinated migration must cover:

| Change | Perk action and acceptance |
| --- | --- |
| 0.74 removed RPC `workflowScript` / `workflowScriptPath` | Send inline `script` through [the RPC adapter][rpc-adapter]. The [0.75 RPC handler][subagents-rpc] explicitly rejects the old key. Test the emitted request and an actual asynchronous wave. A private Perk variable can keep its name; the wire contract must change. |
| Model-facing workflow scripts use a different protocol | Keep Perk's code-owned RPC execution. Do not replace it with `workflow: true` or a fenced script in an assistant response; RPC explicitly rejects that form. |
| Workflow resource names reserve `chain` and `tasks` | Check generated identifiers. Current `renderWaveScript` uses `reports`, so there is no demonstrated collision to fix. |
| Child resource loading now follows project trust | Prove that required report restrictions and skills load before any child work in supported trust states. Refuse a child whose restrictions cannot load; do not globally approve project resources as a workaround. |
| Required child extensions can be required for every runner in 0.75 | Evaluate `requireForAllRunners: true` for the report restriction extension through a supported loading seam. Unsupported external runners must refuse, and restriction startup errors must prevent execution. |
| Supplier orchestration and `structured_output` are model-only | Verify they remain reachable as top-level child tools and unreachable from nested calls; retain Perk's own terminal/orchestration exposure rules. |
| Supplier native model, codemode, MCP, activation, and reload behavior changed | Exercise them through Perk, including extension-registered virtual models, exact MCP tool selectors, disabled workflow scripts, reload/resume, and cancellation. Preserve explicit tool/model/resource choices. |

Update [init's supplier pin][init-settings], doctor compatibility guidance, package
loading/parity fixtures, and the developer reverification procedure together.
Remove the old blanket “0.74+ incompatible” doctor conclusion only after the new
adapter is in place. A supplier's improved workflow recovery does not make Perk's
opaque wave references recoverable automatically: document and test Perk's own
cancel, collect, and reload semantics.

Preserve [report-child policy][child-policy]: caller checkout (`worktree: false`),
fresh context, the latched read-only floor, no parent scratch/authoring guidance,
and byte-exact task restoration across compaction until structured output is
accepted. Supplier upgrade tests must exercise these properties, not just N/N
successful reports.

### 1.2 Preserve late MCP selections during Perk reconciliation

Pi 1.0 retains selected tool names while MCP servers reconnect after resume/reload.
However, [its active-tool setter][pi-agent-session] clears the pending restoration
set whenever a call deactivates **any** currently active tool. Perk can remove one
of its own tools during startup, stage reconciliation, or discovery deferral.
Preserving all *currently visible* foreign names is therefore insufficient to
preserve foreign names that have not registered yet.

This is a source-supported interaction, not a reproduced full-host regression.
First add a real-runtime characterization: save an active deferred MCP tool,
delay its registration on reload, let Perk reconcile its own tools, then register
the server before the next prompt. Repeat with discovery on/off, stage changes,
read-only transitions, and no Perk changes. Pi itself clears pending restoration
when the next agent run starts; distinguish that documented window from Perk
clearing it prematurely.

Fix the smallest Perk-owned activation decision that causes a loss. Prefer initial
registration/default activation and native presentation mechanisms that avoid
unnecessary deactivation during restoration. `prepareLoadout` can hide declarations
but does not authorize calls or edit the pending set. Pi 1.0 exposes no public
owner-scoped pending-selection setter: do not invent one, read private fields, or
reimplement Pi's transcript replay. If the required behavior cannot be achieved
through 1.0's public interface, record the exact blocking case and resolve the
support decision before publication; a fix only on upstream main is not a floor fix.

### 1.3 Accept Pi system messages in learning evidence

[The Python JSONL parser][session-parser] already accepts arbitrary role strings,
but its message `content` shape accepts only an array of blocks. Pi's
[system messages][pi-ai-types] use string content and carry section/tool deltas.
An otherwise valid system-message entry can therefore become a malformed line,
losing its ID and breaking an active-branch ancestry walk. This gap was also
observed during the discovery work.

Accept the released union at the read boundary, preserve entry identity and parent
links, and retain bounded system content plus `sections`, `toolsAdded`, and
`toolsRemoved` evidence for normalization/rendering. Treat these as context/tool
evidence, never as user authorization or a workflow terminal event. Preserve
lenient parsing, malformed counts, and bounded nested-call records. This is an
extension of the existing format-3 grammar, not a speculative format-4 migration.

Acceptance: initial system snapshot, subsequent deltas, resume/tree/compaction,
mixed historical logs, malformed content, a system entry between two branch nodes,
and a parent tool result with incomplete or failed nested calls. Child failure
evidence must remain visible without rewriting a successful parent result as failed.

### 1.4 Audit smaller released changes without inventing breakage

| Pi 1.0 surface | Required response |
| --- | --- |
| Public exports | Typecheck against published 1.0.0 packages and run the bare-import/host-alias census. Ordinary `Agent`, session SDK, and consumed loader APIs remain; removed harness APIs do not justify rewriting the worker. |
| Node requirement | Align Perk's `>=22` declaration, prerequisite checks, and remote setup with Pi's actual **>=22.19.0** requirement. |
| `--provider` without `--model` now errors | Audit stage flags, forwarded arguments, and override precedence. Perk's ordinary model/thinking flags are not by themselves a known failure. Preserve Pi's explicit error rather than silently selecting a different model. |
| `quietStartup` now also accepts `"header"` | Preserve user settings and audit typed assumptions; no current Perk getter dependency was found. |
| Fullscreen is Pi's default | Stop seeding `tuiMode: "fullscreen"`; preserve existing explicit values, including values an older init may have seeded. |
| Codemode missing-member access throws | Update any authored examples/probes to use `"name" in tools` for optional membership. Do not assume `typeof tools.missing` is safe. |
| MCP OAuth and credential fixes | Inherit Pi's implementation and test the applicable server flows. Do not introduce Perk-owned OAuth/token storage. |
| TUI/theme changes | Exercise footer, status, reports, widgets, and `/btw` in fullscreen and regular modes, including light/dark/system themes and a headless run. Keep the existing surfaces charter. |

The target [coding-agent manifest][pi-package], [release changelog][pi-changelog],
and [SDK exports][pi-exports] are the source of truth. The source-only experimental
`./client` and `./experimental/plugin` paths are not a published replacement SDK.

## 2. Enforce the minimum at the right boundaries

Introduce one machine-readable compatibility declaration under `shared/` for
the Pi minimum and any cross-plane runtime requirement. Keep the development
test pins separate: **exact 1.0.0** is the initial tested SDK, while **>=1.0.0** is
the host admission rule. A later development pin must not silently raise the floor.

| Boundary | Required behavior |
| --- | --- |
| Python cold launch | In [the common exec seam][pi-exec], resolve the actual executable first, read its version through a bounded subprocess call, then refuse an older, prerelease-below-floor, or unverifiable host before session launch. Apply to plain, staged, and resumed sessions. Report executable, observed version, required version, and repair guidance. |
| Extension loaded directly by Pi | Check the loaded host SDK's public `VERSION` before workflow registration/operation, independently of PATH and any CLI stamp. Use a small bootstrap if necessary so newer imports do not fail before the useful refusal. No partial workflow tools on an unsupported host. |
| SDK worker | Validate the SDK actually loaded by the worker before resource loading or provider work. A passing PATH `pi --version` does not certify this runtime. Preserve the typed worker failure envelope. |
| Recovery commands | `perk init`, `perk doctor`, help, and upgrade/repair guidance remain available on an old installation. Doctor reports the same shared requirement; it is not the only enforcement point. |
| Remote launch/setup | Make the Pi install/test version explicit in managed workflow artifacts and [.github setup][remote-setup]. Test generated and materialized artifacts together. Avoid a floating `latest` install as proof of the minimum. |

Use version semantics rather than lexical string comparison. Cover 0.99.2,
1.0.0 prereleases, exact 1.0.0, a later compatible release, malformed output,
missing executable, timeout, and CLI/SDK skew. Keep startup checks cheap; do not
install packages or perform network lookups in an ordinary launch preflight.

Keep host libraries as wildcard peers, consistent with [Pi's package contract][pi-packages-doc].
Do not use restrictive npm peer ranges as the runtime gate: managed installs
suppress automatic peers, and normal npm resolution can otherwise introduce
another SDK copy. Preserve bare host imports and the shared-namespace invariant.

## 3. Simplify integrations with demonstrable replacements

| Existing obligation | Proposed change | What can actually be removed / proof needed |
| --- | --- | --- |
| Perk repeats Pi's fullscreen default | Delete `_converge_tui_mode` and its convergence call | Remove seed-specific tests/prose. Preserve user-owned settings and their exclusion from managed-state drift checks; do not erase historical values. |
| Six development Pi packages are maintained in lockstep | Remove unused `pi-client` and `pi-server` development dependencies after the import census | No production imports were found. Update `just`'s update command, packaging lockstep test, and lockfile to the packages actually consumed. Do not remove a transitive host dependency by assumption. |
| Mode changes return `void` | Return an effective-access outcome from [tool gating][tool-gating]: applied/restricted/failed, with the effective mode | Delete caller inference that `exit()` necessarily restored writes. Test restriction-floor refusal, persistence failure, tool-install failure, reload/navigation, and truthful notices. Outcomes are observations, not permission tokens for later async work. |
| Browser doors repeat asynchronous ownership | Consolidate the shared plan/objective review lifecycle above [the existing handoff][browser-handoff] and [draft-review slot][draft-review] | Delete duplicated readiness, late-decision, supersession, and cleanup choreography. Keep subject-specific reviewed-byte/destination checks, direct edits, and publication policy at the callers. |
| Prompt delivery is difficult to explain | Add bounded observation at existing Pi/Perk assembly boundaries | Compare actual outgoing context with the prose map; do not add a second projector or merge binding, scratch, and mode evidence rules merely to reduce files. |

The browser owner must handle early decisions, readiness timeout followed by late
approval, superseding opens, session replacement, abort, and idempotent cleanup.
A retiring operation cannot clear a successor's surfaces. Aborting Perk's wait is
not proof that Plannotator's server stopped; retain the distinction until a
supported supplier handle owns server cancellation.

Several tempting deletions **do not yet have a replacement**:

| Adaptation | Disposition and retirement condition |
| --- | --- |
| [Host SDK bridge][sdk-bridge] | Keep. The consumed extension loader is unchanged between 0.99.2 and 1.0; no native-import identity guarantee replaces the bridge. Delete only after published-host tests prove a single SDK/provider/schema namespace for every supported supplier, including lazy imports, reload, and bare-clone loading. |
| [`/btw` live runtime probe][btw] | Keep confined. `ModelRegistry.runtime` remains private in 1.0, and public image/classifier APIs do not supply a side-session factory sharing live auth overrides/providers. Retire only with a supported equivalent that preserves those semantics. Canonical seeding and public summary streaming are already done. |
| [Report RPC contextless/stale responder guards][rpc-adapter] | Keep until the original trust/discovery/reload duplicate-responder case passes without them. Fixes to Pi's separate `RpcClient` are not that proof. |
| Worker `finishTurn` budget wrapper | Keep unless an actionable public lifecycle hook proves identical no-extra-request behavior, cancellation, persisted follow-up, and one terminal outcome. Idle/settled remains insufficient evidence of stage success. |
| Canonical projection plus Perk delivery predicates | Keep. Pi projects edited context; Perk identifies whether its exact guidance/task evidence was delivered. These are different responsibilities. |

## 4. Adopt native capabilities across the supported session types

### 4.1 Make the capability matrix an executable contract

The CLI loads native built-ins; the ordinary SDK does not automatically reproduce
that setup. Use the public `createToolSearchExtension`, `createCodemodeExtension`,
and `createMcpExtension` factories through `createAgentSessionServices` resource
loader options. Preserve builtin identity/disable semantics. Do not import CLI
internals or rely on a globally installed extension accidentally filling the gap.

| Session | Discovery and composition target | Resource/auth boundary |
| --- | --- | --- |
| Interactive plain and read-write stage session | Native discovery, codemode `on`/`only`, and configured MCP work; Perk's stage presentation and terminal tools remain coherent | Pi's ordinary trusted resources, user choices, and server configuration; Perk retains explicit discovery opt-outs |
| SDK stage worker | Same eligible native capabilities when configured; explicit factories and deterministic setup | Preserve the worker's isolated agent directory and intended project resources. Do not import all global extensions/settings to obtain parity. Headless auth must succeed or return an actionable refusal. |
| Read-only planning/refinement session | Discovery plus useful restricted composition; MCP only under an explicit trusted read policy | Latched access restrictions, bounded writer carve-outs only through their existing direct workflow paths, nested checks on every call |
| Report/reviewer/scout child | Native reads/discovery/composition selected for the agent's task; structured output remains top-level | Required restriction delivery, fresh context, no authoring scratch, required skills, exact permitted servers/tools; a rejected restriction extension prevents launch |
| `/btw` side session | Make applicable native read/discovery capability explicit rather than silently copying the parent loadout | Preserve its intentionally small tool set and isolated context. No parent workflow tools or wholesale parent extension loading; model/auth sharing must retain current semantics. |

Honor `defaultTools`, explicit additions/removals, builtin disabling, codemode mode,
MCP selections, and model overrides. Existing `+tool_search` convergence already
preserves explicit positive/negative/plain entries and deliberately empty or
malformed lists. Keep that ownership rule. Enabling codemode and adding MCP servers
remain configuration choices; capability support does not authorize new network
resources or create credentials.

### 4.2 Finish the restricted composition path

Today [the policy catalog][tool-policy] blocks and suspends codemode under the
read-only gate. This is deliberate: hiding its declaration leaves it active, and
`only` can then hide the remaining direct reads. The sole Perk `query`,
`objective_stack_status`, is itself gate-blocked. The existing contract therefore
records a future restricted composition rule but implements no such path.

Implement that rule as a separate policy change, with a useful read case first:
make `objective_stack_status` eligible in the read-only stages where its existing
plan/objective preconditions hold, and test planning in a worktree plus a report
child's repository reads. Do not introduce a redundant collection of Perk wrappers
around native filesystem tools merely to populate the catalog.

For calls carrying Pi's public `parentToolCallId`, enforce the restricted subset:
eligible Perk **queries**, allowed builtin reads (including the existing bash
verdict), and foreign tools explicitly allowed by provenance/policy. A direct
read-only carve-out is not a nested write grant. `readOnlyHint` is metadata, never
authorization. Unknown MCP tools remain denied until an explicit server/tool
policy grants them; define and validate that policy at the existing configuration
boundary rather than using a foreign tool's self-description as trust.

Use Pi's actual nested execution hooks for enforcement. `hiddenDeclarations`
changes presentation only, and deactivating a `deferred` tool does not make it
uncallable. A script may still discover a denied tool's schema in 1.0; its call must
fail before effects. Do not claim that 1.0 supplies a public filtered-callable-set
API. Verify usability as well as denial in both `on` and `only`; remove the current
suspend/restore workaround only when the restricted path succeeds in both modes.

Treat `models.*` separately: classifier/image calls inside codemode do not become
ordinary nested tool calls. Define their availability and budget treatment
explicitly. SDK-created restricted factories can use `models: false` until that
accounting is available; do not pretend the tool-call hook controls this namespace
in the CLI builtin. Complete this policy decision before claiming session parity.

Terminal, interactive, and orchestration Perk tools remain model-only. Keep
`registerPerkTool` as the one metadata/result boundary: queries return schema-backed
values, actions preserve their existing text/error contract, and soft failure
must not turn into a successful script value. Broaden the deferred family only
for tools with a demonstrated declaration cost, discoverable query, valid primer,
and successful direct/nested semantics. Keep workflow entry/exit tools reachable.

Measure the new matrix against the [adopted pilot][discovery-record]: request bytes,
fixed overhead, search success, and zero dead-end workflow turns. Retain an
always-declared path for users who opt out. Do not simply defer every tool.

### 4.3 Let native model registration precede model selection

[The worker adapter][worker-adapter] currently resolves models/auth before project
extension resources have registered native providers and virtual models. A test
that seeds a provider directly into `ModelRuntime` does not prove extension-loaded
model support. Pi's [services factory][pi-services] already applies pending provider,
native-provider, and virtual-model registrations and refreshes the runtime.

Reorder worker preparation around that public lifecycle: build the allowed
resources/services, register providers, then resolve the configured/default model
and authenticate it, then construct and bind the session. Preserve explicit stage
model and thinking overrides. Do not report “no models” before the authorized
extensions have had the opportunity to register them. Test real extension-backed
registration, saved credentials, explicit selection, default selection, unavailable
auth, and a virtual model whose physical target differs from its public identity.

Support routing without making Perk the router. A configured virtual/native model
is an opt-in Pi capability, not a reason to add a second role-routing configuration
language. Display selected and actual physical model information where useful,
through [surfaces][surfaces], without expanding the one-line footer into a second
control plane or using undocumented runtime fields.

Extend worker accounting before enabling model-using tools there. The current
adapter counts assistant `input + output`; it misses tool-model usage. Consume
Pi's usage records once at the appropriate aggregate boundary, including failures
that incurred usage, and avoid counting both nested and parent aggregates or
adding reasoning tokens already included in output. Keep fresh-token budgets,
cache counters, and monetary/image usage distinct; define how non-token work is
bounded rather than manufacturing a token equivalent. Preserve current worker
retry/compaction choices and no-extra-request turn caps.

### 4.4 Feature fit beyond tool activation

| Native feature | Decision for this program |
| --- | --- |
| MCP namespaces, discovery, structured results, and OAuth | Adopt through Pi's native implementation, with explicit resource policy and late-registration tests. This is a way to add capabilities without adding a Perk-specific wrapper for each service. |
| Classifier models | Support their native API and usage/error records. Run a bounded comparison for an existing triage/classification task against current deterministic/LLM behavior; require quality evidence before replacing workflow judgment. No classifier may decide authorization or terminal success. |
| Image generation | Preserve configured native availability in suitable read-write sessions and account for it. It does not justify a new Perk workflow tool or a release-blocking product feature; restricted/headless support follows the explicit model-call policy above. |
| Cache warming and context budgets | Inherit Pi's behavior and observe request/context/cost effects. Keep Perk's workflow budget separate; do not build another cache manager or copy a private statistics helper. |
| System-message and tool-loadout evidence | Use the parser repair plus bounded outgoing-request observation to explain guidance, discovery, model selection, and context pressure. Preserve canonical projection and owned delivery evidence. |
| Session lifecycle/RPC improvements | Adopt public cancellation/disposal/settlement behavior where it deletes a proven obligation. Keep typed workflow completion and the distinction between Pi RPC and pi-subagents' event-bus RPC. |
| TUI and appearance | Use native defaults and capabilities through Perk's surfaces module. Retain headless no-ops/status delivery and the `/btw`-only custom-UI exception. |

Pi 1.0's [codemode documentation][pi-codemode-doc] specifies native model calls,
usage, errors, and output behavior. Classifier/image `stopReason` and `errorMessage`
must be inspected; a fulfilled call is not necessarily a successful model result.

## 5. Compare suppliers at the existing interfaces

Make the comparison a bounded deliverable before the floor release. A recorded
decision to keep the upgraded supplier is a valid outcome. Select a replacement
only when the comparison establishes a concrete benefit.

### Report execution

Keep [ReportWave's][report-wave] assignments, opaque references, `start/collect/run`,
completeness, deadline partials, and drain-once semantics. Compare below that public
surface, above the private script-shaped transport.

| Candidate | Obligations potentially removed | Obligations retained or acquired |
| --- | --- | --- |
| Updated 0.75 RPC workflow adapter | Only the obsolete payload/compatibility handling; smallest change | Generated script, event correlation, aggregate file reads, stale responders, cancellation/timeout grace |
| Supplier structured delegation | Potentially script generation and workflow aggregate-file transport | Per-lane scheduling, batch settlement, wake/correlation, required extensions, supported package loading; prove caller cwd, no extra worktree, restrictions, and required skills |
| Ordinary Pi SDK report executor | Potentially report-specific supplier orchestration and RPC | Agent/resource loading, auth/provider registration, isolation, concurrency, cancellation/quiescence, schema validation, compaction/task retention, packaging, supervision, and completion wake |

Reuse the lessons from [foreground delegation][foreground-delegation]; a successful
single writer does not establish safe concurrent restricted reports. First reject
candidates that cannot satisfy resource, restriction, or packaging requirements
through supported APIs. Test the viable candidates with the same prepared
assignments: successful siblings plus a failure,
deadline partials, queued/running cancellation, late and duplicate completion,
unknown/duplicate report identities, reload, and repeated collection.

An SDK implementation must not mutate process-global child flags to simulate
per-session policy. Choose explicit session inputs or isolated processes and count
the resulting supervision/resource costs. Preserve the bare-clone packaging rule;
a public supplier subpath still needs a supported loading mechanism.

Choose a replacement only if it passes the shared behavior suite and removes
specific caller/maintenance obligations without duplicating an execution platform.
Record the files/protocol states deleted and the new owner responsibilities.
If neither alternative wins, retain the upgraded RPC adapter and its guards.
Report-transport replacement alone would not remove pi-subagents from Perk;
foreground delegation has other callers.

### Browser review and web access

The browser lifecycle consolidation is required local work regardless of supplier
choice. A plain Pi SDK does not supply Plannotator's browser review, byte/destination
correlation, or annotations API. Compare replacement only against those actual
capabilities, not against the ability to open a URL. Keep the supplier unless a
supported interface removes more lifecycle work than Perk would acquire.

Likewise, native MCP is a transport/integration capability, not automatically a
replacement for pi-web-access's search, extraction, source handling, and result
contract. A configured MCP alternative can be evaluated through the same policy
boundary. Keep the current provider while the comparison lacks equivalent service
behavior. Do not couple this release to purchasing or selecting a new web service.

## 6. Work packages and release order

“Required” means completed before advertising the floor. “Decision required” means
the bounded comparison and disposition must be recorded; a speculative replacement
is not mandatory. Development may use isolated exact-1.0 test installations before
the production compatibility claim changes.

| Order | Work package and principal seams | Dependency | Exit evidence / pre-pin status |
| --- | --- | --- | --- |
| 1 | Exact-release characterization: published packages, removed exports, supplier aliases, delayed MCP, parser fixtures | None | Reproducible 1.0.0 fixtures and an explicit pass/fail ledger; **required** |
| 2 | Supplier migration: `rpcAdapter`, `transport`, `reportWave`, init/doctor, child policy | 1 | 0.75.0 waves plus restriction, trust, schema, cancellation, and reload tests; obsolete payload and doctor ceiling removed; **required** |
| 3 | Access/discovery policy: effective transition results, delayed MCP preservation, restricted nested subset, explicit MCP grants | 1–2 | Real-runtime direct/nested/late-registration matrix; truthful access notices; justified removal of codemode suspension; **required** |
| 4 | Evidence grammar and observation: Python learning parser/normalizer/rendering, existing context seams | 1; integrate with 3 | Valid system entries preserve ancestry; bounded deltas/nested failures survive; actual request evidence distinguishes projection from delivery; **required** |
| 5 | SDK/session capabilities: worker resource factories, registration-before-resolution, child selections, bounded `/btw` integration, usage accounting | 2–4 | Session matrix passes with opt-outs, isolated resources/auth, actual model evidence, no double counting, and existing stage completion/budget guarantees; **required** |
| 6 | Browser operation owner: plan/objective doors, draft-review slot, provider handoff | 2; can proceed alongside 3–5 | Duplicated async protocol deleted; readiness/late decision/replacement/cleanup tests and one real review flow pass; **required** |
| 7 | Supplier/SDK and classifier comparisons | 2–5; browser evidence from 6 | Bounded evidence record with adopt/keep decisions and ownership inventory; implement any selected replacement before final certification; **decision required** |
| 8 | Packaging and minimum enforcement: shared requirement, Python exec, extension bootstrap, worker startup, Node/setup | 1; finalize after 2–7 | Old hosts refuse coherently, repair remains usable, unused dev pins/fullscreen seed removed, current host imports retain one identity; **required** |
| 9 | Final certification and publication | 1–8 | Full acceptance matrix below, exact remaining dev pins and lockfile at 1.0.0, requirements/support docs and managed artifacts converged; **required, last** |

Each implementation phase must be driven by Perk before the next phase starts.
Express automatable dogfood preconditions as ordinary `pytest`/`node:test` cases.
Keep the old-host path only as a negative admission test once the floor is enforced;
do not retain parallel old/new runtime adapters as a permanent support policy.

Cross-plane behavior changes update [shared/contracts.md][contracts] in the same
implementation turn: especially worker execution (§8.11), learning evidence
(§8.35), tools (§8.40), launch/resume (§8.71–72), and host identity (§8.73).
Update [user requirements][requirements] and the relevant user-docs quadrant with
behavior changes; configuration/provider changes also update
[perk-expert's reference][expert-config]. New desired settings go through init's
forward convergence; legacy repairs belong in doctor. Record live/spike evidence
under `docs/design/archive/`; do not rewrite historical PASS records or author
new learned-corpus entries outside `/learn`.

## 7. Acceptance and the final floor decision

| Area | Required evidence on the proposed implementation |
| --- | --- |
| Published minimum | Typecheck, host imports, dependency census, and runtime tests use **published Pi 1.0.0**. Record resolved executable/SDK/supplier versions and paths. Test a later supported release separately if available. |
| Installation and refusal | Bare-clone and installed-package loading; fresh and existing init; doctor/repair; old and malformed host versions; SDK/PATH skew; minimum Node; managed local/remote setup |
| Session lifecycle | Plain/staged/resumed launch, `/reload`, `/tree`, fork, compaction/context edits, restriction-floor persistence, and current session naming/linkage |
| Native tools | Discovery enabled/disabled, foreign namesake, direct/deferred/model-only exposure, codemode `on`/`only`, direct and nested denial, cancellation, and stage transitions without losing operator selections |
| MCP | Delayed registration/restoration, disconnect/reconnect, exact tool selection, trusted and untrusted resources, explicit read grants, denied unknown/mutating tools, configured OAuth flows, and headless credential refusal |
| Worker and models | Project extension registers provider/virtual model before selection; explicit/default models and credentials; terminal success, error, external abort, turn/token caps, model-tool usage counted once, isolated resources, no extra request after cap |
| Children and waves | Fresh restricted children, required-extension failure, no scratch/authoring leakage, task restoration through compaction, top-level structured output, N/N and partial reports, duplicate/late events, timeout/cancellation, repeated collection |
| Learning evidence | Historical and new logs, system snapshots/deltas and ancestry, nested success/failure/incompleteness, malformed input and caps, rendered evidence without fabricated child result bodies |
| Human surfaces | Plan/objective browser review with wave annotations and a correlated decision; supersession/late approval; `/btw` context/auth/summary; fullscreen and regular TUI with readable surfaces; headless behavior |
| Adoption value | Discovery request-cost measurements and no dead ends; browser duplication actually deleted; supplier decisions list obligations removed/acquired; no claimed simplification based solely on fewer lines |

Use narrow tests while implementing, then the repository's normal final gate. In a
Perk implementation session that is one run-all `run_ci` immediately before
submission, with its green report definitive. Prose-governance checks remain the
documented opt-in suite when their corpus is changed. Live provider/browser/TUI
evidence complements CI; neither replaces the other.

Publish the floor only when required rows pass or their scope is explicitly
revised before release. A failed exact-1.0 case cannot be papered over by testing
only a newer host. The final release record must separate supported behavior,
configuration opt-outs, deliberately retained adaptations, and deferred work.
Pi-durable remains outside that decision.

## Source guide

Local links below identify the current owners. Upstream implementation links are
fixed to the inspected release commits so later `latest` documentation does not
silently change the meaning of this plan.

[pi-release]: https://github.com/earendil-works/pi/releases/tag/v1.0.0
[pi-changelog]: https://github.com/earendil-works/pi/blob/a13d35a742c6ef8462812a28fbe1d8c8b7431c32/packages/coding-agent/CHANGELOG.md
[pi-package]: https://github.com/earendil-works/pi/blob/a13d35a742c6ef8462812a28fbe1d8c8b7431c32/packages/coding-agent/package.json
[pi-agent-package]: https://github.com/earendil-works/pi/blob/a13d35a742c6ef8462812a28fbe1d8c8b7431c32/packages/agent/package.json
[pi-exports]: https://github.com/earendil-works/pi/blob/a13d35a742c6ef8462812a28fbe1d8c8b7431c32/packages/coding-agent/src/index.ts
[pi-agent-session]: https://github.com/earendil-works/pi/blob/a13d35a742c6ef8462812a28fbe1d8c8b7431c32/packages/coding-agent/src/core/agent-session.ts
[pi-ai-types]: https://github.com/earendil-works/pi/blob/a13d35a742c6ef8462812a28fbe1d8c8b7431c32/packages/ai/src/types.ts
[pi-services]: https://github.com/earendil-works/pi/blob/a13d35a742c6ef8462812a28fbe1d8c8b7431c32/packages/coding-agent/src/core/agent-session-services.ts
[pi-packages-doc]: https://github.com/earendil-works/pi/blob/a13d35a742c6ef8462812a28fbe1d8c8b7431c32/packages/coding-agent/docs/packages.md
[pi-codemode-doc]: https://github.com/earendil-works/pi/blob/a13d35a742c6ef8462812a28fbe1d8c8b7431c32/packages/coding-agent/docs/codemode.md
[subagents-release]: https://github.com/nicobailon/pi-subagents/releases/tag/v0.75.0
[subagents-aliases]: https://github.com/nicobailon/pi-subagents/blob/ad56bf92fe01a2a5abd962938c619eb2a22ca47d/src/runs/background/runner-aliases.ts
[subagents-rpc]: https://github.com/nicobailon/pi-subagents/blob/ad56bf92fe01a2a5abd962938c619eb2a22ca47d/src/extension/rpc.ts
[baseline-record]: ../design/archive/pi-0.99.2-baseline-verification.md
[discovery-record]: ../design/native-discovery-pilot.md
[discovery-evidence]: ../design/archive/native-discovery-pilot-dogfood.md
[assessment-099]: pi-assessment-2026-09-29.md
[assessment-087]: pi-assessment-2026-09-21.md
[session-plan]: pi-session-management.md
[decomposition]: ts-decomposition/memo.md
[future-proofing]: future-proofing-decomposition.md
[deep-opportunities]: deep-opportunities-pi-integration.md
[headless-plan]: deepen-headless-execution/pi-session-driving.md
[subagents-record]: ../design/archive/pi-subagents-0.73.1-reverify.md
[pi-memo]: upcoming-pi-changes-memo-v3.md
[rpc-adapter]: ../../extension/waves/rpcAdapter.ts
[report-wave]: ../../extension/waves/reportWave.ts
[init-settings]: ../../src/perk/convergence/init/settings.py
[child-policy]: ../design/pi-subagents-child-execution-policy.md
[session-parser]: ../../src/perk/learn/session_jsonl.py
[pi-exec]: ../../src/perk/run/pi_exec.py
[remote-setup]: ../../.github/actions/perk-remote-setup/action.yml
[tool-gating]: ../../extension/substrate/toolGating.ts
[tool-policy]: ../../extension/substrate/toolPolicy.ts
[browser-handoff]: ../../extension/pi/v1/providers/plannotatorHandoff.ts
[draft-review]: ../../extension/pi/v1/draftReview.ts
[sdk-bridge]: ../../extension/substrate/nativeSdkBridge.ts
[btw]: ../../extension/vendor/btw/btw.ts
[worker-adapter]: ../../extension/worker/sdkAdapter.ts
[surfaces]: ../../extension/surfaces/surfaces.ts
[foreground-delegation]: ../../extension/pi/v1/foregroundDelegation.ts
[contracts]: ../../shared/contracts.md
[requirements]: ../user-docs/reference/requirements-and-compatibility.md
[expert-config]: ../../skills/perk-expert/references/configuration.md
