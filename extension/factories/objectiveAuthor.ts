// Objective-authoring context injection (the objective mirror of planMode's plan-authoring
// half). A `perk objective author` cold launch opens a READ-ONLY session whose handoff `stage` is
// `objective-author`; this module injects the objective-authoring contract under its own
// `perk:objective-author-context` customType, keyed off (read-only gate AND stage ===
// objective-author), optionally extended by the same `[workflow] plan_authoring` addendum the
// plan-authoring injection consumes (verbatim reuse, read per-event via loadPerkConfig). planMode.ts defers when the stage is objective-author, so exactly one
// authoring context is injected — the coupling break: plan-authoring is no longer keyed off
// the bare read-only gate.
//
// The `objective_save` warm door (the tool + `/objective-save` command) lives in objectiveSave.ts,
// the mirror of planSave.ts.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { loadPerkConfig } from "../substrate/config.ts";
import { render } from "../substrate/prompts.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import { type BranchEntry, branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";

/** The registry stage id of the objective-authoring session (shared with planMode's defer check). */
export const OBJECTIVE_AUTHOR_STAGE = "objective-author";

/** The objective-authoring context customType (distinct from planMode's `perk:plan-context`). */
export const OBJECTIVE_AUTHOR_CONTEXT_TYPE = "perk:objective-author-context";
const OBJECTIVE_AUTHOR_MARKER = "[OBJECTIVE AUTHORING]";

/**
 * The cooperative gather-then-author contract for objectives. Prompting, NOT enforcement (the tool
 * gate is the enforcement). Mirrors skills/perk-objective-author/SKILL.md: clarify the goal, explore
 * read-only, structure a roadmap, keep the draft current with `objective_draft`, review via
 * `plan_review`, approval auto-saves — never hand-write roadmap YAML.
 */
export const OBJECTIVE_AUTHORING_CONTEXT = render("contexts/objective-authoring.md", {
  marker: OBJECTIVE_AUTHOR_MARKER,
});

/** Build the full objective-authoring injection, appending the project config addendum when present. */
export function objectiveAuthoringContextContent(cwd: string): string {
  const addendum = loadPerkConfig(cwd).planAuthoring;
  return addendum
    ? `${OBJECTIVE_AUTHORING_CONTEXT}\n\n${addendum.trim()}`
    : OBJECTIVE_AUTHORING_CONTEXT;
}

/** Whether the current branch is an objective-author session (read-only gate AND stage match). */
function isObjectiveAuthoring(gating: ToolGating, branch: readonly BranchEntry[]): boolean {
  return gating.isActive() && rebuildWorkflowState(branch).stage === OBJECTIVE_AUTHOR_STAGE;
}

/**
 * Register the objective-authoring context injection (display:false), the mirror of planMode's
 * injection half. Inert outside an objective-author session; never throws.
 */
export function registerObjectiveAuthor(pi: ExtensionAPI, gating: ToolGating): void {
  pi.on("before_agent_start", async (_event, ctx) => {
    const branch = branchOf(ctx);
    if (!isObjectiveAuthoring(gating, branch)) return;
    return {
      message: {
        customType: OBJECTIVE_AUTHOR_CONTEXT_TYPE,
        content: objectiveAuthoringContextContent(ctx.cwd),
        display: false,
      },
    };
  });

  // Strip the stale objective-authoring marker from context once the session is no longer authoring
  // (gate off, or the stage moved on) so it never lingers — the same hygiene planMode applies.
  pi.on("context", async (event, ctx) => {
    const branch = branchOf(ctx);
    if (isObjectiveAuthoring(gating, branch)) return;
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string; role?: string; content?: unknown };
        if (msg.customType === OBJECTIVE_AUTHOR_CONTEXT_TYPE) return false;
        if (msg.role !== "user") return true;
        const content = msg.content;
        if (typeof content === "string") return !content.includes(OBJECTIVE_AUTHOR_MARKER);
        if (Array.isArray(content)) {
          return !content.some(
            (c) =>
              (c as { type?: string; text?: string }).type === "text" &&
              ((c as { text?: string }).text ?? "").includes(OBJECTIVE_AUTHOR_MARKER),
          );
        }
        return true;
      }),
    };
  });
}
