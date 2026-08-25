// The plan feature's model-facing prose units: the plan-authoring context content builder and
// the injection marker/customType constants. Prose-unit MEANING lives here (the feature); the
// v1 adapter only PLACES these units in Pi context payloads (module-contracts.md's prose
// split). The tool registration prose (descriptions + promptGuidelines) deliberately stays
// INLINE at the `pi/v1/plan.ts` registration sites — the prose-review workbench edits
// registration prose through the TypeScript source adapter, which needs literal in-place
// arrays (an identifier indirection is an unsupported source shape there). Prompting, NOT
// enforcement — the read-only tool gate is the enforcement.
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
