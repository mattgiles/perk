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
//     the foreign `/plan` surface authors a FREE-FORM PROSE plan, and that when the plan is
//     decision-complete it must be PRESENTED to the user as the final message; the human persists
//     it through perk's canonical save (the `/plan-save` command — which scrapes the latest plan
//     prose) so it lands at the provider-agnostic `cache.plan-ref`, carrying any objective/node/
//     consumed-learn the cold door stashed in the handoff. The mechanical prose→plan-ref bridge is the EXISTING `/plan-save`
//     `extractPlanMarkdown` scrape (planSave.ts) — no new save machinery; the shim only directs flow.
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
import { resolvedPlanProviderId } from "./planMode.ts";
import { TOMBELL_PLAN_PROVIDER_ID } from "./providers.ts";

/** The tombell plan-adapter bridge customType (distinct from planMode's `perk:plan-context`). */
export const PLAN_ADAPTER_TOMBELL_CONTEXT_TYPE = "perk:plan-adapter-tombell";
const PLAN_ADAPTER_TOMBELL_MARKER = "[PLAN ADAPTER: TOMBELL]";

/**
 * The bridge prompt: directs the foreign free-form prose `/plan` surface into perk's produced
 * contract. Prompting, NOT enforcement (perk's gate, engaged by the cold-door launch, is the
 * read-only authority). Durable anchors only, no line numbers — mirrors PLAN_AUTHORING_CONTEXT.
 */
export const PLAN_ADAPTER_TOMBELL_CONTEXT = `${PLAN_ADAPTER_TOMBELL_MARKER}
You are authoring a plan through the @tombell/pi-plan \`/plan\` surface — a read-only exploration mode
that produces a FREE-FORM PROSE plan (it emits no structured plan and no save tool of its own).

Gather before you plan, then write the plan so an executor with zero prior context can implement it
without guessing: anchor every change durably — function/class names, behavioral descriptions,
structural locations — never line numbers, and resolve every open choice before you save.

When the plan is decision-complete, write the COMPLETE final plan as your last message and present
it to the user for review — do NOT attempt to save it yourself. The user runs the /plan-save
command when satisfied: it scrapes your latest message (so that final message must be the clean,
complete plan) and persists it to the provider-agnostic plan reference (cache.plan-ref). perk
records the saved plan and links this session to it; the objective/node linkage and any
consumed-learn numbers are recovered automatically from the launch handoff. Do not try to write the
plan reference yourself — only the /plan-save save path produces it.`;

/** Whether the foreign `tombell-plan` provider is the selected plan provider for `cwd`. */
export function isTombellPlanSelected(cwd: string): boolean {
  return resolvedPlanProviderId(cwd) === TOMBELL_PLAN_PROVIDER_ID;
}

/**
 * Register the tombell plan adapter: an injection-only bridge, inert unless `[providers] plan =
 * "tombell-plan"`. It NEVER touches tool gating / setActiveTools (Invariant 1) and never throws.
 */
export function registerPlanAdapterTombell(pi: ExtensionAPI): void {
  // Inject the bridge context while the foreign tombell-plan provider is selected (display:false).
  pi.on("before_agent_start", async (_event, ctx) => {
    if (!isTombellPlanSelected(ctx.cwd)) return;
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
