// Feature-owned prose + identity constants for the objective flows — the stage ids the
// providers/doors key off, the objective-authoring context (contracts.md §8.57: live state +
// pointers only; the flow is stated by the launch statement, the detail by the bound skill),
// and the seed guidance the warm doors inject (`/objective-plan`, `/objective-reconcile`,
// `/objective-save`). Everything renders through the shared template seam
// (`substrate/prompts.ts` — a mechanism import, §8.31); branching stays in code.
//
// Pi-free (guard Rule D covers `authoring/` by prefix). Tool-guideline arrays deliberately do
// NOT live here: they stay inline at the `pi/v1` registration sites (the prose-review
// workbench's source-shape constraint).

import { render } from "../../substrate/prompts.ts";

/** The registry stage id of the objective-authoring session (shared with planMode's defer check). */
export const OBJECTIVE_AUTHOR_STAGE = "objective-author";

/** The registry stage id of the structured-save session (`perk objective save`). */
export const OBJECTIVE_SAVE_STAGE = "objective-save";

/** The objective-authoring context customType (distinct from planMode's `perk:plan-context`). */
export const OBJECTIVE_AUTHOR_CONTEXT_TYPE = "perk:objective-author-context";

/** The dedup/strip marker carried by the injected objective-authoring context. */
export const OBJECTIVE_AUTHOR_MARKER = "[OBJECTIVE AUTHORING]";

/**
 * The objective-authoring session context: live state + pointers only (contracts.md §8.57 — the
 * flow is stated by the launch statement, the detail by the `perk-objective-author` skill). It
 * names the working-draft artifact (`objective_draft`), the review tool (`plan_review`), and
 * the bound skill; it never restates the flow. Prompting, NOT enforcement (the tool gate is the
 * enforcement).
 */
export const OBJECTIVE_AUTHORING_CONTEXT = render("contexts/objective-authoring.md", {
  marker: OBJECTIVE_AUTHOR_MARKER,
});

/**
 * Build the full objective-authoring injection, appending the project-config addendum when
 * present. Pure: the adapter passes `loadPerkConfig(cwd).planAuthoring` (the same `[workflow]
 * plan_authoring` addendum the plan-authoring injection consumes — verbatim reuse).
 */
export function objectiveAuthoringContextContent(addendum: string | undefined): string {
  return addendum
    ? `${OBJECTIVE_AUTHORING_CONTEXT}\n\n${addendum.trim()}`
    : OBJECTIVE_AUTHORING_CONTEXT;
}

/**
 * Backend-aware supplemental clause for the objective-read step of the factory prompts.
 * The wording lives in `prompts/common/objective-read/linear.md`, rendered identically by both
 * planes via the shared render seam (contracts.md §8.31); branching stays in code. github (and any
 * non-linear) → "" (the `perk objective show` step already covers it); linear → the Project URL +
 * the linear_get_issue/linear_list_comments tools (an `open <url>` fallback when the url is known).
 */
export function objectiveReadInstruction(
  backend: string,
  objectiveId: string,
  url: string,
): string {
  if (backend !== "linear") return "";
  const where = url ? `(${url})` : `(run \`perk objective show ${objectiveId}\` for its URL)`;
  const fallback = url ? `; if the linear tools are unavailable, open ${url}` : "";
  return render("common/objective-read/linear.md", { where, fallback });
}

/** The seed guidance the warm `/objective-plan` injects to start the factory loop (the
 * perk-objective-plan skill pointer rides the skill-binding suffix — not hardcoded).
 * The loop is file-first (`plan_draft` → `plan_review` → approval-driven save); the node link
 * rides the `objective_node_claim` carrier recorded by the unconditional `planning` mark.
 * The OPTIONAL explore step is ONE `explore_objective_node` call — the tool owns the wave
 * mechanics, the report schema, and reads the configured `[models.subagents] objective-explorer`
 * model at execute time. */
export function factoryGuidance(
  objective: string,
  node: string | null,
  backend = "github",
  url = "",
): string {
  const readClause = objectiveReadInstruction(backend, objective, url);
  return render("stages/objective-plan/guidance.md", {
    objective,
    node: node ?? "",
    read_clause: readClause,
  });
}

/** The seed guidance the warm `/objective-reconcile` injects to start the reconcile pass (the
 * perk-objective-reconcile skill pointer rides the skill-binding suffix — not
 * hardcoded). */
export function reconcileGuidance(objective: string, backend = "github", url = ""): string {
  const readClause = objectiveReadInstruction(backend, objective, url);
  return render("stages/objective-reconcile.md", { objective, read_clause: readClause });
}

/**
 * The seed guidance the warm `/objective-save` injects to drive the structured save (the
 * perk-objective-author skill pointer rides the skill-binding suffix — not hardcoded
 * here). Pure + exported for offline tests.
 */
export function objectiveSaveGuidance(title?: string): string {
  const named = title?.trim() || "";
  return render("stages/objective-save.md", { title: named });
}
