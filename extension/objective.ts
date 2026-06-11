// P2.T9 — the objective TS substrate: `active_objective` live use + budget accounting + threshold
// compaction. The deterministic mechanics (storage, roadmap, next-node) live in the Python plane
// (`perk objective …`); this is the in-session interior keyed off the now-live `active_objective`
// workflow-state field.
//
// NO model-facing bounded transition tools here — the `objective-plan` stage, the plan factory, and
// the "fire only when…" tools are T10. This turn ships three pieces, all inert when no objective is
// active:
//   1. `/objective [<id>|clear]` — set/clear `active_objective` (LWW field) + seed a dedicated
//      `perk:objective-budget` activation marker (high-churn budget data kept OFF the shared record,
//      mirroring checkpoints' dedicated entry).
//   2. Budget accounting — stateless rebuild (the goal.ts pattern): sum assistant-message tokens
//      AFTER the latest activation marker; surface via ctx.ui guarded by ctx.hasUI; rebuilt on
//      session_start AND session_tree AND agent_end (survives reload/branch/compaction for free).
//   3. Threshold-triggered compaction (the trigger-compact.ts pattern): on turn_end, only when an
//      objective is active, compact when context usage crosses a configurable threshold.
//
// Headless-fail-safe: every UI call is ctx.hasUI-guarded; budget accounting + compaction are
// best-effort and never throw (logged-not-thrown, like checkpoints).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { loadPerkConfig } from "./config.ts";
import {
  formatBudgetLine,
  MARK_OBJECTIVE,
  report,
  STATUS_SLOT_OBJECTIVE,
  setStanding,
} from "./surfaces.ts";
import { branchOf, rebuildWorkflowState, WORKFLOW_STATE_TYPE } from "./workflowState.ts";

/** The dedicated budget/activation session entry type (kept off `perk:workflow-state`). */
export const OBJECTIVE_BUDGET_TYPE = "perk:objective-budget";

/** The default context-usage fraction that triggers threshold compaction (overridable via config). */
export const DEFAULT_COMPACT_THRESHOLD = 0.8;

/** A branch entry as seen by the budget scan: a custom marker OR an assistant message. */
interface ScanEntry {
  type: string;
  customType?: string;
  data?: { objective_id?: string; activated_at?: string };
  message?: { role?: string; usage?: { input?: number; output?: number } };
}

export interface BudgetMarker {
  index: number;
  objectiveId: string;
  activatedAt: string;
}

export interface BudgetState {
  objectiveId: string | null;
  tokens: number;
  elapsedMs: number;
}

// --- pure helpers (offline-testable) ------------------------------------------------------------

/** The latest `perk:objective-budget` activation marker on the branch, or null. */
export function findBudgetMarker(branch: readonly ScanEntry[]): BudgetMarker | null {
  for (let i = branch.length - 1; i >= 0; i--) {
    const e = branch[i];
    if (e?.type === "custom" && e.customType === OBJECTIVE_BUDGET_TYPE) {
      const objectiveId = e.data?.objective_id;
      const activatedAt = e.data?.activated_at;
      if (typeof objectiveId === "string" && typeof activatedAt === "string") {
        return { index: i, objectiveId, activatedAt };
      }
    }
  }
  return null;
}

/**
 * Sum assistant-message tokens (`max(0,input) + max(0,output)`) over branch entries AFTER
 * `afterIdx`. Non-assistant / marker entries are ignored; negatives are clamped to 0.
 */
export function sumAssistantTokens(branch: readonly ScanEntry[], afterIdx: number): number {
  let total = 0;
  for (let i = afterIdx + 1; i < branch.length; i++) {
    const e = branch[i];
    if (e?.type !== "message" || e.message?.role !== "assistant") continue;
    const usage = e.message.usage;
    if (!usage) continue;
    total += Math.max(0, usage.input ?? 0) + Math.max(0, usage.output ?? 0);
  }
  return total;
}

/** Rebuild the budget state from a branch (stateless; survives reload/branch/compaction). */
export function rebuildBudget(branch: readonly ScanEntry[], now: number): BudgetState {
  const marker = findBudgetMarker(branch);
  if (marker === null) return { objectiveId: null, tokens: 0, elapsedMs: 0 };
  const activatedMs = Date.parse(marker.activatedAt);
  const elapsedMs = Number.isFinite(activatedMs) ? Math.max(0, now - activatedMs) : 0;
  return {
    objectiveId: marker.objectiveId,
    tokens: sumAssistantTokens(branch, marker.index),
    elapsedMs,
  };
}

