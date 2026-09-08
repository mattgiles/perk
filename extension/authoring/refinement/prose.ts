// The refinement feature's model-facing prose units: the draft tool's guidelines, the
// refinement session context content builder, and the injection marker/customType constants.
// Prose-unit MEANING and ORDER live here (the feature); the v1 adapter only PLACES these units
// in Pi registration fields and event payloads. Prompting, NOT enforcement — the read-only tool
// gate (its refinement flavor) is the enforcement.

import { render } from "../../substrate/prompts.ts";

/** The refinement context customType (distinct from the plan/objective/gist contexts). */
export const REFINEMENT_CONTEXT_TYPE = "perk:objective-refinement-context";

/** The injected refinement context's identity marker (the strip + dedup key). */
export const REFINEMENT_MARKER = "[OBJECTIVE REFINEMENT]";

/**
 * The refinement session context: live state + pointers only (contracts.md §8.57 — the flow is
 * stated by the launch statement, the detail by the `perk-objective-refine` skill). It names the
 * context artifact, the working-draft tool, the review tool, the human failsafe and the bound
 * skill; it never restates the flow.
 */
export const REFINEMENT_CONTEXT = render("contexts/objective-refinement.md", {
  marker: REFINEMENT_MARKER,
});

/** Build the full injection, appending the project-config authoring addendum when present. */
export function refinementContextContent(addendum: string | undefined): string {
  return addendum ? `${REFINEMENT_CONTEXT}\n\n${addendum.trim()}` : REFINEMENT_CONTEXT;
}

/** The `objective_refinement_draft` tool guidelines (verbatim prose units; the adapter places them). */
export const REFINEMENT_DRAFT_TOOL_GUIDELINES = [
  "Call objective_refinement_draft to persist the current working refinement as you author or revise it; pass the FULL Markdown each time (it rewrites the whole draft).",
  "objective_refinement_draft binds the draft to the session's grounding context for you — it never saves to the issue backend and never ends the turn; plan_review (approval) or the human's /objective-refinement-save persist it.",
  "Name unresolved future assumptions and the code seams as observed at capture time; never present the checkout observation as a freshness guarantee.",
];
