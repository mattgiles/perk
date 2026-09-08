// The one marker-dedup'd context-injection mechanism (contracts §8.31 semantics) behind the
// five injected authoring/adapter contexts: gist, plan, objective-authoring, and the
// plannotator/tombell plan adapters all register the same `before_agent_start` + `context` hook
// pair around one injected, marker-dedup'd context. The MECHANICS live here — the live-evidence
// dedup, the selection-driven retention filter, the guarded reads; feature POLICY (eligibility,
// flavor selection, content construction, the customType/marker vocabulary) stays with each
// caller's `InjectedContextSpec` closures.
//
// ONE decision drives both hooks: `spec.select` (the flavor to deliver this turn, or null). It
// reads the FULL branch (`branchOf` — eligibility/state survive compaction), while the dedup
// reads Pi's OWN live projection (`contextEvidence.ts`: `buildContextEntries()` → native
// messages) and asks the typed predicate whether the selected flavor's marker is still delivered
// — as user content (a cold prompt) or as the owned customType's content (a prior hidden copy).
// A copy Pi has compacted out of context re-injects on the next turn even though the historical
// entry still sits on the branch; a summary quoting the marker never counts. The submitting
// `event.prompt` is checked BEFORE the projection read: at `before_agent_start` a cold launch's
// prompt is not yet persisted, so only that check sees a cold seed on the launch turn.
//
// RETENTION follows SELECTION on the `context` event, and touches ONLY the owned customType: a
// null selection (ineligible, or eligibility could not be established — a failed branch read or
// a throwing selector) removes every owned custom message; a selected flavor retains only the
// owned copies carrying that flavor's marker and removes obsolete sibling flavors (a
// plan→objective transition under plannotator cannot retain the old plan-adapter instructions).
// User/task messages are NEVER removed for carrying an owned marker — a cold seed, a quoted
// marker, an `<untrusted_draft>` body are the human's/the door's input and stay byte-for-byte;
// assistant/tool messages and other features' custom messages are never inspected. This filters
// the OUTGOING model context only: persisted transcripts and compaction summaries are never
// rewritten.
//
// Failure semantics: a failed branch read short-circuits INJECTION (no `select` call — an
// empty-branch fallback would wrongly inject for a selector whose reads pass on `undefined`); a
// failed projection read also returns without constructing or injecting content (a guessed copy
// could double-deliver); on the `context` event the same failure fails CLOSED to "nothing
// selected" — stale owned guidance must never survive an unreadable branch. Retention never
// reads the projection.
//
// Deliberate NON-callers keep their own scan/strip semantics: `substrate/bindingDelivery.ts`
// (strips only its own customType — never user turns; projection errors escape its hook),
// `substrate/agentScratch.ts` (requires the exact current custom block, not a marker scan),
// `substrate/toolGating.ts` (full-branch scan — the strict once-per-selected-branch read-only
// marker; its `perk:mode-context` retention is independent of every authoring context here),
// and `hunkFeedback/receiver.ts`.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { type BranchEntry, branchOf } from "../../substrate/workflowState.ts";
import {
  activeContextMessages,
  type ContextMessage,
  contextCarriesMarker,
} from "./contextEvidence.ts";

/**
 * One marker-dedup'd injected context: the owned customType + the flavor table. Each flavor is
 * declared ONCE — the marker literal keys its content thunk — so the retention key, the dedup
 * key (the selected key), and the injected content cannot drift apart: `select` returns a KEY of
 * the table, never a free-floating marker/content pair.
 */
