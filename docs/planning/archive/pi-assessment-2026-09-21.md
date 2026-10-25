# Pi release assessment — 2026-09-21

Status: proposed follow-up work, grounded in source review and focused local probes.
This assessment changes no runtime code, dependency pins, or compatibility claims.

Use **Pi 0.87.0 as the next minimum supported baseline**, together with
pi-subagents 0.70.1 and Plannotator 0.27.17. This is the chosen direction for the
follow-up work; the versions recorded in perk have not yet been changed or certified.

The first work should repair two reproduced behavioral defects: perk's context
evidence projection ignores Pi 0.87 context edits, and `/btw` seeds agent state that
Pi now replaces from the session manager before a request. Updating types alone
does not catch either defect. After those repairs, simplify `/btw` summarization
with the public model registry streaming API. Treat the new lifecycle hooks and
context-budget controls as bounded adoption candidates.

## Snapshot and evidence

The comparison is against perk 3.5.0 at
`8e0843fa597996c0693fd9a1547a4a0f6c30c829`, whose Pi development dependencies remain
pinned to 0.85.1. Dates below are GitHub release publication dates in UTC, verified
with `gh`; they are not commit author dates.

| Release | Published | Release commit | Role in this assessment |
| --- | --- | --- | --- |
| [0.85.1][release-0851] | Before the review week | `d981de1229ef899957bbe968bc8dcda02a21f477` | Current perk development baseline |
| [0.86.0][release-0860] | September 19 | `ecac0a9c4edad3dac5d9f8b40e0c7db7a56471fc` | Public registry streaming, context/cache controls |
| [0.86.1][release-0861] | September 20 | `13cbf77df2396303013a41646bcfa77b4271ae56` | Included maintenance release |
| [0.87.0][release-0870] | September 21 | `16787ad5b2dc748047f314ca1bfe7708f30f54f3` | Installed host and proposed floor |

The installed global `@earendil-works/pi-coding-agent` and its Pi dependencies are
0.87.0 under the mise Node 26.3.0 installation. The local source checkout at
`~/dev/github/earendil-works/pi` was at
`1b6ddca87ca041e3b02b387d5a321eb77fc39eca`. It includes a post-release empty-text
multimodal fix; that fix is **not attributed to installed 0.87.0** here.

Evidence labels distinguish **reproduced** behavior in the installed SDK,
**source-supported** conclusions from released code, and **needs validation**
proposals. The probes did not call a model provider or exercise a live TUI session.

| Perk integration | Current responsibility | Relevant upstream seam |
| --- | --- | --- |
| [Context evidence][context-evidence], [context injection][context-injection], [binding delivery][bindings], [agent scratch][scratch] | Decide whether owned guidance is actually in active context | Canonical session projection and context edits |
| [`/btw`][btw] | Seed a side session, preserve its own tools/policy, summarize the thread | AgentSession request projection; model registry streaming |
| [Headless SDK adapter][sdk-adapter] | Worker lifecycle, budgets, cancellation, terminal result | Turn/settlement events and request lifecycle |
| [RPC adapter][rpc-adapter] | Correlate borrowed-extension replies and reject stale responders | Extension discovery and event subscriptions |

## 1. Integration changes that need fixing

### P0: use Pi's edit-aware projection for context evidence

**Reproduced; introduced by 0.87.0.** `activeContextMessages()` currently flattens
`sessionManager.buildContextEntries()` through `sessionEntryToContextMessages()`.
That handles entry conversion and compaction selection, but it does not apply
`context_edit` relationships. Pi's [session manager][up-session] applies those
relationships in `buildSessionProjection()` / `buildSessionContext()`.

With the installed SDK, this in-memory sequence exposed the difference:

```ts
const manager = SessionManager.inMemory(process.cwd());
const id = manager.appendCustomMessageEntry("perk:test-marker", "MARKER", false);
manager.appendContextEdit(id, null);

manager.buildContextEntries().flatMap(sessionEntryToContextMessages);
// Still contains MARKER.
manager.buildSessionContext().messages;
// Empty: the message was omitted.

manager.appendContextEdit(id, { content: "REPLACED" });
// The old path still sees MARKER; the canonical projection sees REPLACED.
```

Perk can consequently treat removed guidance as delivered, or fail to recognize
replacement guidance. This affects owned context markers, binding delivery, and
scratch evidence; it is not merely a display discrepancy.

**Plan:** change the narrow context-evidence seam to consume
`sessionManager.buildSessionProjection().messages`, exposed on the extension's
`ReadonlySessionManager` in 0.87.0. Adjust its source type to require that method.
The full manager also has `buildSessionContext()`, as used in the probe, but the
extension-facing readonly interface does not expose that instance method.
Preserve perk's ownership rules: only the appropriate user or
owned custom-message content proves delivery; assistant text, tool output,
summaries, and persisted bookkeeping do not. Do not add an independent edit replay
or another branch walker. The canonical projector also suppresses older duplicate
compaction summaries retained inside newer ranges; that benefit is source-supported,
not separately reproduced in the probe.

