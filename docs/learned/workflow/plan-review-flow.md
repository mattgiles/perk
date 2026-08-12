---
title: The plan review → approval → save pipeline
read_when: Working on plan_review / a review backend (plannotator, first-party, tombell), the approvalSave seam, plan-source resolution, Plannotator Direct Edits / the diff apply, or the `pi.events` bridge.
cluster: plan-lifecycle
---

# The plan review → approval → save pipeline

Objective #339 Phase 2 wired plan review into auto-save: `plan_review` resolves the reviewed plan
file-first, an APPROVED verdict auto-saves through one seam, and the review-then-save flow replaced
the old "re-dump the final plan and run /plan-save" instruction. This doc captures the dispatch
shape, the source-tiering law, the gate-ownership seam, and the footguns a new review backend will
hit.

## The backend-neutral review door

`plan_review` lives in `extension/factories/planReview.ts` — moved out of the plannotator adapter. Dispatch:
plannotator-selected → the event-bus bridge; **ANY other selection** (including tombell/unknown) →
the first-party `ctx.ui.editor` review. The first-party path is the *default substrate*, not a
fallback of last resort — Node 2.6 (tombell) is only an injected-contract re-aim on top of it.

The cycle-break that made the move possible: `planReview.ts` imports the bridge as a **value** from
`planAdapterPlannotator.ts`; the adapter imports `ReviewOutcome` *type-only* back — erased at
runtime, no cycle. This is the general recipe whenever a vocabulary type moves to a new owning
module that the old module still references (see `pi/extension-seams.md`).

## Asymmetric source tiering is the review-surface law

- **Save surfaces** resolve artifact → param → transcript (see `plan-save-surfaces.md`).
- **Review surfaces** resolve artifact → param **ONLY**.

An approval auto-saves the reviewed bytes, so a transcript scrape must never be what gets approved.
Any future review backend must soft-skip (`reason: "no_plan"` + a `plan_draft` redirect) rather
than fall through to the scrape.

## The approvalSave seam owns the gate exit

`approvalSave` in `extension/factories/planSave.ts` is the single approval→save orchestration: artifact-first
`resolvePlanSource` → `savePlan` → D1a gate exit on success. Review backends call it and must
**NOT** call `gating.enter/exit` themselves — the seam snapshots `isActive()` pre-save and exits
only on success. A `no-plan` outcome saves nothing and leaves the gate untouched; callers render
their own fallback. This is the Invariant-1 "composes, never owns" template for wiring any review
backend.

`terminate` follows the `result.ts` `ok()` convention: key-absent (not `false`) on non-terminating
arms — tests assert `result.terminate === undefined` on the failed arm. Follow the same shape when
new tools propagate the seam's terminate intent.

## The plan↔objective approval-save mirror is complete

Both review subjects now follow the same approval→save shape: **approved-first routing in the
execute path** (`outcome.status === "completed" && outcome.approved` → the save seam → a dedicated
`approved*SaveResult` renderer), with the generic `*ReviewOutcomeResult` mapper's `completed` case
demoted to **DENIED-only** (kept total for safety, never reached with `approved: true`). The four
renderers are thin delegators over module-private shared cores (`subjectReviewOutcomeResult` /
`approvedSubjectSaveResult` in `planReview.ts`) parameterized by a `ReviewSubject` descriptor
(noun, redirect names, `detailsExtra`). A third review subject (e.g. a tombell objective arm)
constructs its own descriptor and reuses the cores — but the approved-first routing split in its
**execute path** is still mandatory: the DENIED-renders-by-default footgun is structural in the
execute paths, not the renderers.

Residual lie-in-waiting: the shared completed arm emits `approved: outcome.approved` in its
details (not hardcoded `false`) — deliberately behavior-preserving, and now confined to exactly
one site (the consolidated core). Harmless today, but re-routing approved outcomes back through
the mapper would render the DENIED text for an approval.

## Flavoring the shared first-party core

`runFirstPartyReview` serves both subjects via **optional presentation params**
(`editorTitle?`/`verdicts?`/`viewOnly?`) whose defaults keep the plan path byte-stable — the proof
being that every pre-existing first-party test stayed untouched. When extending a shared
interactive core for a second consumer, prefer optional presentation options + the
"existing tests unchanged" byte-stability proof over forking the core.

