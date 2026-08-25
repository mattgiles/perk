// The plan feature's model-facing prose units: the three tool-guideline arrays, the
// plan-authoring context content builder, and the injection marker/customType constants.
// Prose-unit MEANING and ORDER live here (the feature); the v1 adapter only PLACES these units
// in Pi registration fields and event payloads (module-contracts.md's prose split). Prompting,
// NOT enforcement — the read-only tool gate is the enforcement.
//
// Carve-out doctrine (mirrors `authoring/gist/`): this home is Pi-free (guard Rule D) — the
// adapter passes config-derived values (the `[workflow] plan_authoring` addendum) in as plain
// strings; nothing here reads Pi, the config loader, or the surfaces seam.

import { render } from "../../substrate/prompts.ts";

/** The plan-authoring context customType (distinct from the gate's `perk:mode-context`). */
export const PLAN_CONTEXT_TYPE = "perk:plan-context";

/** The injected plan-authoring context's identity marker (the strip + dedup key). */
export const PLAN_MARKER = "[PLAN AUTHORING]";

/**
 * The cooperative gather-then-plan contract. This is prompting, NOT enforcement (the gate is the
 * enforcement). It never leaks internal policy text — it tells the model how to materialize a
 * decision-complete plan an executor with zero prior context can follow. Per contracts.md §8.57
 * this mode context is the plan stage's DESIGNATED FLOW CARRIER in every plan-stage session
 * shape (seeded doors carry launch-shape deltas only; the `perk-plan` skill is the detail tier).
 * Durable anchors only, no line numbers.
 */
export const PLAN_AUTHORING_CONTEXT = render("contexts/plan-authoring.md", {
  marker: PLAN_MARKER,
});

/**
 * Build the full plan-authoring injection, appending the project-config authoring addendum when
 * present. Pure over the addendum — the ADAPTER loads `[workflow] plan_authoring` per event and
 * passes the value in (the narrow-views doctrine).
 */
export function planAuthoringContextContent(addendum: string | undefined): string {
  return addendum ? `${PLAN_AUTHORING_CONTEXT}\n\n${addendum.trim()}` : PLAN_AUTHORING_CONTEXT;
}

/** The `plan_draft` tool guidelines (verbatim prose units; the adapter places them). */
export const PLAN_DRAFT_TOOL_GUIDELINES = [
  "Call plan_draft to persist the current working draft as you author or revise the plan; pass the FULL plan markdown each time (it rewrites the whole draft).",
  "plan_draft never saves to GitHub and never ends the turn — plan_save//plan-save remain the canonical save surface.",
];

/** The `plan_save` tool guidelines (verbatim prose units; the adapter places them). */
export const PLAN_SAVE_TOOL_GUIDELINES = [
  "Use plan_save only after the plan is decision-complete and the user has agreed; it creates the canonical GitHub plan and ends the turn.",
  "Keep the working draft current with plan_draft — the validated plan-draft artifact is what plan_save saves; the `plan` parameter is only a fallback when no draft exists. Never reference line numbers — use durable anchors (function names, behavioral descriptions, structural locations).",
  "Pass plan_save's consumed_learn (the gathered perk:learn issue ids) only from the learned-docs factory — it links the issues the docs plan consolidates so /land closes + labels them.",
  "When saving an objective-factory plan, pass plan_save BOTH objective_id and node_id — this links the node to the plan and advances it planning → in_progress (no separate backlink call).",
];

/** The `plan_review` tool guidelines (verbatim prose units; the adapter places them). */
export const PLAN_REVIEW_TOOL_GUIDELINES = [
  "Keep the working draft current with plan_draft — the validated plan-draft artifact is what plan_review reviews AND auto-saves; the plan param is only a fallback when no draft exists.",
  "Call plan_review only when the plan is decision-complete.",
  "On a DENIED review, revise per the feedback, rewrite the draft with plan_draft, then call plan_review again.",
  "On an APPROVED plan_review, the plan is auto-saved and the turn ends — never re-dump the plan as a final message and never tell the user to run /plan-save; relay the save outcome instead.",
  "On a wave_launched result (the human opted into the reviewer wave), follow the returned guidance in the same turn — launch the wave and relay its findings; the human's browser decision routes back automatically, so never re-call plan_review while that browser review is open.",
  "If plan_review reports it was skipped or unavailable (headless, dismissed), fall back to presenting the complete plan; the human runs /plan-save (the manual failsafe).",
];
