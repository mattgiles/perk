// The Pi adapter for the hunk watch feedback bridge (contracts.md §8.58): eligibility, message
// rendering, the narrow persisted-user-message acceptance scan, and the factory-scoped
// receiver controller index.ts wires into session_start/session_tree.
//
// Eligibility is deliberately strict — only the ONE interactive TUI implement session whose
// reconciled plan-ref matches the worktree's cache.plan-ref ever inspects the stream
// (`ctx.mode === "tui"`: `hasUI` also admits RPC and is NOT the gate). Acceptance is transcript
// OBSERVATION: `branchHasFeedbackMessage` matches only persisted user-role message entries —
// NOT the generic `branchCarries` serialize-everything scan, whose documented
// tool-result-quoting false positive would be too weak for this bridge's central guarantee.
// The residual false positive — a USER message quoting the exact `[feedback <id>]` literal —
// is accepted and documented (§8.58).

import { watch as fsWatch } from "node:fs";
import { type PlanRef, readPlanRef } from "../substrate/cache.ts";
import { planRefsEqual } from "../substrate/workflowState.ts";
import { type ReportTarget, report } from "../surfaces/report.ts";
import {
  createHunkFeedbackInbox,
  type FeedbackInboxHandle,
  type FeedbackTransport,
  type InboxTimers,
  type WatchFactory,
} from "./inbox.ts";
import type { FeedbackRecord } from "./store.ts";

// --- eligibility (pure) -----------------------------------------------------------------------

export interface EligibilityArgs {
  /** Pi's run mode (`ctx.mode`) — only `"tui"` is eligible. */
  mode: string | null;
  /** The effective stage: claim-recorded, reload-rebuilt, or fork-inherited. */
  stage: string | null;
  /** An env-adopted subagent child never receives feedback. */
  adopted: boolean;
  runId: string | null | undefined;
  piSessionId: string | null | undefined;
  /** The session's reconciled `active_plan_ref`. */
  activePlanRef: PlanRef | null;
  /** ONE fresh `readPlanRef` result — the same read supplies the consumer's plan id. */
  cachedRef: PlanRef | null;
}

export function feedbackEligibility(args: EligibilityArgs): boolean {
  return (
    args.mode === "tui" &&
    args.stage === "implement" &&
    !args.adopted &&
    typeof args.runId === "string" &&
    args.runId !== "" &&
    typeof args.piSessionId === "string" &&
    args.piSessionId !== "" &&
    args.cachedRef !== null &&
    planRefsEqual(args.activePlanRef, args.cachedRef)
  );
}

// --- rendering (pure) ---------------------------------------------------------------------------

/**
 * Flatten NON-HUMAN metadata (paths, ids) to one inert line before it is interpolated into the
 * rendered message: git filenames and note ids may carry newlines/control characters that
 * would otherwise break out of the descriptive bullet line and forge structure alongside the
 * trusted human body. Control characters become U+FFFD — never removed silently to "fix" the
 * string into a different valid value.
 */
export function sanitizeInline(value: string): string {
  // biome-ignore lint/suspicious/noControlCharactersInRegex: stripping controls is the point
  return value.replace(/[\u0000-\u001f\u007f]/g, "\ufffd");
}

/**
 * Render one batch as one real user message. The note bodies keep user-message authority (no
 * untrusted-data fencing — this is the human's own feedback); the bridge metadata around them
 * stays descriptive and is sanitized to inert single-line text. Anchors are evidence, not
 * authority — the trailer says so.
 */