**Acceptance:** use the real session manager to cover omission and replacement of
owned markers, reinjection exactly when needed, unrelated-message rejection,
repeated compaction, and branch/reload behavior. Existing marker semantics must
survive the switch. Review all four consumers listed above.

### P0: seed `/btw` through the session manager

**Reproduced; introduced by 0.87.0.** `createSideSession()` writes its parent/thread
seed directly to `session.agent.state.messages`. Pi's new
[`_installAgentRequestProjection()`][up-agent-session] builds request messages from
the session manager and replaces that state before the request. The side session's
in-memory manager does not contain the seed.

A no-network probe using the installed SDK, an in-memory credential store/settings
manager, an empty resource loader, and a fake provider observed:

```json
{"directStateAssignmentSurvives":false,"sessionManagerAppendSurvives":true}
```

The first case assigned a seed to agent state and inspected `agent.prepareRequest()`.
The second appended the seed to the session manager and called `refreshContext()`
before preparing the request. Only the second retained it. This proves the SDK
boundary failure; it does not claim a completed live `/btw` conversation test.

**Plan:** persist the selected seed as canonical session entries before making the
side-session request, then refresh context through the supported API. Handle custom
messages and ordinary conversation roles deliberately. `buildSeedMessages()` already
uses Pi's canonical context builder and excludes the parent scratch custom type;
preserve that selection. Preserve the side session's own system prompt, tool set,
restriction checks, and prior side-thread turns. Parent system/tool declarations
must not become side-session authority merely because they appeared in a seed.

**Acceptance:** the first side request sees the selected parent context and previous
side-thread turns; subsequent turns persist normally; omitted/replaced parent
context is not resurrected; scratch exclusion holds; read-only gate changes still
restrict tools; teardown/restoration works after success, error, and cancellation.

### Baseline change and compatibility boundary

**Observed:** perk's current `npm run typecheck` passed with its 0.85.1 dependencies.
A separate, non-mutating TypeScript compiler overlay resolved Pi package roots and
subpaths to the installed 0.87.0 packages; it also reported **zero diagnostics**.
This included the extension/tools program and the relevant coding-agent, ai, tui,
agent-core, and chord types. Neither result establishes runtime compatibility.

After the two repairs, update the Pi development dependency set together and run
the required checks and live flows. Review of the [release changes][up-changelog]
found no current use of removed
`shouldStopAfterTurn`, and no perk `user_bash` hook needing the new fail-closed
handling. Existing turn listeners do not establish a mandatory event-shape migration.
Do not invent broad API churn to explain the two specific behavioral defects.

## 2. Adaptations to remove or tighten

### Replace context-entry conversion with the canonical message projection

The context-evidence fix removes perk's remaining assumption that independently
converted context entries are the authoritative active messages. Remove the
converter import and derived types if unused after the change. The older manual
active-context-window implementation discussed in the [previous Pi memo][old-pi]
has already been replaced; this assessment is not proposing that old cleanup again.

### P1: simplify only `/btw` thread summarization

**Source-supported since 0.86.0; needs provider validation.** Pi's
[model registry][up-registry] now exposes authenticated `stream()` and
`streamSimple()` methods using the configured provider runtime. `/btw` currently
fetches API credentials/headers, constructs a temporary tool-free AgentSession,
prompts it to summarize the thread, extracts the assistant text, and tears it down.

Use the public registry stream for this one-shot, tool-free operation. Preserve the
summary prompt, model choice, thinking policy, abort propagation, empty/error
handling, and the existing policy for injecting a summary into the main session.
This can remove the summary-only session setup and duplicated authentication path.
The registry's `complete()` method predates this review week; the new capability
is public streaming, not the first public authenticated completion API.

The `liveModelRuntime` probe in the same file is a separate concern: creating the
interactive, tool-capable side session still needs a ModelRuntime. Public streaming
does not itself replace that constructor dependency. Do not claim the entire
private-runtime adaptation can be deleted without a supported session factory seam.

### Keep protections whose upstream cause is still present

- Pi's new `pi.on()` unsubscribe support does not remove guards around the separate
  `pi.events` bus or stale RPC responders. Resource-loader review did not establish
  a fix for duplicate discovery across trust phases. Keep the contextless-responder
  hold in the RPC adapter and the duplicate-scope doctor warning.
- Keep worker deadlines, cancellation, idempotent abort, and terminal-result proof.
  New lifecycle events are not by themselves evidence that perk's completion
  contract or budget enforcement is redundant.
