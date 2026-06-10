// P2.T2a — perk-owned plan mode. The first consumer of T1's tool-gating primitive
// (extension/toolGating.ts). This is the *toggle surface* on top of T1's structural gate: a
// `/plan` command, a `Ctrl+Alt+P` shortcut, and a `--plan` flag all flip `gating.enter`/`exit`.
// perk owns NO parallel enforcement here — T1 is the single read-only authority.
//
// It also injects the cooperative *plan-authoring* prompt layer (the gather-then-plan contract,
// erk context-preservation-prompting) under its own `perk:plan-context` customType (display:false),
// keyed directly off the read-only gate (read-only ⟹ plan in the Phase-2 main session). The
// content is stripped from `context` when the gate is off — the same hygiene T1 applies to its
// `perk:mode-context`. An optional `[workflow] plan_authoring` config addendum (extension/config.ts)
// is appended when present.
//
// Grounded in pi's official `examples/extensions/plan-mode/` recipe, but perk adopts ONLY the
// read-only authoring half: there is no in-session "execution mode" flip — perk separates plan
// (read-only session) from implement (cold-door fresh worktree session), and `[DONE:n]` tracking
// lives in the implement session (T2c).
//
// REGISTRATION-TIME DEFERRAL (Node 2.3). When a foreign `[providers] plan` is selected, perk's
// surface is NOT registered at all: `registerPlanMode` resolves the plan provider id once at
// factory time and, when it is not `perk-plan`, registers NONE of the `--plan` flag, the `/plan`
// command, the `Ctrl+Alt+P` shortcut, the `--plan` session_start entry, or the `before_agent_start`
// injection / its `context` strip. The foreign package then owns those surfaces with no collision
// (Pi suffixes duplicate command names, so handler-time deferral alone is insufficient once the
// foreign package is loaded). Fail-safe: any config-read error → treated as `perk-plan` → everything
// registers exactly as today (the default path is the hard guarantee, zero behavior change).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Key } from "@earendil-works/pi-tui";
import { loadPerkConfig } from "./config.ts";
import { OBJECTIVE_AUTHOR_STAGE } from "./objectiveAuthor.ts";
import { loadProviders, PERK_PLAN_PROVIDER_ID, resolveProviders } from "./providers.ts";
import { report } from "./report.ts";
import type { ToolGating } from "./toolGating.ts";
import { branchOf, rebuildWorkflowState } from "./workflowState.ts";

/** The plan-authoring context customType (distinct from T1's `perk:mode-context`). */
export const PLAN_CONTEXT_TYPE = "perk:plan-context";
const PLAN_MARKER = "[PLAN AUTHORING]";

/**
 * The cooperative gather-then-plan contract. This is prompting, NOT enforcement (T1's gate is the
 * enforcement). It never leaks internal policy text — it tells the model how to materialize a
 * decision-complete plan an executor with zero prior context can follow (mirrors
 * skills/perk-plan/SKILL.md). Durable anchors only, no line numbers.
 */
export const PLAN_AUTHORING_CONTEXT = `${PLAN_MARKER}
You are authoring a perk plan in read-only mode — explore first, then write.

Gather before you plan. Materialize four finding categories from real evidence:
- Status: what exists today (the current behavior, where it lives).
- Discoveries: concrete findings with real file paths and function/class names.
- Corrections: assumptions that turned out wrong, and what is actually true.
- Codebase evidence: the specific code you verified each decision against.

Write the plan so an executor (a future session, or another engineer) with zero prior context can
implement it without guessing. Anchor every change durably — function/class names, behavioral
descriptions, structural locations — never line numbers. Resolve every open choice before saving;
a saved plan must leave no decisions to the implementer.

When the plan is decision-complete: disable plan mode (/plan off), then call the plan_save tool
with the finalized plan markdown.`;

/** Build the full plan-authoring injection, appending the project config addendum when present. */
export function planContextContent(cwd: string): string {
  const addendum = loadPerkConfig(cwd).planAuthoring;
  return addendum ? `${PLAN_AUTHORING_CONTEXT}\n\n${addendum.trim()}` : PLAN_AUTHORING_CONTEXT;
}

/**
 * The resolved `[providers] plan` selection id for `cwd`, read fresh per-event (no static state —
 * the same per-event-read shape `planContextContent(ctx.cwd)` uses). Fail-safe to the perk-plan
 * reference: any load/resolution failure (corrupt bundled set, etc.) returns the reference id so
 * perk's own plan mode keeps working — the default path is the hard guarantee.
 */
