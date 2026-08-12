// perk-owned plan mode. The first consumer of the tool-gating primitive
// (extension/substrate/toolGating.ts). This is the *toggle surface* on top of that structural gate: a
// `/plan` command, a `Ctrl+Alt+P` shortcut, and a `--plan` flag all flip `gating.enter`/`exit`.
// perk owns NO parallel enforcement here — the gate is the single read-only authority.
//
// It also injects the cooperative *plan-authoring* prompt layer (the gather-then-plan contract)
// under its own `perk:plan-context` customType (display:false, once-only: branch-scan dedup'd on
// the marker),
// keyed directly off the read-only gate (read-only ⟹ plan in the main session). The
// content is stripped from `context` when the gate is off — the same hygiene the gate applies to its
// `perk:mode-context`. An optional `[workflow] plan_authoring` config addendum (extension/substrate/config.ts)
// is appended when present.
//
// Grounded in pi's official `examples/extensions/plan-mode/` recipe, but perk adopts ONLY the
// read-only authoring half: there is no in-session "execution mode" flip — perk separates plan
// (read-only session) from implement (cold-door fresh worktree session), and progress tracking
// lives in the implement session.
//
// REGISTRATION-TIME DEFERRAL, now THREE-TIER. `registerPlanMode` resolves the plan
// provider id once at factory time and branches:
//   - `perk-plan` (and the fail-safe error path) → register EVERYTHING (the default path is the
//     hard guarantee, zero behavior change).
//   - `plannotator-plan` (AUGMENT posture) → register everything EXCEPT the `--plan` flag, the
//     `Ctrl+Alt+P` shortcut, and the `--plan` session_start handler: `@plannotator/pi-extension`
//     also registers that flag + shortcut, and duplicate flag/shortcut registration is the known
//     potentially-fatal Pi behavior — plannotator owns `--plan`/`Ctrl+Alt+P` exclusively while
//     perk keeps `/plan`, the authoring injection, and the read-only gate (plannotator augments
//     perk's plan flow via the planAdapterPlannotator `plan_review` bridge; it does not replace it).
//   - any other foreign id (tombell, REPLACE posture) → register NOTHING; the foreign package owns
//     `/plan`/`Ctrl+Alt+P`/`--plan` unambiguously (Pi suffixes duplicate command names, so
//     handler-time deferral alone is insufficient once the foreign package is loaded).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { registerPerkCommand } from "../substrate/command.ts";
import { loadPerkConfig } from "../substrate/config.ts";
import { render } from "../substrate/prompts.ts";
import {
  loadProviders,
  PERK_PLAN_PROVIDER_ID,
  PLANNOTATOR_PLAN_PROVIDER_ID,
  resolveProviders,
} from "../substrate/providers.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import { branchCarries, branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { report } from "../surfaces/report.ts";
// `Key` via the surfaces re-export (keybinding vocabulary, not rich UI) — keeps pi-tui imports
// structurally confined to the surfaces module (the surfacesGuard pi-tui import rule).
import { Key } from "../surfaces/surfaces.ts";
import { GIST_AUTHOR_STAGE } from "./gistAuthor.ts";
import { OBJECTIVE_AUTHOR_STAGE } from "./objectiveAuthor.ts";

/** The plan-authoring context customType (distinct from the gate's `perk:mode-context`). */
export const PLAN_CONTEXT_TYPE = "perk:plan-context";
const PLAN_MARKER = "[PLAN AUTHORING]";

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

/** Build the full plan-authoring injection, appending the project config addendum when present. */
export function planContextContent(cwd: string): string {
  const addendum = loadPerkConfig(cwd).planAuthoring;
  return addendum ? `${PLAN_AUTHORING_CONTEXT}\n\n${addendum.trim()}` : PLAN_AUTHORING_CONTEXT;
}

