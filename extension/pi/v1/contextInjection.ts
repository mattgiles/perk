// The one marker-dedup'd context-injection mechanism (contracts §8.31 semantics) behind the
// five injected authoring/adapter contexts: gist, plan, objective-authoring, and the
// plannotator/tombell plan adapters all register the same `before_agent_start` + `context` hook
// pair around one injected, marker-dedup'd context. The MECHANICS live here — the active-window
// dedup scan, the stale-strip filter, the guarded branch read; feature POLICY (eligibility,
// flavor selection, content construction, the customType/marker vocabulary) stays with each
// caller's `InjectedContextSpec` closures.
//
// The dedup scans the COMPACTION-ACTIVE window (`branchCarries(activeContextWindow(branch),
// marker)` — the bindingDelivery composition): a live copy suppresses re-injection, and
// compaction dropping it from model context re-injects on the next turn even though the
// historical entry still sits on the branch.
//
// Failure semantics are asymmetric BY DESIGN: a failed branch read short-circuits INJECTION
// (no `select` call — an empty-branch fallback would wrongly inject for exclusion-based
// selectors like plan's, whose stage check passes on `undefined`) but the STRIP proceeds over
// `[]` (a throwing read must still remove a stale marker; every `live` closure is either
// branch-independent or fails closed to "not live" on `[]`).
//
// Deliberate NON-callers keep their own scan/strip semantics: `substrate/bindingDelivery.ts`
// (strips only its own customType — never user turns), `substrate/agentScratch.ts` (requires
// the exact current custom block, not a marker scan), `substrate/toolGating.ts` (full-branch
// scan — the strict once-per-session read-only marker), and `hunkFeedback/receiver.ts`.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  activeContextWindow,
  type BranchEntry,
  branchCarries,
  branchOf,
} from "../../substrate/workflowState.ts";

/** One marker-dedup'd injected context: the owned customType + its FULL marker set. */
export interface InjectedContextSpec {
  customType: string;
  /** Every marker the strip owns (plannotator: all three flavor markers). */
  markers: readonly string[];
  /**
   * Feature policy: the flavor to inject this turn, or null (ineligible/defer). `content` is a
   * thunk — invoked ONLY after the dedup scan passes, preserving the scan-before-construct
   * ordering (config reads/renders never run on dedup-suppressed turns).
   */
  select(
    ctx: ExtensionContext,
    branch: readonly BranchEntry[],
  ): { marker: string; content: () => string } | null;
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
 * carries ANY owned marker; keep everything else (non-user roles are never marker-scanned — a
 * cold launch's user prompt is the only leak surface the markers ride).
 */
function stripStaleMessages<T>(messages: T[], spec: InjectedContextSpec): T[] {
  const hasMarker = (text: string): boolean => spec.markers.some((m) => text.includes(m));
  return messages.filter((m) => {
    const msg = m as StrippableMessage;
    if (msg.customType === spec.customType) return false;
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
 *   no injection) → `spec.select` (null → no injection) → dedup on the SELECTED marker over the
 *   compaction-active window (a live copy suppresses; the content thunk is never invoked) →
 *   inject `{ customType, content, display: false }`.
 * - `context`: guarded branch read (a failed read degrades to `[]` and proceeds) → keep
 *   everything while `spec.live`; otherwise strip the owned customType and any user turn
 *   carrying an owned marker.
 */
export function installInjectedContext(pi: ExtensionAPI, spec: InjectedContextSpec): void {
  pi.on("before_agent_start", async (_event, ctx) => {
    let branch: readonly BranchEntry[];
    try {
      branch = branchOf(ctx);
    } catch {
      return;
    }
    const picked = spec.select(ctx, branch);
    if (picked === null) return;
    if (branchCarries(activeContextWindow(branch), picked.marker)) return;
    return {
      message: {
        customType: spec.customType,
        content: picked.content(),
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
    return { messages: stripStaleMessages(event.messages, spec) };
  });
}
