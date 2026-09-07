import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import {
  type DeliveryCarrier,
  type DraftReviewRegistration,
  type RegistrationResult,
  type ReviewIdentity,
  reviewRefused,
  type SaveReceipt,
} from "../../session/draftReviewState.ts";
import type { WorkflowSession } from "../../session/workflowSession.ts";
import { report } from "../../surfaces/report.ts";
import {
  createDraftReviewDecisions,
  type DraftReviewCapability,
  type DraftReviewOperation,
  type DraftReviewSnapshot,
} from "./draftReviewDecisions.ts";
import { DRAFT_REVIEW_RECONCILIATION, draftReviewDiagnostic } from "./draftReviewDiagnostics.ts";
import { draftReviewDeliveryResult, staleDraftReviewResult } from "./draftReviewRendering.ts";
import type { PlannotatorRefusal, PlannotatorReviewOutcome } from "./providers/plannotator.ts";
import type { ReviewOutcome, ToolResult } from "./review.ts";

export interface PreparedDraftReview {
  snapshot: DraftReviewSnapshot;
  registration: DraftReviewRegistration;
  signal: AbortSignal;
  isCurrent(): boolean;
  /** Verify this review's readiness/transport invalidation before permitting fallback. */
  degrade(): RegistrationResult;
  /** IDs come only from verified registration and its matching completed transport outcome. */
  complete(
    outcome: Extract<ReviewOutcome, { status: "completed" }>,
    options: {
      effect: "save" | "revision";
      carrier: DeliveryCarrier;
      execute(capability: DraftReviewCapability): Promise<ToolResult>;
    },
  ): Promise<DraftReviewCompletion>;
  /** Transport cleanup does not assert that a queued result was delivered. */
  dispose(): void;
}
export interface DraftReviewAccess {
  prepare(
    ctx: ExtensionContext,
    parameter?: string,
    signal?: AbortSignal,
  ): { ok: true; value: PreparedDraftReview } | { ok: false; refusal: PlannotatorRefusal };
}

type Decisions = ReturnType<typeof createDraftReviewDecisions>;
export type DraftReviewCompletion = DraftReviewOperation<ToolResult | { status: "consumed" }> & {
  saveReceipt: SaveReceipt | null;
  gateExited: boolean;
  /** A definitive feature result survives later delivery/bookkeeping failure. */
  completedResult: ToolResult | null;
};
/** Required guarded APIs for migrating consumers; no optional production safety hooks. */
export interface DraftReviewRuntime extends DraftReviewAccess {
  mutate<T>(
    ctx: ExtensionContext,
    reason: Parameters<Decisions["mutate"]>[0],
    work: (session: WorkflowSession) => T,
    options?: Pick<NonNullable<Parameters<Decisions["mutate"]>[2]>, "draft">,
  ): DraftReviewOperation<T>;
  /** Bounded effects only. Invalidate synchronously and release BEFORE opening an editor. */
  mutateAsync<T>(
    ctx: ExtensionContext,
    reason: Parameters<Decisions["mutateAsync"]>[0],
    work: (session: WorkflowSession) => Promise<T>,
  ): Promise<DraftReviewOperation<T>>;
}

