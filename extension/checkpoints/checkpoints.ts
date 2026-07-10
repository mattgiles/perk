// perk-owned checkpoints. The implement-session progress tracker: seed an ordered step list from
// the plan body's `## Steps` numbered list, then advance it as the model emits `[DONE:n]` markers
// in its turns. State lives in a dedicated `perk:checkpoint` session entry — kept OFF the shared
// `perk:workflow-state` record (progress is high-churn; this avoids LWW-append smell).
//
// Opt-in + inert-by-default: perk plans are prose, so when no `## Steps` list is present the
// checkpoint degrades to inert (no crash, no nagging). The `perk-plan` skill documents the optional
// `## Steps` section as the forward path.
//
// The pure helpers (extractDoneSteps / markCompletedSteps + the step extractor) are perk-owned
// copies of pi's official `examples/extensions/plan-mode/utils.ts`, adapted to key off `## Steps`
// rather than plan-mode's `Plan:` header. Progress is surfaced headless-safe as the checkpoints
// segment of the composed `perk` status (a `📋 done/total · ▸n` segment published through the shared
// `PerkStatusHandle`) plus a themed `belowEditor` widget factory via `setStandingWidget` (stateless
// render, lines windowed to ≤4 steps and width-truncated); `/checkpoints` notifies a one-line
// summary. Accepted trade-off: pi's RPC mode drops factory widgets — the status chip +
// `/checkpoints` remain the RPC-visible surfaces (recorded in shared/contracts.md).
//
// TODO-PROVIDER DEFERRAL. perk's checkpoints are the *reference* todo provider (`perk-checkpoints`).
// They consume the resolved `[providers] todo` selection and **step the progress surface aside**
// when a foreign todo provider is selected — the todo-seam mirror of planMode.ts's plan-seam
// deferral. The four runtime surfaces guard on `isPerkCheckpointsReferenceSelected(ctx.cwd)` (read
// fresh per-event, fail-safe to the reference): `session_start`/`session_tree`/`turn_end`
// early-return **silently** (no seed, no advance, no render) so the foreign todo provider owns the
// surface uncontested; `/checkpoints` **announces** the deferral headless-safe. Runtime deferral
// only — registration-time vacating is the concrete foreign todo adapter's concern. Fail-safe: any
// config-read error → treated as the reference → zero change on the default selection.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { readHandoff, readPlanBody } from "../substrate/cache.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { loadPerkConfig } from "../substrate/config.ts";
import {
  loadProviders,
  PERK_CHECKPOINTS_PROVIDER_ID,
  resolveProviders,
} from "../substrate/providers.ts";
import {
  digestSessionData,
  readSessionArtifact,
  writeSessionArtifact,
} from "../substrate/sessionData.ts";
import type { BranchEntry } from "../substrate/workflowState.ts";
import { branchCarries, branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import {
  checkpointEntryRenderer,
  MARK_CHECKPOINTS,
  type PerkStatusHandle,
  progressLine,
  registerTranscriptRenderer,
  renderCoarsePlanLines,
  renderProgressLines,
  report,
  setStandingWidget,
  type ThemeLike,
  WIDGET_SLOT_CHECKPOINTS,
} from "../surfaces/surfaces.ts";
import { generatePlanSteps } from "./planSteps.ts";

/** The dedicated checkpoint session entry type. */
export const CHECKPOINT_TYPE = "perk:checkpoint";

/** The once-only generated-checklist context injection's custom message type. */
export const STEPS_CONTEXT_TYPE = "perk:steps-context";

/** The generated-steps session artifact (written via the accessor seam). */
export const STEPS_ARTIFACT_NAME = "plan-steps.json";

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
 * no `## Steps` section (the inert path). Only a recognizable `<n>. text` / `<n>) text` list
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
 * resurrect a step (a subtlety: stale `[DONE:n]` must not resurrect a step). No checkpoint entry ⟹ inert.
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

// --- generated steps -----------------------------------------------------------------------------

/**
 * Recomputed (never stored) generated-ness: a checkpoint state is "generated" iff it is non-inert
 * AND the current plan body parses to NO explicit `## Steps` — explicit steps could only have been
 * seeded from the body, so a non-inert state over a prose body must be LLM-derived.
 */
export function isGeneratedState(cwd: string, state: CheckpointState): boolean {
  return !isInert(state) && extractSteps(readPlanBody(cwd)).length === 0;
}

/** Promote generated step texts to checkpoint steps (1-based, all incomplete). */
function toCheckpointSteps(texts: string[]): CheckpointStep[] {
  return texts.map((text, i) => ({ step: i + 1, text, completed: false }));
}

/**
 * Read the generated-steps artifact through the accessor seam (provenance-pointer validated)
 * and return its steps — but only when its stored `plan_body_digest` matches the CURRENT plan
 * body (a replan/rematerialized body invalidates the cache). `null` on any refusal: no pointer,
 * digest mismatch (file or plan body), unparseable JSON, or an unusable steps shape.
 */
function readGeneratedStepsArtifact(
  ctx: Parameters<typeof readSessionArtifact>[0],
  planBody: string,
): string[] | null {
  const artifact = readSessionArtifact(ctx, STEPS_ARTIFACT_NAME);
  if (artifact === null) return null;
  try {
    const parsed = JSON.parse(artifact.content) as { plan_body_digest?: unknown; steps?: unknown };
    if (parsed.plan_body_digest !== digestSessionData(planBody)) return null;
    const steps = parsed.steps;
    if (!Array.isArray(steps) || steps.length < 2) return null;
    if (!steps.every((s) => typeof s === "string" && s.length > 0)) return null;
    return steps as string[];
  } catch {
    return null;
  }
}

/** The hidden context message teaching the model the generated checklist's exact numbering. */
function stepsContextContent(steps: readonly CheckpointStep[]): string {
  const lines = steps.map((s) => `${s.step}. ${s.text}`);
  return (
    "perk generated the following implementation checklist for this prose plan. Emit `[WIP:n]` " +
    "when you start step n and `[DONE:n]` when it completes, using EXACTLY these numbers:\n\n" +
    lines.join("\n")
  );
}

/**
 * Whether `e` is pi-core's stale-`ctx` compaction proxy error. During `session_compact` pi may
 * replace the running session out from under an in-flight event handler, invalidating the extension
 * runner's `ctx` proxy; the next read off it throws `/stale after session replacement/`. That is a
 * benign race (the dying session is discarded and the replacement session's `session_start`
 * re-renders), so the `session_compact` handler swallows it. Adapted from `@juicesharp/rpiv-todo`'s
 * `index.ts` `isStaleCtxError`.
 */
export function isStaleCtxError(e: unknown): boolean {
  return /stale after session replacement/.test(String(e));
}

// --- the controller -----------------------------------------------------------------------------

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

/** Surface progress in the UI (headless-safe — the handle + widget setter no-op without UI). */
function renderStatus(
  ctx: ExtensionContext,
  status: PerkStatusHandle,
  state: CheckpointState,
  branch: readonly BranchEntry[],
): void {
  if (isInert(state)) {
    // Coarse fallback: an active prose plan (no `## Steps`) still surfaces SOMETHING — the same
    // themed factory path as the steps widget (one dim line, stateless render, belowEditor).
    const coarse = coarseDescriptor(ctx, branch);
    if (coarse) {
      status.set(ctx, "checkpoints", `${MARK_CHECKPOINTS} ${coarse.stage}`);
      setStandingWidget(
        ctx,
        WIDGET_SLOT_CHECKPOINTS,
        (_tui: unknown, theme: ThemeLike) => ({
          render: (width: number) => renderCoarsePlanLines(coarse.planId, theme, width),
          invalidate: () => {},
        }),
        { placement: "belowEditor" },
      );
    } else {
      status.set(ctx, "checkpoints", undefined);
      setStandingWidget(ctx, WIDGET_SLOT_CHECKPOINTS, undefined);
    }
    return;
  }
  // Themed component factory: lines are computed inside render() per call — never cached — over
  // the freshly-rebuilt state snapshot; windowed + width-truncated in surfaces.ts.
  const snapshot = state;
  status.set(ctx, "checkpoints", `${MARK_CHECKPOINTS} ${progressLine(state)}`);
  setStandingWidget(
    ctx,
    WIDGET_SLOT_CHECKPOINTS,
    (_tui: unknown, theme: ThemeLike) => ({
      render: (width: number) => renderProgressLines(snapshot, theme, width),
      invalidate: () => {},
    }),
    { placement: "belowEditor" },
  );
}

/**
 * Register perk-owned checkpoints. Seeds on `session_start` from the plan body's `## Steps` (only in
 * an active workflow, and only once — a later session keeps the existing entry); rebuilds on
 * `session_start` AND `session_tree`; advances on `turn_end`; lists via `/checkpoints`.
 */
export function registerCheckpoints(pi: ExtensionAPI, status: PerkStatusHandle): void {
  // Transcript marker for `perk:checkpoint` snapshots (audit §2.3): renderer body in surfaces.ts,
  // registration = wiring, feature-detect inside the seam (pre-0.80.4 hosts stay inert). No
  // todo-provider deferral here: entries exist only when perk's checkpoints appended them, so
  // rendering history stays correct under any later provider selection.
  registerTranscriptRenderer(pi, CHECKPOINT_TYPE, checkpointEntryRenderer);

  pi.on("session_start", async (_event, ctx) => {
    try {
      // Todo-provider deferral: when a foreign `[providers] todo` is selected, step the progress
      // surface aside silently (no seed, no render) — the foreign provider owns it.
      if (!isPerkCheckpointsReferenceSelected(ctx.cwd)) return;
      const branch = branchOf(ctx);
      const existing = rebuildCheckpoint(branch);
      // Seed once: only when there is no checkpoint yet, a workflow is active, and the plan body
      // carries a `## Steps` list. Otherwise stay inert (no entry appended).
      if (isInert(existing)) {
        const wf = rebuildWorkflowState(branch);
        const active = wf.active_plan_ref != null;
        const planBody = active ? readPlanBody(ctx.cwd) : null;
        let steps = active ? extractSteps(planBody) : [];
        // Generation branch: an active IMPLEMENT session over a prose plan body (no usable
        // `## Steps` — the extractor already maps malformed sections to []) asks the session model
        // for a bounded checklist. Artifact reuse first (the pointer-validated cache, keyed on the
        // plan-body digest); every failure falls through to the coarse fallback unchanged.
        if (steps.length === 0 && planBody !== null && wf.active_plan_ref != null) {
          const stageRaw = wf.run_id != null ? readHandoff(ctx.cwd, wf.run_id)?.stage : undefined;
          if (stageRaw === "implement") {
            let texts = readGeneratedStepsArtifact(ctx, planBody);
            if (texts === null) {
              texts = await generatePlanSteps(ctx, planBody);
              if (texts !== null) {
                // Best-effort persistence for reuse across reload/compaction: a failed artifact
                // write (already warned by the seam) never drops a successful generation.
                writeSessionArtifact(
                  pi,
                  ctx,
                  STEPS_ARTIFACT_NAME,
                  `${JSON.stringify(
                    {
                      plan_id: wf.active_plan_ref.pr_id,
                      plan_body_digest: digestSessionData(planBody),
                      steps: texts,
                    },
                    null,
                    2,
                  )}\n`,
                );
              }
            }
            if (texts !== null) steps = toCheckpointSteps(texts);
          }
        }
        if (steps.length > 0) {
          pi.appendEntry(CHECKPOINT_TYPE, { steps });
          renderStatus(ctx, status, { steps, current: computeCurrent(steps, null) }, branch);
          return;
        }
      }
      renderStatus(ctx, status, existing, branch);
    } catch (error) {
      console.error(`perk: checkpoint seed/rebuild failed on session_start — ${error}`);
    }
  });

  pi.on("session_tree", async (_event, ctx) => {
    try {
      if (!isPerkCheckpointsReferenceSelected(ctx.cwd)) return;
      const branch = branchOf(ctx);
      renderStatus(ctx, status, rebuildCheckpoint(branch), branch);
    } catch (error) {
      console.error(`perk: checkpoint rebuild failed on session_tree — ${error}`);
    }
  });

  // session_compact re-render (adapted from `@juicesharp/rpiv-todo`): a compaction replaces the
  // session entries, so rebuild + re-render the progress surface (mirror `session_tree`: NO
  // re-seed). The catch arm diverges from the other handlers — a stale-`ctx` compaction race is
  // benign and swallowed silently (the replacement session's `session_start` re-renders); only
  // genuine replay bugs are logged per the log-not-throw convention.
  pi.on("session_compact", async (_event, ctx) => {
    try {
      if (!isPerkCheckpointsReferenceSelected(ctx.cwd)) return;
      const branch = branchOf(ctx);
      renderStatus(ctx, status, rebuildCheckpoint(branch), branch);
    } catch (error) {
      if (isStaleCtxError(error)) return;
      console.error(`perk: checkpoint rebuild failed on session_compact — ${error}`);
    }
  });

  pi.on("turn_end", async (event, ctx) => {
    try {
      if (!isPerkCheckpointsReferenceSelected(ctx.cwd)) return;
      const branch = branchOf(ctx);
      const state = rebuildCheckpoint(branch);
      if (isInert(state)) {
        // Coarse path: an active prose plan still surfaces a status (no entry to advance).
        renderStatus(ctx, status, state, branch);
        return;
      }
      const text = isAssistantText(event.message as never);
      if (text === null) {
        renderStatus(ctx, status, state, branch);
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
      renderStatus(ctx, status, state, branch);
    } catch (error) {
      console.error(`perk: checkpoint advance failed on turn_end — ${error}`);
    }
  });

  // The once-only generated-checklist injection: when the seeded checkpoints are
  // LLM-generated (recomputed: non-inert over a prose plan body), inject the numbered list as a
  // hidden context message so `[WIP:n]`/`[DONE:n]` markers use exactly these numbers. Injected
  // custom messages persist to the branch, so the branch-carries-it guard makes this once-only
  // (and a rewind past the injection naturally re-injects). No strip handler: the steps stay
  // relevant for the whole implement session (there is no off state).
  pi.on("before_agent_start", async (_event, ctx) => {
    try {
      if (!isPerkCheckpointsReferenceSelected(ctx.cwd)) return;
      const branch = branchOf(ctx);
      if (branchCarries(branch, STEPS_CONTEXT_TYPE)) return;
      const state = rebuildCheckpoint(branch);
      if (isInert(state) || !isGeneratedState(ctx.cwd, state)) return;
      return {
        message: {
          customType: STEPS_CONTEXT_TYPE,
          content: stepsContextContent(state.steps),
          display: false,
        },
      };
    } catch (error) {
      console.error(`perk: steps-context injection failed on before_agent_start — ${error}`);
    }
  });

  registerPerkCommand(pi, "checkpoints", {
    description: "Show perk implementation checkpoints (read-only).",
    handler: async (_args, ctx) => {
      // Todo-provider deferral: announce the deferral headless-safe and step aside when a
      // foreign `[providers] todo` is selected (the surface-facing mirror of the silent handlers).
      if (!isPerkCheckpointsReferenceSelected(ctx.cwd)) {
        const deferral = `checkpoints deferred — a foreign todo provider (\`${resolvedTodoProviderId(
          ctx.cwd,
        )}\`) is selected via [providers] todo.`;
        report(ctx, "checkpoints", "info", deferral);
        return;
      }
      const state = rebuildCheckpoint(branchOf(ctx));
      // One line: `done/total · ▸n <current step text>`; the tail drops when no
      // step is current (all complete).
      const current = state.steps.find((s) => s.step === state.current);
      const generated = !isInert(state) && isGeneratedState(ctx.cwd, state) ? " (generated)" : "";
      const message = isInert(state)
        ? "no checkpoints — this plan has no `## Steps` list (checkpoints are inert)."
        : `${progressLine(state)}${current ? ` ${current.text}` : ""}${generated}`;
      report(ctx, "checkpoints", "info", message);
    },
  });
}