export interface InjectedContextSpec<K extends string = string> {
  customType: string;
  /**
   * The flavor table: marker literal → content thunk (plannotator: all three flavor markers).
   * A thunk is invoked ONLY after the dedup scan passes, preserving the scan-before-construct
   * ordering (config reads/renders never run on dedup-suppressed turns). Caller contract: the
   * rendered content carries its own key (the marker rides inside the template bytes — pinned by
   * each caller's content tests); a marker-less content would defeat the dedup (re-inject every
   * turn) AND the retention (an owned copy without its flavor's marker is removed as obsolete).
   */
  flavors: Readonly<Record<K, (ctx: ExtensionContext) => string>>;
  /**
   * Feature policy — the ONE eligibility/retention decision: the flavor to deliver this turn (a
   * `flavors` key), or null (ineligible/defer). Drives injection on `before_agent_start` AND the
   * owned-message retention on `context` (null removes every owned copy; a key retains only that
   * flavor's copies).
   */
  select(ctx: ExtensionContext, branch: readonly BranchEntry[]): K | null;
}

/** The structural message slice the retention filter inspects. */
interface OwnedMessage {
  customType?: string;
  content?: unknown;
}

/**
 * The owned-message retention filter (module-private — tests drive it through the registered
 * hook): messages of the owned customType survive only when a flavor is selected AND their
 * content carries that flavor's marker (a string-content or text-part scan of the OWNED copy
 * only); every other message — any role, any other customType — passes through untouched, marker
 * or not.
 */
function retainSelectedFlavor<T>(messages: T[], customType: string, marker: string | null): T[] {
  return messages.filter((m) => {
    const msg = m as OwnedMessage;
    if (msg.customType !== customType) return true;
    return marker !== null && carriesMarker(msg.content, marker);
  });
}

function carriesMarker(content: unknown, marker: string): boolean {
  if (typeof content === "string") return content.includes(marker);
  if (Array.isArray(content)) {
    return content.some(
      (c) =>
        (c as { type?: string; text?: string }).type === "text" &&
        ((c as { text?: string }).text ?? "").includes(marker),
    );
  }
  return false;
}

/**
 * Register the inject/retain hook pair for one marker-dedup'd context (contracts §8.31
 * semantics). Call at the exact registration position the replaced hook pair held — hook
 * ordering is frozen by each installer's internal sequence.
 *
 * - `before_agent_start`: guarded branch read (a failed read short-circuits — no `select` call,
 *   no injection) → `spec.select` (null → no injection) → the submitting prompt carrying the
 *   SELECTED marker suppresses (cold delivery before persistence; another flavor's marker does
 *   not) → guarded projection read (a failed read returns — nothing constructed, nothing
 *   injected) → a live owned copy of the selected marker suppresses (the content thunk is never
 *   invoked) → inject `{ customType, content, display: false }`.
 * - `context`: guarded branch read + `spec.select` (a failed read or a throwing selector fails
 *   closed to null) → retain the owned customType's copies carrying the selected flavor's marker
 *   only; remove every other owned copy (all of them on null). No other message is inspected.
 */
export function installInjectedContext<K extends string>(
  pi: ExtensionAPI,
  spec: InjectedContextSpec<K>,
): void {
  // Defensive over a widened K (string): an off-table key names no flavor — never inject or
  // retain on it.
  const flavorOf = (key: K | null): string | null =>
    key !== null && spec.flavors[key] !== undefined ? key : null;

  pi.on("before_agent_start", async (event, ctx) => {
    let branch: readonly BranchEntry[];
    try {
      branch = branchOf(ctx);
    } catch {
      return;
    }
    const marker = flavorOf(spec.select(ctx, branch));
    if (marker === null) return;
    const content = spec.flavors[marker as K];
    if (event.prompt.includes(marker)) return;
    let live: readonly ContextMessage[];
    try {
      live = activeContextMessages(ctx);
    } catch {
      return;
    }
    if (contextCarriesMarker(live, { customType: spec.customType, marker })) return;
    return {
      message: {
        customType: spec.customType,
        content: content(ctx),
        display: false,
      },
    };
  });

  pi.on("context", async (event, ctx) => {
    let selected: string | null;
    try {
      selected = flavorOf(spec.select(ctx, branchOf(ctx)));
    } catch {
      selected = null;
    }
    return { messages: retainSelectedFlavor(event.messages, spec.customType, selected) };
  });
}