export function resolvedPlanProviderId(cwd: string): string {
  try {
    return resolveProviders(loadPerkConfig(cwd).providers, loadProviders()).plan.id;
  } catch {
    return PERK_PLAN_PROVIDER_ID;
  }
}

/**
 * Whether perk's own plan-mode reference is the selected plan provider for `cwd`. When a foreign
 * plan provider is selected via `[providers] plan`, perk's authoring surface steps aside (defers).
 */
export function isPerkPlanReferenceSelected(cwd: string): boolean {
  return resolvedPlanProviderId(cwd) === PERK_PLAN_PROVIDER_ID;
}

/**
 * Register the perk-owned plan-mode toggle surface over T1's gate. Idempotent enter/exit (the gate
 * tracks its own on/off transition), fail-safe-headless (notify when UI, else stderr).
 */
export function registerPlanMode(pi: ExtensionAPI, gating: ToolGating): void {
  // Registration-time deferral (Node 2.3): resolve the plan provider once at factory time. Under a
  // foreign plan selection, register NOTHING here so the foreign package owns `/plan`/`Ctrl+Alt+P`/
  // `--plan` unambiguously. Fail-safe to the reference (any read error registers everything).
  if (!isPerkPlanReferenceSelected(process.cwd())) return;

  pi.registerFlag("plan", {
    description: "Start in perk plan mode (read-only exploration + plan authoring).",
    type: "boolean",
    default: false,
  });

  function announce(ctx: ExtensionContext, on: boolean): void {
    const message = on
      ? "plan mode ON — read-only exploration; author the plan, then /plan off + plan_save."
      : "plan mode OFF — full tool access restored.";
    report(ctx, "plan-mode", "info", message);
  }

  function toggle(ctx: ExtensionContext): void {
    if (gating.isActive()) {
      gating.exit(ctx);
      announce(ctx, false);
    } else {
      gating.enter(ctx);
      announce(ctx, true);
    }
  }

  pi.registerCommand("plan", {
    description: "Toggle perk plan mode (read-only exploration + plan authoring).",
    handler: async (_args, ctx) => toggle(ctx),
  });

  pi.registerShortcut(Key.ctrlAlt("p"), {
    description: "Toggle perk plan mode",
    handler: async (ctx) => toggle(ctx),
  });

  // `--plan` cold start: enter read-only on session_start when the flag is set and the gate is off.
  // (index.ts's session_start already syncs the gate from the rebuilt `mode`; this layers the flag
  // on top for ad-hoc `pi --plan` interactive starts — the cold plan door drives read-only via the
  // handoff `mode`, not this flag.)
  pi.on("session_start", async (_event, ctx) => {
    if (pi.getFlag("plan") === true && !gating.isActive()) {
      gating.enter(ctx);
    }
  });

  // Inject the plan-authoring context while the read-only gate is active (display:false). The one
  // exception: an objective-author session is ALSO read-only, but objectiveAuthor.ts injects its
  // own authoring context there — so plan mode defers when the launched stage is objective-author
  // (the coupling break: plan-authoring context is no longer keyed off the bare read-only gate).
  pi.on("before_agent_start", async (_event, ctx) => {
    if (!gating.isActive()) return;
    const branch = branchOf(ctx);
    if (rebuildWorkflowState(branch).stage === OBJECTIVE_AUTHOR_STAGE) return;
    return {
      message: {
        customType: PLAN_CONTEXT_TYPE,
        content: planContextContent(ctx.cwd),
        display: false,
      },
    };
  });

  // Strip the stale plan-authoring marker from context when the gate is off (so it never lingers).
  pi.on("context", async (event) => {
    if (gating.isActive()) return;
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string; role?: string; content?: unknown };
        if (msg.customType === PLAN_CONTEXT_TYPE) return false;
        if (msg.role !== "user") return true;
        const content = msg.content;
        if (typeof content === "string") return !content.includes(PLAN_MARKER);
        if (Array.isArray(content)) {
          return !content.some(
            (c) =>
              (c as { type?: string; text?: string }).type === "text" &&
              ((c as { text?: string }).text ?? "").includes(PLAN_MARKER),
          );
        }
        return true;
      }),
    };
  });
}
