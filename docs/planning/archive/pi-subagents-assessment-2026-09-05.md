# Memo: Perk’s pi-subagents integration after the native-session transition

Date: September 5, 2026

Audience: Perk maintainers

Status: Assessment and ranked recommendations; documentation only

Snapshot: Perk `33bf36964a5b407415eb1d01c1e962f77280169e`; installed pi-subagents v0.65.1

## Executive recommendation

Keep Perk’s `ReportWave` module and strengthen the integration beneath it. Perk has already
implemented much of the [August 6 recommendation](./pi-subagents-improvements.md): code-owned
launches, stable assignment keys, engine-validated reports, explicit completeness policies,
and a confined production/test adapter seam. Dream analysis already composes analysis and
reduction phases. The next architectural step is not another generic orchestration wrapper.

The immediate problem is compatibility drift. The current engine removed the wait-tool name
still prescribed by Perk’s streaming-review guidance. Perk’s streaming reviewer definitions
omit the supervisor tool they are instructed to use. Native child sessions changed extension
loading and environment assumptions; a subsequent patch changed what happens when child
execution mode is omitted. The existing adapter tests pass, but simulate upstream responses
and cannot establish that the installed engine still fulfills those assumptions.

Prioritize three groups:

- **Repair now:** establish a tested dependency/runtime baseline; repair streaming coordination;
  make child mode and required capabilities explicit; audit native-session gating and identity.
- **Improve next:** move conflict dispatch into code; share lifecycle and agent-policy mechanics;
  recover useful partial reports; add bounded usage and concurrency observability.
- **Experiment later:** bounded adaptive exploration/review, isolated implementation children,
  selective watchdog review, and external advisory runners. Assess unreleased named-workflow
  registration separately from capabilities available today.

Preserve authority: the Python CLI owns durable worktrees and the session exterior; the
extension owns in-session workflow state; parents reconcile reports and control publication,
except for the explicitly authorized submit-conflict resolver. Upstream scheduling, worktree,
host-command, and mission features do not automatically inherit those responsibilities.

## Scope and evidence

The review window is August 22–September 5, 2026, using UTC release publication dates. It
contains **12 releases, v0.55.0 through v0.65.1**, with v0.54.0 as the preceding baseline.
The release ledger below covers every release; the five themes in section 4 rank relevance
to Perk rather than reproducing every fix. Release metadata, all twelve changelog sections,
relevant tagged implementations/tests, and Perk callers were examined. This is not a claim
to have reviewed every changed line in the upstream comparison.

The installed package was v0.65.1; representative installed source blobs matched the GitHub
tag. Perk’s Pi development dependencies were v0.84.1. The separate local upstream checkout
was stale and was not used as evidence of current behavior. GitHub access used `gh`.
Post-release `main` was `063a5ad78a8f92ba46ed5c9cb37f50b07cc76514`, thirteen commits beyond
v0.65.1. Its workflow-registration addition is an explicitly unreleased preview, not a
reason to write production code against an unshipped interface.

“Confirmed” below means supported by source or the recorded probes. “Needs live verification”
means the complete Perk/Pi/pi-subagents lifecycle was not exercised. Upstream benchmark and
test claims are not Perk measurements.

## 1. How we use pi-subagents today

### The report-wave path

Most delegation is code-owned. Flow modules supply judgment-bearing tasks, agent names,
schemas, and completeness policy to
[`ReportWave`](../../extension/waves/reportWave.ts). Its small `start`/`collect`/`run`
interface hides script generation, preflight, transport, settlement, and normalization:

```text
Flow: assignments + schemas + policy
  → ReportWave: preflight, stable keys, safely serialized runs.all script
  → RPC adapter: capability ping, subscribe, spawn workflow
  → pi-subagents: execute children, capture structured_output, settle workflow
  → completion event → status.json.workflow.value
  → ReportWave: typed reports + failures + completeness
  → parent: reconcile, display, decide, and perform authorized actions
```

The [transport](../../extension/waves/transport.ts) launches one workflow with root
`async: true`, `mission: false`, `context: "fresh"`, an output schema, optional configured
model, and a default fifteen-minute timeout. It subscribes before spawning, buffers early
completion, correlates the run, and attempts a stop on timeout or cancellation. Each child
receives a stable key and trace labels; the generated script returns only key, success,
error, and structured report. Task strings are embedded with `JSON.stringify`, not executable
interpolation. Required Ponytail assignments have exact-source skill preflight.

