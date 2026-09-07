import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import type { DraftReviewRegistration } from "../../session/draftReviewState.ts";
import { report } from "../../surfaces/report.ts";
import { createDraftReviewDecisions, type DraftReviewSnapshot } from "./draftReviewDecisions.ts";
import type { PlannotatorRefusal, PlannotatorReviewOutcome } from "./providers/plannotator.ts";
import type { ReviewOutcome, ToolResult } from "./review.ts";

export interface PreparedDraftReview {
  snapshot: DraftReviewSnapshot;
  registration: DraftReviewRegistration;
  signal: AbortSignal;
  isCurrent(): boolean;
  dispose(): void;
}
export interface DraftReviewAccess {
  prepare(
    ctx: ExtensionContext,
    parameter?: string,
    signal?: AbortSignal,
  ): { ok: true; value: PreparedDraftReview } | { ok: false; refusal: PlannotatorRefusal };
}

export interface RegisteredDraftReviewBridge extends DraftReviewAccess {
  review(
    plan: string,
    registration: DraftReviewRegistration,
    signal?: AbortSignal,
  ): Promise<PlannotatorReviewOutcome>;
}
class DraftReviewTransportStop extends Error {
  readonly refusal: PlannotatorRefusal;
  constructor(refusal: PlannotatorRefusal) {
    super(refusal.detail);
    this.refusal = refusal;
  }
}
export function draftReviewRefusalText(refusal: PlannotatorRefusal): string {
  return `Draft review stopped (${refusal.code}, ${refusal.phase}): ${refusal.detail}. Do not retry a save or discard retained review state; human reconciliation is required.`;
}
export function draftReviewRefusalResult(refusal: PlannotatorRefusal): ToolResult {
  return {
    content: [
      {
        type: "text",
        text: draftReviewRefusalText(refusal),
      },
    ],
    details: { ok: false, status: "refused", reason: refusal.code, phase: refusal.phase },
  };
}
export async function captureDraftReviewRefusal<T>(
  work: Promise<T>,
): Promise<T | PlannotatorRefusal> {
  try {
    return await work;
  } catch (error) {
    if (error instanceof DraftReviewTransportStop) return error.refusal;
    throw error;
  }
}
/** Keep provider refusals at the Pi edge; feature policy never sees a synthetic skip/denial. */
export async function reviewRegisteredDraft(
  bridge: RegisteredDraftReviewBridge,
  ctx: ExtensionContext,
  markdown: string,
  signal?: AbortSignal,
): Promise<ReviewOutcome> {
  if (signal?.aborted) return { status: "aborted" };
  const prepared = bridge.prepare(ctx, markdown, signal);
  if (!prepared.ok) throw new DraftReviewTransportStop(prepared.refusal);
  const review = prepared.value;
  try {
    if (review.snapshot.markdown !== markdown)
      throw new DraftReviewTransportStop({
        status: "refused",
        code: "source-changed",
        phase: "open",
        detail: "review source changed before registration",
      });
    const outcome = await bridge.review(markdown, review.registration, review.signal);
    if (outcome.status === "refused") throw new DraftReviewTransportStop(outcome);
    return outcome;
  } finally {
    review.dispose();
  }
}

/** One activation, shared by tool and browser entries. No startup discovery or replay. */
export function createDraftReviewActivation(pi: ExtensionAPI): DraftReviewAccess {
  let context: ExtensionContext | undefined;
  let decisions: ReturnType<typeof createDraftReviewDecisions> | undefined;
  let active: { abort: AbortController } | undefined;
  let ended = false;
  pi.on("session_shutdown", () => {
    ended = true;
    active?.abort.abort();
  });
  return {
    prepare(ctx, parameter, signal) {
      if (ended)
        return {
          ok: false,
          refusal: {
            status: "refused",
            code: "invalid-state",
            phase: "open",
            detail: "draft review activation ended",
          },
        };
      context = ctx;
      const live = () => {
        if (context === undefined) throw new Error("draft review context unavailable");
        return context;
      };
      decisions ??= createDraftReviewDecisions({
        cwd: ctx.cwd,
        sessionId: ctx.sessionManager.getSessionId(),
        session: () => openBranchWorkflowSession(pi, live()),
        entries: () => live().sessionManager.getBranch(),
        diagnostic: (code, detail) => {
          if (code !== "pending") report(live(), "draft-review", "warning", detail);
        },
      });
      const prepared = decisions.prepare(parameter);
      if (!prepared.ok)
        return {
          ok: false,
          refusal: {
            status: "refused",
            code: prepared.reason,
            phase: "open",
            detail: prepared.detail,
          },
        };
      const abort = new AbortController();
      const stop = () => abort.abort();
      const parent = signal ?? ctx.signal;
      parent?.addEventListener("abort", stop, { once: true });
      if (parent?.aborted) stop();
      const token = { abort };
      const registration = prepared.value.registration;
      return {
        ok: true,
        value: {
          snapshot: prepared.value.snapshot,
          signal: abort.signal,
          isCurrent: () => active === token,
          dispose() {
            parent?.removeEventListener("abort", stop);
            abort.abort();
          },
          registration: {
            ...registration,
            open(requestId) {
              const result = registration.open(requestId);
              if (result.ok) {
                // The synchronous state hook has released exclusion before predecessor teardown.
                const prior = active;
                active = token;
                prior?.abort.abort();
              }
              return result;
            },
          },
        },
      };
    },
  };
}
