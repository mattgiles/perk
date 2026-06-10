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
//
// TODO-PROVIDER DEFERRAL (Node 3.1). perk's checkpoints are the *reference* todo provider
// (`perk-checkpoints`). They now *consume* the resolved `[providers] todo` selection and **step the
// progress surface aside** when a foreign todo provider is selected — the todo-seam mirror of
// planMode.ts's plan-seam deferral (Node 2.2). The four runtime surfaces guard on
// `isPerkCheckpointsReferenceSelected(ctx.cwd)` (read fresh per-event, fail-safe to the reference):
// `session_start`/`session_tree`/`turn_end` early-return **silently** (no seed, no advance, no
// render) so the foreign todo provider owns the progress surface uncontested; `/checkpoints`
// **announces** the deferral headless-safe. Runtime deferral only — registration-time vacating is
// the concrete foreign todo adapter's concern (Node 3.2). Fail-safe: any config-read error → treated
// as the reference → behavior-preserving, zero change on the default selection.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { readHandoff, readPlanBody } from "./cache.ts";
import { loadPerkConfig } from "./config.ts";
import { loadProviders, PERK_CHECKPOINTS_PROVIDER_ID, resolveProviders } from "./providers.ts";
import { report } from "./report.ts";
import type { BranchEntry } from "./workflowState.ts";
import { branchOf, rebuildWorkflowState } from "./workflowState.ts";

/** The dedicated checkpoint session entry type (D3). */
export const CHECKPOINT_TYPE = "perk:checkpoint";

/**
 * The resolved `[providers] todo` selection id for `cwd`, read fresh per-event (no static state —
 * the same per-event-read shape `resolvedPlanProviderId` uses in planMode.ts). Fail-safe to the
 * perk-checkpoints reference: any load/resolution failure (corrupt bundled set, etc.) returns the
 * reference id so perk's own checkpoints keep working — the default path is the hard guarantee.
 */
export function resolvedTodoProviderId(cwd: string): string {
  try {
    return resolveProviders(loadPerkConfig(cwd).providers, loadProviders()).todo.id;
  } catch {
    return PERK_CHECKPOINTS_PROVIDER_ID;
  }
}

/**
 * Whether perk's own checkpoints reference is the selected todo provider for `cwd`. When a foreign
 * todo provider is selected via `[providers] todo`, perk's progress surface steps aside (defers).
 */
export function isPerkCheckpointsReferenceSelected(cwd: string): boolean {
  return resolvedTodoProviderId(cwd) === PERK_CHECKPOINTS_PROVIDER_ID;
}

export interface CheckpointStep {
  step: number;
  text: string;
  completed: boolean;
}

