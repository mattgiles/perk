import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  createDraftReviewActivation,
  type DraftReviewAccess,
  type DraftReviewRuntime,
} from "../pi/v1/draftReviewActivation.ts";
import type { DraftReviewRegistration } from "../session/draftReviewState.ts";
import { digestSessionData } from "../session/workflowSession.ts";

/** Explicit test-only transport hooks. State/claim composition tests use the real coordinator. */
export function recordingDraftRegistration() {
  const calls: string[] = [];
  const registration: DraftReviewRegistration = {
    open(id) {
      calls.push(`open:${id}`);
      return { ok: true };
    },
    attach(id, review) {
      calls.push(`attach:${id}:${review}`);
      return { ok: true };
    },
    invalidateOpening(id, reason) {
      calls.push(`invalidate:${id}:${reason}`);
      return { ok: true };
    },
    subscriptionFailed(id, review) {
      calls.push(`subscribe:${id}:${review}`);
      return { ok: true };
    },
    diagnostic(code) {
      calls.push(`diagnostic:${code}`);
    },
  };
  return { registration, calls };
}

/** Policy-only fixtures deliberately isolate source/save policies from production Git/claims. */
export function policyBrowserReviews(
  subject: "plan" | "objective",
  markdown: string,
  raw = markdown,
): DraftReviewAccess {
  return {
    prepare(ctx, _parameter, signal) {
      const prepared = policyDraftReviews.prepare(ctx, markdown, signal);
      if (prepared.ok) {
        prepared.value.snapshot.raw = raw;
        prepared.value.snapshot.binding.subject = subject;
      }
      return prepared;
    },
  };
}
const mutationRuntimes = new WeakMap<ExtensionContext, DraftReviewRuntime>();
function mutationRuntime(ctx: ExtensionContext): DraftReviewRuntime {
  let runtime = mutationRuntimes.get(ctx);
  if (runtime === undefined) {
    // Policy tests fake only Pi's storage carrier; mutation identity/state/claims remain real.
    const pi = {
      on() {},
      appendEntry(type: string, data: unknown) {
        const manager = ctx.sessionManager;
        if (!("appendCustomEntry" in manager) || typeof manager.appendCustomEntry !== "function")
          throw new Error("Policy fixture needs a writable session manager");
        manager.appendCustomEntry(type, data);
      },
    } as unknown as ExtensionAPI;
    runtime = createDraftReviewActivation(pi);
    mutationRuntimes.set(ctx, runtime);
  }
  return runtime;
}
export const policyDraftReviews: DraftReviewRuntime = {
  mutate(ctx, reason, work, options) {
    return mutationRuntime(ctx).mutate(ctx, reason, work, options);
  },
  mutateAsync(ctx, reason, work) {
    return mutationRuntime(ctx).mutateAsync(ctx, reason, work);
  },
  prepare(_ctx, markdown = "", signal) {
    const abort = new AbortController();
    return {
      ok: true,
      value: {
        snapshot: {
          source: { kind: "parameter", plan: markdown, artifact_at_open: "absent" },
          raw: markdown,
          markdown,
          sourceDigest: digestSessionData(markdown),
          binding: {
            runId: "RID",
            subject: "plan",
            digest: digestSessionData("target"),
            warmNodeClaim: null,
          },
        },
        registration: recordingDraftRegistration().registration,
        signal: signal ?? abort.signal,
        isCurrent: () => true,
        async complete() {
          throw new Error(
            "Policy-only fixture cannot authorize production completion; use real activation/state/claims",
          );
        },
        dispose() {
          abort.abort();
        },
      },
    };
  },
};
