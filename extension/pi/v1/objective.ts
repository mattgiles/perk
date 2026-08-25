// The objective TS substrate: `active_objective` live use + budget accounting + threshold
// compaction. The deterministic mechanics (storage, roadmap, next-node) live in the Python plane
// (`perk objective …`); this is the in-session interior keyed off the now-live `active_objective`
// workflow-state field.
//
// NO model-facing bounded transition tools here — the `objective-plan` stage, the plan factory, and
// the "fire only when…" tools live elsewhere. This module ships three pieces, all inert when no
// objective is active:
//   1. `/objective [<id>|clear]` — set/clear `active_objective` (LWW field) + seed a dedicated
//      `perk:objective-budget` activation marker (high-churn budget data kept OFF the shared
//      record).
//   2. Budget accounting — stateless rebuild (the goal.ts pattern): sum assistant-message tokens
//      AFTER the latest activation marker; surface via ctx.ui guarded by ctx.hasUI; rebuilt on
//      session_start AND session_tree AND agent_settled (survives reload/branch/compaction for
//      free). `agent_settled` fires once per settled run on the final branch state (not mid-retry/
//      mid-compaction); registration is string-keyed, so pre-0.80.4 hosts simply never fire it and
//      the budget gracefully degrades to the session_start/session_tree renders.
//   3. Threshold-triggered compaction (the trigger-compact.ts pattern): on turn_end, only when an
//      objective is active, compact when context usage crosses a configurable threshold.
//
// Headless-fail-safe: every UI call is ctx.hasUI-guarded; budget accounting + compaction are
// best-effort and never throw (logged-not-thrown).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import { type ColdJson, objectField, runColdDoor, stringField } from "../../substrate/coldDoor.ts";
import { registerPerkCommand } from "../../substrate/command.ts";
import { loadPerkConfig } from "../../substrate/config.ts";
import { type BranchEntry, branchOf, WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import {
  formatBudgetLine,
  MARK_OBJECTIVE,
  objectiveBudgetEntryRenderer,
  type PerkStatusHandle,
  registerTranscriptRenderer,
  report,
} from "../../surfaces/surfaces.ts";

/** The dedicated budget/activation session entry type (kept off `perk:workflow-state`). */
export const OBJECTIVE_BUDGET_TYPE = "perk:objective-budget";

/** The default context-usage fraction that triggers threshold compaction (overridable via config). */
export const DEFAULT_COMPACT_THRESHOLD = 0.8;

/** A branch entry as seen by the budget scan: a custom marker OR an assistant message. */
interface ScanEntry extends BranchEntry {
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
  usage: { percent: number | null } | undefined,
  threshold: number,
): boolean {
  if (!usage || usage.percent === null) return false;
  return usage.percent / 100 >= threshold;
}

// --- the controller -----------------------------------------------------------------------------

function scanBranchOf(ctx: ExtensionContext): ScanEntry[] {
  // `branchOf` owns the typed accessor; the scan only ADDS the optional assistant-message
  // shape, so no round-trip through `unknown` is needed (field presence is checked locally).
  return branchOf(ctx) as ScanEntry[];
}

/** The rebuilt `active_objective`, read through the session seam (fail-open null). */
function activeObjective(pi: ExtensionAPI, ctx: ExtensionContext): string | null {
  return openBranchWorkflowSession(pi, ctx).activeObjective();
}

/**
 * Surface the budget as the single-value `perk` status (the `perk-objective`
 * widget is retired; the value carries id + tokens + elapsed). Headless-safe:
 * the handle no-ops without UI.
 */
function renderStatus(pi: ExtensionAPI, ctx: ExtensionContext, status: PerkStatusHandle): void {
  if (!ctx.hasUI) return;
  try {
    const active = activeObjective(pi, ctx);
    if (active === null) {
      status.set(ctx, undefined);
      return;
    }
    const budget = rebuildBudget(scanBranchOf(ctx), Date.now());
    status.set(ctx, `${MARK_OBJECTIVE} ${active} · ${formatBudgetLine(budget)}`);
  } catch (error) {
    console.error(`perk: objective status render failed — ${error}`);
  }
}

function reportError(ctx: ExtensionContext, message: string): void {
  report(ctx, "objective", "error", message);
}

/** The `/objective [<id>|clear]` handler (set/clear active_objective + seed/clear the marker). */
function objectiveCommand(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  args: string,
  status: PerkStatusHandle,
): void {
  const arg = args.trim();
  try {
    if (arg === "") {
      const active = activeObjective(pi, ctx);
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
      renderStatus(pi, ctx, status);
      report(ctx, "objective", "info", "cleared the active objective.");
      return;
    }

    // Activate: set the LWW field + seed a fresh budget activation marker.
    pi.appendEntry(WORKFLOW_STATE_TYPE, { active_objective: arg });
    pi.appendEntry(OBJECTIVE_BUDGET_TYPE, {
      objective_id: arg,
      activated_at: new Date().toISOString(),
    });
    renderStatus(pi, ctx, status);
    report(ctx, "objective", "info", `activated objective ${arg} (budget tracking started).`);
  } catch (error) {
    reportError(ctx, `command failed: ${error}`);
  }
}

/**
 * Fetch the objective's URL via `perk objective show <id> --json` (reading `objective.url`).
 * Lenient: returns "" on any failure / missing url — `runColdDoor` is a soft-result seam and
 * never throws (the seed prompt's step-1 `perk objective show <id>` step surfaces the URL
 * anyway). Only called for the linear backend (github needs no clause → no fetch). Exported for
 * the warm drives that compose the same backend-aware read clause (the ready-time reconcile
 * drive in `doors/ready.ts`).
 */
export async function fetchObjectiveUrl(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  objectiveId: string,
): Promise<string> {
  const r = await runColdDoor<string>(pi, ctx, ["objective", "show", objectiveId, "--json"], {
    label: "perk objective show",
    decode: (payload: ColdJson) =>
      stringField(objectField(payload, "objective") ?? {}, "url") ?? "",
  });
  return r.ok ? r.data : "";
}

/**
 * Install the objective substrate bindings: `/objective` command, budget accounting
 * (session_start / session_tree / agent_settled), and threshold compaction (turn_end). All
 * inert when no objective is active; never throws.
 */
export function installObjectiveBindings(pi: ExtensionAPI, status: PerkStatusHandle): void {
  // Transcript marker for `perk:objective-budget` activations (audit §2.3): renderer body in
  // surfaces.ts, registration = wiring, feature-detect inside the seam (pre-0.80.4 hosts stay
  // inert). Also covers objectiveSave.ts's appends — registration is per entry TYPE.
  registerTranscriptRenderer(pi, OBJECTIVE_BUDGET_TYPE, objectiveBudgetEntryRenderer);

  pi.on("session_start", async (_event, ctx) => {
    renderStatus(pi, ctx, status);
  });

  pi.on("session_tree", async (_event, ctx) => {
    renderStatus(pi, ctx, status);
  });

  pi.on("agent_settled", async (_event, ctx) => {
    // Recompute the budget after each settled run (stateless rebuild from the branch).
    renderStatus(pi, ctx, status);
  });

  pi.on("turn_end", async (_event, ctx) => {
    try {
      if (activeObjective(pi, ctx) === null) return; // inert unless an objective is active
      const threshold =
        loadPerkConfig(ctx.cwd).objectiveCompactThreshold ?? DEFAULT_COMPACT_THRESHOLD;
      const usage = ctx.getContextUsage();
      if (!shouldCompact(usage, threshold)) return;
      const active = activeObjective(pi, ctx);
      ctx.compact({
        customInstructions:
          `Preserve the active perk objective (${active}) and its budget context. ` +
          "Keep the roadmap progress and the current node's intent in the summary.",
        onError: (error) => {
          console.error(`perk: objective compaction failed — ${error}`);
        },
        onComplete: () => {
          renderStatus(pi, ctx, status);
        },
      });
    } catch (error) {
      console.error(`perk: objective compaction trigger failed on turn_end — ${error}`);
    }
  });

  registerPerkCommand(pi, "objective", {
    description: "Show, set (`<id>`), or clear (`clear`) the active perk objective + budget.",
    handler: async (args, ctx) => {
      objectiveCommand(pi, ctx, args, status);
    },
  });
}
