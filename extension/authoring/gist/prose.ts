// The gist feature's model-facing prose units: the two tool-guideline arrays, the
// gist-authoring context content builder, and the injection marker/customType constants.
// Prose-unit MEANING and ORDER live here (the feature); the v1 adapter only PLACES these units
// in Pi registration fields and event payloads (module-contracts.md's prose split). Prompting,
// NOT enforcement — the read-only tool gate is the enforcement.

import { render } from "../../substrate/prompts.ts";

/** The gist-authoring context customType (distinct from planMode's `perk:plan-context`). */
export const GIST_AUTHOR_CONTEXT_TYPE = "perk:gist-author-context";

/** The injected gist-authoring context's identity marker (the strip + dedup key). */
export const GIST_AUTHOR_MARKER = "[GIST AUTHORING]";

/**
 * The gist-authoring session context: live state + pointers only (contracts.md §8.57 — the flow
 * is stated by the launch statement, the detail by the `perk-gist-author` skill). It names the
 * working-draft artifact (`gist_draft`), the review tool (`plan_review`), and the bound skill;
 * it never restates the flow.
 */
export const GIST_AUTHORING_CONTEXT = render("contexts/gist-authoring.md", {
  marker: GIST_AUTHOR_MARKER,
});

/**
 * Build the full gist-authoring injection, appending the project-config authoring addendum when
 * present. Pure over the addendum — the ADAPTER loads `[workflow] plan_authoring` per event and
 * passes the value in (the narrow-views doctrine).
 */
export function gistAuthoringContextContent(addendum: string | undefined): string {
  return addendum ? `${GIST_AUTHORING_CONTEXT}\n\n${addendum.trim()}` : GIST_AUTHORING_CONTEXT;
}

/** The `gist_draft` tool guidelines (verbatim prose units; the adapter places them). */
export const GIST_DRAFT_TOOL_GUIDELINES = [
  "Call gist_draft to persist the current working gist as you author or revise it; pass the FULL prose each time (it rewrites the whole draft).",
  "gist_draft never saves to the issue backend and never ends the turn — gist_save//gist-save remain the canonical save surface.",
  "Pass gist_draft's `scope` only once the consumption tier is settled: `plan` for plan-sized intent, `objective` for objective-sized intent.",
];

/** The `gist_save` tool guidelines (verbatim prose units; the adapter places them). */
export const GIST_SAVE_TOOL_GUIDELINES = [
  "Use gist_save only after the gist says what it means; it creates the tracked gist in the issue backend and ends the turn.",
  "Pass gist_save the statement-of-intent PROSE in `prose` — problem-focused, with at most high-level solution leanings; no implementation steps or roadmap.",
  "Pass gist_save's `scope` only once the consumption tier is settled (plan or objective); omit it to keep the pre-seeded/default scope.",
];
