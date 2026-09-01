---
title: The report-wave module — flow migrations onto code-owned waves, lane semantics, and the wave test machinery
read_when: You are changing extension/waves, review-wave identity/launch manifests, single-use post state, Ponytail coverage, flow migrations, lane semantics, or wave tests.
cluster: subagent-orchestration
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

## Distillation

- Wave mechanics are CODE, module-owned: `reportWave.ts` is the core; the per-flow entrypoints
  and their tools/postures are catalogued in "Orientation" (upstream pi-subagents mechanics live
  in `pi/subagents.md`, not here).
- Every wave spawn carries the fixed contract incl. the explicit acceptance disable
  (`acceptance: {level: "none"}`) — "The fixed spawn contract carries an explicit acceptance
  disable".
- Blocking runs are re-expressed as start + await — "The start/settle split".
- Migrating a flow's prompt mechanics onto a code-owned wave tool follows the checklist — "The
  flow-migration checklist (prompt mechanics → module-owned tool)".
- Lane semantics: status ≠ validity ≠ coverage — a lane can complete with an invalid report, and
  coverage is per-angle — "Lane semantics — status ≠ validity ≠ coverage".
- Size-budgeted renderers emit splittable per-line blocks (join-equivalent when unsplit);
  oversize-unreachability claims are cap arithmetic — "Budgeted block-packing renderers".
- Review posting uses one shared discriminated single-use state across static/dynamic doors, bound
  to one resolved PR and consumed only after successful mutation — "Session-scoped guard state".
- Launch manifests preserve requested/runnable/preflight-failed lanes and required Ponytail
  coverage, so instability becomes honest incompleteness — "Session-scoped guard state".
- "Watch items / residuals" is the flagged-edges register — check it before extending the
  module.

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
- `draftReviewWave.ts` — the draft doors' (`/plan-review-browser`,
  `/objective-review-browser`) streaming wave behind the
  `start_draft_review_wave`/`collect_draft_review_wave` tool pair
  (`extension/doors/draftReviewWaveTools.ts`), registered and census'd.
