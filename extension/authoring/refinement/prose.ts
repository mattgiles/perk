// The refinement feature's model-facing prose units: the draft tool's guidelines, the
// refinement session context content builder, and the injection marker/customType constants.
// Prose-unit MEANING and ORDER live here (the feature); the v1 adapter only PLACES these units
// in Pi registration fields and event payloads. Prompting, NOT enforcement — the read-only tool
// gate (its refinement flavor) is the enforcement.

import { render } from "../../substrate/prompts.ts";
import { objectiveReadInstruction } from "../objective/prose.ts";
import type { RefinementContext } from "./context.ts";

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

/** The re-refinement note (byte-identical to the cold door's `_PRIOR_NOTE`). */
const PRIOR_NOTE =
  "A valid prior refinement already exists on this node — the context carries its FULL " +
  "Markdown; you are re-refining, and a save replaces it whole (full-content replacement).";

/**
 * The shared cold/warm refinement flow prompt (`stages/objective-refine/seed.md`) rendered for
 * the warm `/objective-refine` entry from the VALIDATED context: the objective title + node
 * description ride inside `<untrusted_objective>` as DATA; the only door-derived interpolations
 * are identifiers, the read clause and the session-data path of the context artifact.
 */
export function refinementGuidance(context: RefinementContext, contextPath: string): string {
  const t = context.target;
  return render("stages/objective-refine/seed.md", {
    number: context.objective.id,
    title: context.objective.title,
    node_id: t.identity.node_id,
    node_description: t.source.description,
    read_clause: objectiveReadInstruction(
      t.identity.backend,
      context.objective.id,
      context.objective.url,
    ),
    context_path: contextPath,
    prior_note: context.prior !== null ? PRIOR_NOTE : "",
  });
}

/**
 * The refusal every plan-graph surface renders when invoked inside a refinement session
 * (contracts.md §8.67 isolation): the surface names itself; the text names the only two
 * legitimate exits. Pure.
 */
export function refinementStageRefusal(surface: string): string {
  return (
    `${surface} is not available in an objective-refine session — a refinement never creates ` +
    "a plan, claims a node, or changes node/objective state. Author with " +
    "objective_refinement_draft and review with plan_review; the human saves with " +
    "/objective-refinement-save."
  );
}
