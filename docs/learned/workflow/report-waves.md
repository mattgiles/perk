---
title: The report-wave module — flow migrations onto code-owned waves, lane semantics, and the wave test machinery
read_when: You are touching extension/waves/, migrating flow prompt mechanics onto a code-owned wave tool, debugging lane coverage or wave guard state, or writing wave tests.
---

# The report-wave module

perk's multi-lane subagent fan-outs (review waves, learn-analyst waves) run as **code** on the
Perk-owned report-wave module in `extension/waves/`, launched over the pi-subagents v1 extension
RPC. This doc is the perk-side architecture: the module's shape, the checklist for migrating a
flow's prompt mechanics onto a code-owned wave tool, the lane-normalization semantics, the
session-scoped guard-state patterns, and the wave test machinery worth reusing.

**Doc boundary:** the *upstream* pi-subagents mechanics — the v1 RPC envelope, `outputSchema` /
`structured_output`, the supervisor channel, `mission: false`, `subagent_wait` — live in
`docs/learned/pi/subagents.md`. Cross-link them; don't duplicate them here.

## Orientation

`extension/waves/reportWave.ts` is the operational core. The blocking runner
(`runReportWave`/`runWaveScript`) is re-expressed as start + await over the **start/settle split**
(`startWaveScript`/`startReportWave`). `rpcAdapter.ts` is the live pi-subagents v1 RPC adapter;
`memoryAdapter.ts` is the first-class test double. The flow entrypoints:

- `prReviewWave.ts` — `/pr-review`'s bounded-retry wave behind the `run_pr_review_wave` tool.
- `learnWave.ts` — `/learn`'s analyst fan-out behind `run_learn_wave` (best-effort, no retry).
- `prReviewDynamicWave.ts` — the experimental selector-driven wave behind
  `run_pr_review_dynamic_wave`.
- `adversarialReviewWave.ts` — the human review doors' streaming wave behind the
  `start_review_wave`/`collect_review_wave` tool pair (`extension/doors/reviewWaveTools.ts`),
  registered and in the `extension/substrate/toolGating.ts` census. It landed **dormant** first
  (built + tested, unregistered) because registration, the agent-def fenced-JSON →
  `structured_output` flip, and the census additions had to land **atomically** — registering
  early would have broken lane schemas against the fenced-JSON agent def.

## The start/settle split

`start*` returns a handle plus a `result` promise that **never rejects** — every arm normalizes —
so a detached/uncollected run can never become an unhandled rejection. The blocking form is start
+ await result: ONE operational core, applied at two levels (script: `startWaveScript`; lane:
`startReportWave`). Discipline details: the completion subscription is released exactly on settle;
pre-spawn failures unsubscribe immediately and return the same failure/receipt values the blocking
runner reported.

Because the refactor moved the runner body verbatim, the pre-existing blocking-runner matrices pin
the re-expression equivalence **for free** — refactor-parity proof by untouched test matrices.
When a refactor moves a runner body verbatim, the untouched pre-existing matrix passing *is* the
parity evidence; lean on it rather than re-arguing the invariants.

## The flow-migration checklist (prompt mechanics → module-owned tool)

The `/pr-review` migration is the template. Moving model-authored `workflowScript` mechanics into
a flow-scoped tool predictably touches:

- **The guidance template shrinks to judgment-only prose + the tool name.** The template var set
  shrinks, so `prompts/_fixtures/live.yaml` and the `stageTools.test.ts` drive entry ride along.
- **The schema constant relocates into the wave module.** Check the import graph first — for
  `/pr-review` it was a two-file move.
- **Test pins split three ways:** mechanics pins move to the wave suite (memory-adapter-driven);
  judgment-prose pins stay on the guidance; and an interface-level harness e2e replaces the
  deleted rendered-mechanics pins — plus *negative* pins that `workflowScript`/`runs.all`/
  `outputSchema` no longer appear in the guidance.
