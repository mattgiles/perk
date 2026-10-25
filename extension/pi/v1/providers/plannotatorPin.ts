// The ONE `@plannotator/pi-extension` version every perk mirror of a Plannotator surface was last
// re-verified against. perk speaks Plannotator only through published surfaces it re-states
// locally; this header is the single ledger of those mirrors — upstream file + anchors → perk home:
//
//  - plan-review event envelope: `plannotator-events.ts` (`PLANNOTATOR_REQUEST_CHANNEL`,
//    `PLANNOTATOR_REVIEW_RESULT_CHANNEL`, `PlannotatorPlanReviewPayload`,
//    `PlannotatorPlanReviewStartResult`, `PlannotatorReviewResultEvent`, the `PlannotatorResponse`
//    handled/unavailable/error union) → `plannotator.ts` (`requestPlannotatorPlanReview`);
//  - Direct Edits feedback format: upstream `packages/editor/directEdits.ts`
//    (`buildDirectEditsSection`, `composeFeedbackWithDirectEdits`; NOT shipped in the npm package
//    — re-read it in the upstream repository at the pin's release tag) → `plannotator.ts`
//    (`extractDirectEdits`, `DIRECT_EDITS_HEADING`);
//  - code-review event envelope: `plannotator-events.ts` (`PlannotatorCodeReviewPayload` incl.
//    `prUrl`/`cwd`/`diffType`/`defaultBranch`/`patchFile`, `PlannotatorCodeReviewResult`
//    `approved`/`feedback`/`annotations`, plus the code-review session decision's `exit`)
//    → `plannotatorHandoff.ts`;
//  - readiness routes: `server/serverReview.ts` serves `/api/diff` and not `/api/plan`;
//    `server/serverPlan.ts` serves `/api/plan` and not `/api/diff` → `plannotatorHandoff.ts`
//    (`CODE_REVIEW_READINESS_PROBE_PATH`, `PLAN_REVIEW_READINESS_PROBE_PATH`);
//  - port selection: `server/network.ts` (`getRemoteOverride`, `isRemoteSession`,
//    `getServerPortConfiguration`, `DEFAULT_REMOTE_PORT`) and `generated/port-range.ts`
//    (`parsePortSelection`) → `plannotatorPort.ts` (`isPlannotatorRemoteSession`,
//    `parsePortSelection`, `resolvePlannotatorPorts`, `PLANNOTATOR_DEFAULT_REMOTE_PORT`).
//
// Additive upstream fields perk neither sends nor consumes (e.g. the plan payload's
// `planFilePath`, the review result's `answersOnly`, the code-review result's `platform`) do not
// change a row — each row pins the subset perk relies on.
//
// THE RULE: the pin moves only when EVERY ledger row has been re-read against the source at the
// new version. A row that cannot be re-verified holds the pin where it is (the honest old stamp) —
// never move the pin over an unverified row. The prose carriers (`shared/contracts.md`,
// `docs/user-docs/reference/requirements-and-compatibility.md`,
// `skills/perk-expert/references/providers-and-backends.md`) name this exact version;
// `plannotatorPin.test.ts` fails when they drift. The stack-review browser's Plannotator FLOOR
// (≥ 0.27.16 — the first release carrying `patchFile`) is a different fact and is not this pin.

/** The `@plannotator/pi-extension` version every ledger row above was last re-verified against. */
export const PLANNOTATOR_MIRROR_PIN = "0.28.30";
