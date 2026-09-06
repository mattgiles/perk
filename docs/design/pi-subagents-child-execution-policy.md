# Native child execution policy and scratch identity

**Accepted policy; profiles and restriction producer implemented.** Approval status is recorded
only in the pointer below. The profile encoding/restriction producer is implemented by node 3.2;
node 3.3 still owns scratch identity and child restriction enforcement. This record distinguishes
implemented producer behavior from that pending consumer repair and from historical measurements.
The [characterization archive](archive/pi-subagents-child-capability-characterization.md)
contains the protocol, native outcomes, historical failures, exact disposable sources and
independent teardown. Experiment approval is not approval of these selections.

## Approval pointer

**Accepted by owner merge.** Owner `mattgiles` accepted PR #2231's unchanged published head
`a45e437c3be3da9f0e57e9caaa2808978bfc4516` by merging it at `2026-09-06T15:03:37Z`,
merge commit `de133aeb26d74b95f16a699b3a88cd757344251b`, and confirmed acceptance during
implementation planning. There were no formal PR reviews or discussion comments and no separate
local commit/blob attestation. Historically the owner authorized draft publication for review,
not the originally planned pre-submit local approval; publication itself was not approval.
Neither checkpoint `bfb6a09c` nor `b5dd31ef` is approval.

## Additional required repair: current-parent read-only restrictions

The cold claimed-parent R/E measurements remain valid, but do not establish warm inheritance.
The in-scope `/objective-plan` warm door calls `gating.enter(ctx)`, which appends parent branch
mode without updating a handoff. Fresh children instead take `handoff.mode` in `decideClaim`,
or mint without a mode when no inherited env identity exists. Thus a warmed read-only parent
can produce a child with stale read-write handoff mode or no mode. This is a source-established
gap, **not a newly executed case**.

The owner approved expanding the decision/consumer scope for this gap at
**2026-09-06T14:36:56.574Z**, session response `44ba3dfb`; canonical plan #2230 records the
clarification. No additional native probe or production prototype is authorized in this node.
The following is the exact **source-derived repair design**, with its producer implemented and its strict consumer still
requiring 3.3—not a measured warm-path PASS.

### Separate restriction channel

- **Producer:** the Perk-owned ReportWave renderer, for every child of every report attempt.
  `index.ts` supplies a live `() => gating.isActive()` callback to the wave composition.
  Sample it after asynchronous assignment preflight, immediately before rendering/spawning
  each attempt; never cache the value at extension startup or accept it from assignment/task
  data. A failed snapshot fails the wave without spawning. The public ReportWave caller
  interface stays unchanged.
- **Wire:** child `extensionBindings` has namespace **`perk.parent-restrictions/1`**, whose
  value is exactly **`{"readOnly": boolean}`**, with no additional fields. Always send the
  namespace, including false. No agent name, run id, stage or write grant belongs in it.
  The native runner exposes the canonical bounded JSON through
  `PI_SUBAGENT_EXTENSION_BINDINGS`; S-B proved this transport generically. This namespace's
  new gate effect was not exercised live.
- **Consumer:** a separate `extension/substrate/childRestrictions.ts` boundary, composed in
  `index.ts` before initial gate synchronization and any model turn. Only a runner-hosted
  child (`PI_SUBAGENT_CHILD === "1"`) consumes it; foreground/parent activations ignore this
  environment carrier. It is not a source of agent identity.
- **Decode:** bound the raw envelope to 16 KiB before JSON parsing. Require an object envelope;
  unrelated namespaces are ignored. Require the reserved value to have exactly one own
  boolean `readOnly` field. Invalid JSON/envelope, an invalid reserved value, or an unsupported
  version in the `perk.parent-restrictions/` family produces a read-only floor plus a bounded
  once-per-session warning, never a permissive default. An absent envelope/namespace is legacy
  input: no new floor and no claim of repaired warm inheritance. Both producer and consumer
  must be installed before this record's full report profile is realized.
