// Independent run-scoped exclusion; owner metadata is diagnostic, never proof of review effects.
import { join } from "node:path";
import { isSafeRunId } from "./cache.ts";
import {
  acquireExclusiveFileClaim,
  type ExclusiveFileAcquisition,
  type ExclusiveFileFs,
} from "./exclusiveFileClaim.ts";
import { canonicalSessionDataDir } from "./sessionData.ts";

export const DRAFT_REVIEW_LOCK = "draft-review.lock";
export interface DraftReviewLockOwner {
  pid: number;
  parentSessionId: string;
  ownerRunId: string;
  requestId: string;
  reviewNamespace: string;
  createdAt: string;
}
export type DraftReviewAcquisition =
  | ExclusiveFileAcquisition<DraftReviewLockOwner>
  | { kind: "unavailable"; reason: "no-identity" | "unsafe-namespace" };

function decode(raw: unknown): { token: string; owner: DraftReviewLockOwner } | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  if (
    Object.keys(r).length !== 8 ||
    r.schema !== 1 ||
    typeof r.token !== "string" ||
    !r.token ||
    typeof r.pid !== "number" ||
    !Number.isInteger(r.pid) ||
    r.pid <= 0 ||
    typeof r.parentSessionId !== "string" ||
    !r.parentSessionId.trim() ||
    typeof r.ownerRunId !== "string" ||
    !isSafeRunId(r.ownerRunId) ||
    typeof r.requestId !== "string" ||
    !r.requestId.trim() ||
    typeof r.reviewNamespace !== "string" ||
    !r.reviewNamespace ||
    typeof r.createdAt !== "string" ||
    !r.createdAt
  )
    return null;
  return {
    token: r.token,
    owner: {
      pid: r.pid,
      parentSessionId: r.parentSessionId,
      ownerRunId: r.ownerRunId,
      requestId: r.requestId,
      reviewNamespace: r.reviewNamespace,
      createdAt: r.createdAt,
    },
  };
}

/** The caller supplies its strict-read current identity, never a launch/fallback run stamp. */
export function acquireDraftReviewLock(
  cwd: string,
  parent: { sessionId: string; runId: string | null; requestId: string },
  opts: { fs?: Partial<ExclusiveFileFs> } = {},
): DraftReviewAcquisition {
  if (
    parent.runId === null ||
    !isSafeRunId(parent.runId) ||
    !parent.sessionId.trim() ||
    !parent.requestId.trim()
  ) {
    return { kind: "unavailable", reason: "no-identity" };
  }
  let namespace: string | null;
  try {
    namespace = canonicalSessionDataDir(cwd, parent.runId, { create: true });
  } catch {
    return { kind: "unavailable", reason: "unsafe-namespace" };
  }
  if (namespace === null) return { kind: "unavailable", reason: "unsafe-namespace" };
  return acquireExclusiveFileClaim(
    join(namespace, DRAFT_REVIEW_LOCK),
    {
      encode: (token) => ({
        schema: 1,
        token,
        pid: process.pid,
        parentSessionId: parent.sessionId,
        ownerRunId: parent.runId,
        requestId: parent.requestId,
        reviewNamespace: namespace,
        createdAt: new Date().toISOString(),
      }),
      decode,
    },
    opts.fs,
  );
}