export function renderFeedbackMessage(planId: string, batch: readonly FeedbackRecord[]): string {
  const safePlanId = sanitizeInline(planId);
  const displayId = /^\d+$/.test(safePlanId) ? `#${safePlanId}` : safePlanId;
  const bullets = batch.map((record) => {
    const body = record.body
      .split("\n")
      .map((line) => `  ${line}`)
      .join("\n");
    return (
      `- [feedback ${sanitizeInline(record.feedback_id)}] ${sanitizeInline(record.anchor.file_path)}, ` +
      `${record.anchor.side} line ${record.anchor.line}, hunk ${record.anchor.hunk_index + 1}:\n` +
      body
    );
  });
  return [
    `Human feedback from the live Hunk review of plan ${displayId}:`,
    "",
    bullets.join("\n\n"),
    "",
    "The anchors describe where each note sat in the reviewed diff when it was saved — they " +
      "are evidence, not authority. Inspect the current diff/files before acting on any note; " +
      "the code may have moved since.",
  ].join("\n");
}

/**
 * The observation needles: EVERY record's rendered `[feedback <id>]` literal (sanitized exactly
 * as rendered). Exact batch membership — not just the first record — must be proven in one
 * persisted message before a batch is acknowledged (§8.58): a reconstructed larger batch that
 * merely shares its first record with an older message must NOT be acked off that message.
 */
export function batchMarkers(batch: readonly FeedbackRecord[]): string[] {
  return batch.map((record) => `[feedback ${sanitizeInline(record.feedback_id)}]`);
}

// --- the acceptance scan (pure) ----------------------------------------------------------------

/** The structural slice of pi's `SessionMessageEntry` this scan narrows to. */
interface MessageEntrySlice {
  type?: unknown;
  message?: { role?: unknown; content?: unknown };
}

/** The text of one persisted USER-role message entry, or null for every other entry shape. */
function userMessageText(entry: unknown): string | null {
  if (typeof entry !== "object" || entry === null) return null;
  const slice = entry as MessageEntrySlice;
  if (slice.type !== "message") return null;
  const message = slice.message;
  if (typeof message !== "object" || message === null || message.role !== "user") return null;
  const content = message.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return null;
  const texts: string[] = [];
  for (const part of content) {
    if (typeof part !== "object" || part === null) continue;
    const text = (part as { text?: unknown }).text;
    if (typeof text === "string") texts.push(text);
  }
  return texts.join("\n");
}

/**
 * True when ONE persisted USER-role message entry on the branch carries EVERY marker — the
 * §8.58 acceptance evidence (exact batch membership, not first-record overlap). Tool results,
 * custom entries, and assistant messages can never satisfy it: only `type === "message"`
 * entries whose `message.role === "user"` are searched, and only their text content (a string
 * body, or the `text` parts of an array body). Residual false positive (accepted, §8.58): a
 * human user message quoting every exact `[feedback <id>]` literal of the batch.
 */
export function branchHasFeedbackMessage(
  entries: readonly unknown[],
  markers: readonly string[],
): boolean {
  if (markers.length === 0 || markers.some((marker) => marker === "")) return false;
  for (const entry of entries) {
    const text = userMessageText(entry);
    if (text === null) continue;
    if (markers.every((marker) => text.includes(marker))) return true;
  }
  return false;
}

// --- the controller ------------------------------------------------------------------------------

/** The `pi` slice the receiver injects through. `ExtensionAPI` satisfies it. */
export interface UserMessageSink {
  sendUserMessage(content: string, options?: { deliverAs?: "steer" | "followUp" }): void;
}

/** The `ctx` slice sync needs. `ExtensionContext` satisfies it. */
export interface ReceiverContext extends ReportTarget {
  cwd: string;
  isIdle(): boolean;
  sessionManager: { getBranch(): unknown[] };
}

export interface ReceiverSyncArgs {
  stage: string | null;
  adopted: boolean;
  runId: string | null | undefined;
  piSessionId: string | null | undefined;
  activePlanRef: PlanRef | null;
  mode: string | null;
}

export interface HunkFeedbackReceiver {
  /** Evaluate eligibility and open/close/re-key the inbox accordingly. Never throws. */
  sync(ctx: ReceiverContext, args: ReceiverSyncArgs): void;
  close(): void;
}