- **Monotone effect:** true establishes a child-session read-only **floor**; false adds no
  restriction and is **not evidence of write authority**. Effective gating is the existing
  branch read-only mode **OR** this floor. Within the child activation, no later false/missing
  input, `exit()`, branch navigation or child mode append may clear a captured floor.
  Unknown/forged true can only restrict.
- **State/lifetime:** capture per extension activation and full SDK session identity, not in
  process-global mutable state. Preserve the existing claim/adopt/mint result and errors;
  apply the floor even when the handoff is absent or stale. Reflect a true restriction as
  read-only child branch mode where state establishment succeeds, but do not rely on that
  append for enforcement: a persistence failure remains loud and cannot open the gate or
  enable scratch. Never mint a replacement identity to hide a linkage failure, change stage,
  or rewrite/consume the parent's handoff. Normal reload recaptures the original native packet
  and preserves any existing branch read-only restriction. There is no invented durable copy
  of an unpersisted floor: loss/tampering of both packet and state is outside the repaired
  profile, not a claimed protected reload. A new physical session does not inherit an old
  activation's cached floor.
- **Scratch:** both scratch hooks consult effective read-only gating before advisory identity,
  including the floor even if a mode append failed. `/btw` retains its existing effective-gate
  check. The restriction reader and identity reader cannot grant authority to one another.

This is a spawn-time restriction snapshot, not continuous permission revocation. A later parent
mode change does not reopen a restricted child or retroactively restrict a child launched
without a floor; normal cancellation remains available. Public/manual subagent calls outside
Perk's code-owned ReportWave producer are not certified by this channel. It is not an operating-
system sandbox or authentication between malicious host extensions.

Node 3.2 owns producer wiring/serialization; 3.3 owns strict decoding, the monotone floor in
`toolGating.ts`, startup wiring and effective-gate scratch checks. Required ordinary regressions:
warm parent without `PERK_RUN_ID`/handoff; warm read-only over a stale read-write handoff; each
retry sampling the current gate; false preserving an inherited read-only mode; true surviving
exit/tree changes and failed state persistence; malformed/version-skew packets; unchanged
parent/sibling gates; and all ten report assignments carrying the reserved namespace. No warm
native result is invented, and no new policy decision is deferred to those implementation nodes.

## 1. Evidence boundary and terms

The exercised Perk code is `5dd1cc2a26dbecdc715b72a4cf16f95b4705b62a`; the later commits
contain documentation only. The measured composition is Node 26.3.0, pi-subagents 0.65.1,
and the five repo-local Pi packages at 0.85.1. The engine remains unpinned; the five exact
dev pins remain unchanged. This is not certification of global/consumer installations.

- **Workflow scheduling** decides whether the parent waits for an enclosing workflow call.
  It does not determine its children's execution mode.
- **Child mode** is foreground (native session in the parent process) or background (native
  session in a detached runner).
- **Agent identity** names a resolved agent. **Perk run identity** identifies workflow data.
  Neither an agent name nor a Perk run id grants write authority or a launched stage.
- **Advisory identity** below is a source-bound prompt claim used only for scratch policy,
  not authenticated provenance or a security principal.

R/S/E measured the objective-explorer capability shape; W measured conflict-resolver's shape.
Other report roles are **representative-derived**, not individually run. Model defaults,
fallbacks, Ponytail variants, autonomous reviewer rubrics and real rebase/push procedures were
not all exercised. W was intentionally cancelled, not certified as a successful production
resolver task. The eight intended cases used eleven authorized launches including historical
failures, plus the single B0 smoke; that budget is exhausted.

