# Memo: pi-subagents’ code-first shift and the opportunity for Perk

**Date:** August 6, 2026  
**Status:** Architecture recommendation  
**Scope:** Recent pi-subagents releases, the meaning of “code mode,” and how Perk could use the shift to deepen and harden its subagent orchestration.

## Executive summary

pi-subagents has moved from a declarative orchestration interface—static `tasks[]`, `chain[]`, and specialized parallel controls—to a code-first interface centered on `workflowScript`.

A `workflowScript` is constrained JavaScript that can start children with stable identities, await their results, fan out dynamically, branch on structured outcomes, mix sequential and parallel phases, and assign individual Git worktrees. The child-execution engine is largely unchanged; the major change is the orchestration control plane.

The transition spans several releases:

- `v0.41.0` introduced `workflowScript`, made it the sole public multi-agent orchestration surface, integrated it with async runs, and added per-child worktree support.
- `v0.42.0` fixed the result channel so scripts could reliably branch on actual child output and added an integration test covering dynamic fan-out followed by sequential worktree phases.
- `v0.42.1` corrected async timeout behavior and removed unsupported progress modes.
- An unreleased post-`v0.42.1` change, [PR #863](https://github.com/nicobailon/pi-subagents/pull/863), makes `workflowScript` the sole public execution surface even for a single child and scheduled work.

For Perk, the largest opportunity is not simply replacing “spawn these children in parallel” with inline JavaScript. The larger opportunity is to move the repeated mechanics of report-oriented subagent waves behind a small, Perk-owned interface:

- Select or accept bounded review angles.
- Launch typed, fresh-context children.
- Apply model and context defaults consistently.
- Validate child reports through `outputSchema`.
- Collect all child outcomes under stable keys.
- Apply flow-specific completeness rules.
- Return one compact, typed result to the parent.
- Leave reconciliation, product judgment, human interaction, and external mutations with the parent.

The best first targets are `/pr-review` and `/learn`. Both already use read-only, report-only fan-out followed by parent-owned reconciliation and one parent-owned mutation.

Perk should also seriously consider child-selected review angles. The most promising design is a bounded selector child that runs concurrently with the mandatory plan-fidelity reviewer. Once the selector returns a schema-valid change profile and recommended angles, the workflow launches the selected additional reviewers. Perk code must constrain that choice to a fixed allowlist, preserve mandatory coverage, respect operator directives, and use deterministic fallbacks.

## 1. What changed in pi-subagents

### 1.1 Before code-first orchestration

Before `v0.41.0`, callers expressed multi-agent work through a widening collection of declarative shapes:

- A top-level `tasks[]` array for parallel work.
- A `chain[]` array for sequential work.
- Static parallel chain steps.
- Dynamic `expand` and `collect` controls.
- Dedicated `/parallel`, `/chain`, and `/run-chain` commands.
- Specialized checkpoint and worktree fields.

That interface could represent common workflows, but adaptive orchestration required more schema concepts. The caller needed to understand the distinction between single, parallel, chain, dynamic fan-out, collection, checkpoints, and their associated output rules.

### 1.2 What “code mode” actually means

“Code mode” is the maintainer’s informal name for the `workflowScript` interface. There is no documented `mode: "code"` setting or `/code` command.

A model-facing invocation looks conceptually like:

```js
subagent({
  workflowScript: `
    const scan = await runs.run("scan", {
      agent: "scout",
      task: "Map the changed area"
    });

    const reviews = await runs.all([
      {
        key: "correctness",
        agent: "reviewer",
        task: "Review correctness using: " + scan.output
      },
      {
        key: "tests",
        agent: "reviewer",
        task: "Review test coverage using: " + scan.output
      }
    ]);

    return reviews.map(result => ({
      key: result.key,
      ok: result.ok,
      output: result.output
    }));
  `
});
```

The script runs in a worker-thread VM. It receives a deliberately narrow environment:

- `runs.run(key, params)` for one child.
- `runs.all(items)` for parallel children.
- `runs.status(id)` for status lookup.
- `runs.ref` and `runs.refs` for concise references.
- `emit(value)` for JSON milestones.
- Captured `console`.
- Ordinary JavaScript control flow.

It does not receive filesystem access, a shell, Pi tools, module imports, or host globals. The child agents retain whatever tools their own resolved profiles permit. The tagged implementation is visible in [`scripted-workflow.ts`](https://github.com/nicobailon/pi-subagents/blob/v0.42.1/src/workflows/scripted-workflow.ts).

Each child result can include:

```ts
{
  key: string;
  ok: boolean;
  runId?: string;
  output: string;
  error?: string;
  structuredOutput?: unknown;
  artifactPaths: string[];
}
```

This is the foundation for the maintainer’s “branch on real child output” claim.

### 1.3 Stable keys are more than labels

Every scripted child has a stable key. Reusing a key with byte-equivalent launch parameters reuses the existing launch promise. Reusing it with different parameters fails.

That gives a workflow:

- Stable identity independent of array position.
- Predictable trace and status records.
- Safer retry and reuse behavior.
- Better correlation between Fleet status, artifacts, and returned results.
- A natural place for domain vocabulary such as `plan-fidelity`, `tests`, or `session-deviations`.

This maps particularly well to Perk, where agent roles and review angles already have stable names.

### 1.4 `runs.run` and `runs.all` have deliberately different failure semantics

`runs.run` is fail-fast: a failed child rejects that awaited step.

`runs.all` waits for every sibling and returns ordered results, including failures as `ok: false`. One failed reviewer therefore does not terminate unrelated reviewers.

That distinction lets callers encode meaningful policy:

- `/pr-review`: a required reviewer failure makes the review wave incomplete.
- `/learn`: an analyst failure becomes a skipped angle, while successful reports remain useful.
- Human-triaged review: partial results can still be streamed to the human, with incompleteness shown explicitly.

## 2. Release chronology

### `v0.39.0`: control-plane groundwork

[`v0.39.0`](https://github.com/nicobailon/pi-subagents/releases/tag/v0.39.0) did not contain code mode. It improved the older declarative system with:

- Session-scoped `allowedAgents` ceilings.
- Stable foreground result indexes.
- Usage budgets.
- Chain approval checkpoints.
- Better steering, detachment, and Fleet controls.
- Better extension and model metadata.

These capabilities remain relevant because code-first workflows reuse them, but the orchestration interface was still declarative.

### `v0.40.0`: consolidation, not a new execution model

[`v0.40.0`](https://github.com/nicobailon/pi-subagents/releases/tag/v0.40.0) primarily refreshed documentation and the bundled skill:

- Recommended model tiers and fallbacks.
- Agent-description overrides.
- Better grouped-result provenance.
- Better model and thinking badges.

It still documented the old `tasks[]` and `chain[]` execution shapes.

### `v0.41.0`: the architectural shift

[`v0.41.0`](https://github.com/nicobailon/pi-subagents/releases/tag/v0.41.0) contains the substantial change.

The work arrived through several related changes:

- [PR #737](https://github.com/nicobailon/pi-subagents/pull/737) added trusted inline `workflowScript`, stable keyed calls, result capture, status lookup, trace capture, `emit`, and worker isolation.
- [PR #744](https://github.com/nicobailon/pi-subagents/pull/744) made workflows first-class async runs with durable status, Fleet visibility, stop controls, child parentage, and persisted results.
- [PR #751](https://github.com/nicobailon/pi-subagents/pull/751) removed public `tasks[]`, `chain[]`, static parallel controls, `/chain`, `/parallel`, and `/run-chain`.
- A further change integrated managed worktrees at the workflow and child levels.

The release therefore did more than add another optional syntax. It replaced the public multi-agent orchestration interface.

At the same time, it retained the existing execution substrate:

- Agent discovery.
- Model and tool resolution.
- Fresh or forked context.
- Child processes.
- Acceptance handling.
- Artifacts.
- Status and control.
- Worktree capture.
- Watchdog and permission behavior.

The new layer orchestrates those capabilities rather than rebuilding them.

### `v0.42.0`: “real child output” became reliable

[`v0.42.0`](https://github.com/nicobailon/pi-subagents/releases/tag/v0.42.0) is directly relevant to the tweet’s phrasing.

In `v0.41.0`, grouped intercom delivery could replace a child’s actual return with a stub such as `Trace: 8 event(s)`. That made output-dependent workflows unreliable: a script could launch children, but downstream decisions might not receive their real findings. [Issue #846](https://github.com/nicobailon/pi-subagents/issues/846) documents this failure.

`v0.42.0` fixed the result channel so `runs.run(...).output` retained the real child output after grouped delivery. It also added an integration test that:

1. Builds a target list dynamically.
2. Fans out with `targets.map(...)` and `runs.all`.
3. Waits for all parallel children.
4. Starts a sequential join child.
5. Starts another child with a per-child worktree override.
6. Verifies separate worktree patches and handoff manifests.

This is the closest released evidence for the tweet’s exact claim.

### `v0.42.1`: contract stabilization

[`v0.42.1`](https://github.com/nicobailon/pi-subagents/releases/tag/v0.42.1) fixed two workflow contract mismatches:

- Async workflows had inadvertently inherited the 30-minute foreground timeout. They now have no implicit timeout.
- `chatProgress` advertised modes that had no implementation. The public set is now limited to `auto`, `off`, and `live-card`.

It also fixed a narrow-terminal rendering crash.

### Post-tag `main`: workflow-only public execution

After the `v0.42.1` tag, [PR #863](https://github.com/nicobailon/pi-subagents/pull/863) made `workflowScript` the only public execution surface, including single-child and scheduled runs.

It also added automatic return behavior for a single-expression script:

```js
{
  workflowScript: `runs.run("main", {
    agent: "scout",
    task: "Analyze the target"
  })`
}
```

The wording added to the tool description explicitly advertises ordinary loops, branches, awaits, arrays, and dynamically mixed sequential and parallel phases. That language closely matches the tweet and explains why the announcement is not represented by a similarly named release-note entry: the implementation accumulated across `v0.41`–`v0.42.1`, while the final public-interface hard cut remains unreleased.

## 3. Is this a substantial change?

Yes, with an important qualification.

It is substantial as a public orchestration interface:

- A growing declarative schema was replaced by ordinary program control flow.
- Workflows can respond to actual child results.
- Static and dynamic fan-out use the same primitive.
- Sequential and parallel phases can be interleaved freely.
- Failures can be interpreted differently per flow.
- Stable child identities become part of the normal model.
- Legacy orchestration commands and parameters were removed.
- The same interface is becoming mandatory even for one child.

It is less substantial as an execution-engine rewrite:

- Children still run through the ordinary executor.
- Existing artifact, status, model, permission, and worktree machinery remains authoritative.
- `workflowScript` is a constrained controller, not a general Node environment.
- Worktree changes are captured as patches and handoff manifests; they are not automatically merged into the parent or made visible to later children.

The right characterization is:

> pi-subagents has replaced its orchestration control plane while preserving most of its child-execution substrate.

## 4. Perk’s current subagent architecture

Perk uses pi-subagents as a borrowed delegation engine while shipping its own `perk.*` agent definitions. Built-in pi-subagents agents are disabled in Perk-managed repositories.

The current roles fall into three shapes.

### 4.1 Dependent single-child calls

- `perk.review-classifier` for `/address`.
- `perk.objective-explorer` for optional objective-plan exploration.
- `perk.conflict-resolver` for merge-conflict resolution.

The parent depends on the child’s result before it can continue.

### 4.2 Report-only fan-out

- `perk.pr-reviewer`: two or three fresh-context reviewers, one angle each.
- `perk.learn-analyst`: two to four fresh-context analysts, one angle each.

The children report; the parent reconciles and performs one mutation.

These are the strongest candidates for code-first orchestration.

### 4.3 Live, human-triaged fan-out

- `perk.adversarial-reviewer` for `/pr-review-terminal`.
- `perk.adversarial-reviewer` for `/pr-review-browser`.

These flows send provisional findings through `contact_supervisor`. The parent incrementally relays them into a live human interface while holding a timed `wait` loop open.

These flows can improve their launch and completion mechanics, but the parent’s live relay loop remains essential.

## 5. Problems in the current Perk shape

### 5.1 The model owns too much orchestration mechanics

The `/pr-review` guidance currently tells the model to spawn two or three reviewers in parallel, repeat model overrides, collect fenced blocks, and reconcile returned strings ([prompt](/Users/mattgiles/dev/github/mattgiles/perk/prompts/stages/pr-review.md:1)).

`/learn` repeats the same mechanics with a different agent, angle vocabulary, result shape, and failure policy ([prompt](/Users/mattgiles/dev/github/mattgiles/perk/prompts/stages/learn-orchestrate.md:1)).

The parent must know:

- Which agent to use.
- How many children are allowed.
- Which context mode applies.
- How to repeat model overrides.
- How to represent parallelism.
- How to identify results.
- How to extract fenced JSON.
- What a malformed report means.
- Whether one failure invalidates the whole wave.
- Which fields are mechanically derived.
- Which decisions remain judgment.

That is a large interface for a relatively repetitive implementation.

### 5.2 Structured data is carried through prose conventions

Several agents return:

1. A short human-readable summary.
2. A fenced JSON block with an exact shape.

Examples include:

- `perk.review-classifier`.
- `perk.objective-explorer`.
- `perk.pr-reviewer`.
- `perk.learn-analyst`.

pi-subagents now supports `outputSchema` and exposes validated `structuredOutput` on child results. Continuing to scrape fenced JSON leaves reliability on the table.

### 5.3 Tests verify vocabulary, not orchestration behavior

The `/pr-review` tests assert that the rendered guidance mentions:

- The agent name.
- Fresh context.
- “2–3.”
- The word “parallel.”

They do not prove:

- One workflow owns the wave.
- Keys are stable.
- Every child receives the configured model.
- Reports satisfy a schema.
- Partial failures are handled correctly.
- A missing required angle blocks a clean verdict.
- Result ordering cannot change semantics.

See [prReview.test.ts](/Users/mattgiles/dev/github/mattgiles/perk/extension/doors/prReview.test.ts:13).

### 5.4 Contracts already drift from the installed extension

Perk’s contract still specifies a `tasks` array for the human-triaged review fan-out ([contracts.md](/Users/mattgiles/dev/github/mattgiles/perk/shared/contracts.md:884)), even though pi-subagents removed that public surface in `v0.41.0`.

The learned subagent documentation carries the same stale shape ([subagents.md](/Users/mattgiles/dev/github/mattgiles/perk/docs/learned/pi/subagents.md:318)).

### 5.5 The dependency seam is weak

Perk references unversioned `npm:pi-subagents`; the currently materialized package is `0.42.0`, while the latest release is `0.42.1`.

That is risky because Perk relies on detailed behavior:

- Tool fields.
- Agent discovery.
- Model propagation.
- Intercom semantics.
- Result delivery.
- Wait behavior.
- Worktree artifacts.
- Supervisor-channel timing.

Leaning more heavily on the extension should be accompanied by a stronger compatibility posture.

## 6. The principal opportunity: typed report waves

The repeated domain concept is not “parallel tasks.” It is a **report wave**:

> Run a bounded set of fresh-context, report-only children; collect typed outcomes under stable domain keys; apply a flow-specific completeness policy; return one compact result for parent judgment.

A report wave should handle:

- Stable lane keys.
- Agent identity.
- Context defaults.
- Model defaults.
- Output schemas.
- Status labels.
- Parallel launch.
- All-settled collection.
- Failure normalization.
- Usage aggregation.
- Completeness calculation.
- Compact return projection.

It should not handle:

- Deduplicating semantically overlapping findings.
- Deciding whether a learning is durable.
- Selecting the final learning classification.
- Posting a GitHub review.
- Resolving review threads.
- Capturing a learning.
- Making product or architectural decisions.

Those remain parent responsibilities.

### Proposed result interface

```ts
type ReportWaveResult<T> = {
  complete: boolean;
  reports: Array<{
    key: string;
    report: T;
  }>;
  failures: Array<{
    key: string;
    error: string;
  }>;
};
```

The `complete` interpretation is flow-specific:

- `/pr-review`: `true` only when every required selected angle produced a schema-valid report.
- `/learn`: successful reports remain useful; failures are explicitly recorded as skipped angles.
- Human-triaged review: partial reports can still be shown, but completion cannot be represented as full coverage.

## 7. Child-selected review angles

Child-selected review angles are worth adopting, provided the selection is bounded and treated as delegated analysis rather than delegated authority.

### 7.1 Why child selection may be better than parent selection

The parent currently chooses extra angles based on “the nature of the change.” But Perk intentionally keeps the raw PR diff out of the parent session to reduce context pollution and avoid bias.

That creates tension:

- The parent owns angle selection.
- The parent may know what it implemented.
- That knowledge is precisely what fresh review tries not to trust.
- The cleanest view of the actual PR lives in a fresh child.

A fresh selector child can inspect the PR, plan, and changed surfaces without inheriting the implementation session’s rationale. It may therefore choose more relevant review coverage.

Examples:

- A docs-and-contract-only PR should favor quality/docs accuracy over tests.
- A parser or state-machine change should favor correctness and tests.
- An authentication, permissions, or shell-execution change should favor correctness/security.
- A test-harness-only PR may need tests/validation and quality rather than product correctness.
- A sweeping refactor may need correctness plus quality even if test files are abundant.

### 7.2 Recommended orchestration shape

The selector should run concurrently with the mandatory plan-fidelity reviewer:

```js
const planFidelity = runs.run("plan-fidelity", {
  agent: "perk.pr-reviewer",
  task: "angle: plan-fidelity ..."
});

const selection = await runs.run("angle-selector", {
  agent: "perk.review-angle-selector",
  task: "Classify the PR and select additional review angles ..."
});

const selected = normalizeSelection(selection.structuredOutput);

const additional = await runs.all(selected.map(angle => ({
  key: angle,
  agent: "perk.pr-reviewer",
  task: "angle: " + angle + " ..."
})));

return {
  selection: selection.structuredOutput,
  reports: [
    (await planFidelity).structuredOutput,
    ...additional.map(result => result.structuredOutput)
  ]
};
```

This uses the new execution model meaningfully:

- The mandatory reviewer begins immediately.
- Angle selection happens independently.
- The second phase is data-dependent.
- Additional reviewers fan out dynamically.
- All results return in one workflow value.

The selector adds one model call but does not necessarily add its entire duration to the critical path because plan-fidelity runs concurrently.

### 7.3 The selector’s interface

A dedicated selector agent is cleaner than overloading `perk.pr-reviewer` with a second operating mode.

Suggested structured result:

```json
{
  "change_profile": {
    "product_logic": true,
    "tests": true,
    "docs_contracts": false,
    "security_sensitive": false,
    "configuration_or_packaging": true,
    "cross_plane": true
  },
  "selected_angles": ["correctness", "tests"],
  "risk_flags": [
    "shared behavior changed across Python and TypeScript"
  ],
  "rationale": {
    "correctness": "The change alters cross-plane state transitions.",
    "tests": "Both plane-specific suites must pin equivalent behavior."
  },
  "confidence": "high"
}
```

The selector recommends only the additional angles. `plan-fidelity` remains mandatory and is inserted by Perk.

### 7.4 Selection must be constrained by code

The workflow or Perk-owned orchestration module should enforce:

1. Only known angle slugs are accepted:
   - `correctness`
   - `tests`
   - `quality`

2. `plan-fidelity` is always present.

3. Total reviewers remain within the existing two-to-three cap.

4. At least one additional angle is selected.

5. Duplicate or unknown angles are removed.

6. Operator directives remain authoritative inputs:
   - A directive can force or strongly bias a valid angle.
   - It cannot remove plan-fidelity.
   - It cannot exceed the reviewer cap.

7. Selector failure uses a deterministic fallback:
   - Default: `correctness` and `tests`.
   - For an explicitly docs-only operator directive: `quality`, with a second default chosen according to the agreed policy.

8. Low-confidence selection can trigger the broader deterministic fallback.

9. Selection rationale is surfaced for observability but is not passed to the reviewers as truth. Reviewers fetch and inspect the PR independently.

### 7.5 Independence and bias controls

The selector should not synthesize findings or pre-argue the PR’s correctness. It should only classify change shape and choose coverage.

Review children should receive:

- Their assigned angle.
- Any operator directive relevant to that angle.
- The PR identity or normal active-PR resolution context.

They should not receive:

- The selector’s substantive interpretation of the change.
- Its conclusion about likely correctness.
- Other reviewers’ findings.
- The implementation session’s rationale.

This preserves the independence Perk values.

### 7.6 Parent ownership after child selection

Child-selected angles do alter the current “angle selection is parent judgment” rule. The revised principle should be more precise:

> Review coverage selection may be delegated to a fresh, bounded selector because it is reversible analytical routing. Review reconciliation, finding acceptance, external posting, and next-step authority remain with the parent.

This is compatible with Perk’s broader rule that children can produce evidence and classifications while the parent acts.

## 8. Flow-by-flow recommendations

### 8.1 `/pr-review`: highest-value first adoption

Recommended design:

1. Start mandatory plan-fidelity and the selector concurrently.
2. Validate and constrain selected angles.
3. Launch selected additional reviewers through `runs.all`.
4. Require `outputSchema` for every reviewer.
5. Return one typed aggregate.
6. Mark the wave incomplete if any selected reviewer fails.
7. Let the parent reconcile and call `post_pr_review`.

Use `async: false` because the parent must immediately consume the reports before it can post.

Primary gains:

- Better angle relevance.
- No fenced-JSON scraping.
- No accidental sequential reviewer calls.
- One stable run identity.
- Explicit coverage completeness.
- Lower parent transcript volume.
- Easier eventual promotion to a headless stage.

### 8.2 `/learn`: second adoption

Recommended design:

1. Parent or existing deterministic branch chooses the angle set.
2. Launch the selected analysts in one `runs.all`.
3. Require schema-valid structured reports.
4. Return successful reports plus explicit failures.
5. Preserve the existing rule that malformed or missing reports become skipped angles.
6. Parent performs semantic deduplication and chooses the primary classified decision.

Child-selected learn angles are less compelling because the evidence-gather phase already has deterministic knowledge of available sources. They could be considered later, but `/pr-review` is the stronger adaptive-routing use case.

Use `async: false` for the ordinary warm pass because the parent immediately reconciles and captures.

### 8.3 `/pr-review-terminal` and `/pr-review-browser`

Convert the removed `tasks[]` launch to one async `workflowScript` using:

- Stable angle keys.
- `runs.all`.
- Explicit `phase` and `label`.
- All-settled final outcomes.
- Structured final reports.

Retain:

- Child `contact_supervisor` progress messages.
- The parent’s timed `wait` loop.
- The in-conversation path-and-line ledger.
- Incremental pushes to hunk or plannotator.
- Human-owned triage.
- Parent-owned final posting.

The script must not receive the UI handle or attempt to call UI tools. That knowledge remains isolated in the parent.

Child-selected angles could also be used here, with `claimed-intent` replacing `plan-fidelity` as the mandatory angle where the current contract requires it.

### 8.4 `/address`

The immediate gain is smaller because it uses one classifier child.

Still worthwhile:

- Move to a single-expression `workflowScript` for upcoming compatibility.
- Pass an `outputSchema`.
- Return only the compact classification object.
- Render a human table in the parent if desired rather than requiring double delivery from the child.

The parent continues to edit and resolve threads.

### 8.5 Objective-plan exploration

A single-expression workflow is sufficient for the current optional explorer.

A later enhancement could use adaptive exploration for large objective nodes:

1. One topology child identifies distinct code surfaces.
2. A bounded fan-out explores those surfaces independently.
3. One compact aggregate returns files, symbols, anchors, and open questions.

This should remain optional. Parallel exploration is useful only when the node genuinely spans separable surfaces.

### 8.6 Conflict resolution

Do not use managed worktree isolation. The resolver must operate on and push the actual PR branch.

Potential improvements:

- Return a structured receipt containing base, rebase outcome, conflicted files, verification commands, resulting commit, and push status.
- Make `/submit` verify that receipt only as evidence, then independently re-check mergeability.
- Consider a future read-only post-rebase validator before accepting success.

The current one-child flow does not otherwise benefit much from dynamic orchestration.

### 8.7 Implementation writers

Perk should not initially adopt parallel worktree writers.

Reasons:

- Current conventions deliberately keep durable writes and integration judgment with the parent.
- pi-subagents captures worktree patches but does not merge them automatically.
- Multiple patches create integration and ordering decisions.
- Perk plan steps and the implement session's todo-checklist discipline assume a coherent
  implementation thread.
- Independent child success does not prove aggregate correctness.

A future narrowly bounded implementation experiment might be justified, but it should not be bundled into the report-wave adoption.

## 9. Target Perk architecture

### 9.1 A deep report-wave module

The long-term design should be a Perk-owned module with a small interface, not repeated generated JavaScript embedded across prompts.

Possible external interface:

```ts
gatherPrReviewReports({
  directive?: string;
}): Promise<PrReviewWaveResult>;

gatherLearnReports({
  manifestPath: string;
  bundleDir: string;
}): Promise<LearnWaveResult>;
```

The caller should not need to know:

- pi-subagents agent-discovery rules.
- `workflowScript` syntax.
- Stable-key validation.
- Context propagation.
- Model override placement.
- `outputSchema` mechanics.
- Artifact paths.
- Result normalization.
- Failure collection.
- Selector fallback rules.
- Usage aggregation.

Those belong in the implementation.

Internally, both entrypoints may share:

```ts
wave.run(request)
```

But a generic `subagent_wave` model tool should be avoided. It would merely expose pi-subagents vocabulary through a second, shallow interface.

> **Update (Objective #2130, Node 2.1):** realized as the opaque `ReportWave` lifecycle
> (`start`/`collect`/`run` in `extension/waves/reportWave.ts`): flow entrypoints take a
> `ReportWave` and call `wave.run`/`wave.start`; the delegation port (`WaveAdapter`) is
> waves-interior behind `createReportWave`'s per-launch adapter supply.

### 9.2 Adapter strategy

pi-subagents is a true external dependency, so Perk should define an internal port at the seam.

Production options:

1. Initially render and launch a tested `workflowScript`.
2. Longer-term use the official [`pi-subagents/delegation`](https://github.com/nicobailon/pi-subagents/blob/main/docs/extension-api.md#structured-delegation-api) interface for correlated foreground leaves and perform orchestration in Perk’s TypeScript.
3. Use the async RPC workflow surface only where a durable async run is actually needed.

Test adapter:

- In-memory results keyed by logical lane.
- Configurable delay and completion ordering.
- Structured success.
- Plain failure.
- Malformed structured result.
- Duplicate or unknown selector angles.
- Missing required lane.
- Partial wave completion.

This creates a real seam: production external adapter plus an in-memory test adapter.

### 9.3 Why programmatic orchestration is deeper than prompt scripting

Inline `workflowScript` is a valuable dogfood step, but if the parent model writes the script each time, important policies remain guidance:

- It may choose unstable keys.
- Forget a schema.
- Misapply a model override.
- Return excessive output.
- Treat failures incorrectly.
- Omit the mandatory angle.
- Post clean after incomplete coverage.

A Perk-owned module converts those policies into implementation. The parent supplies only judgment-bearing inputs, such as an operator directive.

## 10. Compatibility and safety work required first

### 10.1 Establish a tested upstream version

Perk should either:

- Pin a tested pi-subagents release, or
- Declare a supported minimum/range and verify capabilities at runtime.

Given the project’s reliance on detailed pre-1.0 behavior, an exact tested version is the safer starting point.

At minimum, `perk doctor` should report:

- Installed pi-subagents version.
- Whether `workflowScript` is present.
- Whether child `outputSchema` reaches `structuredOutput`.
- Whether async `wait` and supervisor tools match the expected contract.
- Whether the installed version is older or newer than Perk’s tested range.

### 10.2 Update contracts and documentation

The same change should remove stale `tasks[]` language from:

- [shared/contracts.md](/Users/mattgiles/dev/github/mattgiles/perk/shared/contracts.md:884)
- [docs/learned/pi/subagents.md](/Users/mattgiles/dev/github/mattgiles/perk/docs/learned/pi/subagents.md:318)
- The terminal and browser review guidance.
- Any bundled Perk-expert reference that describes the affected surface.

Because this changes cross-plane behavior and user-visible orchestration, the repo conventions require contract and user-doc updates in the same turn.

### 10.3 Consider stage-aware capability ceilings

pi-subagents exposes [capability ceilings](https://github.com/nicobailon/pi-subagents/blob/main/docs/extension-api.md#capability-ceilings) that can restrict launchable agents and child tools.

Potential policies:

- Objective planning: `perk.objective-explorer` only.
- Address: `perk.review-classifier` only.
- Automated PR review: `perk.review-angle-selector` and `perk.pr-reviewer`.
- Learn: `perk.learn-analyst` only.
- Conflict resolution: `perk.conflict-resolver` only.
- Human review: `perk.adversarial-reviewer` only.

This would replace some prompt-only discipline with runtime enforcement. It should be introduced carefully because Perk currently accepts broader ad hoc parent delegation.

## 11. Testing strategy

Tests should move from prose assertions to the module interface.

### Selector tests

- Always inserts plan-fidelity.
- Accepts only allowed additional angles.
- Enforces the two-to-three reviewer range.
- Honors a valid operator-forced angle.
- Rejects unknown selector output.
- Deduplicates repeated angles.
- Uses deterministic fallback on selector failure.
- Uses fallback on low confidence if that policy is adopted.
- Does not pass selector conclusions into reviewer tasks.

### Review-wave tests

- Starts plan-fidelity concurrently with selection.
- Starts selected additional reviewers only after selection.
- Applies fresh context and configured model to every lane.
- Preserves stable keys regardless of completion order.
- Requires schema-valid reports.
- Marks missing selected reviewers as incomplete.
- Never permits `complete: true` after a required failure.
- Returns compact reports without raw child transcripts.
- Records usage and artifacts without exposing them as judgment inputs.

### Learn-wave tests

- Launches all selected angles.
- Continues after one analyst failure.
- Reports failed angles explicitly.
- Preserves successful reports.
- Leaves semantic deduplication and primary classification to the parent.

### Adapter contract tests

- The production adapter correctly translates the Perk wave specification to the supported pi-subagents interface.
- Upstream result shapes normalize into the Perk result.
- Unsupported installed versions fail clearly.
- Cancellation and timeout produce explicit incomplete outcomes.

## 12. Suggested rollout

### Slice 0: converge on current upstream

- Upgrade the materialized extension to `0.42.1`.
- Decide version-pin or supported-range policy.
- Update stale contracts and learned docs.
- Add a doctor compatibility check.

### Slice 1: typed `/pr-review` workflow with existing parent-selected angles

- Use one foreground workflow.
- Add stable keys and labels.
- Add child `outputSchema`.
- Return a compact typed aggregate.
- Encode “required angle failure means incomplete.”
- Keep angle selection parent-owned for this first dogfood slice.

This isolates the mechanics change from the selection-policy change.

### Slice 2: bounded child-selected review angles

- Add `perk.review-angle-selector`.
- Start it concurrently with plan-fidelity.
- Validate its structured result.
- Enforce the allowlist, cap, operator directive, and fallback.
- Measure review relevance and latency.

### Slice 3: migrate `/learn`

- Reuse the report-wave implementation.
- Apply best-effort completeness semantics.
- Remove fenced-JSON parsing.
- Preserve parent classification and capture.

### Slice 4: migrate terminal/browser launches

- Replace stale `tasks[]` fan-out with one async workflow.
- Preserve supervisor streaming and parent UI relay.
- Add stable keys and structured final reports.
- Consider bounded child-selected angles with `claimed-intent` mandatory.

### Slice 5: deepen the module

- Move tested workflow mechanics behind the Perk-owned report-wave interface.
- Introduce the production pi-subagents adapter and in-memory test adapter.
- Delete redundant prose-mechanics tests once interface-level coverage exists.
- Reassess whether `/pr-review` can become a headless `DriveStage`.

## 13. Expected gains

If implemented as a deep Perk module rather than prompt syntax alone, this shift should provide:

### Reliability

- Schema-valid child reports.
- Explicit partial failure.
- No accidental clean verdict after incomplete coverage.
- Stable result identities.
- Less dependence on fenced-text parsing.

### Review quality

- Angles chosen from the actual change rather than the implementation session’s recollection.
- Mandatory plan-fidelity coverage preserved.
- Operator focus retained.
- Better specialization for docs, tests, security, configuration, and cross-plane changes.

### Context efficiency

- One compact workflow result enters the parent context.
- Raw diffs remain in fresh children.
- Repeated prose tables and JSON blocks can be removed.
- Trace and artifacts remain available without dominating the model-visible response.

### Observability

- One top-level workflow run.
- Named phases and stable lane keys.
- Per-lane model, effort, duration, and usage.
- Clear distinction between incomplete execution and clean findings.

### Testability

- Failure policy can be tested without an LLM.
- Selector normalization becomes pure code.
- External pi-subagents behavior is isolated behind an adapter.
- Tests exercise observable wave outcomes rather than prompt wording.

### Architectural locality

- Upstream invocation changes are handled once.
- Model propagation is implemented once.
- Schemas live in one authoritative location.
- Completeness rules live next to the flow that owns them.
- Prompts focus on judgment instead of launch plumbing.

## Recommendation

Perk should lean into pi-subagents’ code-first direction, beginning with `/pr-review`.

The recommended target is:

1. A fresh mandatory plan-fidelity reviewer begins immediately.
2. A fresh selector child concurrently classifies the change and chooses bounded additional angles.
3. Perk validates and constrains that selection.
4. Selected reviewers fan out with structured outputs.
5. The wave returns one typed completeness-and-reports object.
6. The parent reconciles, judges, and posts exactly once.

This uses code mode for what it is genuinely good at—controlled sequence, fan-out, output-dependent branching, and aggregation—without transferring authority or product judgment into the workflow script.

The deeper end state should be a Perk-owned report-wave module with a small interface and a pi-subagents adapter. That is where the architectural shift becomes durable leverage rather than merely a new syntax for the same prompt-driven orchestration.