// Production timer/watcher deps — unref'd so a live inbox never pins the process open past
// session teardown (session_shutdown still closes cleanly and releases the lease).
const productionTimers: InboxTimers = {
  setTimeout: (fn, ms) => {
    const handle = setTimeout(fn, ms);
    handle.unref?.();
    return handle;
  },
  clearTimeout: (handle) => clearTimeout(handle as NodeJS.Timeout),
  setInterval: (fn, ms) => {
    const handle = setInterval(fn, ms);
    handle.unref?.();
    return handle;
  },
  clearInterval: (handle) => clearInterval(handle as NodeJS.Timeout),
};

const productionWatch: WatchFactory = (dir, onChange, onError) => {
  const watcher = fsWatch(dir, () => onChange());
  watcher.on("error", (error) => onError(error));
  watcher.unref?.();
  return { close: () => watcher.close() };
};

/**
 * The factory-scoped receiver controller (the `registerToolGating`/`createPerkStatus`
 * convention — no module globals). A `/reload` re-runs the extension factory and creates a
 * fresh controller; the lease's same-identity reacquire mints a FRESH token, so the stale
 * predecessor instance fails its next verifyLease and closes itself fail-closed.
 */
export function createHunkFeedbackReceiver(
  pi: UserMessageSink,
  deps: { timers?: InboxTimers; watch?: WatchFactory; now?: () => number } = {},
): HunkFeedbackReceiver {
  let active: { key: string; handle: FeedbackInboxHandle } | null = null;
  let passiveReportedKey: string | null = null;

  const close = (): void => {
    if (active === null) return;
    try {
      active.handle.close();
    } catch {
      // disposal is best-effort
    }
    active = null;
  };

  return {
    sync(ctx, args) {
      try {
        // ONE fresh read per sync: the same value feeds the eligibility match AND (on open)
        // the consumer identity's plan id.
        const cachedRef = readPlanRef(ctx.cwd);
        if (
          !feedbackEligibility({ ...args, cachedRef }) ||
          cachedRef === null ||
          typeof args.runId !== "string" ||
          typeof args.piSessionId !== "string"
        ) {
          close();
          return;
        }
        const planId = cachedRef.pr_id;
        const key = [ctx.cwd, args.runId, args.piSessionId, planId].join("\u0000");
        if (active !== null && active.key === key) return; // same-identity re-sync: no-op
        close();

        const transport: FeedbackTransport = {
          inject(batch: readonly FeedbackRecord[]) {
            const message = renderFeedbackMessage(planId, batch);
            // Idle → an ordinary next turn; busy → steer (never followUp — feedback should
            // reach the agent mid-flight, not queue behind the whole turn).
            if (ctx.isIdle()) pi.sendUserMessage(message);
            else pi.sendUserMessage(message, { deliverAs: "steer" });
          },
          isInjected(batch: readonly FeedbackRecord[]) {
            return branchHasFeedbackMessage(ctx.sessionManager.getBranch(), batchMarkers(batch));
          },
          isIdle: () => ctx.isIdle(),
        };
        const inbox = createHunkFeedbackInbox({
          now: deps.now ?? Date.now,
          timers: deps.timers ?? productionTimers,
          watch: deps.watch ?? productionWatch,
          report: (severity, message) => report(ctx, "hunk feedback", severity, message),
        });
        const result = inbox.open(
          { cwd: ctx.cwd, runId: args.runId, piSessionId: args.piSessionId, planId },
          transport,
        );
        if ("passive" in result) {
          if (passiveReportedKey !== key) {
            passiveReportedKey = key;
            report(ctx, "hunk feedback", "warning", `staying passive — ${result.reason}`);
          }
          return;
        }
        active = { key, handle: result };
      } catch (error) {
        report(ctx, "hunk feedback", "error", `receiver sync failed — ${error}`, {
          alsoLog: true,
        });
      }
    },
    close,
  };
}