/**
 * The resolved `[providers] plan` selection id for `cwd`, read fresh per-event (no static state —
 * the same per-event-read shape `planContextContent(ctx.cwd)` uses). Fail-safe to the perk-plan
 * reference: any load/resolution failure returns the reference id so perk's own plan mode keeps
 * working — the default path is the hard guarantee. With the resolver's per-seam fail-open
 * fallbacks this catch narrows to genuine file-read/parse failures — logged loudly (consoleCapture
 * routes it into the session log), never swallowed: a silent catch here once masked a
 * version-skew throw and silently swapped the review surface to first-party.
 */
export function resolvedPlanProviderId(cwd: string): string {
  try {
    return resolveProviders(loadPerkConfig(cwd).providers, loadProviders()).plan.id;
  } catch (error) {
    console.error(
      `perk: plan provider resolution failed — falling back to ${PERK_PLAN_PROVIDER_ID}: ${error}`,
    );
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
 * Register the perk-owned plan-mode toggle surface over the read-only gate. Idempotent enter/exit (the gate
 * tracks its own on/off transition), fail-safe-headless (notify when UI, else stderr).
 */
export function registerPlanMode(pi: ExtensionAPI, gating: ToolGating): void {
  // Three-tier registration branch (see the header comment): full registration for the reference
  // (fail-safe default), a PARTIAL vacate (skip only `--plan` + `Ctrl+Alt+P`) under the augment-
  // posture plannotator selection, and a full vacate under any other foreign selection (tombell).
  const providerId = resolvedPlanProviderId(process.cwd());
  const plannotatorSelected = providerId === PLANNOTATOR_PLAN_PROVIDER_ID;
  if (providerId !== PERK_PLAN_PROVIDER_ID && !plannotatorSelected) return;

  if (!plannotatorSelected) {
    pi.registerFlag("plan", {
      description: "Start in perk plan mode (read-only exploration + plan authoring).",
      type: "boolean",
      default: false,
    });
  }

  function announce(ctx: ExtensionContext, on: boolean): void {
    const message = on
      ? "plan mode ON — read-only exploration; author the plan, then review with plan_review (approval auto-saves; /plan-save is the manual failsafe)."
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

  registerPerkCommand(pi, "plan", {
    description: "Toggle perk plan mode (read-only exploration + plan authoring).",
    handler: async (_args, ctx) => toggle(ctx),
  });

  if (!plannotatorSelected) {
    pi.registerShortcut(Key.ctrlAlt("p"), {
      description: "Toggle perk plan mode",
      handler: async (ctx) => toggle(ctx),
    });

    // `--plan` cold start: enter read-only on session_start when the flag is set and the gate is
    // off. (index.ts's session_start already syncs the gate from the rebuilt `mode`; this layers
    // the flag on top for ad-hoc `pi --plan` interactive starts — the cold plan door drives
    // read-only via the handoff `mode`, not this flag.) Skipped under the plannotator selection
    // along with the flag itself (the flag no longer exists on perk's side).
    pi.on("session_start", async (_event, ctx) => {
      if (pi.getFlag("plan") === true && !gating.isActive()) {
        gating.enter(ctx);
      }
    });
  }

  // Inject the plan-authoring context while the read-only gate is active (display:false). The
  // exceptions: objective-author and gist-author sessions are ALSO read-only, but
  // objectiveAuthor.ts / gistAuthor.ts inject their own authoring contexts there — so plan mode
  // defers when the launched stage is either (the coupling break: plan-authoring context is no
  // longer keyed off the bare read-only gate).
  pi.on("before_agent_start", async (_event, ctx) => {
    if (!gating.isActive()) return;
    const branch = branchOf(ctx);
    const launchedStage = rebuildWorkflowState(branch).stage;
    if (launchedStage === OBJECTIVE_AUTHOR_STAGE || launchedStage === GIST_AUTHOR_STAGE) return;
    // Once-only: injected customs persist to the branch, so a live copy suppresses re-injection;
    // compaction dropping it makes the scan come up clean and the next turn re-injects.
    if (branchCarries(branch, PLAN_MARKER)) return;
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