- `reviewClassifierWave.ts` — `/address`'s single-lane classify wave behind the
  `classify_review_feedback` tool (`extension/doors/address.ts`): ONE `perk.review-classifier`
  lane, strict completeness, no retry (the flow's posture is "surface the error and stop").
- `objectiveExplorerWave.ts` — the objective-plan factory's OPTIONAL single-lane explore wave
  behind `explore_objective_node` (`extension/pi/v1/objectivePlanning.ts`): ONE
  `perk.objective-explorer` lane, strict completeness, no retry (on failure the guidance says
  "explore directly instead"). Both single-lane entrypoints hold their report schema as a module
  constant — the migration that killed the hand-transcribed `outputSchema` blocks.
- `auditWave.ts` — the perk-dev session-audit wave behind `run_audit_wave`
  (`extension/doors/auditWaveTools.ts`): the learnWave-shaped sibling with a **structural write
  binding**. The tool is a `READ_ONLY_TOOLS` member whose write target comes only from the cold
  door's workflow-state (`audit_bundle_dir`), with **no parameters** — no model-relayed path ⇒ no
  aimable writer. This is the precedent for read-only-gated tools that must write. Side effect
  worth sweeping for: adding an isolated registry stage (empty `successors`) implicitly grows
  GC's terminal set (`terminal_stage_ids()`), firing the exact-set pin in `tests/test_gc.py` — a
  stage-adding plan should sweep `src/perk/state/gc.py` alongside the
  stageTools/toolGating/registry pins.
- `harvestWave.ts` — the seeded `perk learn harvest` session's analyst fan-out behind the
  `run_harvest_wave` tool (`extension/doors/harvestWaveTools.ts`). The one `manifest_path` param
  is a **relay handshake, not an authority**: the execute derives the only acceptable run-scoped
  path from the claimed run's workflow-state and reads the derived path (contracts §8.48); a
  single-lane manifest is refused toward the seed's direct-analysis path. Best-effort
  completeness, ONE attempt, no retry; reports re-decoded + pointer-stamped in code.
- `dreamWave.ts` — the `perk learn dream` session's FIRST-level analyst wave: strict §8.59
  manifest decode that binds the run-scoped manifest path into the decoded value, run-key-safe
  orchestration keys (the `auditWave.ts` pattern), the `DREAM_ANALYST_CAPS` SSOT, and **strict**
  completeness (one failed/undecodable lane forces `complete: false`); one attempt, no retry
  (contracts §8.60).
- `dreamReducerWave.ts` — the SECOND-level wave: three FIXED fresh-context `perk.dream-reducer`
  lanes (`DREAM_REDUCER_ANGLES`) cross-examining the complete analyst outcome; **pure
  orchestration** — it composes/finalizes the bundle content while the door owns every fs write;
  the `DREAM_REDUCER_CAPS` SSOT; strict (contracts §8.61). Both dream levels run behind the ONE
  **parameterless** `run_dream_wave` tool (`extension/doors/dreamWaveTools.ts`) — the
  `run_audit_wave` workflow-state-bound posture on BOTH the read and write sides; reducers
  launch only after a complete first wave and an in-budget bundle write.

## The fixed spawn contract carries an explicit acceptance disable

Every wave spawn carries `acceptance: {level: "none", reason}` (`WAVE_ACCEPTANCE`, a fixed
`WaveSpawnParams` field — no per-lane/per-flow opt-out). Without it, pi-subagents (since 0.46.0)
auto-infers a generic acceptance contract for reviewer/analyst-named or read-only children and
injects a fenced `acceptance-report` completion instruction into every lane — a competing
completion contract observed steering a child into invalid `structured_output` attempts.
Delivery rides pi-subagents' workflow-defaults spread onto each lane child; `renderWaveScript`
is untouched (scripts stay byte-identical). The hazard details live in
`docs/learned/pi/subagents.md`; the doctor `subagent-compat` "explicit acceptance disable" probe
row is the drift tripwire.

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

Adjacent lessons:

- **Dormant landings cite the def+wave atomicity precedent up front** — the dormant-first →
  atomic-flip shape below is settled; plans should invoke it rather than re-derive it (#1999).
- **Agent-def prose precision is behavioral** — near-miss phrasing (an empty array vs explicit
  challenge rows) is a correctness bug, not a style nit (#1997).
- **Retiring prompt discipline into code surfaces latent underspecification** rather than merely
  transcribing it — the annotation-push module had to *strengthen* semantics the browser-review
  curl cheat sheet never confronted (see `plan-review-flow.md`).
- **When a mechanics module is scheduled to delete interim guidance prose, keep that prose
  minimal** and spend the design effort on the conventions the module will inherit. What survived
  into `learnWave.ts` were the contract-ish decisions — angle-slug keys, the compact per-lane
  projection, all-settled semantics; the prose skeletons did not.

### The dormant-first → atomic-flip migration is validated

The posture this doc prescribed worked in practice: the tool pair + annotation push landed
built/tested/**unregistered**, and the later flip changed registration, the agent-def completion
contract, the door prompts, the skills, and the tool census in one change — exactly because the
wave's `outputSchema` and the def's completion form must agree at every commit. De-dormanting was
mechanical: delete the DORMANT paragraphs, drop the tests' `extraExtensions` registration
workaround (the harness binds perk's extension, so live registration reaches it for free), and
flip census-absence pins to census-membership pins. Worth repeating for future risky wirings.

The companion prose rule: **a dormant def/module must not be described in present-tense "perk
does X" prose** — materialized substrate is not live behavior; qualify activation state until the
wiring lands.

## Shape parity is not contract parity (schema forward-binding)

When forward-binding a wave report schema to a downstream consumer's shape
(`DRAFT_REVIEW_REPORT_SCHEMA` → the plan-finding shape in `extension/doors/annotationPush.ts`),
matching keys/types is not enough — **trace representative *values* through the next decoder**.
The schema accepted whitespace-only `phrase` strings that plan-mode `push_annotations` rejects
*wholesale* (one bad anchor fails the batch), so an engine-valid report could fail the
feed-without-reshaping contract. The fix carries a `pattern` constraint on the string arm —
JSON Schema `pattern` applies only to string instances, so the required-nullable `null` arm still
passes — plus negative/positive semantic pins.

Corollary for agent-def prose: **prompt rules stated globally can be internally impossible.** A
def requiring both "wrap any quoted draft text in delimiters" and "emit a bare byte-exact anchor
field" holds two representations of quoted draft text to contradictory rules — state the
exception explicitly or the completion contract is unsatisfiable.

## Budgeted block-packing renderers

Rules for renderers that pack content into size-budgeted blocks (#1991, #2000, #1997):

- **Any block whose size scales with input cardinality must be splittable** — emit aggregates as
  per-line blocks sharing one group, byte-identical to the joined form when no split occurs
  (prove join-equivalence first; split behavior falls out).
- **"Structurally unreachable" oversize claims are arithmetic** over the admission caps on the
  largest JOINED block, verified with a cap-conformant adversarial fixture the unfixed code
  refuses.
- **Redundant projections in composed reports invite divergence** — derive from rows, don't
  re-project.
- **Cleanup side effects in injected-effect execute cores get typed fail arms + failure-path
  coverage**, even "can't-fail" removals.
- **Encode subset vocabularies in the type** (`Exclude<…>`), not runtime filtering; cross-plane
  string literals get a lockstep pin.

## Validate downstream identifier contracts at the render boundary, not only through test adapters

The first live audit wave failed **all 15 lanes** because the memory and fake-RPC adapters never
exercised pi-subagents' in-worker run-key validation — the rendered lane keys were legal to every
test double but rejected by the real engine. The lessons:

- **Opaque orchestration keys should be contract-safe bounded identifiers** — short, restricted
  alphabet, no semantic payload. Semantic pair identity (which session/which expectation a lane
  serves) belongs in code-owned metadata/labels, never encoded into the key itself.
- **Mirror the upstream contract with a producer/renderer guard**: validate the keys at the
  render boundary (where the module composes them), so a bad key fails offline in the suite
  rather than live in the worker.
- **But keep a live dogfood leg** — an upstream contract change can outrun the mirror; the guard
  proves conformance to the contract *as mirrored*, not to the live engine.
- **Canonical-form enforcement pairs with normalized containment** — the decoder refuses any doc
  path where `posix.normalize(path) !== path`, so byte-exact membership/dedup/self-target rules
  operate on canonical identities (aliases otherwise coexist as two corpus members) (#1999).
- **Bind the source path into the decoded artifact at decode time**
  (`decodeDreamManifest(raw, manifestPath)` stamps it) — one authority pairing the validated
  object with the file children read, never two independent params (#1999).
- **Runner failures translate to a flow-specific shape** (a semantic lane id or null) —
  orchestration keys appear only in detail fields (#1999).
- **Lane planners stay module-private** — assert composition by parsing the injected adapter's
  recorded spawn (#1999).

## A code-owned wave boundary needs contract-complete pins, not just happy-path fan-out tests

The post-review hardening list from the harvest-wave landing — the recurring gaps when a wave
boundary moves into code and the suite only pins the happy-path fan-out:

- **nested untrusted-manifest decoding** (every level of an untrusted input decoded, not just the
  outer envelope);
- **load-bearing `promptGuidelines` policy prose** (pinned, since children obey it);
- **cancellation at the glue boundary** (abort between phases, not just pre-launch);
- **schema/sanitizer shared cap constants** (one constant consumed by both, pinned so they can't
  drift apart);
- **the full report envelope consumed downstream** (e.g. `{ opportunities, omitted_count }`) —
  pin every field a consumer reads, not just the headline array.

## Heterogeneous lanes + the custom-lane trust posture

(The upstream per-item `outputSchema` mechanics live in `pi/subagents.md` — this is the
perk-side application.)

- Keep **ONE workflow-level report schema for fixed lanes** and render a conditional per-lane
  `outputSchema` override only for heterogeneous lanes — the override renders only when present,
  so the fixed-item pins stay byte-identical.
- The dynamic flow's **custom selector lane is a deliberate untrusted-text exception with a
  module-owned trust posture**: reserved-lane-key + kebab-slug validation; a
  whitespace-collapsed ≤300-char scope; ONE custom lane rendered through a fixed
  scope-definition-only template; the invariant that a non-null custom selection ⟺ the lane
  launched; custom-aware static retry via the per-lane schema; and fallback only when neither
  valid picks nor a valid custom arrived.
- Such an exception warrants an **explicit adversarial containment test** — a hostile scope must
  stay in exactly the one lane — with the expectation spelled literally in the test rather than
  derived from the production helper.
- Named residual: the per-item `outputSchema` override is proven offline (rendered-script
  execution + serialized-object pins) but not against live pi-subagents RPC until a live
  `/pr-review-dynamic` run with a selector-proposed custom angle.

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

### One discriminated, single-use post record

Static and dynamic PR-review doors share one module-scoped state machine: `null`, `pending`, a
recorded wave outcome, then `consumed`. Decode tool parameters first; immediately after successful
decode transition to `pending`, before resolving the review target or spawning lanes. Bad input
preserves the prior usable record, but any valid new pass invalidates it even if target resolution
or launch later fails. This prevents an old complete result from being posted after a newer attempt.
Registration resets module state for a fresh session.

A successful post consumes the record exactly once. A `review_target_changed` refusal demotes a recorded
outcome back to pending because its identity evidence is no longer postable. Other mutation
failures retain the record so a transient failure can be retried without rerunning the wave. Keep
the post tool sequential: this check/transition sequence is safe only under one-at-a-time execution.

### Layer identity through every boundary

The parent resolves the PR once before spawning and threads that expected PR into each lane task.
Children read review context only through an expected-PR-checked path. At mutation time Python
resolves the target afresh and refuses if it differs. There is deliberately no second TypeScript
pre-post read: duplicate reads widen the race window without replacing the authoritative mutation
check. Binding is to PR identity, not head SHA, so new commits do not silently retarget the review
to another PR.

The durable posted identity comes from exactly one source: the successful mutation response. Do
not preserve a caller-supplied or preflight identity as if it proved what GitHub accepted. Likewise,
when an input field is removed, reject the stale key by making the whole decoded batch invalid;
silently dropping it lets old callers appear successful under changed semantics.

### Truthful launch and coverage manifests

`WaveLaunchManifest` preserves three ordered sets: requested lanes, runnable lanes, and keyed
preflight failures. If preflight rejects every lane, launch returns `ok: false` with those specific
failures rather than manufacturing a synthetic wave failure. Pending state keeps the full requested
order so collection retains the true coverage denominator even when some lanes never spawn.

Ponytail is required and exclusively owns the standalone YAGNI/simplification pass. Do not dilute
that ownership into another angle or count a missing Ponytail as covered. The honest TOCTOU posture
is that repository or target instability yields incomplete coverage, never falsely accepted
coverage; the system does not claim head-SHA immutability.

### Adjacent tripwires

A prompt-surface or tool-schema change also updates the prose-graph projection in
`docs/design/prose-prompt-map.md` and its pinned fragment total. Those count failures are
intentional ripple detectors, not unrelated test churn.

The registered-tool census has a fourth leg: the docs-site table
`docs/user-docs/reference/in-session/model-tools.md`, guarded by
`docs/site/src/in-session-reference.test.mjs` (set-equal to `PERK_TOOLS` and a live harness
registration) — keep that guard in mind when registering tools (#1997).

For start/collect wave pairs, `executionMode: "sequential"` remains the concurrency guard. Collect
races the pending result against a bounded, environment-overridable grace to absorb the completion-
event versus `subagent_wait` wake race. An unsettled result soft-fails while retaining pending; the
module timeout eventually settles a stuck run and a later collect drains it.

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
- **Fake-responder waves never exercise the agent def.** A prose agent-def paired with a code
  schema needs its own lockstep test — the fake responder writes already-valid reports straight
  into the run result, so a def regression (e.g. back to a retired fenced-JSON completion form)
  leaves the suite green while every live lane fails. The pattern: derive the def assertions from
  `schema.required` (drift in either direction trips the same test); reject the retired
  completion form explicitly (`doesNotMatch` on the old wording) while *counting* the legitimate
  remaining fenced-JSON uses; fold the `.pi/agents/perk/` mirror byte-identity pin into the same
  test. Reusable example: `extension/waves/adversarialReviewWave.test.ts`.
- **Identity-bearing generated items need per-key assertions.** Tie every generated lane task to
  *its own* key — assert each task opens with its lane's `Angle:` prefix; exact-pinning a sample
  of two of N leaves a lane launched under a sibling's rubric green.
- **Configuration-like values need an externally observable failure-path test.** When a value
  (e.g. a wave's `flow` identifier) only surfaces through a seam, observe it through that seam —
  the shared runner's pre-aborted-signal cancellation detail names the flow, making it the
  cheapest observable pin.
- **Probing door-primed module state without test-only exports.** The zero-item push
  (`findings: []`) with an injected throwing `fetchLike` is a side-effect-free primed/unprimed
  probe — nothing held means no fetch. Companion gotcha: background-`finally` clears need a
  bounded poll, not an immediate assert (`extension/doors/prReviewBrowser.test.ts`).

## Watch items / residuals

- Three suites parse the module-rendered script by slicing between `runs.all(` and `);\nreturn` —
  a renderer output-shape change breaks them loudly but widely (consider a shared parse helper at
  a fourth consumer).
- The review-wave pair (and the draft pair) HAVE now run against real pi-subagents — the
  2026-08-10 live dogfood of the three streaming browser doors
  (`docs/design/archive/streaming-doors-dogfood.md`: streaming cadence, dedupe, `replace` reshape,
  typed collect aggregates, all live-confirmed). The **dynamic flow**
  (`prReviewDynamicWave.ts`) has still not run against real pi-subagents — that half of the
  residual stands, with the stale-session gotcha: a landing session predates its own
  extension code (see `pi/extension-api.md` on dogfooding just-changed extension code).
- `pr`/`worktree`/`bundle_dir` stay model-relayed (an accepted trust posture;
  `decodeStartReviewWaveParams` is the single seam to adjust if door-recorded context is
  adopted).
- pi-subagents is deliberately UNPINNED; the guidance is source-re-verified at the version
  pinned by `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` (`src/perk/convergence/doctor/checks.py`),
  and the doctor `subagent-compat` probes are the drift tripwire — re-verify the adapter on any
  bump.
- The pre-digest recipe for foreign-seam nodes (read the unimportable dependency's source at plan
  time, pin the envelope as module constants, keep unversioned names advertised-not-pinned) is
  recorded in `pi/subagents.md` — cross-link, don't restate.
- An advisory multi-angle review followed by an immediate land silently converts findings into
  debt — route them explicitly (a follow-up node, or fold into the next node touching the
  module; PR #1910 → plan #1912 is the worked instance). A clean plan-fidelity lane does not
  mean a clean PR (#2000, #1991, #1999).

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
  `adversarialReviewWave.ts`, `draftReviewWave.ts`, `reviewClassifierWave.ts`,
  `objectiveExplorerWave.ts`, `auditWave.ts`, `harvestWave.ts`, `dreamWave.ts`,
  `dreamReducerWave.ts` — the flow entrypoints
- `extension/doors/reviewWaveTools.ts` — the start/collect tool pair (live — the review doors
  drive it)
