---
title: The report-wave module — code-owned waves, lane semantics, native settlement, and the wave test machinery
read_when: You are changing extension/waves, review-wave identity/launch token, native partial settlement and unfinished lanes, stop/terminal-proof classes, parent-prepared snapshots, lane semantics, wave tests
cluster: subagent-orchestration
---

# The report-wave module

perk's multi-lane subagent fan-outs (review waves, learn-analyst waves) run as **code** on the
Perk-owned report-wave module in `extension/waves/`, launched over the pi-subagents v1 extension
RPC. This doc is the perk-side architecture: the module's shape, the recipe for wiring a new
flow onto a code-owned wave, the lane-normalization semantics, the session-scoped guard-state
patterns, and the wave test machinery worth reusing.

**Doc boundary:** the *upstream* pi-subagents mechanics — the v1 RPC envelope, `outputSchema` /
`structured_output`, the supervisor channel (off at every perk spawn), `mission: false`, the
completion-notification wake (`"subagent-notify"`) and the `bg_wait` background-wait tool (the
renamed `subagent_wait`; perk does not adopt it) — and the engine-version chronology live in
`docs/learned/pi/subagents.md`. Cross-link them; don't duplicate them here.

## Distillation

- Wave mechanics are CODE: `reportWave.ts` (logical core) over `transport.ts`; every flow is a
  mechanism + installer pair — "Orientation"; completeness is `strict` (complete ⟺ zero
  failures) or `best-effort` (complete ⟺ no wave-level failure) per flow.
- Every spawn carries three fixed fields — `acceptance: {level: "none"}`,
  `intercomBridge: {mode: "off"}`, the per-launch `args.launch` token — "The fixed spawn
  contract carries an explicit acceptance disable".
- Blocking runs are start + await — "The start/settle split"; a new flow = mechanism +
  installer + policy lockstep + dormant-first → atomic flip — "Wiring a new wave flow".
- Lane semantics: status ≠ validity ≠ coverage ≠ assessment completion — "Lane semantics";
  size-budgeted renderers emit splittable per-line blocks — "Budgeted block-packing renderers".
- Review posting uses one discriminated single-use `ReviewPassHolder` bound to one PR; launch
  manifests preserve requested/runnable/preflight-failed lanes — "Session-scoped guard state".
- The recorded post carries a code-owned minimum verdict; native `partial` settlement retains
  sibling reports but never completeness (duplicate keys withheld at BOTH tiers; still-running
  roster lanes report `lane-failed`); every child carries the CONSTANT `{readOnly: true}`
  packet + `worktree: false` — "One discriminated, single-use post record", "Native partial
  settlement", "The constant child-restriction packet".
- Producer-lane waves key lanes `lane.<ordinal>`; routing tokens are fenced by refusal, never
  escaped; outcome loops walk the plan — "Validate downstream identifier contracts"; `blocked`
  reports reclassify to `lane-failed` before coverage — "Lane semantics".
- Parent-verified inputs — the stack door's digest-bound `PinnedStack` (the pinned `review-context`
  command), the draft doors' door-primed `custom` lane — "Parent-verified lane inputs"; Ponytail's
  exact skill source is preflighted, never serialized — "Truthful launch and coverage manifests".
- The parent owns the facts, the lane returns judgment — "Parent-prepared snapshots"; a
  `no_active_session` reply is held for a later success — "The context-less RPC hold"; dated
  history and live evidence — "Live-proof ledger (dated)"; still open — "Watch items / residuals".

## Orientation

`extension/waves/reportWave.ts` is the LOGICAL core — `ReportAssignment` (the renamed
`WaveLane`; `ReportWaveRequest.assignments`), normalization, the runner, and the caller-facing
failure union — over the transport tier in `waves/transport.ts`: the adapter seam (`WaveAdapter`,
`WaveSpawnParams`, `WAVE_ACCEPTANCE`), the script tier (`startWaveScript`/`runWaveScript`,
`WAVE_TIMEOUT_MS`), receipt primitives, and the transport failure vocabulary
(`WaveRunFailureReason` — the six wave-level reasons, a structural SUBSET of the logical tier's
`ReportWaveFailureReason`, so script failures flow up with zero runtime mapping and a lane-level
reason on a script-run failure is unrepresentable). Callers consume the opaque `ReportWave`
lifecycle — `start`/`collect`/`run` over opaque `ReportWaveRef`s: they supply assignments and
consume typed outcomes, never adapters, run handles, or result promises (the blocking `run` is
start + await inside the instance; pending execution is instance-owned with drain-once,
delete-as-claim collection). `ReportWaveRequest.completeness` is `strict` — complete ⟺ zero
failures (the three review waves, the classifier, explorer, scout, simplify and both dream tiers)
— or `best-effort` — complete ⟺ no wave-level `key: null` failure, assignment failures being
explicitly reported skips (the learn, harvest and audit waves). Adapter selection is wave-owned:
`createReportWave(bus)` constructs the ONE per-activation production instance at the composition
root (`extension/pi/activation.ts::activatePerk`) — it takes **no supplier** (the child
restriction packet is a constant, below); `reportWaveOver(adapter)` is the test injection seam.
`renderWaveScript` + assignment validation are module-private — script text is invisible outside
`waves/`, so renderer assertions observe the spawned `script` through the adapter seam.
`rpcAdapter.ts` is the live pi-subagents v1 RPC adapter (interior — `reportWave.ts` is its one
sanctioned production construction site); the first-class test double lives in
`extension/testing/memoryAdapter.ts`. Guard Rule G (`extension/importDirectionGuard.test.ts`)
bans production edges into `transport.ts`/`rpcAdapter.ts` from outside `waves/` (no production
adapter construction exists outside `waves/`) and censuses raw `WAVE_RPC_`/channel tokens (tests
included). The flow entrypoints (mechanism — installer + tool — policy):

- `prReviewWave.ts` — `/pr-review`'s wave behind `run_pr_review_wave` (installer
  `extension/pi/v1/codeReview/automated.ts`): strict, ONE bounded retry of the uncovered lanes —
  never a `skill-unavailable` lane, and none after a non-retryable wave-level failure.
- `extension/learning/analystWave.ts` (`runLearnAnalystWave`) — `/learn`'s analyst fan-out behind
  `run_learn_wave` (`extension/pi/v1/learning/learn.ts`): best-effort, no retry.
- `adversarialReviewWave.ts` — the human review doors' completion-only wave behind
  `start_review_wave`/`collect_review_wave` (`extension/pi/v1/codeReview/reviewWave.ts`): strict,
  zero retries; `collectAdversarialReviewWave` applies `reclassifyBlockedReports`; the optional
  `stack: PinnedStack` input is § "Parent-verified lane inputs".
- `draftReviewWave.ts` — the draft doors' completion-only wave behind
  `start_draft_review_wave`/`collect_draft_review_wave` (`extension/pi/v1/draftReviewWaveTools.ts`
  over `extension/authoring/review/draftContext.ts`): 2–3 of four settled angles + the optional
  door-primed `custom` lane + Ponytail; strict, zero retries.
