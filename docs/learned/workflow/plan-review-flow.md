---
title: The plan review → approval → save pipeline
read_when: Working on plan_review / a review backend (plannotator, first-party, tombell), the approvalSave seam, plan-source resolution for review vs save, wiring a new review surface's APPROVED/DENIED arms (the approved-first routing split), flavoring the shared first-party review core for a second subject, or changing factory/authoring guidance prose (the three-tier prose mirror).
---

# The plan review → approval → save pipeline

Objective #339 Phase 2 wired plan review into auto-save: `plan_review` resolves the reviewed plan
file-first, an APPROVED verdict auto-saves through one seam, and the review-then-save flow replaced
the old "re-dump the final plan and run /plan-save" instruction. This doc captures the dispatch
shape, the source-tiering law, the gate-ownership seam, and the footguns a new review backend will
hit.

## The backend-neutral review door

`plan_review` lives in `extension/planReview.ts` — moved out of the plannotator adapter. Dispatch:
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

`approvalSave` in `extension/planSave.ts` is the single approval→save orchestration: artifact-first
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
demoted to **DENIED-only** (kept total for safety, never reached with `approved: true`). A third
review subject (e.g. a tombell objective arm) should copy this exact split — the
DENIED-renders-by-default footgun is structural, not incidental.

Residual lie-in-waiting: `objectiveReviewOutcomeResult`'s completed arm still emits
`approved: outcome.approved` in its details (not hardcoded `false`) — harmless today, but
re-routing approved outcomes back through it would render "objective DENIED" text for an approval.

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

## The three-tier prose mirror (factory/authoring guidance)

Factory and authoring guidance lives in three tiers that must move together:

1. **Runtime injected constants** — the source of truth, wording-pinned by tests.
2. **`shared/contracts.md`** — the cross-plane record.
3. **`skills/*/SKILL.md`** — the judgment layer.

Changing one tier without the others is the drift mode (a runtime-tier rewrite that skipped
contracts created drift a later repair node had to close). Facts that make the drift easy to miss:

- **Skill bodies have no content-pinning tests** (`tests/test_packaging.py` asserts presence only),
  so skill rewrites are CI-inert — nothing alarms when the skill tier goes stale.
- A grep hit for an old phrase in a test file may pin a **runtime constant** via `doesNotMatch`,
  not the skill — check the assertion target before assuming a conflict.
- Shipped `skills/<name>/SKILL.md` must stay **consumer-repo-agnostic**: repo-local disciplines
  (e.g. perk's grill addendum in `.pi/perk.toml` `[workflow] plan_authoring`) land in skills as
  generic posture lines, never by naming a repo-local skill.
- Only the tracked `skills/<name>/` sources are editable — `.agents/skills/` is gitignored and
  resynced by `perk init`.

## First-party review mechanics

- **Edit write-back-or-abort:** an edited plan is written back via `plan_draft`'s writer *before*
  the verdict; a write-back failure aborts the review.
- The verdict is a 3-option select, plus a `dismissed` outcome arm.
- **`savePlan` trims the plan before staging the stdin file** — tests asserting the cold-door
  `--plan-file` content must expect the *trimmed* bytes, not the artifact bytes.

## Footguns (each documented at its site; collected here)

1. **`reviewOutcomeResult` is total and its `completed` case unconditionally renders the DENIED
   text** — the execute path must route approved outcomes to `approvedSaveResult` FIRST. A new
   backend that reuses `reviewOutcomeResult` and forgets the approved-first routing renders "plan
   DENIED" for an approval.
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
- `extension/planReview.ts` — the door, `executePlanReview`, the first-party review
- `extension/planSave.ts` — `approvalSave`, `resolvePlanSource`, `savePlan`
- `docs/learned/workflow/plan-save-surfaces.md` — the save-side source resolution + recovery carrier
- `docs/learned/workflow/provider-seam.md` — the plannotator augment-posture provider
- `docs/learned/pi/extension-api.md` — `ctx.ui.editor` facts + the `headfulUIContext` gap
- `docs/learned/pi/tool-param-decode.md` — the tri-state param decode the door's `plan` param uses
- `docs/learned/pi/extension-seams.md` — minimal structural slices + the type-only-import cycle break