- **Name the `extension/substrate/toolGating.ts` lockstep explicitly** (`PERK_TOOLS` + the
  worktree-stage family). Two consecutive flow plans missed it; the `stageTools.test.ts`
  drive-coverage guard forces it the moment the guidance names the tool, but catching it at plan
  time avoids the late scramble commit (see also `warm-door-commands.md`).

Two adjacent lessons:

- **Retiring prompt discipline into code surfaces latent underspecification** rather than merely
  transcribing it — the annotation-push module had to *strengthen* semantics the browser-review
  curl cheat sheet never confronted (see `plan-review-flow.md`).
- **When a mechanics module is scheduled to delete interim guidance prose, keep that prose
  minimal** and spend the design effort on the conventions the module will inherit. What survived
  into `learnWave.ts` were the contract-ish decisions — angle-slug keys, the compact per-lane
  projection, all-settled semantics; the prose skeletons did not.

## Lane semantics — status ≠ validity ≠ coverage

The normalization distinction lives at the `lane-failed` / `malformed-report` reason comments in
`reportWave.ts`: `ok: true` with a `null` report is `lane-failed` (structured output never
validated — the engine populates `structuredOutput` only on schema-valid lanes), while a
non-object/non-null report or a non-boolean `ok` is `malformed-report`. Flow code messaging
skipped lanes must not conflate them.

The broader rule (from the session-corpus audit): **a child's harness status is not report
validity is not wave coverage.** Validate the report artifact separately, retry a failed required
lane only within its bounded policy, and persist an uncovered lane rather than upgrading partial
coverage to clean.

Extra defensive arms worth keeping when extending the module: a pre-aborted `AbortSignal` cancels
before launch (no spawn issued); malformed async-complete payloads are dropped, never surfaced as
phantom completions; a `status.json` without a `state` field throws (`aggregate-unreadable`)
rather than being treated as terminal.

## Session-scoped guard state

Three related patterns keep wave state session-safe:

- **The guard-closure pattern.** Tool A records its outcome; sibling tool B refuses against it
  (`run_pr_review_wave` → `lastWave`; `post_pr_review` → `incomplete_coverage`); no-record ⇒ pass
  keeps B usable standalone. A cheap shape for mechanizing any "tool B must respect tool A's last
  outcome" invariant. The guard remembers only the *last* wave outcome (by design — a later
  complete wave resets it).
- **Sibling doors sharing a guard go module-scope with an exported recorder + per-registration
  reset** (`recordReviewWaveOutcome` in `extension/doors/prReview.ts` — the register function
  resets it because a fresh registration is a fresh session). The reset-on-register nuance is
  what keeps module-scope state session-safe.
- **`executionMode: "sequential"` is the concurrency guard** for one-pending-wave state (the
  `pending` slot in the review-wave pair) — the check-then-store is non-racy *only* because of
  it.
- **The collect-grace race idiom.** Collect races the pending `result` against a bounded,
  env-overridable grace to absorb the completion-event-vs-`subagent_wait` wake race; unsettled ⇒
  soft-fail with pending **retained**. No cancel surface is needed — the module timeout settles a
  stuck wave and a later collect drains it.

## Deliberate non-behaviors need regression pins

When a design decision is "we do NOT do X", write the test that fails if someone starts doing X.
Instances:

- The per-call tool `AbortSignal` is deliberately **not** threaded into the wave — the wave
  outlives the call; the module-owned timeout is the orphan insurance. Pinned by a
  registered-tool call with an *already-aborted* signal that must still launch and stay
  collectable.
- `executionMode: "sequential"` is load-bearing — declaring it on the tool def isn't enough; the
  registration test asserts it.

## Test machinery (reuse, don't rebuild)

