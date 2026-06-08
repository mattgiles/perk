// #187 — the universal, first-party `ask_user_question` tool. Lets a model interactively ask the
// human a clarifying question during a turn (free-text, or a multiple-choice selection with an
// always-present "type a custom answer" escape) and continues its turn with the answer. It is
// NON-terminating and headless-fail-safe: with no interactive UI it returns a graceful no-user
// sentinel instead of blocking (the AGENTS.md headless-fail-safe convention).
//
// To be callable *during planning* the tool name is added to `READ_ONLY_TOOLS` in toolGating.ts —
// read-only mode otherwise hides every custom tool (the documented read-only gating trap). The
// stricter SDK_READ_ONLY_TOOLS (headless child sessions) is intentionally NOT touched.
//
// Structure: a pure, injectable core (`runAskUserQuestion`) over a minimal `AskUserUI` surface, plus
// a thin `registerAskUser` wrapper — mirrors ciExecutor.ts's pure-core + injected-fakes testability.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** The always-appended escape entry on the select path so preset options never trap the user. */
export const OTHER_CHOICE = "✏️ Other (type a custom answer)…";

/** The minimal structural UI surface the core needs (a subset of `ctx.ui`). */
export interface AskUserUI {
  select(
    title: string,
    options: string[],
    opts?: { signal?: AbortSignal },
  ): Promise<string | undefined>;
  input(
    title: string,
    placeholder?: string,
    opts?: { signal?: AbortSignal },
  ): Promise<string | undefined>;
}

/** The structured `details` surface for the tool result (failure/dismissal are non-throwing). */
export interface AskDetails {
  ok: boolean;
  /** Whether a real user answer was captured (false for headless / dismissed / empty). */
  answered: boolean;
}

/** A non-terminating tool result: the model continues its turn with the answer text. */
export type AskResult = { content: { type: "text"; text: string }[]; details: AskDetails };

const DISMISSED_TEXT = "(no answer — the user dismissed the prompt.)";
const NO_UI_TEXT =
  "(no interactive user available — proceed using your best judgment and state the assumption you made.)";
const NO_QUESTION_TEXT = "ask_user_question: no question provided.";

function answer(text: string, answered: boolean): AskResult {
  return { content: [{ type: "text", text }], details: { ok: true, answered } };
}

/**
 * The pure core: ask the user `question` (optionally with preset `options`) and resolve to a
 * non-terminating tool result carrying the answer text. Fully offline-testable with a fake UI.
 */
export async function runAskUserQuestion(args: {
  hasUI: boolean;
  ui: AskUserUI;
  question: string;
  options?: string[];
  signal?: AbortSignal;
}): Promise<AskResult> {
  const { hasUI, ui, options, signal } = args;
  const question = (args.question ?? "").trim();
  if (!question) return answer(NO_QUESTION_TEXT, false);
  if (!hasUI) return answer(NO_UI_TEXT, false);

  if (options && options.length > 0) {
    const choice = await ui.select(question, [...options, OTHER_CHOICE], { signal });
    if (choice === undefined) return answer(DISMISSED_TEXT, false);
    if (choice === OTHER_CHOICE) {
      const typed = await ui.input(question, undefined, { signal });
      return typed === undefined ? answer(DISMISSED_TEXT, false) : answer(typed, true);
    }
    return answer(choice, true);
  }

  const typed = await ui.input(question, undefined, { signal });
  return typed === undefined ? answer(DISMISSED_TEXT, false) : answer(typed, true);
}

const TOOL_GUIDELINES = [
  "Prefer this during planning to resolve genuine ambiguity rather than guessing.",
  "Ask ONE focused question at a time, and wait for the answer before the next.",
  "Provide `options` when the answer is a choice — a free-text escape is always added.",
  "Explore the codebase first: if a question is answerable from the code, read it instead of asking.",
];

/** Register the universal warm tool: `ask_user_question`. */
export function registerAskUser(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "ask_user_question",
    label: "Ask user",
    description:
      "Ask the human user a clarifying question and return their answer. Supports a free-text " +
      "prompt or a multiple-choice selection (a 'type a custom answer' escape is always added). " +
      "NON-terminating: the turn continues with the answer. With no interactive UI it returns a " +
      "no-user sentinel instead of blocking.",
    promptSnippet: "Ask the user a clarifying question and get their answer",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["question"],
      properties: {
        question: { type: "string", description: "The question to ask the user." },
        options: {
          type: "array",
          items: { type: "string" },
          description:
            "Optional preset choices rendered as a selector; a free-text escape is always appended.",
        },
      },
    },
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const { question, options } = params as { question?: string; options?: string[] };
      return runAskUserQuestion({
        hasUI: ctx.hasUI,
        ui: ctx.ui,
        question: question ?? "",
        options,
        signal,
      });
    },
  });
}
