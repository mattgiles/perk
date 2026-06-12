// Node 3.2 — the FIRST 3rd-party todo adapter. A perk-owned, injection-only bridge that re-enables
// `@juicesharp/rpiv-todo` as a REAL, selectable todo provider: it carries perk's implement-progress
// discipline onto that package's checklist-overlay surface (the todo-seam mirror of
// planAdapterTombell, which bridges the plan seam).
//
// INERT BY DEFAULT. This shim is ALWAYS registered in index.ts but does nothing unless the resolved
// `[providers] todo` selection is `juicesharp-todo` (read fresh per-event via the same
// `resolvedTodoProviderId` the reference checkpoints provider uses) AND the session is an active
// workflow (`active_plan_ref != null`, the same gate the reference checkpoints provider seeds on).
// On any non-juicesharp selection it injects nothing and only strips its own stale marker — zero
// behavior change on the default path.
//
// WHAT IT DOES (and does NOT do):
//   - It injects a hidden (`display:false`) `perk:todo-adapter-juicesharp` context that tells the
//     model the foreign `@juicesharp/rpiv-todo` checklist overlay is the sole progress surface here
//     (perk's own checkpoints stepped aside at Node 3.1) and directs it to carry perk's
//     implement-progress DISCIPLINE onto that overlay: seed it from the plan body's `## Steps` and
//     mark each item complete in order — the same gather-then-advance flow perk's checkpoints embody.
//   - It does NOT own, replace, or duplicate the read-only gate (Invariant 1) and NEVER calls
//     `setActiveTools` / registers a `tool_call` handler (the todo seam composes no shared primitive).
//   - It does NOT write perk's `perk:checkpoint` entry and does NOT revive perk's deferred marker
//     scanner (Correction 2): that entry is a transient TS-only progress overlay nothing downstream
//     consumes, and perk's render + scanner are already deferred (Node 3.1). Re-populating it would
//     be dead duplication — the foreign overlay is the sole, uncontested progress surface.
//   - It adds NO registration-time vacating (Correction 1): unlike the plan seam (where perk and the
//     foreign package both register `/plan`, forcing Pi to suffix the duplicate), the todo seam has
//     no command-name collision — perk registers `/checkpoints`; the foreign overlay registers its
//     own differently-named command(s) — so Node 3.1's runtime deferral is already sufficient.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { resolvedTodoProviderId } from "../checkpoints/checkpoints.ts";
import { JUICESHARP_TODO_PROVIDER_ID } from "../providers.ts";
import { branchOf, rebuildWorkflowState } from "../workflowState.ts";

/** The juicesharp todo-adapter bridge customType (distinct from checkpoints' `perk:checkpoint`). */
export const TODO_ADAPTER_JUICESHARP_CONTEXT_TYPE = "perk:todo-adapter-juicesharp";
const TODO_ADAPTER_JUICESHARP_MARKER = "[TODO ADAPTER: JUICESHARP]";

/**
 * The bridge prompt: carries perk's implement-progress discipline onto the foreign checklist
 * overlay. Prompting, NOT enforcement (perk's checkpoint scanner is deferred under this selection).
 * Durable anchors only, no line numbers.
 */
export const TODO_ADAPTER_JUICESHARP_CONTEXT = `${TODO_ADAPTER_JUICESHARP_MARKER}
This implement session tracks progress through the \`@juicesharp/rpiv-todo\` checklist overlay — the
selected todo provider (\`[providers] todo = "juicesharp-todo"\`). perk's own checkpoint surface has
stepped aside (Node 3.1), so the foreign overlay is the sole progress surface here.

Carry perk's implement-progress discipline onto that overlay: seed it from the plan body's
\`## Steps\` numbered list — one checklist item per step, in order — then mark each item complete as
you finish the corresponding step, the same gather-then-advance flow perk's checkpoints embody. Use
the overlay's own controls to add and complete items; you do not need perk's \`[WIP:n]\`/\`[DONE:n]\`
markers here (perk's checkpoint scanner is deferred under this selection). If the plan has no
\`## Steps\` list, there is nothing to seed — let the overlay behave as its defaults suggest.`;

/** Whether the foreign `juicesharp-todo` provider is the selected todo provider for `cwd`. */
export function isJuicesharpTodoSelected(cwd: string): boolean {
  return resolvedTodoProviderId(cwd) === JUICESHARP_TODO_PROVIDER_ID;
}

/**
 * Register the juicesharp todo adapter: an injection-only bridge, inert unless `[providers] todo =
 * "juicesharp-todo"` AND the session is an active workflow. It NEVER touches tool gating /
 * setActiveTools (Invariant 1) and never throws.
 */
export function registerTodoAdapterJuicesharp(pi: ExtensionAPI): void {
  // Inject the bridge context while the foreign juicesharp-todo provider is selected AND a workflow
  // is active (active_plan_ref != null) — the same active-workflow scope the reference checkpoints
  // provider seeds on, so the bridge never reaches planning/objective sessions (display:false).
  pi.on("before_agent_start", async (_event, ctx) => {
    if (!isJuicesharpTodoSelected(ctx.cwd)) return;
    const branch = branchOf(ctx);
    if (rebuildWorkflowState(branch).active_plan_ref == null) return;
    return {
      message: {
        customType: TODO_ADAPTER_JUICESHARP_CONTEXT_TYPE,
        content: TODO_ADAPTER_JUICESHARP_CONTEXT,
        display: false,
      },
    };
  });

  // Strip the stale bridge marker from context when juicesharp-todo is no longer selected (same
  // hygiene the sibling adapters apply), so it never lingers across a deselect.
  pi.on("context", async (event, ctx) => {
    if (isJuicesharpTodoSelected(ctx.cwd)) return;
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string; role?: string; content?: unknown };
        if (msg.customType === TODO_ADAPTER_JUICESHARP_CONTEXT_TYPE) return false;
        if (msg.role !== "user") return true;
        const content = msg.content;
        if (typeof content === "string") return !content.includes(TODO_ADAPTER_JUICESHARP_MARKER);
        if (Array.isArray(content)) {
          return !content.some(
            (c) =>
              (c as { type?: string; text?: string }).type === "text" &&
              ((c as { text?: string }).text ?? "").includes(TODO_ADAPTER_JUICESHARP_MARKER),
          );
        }
        return true;
      }),
    };
  });
}