export interface RegisteredDraftReviewBridge extends DraftReviewRuntime {
  review(
    plan: string,
    registration: DraftReviewRegistration,
    signal?: AbortSignal,
  ): Promise<PlannotatorReviewOutcome>;
}
class DraftReviewTransportStop extends Error {
  readonly refusal: DraftReviewStop;
  constructor(refusal: DraftReviewStop) {
    super(refusal.detail);
    this.refusal = refusal;
  }
}
type DraftReviewStop = Omit<PlannotatorRefusal, "phase"> & {
  phase: PlannotatorRefusal["phase"] | "dispatch" | "mutation" | "observation";
};
export type DraftReviewConfirmedFacts = {
  saveReceipt?: SaveReceipt | null;
  gateExited?: boolean;
};
export function draftReviewRefusalText(
  refusal: DraftReviewStop,
  facts: DraftReviewConfirmedFacts = {},
): string {
  const receipt =
    facts.saveReceipt === undefined || facts.saveReceipt === null
      ? ""
      : ` Confirmed save: ${facts.saveReceipt.id} (${facts.saveReceipt.url}).`;
  const gate =
    facts.gateExited === true ? " The successful save already exited the read-only gate." : "";
  return `Draft review stopped (${refusal.code}, ${refusal.phase}): ${refusal.detail}.${receipt}${gate} Do not retry a save or discard retained review state; human reconciliation is required. Follow ${DRAFT_REVIEW_RECONCILIATION} (human-only; no in-place repair).`;
}
export function draftReviewRefusalResult(
  refusal: DraftReviewStop,
  facts: DraftReviewConfirmedFacts = {},
): ToolResult {
  return {
    content: [
      {
        type: "text",
        text: draftReviewRefusalText(refusal, facts),
      },
    ],
    details: {
      ok: false,
      status: "refused",
      reason: refusal.code,
      phase: refusal.phase,
      ...(facts.saveReceipt == null ? {} : { save_receipt: facts.saveReceipt }),
      ...(facts.gateExited === true ? { gate_exited: true } : {}),
    },
  };
}
export function draftReviewMutationValue<T>(result: DraftReviewOperation<T>): T {
  if (!result.ok)
    throw new DraftReviewTransportStop({
      status: "refused",
      code: result.reason,
      phase: "mutation",
      detail: result.detail,
    });
  return result.value;
}
export function draftReviewMutationRefusal(
  result: Extract<RegistrationResult, { ok: false }>,
  facts: DraftReviewConfirmedFacts = {},
): ToolResult {
  return draftReviewRefusalResult(
    {
      status: "refused",
      code: result.reason,
      phase: "mutation",
      detail: result.detail,
    },
    facts,
  );
}
export function draftReviewCompletionResult(result: DraftReviewCompletion): ToolResult {
  if (!result.ok)
    return draftReviewRefusalResult(
      {
        status: "refused",
        code: result.reason,
        phase: "dispatch",
        detail: result.detail,
      },
      result,
    );
  if ("content" in result.value) return result.value;
  return {
    content: [
      { type: "text", text: "Draft review delivery was already confirmed; no effects repeated." },
    ],
    details: { ok: true, status: "consumed" },
  };
}
export async function captureDraftReviewRefusal<T>(work: Promise<T>): Promise<T | DraftReviewStop> {
  try {
    return await work;
  } catch (error) {
    if (error instanceof DraftReviewTransportStop) return error.refusal;
    throw error;
  }
}
/** One activation, shared by tool and browser entries. No startup discovery or replay. */
export function createDraftReviewActivation(pi: ExtensionAPI): DraftReviewRuntime {
  let context: ExtensionContext | undefined;
  let decisions: Decisions | undefined;
  let identity: { cwd: string; sessionId: string; runId: string } | undefined;
  let ended = false;
  const transports = new Set<{ close(): void; prune(): void }>();
  let active: { close(): void } | undefined;

  function abandon() {
    ended = true;
    // Forgetting local expectations never clears durable intent or grants retry permission.
    decisions?.abandon();
    for (const transport of transports) transport.close();
    transports.clear();
  }
  function live(): ExtensionContext {
    if (ended || context === undefined || identity === undefined)
      throw new Error("draft review activation unavailable");
    try {
      const current = openBranchWorkflowSession(pi, context).currentRunIdentity();
      if (
        context.cwd !== identity.cwd ||
        context.sessionManager.getSessionId() !== identity.sessionId ||
        !current.ok ||
        current.runId !== identity.runId
      )
        throw new Error("draft review activation identity changed");
      return context;
    } catch {
      abandon();
      throw new Error("draft review activation identity unavailable or changed");
    }
  }
  function use(ctx: ExtensionContext): DraftReviewOperation<Decisions> {
    if (ended) return reviewRefused("invalid-state");
    try {
      const run = openBranchWorkflowSession(pi, ctx).currentRunIdentity();
      if (!run.ok) {
        if (identity !== undefined) abandon();
        return reviewRefused(run.reason);
      }
      const sessionId = ctx.sessionManager.getSessionId();
      if (
        identity !== undefined &&
        (ctx.cwd !== identity.cwd ||
          sessionId !== identity.sessionId ||
          run.runId !== identity.runId)
      ) {
        abandon();
        return reviewRefused("superseded");
      }
      identity ??= { cwd: ctx.cwd, sessionId, runId: run.runId };
      context = ctx;
      decisions ??= createDraftReviewDecisions({
        cwd: identity.cwd,
        sessionId: identity.sessionId,
        session: () => openBranchWorkflowSession(pi, live()),
        entries: () => live().sessionManager.getBranch(),
        diagnostic: (code, detail) => {
          if (code !== "pending") report(live(), "draft-review", "warning", detail);
        },
      });
      return { ok: true, value: decisions };
    } catch {
      abandon();
      return reviewRefused("io-error");
    }
  }
  function annotated<T extends RegistrationResult>(
    result: T,
    ctx: ExtensionContext,
    known?: ReviewIdentity,
  ): T {
    if (result.ok) return result;
    try {
      return {
        ...result,
        detail: draftReviewDiagnostic(
          result,
          identity?.cwd ?? ctx.cwd,
          openBranchWorkflowSession(pi, ctx),
          known,
          identity?.runId,
        ).detail,
      };
    } catch {
      return {
        ...result,
        detail: `${result.detail}. Diagnostic identity/namespace unavailable; no absence or no-effect claim`,
      };
    }
  }
  function diagnostic(result: RegistrationResult) {
    if (result.ok) return;
    // A failed notice cannot change a refusal into delivery or escape lifecycle cleanup.
    try {
      if (context !== undefined)
        report(
          context,
          "draft-review",
          "warning",
          draftReviewRefusalText({
            status: "refused",
            code: result.reason,
            phase: "observation",
            detail: annotated(result, context).detail,
          }),
        );
    } catch {
      console.error("perk: draft review lifecycle diagnostic unavailable");
    }
  }
  function observe(coordinator: Decisions): RegistrationResult {
    try {
      const result = coordinator.observe(live().sessionManager.getBranch());
      for (const transport of transports) transport.prune();
      return result;
    } catch {
      abandon();
      return reviewRefused("io-error");
    }
  }
  pi.on("turn_end", (_event, ctx) => {
    // No preparation means no locally expected delivery to discover.
    if (decisions === undefined || ended) return;
    const current = use(ctx);
    diagnostic(current.ok ? observe(current.value) : current);
  });
  pi.on("session_shutdown", (_event, ctx) => {
    if (ended) return;
    try {
      if (decisions !== undefined) {
        const current = use(ctx);
        if (current.ok) diagnostic(current.value.end(ctx.sessionManager.getBranch()));
        else diagnostic(current);
      }
    } catch {
      diagnostic(reviewRefused("io-error"));
    } finally {
      abandon();
    }
  });
  return {
    mutate(ctx, reason, work, options) {
      const current = use(ctx);
      return annotated(current.ok ? current.value.mutate(reason, work, options) : current, ctx);
    },
    async mutateAsync(ctx, reason, work) {
      const current = use(ctx);
      return annotated(current.ok ? await current.value.mutateAsync(reason, work) : current, ctx);
    },
    prepare(ctx, parameter, signal) {
      const current = use(ctx);
      const refused = (result: Extract<RegistrationResult, { ok: false }>) => ({
        ok: false as const,
        refusal: {
          status: "refused" as const,
          code: result.reason,
          phase: "open" as const,
          detail: annotated(result, ctx).detail,
        },
      });
      if (!current.ok) return refused(current);
      const coordinator = current.value;
      const observed = observe(coordinator);
      if (!observed.ok) return refused(observed);
      const prepared = coordinator.prepare(parameter);
      if (!prepared.ok) return refused(prepared);
      const snapshot = structuredClone(prepared.value.snapshot);
      const runId = snapshot.binding.runId;
      const abort = new AbortController();
      const parent = signal ?? ctx.signal;
      let id: ReviewIdentity | undefined;
      let disposed = false;
      const token = {
        prune() {
          if (disposed && (id === undefined || !coordinator.hasExpectation(id))) token.close();
        },
        close() {
          parent?.removeEventListener("abort", stop);
          abort.abort();
          transports.delete(token);
        },
      };
      const stop = () => {
        abort.abort();
        // An in-flight dispatch owns its claim and handles its own post-intent abort.
        // Released expectations can be settled now, using evidence before uncertainty.
        if (!ended && id !== undefined) {
          try {
            live();
            diagnostic(coordinator.interrupt(id));
            token.prune();
          } catch {
            abandon();
          }
        }
      };
      parent?.addEventListener("abort", stop, { once: true });
      if (parent?.aborted) stop();
      transports.add(token);
      const registration = prepared.value.registration;
      const check = (): RegistrationResult => {
        if (ended || disposed) return annotated(reviewRefused("invalid-state"), ctx, id);
        try {
          live();
          return { ok: true };
        } catch {
          return reviewRefused("superseded");
        }
      };
      return {
        ok: true,
        value: {
          snapshot: prepared.value.snapshot,
          signal: abort.signal,
          isCurrent() {
            if (ended || active !== token) return false;
            try {
              live();
              return true;
            } catch {
              return false;
            }
          },
          degrade() {
            const checked = check();
            if (!checked.ok) return checked;
            if (id === undefined) return annotated(reviewRefused("invalid-state"), ctx);
            return annotated(coordinator.degrade(id, runId), ctx, id);
          },
          async complete(outcome, options) {
            outcome = { ...outcome };
            options = { ...options, carrier: { ...options.carrier } };
            let completedResult: ToolResult | null = null;
            const checked = check();
            if (!checked.ok)
              return { ...checked, saveReceipt: null, gateExited: false, completedResult };
            if (id === undefined || id.reviewId === null || outcome.reviewId !== id.reviewId)
              return {
                ...reviewRefused("superseded"),
                saveReceipt: null,
                gateExited: false,
                completedResult,
              };
            const result = await coordinator.dispatch({
              id,
              runId,
              approved: outcome.approved,
              feedback: outcome.feedback,
              effect: options.effect,
              signal: abort.signal,
              async execute(capability) {
                const result =
                  capability.effect === "stale-reference"
                    ? staleDraftReviewResult(
                        snapshot.binding.subject,
                        snapshot.sourceDigest,
                        outcome.feedback,
                      )
                    : await options.execute(capability);
                completedResult = result;
                const delivery = draftReviewDeliveryResult(
                  result,
                  options.carrier,
                  capability.dispatchId,
                );
                capability.deliver(
                  options.carrier,
                  delivery.content,
                  options.carrier.kind === "user"
                    ? () => {
                        const ctx = live();
                        pi.sendUserMessage(
                          delivery.content,
                          ctx.isIdle() ? undefined : { deliverAs: "followUp" },
                        );
                      }
                    : undefined,
                );
                return delivery;
              },
            });
            return { ...annotated(result, ctx, id), completedResult };
          },
          dispose() {
            disposed = true;
            // Tool results persist after return. Retain abort observation until the expectation
            // is settled or this activation ends, but never keep a transport listener alive.
            if (id === undefined || !coordinator.hasExpectation(id)) token.close();
            else abort.abort();
          },
          registration: {
            diagnostic: registration.diagnostic,
            open(requestId) {
              const checked = check();
              if (!checked.ok) return checked;
              if (id !== undefined) return annotated(reviewRefused("invalid-state"), ctx, id);
              const result = annotated(registration.open(requestId), ctx, {
                requestId,
                reviewId: null,
              });
              if (result.ok) {
                id = { requestId, reviewId: null };
                // The state hook released exclusion before predecessor transport teardown.
                const prior = active;
                active = token;
                prior?.close();
              }
              return result;
            },
            attach(requestId, reviewId) {
              const checked = check();
              if (!checked.ok) return checked;
              if (id?.requestId !== requestId) return reviewRefused("superseded");
              const result = annotated(registration.attach(requestId, reviewId), ctx, {
                requestId,
                reviewId,
              });
              if (result.ok) id = { requestId, reviewId };
              return result;
            },
            invalidateOpening(requestId, reason) {
              const checked = check();
              if (!checked.ok) return checked;
              return id?.requestId === requestId
                ? annotated(registration.invalidateOpening(requestId, reason), ctx, id)
                : reviewRefused("superseded");
            },
            subscriptionFailed(requestId, reviewId) {
              const checked = check();
              if (!checked.ok) return checked;
              return id?.requestId === requestId && id.reviewId === reviewId
                ? annotated(registration.subscriptionFailed(requestId, reviewId), ctx, id)
                : reviewRefused("superseded");
            },
          },
        },
      };
    },
  };
}
