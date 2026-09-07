// Live-context evidence over Pi's OWN projection (contracts §8.31 semantics). Pi decides which
// session entries are still represented in model context (`sessionManager.buildContextEntries()`
// — the current leaf's compaction-aware entry list) and how each projects into a runtime message
// (`sessionEntryToContextMessages`); perk owns only the typed predicates over those native
// messages. There is no second traversal here: no compaction lookup, no kept-entry cutoff
// reconstruction, no retained-tail storage inspection — and no cache, registration, or
// persistent state.
//
// Evidence is TYPED, never serialized: a marker counts only when it rides user content (a cold
// launch's prompt) or the owning customType's custom content (a prior hidden injection). A
// compaction/branch summary quoting the marker, assistant/tool/bash output mentioning it, an
// unrelated custom, or plain `custom` state (`data.content`) is NOT a live delivery — Pi's
// converter keeps those roles distinguishable, so the predicate never has to guess from bytes.
//
// Full-branch history (`substrate/workflowState.ts::branchOf` + `branchCarries`) stays a separate
// authority: eligibility/state rebuilds and the strict once-per-selected-branch read-only marker
// read the whole branch; THIS leaf answers only "is the delivery live in model context now".
// Projection/conversion failures propagate — a read failure is never manufactured into an empty
// (and therefore falsely clean) projection; each consumer decides its own failure policy.

import {
  type ExtensionContext,
  sessionEntryToContextMessages,
} from "@earendil-works/pi-coding-agent";

/** The minimal structural read the projection needs; `ExtensionContext` satisfies it. */
export interface ContextProjectionSource {
  sessionManager: Pick<ExtensionContext["sessionManager"], "buildContextEntries">;
}

/** Pi's native runtime message, exactly as its converter yields it (no perk message union). */
export type ContextMessage = ReturnType<typeof sessionEntryToContextMessages>[number];

/** The owner of a marker: the injected customType the marker's hidden copy rides under. */
export interface MarkerOwner {
  customType: string;
  marker: string;
}

/**
 * The messages Pi currently projects into model context for the selected branch, BEFORE any
 * extension `context` filter runs: one `buildContextEntries()` read, flattened through Pi's
 * package-root converter. Returned unchanged (roles, shapes, and bytes are Pi's).
 */
export function activeContextMessages(source: ContextProjectionSource): ContextMessage[] {
  return source.sessionManager.buildContextEntries().flatMap(sessionEntryToContextMessages);
}

/**
 * Whether a live delivery of `marker` is in `messages`: user content, or custom content whose
 * `customType` is exactly the owner's. A string must contain the marker; an array needs ONE valid
 * `{ type: "text", text: string }` part containing the whole marker — parts are never joined, so
 * a marker split across parts is not evidence, and non-text/malformed parts are ignored. Nothing
 * else (assistant/tool/bash output, other customs, summaries, metadata/`details`) ever counts.
 */
export function contextCarriesMarker(
  messages: readonly ContextMessage[],
  owner: MarkerOwner,
): boolean {
  return messages.some((message) => {
    if (message.role === "user") return contentCarries(message.content, owner.marker);
    if (message.role === "custom") {
      return (
        message.customType === owner.customType && contentCarries(message.content, owner.marker)
      );
    }
    return false;
  });
}

/** Narrow runtime content check (session files are parsed unvalidated — trust shapes, not types). */
function contentCarries(content: unknown, marker: string): boolean {
  if (typeof content === "string") return content.includes(marker);
  if (!Array.isArray(content)) return false;
  return content.some((part) => {
    if (typeof part !== "object" || part === null) return false;
    const { type, text } = part as { type?: unknown; text?: unknown };
    return type === "text" && typeof text === "string" && text.includes(marker);
  });
}
