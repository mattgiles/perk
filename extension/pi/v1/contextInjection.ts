// The one marker-dedup'd context-injection mechanism (contracts §8.31 semantics) behind the
// five injected authoring/adapter contexts: gist, plan, objective-authoring, and the
// plannotator/tombell plan adapters all register the same `before_agent_start` + `context` hook
// pair around one injected, marker-dedup'd context. The MECHANICS live here — the live-evidence
// dedup, the stale-strip filter, the guarded reads; feature POLICY (eligibility, flavor
// selection, content construction, the customType/marker vocabulary) stays with each caller's
// `InjectedContextSpec` closures.
//
// Two authorities, deliberately distinct: `spec.select`/`spec.live` read the FULL branch
// (`branchOf` — eligibility/state survive compaction), while the dedup reads Pi's OWN live
// projection (`contextEvidence.ts`: `buildContextEntries()` → native messages) and asks the typed
// predicate whether the selected flavor's marker is still delivered — as user content (a cold
// prompt) or as the owned customType's content (a prior hidden copy). A copy Pi has compacted
// out of context re-injects on the next turn even though the historical entry still sits on the
// branch; a summary quoting the marker never counts. The submitting `event.prompt` is checked
// BEFORE the projection read: at `before_agent_start` a cold launch's prompt is not yet
// persisted, so only that check sees a cold seed on the launch turn.
//
// Failure semantics are asymmetric BY DESIGN: a failed branch read short-circuits INJECTION
// (no `select` call — an empty-branch fallback would wrongly inject for exclusion-based
// selectors like plan's, whose stage check passes on `undefined`); a failed projection read also
// returns without constructing or injecting content (a guessed copy could double-deliver); but
// the STRIP proceeds over `[]` (a throwing branch read must still remove a stale marker; every
// `live` closure is either branch-independent or fails closed to "not live" on `[]`). The strip
// never reads the projection.
//
// Deliberate NON-callers keep their own scan/strip semantics: `substrate/bindingDelivery.ts`
// (strips only its own customType — never user turns; projection errors escape its hook),
// `substrate/agentScratch.ts` (requires the exact current custom block, not a marker scan),
// `substrate/toolGating.ts` (full-branch scan — the strict once-per-selected-branch read-only
// marker), and `hunkFeedback/receiver.ts`.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { type BranchEntry, branchOf } from "../../substrate/workflowState.ts";
import {
  activeContextMessages,
  type ContextMessage,
  contextCarriesMarker,
} from "./contextEvidence.ts";

/**
 * One marker-dedup'd injected context: the owned customType + the flavor table. Each flavor is
 * declared ONCE — the marker literal keys its content thunk — so the strip set (every key), the
 * dedup key (the selected key), and the injected content cannot drift apart: `select` returns a
 * KEY of the table, never a free-floating marker/content pair.
 */
export interface InjectedContextSpec<K extends string = string> {
  customType: string;
  /**
   * The flavor table: marker literal → content thunk (plannotator: all three flavor markers).
   * The strip owns every key. A thunk is invoked ONLY after the dedup scan passes, preserving
   * the scan-before-construct ordering (config reads/renders never run on dedup-suppressed
   * turns). Caller contract: the rendered content carries its own key (the marker rides inside
   * the template bytes — pinned by each caller's content tests); a marker-less content would
   * defeat the dedup and re-inject every turn.
   */
  flavors: Readonly<Record<K, (ctx: ExtensionContext) => string>>;
  /** Feature policy: the flavor to inject this turn (a `flavors` key), or null (ineligible/defer). */
  select(ctx: ExtensionContext, branch: readonly BranchEntry[]): K | null;
  /** Feature policy: true while the injected context is still relevant (the strip fires when false). */
  live(ctx: ExtensionContext, branch: readonly BranchEntry[]): boolean;
}

/** The structural message slice the stale-strip filter inspects. */
interface StrippableMessage {
  customType?: string;
  role?: string;
  content?: unknown;
}

/**
 * The stale-strip filter (module-private — tests drive it through the registered hook): drop the
 * owned customType; drop `role === "user"` messages whose string content or text-part array
 * carries ANY owned marker (every `flavors` key); keep everything else (non-user roles are never
 * marker-scanned — a cold launch's user prompt is the only leak surface the markers ride).
 */
function stripStaleMessages<T>(messages: T[], customType: string, markers: readonly string[]): T[] {
  const hasMarker = (text: string): boolean => markers.some((m) => text.includes(m));
  return messages.filter((m) => {
    const msg = m as StrippableMessage;
    if (msg.customType === customType) return false;
    if (msg.role !== "user") return true;
    const content = msg.content;
    if (typeof content === "string") return !hasMarker(content);
    if (Array.isArray(content)) {
      return !content.some(
        (c) =>
          (c as { type?: string; text?: string }).type === "text" &&
          hasMarker((c as { text?: string }).text ?? ""),
      );
    }
    return true;
  });
}

/**
 * Register the inject/strip hook pair for one marker-dedup'd context (contracts §8.31
 * semantics). Call at the exact registration position the replaced hook pair held — hook
 * ordering is frozen by each installer's internal sequence.
 *
 * - `before_agent_start`: guarded branch read (a failed read short-circuits — no `select` call,
 *   no injection) → `spec.select` (null → no injection) → the submitting prompt carrying the
 *   SELECTED marker suppresses (cold delivery before persistence; another flavor's marker does
 *   not) → guarded projection read (a failed read returns — nothing constructed, nothing
 *   injected) → a live owned copy of the selected marker suppresses (the content thunk is never
 *   invoked) → inject `{ customType, content, display: false }`.
 * - `context`: guarded branch read (a failed read degrades to `[]` and proceeds) → keep
 *   everything while `spec.live`; otherwise strip the owned customType and any user turn
 *   carrying an owned marker.
 */
export function installInjectedContext<K extends string>(
  pi: ExtensionAPI,
  spec: InjectedContextSpec<K>,
): void {
  const markers = Object.keys(spec.flavors);
  pi.on("before_agent_start", async (event, ctx) => {
    let branch: readonly BranchEntry[];
    try {
      branch = branchOf(ctx);
    } catch {
      return;
    }
    const marker = spec.select(ctx, branch);
    if (marker === null) return;
    // Defensive over a widened K (string): an off-table key names no flavor — never inject.
    const content: ((ctx: ExtensionContext) => string) | undefined = spec.flavors[marker];
    if (content === undefined) return;
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
    let branch: readonly BranchEntry[];
    try {
      branch = branchOf(ctx);
    } catch {
      branch = [];
    }
    if (spec.live(ctx, branch)) return;
    return { messages: stripStaleMessages(event.messages, spec.customType, markers) };
  });
}
