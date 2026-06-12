// Node 2.3 — the FIRST 3rd-party plan adapter. A perk-owned, injection-only bridge that re-enables
// `@tombell/pi-plan` as a REAL, selectable plan provider: it bridges that package's free-form prose
// `/plan` surface to perk's canonical produced contract (`plan_save` → `cache.plan-ref`).
//
// INERT BY DEFAULT. This shim is ALWAYS registered in index.ts but does nothing unless the resolved
// `[providers] plan` selection is `tombell-plan` (read fresh per-event, same shape as planMode). On
// any non-tombell selection it injects nothing and only strips its own stale marker — zero behavior
// change on the default path.
//
// WHAT IT DOES (and does NOT do):
//   - It injects a hidden (`display:false`) `perk:plan-adapter-tombell` context that tells the model
//     the foreign `/plan` surface authors a FREE-FORM PROSE plan, and directs it through perk's
//     review-first discipline (Node 2.6): keep the draft current with `plan_draft`, then call
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
//     `extractPlanMarkdown` transcript scrape (planSave.ts) — no new save machinery; the shim
//     only directs flow.
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
import { OBJECTIVE_AUTHOR_STAGE } from "../factories/objectiveAuthor.ts";
import { resolvedPlanProviderId } from "../factories/planMode.ts";
import { TOMBELL_PLAN_PROVIDER_ID } from "../providers.ts";
import { type BranchEntry, branchOf, rebuildWorkflowState } from "../workflowState.ts";

/** The tombell plan-adapter bridge customType (distinct from planMode's `perk:plan-context`). */
export const PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE = "perk:plan-adapter-tombell";
const PLAN_ADAPTER_TOMBELL_MARKER = "[PLAN ADAPTER: TOMBELL]";

/**
 * The bridge prompt: directs the foreign free-form prose `/plan` surface into perk's review-first
 * discipline (mirrors PLAN_AUTHORING_CONTEXT's review-first ending), with the present +
 * `/plan-save` flow as the explicit fail-open fallback. Prompting, NOT enforcement (perk's gate,
 * engaged by the cold-door launch, is the read-only authority). Durable anchors only, no line
 * numbers.
 */
export const PLAN_ADAPTER_TOMBELL_CONTEXT = `${PLAN_ADAPTER_TOMBELL_MARKER}
You are authoring a plan through the @tombell/pi-plan \`/plan\` surface — a read-only exploration mode
that produces a FREE-FORM PROSE plan (it emits no structured plan and no save tool of its own).

Gather before you plan, then write the plan so an executor with zero prior context can implement it
without guessing: anchor every change durably — function/class names, behavioral descriptions,
structural locations — never line numbers, and resolve every open choice before you save.

perk persists the plan to the provider-agnostic plan reference (cache.plan-ref); the objective/node
linkage and any consumed-learn numbers are recovered automatically from the launch handoff — never
try to write the plan reference yourself.

- Keep the working draft current with the plan_draft tool — the validated plan-draft artifact is
  what gets reviewed AND auto-saved.
- When the plan is decision-complete, call the plan_review tool — the human reviews the draft in
  perk's in-TUI editor review.
- If the review is DENIED: revise per the feedback, rewrite the draft with plan_draft, then call
  plan_review again.
- If the review is APPROVED: the plan is auto-saved and the session leaves read-only. Relay the
  save outcome — do NOT re-dump the plan as a final message and do NOT tell the user to run
  /plan-save.
- If plan_review reports it was skipped or unavailable, OR the plan_draft/plan_review tools are not
  in your tool set (this plan surface restricts tools): write the COMPLETE final plan as your last
  message and present it to the user — the human runs the /plan-save command when satisfied (it
  prefers the validated draft artifact and falls back to scraping your latest message, so that
  final message must be the clean, complete plan and nothing else).`;

/** Whether the foreign `tombell-plan` provider is the selected plan provider for `cwd`. */
export function isTombellPlanSelected(cwd: string): boolean {
  return resolvedPlanProviderId(cwd) === TOMBELL_PLAN_PROVIDER_ID;
}

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
 * Register the tombell plan adapter: an injection-only bridge, inert unless `[providers] plan =
 * "tombell-plan"`. It NEVER touches tool gating / setActiveTools (Invariant 1) and never throws.
 */
export function registerPlanAdapterTombell(pi: ExtensionAPI): void {
  // Inject the bridge context while the foreign tombell-plan provider is selected AND a plan
  // authoring mode is on — perk's read-only gate (per the persisted `perk:workflow-state.mode`,
  // the gate's state twin — never the gate object) OR tombell's own persisted `plan-mode-state`
  // entry (the ad-hoc interactive `/plan` arm). Objective-author sessions are excepted
  // (objectiveAuthor owns that session; mirrors the plannotator adapter's recipe).
  pi.on("before_agent_start", async (_event, ctx) => {
    if (!isTombellPlanSelected(ctx.cwd)) return;
    const branch = branchOf(ctx);
    const state = rebuildWorkflowState(branch);
    if (state.stage === OBJECTIVE_AUTHOR_STAGE) return;
    if (state.mode !== "read-only" && !isTombellPlanModeEnabled(branch)) return;
    return {
      message: {
        customType: PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE,
        content: PLAN_ADAPTER_TOMBELL_CONTEXT,
        display: false,
      },
    };
  });

  // Strip the stale bridge marker from context when tombell-plan is no longer selected (same
  // hygiene planMode/objectiveAuthor/toolGating apply), so it never lingers across a deselect.
  pi.on("context", async (event, ctx) => {
    if (isTombellPlanSelected(ctx.cwd)) return;
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string; role?: string; content?: unknown };
        if (msg.customType === PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE) return false;
        if (msg.role !== "user") return true;
        const content = msg.content;
        if (typeof content === "string") return !content.includes(PLAN_ADAPTER_TOMBELL_MARKER);
        if (Array.isArray(content)) {
          return !content.some(
            (c) =>
              (c as { type?: string; text?: string }).type === "text" &&
              ((c as { text?: string }).text ?? "").includes(PLAN_ADAPTER_TOMBELL_MARKER),
          );
        }
        return true;
      }),
    };
  });
}