The objective arm's **asymmetric param handling**: in an objective-author session a *well-typed*
`plan` param is silently ignored (the draft artifact is the SOLE source — no param tier, no
transcript tier), but a *mistyped* one still strict-fails `bad_input`, because param decode runs
**before** the stage branch. That decode-first order is pinned by a test — preserve it when
reworking either arm.

Under `viewOnly`, the editor's return value must **never** be the save source — the seam re-reads
the artifact at save time (tests pin this by asserting the cold-door body file equals the
artifact's prose, not the editor return).

## The prose layering (§8.57: one canonical carrier per statement)

Factory and authoring guidance follows the single-statement-of-contract layering rule
(`shared/contracts.md §8.57`): per stage, each contract statement has exactly **one canonical
carrier** — the launch statement carries the flow, the injected context carries live state +
pointers, the adapter block carries only the provider's surface delta, and the bound skill is
the read-on-demand **detail tier that points back** at the flow, never restating it. The
surviving lockstep obligations are narrower than the old move-together doctrine: **runtime
injected constants stay wording-pinned by tests** (rewire the pins in the same change), and a
cross-plane *behavior* change still amends `shared/contracts.md` in the same turn. Facts that
make residual drift easy to miss:

- **Skill bodies have no content-pinning tests** (`tests/test_packaging.py` asserts presence only),
  so skill rewrites are CI-inert — nothing alarms when the skill tier goes stale.
- A grep hit for an old phrase in a test file may pin a **runtime constant** via `doesNotMatch`,
  not the skill — check the assertion target before assuming a conflict.
- Shipped `skills/<name>/SKILL.md` must stay **consumer-repo-agnostic**: repo-local disciplines
  land in skills as generic posture lines, never by naming a repo-local skill. (The grill
  discipline — formerly perk's repo-local `[workflow] plan_authoring` addendum — now ships as
  `skills/perk-grill`, which the stage skills point at; a shipped skill naming another shipped
  skill satisfies the rule.)
- Only the tracked `skills/<name>/` sources are editable — `.agents/skills/` is gitignored and
  resynced by `perk init`.

## The `PLAN_AUTHORING_CONTEXT` nudge seam (#700)

The "consult learnings before planning" nudge is a concrete instance of the authoring-guidance prose
above. `PLAN_AUTHORING_CONTEXT` (exported in `extension/factories/planMode.ts`) is built into the
final injection by `planContextContent(cwd)`, which appends the optional `[workflow] plan_authoring`
config addendum. The prose itself now lives in `prompts/contexts/plan-authoring.md` (the constant
remains the exported render product, with the marker passed as a render var) — the edit lockstep's
first surface is the **template**, not an inline literal. Fixed shape: `[PLAN AUTHORING]` marker → the "Gather before you plan" four-category
list → free-form middle → "Write the plan so an executor…" → the review-first ending. **Insert new
guidance between the gather list and the executor paragraph.**

- **One seam reaches BOTH plan factories.** Interactive `perk plan` AND objective-node sessions both
  receive it — node-planning borrows the shared `plan` stage. The foreign-provider bridge seed
  prompts (`PLAN_ADAPTER_TOMBELL_CONTEXT` / `PLAN_ADAPTER_PLANNOTATOR_CONTEXT`) are **SEPARATE**,
  already diverge, and have **no byte-parity test** — they need their own edit if mirrored.
- **Lockstep for editing this constant:** the `prompts/contexts/plan-authoring.md` template
  (the constant's prose source) and an **additive** substring assertion in `planMode.test.ts`
  (the `planContextContent` test) — add one new `assert.match` to pin new content. (The
  `perk-plan` skill is the §8.57 detail tier, not an SSOT mirror — it points back at the flow.)
- **Design rationale (a soft nudge, not a gate).** The read-only bash gate was a red herring (`read`
  on `docs/learned/*.md` is always allowed); the gap was that nothing *instructed* consulting them. A
  structural forcing-function (a required "learnings consulted" field) was rejected as
  weakest-guarantee-for-most-cost; the "there may be nothing relevant … does not need to be grounded"
  sentence keeps it a **check, not a grounding mandate.**

## First-party review mechanics

- **Edit write-back-or-abort:** an edited plan is written back via `plan_draft`'s writer *before*
  the verdict; a write-back failure aborts the review.
- The verdict is a 3-option select, plus a `dismissed` outcome arm.
- **`savePlan` trims the plan before staging the stdin file** — tests asserting the cold-door
  `--plan-file` content must expect the *trimmed* bytes, not the artifact bytes.

## Plannotator Direct Edits — the prose-diff apply

- **The format is prose, not an API.** The reviewer's edits arrive inside the existing `feedback`
  string: a `# Direct Edits` heading + preamble + a ```` ```diff ```` fence containing a jsdiff
  `createTwoFilesPatch(…, {context: 3}).trimEnd()` patch against the exact bytes perk submitted;
  annotations follow after `\n\n---\n\n`. Format pin: plannotator
  `packages/editor/directEdits.ts` @ v0.26.1 — a version-pinned prose contract, re-verify on
  plannotator upgrades.
- **The per-arm asymmetry.** Plan arm on APPROVE: mechanical apply — `extractDirectEdits` (strict
  fence parse, `extension/adapters/planAdapterPlannotator.ts`) → `applyUnifiedDiff`
  (`extension/substrate/unifiedDiff.ts` — the THIRD vendored zero-runtime-dep engine after
  miniYaml/miniJinja; returns null on any anomaly) → `writePlanDraft` write-back → save the
  EDITED bytes with `edited: true` and remainder-only feedback. Objective arm on APPROVE with a
  Direct Edits section: **no save** — the save seam re-reads the STRUCTURED draft, so
  rendered-markdown edits can't fold back mechanically; instead a non-terminating revise round
  (`status: "revise"`, `reason: "direct_edits"`, gate untouched) routes an `objective_draft`
  fold-in + a confirming re-review. Gist arm on APPROVE with a Direct Edits section: the same
  no-save fold-and-re-review shape, but **field-aware** — the model folds each hunk into the
  matching `gist_draft` field (a `# <title>` heading hunk → `title`, a `Scope:` line hunk →
  `scope`, prose hunks → `prose`), then re-reviews to confirm. DENY stays model-mediated on all
  arms.
- **The fail-open ladder is the design posture for prose-formatted foreign data.** Every
  mechanical rung (parse / apply / write-back) degrades to the pre-feature verbatim behavior; a
  seen-but-unhonorable heading adds a loud warning + `details.direct_edits_applied: false`.
  Strictness is the safety mechanism: a lenient apply could save bytes the reviewer never
  approved, which is worse than declining.
- **The `trimEnd()` leniency.** plannotator embeds `patch.trimEnd()` in the fence, so trailing
  whitespace-only context lines of the final hunk may be trimmed away; the applier reconstructs
  them from the base (context bytes ARE base bytes) and verifies each is whitespace-only.
  Generator-parity tests keep jsdiff as a **dev-only** dependency (mirroring the miniYaml ↔
  `yaml` recipe) to pin compatibility with the exact generator, including this arm.
- **The write-back-then-save discipline generalizes:** the plannotator apply replays the
  first-party pre-verdict write-back post-verdict (the bridge only reports the diff) — reviewed
  bytes == artifact bytes == saved bytes holds on every path that saves.
- **Dependency note:** `@types/diff` is a deprecated stub — `diff@8` ships its own types; never
  spec `@types/diff` again (only `diff` itself, dev-only, is in `package.json`).

## The plannotator plan-review bridge — abort lifecycle + the browser engine

- **An already-aborted `AbortSignal` never fires a newly-added `"abort"` listener.** Any code
  shaped entry-`signal.aborted`-check → `await` something → register an abort listener must
  **re-check `aborted` at the registration point** — the entry check does not cover the await
  window, and the listener will not retro-fire. In the bridge
  (`extension/adapters/planAdapterPlannotator.ts`) this wedged the open-ended decision wait
  forever when an abort landed during the bounded handshake await; the re-check is pinned by its
  "an abort during the pending handshake registers no listener" test (PR #1459).
- **Planning corollary:** a "byte-stable refactor" claim is intent, not proof — restructuring
  listener lifecycles (persistent map → per-request unsubscribe) is exactly what exposes latent
  races the old shape masked. Welcome small behavior deltas that are bug fixes; pin them with
  their own tests rather than forcing byte-stability.
- **Pin the wiring, not just the constants.** The two flavor-unique readiness routes (`/api/diff`
  code-review-only, `/api/plan` plan-server-only) are exported constants so a probe can never
  false-positive against the wrong server flavor — but a constants-only pin passes even if the
  wrappers swap routes. When a generic engine (`startPlannotatorSurface<T>` in
  `extension/doors/plannotatorHandoff.ts`) takes per-flavor parameters, add one test mocking
  `globalThis.fetch` that exercises the real default wiring end-to-end (each wrapper hands the
  engine its own route).
- **Consumers:** `startPlannotatorPlanReview` is consumed by the `/plan-review-browser` door
  (`extension/doors/planReviewBrowser.ts`). Route/envelope/bind-order pins
  are at `@plannotator/pi-extension@0.26.4`; drift degrades loudly (readiness `timeout` /
  handshake `unavailable`), never silently.

## Summoned background review doors — three race classes the blocking path doesn't have

Unlike the model-called `plan_review` (a blocking wait), the `/plan-review-browser` door
(`extension/doors/planReviewBrowser.ts`) leaves the session **live while the human decides in
the browser**. That structural difference creates three race classes beyond the two edges the
plan explicitly accepted (double-open stale-clear; early decision mid-wave):

1. **Stale-draft race (APPROVE).** `approvalSave` resolves the *live* artifact, so a `plan_draft`
   write landing during the open-ended browser wait would save bytes the human never approved.
   The APPROVE arm must re-read the validated artifact and proceed only when the live bytes equal
   the bytes captured at open; mismatch/missing → loud stale refusal — nothing saved, gate
   untouched, a re-review notice injected.
2. **Degrade/decision race.** The readiness observer and the decision task are *independent*
   background tasks over one bridge; clearing primed surfaces on degrade does NOT stop the
   decision task, so a false-negative readiness probe followed by a real human decision would
   route into the save path anyway. Two background tasks sharing one bridge need a **shared
   mutable liveness token** (`PlanReviewDoorSession.degraded`), not just surface clears — the
   degrade arm flips it, and the decision task ignores a post-degrade decision *loudly*.
3. **Provenance laundering (feedback re-injection).** Browser feedback can carry
   reviewer-wave-originated content; injecting it verbatim as a user turn launders
   machine-generated text into implementation guidance. Wrap reviewer-originated feedback in
   `<untrusted_reviewer_feedback>` delimiters with a DATA-not-instructions note — the fallback
   when structured provenance filtering isn't available because feedback is a composed string.

**The meta-rule:** when a plan *explicitly accepts* some race edges, that acceptance list is a
prompt to enumerate the adjacent races — the missed ones sat right beside the accepted ones.

**Inheritance:** any future "open-ended background decision + live session" door (the
objective-review sibling first) inherits all three and must replicate the byte-compare guard,
the liveness token, and the delimiting.

The objective sibling shipped as a **twin door**, and its duplication decisions held with no
friction: module-private delimiter helpers duplicated, a local door-session twin, and a
rule-of-three deferral of a generic door core — **the third door (gist) is the extraction
trigger**.

## Footguns (each documented at its site; collected here)

1. **The shared outcome-mapper core (`subjectReviewOutcomeResult`, behind `reviewOutcomeResult` /
   `objectiveReviewOutcomeResult`) is total and its `completed` case unconditionally renders the
   DENIED text** — the execute path must route approved outcomes to the approved-save renderer
   FIRST. A new backend that reuses the mapper and forgets the approved-first routing renders
   "plan DENIED" for an approval.
2. **`SKIP_TEXT` covers only the headless arm.** Re-introducing a "not configured" skip would
   resurrect the deleted not-plannotator-selected arm and dead-code the first-party path.
3. **Guard ordering:** the objective-author soft-skip guard sits AFTER the not-selected/headless
   skips and checks only `stage` (not `mode`) — inserting guards before the selection skip changes
   default-path results.
4. **`approvedSaveResult`'s `edited` detail is optional (`edited?: boolean`)**, keeping every
   no-edit call site byte-stable — the additive-details intent decides such signatures.

## Testing recipes

- **Dialog flows are untestable through the harness** (`headfulUIContext` has no
  `editor`/`select`) — test via the extracted `executePlanReview` core with a fake ctx carrying a
  scripted `PlanReviewUI` (the askUser.ts pure-core recipe). The registered-tool path can only be
  harness-tested for arms that never reach a dialog (headless / bad_input / no_plan / bridge).
- **Type injected dependencies as the minimal structural slice** (e.g. `{ review(plan, signal) }`),
  not the concrete bridge — a recording fake bridge (canned `ReviewOutcome` + a reviewed-plans
  capture) collapses bus + envelope + timers per test.
- An in-memory `exec` recorder (the planSave.test.ts `fakeApprovalPi` recipe, with `PERK_NO_LLM=1`
  pinned per-test) asserts cold-door argv (`plan-save`/`--json`/`--plan-file`) fully offline — no
  scaffolded fake binary, no harness session.
- **Forcing a `writePlanDraft` failure:** a branch with no `run_id` fails the artifact-tier
  write-back (`no_run_id`) while a `plan` *param* still resolves as the review source (the artifact
  tier needs run_id; the param tier doesn't) — a clean lever for the write-back-failure arm.
- **Prompt-rewrite testing discipline:** design negative asserts *together with* the replacement
  prose — choose unique anchors for the retired sentence while wording the survivor, so the
  `doesNotMatch` pins stay meaningful (a naive pin on a shared phrase collides with the surviving
  sentence). And when a feature is "covered by construction" (A calls B, both tested separately),
  still add the one **composition test** for the path real sessions take — claim recovery was
  proven on the `plan_save` tool path and `approvalSave`'s mechanics separately, yet no test drove
  `approvalSave` with a claim present until the gap was named.
- **The pure-fake `approvalSave` recipe extends to workflow-state preconditions:** seed the
  branch's workflow-state entry data (e.g. `{ run_id, objective_node_claim }`), drive
  `approvalSave` with the fake pi + reportable ctx over the same live branch array, then assert
  post-state via `rebuildWorkflowState(branch)` — no harness/session needed even for
  claim-clear read-back, because the fake `appendEntry` lands on the branch the ctx reads.
- **A gate test must make the tested gate the only refusing gate.** Seed state satisfying every
  downstream gate and assert the gate-*specific* message — the `/plan-review-browser`
  headless-gate test originally used no draft, so removing the headless gate would fall through
  to the no-draft refusal and still pass.
- **Pin deliberately asymmetric cleanup semantics.** When one direction of a lifecycle is
  intentionally NOT mirrored (priming the draft-review context resets the pending wave; clearing
  must *leave* a launched wave collectable — the early-decision edge), pin the non-behavior
  explicitly: a "natural" symmetric cleanup change would orphan in-flight reports without
  failing tests.
- **A precedence/ordering pin is only real when the deprioritized branch's trigger condition is
  simultaneously true.** The Direct-Edits-before-stale-guard order was implemented correctly but
  initially tested with the live artifact equal to the open-time baseline — swapping the check
  order would still pass. The real test lands a concurrent draft write *then* routes an
  APPROVE-with-Direct-Edits.
- **Unit tests of an extracted decision core don't prove the caller's threading.** Direct
  decision-routing tests with a manually-supplied raw artifact pass even if the command threads
  rendered markdown instead of raw artifact bytes as the stale baseline (making every real
  approval stale-refuse) — each critical data-threading seam needs one harness-level
  command→open→decision composition test.

## The second event-bus bridge: the `code-review` request (`plannotatorHandoff.ts`)

The plannotator browser code-review doors (today `/pr-review-browser`; originally
`/pr-review-local`, retired) open plannotator's browser **code-review** UI — the **second**
plannotator event-bus bridge (after `plan_review`'s `createPlannotatorBridge`; the bridge now
lives in `extension/doors/plannotatorHandoff.ts`) and the reusable cross-extension pattern:

- **Cross-extension invocation has no API — speak the published event bus.** pi exposes no way for
  one extension to invoke another's slash command (`sendUserMessage` sends model text;
  `steer`/`followUp` *error* on slash commands). To reuse plannotator's review UI, perk emits a
  `plannotator:request` on the in-process `pi.events` bus — the same mechanism the plan-review bridge
  uses. This is now the reusable pattern for "trigger another loaded extension's behavior."
- **The `code-review` envelope differs from `plan-review` — single-response, no handshake** (pinned
  against a specific `@plannotator/pi-extension` version in the bridge's comment). For
  `action: "code-review"` plannotator resolves **once** with the final
  `{ approved, feedback?, annotations? }`: no fast handshake, no `reviewId` channel, no timeout.
  Consequences — the bridge is simpler (emit once, resolve on the single response; no pending
  registry); because there is no handshake, perk **gates on presence up front**
  (`pi.getCommands().some(c => c.name === "plannotator-review")` — the bare command name; detection is
  independent of the selected plan provider) and awaits the (possibly long) review in the
  **background** (`void (async () => {...})()`) so the session isn't blocked for the whole review.
- **Feedback routing** reuses submit.ts's idle-vs-streaming pattern (`ctx.isIdle()` →
  `sendUserMessage` vs `deliverAs: "followUp"`), and a short perk-authored triage suffix is appended
  **only when `annotations.length > 0`** (a platform PR approve/comment action returns an empty
  annotation set — don't tell the agent to "address" a platform action).
- **Mechanics that held:** a new read-only cold-door worker `perk pr url` (`{pr:{number,url}}`, exit
  0/1/2) mirrors `pr review-context`'s resolution path; registering a new `pr` worker is the
  established 3-edit recipe (import + `mark_kind(..., "worker")` + `pr_group.add_command(...)`) plus
  the alphabetically-sorted `EXPECTED_SURFACE` entry. The door is a plain warm command (no
  registry stage, no model tool) → no `shared/registry.yaml` / `READ_ONLY_TOOLS` change; all UI
  via `report()` so `surfacesGuard` stays green. (The tsc combined-literal-discriminant
  `||`-narrowing gotcha hit here is recorded in `toolchain/biome.md`.)

## The annotation-push module (`push_annotations`)

The flow-scoped `push_annotations` tool (`extension/doors/annotationPush.ts`) — live in review
mode behind the `/pr-review-browser` door's prime/clear lifecycle, and in plan mode behind the
`/plan-review-browser` and `/objective-review-browser` doors (which prime `mode: "plan"`) —
owns the finding→annotation mechanics for **both** plannotator modes
(review: line-anchored; plan: phrase-anchored drafts) — the browser-review curl cheat sheet
retired into code. Its
state-machine invariants (send-time dedupe against settled state, zero-item pending clears
staying visible, retained cross-source alternates, the exact-201 success bar) live in the
**module header comment** — point there, don't restate them.

The cross-cutting lesson: **hold-and-accumulate designs (pending queue + settled ledger +
per-source replace) break at the *compositions* of pending and settled state, not in the
per-component specs.** A plan that fully specifies each component still under-specifies their
interactions — the initial faithful implementation had four major defects, all emergent
pending×settled interactions. Make held-vs-settled interactions the **primary review surface**
for any similar queue+ledger+replace design.

Residuals: the plan-mode finding contract's bind to the draft-reviewer report schema is now
consumed live and pinned by the def↔schema lockstep tests (`draftReviewWave.test.ts` — a
vocabulary mismatch is a test failure now, not a silent break); plannotator version drift is
detected only at push time as `push_rejected` — loud but late, by design.

## Residual risks

- The editor-dialog UX (long-plan scrolling, the Ctrl+G `$EDITOR` round-trip) is
  automation-untested — pinned only by the pi type contract; see `pi/extension-api.md` for the
  `ctx.ui.editor` facts.
- ~~`PLAN_ADAPTER_TOMBELL_CONTEXT` re-aim~~ — Node 2.6 landed (PR #404): the tombell context now
  speaks review-first, with present + `/plan-save` as its explicit fail-open arm (see contracts
  §8.10 / §8.23).

## Sources

- Issues #379, #383, #388, #401 (plans #374, #380, #384, #390 → PRs #377, #382, #386, #396)
- Issues #424, #433, #434, #444 (plans #422, #427, #430, #437 → PRs #423, #431, #432, #441)

## Cross-references

- `shared/contracts.md` §8.23 — the consolidated file-first plan contract (the three backends)
- `extension/factories/planReview.ts` — the door, `executePlanReview`, the first-party review
- `extension/factories/planSave.ts` — `approvalSave`, `resolvePlanSource`, `savePlan`
- `extension/substrate/unifiedDiff.ts` — the strict vendored unified-diff applier (Direct Edits)
- `extension/adapters/planAdapterPlannotator.ts` — `extractDirectEdits`, the Direct Edits format pin
- `docs/learned/workflow/plan-save-surfaces.md` — the save-side source resolution + recovery carrier
- `docs/learned/workflow/provider-seam.md` — the plannotator augment-posture provider
- `docs/learned/pi/extension-api.md` — `ctx.ui.editor` facts + the `headfulUIContext` gap
- `docs/learned/pi/tool-param-decode.md` — the tri-state param decode the door's `plan` param uses
- `docs/learned/pi/extension-seams.md` — minimal structural slices + the type-only-import cycle break