export interface CheckpointState {
  steps: CheckpointStep[];
  /** The in-progress step number (derived from `[WIP:n]` + completion), or `null`. */
  current: number | null;
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

/** Extract `[WIP:n]` step numbers from a block of text (case-insensitive). */
export function extractWipSteps(text: string): number[] {
  const steps: number[] = [];
  for (const match of text.matchAll(/\[WIP:(\d+)\]/gi)) {
    const step = Number(match[1]);
    if (Number.isFinite(step)) steps.push(step);
  }
  return steps;
}

/** The last `[WIP:n]` in `text` whose step exists and is not completed, else `null`. */
export function latestWipStep(text: string, steps: CheckpointStep[]): number | null {
  const wips = extractWipSteps(text);
  for (let i = wips.length - 1; i >= 0; i--) {
    const n = wips[i] as number;
    const item = steps.find((s) => s.step === n);
    if (item && !item.completed) return n;
  }
  return null;
}

/**
 * Derive the in-progress step: `preferred` if it names an existing incomplete step; else the
 * lowest-numbered incomplete step; else `null` (all complete / no steps).
 */
export function computeCurrent(steps: CheckpointStep[], preferred: number | null): number | null {
  if (preferred != null) {
    const item = steps.find((s) => s.step === preferred);
    if (item && !item.completed) return preferred;
  }
  const lowest = steps.filter((s) => !s.completed).sort((a, b) => a.step - b.step)[0];
  return lowest ? lowest.step : null;
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
  if (seed === null) return { steps: [], current: null };

  const after: string[] = [];
  for (let i = markerIdx + 1; i < branch.length; i++) {
    const text = isAssistantText(branch[i] as never);
    if (text) after.push(text);
  }
  const afterText = after.join("\n");
  markCompletedSteps(afterText, seed);
  const current = computeCurrent(seed, latestWipStep(afterText, seed));
  return { steps: seed, current };
}

// --- the controller -----------------------------------------------------------------------------

function progressLine(state: CheckpointState): string {
  const done = state.steps.filter((s) => s.completed).length;
  const base = `${done}/${state.steps.length}`;
  return state.current != null ? `${base} · ▶${state.current}` : base;
}

/** The glyph for a step: ☑ completed, ▶ the current step, ☐ otherwise. */
function stepGlyph(state: CheckpointState, s: CheckpointStep): string {
  if (s.completed) return "☑";
  if (s.step === state.current) return "▶";
  return "☐";
}

/** A coarse descriptor of the active plan when there is no `## Steps` checklist (the prose path). */
interface CoarseDescriptor {
  stage: string;
  planId: string;
}

function coarseDescriptor(
  ctx: ExtensionContext,
  branch: readonly BranchEntry[],
): CoarseDescriptor | null {
  const wf = rebuildWorkflowState(branch);
  if (wf.active_plan_ref == null) return null;
  const stageRaw = wf.run_id != null ? readHandoff(ctx.cwd, wf.run_id)?.stage : undefined;
  const stage = typeof stageRaw === "string" && stageRaw ? stageRaw : "active";
  return { stage, planId: wf.active_plan_ref.pr_id };
}

/** Surface progress in the UI (guarded — headless never touches setStatus/setWidget). */
function renderStatus(
  ctx: ExtensionContext,
  state: CheckpointState,
  branch: readonly BranchEntry[],
): void {
  if (!ctx.hasUI) return;
  if (isInert(state)) {
    // Coarse fallback: an active prose plan (no `## Steps`) still surfaces SOMETHING.
    const coarse = coarseDescriptor(ctx, branch);
    if (coarse) {
      ctx.ui.setStatus("perk-checkpoints", `📋 ${coarse.stage}`);
      ctx.ui.setWidget("perk-checkpoints", [
        `Plan #${coarse.planId}: prose plan — no \`## Steps\` checklist`,
      ]);
    } else {
      ctx.ui.setStatus("perk-checkpoints", undefined);
      ctx.ui.setWidget("perk-checkpoints", undefined);
    }
    return;
  }
  ctx.ui.setStatus("perk-checkpoints", `📋 ${progressLine(state)}`);
  ctx.ui.setWidget(
    "perk-checkpoints",
    state.steps.map((s) => `${stepGlyph(state, s)} ${s.step}. ${s.text}`),
  );
}

/**
 * Register perk-owned checkpoints. Seeds on `session_start` from the plan body's `## Steps` (only in
 * an active workflow, and only once — a later session keeps the existing entry); rebuilds on
 * `session_start` AND `session_tree`; advances on `turn_end`; lists via `/checkpoints`.
 */
export function registerCheckpoints(pi: ExtensionAPI): void {
  pi.on("session_start", async (_event, ctx) => {
    try {
      // Todo-provider deferral (Node 3.1): when a foreign `[providers] todo` is selected, step the
      // progress surface aside silently (no seed, no render) — the foreign provider owns it.
      if (!isPerkCheckpointsReferenceSelected(ctx.cwd)) return;
      const branch = branchOf(ctx);
      const existing = rebuildCheckpoint(branch);
      // Seed once: only when there is no checkpoint yet, a workflow is active, and the plan body
      // carries a `## Steps` list. Otherwise stay inert (no entry appended).
      if (isInert(existing)) {
        const active = rebuildWorkflowState(branch).active_plan_ref != null;
        const steps = active ? extractSteps(readPlanBody(ctx.cwd)) : [];
        if (steps.length > 0) {
          pi.appendEntry(CHECKPOINT_TYPE, { steps });
          renderStatus(ctx, { steps, current: computeCurrent(steps, null) }, branch);
          return;
        }
      }
      renderStatus(ctx, existing, branch);
    } catch (error) {
      console.error(`perk: checkpoint seed/rebuild failed on session_start — ${error}`);
    }
  });

  pi.on("session_tree", async (_event, ctx) => {
    try {
      if (!isPerkCheckpointsReferenceSelected(ctx.cwd)) return;
      const branch = branchOf(ctx);
      renderStatus(ctx, rebuildCheckpoint(branch), branch);
    } catch (error) {
      console.error(`perk: checkpoint rebuild failed on session_tree — ${error}`);
    }
  });

  pi.on("turn_end", async (event, ctx) => {
    try {
      if (!isPerkCheckpointsReferenceSelected(ctx.cwd)) return;
      const branch = branchOf(ctx);
      const state = rebuildCheckpoint(branch);
      if (isInert(state)) {
        // Coarse path: an active prose plan still surfaces a status (no entry to advance).
        renderStatus(ctx, state, branch);
        return;
      }
      const text = isAssistantText(event.message as never);
      if (text === null) {
        renderStatus(ctx, state, branch);
        return;
      }
      const advanced = markCompletedSteps(text, state.steps) > 0;
      // A WIP declared THIS turn wins; otherwise preserve the prior `current` (unless it completed).
      state.current = computeCurrent(
        state.steps,
        latestWipStep(text, state.steps) ?? state.current,
      );
      if (advanced) {
        // Persist the advanced completion as a new marker entry (carries completion forward).
        pi.appendEntry(CHECKPOINT_TYPE, { steps: state.steps });
      }
      // Always re-render: `current` can change without completion advancing.
      renderStatus(ctx, state, branch);
    } catch (error) {
      console.error(`perk: checkpoint advance failed on turn_end — ${error}`);
    }
  });

  pi.registerCommand("checkpoints", {
    description: "Show perk implementation checkpoints (read-only).",
    handler: async (_args, ctx) => {
      // Todo-provider deferral (Node 3.1): announce the deferral headless-safe and step aside when a
      // foreign `[providers] todo` is selected (the surface-facing mirror of the silent handlers).
      if (!isPerkCheckpointsReferenceSelected(ctx.cwd)) {
        const deferral = `checkpoints deferred — a foreign todo provider (\`${resolvedTodoProviderId(
          ctx.cwd,
        )}\`) is selected via [providers] todo.`;
        report(ctx, "checkpoints", "info", deferral);
        return;
      }
      const state = rebuildCheckpoint(branchOf(ctx));
      const message = isInert(state)
        ? "perk: no checkpoints — this plan has no `## Steps` list (checkpoints are inert)."
        : `perk checkpoints (${progressLine(state)}):\n${state.steps
            .map((s) => `${stepGlyph(state, s)} ${s.step}. ${s.text}`)
            .join("\n")}`;
      if (ctx.hasUI) ctx.ui.notify(message, "info");
      else console.error(message);
    },
  });
}
