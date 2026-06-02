// P2.T2c — perk-owned checkpoints. The implement-session progress tracker: seed an ordered step
// list from the plan body's `## Steps` numbered list, then advance it as the model emits `[DONE:n]`
// markers in its turns. State lives in a dedicated `perk:checkpoint` session entry (D3) — kept OFF
// the shared `perk:workflow-state` record (progress is high-churn; this avoids LWW-append smell).
//
// Opt-in + inert-by-default (D4): perk plans are prose, so when no `## Steps` list is present the
// checkpoint degrades to inert (no crash, no nagging). The `perk-plan` skill documents the optional
// `## Steps` section as the forward path.
//
// The pure helpers (extractDoneSteps / markCompletedSteps + the step extractor) are perk-owned
// copies of pi's official `examples/extensions/plan-mode/utils.ts` (as T1 copied the regex tables),
// adapted to key off `## Steps` rather than plan-mode's `Plan:` header. Status is surfaced via
// `ctx.ui.setStatus`/`setWidget` guarded by `ctx.hasUI` (headless-safe); `/checkpoints` lists it.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { readPlanBody } from "./cache.ts";
import type { BranchEntry } from "./workflowState.ts";
import { rebuildWorkflowState } from "./workflowState.ts";

/** The dedicated checkpoint session entry type (D3). */
export const CHECKPOINT_TYPE = "perk:checkpoint";

export interface CheckpointStep {
  step: number;
  text: string;
  completed: boolean;
}

export interface CheckpointState {
  steps: CheckpointStep[];
}

/** A step list with no items is "inert" — no `## Steps` was found in the plan body. */
export function isInert(state: CheckpointState): boolean {
  return state.steps.length === 0;
}

// --- pure helpers (perk-owned copies of plan-mode/utils.ts) -------------------------------------

/** Extract `[DONE:n]` step numbers from a block of text (case-insensitive). */
export function extractDoneSteps(text: string): number[] {
  const steps: number[] = [];
  for (const match of text.matchAll(/\[DONE:(\d+)\]/gi)) {
    const step = Number(match[1]);
    if (Number.isFinite(step)) steps.push(step);
  }
  return steps;
}

/** Mark steps named by `[DONE:n]` in `text` as completed (mutates `steps`); returns the count. */
export function markCompletedSteps(text: string, steps: CheckpointStep[]): number {
  const done = extractDoneSteps(text);
  for (const n of done) {
    const item = steps.find((s) => s.step === n);
    if (item) item.completed = true;
  }
  return done.length;
}

/**
 * Parse the plan body's `## Steps` numbered list into checkpoint steps. Returns `[]` when there is
 * no `## Steps` section (the inert path, D4). Only a recognizable `<n>. text` / `<n>) text` list
 * under the header is parsed; the section ends at the next `## ` heading.
 */
export function extractSteps(planBody: string | null | undefined): CheckpointStep[] {
  if (!planBody) return [];
  const lines = planBody.split(/\r?\n/);
  let inSection = false;
  const steps: CheckpointStep[] = [];
  for (const raw of lines) {
    const line = raw ?? "";
    const header = line.match(/^\s*(#{1,6})\s+(.*\S)\s*$/);
    if (header) {
      // Enter the section on a `## Steps`-style heading; leave it on any other heading.
      inSection = /^steps\b/i.test((header[2] ?? "").trim());
      continue;
    }
    if (!inSection) continue;
    const numbered = line.match(/^\s*(\d+)[.)]\s+(.+?)\s*$/);
    if (numbered) {
      const text = (numbered[2] ?? "").trim();
      if (text) steps.push({ step: steps.length + 1, text, completed: false });
    }
  }
  return steps;
}

// --- rebuild (the scan-after-marker discipline) -------------------------------------------------

function isAssistantText(entry: {
  type?: string;
  message?: { role?: string; content?: unknown };
}): string | null {
  if (entry.type !== "message" || entry.message?.role !== "assistant") return null;
  const content = entry.message.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((b) => {
        const block = b as { type?: string; text?: string };
        return block.type === "text" && typeof block.text === "string" ? block.text : "";
      })
      .filter(Boolean)
      .join("\n");
  }
  return null;
}

/**
 * Rebuild checkpoint state from the branch. The latest `perk:checkpoint` entry is the **marker**
 * (its `steps` carry completion persisted on prior turns); we then re-fold `[DONE:n]` from assistant
 * messages **after** that marker only — so stale `[DONE:n]` from a previous execution can't
 * resurrect a step (the subtlety pi best-practices §4 flags). No checkpoint entry ⟹ inert.
 */