The [closed matrix](archive/pi-subagents-child-capability-characterization.md#closed-matrix-classifications)
is the capability authority. R-F lacks inherited Perk enforcement; S-B reproduces missing
report-only scratch suppression; both W modes support the measured writer operations and
cancellation. E proves explicit loading only under read-only parents and **cannot authorize
any explicit-Perk-list production profile**. Phase-2 waived streaming legs remain waived.

## 2. Closed role and consumer census

`src/perk/convergence/init/agents.py::PERK_AGENTS` owns ten delivered definitions. Nine are
reports and one is the writer. The separately owned repo-local auditor adds one report:
**8 non-streaming reports + 2 streaming reports + 1 writer = 11 roles**. Every included role
appears exactly once below. `agents/<stem>.md` is canonical for delivered roles;
`.pi/agents/perk/<stem>.md` is its byte-identical managed copy.

| Role | Family / selected child mode | Owning launch source | Primary consumer regression suite |
| --- | --- | --- | --- |
| `perk.pr-reviewer` | Non-streaming / background | `extension/waves/prReviewWave.ts` | `extension/waves/prReviewWave.test.ts` |
| `perk.review-classifier` | Non-streaming / background | `extension/waves/reviewClassifierWave.ts` | `extension/waves/reviewClassifierWave.test.ts` |
| `perk.objective-explorer` | Non-streaming / background | `extension/waves/objectiveExplorerWave.ts` | `extension/waves/objectiveExplorerWave.test.ts` |
| `perk.learn-analyst` | Non-streaming / background | `extension/learning/analystWave.ts` | `extension/learning/analystWave.test.ts` |
| `perk.harvest-analyst` | Non-streaming / background | `extension/learning/harvest.ts` | `extension/learning/harvest.test.ts` |
| `perk.dream-analyst` | Non-streaming / background | `extension/learning/dream.ts`, orchestrated by `extension/learning/dreamAnalysis.ts` | `extension/learning/dream.test.ts`, `extension/learning/dreamAnalysis.test.ts` |
| `perk.dream-reducer` | Non-streaming / background | `extension/learning/dreamReducer.ts`, orchestrated by `extension/learning/dreamAnalysis.ts` | `extension/learning/dreamReducer.test.ts`, `extension/learning/dreamAnalysis.test.ts` |
| `perk-dev.session-auditor` | Non-streaming / background | `extension/learning/audit.ts`; definition `.pi/agents/perk-dev/session-auditor.md` | `extension/learning/audit.test.ts`, `extension/learning/auditorDef.test.ts`, `tests/test_repo_local_agents.py` |
| `perk.adversarial-reviewer` | Streaming / background | `extension/waves/adversarialReviewWave.ts` | `extension/waves/adversarialReviewWave.test.ts` |
| `perk.draft-reviewer` | Streaming / background | `extension/waves/draftReviewWave.ts` | `extension/waves/draftReviewWave.test.ts` |
| `perk.conflict-resolver` | Writer / foreground, both subprofiles | Both `prompts/stages/conflict-resolution*.md` templates; injected by `extension/pi/v1/delivery/submit.ts` and `extension/pi/v1/delivery/stackSync.ts` | `extension/pi/v1/delivery/submit.test.ts`, `extension/pi/v1/delivery/address.test.ts`, `extension/pi/v1/delivery/stackSync.test.ts`; `extension/substrate/stageTools.test.ts` |

Custom/Ponytail review lanes are invocation variants of the listed reviewers, not new agent
identities. Excluded: `perk-dev.analyst`, user/custom definitions, upstream builtins and external
CLI agents. The exclusion does not erase their explicit scratch fallback in §5. A new
code-owned role is scope drift: reconcile this record before encoding it, never classify it
by a name heuristic.

### Preserved model and skill exceptions

Keep `[models.subagents]` lookup and workflow-level model injection unchanged, including the
`inherit` sentinel and thinking suffix. Keep every canonical default/fallback list; these are
source facts, not claims that each model was tested:

| Role stem | Default → ordered fallback |
| --- | --- |
| `pr-reviewer`, `learn-analyst`, `conflict-resolver` | `anthropic/claude-sonnet-4-5` → `anthropic/claude-haiku-4-5` |
| `review-classifier`, `objective-explorer` | `anthropic/claude-haiku-4-5` → `anthropic/claude-sonnet-4-5` |
| `harvest-analyst`, `dream-analyst` | `openai/gpt-5.6-terra` → `openai/gpt-5.6-luna` |
| `dream-reducer`, `adversarial-reviewer` | `anthropic/claude-fable-5` → `anthropic/claude-sonnet-4-5` |
| `draft-reviewer` | `openai/gpt-5.6-sol` → `openai/gpt-5.6-terra` |
| `session-auditor` | `openai/gpt-5.6-luna` → `openai/gpt-5.6-terra` |

Preserve source-bound Ponytail `skillPath` declarations: `ponytail-review` for pr-reviewer and
adversarial-reviewer, `ponytail` for draft-reviewer, under the project-installed
`@dietrichgebert/ponytail` package. `extension/waves/ponytail.ts` retains exact-source preflight,
lane-local failure and no same-named global/project fallback. An explicit assignment skill is
not discovered-skill inheritance. No other role gains an explicit skill or extension.

## 3. Selected execution profiles

| Dimension | All ten report roles | Conflict resolver, both subprofiles |
| --- | --- | --- |
| Child mode | Background | Foreground |
| Encoding | Canonical definition `async: true`; child-call `async` **absent** | Child-call `async: false`; do not change the definition's existing omitted execution default |
| Workflow scheduling | Existing `async: true` ReportWave transport | Existing top-level `async: false` one-child workflow |
| Conversation | Existing fixed top-level `context: "fresh"` inherited by children | Existing explicit top-level `context: "fresh"` inherited by the one child |
| Project context | `inheritProjectContext: false` | `inheritProjectContext: true` |
| Global context | `inheritGlobalContext: false` | `inheritGlobalContext: false` |
| Discovered skills | `inheritSkills: false` | `inheritSkills: true` |
| Base prompt | Preserve `systemPromptMode: replace` and role rubric | Preserve `systemPromptMode: replace` and both resolver rubrics |
| Extensions | Omit `extensions` and `subagentOnlyExtensions`; use ambient runner discovery | Omit both fields; foreground has no ambient discovery |
| Mission / acceptance | Fixed `mission: false` and existing `WAVE_ACCEPTANCE` (`level: none`) | Preserve existing omissions/native defaults; do not add a new acceptance or mission contract |
| Required tools | `read`, `grep`, `find`, `ls`, `bash`, engine `structured_output` | `read`, `grep`, `find`, `ls`, `bash`, `edit`, `write` |
| Supervisor | Optional capability with the rules below | Optional; absence cannot change mode or authority |
| Actual cwd | Trusted calling session's cwd via the native RPC context | Explicit child `cwd` from the validated dispatch worktree |

**Why this split:** background reports preserve required ambient Perk/provider behavior and
inherited cold-parent enforcement that R-F loses. Complete warm-parent enforcement and named
scratch suppression **require the specified 3.2/3.3 repairs**, not claimed current passes.
Foreground writers preserve the measured builtins, real cwd and project/skill inheritance while avoiding an unproven cross-cwd Perk handoff.
This is a fixed policy choice, never a failure-triggered mode fallback.

A1's encoding is mandatory. The installed `prepareWorkflowLaunchParams` sets
`workflowAwaitAsync: true` for an omitted child `async`, then the definition selects background.
Explicit child `async: true` instead returns detached-launch semantics and must not be substituted
for the omission. Do not expose that private await flag in Perk payloads or add a collector.
The release's `workflow-launch-params.test.ts` corroborates this distinction; R/S/E exercised it.

Node 3.2 implements `async: true` to the **nine delivered report definitions and the repo-local
auditor**, converges their managed copies, and tests the intentional renderer omission. It encodes
`async: false` and the actual `cwd` to the child item in **both** conflict templates. It makes
`inheritGlobalContext: false` explicit in the eleven definitions; that preserves the selected
resolved value rather than relying on a future engine default. Global context instructions
are distinct from skill discovery: writer skill inheritance includes the ordinary global/project
catalog, subject to the engine's mandatory removal of the orchestration skill. This never grants
nested-subagent tools. No `ReportAssignment`/`ReportWave` caller-interface expansion or generic
profile/agent registry is needed; the live restriction supplier is composition-internal.

### Extension, provider and cwd boundaries

Reports run from the trusted parent project with normal Perk wiring. Cold handoff adoption
remains unchanged; warm parents use the additional restriction channel above rather than a
fictional handoff. The existing RPC context supplies the cwd deliberately; review-head worktree
paths remain **read-only task data**, not a runtime/agent/extension discovery root. No head-provided
agent definition, extension or setup command is loaded merely to review a PR. Preserve the
current explicit-source skill checks and native discovery; a missing/mismatched role or required
capability is a loud failure, never a switch to foreground.

Omitted, empty and explicit extension lists are not interchangeable. `extensions: []` disables
ambient loading; an explicit Perk list disables other ambient sources. Neither is selected.
The observer was diagnostic only and must not enter production definitions or payloads.

Foreground writers do **not** acquire Perk scratch, inherited Perk mode or ambient-extension-only
provider/MCP capabilities. Their native/global model configuration remains available, as W-F
proved for the configured `openai/gpt-5.6-luna`; this is not a provider-extension certificate.
A provider/extension composition requiring ambient child loading is outside this writer profile:
stop and re-verify/reconcile with the owner, not silently run background or drop the configured
model. Existing model configuration and declared model fallback lists are not rewritten by this
record; engine/provider errors remain loud.

### The two writer dispatch subprofiles

1. **PR rebase:** the source is `ctx.cwd` in the worktree-bound submit/address flow. Pass that
   absolute validated path as child `cwd`, not just `cd` prose. The existing resolver owns
   context fetch, rebase, verification and force-with-lease push; its PR-only abort behavior
   stays unchanged. Parent re-submission still re-verifies mergeability.
2. **Retained continuation:** the source is the fresh, containment-validated
   `SyncConflictDispatch.worktree`, from the Python-owned continuation projection. Pass it as
   child `cwd`; preserve the retained-mode sentinel, explicit PR identity, in-progress-rebase
   checks, completed-only outcome gate, no push/no abort rule, claim lease and attempt cap.
   Publication remains the human's `objective_stack_sync {continue: true}` gesture.

Both require the existing authorized write-capable parent flow and exactly one writer per
worktree. Missing/ambiguous worktree or agent capability fails before mutation. Discovery occurs
at the actual target cwd; do not silently accept a conflicting/shadowed definition or install
new wiring inside an in-progress retained rebase to make discovery pass. Profile changes remain
in the prompt-authored dispatch; no code-owned dispatcher, rebase helper or authority migration.

The retained worktree does **not** automatically carry the caller's
`.perk/workflow/handoff/<PERK_RUN_ID>.json`. `cache.readHandoff` is cwd-local; `sync.py` creates
an isolated detached Git worktree, while the warm adapter only validates and injects guidance.
W-B explicitly linked the real consumed parent handoff into its separate fixtures. Selecting
background there as if that transport already existed would be fiction. **No cross-cwd handoff
copying, synthetic parent handoff or writer lifecycle transport is assigned to 3.2/3.3.**
Foreground is the measured writer profile that needs none of them. Its lack of Perk scratch
is part of the selected trade-off.

### Supervisor and cancellation limits

Non-streaming reports complete through their engine-validated structured report. Supervisor
absence, failed submission or no timely delivery is optional-capability degradation, not a
reason to retry/change mode or invalidate an otherwise valid report.

Streaming reviewers retain the Phase-2 contract: attempt nonempty finding batches when the
native tool is available; `streamed: true` means accepted/queued submission, not human-visible
delivery. No findings yields false without an empty batch; unavailable/partial streaming is
explained in `fyi`, and collection discloses completion-only findings. Preserve the existing
native-wake relay, schema/coverage rules, parent sink and final-authority behavior. The observed
background supervisor messages arrived after workflow settlement at the headless parent's
message-event surface. That is an allowed negative observation, **not** a timely-delivery
promise or a revalidation of the waived browser/draft/bridge-off legs.

Cancellation stays with existing owners: ReportWave transport owns its AbortSignal/deadline
and normal native stop request; the parent/native subagent tool owns the blocking resolver
workflow's cancellation. Stop acknowledgement, logical `stopped`, tool termination, observer
shutdown and detached-process proof are distinct. No automatic restart or `bg_wait` adoption.

W proved exact-child RPC stop inside an **async** enclosing workflow, including actual bash
abort, shutdown, a thirty-second no-trailing-write window and continued parent usability.
The selected blocking resolver workflow is retained from current behavior; propagation to the
same foreground child abort/dispose path is source-backed, **not a separately exercised root-
scheduling variant**. Direct top-level foreground targets are not RPC `stop` targets. Thirty
seconds is the experiment's observation bound, not a new universal production SLA. Node 3.2
pins cancellation propagation in ordinary framework tests without claiming a new live pass.

## 4. Identity carrier decision

**Use the engine-authored session system-prompt prefix as advisory agent identity.** Its exact
producer is pi-subagents 0.65.1 `buildInProcessChildLaunch` in
`src/runs/shared/child-launch.ts`; the namespace/field is `active_agent.name`:

```text
<active_agent name="perk.objective-explorer"/>
```

With a non-null role prompt and `systemPromptMode: replace`, the producer puts this line first,
followed by two newlines and the role prompt. It escapes `&`, `"`, `<`, `>` as the corresponding
named XML entities. The consumer reads **`ctx.getSystemPrompt()` at `session_start`**, before
scratch eligibility is evaluated by `before_agent_start` or `context`. R/S/W/E directly
observed that timing in the modes where the observer/Perk were active. At later provider time
the first line is the engine's child-boundary prose: do not re-scan the live prompt each turn.

Perk's new resolver belongs at `extension/substrate/childIdentity.ts`, composed by `index.ts`
and consumed by `agentScratch.ts`. Cache only within one extension activation, keyed to the
full SDK session UUID plus session-file path (or null). Never key it solely by Perk run id or
`pi_session_id` basename—multiple children use `session.jsonl`. No process-global name stamp,
new persisted identity entry, public model tool or engine-internal import.

The shape to implement is a typed advisory result: valid name versus unavailable (absent,
malformed, unreadable or stale), with provenance `native-system-prompt-prefix`. Availability
is not inferred from task text, session display name, a report's `case`, `PERK_RUN_ID`, stage,
parent-history content or arbitrary later prompt lines.

### Parsing, precedence and lifecycle

- Inspect only the exact first line; cap it at 4 KiB UTF-8. Require the entire line to match
  the one-tag/one-double-quoted-`name`-attribute shape, without leading/trailing whitespace,
  additional attributes, extra tags or literal unescaped XML-significant characters within
  the attribute value.
- Decode only the four producer entities, **once**, and require canonical re-encoding to
  reproduce the attribute bytes. No general XML parser or recursive entity expansion. Require
  a nonempty decoded name, at most 256 UTF-8 bytes and no Unicode General Category Cc
  control characters. Compare known
  names exactly and case-sensitively; valid names outside the census remain custom/unknown.
- The startup prefix is the only name carrier. Ignore `PI_SUBAGENT_CHILD_AGENT` entirely.
  Ignore every `extensionBindings` namespace for scratch identity, including conflicting
  claims. S proved that bindings are runner-only, so selecting them as a two-mode identity
  channel would add an unnecessary split. There is **no identity binding namespace**:
  `perk.parent-restrictions/1` is consumed only by the separate restriction boundary.
- `ChildRuntimeConfig.agent` is engine-internal hook data; no supported third-party getter was
  established. Do not import private engine modules, inspect closure state, or infer agent
  identity from runtime-acknowledgement IDs.
- Read `PI_SUBAGENT_CHILD === "1"` only as the documented **runner-hosted-child presence bit**
  for unavailable-identity fallback. It never supplies the name, mode, stage or write authority.
  Read it into the activation/session snapshot; never set it for a foreground child.
- Every `session_start` replaces the snapshot; `session_shutdown` clears it. Session-key
  mismatch makes the cached value unavailable, never an inherited name. `session_tree` and
  compaction do not reinterpret quoted markers or change the physical session's actor.
- Reload must discard and recapture, not carry a prior name. Source tracing in Pi 0.85.1 shows
  runtime/tool-registry reconstruction restores the loader's base system prompt before
  `session_start`; the child loader retains its tagged replacement prompt. This reload path
  is source-backed and must be regression-tested by 3.3, not labeled another native live case.

### Advisory—not authentication

Task/history/PR text containing a marker is ignored; it cannot precede the engine's prefix
through normal role construction. A privileged host/extension that forges the actual first
system-prompt line can forge this advisory claim. Perk does not pretend otherwise. A forged
known-report prefix may suppress scratch even in a parent; a forged writer/custom prefix may
change scratch eligibility, but **never** opens tools, changes workflow mode, grants mutation,
re-consumes a handoff or creates a launched stage. Such host tampering is outside the claim of
report-only enforcement. This trade-off is selected only for scratch guidance/provisioning,
not for an authorization principal. New uses require a separate decision.

## 5. Exact scratch behavior for 3.3

These rules apply only when Perk is active. Effective read-only gating—branch-LWW mode **or**
the separate parent-restriction floor—wins before identity and makes the turn ineligible.
Preserve the existing claim implementation; the identity resolver never changes authority.

| Identity after startup capture, with no effective read-only restriction | Agent scratch eligibility |
| --- | --- |
| Any of the ten report roles in §2 | **No** |
| `perk.conflict-resolver` | **Yes** |
| Valid custom/unknown name outside the closed census | **Yes**, retaining the named-custom fallback |
| Absent/malformed/unreadable/stale name in a runner-hosted child (`PI_SUBAGENT_CHILD === "1"`) | **No**, conservative unidentified-child fallback; warn once per session/reason |
| Unavailable name without the runner bit | **Yes**, parent/unidentified-foreground fallback; not proof of foreground report suppression |
| Legacy-only or bindings-only name claim | Ignore the claim; apply the applicable unavailable row |

The unidentified-background fallback is deliberately narrower than today's unconditional
unknown-name eligibility. It also covers custom append-mode prompts without an initial marker;
their definitions are not changed. A well-formed custom name remains eligible. A foreground
missing/malformed marker cannot reliably distinguish an uninstrumented child from a parent:
that is an **explicit unsupported negative case**, never a compatible report profile. All
selected report roles are background with tagged replacement prompts. Selected foreground
writers have no Perk activation, so their eligibility is not a promise of scratch provisioning.

Add `perk-dev.session-auditor` to `REPORT_ONLY_CHILD_AGENTS`: the exact set becomes the ten
reports, excluding conflict-resolver. Do not exclude the auditor merely because init does not
own its definition. Retain parent and valid writer/custom eligibility subject to read-only mode.

For ineligible turns, `registerAgentScratch` must not call the agent-scratch provisioner in
**either** hook, and its context filter removes all direct `perk:agent-scratch` messages.
For eligible turns, preserve confined current-run provisioning before deduplication, one
current direct block, stale/duplicate direct-block removal, and visible provisioning failures.
Do not edit prose quoted inside ordinary messages/compaction summaries. The lifecycle may still
create a derived run root for workflow/session data: report suppression means no **`agent/`
directory or agent-scratch guidance**, not zero lifecycle filesystem activity.

## 6. Implementation-only responsibilities

### Node 3.2 — implemented profile/producer responsibilities

- Change the nine delivered report defaults and auditor default to `async: true`; converge
  byte-identical managed copies. Keep writer definition default unchanged and make both
  owned writer calls explicitly foreground with actual child cwd.
- Encode explicit global-context false while preserving project/skill fields, models,
  fallbacks, Ponytail exact-source exceptions, report mission/acceptance and writer defaults.
- Preserve `renderWaveScript`'s child-async omission and ReportWave's fixed async/fresh
  transport. Add the composition-internal live gate supplier and the exact per-child
  `perk.parent-restrictions/1` serialization specified above, sampled anew per attempt.
  Do not add a generic profile override, caller-controlled restriction/extension field or raw
  transport access outside the existing boundary.
- Update both conflict templates and their render/dispatch tests, including submit's address
  consumer and retained continuation's no-publish/completed-only gate. Keep model interpolation,
  attempt counters, leases and existing fail-closed path vocabulary.
- Tests: `tests/test_subagent_agents.py`, `tests/test_managed_state.py`,
  `tests/test_init_idempotent.py`, `tests/test_packaging.py`, `tests/test_repo_local_agents.py`;
  the per-consumer suites in §2; `extension/waves/reportWave.test.ts` (including transport
  timeout/cancellation tests), `extension/waves/reportWaveRpc.test.ts`,
  `extension/waves/rpcAdapter.test.ts`; and `extension/delivery/stackConflict.test.ts`.
  Pin all 11 memberships, background defaults despite a foreground engine default, writer
  explicit false despite a background default, writer definition default still omitted,
  no serialized child `async: true`, unchanged model/skill exceptions, actual cwd on both writer paths, and the fixed report context and
  acceptance contract. Regenerate `shared/subagents/representative-wave-script.js` for the
  new restriction field; never teach its golden the forbidden child `async: true` flag.
- Amend `shared/contracts.md` for the implemented behavior and matching user-facing docs.
  The implemented producer/profile behavior is recorded there; the separate consumer remains pending.

### Node 3.3 — implement identity and the independent restriction floor

- Implement the bounded resolver and activation/session-local capture in
  `extension/substrate/childIdentity.ts`; wire it before scratch hooks can evaluate eligibility.
  Replace the removed environment-name dependency in `agentScratch.ts`, add the auditor, and
  preserve the independent lifecycle/gating authority and `/btw` parent's provisioner behavior.
- Implement the separate `childRestrictions.ts` decoder/floor and add
  `extension/substrate/childRestrictions.test.ts`, including the warm-path and monotonicity
  cases specified above. Wire the floor before gate synchronization; neither identity nor
  a failed child-state append may weaken it.
- Add `extension/substrate/childIdentity.test.ts`; extend
  `extension/substrate/agentScratch.test.ts`, `extension/substrate/toolGating.test.ts`,
  `extension/session/lifecycle.test.ts`, `extension/sessionLifecycle.test.ts`
  and the existing `/btw` tests where wiring touches them. Use pytest/node:test, not a retained
  disposable decoder or a new native-run framework.
- Cover both active launch modes with valid known-report/writer/custom markers; all ten
  report names; read-only precedence; malformed/empty/oversized/extra-attribute/double-tag
  input; single-pass entities; task/history/later-line forgeries; privileged first-line forgery
  affecting scratch only; ignored conflicting bindings/legacy names; unavailable foreground
  versus background fallback; independent same-process activations; SDK session/file key
  changes; reload recapture; compaction and branch navigation; and direct scratch cleanup.
- Pin no provisioner call for reports/unidentified background children in either hook, but
  preserve eligible-writer/parent retry and dedup behavior. Prove identity cannot change mode,
  stage, handoff consumption, gate toolset or sibling/parent state. Keep unsupported foreground
  activation/carrier cases explicitly negative, not universal compatibility claims.
- Amend the implemented identity/scratch/restriction contract and corresponding docs. No new
  write grant, cross-cwd handoff transport, process-global foreground stamp or generic sandbox.

## 7. Reconsideration and residuals

Re-verify and reconcile this record before either consumer departs from it when engine/Pi
version **or relevant bytes** change, extension/provider composition changes, native mode/default
resolution changes, the prefix producer/timing changes, or a contradictory live observation
appears. Upstream HEAD can differ while still declaring 0.65.1; version equality is insufficient.
Use [the re-verification guide](../developers/pi-subagents-reverify.md), preserve failures and
seek owner disposition. No automatic install, fallback mode, new live attempt or source-hash
refresh merely to get a pass.

Residuals presented for final review are: representative-derived sibling coverage; source-only
model/global-context/reload/root-scheduling claims; foreground writer's absent Perk scratch and
ambient-provider support; no arbitrary cross-cwd handoff inheritance; advisory spoofable identity
with the explicit fallback matrix; late background supervisor observation; and the untouched
Phase-2 streaming waivers. The report-suppression and strict warm-restriction consumer repairs
remain **required from 3.3, not implemented here**; profiles and the per-attempt producer are
implemented. No warm-path native PASS is claimed. No unresolved policy
choice is delegated to the implementation consumers.
