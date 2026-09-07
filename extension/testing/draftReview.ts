import type { DraftReviewAccess } from "../pi/v1/draftReviewActivation.ts";
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
export const policyDraftReviews: DraftReviewAccess = {
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
        dispose() {
          abort.abort();
        },
      },
    };
  },
};