The [RPC adapter](../../extension/waves/rpcAdapter.ts) uses the installed extension’s v1 event
bus, not a bare `pi-subagents` package import. It negotiates the completion-event name and
reads the final aggregate from `status.json.workflow.value`. Output-free receipts retain run
and child identities and artifact paths; their absence does not change review judgments.
`collect` drains an opaque, instance-owned reference once. Pending collection is process-local,
not a durable Perk resume interface.

Crucially, **root workflow async mode and child async mode are separate decisions**. Perk’s
renderer does not set child `async`. In v0.65.1 that omission respects agent/global defaults;
the engine’s global default is background execution. The inspected installation also used
that default. An async workflow is not evidence that its orchestrator survives parent-process
loss, and a root `async: false` does not force its children into foreground mode.

### Workflow families

Automated PR review uses strict coverage and one bounded retry policy. Classification and
objective exploration use single-child strict waves. Learn, harvest, and the developer-only
audit use best-effort collection. Dream runs strict analysts, validates and bounds their
bundle in parent code, then runs three strict reducers. Streaming PR and draft review split
launch from collection while the parent relays provisional findings into hunk or plannotator;
final structured reports remain authoritative. Appendix A maps these flows to source.

Conflict resolution is the exception to the shared report path. The
[submit prompt](../../prompts/stages/conflict-resolution.md) and
[stack-continuation prompt](../../prompts/stages/conflict-resolution-continuation.md) ask the
parent model to write a one-child workflow and return text output. They prescribe root
`async: false` and a task beginning with `cd <worktree>`, rather than setting launch `cwd`.
Submit resolution may rebase, verify, and force-push the PR branch; retained stack resolution
must not push and requires human consent before parent-owned continuation. Parent code retains
attempt caps and canonical state checks.

### Agents and runtime policy

[`perk init`](../../src/perk/convergence/init/agents.py) delivers ten canonical Markdown
definitions from [`agents/`](../../agents/) into the owned `.pi/agents/perk/` directory,
byte-for-byte. Nine are report-oriented; `conflict-resolver` is a writer. Report definitions
replace the system prompt, disable project-context and ambient-skill inheritance, and allow
`read, grep, find, ls, bash`. Conflict resolution additionally allows editing/writing and
inherits project context. Frontmatter supplies model/fallback defaults; `[models.subagents]`
can supply the wave-level launch override. The generic assignment interface has no per-child
model override.

The repo’s [Pi settings](../../.pi/settings.json) borrow unpinned `npm:pi-subagents` and disable
its built-in agents. The development-only `perk-dev.session-auditor` is not one of the ten
shipped roles. The [direct Pi SDK stage executor](../../extension/worker/sdkAdapter.ts) is
separate from pi-subagents and should not inflate the delegation inventory.

## 2. What is good about our usage

**The shared module earns its depth.** Deleting `ReportWave` would redistribute preflight,
serialization, cancellation, correlation, schema handling, and failure semantics across many
callers. Its production adapter and test adapter make the seam real. The
[import-direction guard](../../extension/importDirectionGuard.test.ts) keeps transport details
inside the wave implementation; upstream changes can usually be handled locally.

**Fresh contexts isolate judgment.** Reviewers inspect evidence without inheriting the
implementation conversation’s conclusions. Tasks carry bounded inputs and distinguish
untrusted drafts/reports from instructions. The parent owns synthesis and human interaction;
children never receive UI handles. This is an appropriate use of subagents as context and
capability separation, not simply parallel execution.

**Completeness is a domain decision.** Strict review does not confuse a failed lane with a
clean verdict. Best-effort learning can preserve successful analyses while identifying skipped
angles. PR review’s bounded retry avoids retrying unavailable infrastructure or missing required
skills indefinitely. Stable keys survive completion-order differences and make missing coverage
explicit.

**Evidence and authority are separated.** Engine-validated structured reports carry judgments;
receipts carry correlation metadata; the parent decides what to publish or capture. Streaming
updates are provisional and final reports reconcile them. Exact-source Ponytail checks prevent
a same-named skill from silently satisfying a required review assignment.

These are already-built strengths, not recommendations to recreate. In particular, moving
review/learn orchestration out of prompts, adding structured classifier/explorer reports, and
building multi-stage dream analysis should be marked as progress since August.

## 3. What is limiting or inelegant

### Confirmed compatibility mismatches

1. **Streaming guidance names a removed tool.** Both
   [PR review](../../extension/pi/v1/codeReview/reviewWave.ts) and
   [draft review](../../extension/pi/v1/draftReviewWaveTools.ts) prescribe repeated
   `subagent_wait({timeoutMs: 30000})` calls. v0.61 removed that alias; the installed tool is
   `bg_wait`. The [tool census](../../extension/substrate/toolGating.ts) also retains old names
   and omits `bg_wait`. This affects read-only gating as well as instructions.