- `reviewClassifierWave.ts` — `/address`'s ONE-lane `perk.review-classifier` wave behind
  `classify_review_feedback` (`extension/pi/v1/delivery/address.ts`): strict, no retry (the flow's
  posture is "surface the error and stop").
- `objectiveExplorerWave.ts` — the objective-plan factory's OPTIONAL ONE-lane
  `perk.objective-explorer` wave behind `explore_objective_node`
  (`extension/pi/v1/objectivePlanning.ts`): strict, no retry (on failure the guidance says "explore
  directly instead").
- `extension/learning/audit.ts` (`judgeAuditBundle`) — the perk-dev session-audit wave behind
  `run_audit_wave` (`extension/pi/v1/learning/audit.ts`), with a **structural write binding**: a
  `gated: { carveOut }` policy whose write target comes only from the cold door's workflow-state
  (`audit_bundle_dir`) and **no parameters** — no model-relayed path ⇒ no aimable writer (the
  precedent for read-only-gated tools that must write). A new isolated registry stage grows
  `src/perk/state/gc.py::terminal_stage_ids` and trips `tests/test_gc.py`'s exact-set pin — sweep
  it with the stageTools/toolGating/registry pins.
- `extension/learning/harvest.ts` (`analyzeHarvest`) — `perk learn harvest`'s analyst fan-out
  behind `run_harvest_wave` (`extension/pi/v1/learning/harvest.ts`): the one `manifest_path` param
  is a **relay handshake, not an authority** — the execute reads only the run-scoped path derived
  from workflow-state (contracts §8.48), and a single-lane manifest is refused toward the seed's
  direct-analysis path; best-effort, ONE attempt, no retry.
- `extension/learning/dream.ts` (analyst tier) + `dreamReducer.ts` (three fixed fresh-context
  `perk.dream-reducer` lanes, `DREAM_REDUCER_ANGLES`; pure orchestration — the door owns every fs
  write) behind the ONE parameterless `run_dream_wave` (`extension/pi/v1/learning/dream.ts`) over
  `extension/learning/dreamAnalysis.ts::analyzeDream`: both tiers strict, one attempt, no retry,
  workflow-state-bound on read and write like `run_audit_wave`. Manifest decode, preflight, caps,
  bundle budget and reducers-only-after-a-complete-first-wave: contracts §8.59–§8.61 and
  `learn-harvest-dream-core.md`.
- `scoutWave.ts` — the `perk.scout` delegation wave behind `run_scout_wave`
  (`extension/pi/v1/scoutWave.ts`): 1–`SCOUT_MAX_BRIEFS` (6) briefs, one fresh-context lane each,
  **strict**, one attempt, no retry (an incomplete wave is the caller's to handle).
- `simplifyWave.ts` — the `/simplify-plan`/`/simplify-objective` doors' single-assignment, strict,
  zero-retry `perk.simplifier` wave (installer `extension/pi/v1/simplify.ts`: two warm doors and
  **no tool**).

Every mechanism holds its closed report schema as a module constant (the workflow-level
`outputSchema`). `ponytail.ts` is not a flow — it is the Ponytail source-identity preflight every
Ponytail lane passes through (§ "Truthful launch and coverage manifests"); `laneIdentity.ts` and
`blockedReports.ts` are the shared lane helpers (§ "Validate downstream identifier contracts",
§ "Lane semantics").

## The constant child-restriction packet

Every runnable child item in the rendered script carries exactly
`extensionBindings: {"perk.parent-restrictions/1": {readOnly: true}}`
(`reportWave.ts::REPORT_CHILD_RESTRICTIONS`, a module constant) together with `worktree: false`
(caller-checkout placement, so the plan-ref-dependent readers — `/pr-review`, the `/address`
classifier — keep working without a per-request policy). `renderWaveScript(assignments)` embeds
both **unconditionally**: nothing is sampled from the parent gate, the handoff, task or assignment
data; explicit field selection plus a whole-array `JSON.stringify` keep hostile task text and extra
assignment properties inert. The earlier design — a required lazy `parentReadOnly` supplier sampled
once per attempt, an `unavailable` capture-failure arm, and a `ReportWaveRequest.execution` opt-in —
is **gone**: every report child is read-only and caller-placed, so no flow can select otherwise and
there is no capture that can fail.

This is the producer half of the two-boolean policy; the consumer (`decodeReadOnlyFloor`, the
activation latch) and the binding record are in `pi/subagents.md` § "Native child execution — the
two-boolean policy" and `docs/design/pi-subagents-child-execution-policy.md`. Lesson: when only
one half of a producer/consumer repair lands, state the residual in `contracts.md` — passing tests
never imply end-to-end behavior.

## The fixed spawn contract carries an explicit acceptance disable

Every wave spawn carries three fixed `WaveSpawnParams` fields — no per-lane/per-flow opt-out.
`acceptance: {level: "none", reason}` (`WAVE_ACCEPTANCE`): without it the engine infers an
acceptance contract and injects a competing completion instruction — observed steering a child
into invalid `structured_output` attempts (the inference rule and its version history:
`docs/learned/pi/subagents.md`'s **Acceptance hazard** paragraph). `intercomBridge: {mode: "off"}`
(`WAVE_INTERCOM_BRIDGE`): the engine discards parent-side progress updates yet still appends a
bridge template telling children to send them — perk children never ask decisions, so the bridge
is pure cost, and turning it off at spawn is what makes every wave **completion-only** (no
`contact_supervisor` tool, no template, no tool-named prohibition in def prose). Both ride the
engine's workflow-defaults spread onto each lane child; scripts stay byte-identical.

**The launch token is the third fixed field.** `args: { launch: randomUUID() }` is minted at
`startWaveScript`'s one spawn site (`transport.ts`): not a spec field, not caller-selectable, never
read back, never identity (identity stays `asyncDir`/`asyncId`); the script bytes are unchanged, so
render parity holds. Its only job is to defeat the supplier's workflow reuse key (`scriptDigest` +
`argsDigest` over a `runtime-replaced` run — `pi/subagents.md` § The v1 extension RPC seam), which
once returned a `/reload`-replaced wave's reports as fresh. A source pin in
`reportWaveRpc.test.ts` forbids the reuse vocabulary in the three wave modules and asserts the
mint site. Glossary: `CONTEXT.md` **Launch token** / **Relaunch freshness**. `/reload` stops an
in-process workflow, and a wave that completed before the reload is `no_wave` to the next
activation (collection is per-activation; both observed live 2026-10-25 — § "Live-proof ledger
(dated)"). The doctor `subagent-compat` version `warn` is the drift tripwire (doctor never reads
the engine's source).

## The start/settle split

`start*` returns a handle plus a `result` promise that **never rejects** — every arm normalizes —
so a detached/uncollected run can never become an unhandled rejection. The blocking form is
start + await result: ONE operational core, applied at two levels (script: `transport.ts`'s
`startWaveScript`; assignment: the module-private start behind the opaque `ReportWave.start` —
the handle and result promise never leave `reportWave.ts`; callers hold a `ReportWaveRef` and
`collect` drains it). Discipline details: the completion subscription is released exactly on settle;
pre-spawn failures unsubscribe immediately and return the same failure/receipt values the blocking
runner reported.

When a refactor moves a runner body verbatim, the untouched pre-existing matrix passing *is* the
parity evidence — lean on it rather than re-arguing the invariants.

## Wiring a new wave flow — mechanism + installer, policy lockstep, dormant-first

- **Mechanism + installer.** The mechanism (`extension/waves/<flow>Wave.ts`) owns the closed
  report schema and the code-composed `<untrusted_…>` envelope and returns the raw
  `ReportWaveResult`; the installer (`extension/pi/v1/…`) does tool-boundary decode → model
  resolution (`[models.subagents]`) → the `ToolResult` projection. Clone the **full** options
  shape (`timeoutMs?` included) even when no production caller passes it.
- **Guidance stays judgment-only prose + the tool name**, negatively pinned against
  `workflowScript`/`runs.all`/`outputSchema`; a template-var change rides
  `prompts/_fixtures/live.yaml` + the `stageTools.test.ts` drive entry.
- **Name the five-leg tool-policy lockstep at plan time:** the `registerPerkTool` policy
  (`stages`, e.g. `WORKTREE_STAGES`); the regenerated `shared/fixtures/tool-matrix.json`
  (`pi/tool-loadout.md`); the `stageTools.test.ts` drive-coverage guard, firing once the guidance
  names the tool (`warm-door-commands.md`); the docs-site table
  `docs/user-docs/reference/in-session/model-tools.md` (guard
  `docs/site/src/in-session-reference.test.mjs`); the prose-graph projection
  `docs/design/prose-prompt-map.md`'s pinned fragment total (count failures are ripple detectors).
- **Dormant-first → atomic flip** when the wave's `outputSchema` and the def's completion form
  must agree at every commit: land built/tested/unregistered, then flip registration, the def's
  completion contract, the door prompts, the skills and the census in ONE change. At the dormant
  landing write the **dormant-qualifier inventory** into the flip node (def description + its
  prose-invariants pin, wave header, contracts §8.3, config comments, `[models.subagents]` doc
  rows, deferred prose-map/CHANGELOG items) and pin one qualifier ("Ships dormant") so the flip
  must invert a pin; de-dormanting = delete the DORMANT paragraphs, drop the tests'
  `extraExtensions` workaround, flip census-absence pins to membership pins. A dormant def/module
  is never described in present-tense "perk does X" prose.
- Agent-def prose precision is behavioral (#1997); retiring prompt discipline into code surfaces
  latent underspecification (`plan-review-flow.md`); keep interim prose a module will delete
  minimal and invest in the conventions it inherits.

Dated: the `/pr-review` migration (2026-08-08) was the template; the adversarial pair (#1999) and
the simplifier (#2557 → #2561, same day) validated dormant-first — § "Live-proof ledger (dated)".

## Shape parity is not contract parity (schema forward-binding)

When forward-binding a wave report schema to a downstream consumer's shape
(`DRAFT_REVIEW_REPORT_SCHEMA` → the plan-finding shape in `extension/pi/v1/providers/annotations.ts`),
matching keys/types is not enough — **trace representative *values* through the next decoder**.
The schema accepted whitespace-only `phrase` strings that plan-mode `push_annotations` rejects
*wholesale* (one bad anchor fails the batch), so an engine-valid report could fail the
feed-without-reshaping contract. The fix carries a `pattern` constraint on the string arm —
JSON Schema `pattern` applies only to string instances, so the required-nullable `null` arm still
passes — plus negative/positive semantic pins.

Corollary for agent-def prose: **prompt rules stated globally can be internally impossible.** A
def requiring both "wrap any quoted draft text in delimiters" and "emit a bare byte-exact anchor
field" holds two representations of quoted draft text to contradictory rules — state the
exception explicitly or the completion contract is unsatisfiable. The second exemption class: a
report field that IS the replacement artifact (the simplifier's `proposal`, which under `lite`
carries retained source prose verbatim) cannot obey a "wrap quoted draft text" rule either — wrapping
would make the proposal unusable as a draft. Scope wrap rules to commentary fields, name both
exemptions explicitly (anchor fields, whole-document fields), and pin both clauses in the def's
prose-invariants test. **Audit every output field that can contain source text**, not only anchors.

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
  proves conformance to the contract *as mirrored*, not to the live engine (the current live legs:
  S3 and W6 of the 2026-10-25 certification — § "Live-proof ledger (dated)").
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

**The endpoint.** All three producer-lane learn waves (harvest, audit, the dream analyst tier) now
share ONE code-owned formatter, `extension/waves/laneIdentity.ts::orchestrationKey(ordinal)` →
`lane.<ordinal>`; the per-flow `<sanitized id>.<ordinal>` sanitizers were deleted (a half-measure
that carried producer bytes into the key collapsed to one format that carries none). The
convergence fixed a latent harvest throw: a producer-valid `docs/learned/` directory name outside
the run-key charset reached `validateAssignments` and threw instead of taking the typed failure
path. Two patterns came with it:

- **The routing-token fence** (`isRoutingToken` / `renderRoutingToken`) is a **refusal rule, not an
  escaping rule**: a token must survive byte-exact matching against the manifest and byte-exact
  echo back, so any escaping breaks selection by construction — accepted tokens render
  byte-identical (every existing raw-byte task-prose pin stays valid) and unacceptable ones are
  refused by the strict decoders or degraded by the lenient audit planner *before* a task is
  composed. A "routing token" is named by its **render site** (task prose), not by one producer's
  id shape — the audit wave also renders a pair-level `session_basename` the child echoes.
- **Plan-iteration over aggregate-iteration.** Outcome loops walk the module-private lane plan and
  look aggregate rows up by planned key (`reportsByKey` / `failuresByKey`), which structurally
  removes the "unplanned key in the aggregate" branch; outcome order becomes manifest order — pin
  it once.

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

## Parent-verified lane inputs — the pinned stack and the door-primed custom lane

When a lane's input must match what the human is looking at, pass parent-verified DATA into the
task — never a flag that lets the child re-derive a moving answer, never model-relayed coordinates.

- **The pinned stack.** `extension/waves/adversarialReviewWave.ts::PinnedStack` (`topPr`,
  `checkout`, `baseSha`, `heads[{pr, headSha}]` bottom→top) is the checkout snapshot the stack door
  verified and bound: `extension/pi/v1/codeReview/stack.ts::verifyStackPatch` hashes the derived
  patch against the cold checkout envelope's `patch_sha256` (`mismatch`: the checkout was refreshed
  — reopen), `pinnedStackOf` builds the pin, and the door sets it into the per-activation
  `StackPinState` (`pinned` + `inFlight`, in `extension/pi/v1/codeReview/reviewWave.ts`).
  `start_review_wave`'s `stack` is a **boolean**: `true` reads `StackPinState.pinned`, refuses when
  no stack review is open or its `topPr`/`checkout` disagree with the call's `pr`/`worktree`, and
  locks the pin as `inFlight` until `collect_review_wave` settles — a different-pin stack open is
  refused meanwhile (`pinSupersedeRefusal`). Only the lane task's subject sentence changes: it
  names the stack topped by the PR and embeds `pinnedReviewContextCommand(stack)` —
  `perk pr review-context --pr <top> --stack --pin-base <sha> --pin-head <pr>=<sha> …`, the ONE
  renderer lane tasks and the stack guidance's routing step share. The CLI's pinned arm
  (`src/perk/cli/commands/pr/review_context_cmd.py::_pinned_stack_context`, `_validate_pins`)
  treats the pins AS the membership — grammar, objects present locally, a linear stack over the
  base (`pinned_object_missing` / `stack_topology_broken`) — and diffs exactly those commits with
  **no git fetch** (`local-pinned`; member title/body stay live GitHub reads). Without `stack`,
  lane tasks are byte-identical to the single-PR wave (`adversarialReviewWave.test.ts`). *Dated:*
  before perk 3.6.0 (2026-09-21) `stack` was a bare discriminator and the child re-resolved
  membership live — the moving-ref hazard the pins closed.
- **The door-primed custom lane.** `extension/waves/draftReviewWave.ts` adds ONE extra assignment
  (key = label = `custom`) iff the door-primed context
  (`extension/authoring/review/draftContext.ts`) carries a human-supplied angle definition — the
  tool pair has no custom parameter, so the model cannot invent a lane. The task flags the
  definition as DATA from the human; the schema's `angle` enum includes `custom`; coverage and
  `push_annotations` treat it like any lane under its own source
  (`extension/waves/draftReviewWave.test.ts`: appears iff supplied, verbatim as flagged DATA). A
  lane fed untrusted text warrants an explicit containment test — hostile text stays in exactly
  that one lane, the expectation spelled literally in the test.
- **The per-lane schema override has no live carrier.** `ReportAssignment.outputSchema` still
  renders per item only when present (fixed-item pins stay byte-identical); its one carrier — the
  dynamic flow's selector-proposed custom lane (reserved-key + kebab-slug validation, ≤300-char
  collapsed scope, fixed template) — retired with that flow on 2026-09-10 (perk 3.3.0), never run
  live. Keep the mechanic; don't add a carrier to justify it.

## Parent-prepared snapshots — the parent owns the facts, the lane returns judgment

The `/address` classifier recipe (`extension/waves/reviewClassifierWave.ts`), reusable for any
lane that judges parent-known subjects:

- **Strict decode at the parent.** The parent fetches the input and decodes it with a compiled
  typebox schema — open objects, every kept field strict, id uniqueness checked (the consumer twin
  of the producer's duplicate-id refusal).
- **Code derives the subjects** and renders only those, inside a fixed-tag fence
  (`<untrusted_feedback_snapshot>`; attribute values via `JSON.stringify`).
- **Complete-coverage bounded rendering.** Every subject is listed; the per-body cap adapts from
  `SNAPSHOT_BODY_CAP_CHARS` (4,000) down to `SNAPSHOT_BODY_FLOOR_CHARS` (200) under a
  `SNAPSHOT_DIGEST_BUDGET_CHARS` (240K-char) budget, refusing `snapshot_too_large` only when the
  floor itself overflows — a sibling of "Budgeted block-packing renderers".
- **The lane schema carries judgment only** — `additionalProperties: false` turns a parent-known
  field echoed by the lane into a schema fault.
- **The binder** checks shape first, then correlates every fault in one pass walking the subjects.
- **The parent holds the bound result per activation**, cleared at every classify entry; the
  mutating tool (`finalize_address`) refuses when nothing is held or an id is outside the held set.
- Typebox 1.x wire fact: `Type.Enum` serialises to a plain `{enum}` with no `type`/`anyOf`.
- Plan craft: check example fixtures against the plan's own formula; `failFor`'s `fail()` already
  reports.

## Lane semantics — status ≠ validity ≠ coverage

The normalization distinction lives at the `lane-failed` / `malformed-report` reason comments in
`reportWave.ts`: `ok: true` with a `null` report is `lane-failed` (structured output never
validated), while a non-object/non-null report or a non-boolean `ok` is `malformed-report`. Since
pi-subagents 0.71.0 a **failed** lane can retain a schema-valid report as evidence, so coverage is
`ok: true` AND an object report — `normalizeAssignments` classifies `ok: false` as `lane-failed`
regardless of a retained report (pinned in `extension/waves/reportWave.test.ts`); "valid ⇒ covered"
is false. `shared/contracts.md` §8.35's lead sentence still reads "covered angle ⟺ ok lane ⟺
schema-valid report"; its own later paragraph — `ok` is the sole per-lane status fact, and a failed
row that retains a schema-valid report stays `lane-failed`, never covered — supersedes it. The lead
amendment is still open (#2583). Flow code messaging skipped lanes must not conflate the reasons.

The broader rule (from the session-corpus audit): **a child's harness status is not report
validity is not wave coverage.** Validate the report artifact separately, retry a failed required
lane only within its bounded policy, and persist an uncovered lane rather than upgrading partial
coverage to clean.

**Schema-valid ≠ covered.** An engine-valid report is not necessarily a completed required
assessment. `extension/waves/blockedReports.ts::reclassifyBlockedReports(result, isBlocked)` is the
flow-neutral normalization: each flow supplies its typed predicate (pr-review `verdict ===
"blocked"`; the adversarial doors `blocked === true`), and every matching report moves from
`reports` into `failures` as an assignment-keyed `lane-failed` **before** retry selection,
`covered`, and `complete` — a recovered bounded retry is covered, a persistent block stays
uncovered; the block's `fyi` diagnostics keep their bytes and order and never become postable
findings; missing/null/blank plan text **blocks** plan-fidelity (not FYI). In the adversarial
schema `blocked` is a **required** boolean (never defaulted — missing/mistyped is engine-invalid) with a
schema conditional (blocked ⇒ empty findings + nonblank `fyi`), and it is not a verdict: it marks
"could not finish", distinct from "no findings". Relatedly, conversation isolation, filesystem
placement and perk's read-only floor are three separate controls: isolation is the engine's (every
lane is a fresh child context); placement is the renderer's constant `worktree: false` — every
report child of every flow runs in the caller checkout, there is no per-request opt-in or
native-default arm (§ "The constant child-restriction packet"); the floor is the constant
restriction packet. Never repair missing plan authority by copying ignored state into allocated
worktrees.

**A retry relaunches exactly the effective lanes WITHOUT a report.** A retained actionable report
is therefore effective evidence a retry can never supersede — only a `blocked` report (reclassified
`lane-failed`) is retried away. A retry-policy change re-audits downstream end-to-end fixtures for
REACHABILITY (a stale `extension/codeReview/automated.test.ts` composition kept asserting a path
the new policy could no longer reach).

**A compacted lane is not a failed lane.** A floored report child can be compacted mid-run; its
task restore and the `structured_output` hold live entirely in the child's extension runtime (the
wave module is unchanged) — `docs/learned/pi/subagents.md` § "Report children survive compaction".

Extra defensive arms worth keeping when extending the module: a pre-aborted `AbortSignal` cancels
before launch (no spawn issued); malformed async-complete payloads are dropped, never surfaced as
phantom completions; a `status.json` without a `state` field throws (`aggregate-unreadable`)
rather than being treated as terminal.

## Native partial settlement — retain sibling reports, never completeness

When pi-subagents settles a workflow `partial` (`terminalOutcome: {state: "partial", reason:
"timeout" | "budget_exhausted"}`), independently successful engine-validated sibling reports are
preserved while the wave still surfaces failure and `complete: false`. The invariants:

- **Report authority is dual-sourced, never merged.** An array-valued durable
  `status.json.workflow.value` is authoritative in full (failed rows and holes included); only when
  the durable value is not an array does the transport fall back to the completion's compact
  child-result projection (`workflowKey`→`key`, `success`→`ok`, string `error`,
  `structuredOutput`→`report`). Ordinary `complete` still uses the durable value exclusively.
- **Keys come only from a nonempty `workflowKey`** — never `agent`, order, artifact paths, or
  receipts. **Duplicate-key withholding is dual-tier**: the transport
  (`rpcAdapter.ts::narrowRetainedEntries`) collapses duplicate `workflowKey` rows (or one `runId`
  across keys) into one `{ok: null}` entry → the normalizer's *no-boolean-`ok`* `malformed-report`
  detail; the logical tier (`reportWave.ts::normalizeAssignments`) counts rows per expected key →
  `malformed-report` with the *"appears N times"* detail. Both withhold every row for that key,
  neither guesses first/last-wins; contracts §8.35 is the single normative home. Test technique:
  pin **tier-of-origin via detail-string divergence** (`assert.match` one detail AND
  `assert.doesNotMatch` the other on the same failure), and give duplicate fixtures **different**
  reports so a first-/last-wins regression is observable.
- **The engine deadline settles; perk's timer is post-grace insurance.** The spawned `timeoutMs`
  IS the engine deadline (`WAVE_TIMEOUT_MS`, 30 min; `PERK_WAVE_TIMEOUT_MS` overrides). perk's
  local timer is orphan insurance armed for deadline + a fixed 60 s `WAVE_SETTLEMENT_GRACE_MS` (no
  env knob, no spec field), so the engine's `partial/timeout` settlement and its completion
  carrier are consumed first. Retention happens only for the explicit native carrier (an object
  `terminalOutcome` on a `failed`/`partial` completion; never inferred from prose). A *deadline
  partial* retains finished lanes' reports; a `results[]` row with `state: "running"` (no
  `success`) projects to `lane-failed` ("lane still running at native partial settlement"), never
  `ok: null`/`malformed-report`. Only the post-grace local `timeout` (and cancel) has no retained
  reports. Vocabulary: `CONTEXT.md` (engine deadline / settlement grace / deadline partial);
  normative home §8.35; the engine side is `pi/subagents.md` § "Execution surfaces and structured
  output".
- **Roster-correlated unfinished lanes.** The supplier builds partial `results[]` from settled
  children only, so a still-running `runs.all` lane appears only in the `workflowChildren`
  roster. An identity-only side channel (`unfinishedLanes` on `WaveCompletion` → the `ok: false`
  arm → `normalizeAssignments`) is consulted only in the no-carrier-row branch and reports
  `lane-failed` with `LANE_STILL_RUNNING_ERROR`. Qualification: state `running`, a nonempty
  `runId` mapping uniquely to its own `childId` via the receipt correlation map (computed once per
  completion), a unique `childId`, and no `results` row with its key or run id. Invariants: a
  carrier row always wins; the roster never contributes a report, `ok` or error text; the field is
  omitted when empty; a withheld or mismatched inventory leaves `missing-lane`; no receipt child is
  synthesized. Reusable pattern: when a supplier splits one fact across two payload surfaces, add
  a separate identity-only channel consulted only at the exact fallback point. `ok` is the sole
  per-lane status fact (a failed row with partial markers and a schema-valid report stays
  `lane-failed`). Proven live on 2026-10-25 (W6: at a 20 s engine deadline the roster-only
  running lane reported `lane-failed` "lane still running at native partial settlement" beside the
  retained sibling report — § "Live-proof ledger (dated)").
- **Completeness is always false on this path** under both completeness policies, even if every
  report survived; the retained `key: null` `run-failed` entry (ordered first, naming the native
  reason) guarantees it; receipts stay output-free and `failed`.
- **Storage lifetime.** Completions are buffered **only while the spawn handle is unknown**; after
  the spawn reply the first matching completion goes into a single `matched` slot and the buffer is
  cleared (foreign entries and duplicates included); an `accepting` flag closes on settlement,
  timeout, or cancel so a completion arriving during the stop can never become late salvage
  (the stop itself is a typed outcome plus one terminal-proof read — `pi/subagents.md` § The v1
  extension RPC seam). A run-long buffer would leak report DATA across concurrent waves — and output-only tests
  cannot prove the release, so a source-shape pin was required.

## Session-scoped guard state

### One discriminated, single-use post record

The `/pr-review` pass rides one discriminated, single-use state machine: `null`, `pending`, a
recorded wave outcome, then `consumed`. Since the door→typed-op migration (PR #2109 — which also
retired the dynamic door) that state is **per-activation, never module-scoped**: the installer
creates one `ReviewPassHolder` per activation (`extension/codeReview/automated.ts`, created and
threaded by `extension/pi/v1/codeReview/automated.ts`), the browser door's annotation state is
likewise per-activation (`extension/pi/v1/codeReview/browser.ts`), and a fresh session gets fresh
state by construction — no registration-time module reset exists or is needed. (Dated: the
retired dynamic door once shared a module-scoped machine with `/pr-review`; module-level flow state
is banned since.)

Decode tool parameters first; immediately after successful decode transition to `pending`, before
resolving the review target or spawning lanes. Bad input preserves the prior usable record, but
any valid new pass invalidates it even if target resolution or launch later fails. This prevents
an old complete result from being posted after a newer attempt.

A successful post consumes the record exactly once. A `review_target_changed` refusal demotes a recorded
outcome back to pending because its identity evidence is no longer postable. Other mutation
failures retain the record so a transient failure can be retried without rerunning the wave. Keep
the post tool sequential: this check/transition sequence is safe only under one-at-a-time execution.

The recorded variant also carries a code-owned **minimum verdict**. `runAutomatedReview` projects it
ONCE from the reviewer's effective reports (`outcome.reports` — post-retry,
post-blocked-reclassification) and stores it as a primitive: `actionable` iff any report object's
exact `verdict === "actionable"` OR its `findings` is a nonempty array, else `clean`.
`publishAutomatedReview` refuses a `clean` post over `minimumVerdict === "actionable"`
**statelessly** (`review_verdict_conflict`: no consume, no `last_pr_review` append, holder
untouched — the record survives for a reconciled actionable post). Refusal ordering is
load-bearing: pending (`review_wave_unavailable`) → consumed (`review_wave_consumed`) →
clean-over-incomplete (`incomplete_coverage`, which wins even when actionable) →
clean-over-complete-but-actionable (`review_verdict_conflict`) → the publisher. Boundaries:
complete coverage is necessary but insufficient for clean; the floor is not a second schema
validator (the nonempty-findings arm is only a safeguard below schema validation — the schema
permits `actionable` with empty findings, so neither arm alone suffices); store the primitive only
(snapshot isolation — later source mutation must not move the floor); `minimumVerdict` is absent
from `last_pr_review`, the tool aggregate, and §8.35 receipts; FYI prose is never consulted; and it
is not an ever-actionable latch — retry replacement can move an earlier actionable report out of
the effective set, hence the scan of `outcome.reports`, never attempt receipts.

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

`ReportWaveLaunchManifest` preserves three ordered sets: requested lanes, runnable lanes, and keyed
preflight failures. If preflight rejects every lane, launch returns `ok: false` with those specific
failures rather than manufacturing a synthetic wave failure. Pending state keeps the full requested
order so collection retains the true coverage denominator even when some lanes never spawn.

The one preflight is the Ponytail source boundary (`extension/waves/ponytail.ts`): a lane's
`requiredSkill` names the exact project-package skill file (`PONYTAIL_CORE_SKILL` /
`PONYTAIL_REVIEW_SKILL`); `preflightPonytailSkill` checks the package identity, its advertised
`pi.skills` entry, the readable file and its frontmatter name. The requirement is never serialized
into the script; a failure is a keyed, non-retryable `skill-unavailable` (Ponytail is never
resolved from a same-named project/user skill). The memory/fake adapters never exercise it —
production defaults to `preflightPonytailSkill`, tests inject `requiredSkillPreflight`.

Ponytail is required and exclusively owns the standalone YAGNI/simplification pass. Do not dilute
that ownership into another angle or count a missing Ponytail as covered. The honest TOCTOU posture
is that repository or target instability yields incomplete coverage, never falsely accepted
coverage; the system does not claim head-SHA immutability. **Ponytail-bound defs come in two
roles.** All share the source-bound recheck clauses — the first-action exact-file read, the
frontmatter-name check, terminate without calling `structured_output`, never resolve a same-named
project/user skill, and the "short {pass} pass" stability clause (`review` or `simplify`). Only
*reviewer* defs carry the ownership-boundary clauses (exclusive owner of standalone findings;
ordinary lanes mention simplification only when inseparable; no second standalone Ponytail finding),
because they apply only where Ponytail is one angle among siblings — a lane that IS the whole pass
(`perk.simplifier`) omits them. `tests/test_subagent_agents.py::test_ponytail_defs_source_bind_only_the_exact_skill_paths`
encodes the split; a new Ponytail-bound def copies the recheck paragraph and decides its role.

### Start/collect pairs — instance-owned pending, the collect grace, the wake rule

`executionMode: "sequential"` is the concurrency guard (asserted by the registration tests).
Pending execution is INSTANCE-OWNED: the `ReportWave` instance holds every launched, uncollected
run behind opaque `ReportWaveRef`s with drain-once (delete-as-claim) collection. Flow state holds
only the ref — which wave is *current* is flow policy, never module-global: the draft pair's
`DraftReviewWaveState.pending` slot (the door-primed `context` beside it) in
`extension/authoring/review/draftContext.ts`, created per-activation in `activatePerk` and
threaded to the tool pair AND both browser doors; the review pair's registration-owned
`ReviewWaveState.pending` slot beside the shared `StackPinState` in
`extension/pi/v1/codeReview/reviewWave.ts`. Collect races the pending result against a bounded
grace (`PERK_WAVE_COLLECT_GRACE_MS` — wave-owned, default 15 s) to absorb ordering skew between
native workflow-completion delivery and aggregate resolution. An early unsettled collect retains
pending: end the turn and await matching workflow completion. Grace expiry after matching
completion was observed is an unresolved lifecycle contradiction: report and stop for owner
diagnosis, never poll or relaunch. The engine deadline settles; the local timer is post-grace
insurance; pending stays collectable.

Parents retain workflow identity and yield with Pi open: a routine successful child completion
does not wake them; failed/paused/stopped children and the workflow completion do, and only the
matching WORKFLOW completion authorizes collection. They reconcile exactly once from typed
reports; duplicate/late notices never re-collect. The flow-side slot clear is identity-guarded: a
supersede landing during an in-flight collect's await never erases the NEW pending wave. After a
`/reload` the old wave is `no_wave` (collection is per-activation). Pins: drain/race in
`extension/waves/reportWave.test.ts`, the flow slot in
`extension/pi/v1/draftReviewWaveTools.test.ts`, two-session isolation in
`extension/pi/v1/waveIsolation.test.ts`.

### Delivery after collection — reconciliation, held pushes, the perk:wave marker

Both review report schemas are completion-only: `{angle, summary, findings[], fyi[]}` (the
adversarial schema adds the required `blocked`), no delivery-status field — the wave spawns with
the bridge off, so nothing reaches the parent before the wave finishes (*dated:* the `streamed`
flag and its "no provisional batches" disclosures left with the streaming protocol in perk 3.4.0).
The collect result is `headline + fenced aggregate + the DATA sentence`. Coverage/failure/attempt
semantics and receipt-only details are unchanged; `fyi` is in-session color, never synthetic
findings or posted comments.

Browser reconciliation happens once, after collection: parent-reconciled arrays must be
disjoint — merge supported concerns and contributor tags, preserve maximum severity with its
corresponding confidence, and assign each anchor to the first contributing covered lane; push
each covered lane once with `replace: true`, empty arrays included. With nothing pushed before
collection, `annotations.ts` has no uncovered-source clear and no cross-source promotion. A held
final push before browser readiness is flushed by the readiness continuation; after readiness the
tool retries in-call over `HELD_RETRY_DELAYS_MS` and, exhausted, presents the findings in-session
— no later wake is promised. The early-decision window this opens (the human decides before the
wave lands) is closed by policy, not a gate: the tool pairs write a code-owned `perk:wave` status
marker (running at launch → cleared, "failed" or "incomplete" at collect; the `wave` slug is
refused to the model) and the door-open notice says to decide after the findings arrive; an early
decision is authoritative and forgoes them. The marker's fourth, *detached* arm
(`reviewDetachedStatus` in `extension/pi/v1/providers/waveStatus.ts`: replaced / interrupted /
session-ended) is pushed only by the browser-operation owner (`plan-review-flow.md` § "The
browser-operation owner"), never by the tool pairs. The marker persists after the workflow notice
until collection — observed live on both doors on 2026-10-25 (§ "Live-proof ledger (dated)").
Plan-mode source ownership also needs an `author` carrier for visible lane attribution (the
installed plan UI displays author rather than source).

## The context-less RPC hold

`extension/waves/rpcAdapter.ts::request` is no longer first-reply for errors (#2472): a
`no_active_session` reply (`WAVE_RPC_CONTEXTLESS_ERROR_CODE`) is HELD while the per-request
listener stays open. A later `success: true` wins and emits one fail-open `onDuplicateResponder`
event — forwarded as `WaveNotice {method, superseded}` and latched once per activation by
`extension/pi/v1/waveNoticeReporter.ts`. Any DIFFERENT error rejects immediately; only the reply
timeout surfaces the held error, with a "(held for a later reply…)" suffix; `ping` stays
first-reply. The second responder it absorbs is Pi's pre-trust extension leak
(`pi/subagents.md` § "The v1 extension RPC seam"). Accepted residuals: a genuine single-responder
`no_active_session` surfaces only at the ~30 s reply timeout; two loaded versions advertising
different async-complete channels time out loudly. A duplicate-load INFO leg on 0.81.0 observed
zero `no_active_session` replies (W3 — § "Live-proof ledger (dated)"); the full duplicate-load
protocol stays in `docs/design/archive/pi-pre-trust-extension-leak.md`.

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
- **The shared fake pi-subagents responder** (`extension/testing/fakeSubagents.ts`):
  `createFakeSubagents(plans)` answers `ping`/`spawn` with the v1 envelope, writes a terminal
  `status.json` into a mkdtemp `asyncDir`, delivers completions (per-spawn `delivery:
  "auto" | "manual" | "never"` knobs — `manual` + `emit` drive correlation tests; `never` + a
  tiny `timeoutMs` drives timeout→stop), sinks spawn params (`spawns`) and stop requests
  (`stops`), and computes script-derived aggregates via the `executeScript` plan hook — the
  offline e2e pattern for any RPC-launched wave (bind via the harness's `extraExtensions` or
  `attach` on a bare fake bus; the door/pi suites ride it). `waveScriptItems` is the shared
  `runs.all(`-slice parser (a failed parse throws, never a silent empty list).
- **Dormant (unregistered) tools** get real-session e2e coverage via the harness `extraExtensions`.
- **Pin the glue, not just the seams.** Config parse pinned + spawn param pinned still misses the
  tool-execute threading between them — have the fake responder sink spawn params so an e2e
  asserts the configured model/tasks reach the real spawn. "Both sides tested" ≠ "the boundary
  tested."
- **Fake-responder waves never exercise the agent def.** A prose agent-def paired with a code
  schema needs its own lockstep test — the fake responder writes already-valid reports straight
  into the run result, so a def regression (e.g. back to a retired fenced-JSON completion form)
  leaves the suite green while every live lane fails. The pattern: derive the def assertions from
  `schema.required` (drift in either direction trips the same test); reject the retired
  completion form explicitly (`doesNotMatch` on the old wording) while *counting* the legitimate
  remaining fenced-JSON uses; the def↔schema pins read `agents/<name>.md` only. Reusable example:
  `extension/waves/adversarialReviewWave.test.ts`.
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
  bounded poll, not an immediate assert (`extension/pi/v1/codeReview/browser.test.ts`).
- **The fake engine's ONE settlement mode.** `fakeSubagents.ts` plans take `executeSettlement`
  beside `executeScript` (optional-`never` exclusions refuse a mixed plan at construction) to
  script a native partial settlement — the offline evidence for the retention path.
- **Changing a shared wave timer needs a repository-wide expiry census** — an indirect collect test
  relied on the real 200 ms expiry via the env override and silently became a 60 s wait.
  Mocked-timer idiom: `t.mock.timers.enable({apis: ["setTimeout"]})`, hold the promise, drain
  microtasks with one `setImmediate`, then tick `timeoutMs + WAVE_SETTLEMENT_GRACE_MS`. Keep the
  engine deadline, settlement grace and collect grace (`PERK_WAVE_COLLECT_GRACE_MS`) distinct;
  the inside-grace regression delivers at `deadline + grace − 1`.
- **Stop/proof and reload knobs.** The shared fake takes `stopReply`, `terminalProof`,
  `statusReply: "error"`, records `statuses`, and rebinds via `extension(pi)` on reload (constants
  `FAKE_DEFAULT_TERMINAL_PROOF`, `noLiveRunController`); the memory adapter takes `stopOutcome`,
  `terminalProof`, `proofs` (`MEMORY_DEFAULT_TERMINAL_PROOF`) and answers a never-spawned handle
  like the engine. `awaitedChildEvent` (in `reportWaveRpc.test.ts`) is sent from inside
  `executeSettlement`; `plantFakeSubagentsResponder` (harness) plants `<cwd>/.pi/extensions/*.ts`
  importing the shared fake by absolute path, so headless worker e2e drives run RPC waves offline;
  `classifyThenFinalize` drives the `/address` pair. The reload idiom: enable `t.mock.timers` for
  `setTimeout` only after `loadPerkSession`, drive a bounded tick + `setImmediate` loop, drain the
  orphan transport with `timeoutMs + WAVE_SETTLEMENT_GRACE_MS`; the old activation's `pi.events`
  stale-ctx throw becomes `acknowledged: false` / `unavailable` in the never-throwing adapter.
- **Supplier reason text is DATA.** Assert the class; compose any verbatim expectation from the
  fake's exported constant or ONE test-local constant feeding both input and expectation; fake doc
  comments call their strings samples.
- **Raw-text source pin gotcha.** `reportWaveRpc.test.ts` matches the raw text of
  `rpcAdapter.ts`/`transport.ts`/`reportWave.ts`, comments included, and forbids (among others)
  `stopCause`, `usage`, `totalTokens`, `totalCost`, `costUsd`, `inputTokens`, `outputTokens`,
  `cacheRead`, `cacheWrite`, `.cost`, `timedOut`, `triggerTurn`, `capacity`, `reused` — prose in
  those modules must avoid them; the pin proves it catches known snippets first.
- **Staging a deadline partial.** By output length it does not work (the scout report shape is
  bounded); a `sleep N` first step does.
- **The surviving coverage is public-surfaces-only.** The installed-engine suites
  (`partialSettlementCompat`, the child-execution/plan-bound compat tests, the shared
  `installedEngine` fixture) were deleted with the public-surfaces posture (`pi/subagents.md`
  § "Engine-coupling posture"). What remains: `extension/waves/reportWave.test.ts` (normalization,
  the constant packet, hostile-fields), `extension/waves/reportWaveRpc.test.ts` (the fake-RPC
  round-trip incl. the transport-tier withholding), and `extension/pi/v1/waveIsolation.test.ts`
  (composition at the registered-tool boundary). `lane.<ordinal>` conformance to `RUN_KEY_PATTERN`
  is pinned offline by the audit/harvest/dream wave suites (`laneIdentity.test.ts` pins the
  routing-token fence, not the key pattern); the live legs are the ledger's, re-owed on every engine
  bump.

## Live-proof ledger (dated)

- 2026-07-10 — the PR-review doors' live dogfood (`docs/design/archive/pr-review-doors-dogfood.md`;
  its streaming-mechanics claims are superseded).
- 2026-08-08 (2.3.0) — every flow onto code-owned waves over pi-subagents v1 (`/pr-review` the
  migration template).
- 2026-08-10 — the three browser doors live-confirmed (dedupe, `replace` reshape, typed collect
  aggregates) under the historical held-turn streaming protocol only
  (`docs/design/archive/streaming-doors-dogfood.md`).
- 2026-08-20 (3.1.0) — the draft doors + `start_draft_review_wave`/`collect_draft_review_wave`.
- 2026-09-05 — the 0.65.1 host-peer launch failure
  (`docs/design/archive/pi-subagents-native-baseline-dogfood.md`) resolved on the repo-local
  five-package dev host at `52c4fde5`
  (`docs/design/archive/pi-subagents-native-streaming-dogfood.md`); no consumer/global repair
  claimed.
- 2026-09-10 (3.3.0) — `/pr-review-dynamic` retired wholesale, never run against real pi-subagents;
  its render-then-execute test idiom left with it.
- 2026-09-15/16 (3.4.0) — completion-only waves (bridge off at spawn, the streaming protocol and
  `streamed` disclosures removed, the `perk:wave` marker);
  `docs/design/archive/pi-subagents-0.68.0-reverify.md`: doctor half PASS, browser half not run.
- 2026-09-21 (3.6.0) — stack reviews, reviewer diffs and routing on pinned commits (`PinnedStack`).
- 2026-09-27 (#2557 → #2561) — the simplifier lane dormant → live the same day (the
  dormant-qualifier inventory practice).
- 2026-10-23/24 — Pi 1.1.0 + pi-subagents 0.76.1 certification HELD, W4/W6/W7a FAIL
  (`docs/design/archive/pi-1.1.0-certification.md`); W6 repaired offline
  (`docs/design/archive/pi-subagents-0.76.1-lifecycle.md`).
- 2026-10-25 — Pi 1.4.0 + pi-subagents 0.81.0 certification, verdict PARTIAL
  (`docs/design/archive/pi-1.4.0-certification.md`): live PASS for the review- and draft-wave
  launches (I7b-PR, I7b-plan), both browser doors with the marker observed and N/N annotations
  (X5a, X5b), scout (S3), the deadline partial with the roster-correlated unfinished lane (W6),
  reload → per-activation `no_wave` (W4), cancel + reload-then-stop (W7a); duplicate load with
  zero `no_active_session` (W3, INFO). What no run has observed: § "Watch items / residuals".

## Watch items / residuals

- The module-rendered script's `runs.all(` … `);\nreturn` shape is parsed by ONE shared helper
  (`testing/fakeSubagents.ts`'s `waveScriptItems`) — a renderer output-shape change fails loudly in
  one place.
- **Wave accounting.** The supplier's `results[].usage` and root totals are not owned-run
  attribution (no reuse flag; the `cost` RPC includes the parent), so perk reads none of them and
  wave cost stays `unavailable` (§8.35; the raw-text pin enforces it).
- **Next-bump hazard.** pi-subagents 0.82.0's `autoResume: true` default conflicts with
  per-activation collection — owned by `pi/subagents.md` § "History (dated)" (routed code
  follow-up).
- **Trust posture.** `pr`/`worktree` stay model-relayed (`decodeStartReviewWaveParams` in
  `extension/pi/v1/codeReview/reviewWave.ts` is the single seam to adjust if door-recorded context
  is adopted) while `stack` is bound to `StackPinState`; `bundle_dir` is `run_learn_wave`'s
  analogous model-relayed param.
- pi-subagents is PINNED for consumers (`SUBAGENTS_PACKAGE` in
  `src/perk/convergence/init/settings.py` — read the constant for the current pin; this adapter
  sends the inline script as the RPC spawn key `script`); the guidance is source-re-verified at
  the version recorded by `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`
  (`src/perk/convergence/doctor/checks.py`), and the doctor `subagent-compat` version `warn` is the
  drift tripwire (it never reads the engine's source) — re-verify the adapter on any bump.
- The pre-digest recipe for foreign-seam nodes (read the unimportable dependency's source at plan
  time, pin the envelope as module constants, keep unversioned names advertised-not-pinned) is
  recorded in `pi/subagents.md` — cross-link, don't restate.
- An advisory multi-angle review followed by an immediate land silently converts findings into
  debt — route them explicitly (a follow-up node, or fold into the next node touching the
  module; PR #1910 → plan #1912 is the worked instance). A clean plan-fidelity lane does not
  mean a clean PR (#2000, #1991, #1999).
- The 60 s `WAVE_SETTLEMENT_GRACE_MS` is still verified only under mocked clocks (W6 settled on the
  engine deadline before the grace armed).
- Blocking flows may occupy ~31 min per attempt (`/pr-review` ~62 min worst case with its retry).
- A genuine single-responder `no_active_session` still surfaces only at the ~30 s reply timeout.
- The simplifier's 40,000-char `proposal` cap fails a whole report (`lane-failed`, no retry) when a
  draft cannot be cut under it — no live evidence; cap tuning is an ordinary plan.
- §8.35's lead biconditional (#2583) is contracts drift outside this doc (§ "Lane semantics").

## Cross-references

- `docs/learned/pi/subagents.md` — the upstream pi-subagents mechanics (RPC envelope,
  `outputSchema`, supervisor channel) and the pre-digest recipe
- `docs/learned/workflow/warm-door-commands.md` — the toolGating census + drive-coverage guard
- `docs/learned/pi/tool-loadout.md` — the `registerPerkTool` catalog, postures and the matrix fixture
- `docs/learned/workflow/learn-evidence-pipeline.md` — the `/learn` orchestrator that rides
  `extension/learning/analystWave.ts`
- `docs/learned/workflow/plan-review-flow.md` — the annotation-push module (the sibling
  prompt-discipline-into-code migration)
- `docs/learned/workflow/learn-harvest-dream-core.md` — the dream preflight / reducer-prerequisite
  owner
- `docs/design/archive/pi-1.4.0-certification.md`, `docs/design/archive/pi-1.1.0-certification.md`
  — the live ledger's latest rows
- `extension/waves/reportWave.ts` (the logical tier + the opaque `ReportWave` lifecycle) +
  `waves/transport.ts` (the confined transport tier) + `rpcAdapter.ts` — the operational core
  and its live adapter; `extension/testing/memoryAdapter.ts` — the first-class test double
- `extension/testing/fakeSubagents.ts` — the shared fake responder + `waveScriptItems`
- `extension/authoring/review/draftContext.ts` — the draft pair's flow-owned pending/context
  slots (opaque refs only)
- `extension/waves/prReviewWave.ts`, `adversarialReviewWave.ts`, `draftReviewWave.ts`,
  `reviewClassifierWave.ts`, `objectiveExplorerWave.ts`, `scoutWave.ts`, `simplifyWave.ts` +
  `extension/learning/analystWave.ts`, `audit.ts`, `harvest.ts`, `dream.ts`, `dreamReducer.ts`,
  `dreamAnalysis.ts` — the flow entrypoints
- `extension/waves/laneIdentity.ts` — `orchestrationKey` + the routing-token fence;
  `extension/waves/blockedReports.ts` — `reclassifyBlockedReports`
- `extension/waves/ponytail.ts` — the Ponytail source preflight
- `extension/waves/reportWave.test.ts`, `reportWaveRpc.test.ts`, `extension/pi/v1/waveIsolation.test.ts`
  — the surviving offline coverage
- `extension/pi/v1/codeReview/reviewWave.ts` — the start/collect tool pair (+ `StackPinState`;
  live — the review doors drive it); `extension/pi/v1/codeReview/stack.ts` — the stack door's
  digest check + pin builder
- `src/perk/cli/commands/pr/review_context_cmd.py` — the pinned `review-context` arm
- `extension/pi/v1/simplify.ts` — the simplify doors' installer (two warm doors, no tool)
- `docs/design/pi-subagents-child-execution-policy.md` — the binding record for the two-boolean
  child policy (the constant packet is its producer half)
