// Gist-authoring context injection (the gist mirror of objectiveAuthor.ts). A `perk gist
// author` cold launch opens a READ-ONLY session whose handoff `stage` is `gist-author`; this
// module injects the gist-authoring contract under its own `perk:gist-author-context` customType
// (once-only: branch-scan dedup'd on the marker), keyed off (read-only gate AND stage ===
// gist-author), optionally extended by the same `[workflow] plan_authoring` addendum the
// plan-authoring injection consumes (verbatim reuse, read per-event via loadPerkConfig).
// planMode.ts defers when the stage is gist-author, so exactly one authoring context is injected.
//
// The `gist_save` warm door (the tool + `/gist-save` command) lives in gistSave.ts, the mirror
// of objectiveSave.ts.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { loadPerkConfig } from "../substrate/config.ts";
import { render } from "../substrate/prompts.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import {
  type BranchEntry,
  branchCarries,
  branchOf,
  rebuildWorkflowState,
} from "../substrate/workflowState.ts";

/** The registry stage id of the gist-authoring session (shared with planMode's defer check). */
export const GIST_AUTHOR_STAGE = "gist-author";

/** The gist-authoring context customType (distinct from planMode's `perk:plan-context`). */
export const GIST_AUTHOR_CONTEXT_TYPE = "perk:gist-author-context";
const GIST_AUTHOR_MARKER = "[GIST AUTHORING]";

/**
 * The gist-authoring session context: live state + pointers only (contracts.md §8.57 — the flow
 * is stated by the launch statement, the detail by the `perk-gist-author` skill). It names the
 * working-draft artifact (`gist_draft`), the review tool (`plan_review`), and the bound skill;
 * it never restates the flow. Prompting, NOT enforcement (the tool gate is the enforcement).
 */
export const GIST_AUTHORING_CONTEXT = render("contexts/gist-authoring.md", {
  marker: GIST_AUTHOR_MARKER,
});

/** Build the full gist-authoring injection, appending the project config addendum when present. */
export function gistAuthoringContextContent(cwd: string): string {
  const addendum = loadPerkConfig(cwd).planAuthoring;
  return addendum ? `${GIST_AUTHORING_CONTEXT}\n\n${addendum.trim()}` : GIST_AUTHORING_CONTEXT;
}

/** Whether the current branch is a gist-author session (read-only gate AND stage match). */
function isGistAuthoring(gating: ToolGating, branch: readonly BranchEntry[]): boolean {
  return gating.isActive() && rebuildWorkflowState(branch).stage === GIST_AUTHOR_STAGE;
}

/**
 * Register the gist-authoring context injection (display:false), the gist mirror of
 * objectiveAuthor's injection. Inert outside a gist-author session; never throws.
 */
export function registerGistAuthor(pi: ExtensionAPI, gating: ToolGating): void {
  pi.on("before_agent_start", async (_event, ctx) => {
    const branch = branchOf(ctx);
    if (!isGistAuthoring(gating, branch)) return;
    // Once-only: injected customs persist to the branch, so a live copy suppresses re-injection;
    // compaction dropping it makes the scan come up clean and the next turn re-injects.
    if (branchCarries(branch, GIST_AUTHOR_MARKER)) return;
    return {
      message: {
        customType: GIST_AUTHOR_CONTEXT_TYPE,
        content: gistAuthoringContextContent(ctx.cwd),
        display: false,
      },
    };
  });

  // Strip the stale gist-authoring marker from context once the session is no longer authoring
  // (gate off, or the stage moved on) so it never lingers — the same hygiene planMode applies.
  pi.on("context", async (event, ctx) => {
    const branch = branchOf(ctx);
    if (isGistAuthoring(gating, branch)) return;
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string; role?: string; content?: unknown };
        if (msg.customType === GIST_AUTHOR_CONTEXT_TYPE) return false;
        if (msg.role !== "user") return true;
        const content = msg.content;
        if (typeof content === "string") return !content.includes(GIST_AUTHOR_MARKER);
        if (Array.isArray(content)) {
          return !content.some(
            (c) =>
              (c as { type?: string; text?: string }).type === "text" &&
              ((c as { text?: string }).text ?? "").includes(GIST_AUTHOR_MARKER),
          );
        }
        return true;
      }),
    };
  });
}