/** True when context usage has crossed the compaction threshold (pure; tolerant of unknowns). */
export function shouldCompact(
  usage: { percent: number | null; tokens: number | null } | undefined,
  threshold: number,
): boolean {
  if (!usage || usage.percent === null) return false;
  return usage.percent / 100 >= threshold;
}

// --- the controller -----------------------------------------------------------------------------

function scanBranchOf(ctx: ExtensionContext): ScanEntry[] {
  return ctx.sessionManager.getBranch() as unknown as ScanEntry[];
}

function activeObjective(ctx: ExtensionContext): string | null {
  try {
    const state = rebuildWorkflowState(branchOf(ctx));
    return state.active_objective ?? null;
  } catch {
    return null;
  }
}

/** Surface the budget in the UI (guarded — headless never touches setStatus/setWidget). */
function renderStatus(ctx: ExtensionContext): void {
  if (!ctx.hasUI) return;
  try {
    const active = activeObjective(ctx);
    if (active === null) {
      setStanding(ctx, STATUS_SLOT_OBJECTIVE, undefined);
      return;
    }
    const budget = rebuildBudget(scanBranchOf(ctx), Date.now());
    setStanding(ctx, STATUS_SLOT_OBJECTIVE, {
      status: `${MARK_OBJECTIVE} ${active} · ${formatBudgetLine(budget)}`,
      widget: [`objective: ${active}`, `budget: ${formatBudgetLine(budget)}`],
    });
  } catch (error) {
    console.error(`perk: objective status render failed — ${error}`);
  }
}

function reportError(ctx: ExtensionContext, message: string): void {
  report(ctx, "objective", "error", message);
}

/** The `/objective [<id>|clear]` handler (set/clear active_objective + seed/clear the marker). */
function objectiveCommand(pi: ExtensionAPI, ctx: ExtensionContext, args: string): void {
  const arg = args.trim();
  try {
    if (arg === "") {
      const active = activeObjective(ctx);
      const budget = rebuildBudget(scanBranchOf(ctx), Date.now());
      const message =
        active === null
          ? "no active objective. Use `/objective <id>` to activate one."
          : `active objective ${active} · ${formatBudgetLine(budget)}`;
      report(ctx, "objective", "info", message);
      return;
    }

    if (arg === "clear") {
      pi.appendEntry(WORKFLOW_STATE_TYPE, { active_objective: null });
      renderStatus(ctx);
      report(ctx, "objective", "info", "cleared the active objective.");
      return;
    }

    // Activate: set the LWW field + seed a fresh budget activation marker.
    pi.appendEntry(WORKFLOW_STATE_TYPE, { active_objective: arg });
    pi.appendEntry(OBJECTIVE_BUDGET_TYPE, {
      objective_id: arg,
      activated_at: new Date().toISOString(),
    });
    renderStatus(ctx);
    report(ctx, "objective", "info", `activated objective ${arg} (budget tracking started).`);
  } catch (error) {
    reportError(ctx, `command failed: ${error}`);
  }
}

/**
 * Register the objective substrate: `/objective` command, budget accounting (session_start /
 * session_tree / agent_end), and threshold compaction (turn_end). All inert when no objective is
 * active; never throws.
 */
export function registerObjective(pi: ExtensionAPI): void {
  pi.on("session_start", async (_event, ctx) => {
    renderStatus(ctx);
  });

  pi.on("session_tree", async (_event, ctx) => {
    renderStatus(ctx);
  });

  pi.on("agent_end", async (_event, ctx) => {
    // Recompute the budget after each agent loop (stateless rebuild from the branch).
    renderStatus(ctx);
  });

  pi.on("turn_end", async (_event, ctx) => {
    try {
      if (activeObjective(ctx) === null) return; // inert unless an objective is active
      const threshold =
        loadPerkConfig(ctx.cwd).objectiveCompactThreshold ?? DEFAULT_COMPACT_THRESHOLD;
      const usage = ctx.getContextUsage();
      if (!shouldCompact(usage, threshold)) return;
      const active = activeObjective(ctx);
      ctx.compact({
        customInstructions:
          `Preserve the active perk objective (${active}) and its budget context. ` +
          "Keep the roadmap progress and the current node's intent in the summary.",
        onError: (error) => {
          console.error(`perk: objective compaction failed — ${error}`);
        },
        onComplete: () => {
          renderStatus(ctx);
        },
      });
    } catch (error) {
      console.error(`perk: objective compaction trigger failed on turn_end — ${error}`);
    }
  });

  pi.registerCommand("objective", {
    description: "Show, set (`<id>`), or clear (`clear`) the active perk objective + budget.",
    handler: async (args, ctx) => {
      objectiveCommand(pi, ctx, args);
    },
  });
}