2. **Streaming agents lack their streaming tool.** The canonical
   [adversarial reviewer](../../agents/adversarial-reviewer.md) and
   [draft reviewer](../../agents/draft-reviewer.md) omit `contact_supervisor` from their tool
   allowlists. The installed native tool planner confirms it is absent. Upstream repaired its
   bundled reviewer/scout definitions, not Perk’s custom definitions. Perk explicitly tells
   children to skip streaming silently when unavailable, so successful final reports can mask
   the missing capability. See [upstream issue 1846](https://github.com/nicobailon/pi-subagents/issues/1846).
3. **Child execution mode is accidental policy.** Omitted child `async` was forced false
   through v0.65.0, then repaired in v0.65.1 to honor defaults. Perk can therefore change
   process, extension, provider, and tool behavior across a patch upgrade without changing its
   script. This is confirmed behavior, not a claim that all current children run foreground.
4. **Compatibility checks describe an older engine.**
   [Doctor](../../src/perk/convergence/doctor/checks.py) records v0.52.1 as its verified guidance
   version and probes old source strings, including the removed wait alias and `pi-args.ts`.
   Its warning-only source inspection does not prove current runtime behavior. With an unpinned
   dependency, installation currency and tested compatibility are different facts.

### Important risks and intentional tradeoffs

Native sessions removed the old environment-based child contract, while
[`agentScratch.ts`](../../extension/substrate/agentScratch.ts) still uses
`PI_SUBAGENT_CHILD_AGENT` to suppress scratch guidance for report-only children. The stale
dependency is confirmed; actual scratch behavior depends on which extensions and Perk state
the child receives and needs a live check. Likewise, claims that every child inherits Perk’s
read-only gate must be re-established separately for foreground and background launches.

A tool allowlist containing `bash` is not a read-only sandbox. Fresh context, read-only prose,
acceptance roles, and watchdog review do not prevent shell mutation. Native child permission
handling and Perk’s command guard must be tested together; merely removing `edit`/`write` is
insufficient. This matters more than whether a reviewer’s prompt sounds strict.
Perk also deliberately permits broader ad hoc delegation rather than installing stage-specific
agent/capability ceilings. Restricting that freedom would be a policy change, not a tool-name repair.

The [transport](../../extension/waves/transport.ts) only accepts terminal state `complete`.
Upstream partial settlement can preserve valid sibling evidence, but Perk currently turns that
into a wave-level failure without returning those reports. Its opaque refs cannot be recovered
after extension reload, and direct aggregate-file reads couple it to persisted shape. These
are deliberate simplifications with costs, not proof that ordinary successful collection fails.

Conflict dispatch leaves launch syntax, working-directory intent, and result interpretation
in model-authored prose despite having higher mutation stakes. Streaming flows also duplicate
relay instructions, while agent definitions duplicate capability conventions. Standardizing
those mechanics would help; forcing every flow into identical retry or completeness policy
would not.

## 4. The five largest, most relevant recent changes

### 4.1 Native sessions changed the integration substrate

In v0.65.0, native Pi `AgentSession`s replaced spawned Pi CLI children. Foreground children
run inside the parent process; background children run in a detached runner. Typed child
configuration replaced the old argv/environment/stdout launch protocol. Durable result and
status shapes were intentionally retained, which helps Perk’s RPC adapter, but does not preserve
every child-side assumption. See the [native-session change](https://github.com/nicobailon/pi-subagents/pull/1844)
and [tagged child launch](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/src/runs/shared/child-launch.ts).

Foreground children do not load ambient extensions; explicitly configured extensions and
internal hooks are distinct from ambient discovery. Background children can load ambient
extensions unless their launch policy disables them. Upstream directs MCP/provider-extension
users toward background execution; a runtime-only MCP registration in the parent is not itself
a transferable native child capability. Background execution requires the installed Pi npm
package, not only a standalone binary.

v0.65.1 then [repaired omitted child async defaults](https://github.com/nicobailon/pi-subagents/pull/1891)
while awaiting background completion inside the workflow. It also repaired provider registration,
package resolution, proxy handling, and parallel session-file isolation. Perk should select a
child mode based on required capabilities and verify it, not infer it from root mode or switch
modes automatically after failure. Upstream startup-performance claims justify measurement;
they are not measured Perk latency improvements.

### 4.2 Waiting, supervisor coordination, and settlement became more explicit

Across v0.55–v0.65.1, child-level stop/steer, retained-session recovery, supervisor coordination,
and terminal evidence improved. v0.58 began classifying workflow budget/deadline stops as partial
outcomes with settled child evidence. Subsequent fixes kept sequential workflows alive through
supervisor coordination and improved reload and stop behavior. These changes make targeted
recovery more plausible than relaunching every successful sibling.

The most immediate behavioral change is v0.61’s wait-alias removal. The
[current wait tool](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/src/runs/background/wait-tool.ts)
is designed primarily for work without native completion notification. Ordinary async children
already notify the parent; interactive guidance favors returning control, and headless runs
auto-drain current-session work at `agent_end`. Wait-window expiry is a non-error
`window_elapsed`, not a failed job.

Consequently, repairing Perk means more than replacing one string. Its deliberate same-turn
streaming relay must be tested against notifications, supervisor delivery, and final collection.
The existing subscribe-before-spawn code remains valuable. Supported
[RPC status/control](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/docs/extension-api.md)
and durable evidence merit evaluation, but do not imply that Perk already has restart-safe
workflow execution.

### 4.3 Workflow composition gained validation, sequential lanes, and limits

v0.57 added offline `action: "validate"` and `workflowScriptPath`; v0.59 added `runs.lanes`
and applied global concurrency limits to scripted `runs.run`/`runs.all`; v0.61 added per-workflow
concurrency and spawn-count overrides. See the
[tagged workflow guide](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/docs/workflows.md).

Validation checks syntax and structural mistakes such as invalid/duplicate literal keys,
nonportable async constructs, and result-shape misuse. It does not prove agent availability,
permission safety, or report quality. Perk’s representative generated script already passes;
making that a repeatable compatibility check is more useful than moving a short, safely
serialized script into a file merely because file loading exists.

`runs.lanes` expresses parallel lanes with sequential stages, retained continuation, and
lane-local blocking. It returns a bounded progress/result board rather than requiring complete
transcript aggregation. This can suit isolated implementation followed by review. Dream’s
parent-validated analysis bundle is already meaningful orchestration and should not be flattened
just to use the newer primitive. Concurrency limits, launch-count limits, usage budgets, and
deadlines solve different problems; a usage budget does not terminate already-running children.

`runs.host` adds timed host commands and saved evidence, but authority is constrained. In
v0.65.1, [named resources](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/src/workflows/workflow-resources.ts)
are package built-ins `review` and `run-ci`; the latter permits only `npm test` or
`npm run typecheck`. Raw inline/file scripts cannot manufacture host authority. This is not a
released replacement for Perk’s configured `run_ci` or an extension registration facility.

### 4.4 Agent integration became more configurable and package-friendly

v0.58 added **process-local event registration** of runtime agents through the installed
pi-subagents owner. This addresses independent extensions that cannot safely import a second
package instance; [issue 1533](https://github.com/nicobailon/pi-subagents/issues/1533) and the
[extension guide](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/docs/extension-api.md)
describe the seam. Registration is synchronous, disposable, and first-owner-wins. It is not
automatic propagation into every background process.

Other relevant changes compose with that option: v0.56 namespaced `extensionBindings`; v0.58
separate global-context opt-in; v0.59 explicit nested-subagent authorization; v0.60 structured
capability discovery; v0.62 `excludeTools`; and v0.63 extra scan directories and consistent
custom-agent overrides. Custom overrides replace matching frontmatter fields, rather than
implicitly merging list contents. See the
[agent guide](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/docs/agents.md) and
[configuration guide](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/docs/configuration.md).

For Perk, runtime registration could reduce copied artifacts, but current convergence provides
offline discovery, wheel packaging, and explicit ownership. Those benefits must survive any
migration. `inheritGlobalContext` now defaults off even when project context is inherited:
conflict resolution deserves an explicit decision; report roles already disable project
inheritance. Do not confuse fresh conversation history with absence of all repository or
operator instructions. Custom override parity shipped in v0.63, not v0.64.

### 4.5 Completion evidence became more compatible with report-only agents

v0.56 improved strict schema/acceptance compatibility. v0.62 let native children combine
acceptance evidence with their `structured_output` call using `acceptance.report: "on"`;
`"off"` retains fenced acceptance reporting. v0.63 stopped automatically injecting acceptance
reports into inferred reviewer/read-only children. See
[acceptance handling](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/src/runs/shared/acceptance.ts).

Perk currently sets `{level: "none", reason: ...}` for every report wave because competing
completion instructions previously interfered with its schema contract. The explicit disable
is still valid and documents intent; removing it is not an urgent modernization. A future
writer can adopt structured evidence without forcing every reviewer to produce a second report.

Acceptance, completion guards, and permissions are separate. `acceptanceRole` expresses intent,
not tool authorization. The [completion guard](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/src/runs/shared/completion-guard.ts)
can treat shell or unknown tools as mutation-capable; explicit report-role configuration should
be evaluated to avoid demanding changes from a successful read-only investigation. Neither
disabling that guard nor declaring a read-only role substitutes for command enforcement.
For Perk’s bash-enabled report agents, the concrete options to test are
`acceptanceRole: read-only` and `completionGuard: false`, alongside the existing explicit
acceptance disable. These are recommendations, not fields already present in the canonical roles.

## 5. Opportunities to make existing usage more idiomatic

The following recommendations are ordered. Cost is relative engineering scope, not an estimate
of calendar time. Every slice should preserve the `ReportWave` caller interface unless an
observable new capability genuinely requires it.

### R1 — Repair now: establish a tested compatibility baseline

Affected: every flow; evidence: section 3’s version/probe drift and section 4.1’s mode changes.
Prefer an exact tested dependency release initially, with a documented update procedure and
Pi compatibility matrix. Replace brittle source-substring assertions with behavior/capability
checks where supported, retaining version diagnostics. Add installed-engine script validation
and a small real lifecycle smoke beside fast adapter tests. Benefit: upgrades stop silently
changing execution assumptions. Cost: medium. Risk: a pin delays useful fixes or differs across
consumer installations. Dependency: init/package-resolution policy. First step: demonstrate the
review lifecycle on v0.65.1/Pi v0.84.1 and record the supported baseline before choosing a bump.

### R2 — Repair now: restore the streaming contract

Affected: terminal/browser PR review and draft review; evidence: the removed wait alias and
effective reviewer allowlists. Add supervisor capability deliberately to canonical definitions,
reconverge managed copies, update gating, and replace obsolete relay instructions with a tested
notification/wait lifecycle. Keep final reports authoritative and report unavailable streaming
clearly. Benefit: live findings become a supported behavior again. Cost: small-to-medium.
Risk: duplicate batches or premature collection during wake/settlement races. Dependencies:
R1 and chosen child mode. First step: one reviewer sends a provisional batch, settles, and is
collected exactly once on both UI paths; also test no-findings and unavailable-supervisor cases.

### R3 — Repair now: make child policy explicit under native sessions

Affected: all report roles and conflict resolution; evidence: sections 3 and 4.1. Define the
minimum execution/capability profile for each role family, including explicit child mode,
extension loading, context, supervisor needs, and real `cwd`. Keep background mode initially
where existing Perk/provider extensions are required; evaluate foreground only with proof that
required capabilities survive. Replace removed child-identity assumptions with a supported
mode-aware mechanism. Benefit: stable behavior and auditable authority. Cost: medium-to-large.
Risk: a superficially faster launch loses command guards or provider tools. Dependency: R1.
First step: a foreground/background matrix asserting tool availability, read-only command denial,
Perk identity/scratch behavior, context inheritance, and cancellation. Do not auto-fallback modes.

### R4 — Improve next: make conflict dispatch code-owned

Affected: submit and retained stack resolution; evidence: section 1’s prompt-authored exception.
Provide a domain-specific dispatch interface with explicit working directory and distinct
submit-versus-continuation authority. Return a structured outcome and evidence receipt; retain
canonical parent verification, attempt limits, and human continuation consent. Do not shoehorn
a writer into a report-only wave by weakening that module’s invariants. Benefit: higher-stakes
launches gain the same determinism as review. Cost: medium. Risk: accidentally granting push
authority in continuation mode or targeting the wrong worktree. Dependencies: R1/R3 and the
cross-plane worktree contract. First step: characterize both modes in tests, then replace only
script construction and outcome parsing, preserving the existing worktree owner.

### R5 — Improve next: retain partial evidence and recover collection

Affected: long waves, especially learning/dream and streamed review; evidence: complete-only
transport and process-local refs. Evaluate supported status/control interfaces behind the
existing adapter; add explicit incomplete outcomes containing independently validated successful
reports. A later bounded recovery interface should bind to original session/run/assignment
identity and prevent duplicate reconciliation. Benefit: less lost work and fewer repeated model
calls. Cost: medium-to-large. Risk: stale or incomplete evidence being presented as full coverage.
Dependency: R1 plus live settlement tests. First step: force one sibling to finish and another
to time out, then prove the first report is recoverable while strict completeness remains false.

Single-child classifier/explorer flows may eventually use the existing structured foreground
delegation interface internally. That interface predates this window; it is not a new release
feature. Defer a transport split unless measured latency/complexity improves and mode, packaging,
and cancellation requirements remain satisfied. One-child waves currently benefit from shared
policy, so “fewer workflow objects” alone is insufficient justification.

## 6. Opportunities to standardize our usage

### R6 — Improve next: share role and lifecycle conventions, not every policy

Affected: canonical agents, streaming flows, doctor, and wave callers; evidence: duplicated
definitions/instructions and the new configuration facilities in section 4.4. Establish one
reviewable convention for capabilities, context inheritance, execution mode, model precedence,
completion contract, and telemetry. Keep generation/validation behind existing seams instead of
creating a second user-facing configuration language. Factor shared streaming lifecycle mechanics
while keeping PR line anchors and draft phrase anchors domain-specific.

Preserve justified differences: strict versus best-effort completeness; PR-specific retry;
report-only versus conflict-writing authority; and human versus automated review verdicts.
Explicit launch models should retain precedence over agent defaults. Runtime registration and
extra scan directories are alternatives to evaluate, not simultaneous migrations to adopt.
Benefit: fewer drifting capability lists and copied instructions. Cost: medium. Risk: a universal
profile obscures real distinctions or breaks standalone agent discovery. Dependencies: R2/R3.
First step: test the ten delivered roles against a small capability/intent inventory and unify
the streaming lifecycle’s behavioral tests. Keep file delivery until another approach proves
equivalent packaging and reload behavior.

### R7 — Improve next: standardize bounded execution and useful telemetry

Affected: every wave; evidence: upstream concurrency, spawn budgets, structured capabilities,
and richer receipts. Centralize supported bounds and record chosen mode/model, elapsed time,
usage, retries, and artifact references without turning receipts into verdict inputs. Prefer
existing upstream evidence over duplicate status files. Benefit: cost and latency decisions
become measurable. Cost: medium. Risk: telemetry leaks report content or a global limit starves
mandatory review coverage. Dependencies: R1; use R5 for recovered evidence. First step: measure
ordinary PR-review and dream runs, then choose explicit concurrency/spawn limits from that data.
Do not equate deadline expiry with a retryable provider timeout.

Behavior-changing implementation slices must amend `shared/contracts.md` and user documentation
where required, plus matching expert references for configuration changes. This memo changes
none of those contracts and does not pre-author documentation for unbuilt behavior.

## 7. Opportunities to deepen or expand usage

### R8 — Experiment later: bounded adaptive exploration and review

Affected: broad objective exploration and complex PRs; evidence: existing typed waves and
workflow composition. Trial a fresh selector/explorer that chooses from a fixed allowlist and
bounded fan-out; preserve mandatory plan-fidelity and Ponytail coverage, operator directives,
and deterministic fallback. A second investigation should require a concrete unresolved question,
not an open-ended agent loop. Benefit: more relevant coverage on heterogeneous changes.
Cost: medium. Risk: selector latency, missed angles, or shared framing bias. Dependencies:
R1/R7 and baseline quality measures. First step: an offline comparison on representative PRs;
there is no current selector-driven implementation to “extend.” Build on dream’s existing
analysis/reduction pattern where appropriate.

### R9 — Experiment later: isolated writers with explicit handoff

Affected: a future bounded implementation task, not ordinary review or retained-conflict repair.
v0.63 added Worktrunk selection with native Git fallback; v0.65 added validated `baseRef` and
per-project worktree nesting; v0.65.1 preserves complete binary patches before cleanup. See
[worktree implementation](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/src/runs/shared/worktree.ts)
and [cleanup planning](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/src/runs/shared/worktree-cleanup-plan.ts).
These improve the basis for a child that implements one isolated task, then a reviewer examines
its handoff. They do not integrate competing patches or transfer publication authority.

Benefit: parallelizable implementation with independent review. Cost: large. Risk: dual worktree
ownership, dirty-source rejection, lost changes, and conflicting patches. Dependencies: R3/R7,
an explicit Python-owned lifecycle, and parent integration/CI policy. First step: one disposable
writer/reviewer lane from a clean pinned base, no publication, with validated patch retention
and failure cleanup. Keep actual PR conflict work in its existing canonical worktree.

### R10 — Experiment later: selective watchdog review

Affected: future writers or unusually long/high-risk investigations. v0.64 added launch role/model
rules, safe diff inspection, review cadence, `WATCHDOG.md`, and surfaced findings; see the
[watchdog guide](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/docs/watchdog.md).
Benefit: earlier detection of drift. Cost: medium plus model spend. Risk: repeated noisy reviews
or confusion with Perk’s human approval/CI authority. Dependencies: R3/R7 and a concrete failure
mode to detect. First step: advisory-only watchdog on the R9 experiment, measuring actionable
warnings and cost. Do not add watchdogs to every short report wave or treat them as a sandbox.

### R11 — Experiment later: external runners as a separate advisory contract

Affected: a new comparative review/research experiment. v0.57 packaged external CLI profiles for
Codex, Claude Code, and Cursor, with read-only/writing modes, bounded capture, and preflight;
see [agent execution options](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/docs/agents.md).
These run asynchronously and do not generally provide native `structured_output`, fork context,
tools, supervisor, or acceptance semantics. Benefit: alternative tooling and independent evidence.
Cost: medium-to-large. Risk: opaque output, different permissions, and extra authentication/runtime
requirements. Dependencies: separate capability and output validation plus R7 measurements.
First step: one read-only advisory result that cannot satisfy mandatory `ReportWave` coverage.
Do not substitute an external profile for a native reviewer and assume contract equivalence.

### R12 — Experiment later, unreleased: trusted workflow registration

[PR 1910](https://github.com/nicobailon/pi-subagents/pull/1910), merged after v0.65.1, adds
`registerWorkflowResource` through `pi-subagents/workflow-resources`. It binds names to the
actual SDK session ID, validates bounded arguments and synchronous expansion, captures exact
host key/command grants, rejects collisions, and provides identity-safe disposal. Disposal
blocks future lookup without revoking already admitted work. It does not add a runner,
publication authority, or a shell sandbox.

Affected: possible future Perk-owned named workflows combining child judgment and finite host
operations. Benefit: trusted composition without model-authored host authority. Cost: medium,
potentially larger if packaging changes. Risk: session/reload leakage, unsafe argument-to-shell
expansion, and duplicate package ownership. Dependencies: a release containing the feature,
R1/R3, and Perk’s [bare-import constraints](../../extension/bareImportGuard.test.ts). First step:
evaluate a no-model startup/reload/disposal smoke from the shipped extension layout after release.
The new package import is not equivalent to the already released runtime-agent event interface.
Perk’s `run_ci`, configured checks, durable state, and publication remain Perk-owned even if
this composition facility is eventually adopted.

## Appendix A — Current workflow inventory

All report rows use fresh-context structured reports and the shared transport. “Parent” names
the owner after collection; it does not mean every parent operation occurs automatically.

| Flow and source | Assignment/agent shape | Completion and retry | Parent responsibility |
|---|---|---|---|
| [Automated PR review](../../extension/waves/prReviewWave.ts) | 2–4 selected review angles, mandatory plan-fidelity, plus automatic Ponytail; `perk.pr-reviewer` | Strict; one bounded retry of eligible failures | Reconcile findings/verdict and post review |
| [PR review streaming](../../extension/waves/adversarialReviewWave.ts) | Selected adversarial angles plus Ponytail; `perk.adversarial-reviewer` | Split start/collect; provisional supervisor batches, final coverage | Relay to hunk/plannotator, human triage, publication |
| [Draft review streaming](../../extension/waves/draftReviewWave.ts) | Selected draft angles plus Ponytail and optional custom lens; `perk.draft-reviewer` | Split start/collect; final phrase-anchored reports | Browser relay, human triage, draft decisions |
| [Feedback classification](../../extension/waves/reviewClassifierWave.ts) | One `perk.review-classifier` | Strict; no flow retry | Fix, publish, and resolve through address workflow |
| [Objective exploration](../../extension/waves/objectiveExplorerWave.ts) | One optional `perk.objective-explorer` | Strict; no flow retry | Decide plan scope and author plan |
| [Learn](../../extension/learning/analystWave.ts) | Selected evidence angles; `perk.learn-analyst` | Best effort; explicit skipped angles | Deduplicate, classify, capture |
| [Harvest](../../extension/learning/harvest.ts) | Bounded docs manifests; `perk.harvest-analyst` | Best effort | Curate a bounded improvement objective |
| [Developer audit](../../extension/learning/audit.ts) | Evidence packets; `perk-dev.session-auditor` | Best effort | Produce bounded verdict artifact |
| [Dream](../../extension/learning/dream.ts), [reduction](../../extension/learning/dreamReducer.ts) | `perk.dream-analyst`, then three `perk.dream-reducer` lenses | Strict in both phases; parent-validated intermediate bundle | Curate one objective and dream report |
| [Submit conflict](../../extension/pi/v1/delivery/submit.ts) | Prompt-authored single `perk.conflict-resolver` | Text outcome; bounded redispatch attempts | Recheck mergeability after authorized child rebase/verify/push |
| [Stack conflict](../../extension/pi/v1/delivery/stackSync.ts) | Same role, retained-continuation sentinel | Text outcome; canonical state and attempt checks | Obtain human consent before continuation/publication |

The shipped agent list in `src/perk/convergence/init/agents.py` is authoritative. A catalog
mention of `perk-pr-review-dynamic` is not evidence of an implemented selector flow.

## Appendix B — Twelve-release ledger

Dates below are UTC publication dates, which can differ from a changelog’s calendar heading.
The selection column identifies Perk-relevant changes, not the entire release contents.

| Release | Published | Relevant additions, changes, or fixes |
|---|---|---|
| [v0.55.0](https://github.com/nicobailon/pi-subagents/releases/tag/v0.55.0) | Aug 23 | Thinking/provider defaults, relative output paths under managed artifacts, child-level controls |
| [v0.56.0](https://github.com/nicobailon/pi-subagents/releases/tag/v0.56.0) | Aug 23 | Namespaced extension bindings; schema/acceptance compatibility |
| [v0.57.0](https://github.com/nicobailon/pi-subagents/releases/tag/v0.57.0) | Aug 26 | Offline script validation, script files, external CLI profiles, bounded child summaries |
| [v0.58.0](https://github.com/nicobailon/pi-subagents/releases/tag/v0.58.0) | Aug 27 | Global-context opt-in, runtime-agent event registration, partial settlement and recovery |
| [v0.59.0](https://github.com/nicobailon/pi-subagents/releases/tag/v0.59.0) | Aug 28 | Sequential lanes, host-command steps, workflow concurrency enforcement, nested authorization, control/evidence improvements |
| [v0.60.0](https://github.com/nicobailon/pi-subagents/releases/tag/v0.60.0) | Aug 30 | Structured capability discovery, progress grouping, clearer recovery diagnostics |
| [v0.61.0](https://github.com/nicobailon/pi-subagents/releases/tag/v0.61.0) | Aug 31 | Wait-alias removal, workflow-specific limits, built-in named resources, leaner context/status |
| [v0.62.0](https://github.com/nicobailon/pi-subagents/releases/tag/v0.62.0) | Aug 31 | Structured acceptance evidence, tool exclusions, session-only schedules, fork cwd fixes |
| [v0.63.0](https://github.com/nicobailon/pi-subagents/releases/tag/v0.63.0) | Sep 1 | Scan directories, custom override parity, Worktrunk, read-only acceptance correction |
| [v0.64.0](https://github.com/nicobailon/pi-subagents/releases/tag/v0.64.0) | Sep 2 | Watchdog launch rules/diff/cadence/instructions; warnings surfaced in results |
| [v0.65.0](https://github.com/nicobailon/pi-subagents/releases/tag/v0.65.0) | Sep 4 | Native sessions, changed extension loading, renamed tool-plan subpath, worktree baseRef, bundled supervisor allowlists |
| [v0.65.1](https://github.com/nicobailon/pi-subagents/releases/tag/v0.65.1) | Sep 4 | Omitted child async defaults, provider/package/proxy/session fixes, complete validated worktree patches |

The [tagged changelog](https://github.com/nicobailon/pi-subagents/blob/v0.65.1/CHANGELOG.md)
provides the full chronology. Schedules and missions are not recommended merely because they
exist: adopting them would require a concrete Perk-owned lifecycle and authority decision.

## Appendix C — Verification and remaining uncertainty

Completed during this assessment:

- `node --test --test-reporter=spec extension/waves/rpcAdapter.test.ts extension/waves/reportWaveRpc.test.ts extension/waves/adapterContract.test.ts`:
  **31 passed, zero failed**. These tests use simulated upstream responses.
- A representative script was captured from Perk’s actual renderer without launching a child.
  The installed engine’s `validateWorkflowScript` returned `ok: true` with no errors. The
  captured root had `async: true`; child assignments did not specify `async`.
- The installed `resolvePiLaunchToolPlan` resolved both streaming reviewers, with structured
  reporting requested, to `read, grep, find, ls, bash, structured_output` and no
  `contact_supervisor`. This proves the canonical-definition mismatch, not actual message
  delivery under arbitrary operator overrides.
- Installed `CHANGELOG.md`, RPC, wait-tool, and child-launch Git blob hashes matched v0.65.1
  at tag commit `83be9c3de2cde1553c0269f383efc1eb1194dc8b`.

The checks did not run live model children, measure performance, exercise the full UI relay,
or run all of Perk’s CI. Script validation and a passing fake adapter are necessary evidence,
not end-to-end compatibility certification.

Before implementing expansions, verify foreground/background capabilities and command gating;
supervisor delivery and wait behavior; exact-once collection through cancellation and reload;
partial-report retention; and installed-consumer package resolution. Keep those results distinct
from upstream-only tests and measurements. The acceptance criterion for this memo is an
evidence-backed, ranked decision aid covering all seven requested questions—not a claim that
the recommended repairs have already been made.
