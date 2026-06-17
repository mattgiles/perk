// btw — extracted pure core (the perk extracted-core pattern: pure helpers split out so they are
// unit-testable offline, without constructing a live pi session/overlay).
//
// Vendored from `mitsuhiko/agent-stuff` `extensions/btw.ts` (MIT) and adapted for perk: the helpers
// below were lifted verbatim except for the conformance changes called out inline (the extended
// `stripDynamicSystemPromptFooter` regex; `sideSessionTools`, the perk gate-mirror; and the §5
// themed-glyph conformance in `renderToolCallLines`/`renderErrorLine` — `❌`→`✗`, running `⚙`→`▸`).

import { truncateToWidth } from "@earendil-works/pi-tui";

/** The minimal theme surface the pure renderers need (pi's real `Theme` satisfies it). */
export interface ThemeLike {
  fg(color: string, text: string): string;
}

export type ToolCallStatus = "running" | "done" | "error";

export interface ToolCallInfo {
  toolCallId: string;
  toolName: string;
  args: string;
  status: ToolCallStatus;
}

/** A thread item as `formatThread` consumes it (the question/answer subset of `BtwDetails`). */
export interface ThreadItemLike {
  question: string;
  answer: string;
}

/**
 * Strip pi's dynamic system-prompt footer (the trailing `Current date…` / `Current working
 * directory:` lines) so the side session's seeded system prompt is stable.
 *
 * perk conformance: the live perk/pi prompt footer reads `Current date:` (not `Current date and
 * time:`), so this also strips the `Current date:` form. The original only matched
 * `Current date and time:`.
 */
export function stripDynamicSystemPromptFooter(systemPrompt: string): string {
  return systemPrompt
    .replace(/\nCurrent date(?: and time)?:[^\n]*(?:\nCurrent working directory:[^\n]*)?$/u, "")
    .replace(/\nCurrent working directory:[^\n]*$/u, "")
    .trim();
}

/** Join the text parts of an assistant message's content into a trimmed string. */
export function extractText(parts: readonly { type: string; text?: string }[]): string {
  return parts
    .filter((part) => part.type === "text")
    .map((part) => part.text ?? "")
    .join("\n")
    .trim();
}

/** Extract the assistant text from a raw stream event message (defensive, untyped input). */
export function extractEventAssistantText(message: unknown): string {
  if (!message || typeof message !== "object") {
    return "";
  }

  const maybeMessage = message as { role?: unknown; content?: unknown };
  if (maybeMessage.role !== "assistant" || !Array.isArray(maybeMessage.content)) {
    return "";
  }

  return maybeMessage.content
    .filter((part): part is { type: "text"; text: string } => {
      return !!part && typeof part === "object" && (part as { type?: unknown }).type === "text";
    })
    .map((part) => part.text)
    .join("\n")
    .trim();
}

/**
 * The pure core of `getLastAssistantMessage`: the last `role === "assistant"` message in an array,
 * or null. `btw.ts` calls it with `session.state.messages`.
 */
export function lastAssistantMessage<T extends { role: string }>(messages: readonly T[]): T | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message && message.role === "assistant") {
      return message;
    }
  }
  return null;
}

/** Format a side thread for summary handoff (`User: …\nAssistant: …`, `---`-separated). */
export function formatThread(thread: readonly ThreadItemLike[]): string {
  return thread
    .map((item) => `User: ${item.question.trim()}\nAssistant: ${item.answer.trim()}`)
    .join("\n\n---\n\n");
}

/** Render the first argument of a tool call to a short label (truncated for the transcript). */
export function formatToolArgs(toolName: string, args: unknown): string {
  if (!args || typeof args !== "object") return "";
  const a = args as Record<string, unknown>;
  switch (toolName) {
    case "bash":
      return typeof a.command === "string"
        ? truncateToWidth(a.command.split("\n")[0] ?? "", 50, "…")
        : "";
    case "read":
    case "write":
    case "edit":
      return typeof a.path === "string" ? a.path : "";
    default: {
      const first = Object.values(a)[0];
      return typeof first === "string" ? truncateToWidth(first.split("\n")[0] ?? "", 40, "…") : "";
    }
  }
}

/**
 * The gate-mirror decision (plan decision 1): the side session's toolset mirrors perk's read-only
 * gate. When read-only it gets `["read"]` only — a foreign session's `bash` cannot be sandboxed by
 * perk's `isReadOnlyBashCommand`, so `bash` is excluded under read-only — preserving perk's
 * structural read-only guarantee; when read-write it gets the full set.
 */
export function sideSessionTools(readOnly: boolean): string[] {
  return readOnly ? ["read"] : ["read", "bash", "edit", "write"];
}

/**
 * The themed tool-call transcript lines (§5-conformed glyphs): running `▸` (`accent`), error `✗`
 * (`error`), done `✓` (`success`). Every line is width-truncated (the §4 D9 never-exceed-`width`
 * law). The charter-time `⚙` running glyph is conformed to `▸`.
 */
export function renderToolCallLines(
  toolCalls: readonly ToolCallInfo[],
  theme: ThemeLike,
  width: number,
): string[] {
  const lines: string[] = [];
  for (const tc of toolCalls) {
    const icon = tc.status === "running" ? "▸" : tc.status === "error" ? "✗" : "✓";
    const color = tc.status === "running" ? "accent" : tc.status === "error" ? "error" : "success";
    const label = theme.fg(color, `${icon} `) + theme.fg("toolTitle", tc.toolName);
    const argsText = tc.args ? theme.fg("dim", ` ${tc.args}`) : "";
    lines.push(truncateToWidth(`  ${label}${argsText}`, width, ""));
  }
  return lines;
}

/**
 * The themed pending-error transcript line (§5-conformed): the charter-time `❌` error glyph is
 * conformed to the themed `✗` (`error`).
 */
export function renderErrorLine(theme: ThemeLike, message: string): string {
  return theme.fg("error", `✗ ${message}`);
}
