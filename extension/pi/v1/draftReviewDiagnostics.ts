import { join } from "node:path";
import {
  DRAFT_REVIEW_ARTIFACT,
  type RegistrationResult,
  type ReviewIdentity,
  readDraftReview,
} from "../../session/draftReviewState.ts";
import type { WorkflowSession } from "../../session/workflowSession.ts";
import { DRAFT_REVIEW_LOCK } from "../../substrate/draftReviewLock.ts";
import { canonicalSessionDataDir } from "../../substrate/sessionData.ts";

export const DRAFT_REVIEW_RECONCILIATION = "docs/user-docs/how-to/reconcile-a-draft-review-stop.md";

/** Diagnostic reads grant no authority and perform no repair. Invalid provenance stays unknown. */
export function draftReviewDiagnostic(
  result: Extract<RegistrationResult, { ok: false }>,
  cwd: string,
  session: WorkflowSession,
  known?: ReviewIdentity,
  expectedRun?: string,
): typeof result {
  let run = expectedRun ?? "unknown";
  let namespace: string | null = null;
  let id = known;
  let state = "unknown";
  let receipt = "unknown (not proof of no save)";
  let digest = "unknown";
  try {
    const identity = session.currentRunIdentity();
    if (identity.ok || expectedRun !== undefined) {
      run = expectedRun ?? (identity.ok ? identity.runId : "unknown");
      namespace = canonicalSessionDataDir(cwd, run, { create: false });
      // Never read a replacement run's record as evidence about the retained activation.
      const loaded = identity.ok && identity.runId === run ? readDraftReview(session) : null;
      if (loaded?.ok && loaded.record !== null) {
        const record = loaded.record;
        id = { requestId: record.request_id, reviewId: record.correlation.review_id };
        state = record.consumption.state;
        if ("reason" in record.consumption) state += `/${record.consumption.reason}`;
        digest = record.correlation.source_digest;
        if ("attempt" in record.consumption) {
          const save = record.consumption.attempt.save;
          if (save.state === "confirmed")
            receipt = `${JSON.stringify(save.id)} (${JSON.stringify(save.url)})`;
          else receipt = `${save.state} (not proof of no earlier save)`;
        }
      }
    }
  } catch {
    // Keep partial diagnostic facts; unreadability is not absence and never authorizes retry.
  }
  const artifact =
    namespace === null
      ? "unavailable (unsafe or unreadable namespace)"
      : join(namespace, DRAFT_REVIEW_ARTIFACT);
  const lock =
    namespace === null
      ? "unavailable (unsafe or unreadable namespace)"
      : join(namespace, DRAFT_REVIEW_LOCK);
  const operation =
    known === undefined
      ? ""
      : `; operation request: ${JSON.stringify(known.requestId)}; operation review: ${JSON.stringify(known.reviewId ?? "unknown")}`;
  return {
    ...result,
    detail: `${result.detail}. Run: ${JSON.stringify(run)}; request: ${JSON.stringify(id?.requestId ?? "unknown")}; review: ${JSON.stringify(id?.reviewId ?? "unknown")}${operation}; last verified state: ${state}; reviewed digest: ${digest}; artifact: ${JSON.stringify(artifact)}; lock: ${JSON.stringify(lock)}; known save receipt: ${receipt}. Lock owner metadata is not proof of effects`,
  };
}