export function rebuildCheckpoint(branch: readonly BranchEntry[]): CheckpointState {
  let markerIdx = -1;
  let seed: CheckpointStep[] | null = null;
  for (let i = branch.length - 1; i >= 0; i--) {
    const e = branch[i] as BranchEntry & { data?: { steps?: CheckpointStep[] } };
    if (e?.type === "custom" && e.customType === CHECKPOINT_TYPE) {
      const stored = e.data?.steps;
      if (Array.isArray(stored)) {
        seed = stored.map((s) => ({ step: s.step, text: s.text, completed: !!s.completed }));
        markerIdx = i;
      }
      break;
    }
  }
  if (seed === null) return { steps: [] };

  const after: string[] = [];
  for (let i = markerIdx + 1; i < branch.length; i++) {
    const text = isAssistantText(branch[i] as never);
    if (text) after.push(text);
  }
  markCompletedSteps(after.join("\n"), seed);
  return { steps: seed };
}

// --- the controller -----------------------------------------------------------------------------

function progressLine(state: CheckpointState): string {
  const done = state.steps.filter((s) => s.completed).length;
  return `${done}/${state.steps.length}`;
}

/** Surface progress in the UI (guarded — headless never touches setStatus/setWidget). */
function renderStatus(ctx: ExtensionContext, state: CheckpointState): void {
  if (!ctx.hasUI) return;
  if (isInert(state)) {
    ctx.ui.setStatus("perk-checkpoints", undefined);
    ctx.ui.setWidget("perk-checkpoints", undefined);
    return;
  }
  ctx.ui.setStatus("perk-checkpoints", `📋 ${progressLine(state)}`);
  ctx.ui.setWidget(
    "perk-checkpoints",
    state.steps.map((s) => `${s.completed ? "☑" : "☐"} ${s.step}. ${s.text}`),
  );
}

function branchOf(ctx: ExtensionContext): BranchEntry[] {
  return ctx.sessionManager.getBranch() as unknown as BranchEntry[];
}

/**
 * Register perk-owned checkpoints. Seeds on `session_start` from the plan body's `## Steps` (only in
 * an active workflow, and only once — a later session keeps the existing entry); rebuilds on
 * `session_start` AND `session_tree`; advances on `turn_end`; lists via `/checkpoints`.
 */
export function registerCheckpoints(pi: ExtensionAPI): void {
  pi.on("session_start", async (_event, ctx) => {
    try {
      const branch = branchOf(ctx);
      const existing = rebuildCheckpoint(branch);
      // Seed once: only when there is no checkpoint yet, a workflow is active, and the plan body
      // carries a `## Steps` list. Otherwise stay inert (no entry appended).
      if (isInert(existing)) {
        const active = rebuildWorkflowState(branch).active_plan_ref != null;
        const steps = active ? extractSteps(readPlanBody(ctx.cwd)) : [];
        if (steps.length > 0) {
          pi.appendEntry(CHECKPOINT_TYPE, { steps });
          renderStatus(ctx, { steps });
          return;
        }
      }
      renderStatus(ctx, existing);
    } catch (error) {
      console.error(`perk: checkpoint seed/rebuild failed on session_start — ${error}`);
    }
  });

  pi.on("session_tree", async (_event, ctx) => {
    try {
      renderStatus(ctx, rebuildCheckpoint(branchOf(ctx)));
    } catch (error) {
      console.error(`perk: checkpoint rebuild failed on session_tree — ${error}`);
    }
  });

  pi.on("turn_end", async (event, ctx) => {
    try {
      const state = rebuildCheckpoint(branchOf(ctx));
      if (isInert(state)) return; // nothing to track
      const text = isAssistantText(event.message as never);
      if (text === null) return;
      if (markCompletedSteps(text, state.steps) > 0) {
        // Persist the advanced completion as a new marker entry (carries completion forward).
        pi.appendEntry(CHECKPOINT_TYPE, { steps: state.steps });
        renderStatus(ctx, state);
      }
    } catch (error) {
      console.error(`perk: checkpoint advance failed on turn_end — ${error}`);
    }
  });

  pi.registerCommand("checkpoints", {
    description: "Show perk implementation checkpoints (read-only).",
    handler: async (_args, ctx) => {
      const state = rebuildCheckpoint(branchOf(ctx));
      const message = isInert(state)
        ? "perk: no checkpoints — this plan has no `## Steps` list (checkpoints are inert)."
        : `perk checkpoints (${progressLine(state)}):\n${state.steps
            .map((s) => `${s.completed ? "✓" : "○"} ${s.step}. ${s.text}`)
            .join("\n")}`;
      if (ctx.hasUI) ctx.ui.notify(message, "info");
      else console.error(message);
    },
  });
}