- Ordinary context filters inherit Pi's corrected prompt/tool restoration. There
  is no reason to migrate them to `context_with_system` merely to retain behavior.

## 3. Improvements worth purposeful adoption

| Candidate | Fit with existing perk behavior | Decision and validation |
| --- | --- | --- |
| 0.87 actionable `turn_end` and `agent_before_settle` | Worker budget/completion decisions already live near turn boundaries | Evaluate one bounded worker case after repairs. Verify persisted follow-up entries, continuation, cancellation, and exactly one terminal result. `agent_settled` is notification-only for deferred work. |
| 0.86 per-model compaction reserves and retained-context budgets | Different planner/reviewer models have different context needs | Consider a small configuration/documentation change only after measurement. Perk's [objective threshold][objective] is domain policy, not replaced by these budgets. |
| 0.86 cache warming and its decision hook | Potential latency benefit during existing interactive tool work | Inherit normal upstream behavior first. Idle warming is opt-in; quantify latency/cost before adding perk controls. Workers explicitly disable auto-compaction/retry today; do not reverse that policy incidentally. |
| 0.87 canonical context APIs | Shared substrate for both evidence and side-session seeds | Adopt as part of the two required repairs rather than building another abstraction over entry replay. |

Startup compile-cache/lazy compiler work and terminal/clipboard improvements arrive
through the host upgrade. They need ordinary smoke coverage, not new perk features.
The new AgentHarness surface is outside this assessment's proposed implementation
scope. A lifecycle improvement is not justification for rewriting the worker stack.

## Ordered implementation and verification

1. **Repair context evidence and `/btw` seeding against 0.87.0.** Keep the work in
   their existing narrow seams. Add focused regression cases for the behaviors
   reproduced above; update contracts only where the actual perk contract changes.
2. **Move the development baseline together.** Update the coordinated Pi package
   pins, check extension loading and the headless adapter, and run the repository's
   required CI. Exercise guidance delivery across edits/compaction, a multi-turn
   `/btw` session, and a worker success/cancel/budget path on the new host.
3. **Simplify summarization separately.** Verify an extension-registered provider
   and an API-key override, along with abort/error/empty results. Remove only code
   demonstrably displaced by the public streaming path.
4. **Choose adoption work from evidence.** A worker lifecycle experiment and any
   context/cache configuration proposal need their own bounded acceptance criteria;
   neither blocks the two repairs.

Coordinate the baseline with the [pi-subagents assessment][subagents-assessment]:
installed 0.70.1 does not include its checkout's later Pi 0.87 fork-context fix.
Perk's report waves and conflict delegation use fresh context, but that limits the
claim rather than certifying every extension feature. Browser integration checks
are covered by the [Plannotator assessment][plannotator-assessment].

Completed evidence is source comparison, two installed-SDK reproductions, and the
two type checks described above. Full CI, live provider calls, browser waves, and
interactive `/btw` validation remain implementation gates. No certification or
dependency update is implied by this planning document.

[release-0851]: https://github.com/earendil-works/pi/releases/tag/v0.85.1
[release-0860]: https://github.com/earendil-works/pi/releases/tag/v0.86.0
[release-0861]: https://github.com/earendil-works/pi/releases/tag/v0.86.1
[release-0870]: https://github.com/earendil-works/pi/releases/tag/v0.87.0
[up-session]: https://github.com/earendil-works/pi/blob/16787ad5b2dc748047f314ca1bfe7708f30f54f3/packages/coding-agent/src/core/session-manager.ts
[up-agent-session]: https://github.com/earendil-works/pi/blob/16787ad5b2dc748047f314ca1bfe7708f30f54f3/packages/coding-agent/src/core/agent-session.ts
[up-registry]: https://github.com/earendil-works/pi/blob/16787ad5b2dc748047f314ca1bfe7708f30f54f3/packages/coding-agent/src/core/model-registry.ts
[up-changelog]: https://github.com/earendil-works/pi/blob/16787ad5b2dc748047f314ca1bfe7708f30f54f3/packages/coding-agent/CHANGELOG.md
[context-evidence]: ../../extension/pi/v1/contextEvidence.ts
[context-injection]: ../../extension/pi/v1/contextInjection.ts
[bindings]: ../../extension/substrate/bindingDelivery.ts
[scratch]: ../../extension/substrate/agentScratch.ts
[btw]: ../../extension/vendor/btw/btw.ts
[sdk-adapter]: ../../extension/worker/sdkAdapter.ts
[rpc-adapter]: ../../extension/waves/rpcAdapter.ts
[objective]: ../../extension/pi/v1/objective.ts
[old-pi]: upcoming-pi-changes-memo-v3.md
[subagents-assessment]: pi-subagents-assessment-2026-09-21.md
[plannotator-assessment]: plannotator-assessment-2026-09-21.md
