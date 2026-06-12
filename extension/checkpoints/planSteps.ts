// #342 — generated checkpoint TODOs for prose plans: the second consumer of the structured-output
// substrate (the `planTitle.ts` idiom). When an implement session starts on a plan body that lacks
// a usable `## Steps` numbered list, checkpoints ask the session model for a bounded, ordered
// implementation checklist via a single structured tool call. Every failure mode (the offline
// gate, no model, unresolved auth, a model error, no tool call, schema-invalid args, an unusable
// sanitized list) returns `null`, so the caller's deterministic fallback (today's coarse prose
// behavior) takes over — a session start is never failed by this path.

import { Type } from "@earendil-works/pi-ai";
import {
  completeStructured,
  type ModelAuthContext,
  resolveModelAuth,
} from "../substrate/structuredOutput.ts";

/** Bounds shared by the schema and the sanitizer. */
const STEPS_MIN = 2;
const STEPS_MAX = 12;
const STEP_TEXT_MAX_CHARS = 200;

/** The structured result schema: a bounded, ordered list of concise imperative steps. */
const PlanStepsSchema = Type.Object({
  steps: Type.Array(Type.String({ minLength: 1, maxLength: STEP_TEXT_MAX_CHARS }), {
    minItems: STEPS_MIN,
    maxItems: STEPS_MAX,
    description:
      "Concise, ordered, imperative implementation steps covering the whole plan " +
      "(one short phrase per step, no numbering, no markdown).",
  }),
});

/** Cap the plan markdown handed to the model (steps need the plan, not an unbounded payload). */
export const STEPS_INPUT_CHAR_CAP = 24_000;

/**
 * Normalize raw model steps into a clean checkpoint list, or `null` when unusable. Pure: per item,
 * trims, strips a leading list marker the model may echo (`1.` / `1)` / `-` / `*`), collapses
 * internal whitespace/newlines to single spaces, truncates to ≤200 chars; drops empties; caps at
 * 12 items; returns `null` when fewer than 2 survive.
 */
export function sanitizeSteps(raw: string[]): string[] | null {
  const out: string[] = [];
  for (const item of raw) {
    if (typeof item !== "string") continue;
    let s = item.trim();
    // Strip a leading echoed list marker: `1.`, `1)`, `-`, `*`.
    s = s.replace(/^(?:\d+[.)]|[-*])\s+/, "");
    s = s.replace(/\s+/g, " ").trim();
    if (!s) continue;
    if (s.length > STEP_TEXT_MAX_CHARS) s = s.slice(0, STEP_TEXT_MAX_CHARS).trim();
    out.push(s);
    if (out.length >= STEPS_MAX) break;
  }
  return out.length >= STEPS_MIN ? out : null;
}

/**
 * The deterministic offline gate. `PERK_NO_LLM` (set by the test harness, never by the production
 * `perk` CLI) disables step generation so tests stay fully offline regardless of ambient API keys —
 * the same gate as `llmTitlesEnabled`. Pure and unit-testable.
 */
export function llmStepsEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return !env.PERK_NO_LLM;
}

/**
 * Best-effort: generate an ordered implementation checklist for `planMarkdown` via the session
 * model, or `null` on any failure / when the gate is on. Never throws. Reports a genuine model
 * error (`console.error`) but stays non-fatal — the caller falls back to the coarse prose path.
 */
export async function generatePlanSteps(
  ctx: ModelAuthContext,
  planMarkdown: string,
  signal?: AbortSignal,
): Promise<string[] | null> {
  if (!llmStepsEnabled()) return null;

  let auth: Awaited<ReturnType<typeof resolveModelAuth>>;
  try {
    auth = await resolveModelAuth(ctx);
  } catch {
    return null;
  }
  if (!auth.ok) return null; // silent: no model / no auth configured (fail-safe).

  const outcome = await completeStructured({
    model: auth.model,
    schema: PlanStepsSchema,
    toolName: "set_plan_steps",
    toolDescription: "Provide the ordered implementation checklist for the plan.",
    system:
      "You decompose software engineering plans into concise, ordered implementation checklists.",
    instruction:
      "Read this implementation plan and produce an ordered implementation checklist covering the " +
      "whole plan: 2–12 steps, each a single concise imperative phrase (no numbering, no markdown).",
    input: planMarkdown.slice(0, STEPS_INPUT_CHAR_CAP),
    apiKey: auth.apiKey,
    headers: auth.headers,
    signal,
    timeoutMs: 30_000,
  });
  if (!outcome.ok || !outcome.value) {
    // Report (don't swallow) a genuine model error; the session start still proceeds.
    if (!outcome.ok) console.error(`perk: plan-steps — ${outcome.error}`);
    return null;
  }
  return sanitizeSteps(outcome.value.steps);
}