- **The memory adapter needs imperative delivery hooks, not just declarative config**, because it
  must pass the shared adapter-contract suite (`adapterContract.test.ts`'s harness seam). Those
  hooks are contract-suite plumbing, safe to use in flow tests too. Its per-spawn aggregates FIFO
  (keyed by `asyncDir`) supports multi-wave retry tests additively — grow the first-class double
  with additive knobs instead of writing bespoke mocks.
- **Delivery ordering rides a macrotask** — see the comment at the `setTimeout(..., 0)` site in
  `memoryAdapter.ts` (a microtask would still beat the awaiting continuation, silently converting
  the default ordering arm into the race arm).
- **The fake pi-subagents RPC responder on `pi.events`** (`extension/doors/prReview.test.ts`)
  answers `ping`/`spawn` with the v1 envelope, writes a terminal `status.json` into a mkdtemp
  `asyncDir`, emits the completion event, and sinks spawn params — the offline e2e pattern for
  any RPC-launched wave.
- **The render-then-execute pattern** for dynamic in-script logic
  (`prReviewDynamicWave.test.ts`, `prReviewDynamic.test.ts`): the module renders deterministic JS
  (all dynamic data `JSON.stringify`-embedded); unit tests execute the rendered script via the
  `AsyncFunction` constructor over a scripted fake `runs` global; and the e2e responder
  *evaluates* the received script and writes its actual return into `status.json` — a full
  offline render→execute→aggregate round-trip. Reach for this over string-pins whenever a
  rendered script carries branching logic.
- **Dormant (unregistered) tools get end-to-end coverage via the harness's `extraExtensions`
  hook** — real-session runs with the dormant tools registered, without wiring them live.
- **Pin the glue, not just the seams.** Config parse pinned + spawn param pinned still misses the
  tool-execute threading between them — have the fake responder sink spawn params so an e2e
  asserts the configured model/tasks reach the real spawn. "Both sides tested" ≠ "the boundary
  tested."
- **Reviewing dormant code *as if live* is validated** — the multi-angle review wave caught the
  missing network-failure test on a dormant module.

## Watch items / residuals

- Three suites parse the module-rendered script by slicing between `runs.all(` and `);\nreturn` —
  a renderer output-shape change breaks them loudly but widely (consider a shared parse helper at
  a fourth consumer).
- The dynamic flow and the review-wave pair have not yet run against real pi-subagents —
  the stale-session gotcha: a landing session predates its own extension code (see
  `pi/extension-api.md` on dogfooding just-changed extension code).
- `pr`/`worktree`/`bundle_dir` stay model-relayed (an accepted trust posture;
  `decodeStartReviewWaveParams` is the single seam to adjust if door-recorded context is
  adopted).
- pi-subagents is pinned (0.45.0 at capture); the doctor `subagent-compat` probes are the drift
  tripwire — re-verify the adapter on any bump.
- The pre-digest recipe for foreign-seam nodes (read the unimportable dependency's source at plan
  time, pin the envelope as module constants, keep unversioned names advertised-not-pinned) is
  recorded in `pi/subagents.md` — cross-link, don't restate.

## Cross-references

- `docs/learned/pi/subagents.md` — the upstream pi-subagents mechanics (RPC envelope,
  `outputSchema`, supervisor channel) and the pre-digest recipe
- `docs/learned/workflow/warm-door-commands.md` — the toolGating census + drive-coverage guard
- `docs/learned/workflow/learn-evidence-pipeline.md` — the `/learn` orchestrator that rides
  `learnWave.ts`
- `docs/learned/workflow/plan-review-flow.md` — the annotation-push module (the sibling
  prompt-discipline-into-code migration)
- `extension/waves/reportWave.ts` (+ `rpcAdapter.ts`, `memoryAdapter.ts`) — the operational core
  and its adapters
- `extension/waves/prReviewWave.ts`, `learnWave.ts`, `prReviewDynamicWave.ts`,
  `adversarialReviewWave.ts` — the flow entrypoints
- `extension/doors/reviewWaveTools.ts` — the start/collect tool pair (live — the review doors
  drive it)
