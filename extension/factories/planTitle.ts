// #129 — the first consumer of the structured-output substrate: a best-effort, fail-safe
// LLM-generated GitHub issue title for a perk plan. When a plan is saved WITHOUT an explicit title,
// the warm door asks the session model for a structured `{ title, category }` object and forwards
// the sanitized title to `perk plan-save --title`. Every failure mode (no model, unresolved auth,
// the offline gate, a model error, no tool call, schema-invalid args, an empty sanitized title)
// returns `null`, so the cold door's deterministic `plan.derive_title` fallback takes over and a
// save is never blocked. The `category` field exercises multi-field structured output but is
// intentionally ignored for now.

import { type Static, StringEnum, Type } from "@earendil-works/pi-ai";
import { completeStructured, type ModelAuthContext, resolveModelAuth } from "./structuredOutput.ts";

/** The structured result schema. `StringEnum` (not `Type.Enum`) per pi-ai's Google-compat guidance. */
const PlanTitleSchema = Type.Object({
  title: Type.String({
    minLength: 1,
    maxLength: 120,
    description:
      "A concise, imperative GitHub issue title for the plan (no trailing period, no markdown).",
  }),
  category: StringEnum(["feature", "fix", "refactor", "docs", "test", "chore"], {
    description: "The dominant kind of change (currently informational only).",
  }),
});

export type PlanTitleResult = Static<typeof PlanTitleSchema>;

/** Cap the plan markdown handed to the model (a title needs only the opening, not the whole plan). */
export const TITLE_INPUT_CHAR_CAP = 12000;

/** Max characters in the final issue title (mirrors the schema's `maxLength`). */
const TITLE_MAX_CHARS = 120;

/**
 * Normalize a raw model title into a clean, single-line issue title, or `null` if empty after
 * sanitizing. Pure: trims; strips a leading `"# "`; strips surrounding quotes/backticks; collapses
 * internal whitespace/newlines to single spaces; truncates to ≤120 chars on a word boundary where
 * practical.
 */
export function sanitizeTitle(raw: string): string | null {
  let s = raw.trim();
  if (!s) return null;
  // Strip a leading ATX heading marker (the model sometimes echoes the plan's `# ` heading).
  s = s.replace(/^#+\s*/, "");
  if (!s) return null;
  // Strip a single layer of surrounding quotes or backticks.
  const pairs: [string, string][] = [
    ['"', '"'],
    ["'", "'"],
    ["`", "`"],
  ];
  for (const [open, close] of pairs) {
    if (s.length >= 2 && s.startsWith(open) && s.endsWith(close)) {
      s = s.slice(1, -1).trim();
      break;
    }
  }
  // Collapse any internal whitespace/newlines to single spaces.
  s = s.replace(/\s+/g, " ").trim();
  if (!s) return null;
  if (s.length > TITLE_MAX_CHARS) {
    const head = s.slice(0, TITLE_MAX_CHARS);
    const lastSpace = head.lastIndexOf(" ");
    // Truncate on a word boundary when one exists past the halfway point; else a hard cut.
    s = (lastSpace > TITLE_MAX_CHARS / 2 ? head.slice(0, lastSpace) : head).trim();
  }
  return s || null;
}

/**
 * The deterministic offline gate. `PERK_NO_LLM` (set by the test harness, never by the production
 * `perk` CLI) disables title generation so tests stay fully offline regardless of ambient API keys.
 * Pure and unit-testable.
 */
export function llmTitlesEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return !env.PERK_NO_LLM;
}

/**
 * Best-effort: generate a GitHub issue title for `planMarkdown` via the session model, or `null` on
 * any failure / when the gate is on. Never throws. Reports a genuine model error
 * (`console.error`) but stays non-fatal — the save proceeds and the cold door derives the title.
 */
export async function generatePlanTitle(
  ctx: ModelAuthContext,
  planMarkdown: string,
  signal?: AbortSignal,
): Promise<string | null> {
  if (!llmTitlesEnabled()) return null;

  let auth: Awaited<ReturnType<typeof resolveModelAuth>>;
  try {
    auth = await resolveModelAuth(ctx);
  } catch {
    return null;
  }
  if (!auth.ok) return null; // silent: no model / no auth configured (fail-safe).

  const outcome = await completeStructured({
    model: auth.model,
    schema: PlanTitleSchema,
    toolName: "set_plan_title",
    toolDescription: "Provide the chosen title and category for the plan.",
    system: "You write concise, descriptive GitHub issue titles for software engineering plans.",
    instruction:
      "Read this implementation plan and choose a title and category. The title must be a concise, " +
      "imperative phrase, at most ~70 characters, with no trailing period and no markdown.",
    input: planMarkdown.slice(0, TITLE_INPUT_CHAR_CAP),
    apiKey: auth.apiKey,
    headers: auth.headers,
    signal,
  });
  if (!outcome.ok || !outcome.value) {
    // Report (don't swallow) a genuine model error; the save still proceeds.
    if (!outcome.ok) console.error(`perk: plan-title — ${outcome.error}`);
    return null;
  }
  return sanitizeTitle(outcome.value.title);
}
