// The FIRST 3rd-party plan adapter. A perk-owned, injection-only bridge that re-enables
// `@tombell/pi-plan` as a REAL, selectable plan provider: it bridges that package's free-form prose
// `/plan` surface to perk's canonical produced contract (`plan_save` → `cache.plan-ref`).
//
// INERT BY DEFAULT. This shim is ALWAYS registered in index.ts but does nothing unless the resolved
// `[providers] plan` selection is `tombell-plan` (read fresh per-event, same shape as the plan
// installer). On any non-tombell selection it injects nothing and only strips its own stale
// marker — zero behavior change on the default path.
//
// WHAT IT DOES (and does NOT do):
//   - It injects a hidden (`display:false`, once-only: scan-dedup'd on the marker over the
//     compaction-active window) `perk:plan-adapter-tombell` context that tells the model
//     the foreign `/plan` surface authors a FREE-FORM PROSE plan, and directs it through perk's
//     review-first discipline: keep the draft current with `plan_draft`, then call
//     `plan_review` — which (for any non-plannotator selection, tombell included) runs the
//     first-party in-TUI editor review, and whose APPROVED outcome auto-saves via the
//     `approvalSave` seam. The injection is CONDITIONED: it fires only when perk's read-only gate
//     is active (per the persisted `perk:workflow-state.mode`) OR tombell's own persisted
//     `plan-mode-state` entry says plan mode is enabled — never in an objective-author session
//     (objectiveAuthor.ts owns that authoring context).
//   - The present + `/plan-save` flow is the explicit FAIL-OPEN fallback, not the primary path:
//     it applies when the review reports skipped/unavailable, or when `@tombell/pi-plan`'s own
//     interactive `/plan` `setActiveTools` restriction hides `plan_draft`/`plan_review` from the
//     tool set. `/plan-save` prefers the validated draft artifact and falls back to the
//     `extractPlanMarkdown` transcript scrape (authoring/plan/source.ts) — no new save
//     machinery; the shim only directs flow.
//   - It does NOT own, replace, or duplicate the read-only gate (Invariant 1) and NEVER calls
//     `setActiveTools` / registers a `tool_call` handler. The read-only tier during foreign planning
//     comes from (a) perk's gate, already engaged by the cold-door launch (session_start →
//     syncFromState(handoff.mode=read-only)), and (b) the foreign package's own self-enforcement for
//     ad-hoc interactive `pi --plan`. The shim is purely a prompting bridge.
//   - It does NOT restamp `cache.plan-ref.provider` — a tombell-authored prose plan lands with
//     `provider="github"` exactly like a perk-authored plan (the authoring-provider id lives only in
//     the `[providers] plan` selection; `provider` is the issue storage backend). All downstream
//     stages bind only to the provider-agnostic plan-ref and are unchanged.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { GIST_AUTHOR_STAGE } from "../../../authoring/gist/draft.ts";
import { OBJECTIVE_AUTHOR_STAGE } from "../../../authoring/objective/prose.ts";
import { render } from "../../../substrate/prompts.ts";
import { type BranchEntry, rebuildWorkflowState } from "../../../substrate/workflowState.ts";
import { installInjectedContext } from "../contextInjection.ts";
import { isTombellPlanSelected } from "./selection.ts";

/** The tombell plan-adapter bridge customType (distinct from the `perk:plan-context`). */
export const PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE = "perk:plan-adapter-tombell";
const PLAN_ADAPTER_TOMBELL_MARKER = "[PLAN ADAPTER: TOMBELL]";

/**
 * The bridge prompt: directs the foreign free-form prose `/plan` surface into perk's review-first
 * discipline (mirrors PLAN_AUTHORING_CONTEXT's review-first ending), with the present +
 * `/plan-save` flow as the explicit fail-open fallback. Prompting, NOT enforcement (perk's gate,
 * engaged by the cold-door launch, is the read-only authority). Durable anchors only, no line
 * numbers.
 */
export const PLAN_ADAPTER_TOMBELL_CONTEXT = render("contexts/adapters/tombell-plan.md", {
  marker: PLAN_ADAPTER_TOMBELL_MARKER,
});

/**
 * Whether @tombell/pi-plan's own plan mode is enabled, per the latest `plan-mode-state` custom
 * entry on the branch (the package's persisted state twin — it writes one per toggle via
 * `pi.appendEntry`, latest wins, mirroring its own `session_start` rebuild). Defensive: any
 * missing / malformed entry ⇒ false.
 */
export function isTombellPlanModeEnabled(branch: readonly BranchEntry[]): boolean {
  for (let i = branch.length - 1; i >= 0; i--) {
    const entry = branch[i];
    if (entry?.type !== "custom" || entry.customType !== "plan-mode-state") continue;
    return entry.data?.enabled === true;
  }
  return false;
}

/**
 * Install the tombell plan adapter: an injection-only bridge, inert unless `[providers] plan =
 * "tombell-plan"`. It NEVER touches tool gating / setActiveTools (Invariant 1) and never throws.
 */
export function installTombellPlanAdapter(pi: ExtensionAPI): void {
  // Inject the bridge context while the foreign tombell-plan provider is selected AND a plan
  // authoring mode is on — perk's read-only gate (per the persisted `perk:workflow-state.mode`,
  // the gate's state twin — never the gate object) OR tombell's own persisted `plan-mode-state`
  // entry (the ad-hoc interactive `/plan` arm). Objective-author and gist-author sessions are
  // excepted (objectiveAuthor/gistAuthor own those sessions; mirrors the plannotator adapter's
  // recipe — the tombell REPLACE posture covers the plan surface only). The strip fires when
  // tombell-plan is no longer selected, so the marker never lingers across a deselect; the
  // inject/strip mechanics (active-window dedup, stale-marker strip) live in the shared helper.
  installInjectedContext(pi, {
    customType: PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE,
    flavors: {
      [PLAN_ADAPTER_TOMBELL_MARKER]: () => PLAN_ADAPTER_TOMBELL_CONTEXT,
    },
    select: (ctx, branch) => {
      if (!isTombellPlanSelected(ctx.cwd)) return null;
      const state = rebuildWorkflowState(branch);
      if (state.stage === OBJECTIVE_AUTHOR_STAGE || state.stage === GIST_AUTHOR_STAGE) return null;
      if (state.mode !== "read-only" && !isTombellPlanModeEnabled(branch)) return null;
      return PLAN_ADAPTER_TOMBELL_MARKER;
    },
    live: (ctx) => isTombellPlanSelected(ctx.cwd),
  });
}
