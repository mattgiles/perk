// Participating submit/address writers exclude each other by canonical worktree Git identity.
// There is NO reclamation policy. Death, age, reload and cancellation cannot prove quiescence.
import { join } from "node:path";
import {
  acquireExclusiveFileClaim,
  type ClaimFinish,
  type ExclusiveFileAcquisition,
  type ExclusiveFileClaim,
  type ExclusiveFileFs,
} from "./exclusiveFileClaim.ts";
import { worktreeGitDir } from "./git.ts";

export const WORKTREE_RESOLVER_LOCK = "perk-submit-conflict.lock";

export interface LockOwner {
  pid: number;
  parentSessionId: string;
  ownerRunId: string;
  requestId: string;
  worktreeIdentity: string;
  createdAt: string;
}
export type LockFinish = ClaimFinish;
export type WorktreeResolverClaim = ExclusiveFileClaim;
export type WorktreeResolverAcquisition =
  | ExclusiveFileAcquisition<LockOwner>
  | { kind: "unavailable" };
export type WorktreeLockFs = ExclusiveFileFs;

function decode(raw: unknown): { token: string; owner: LockOwner } | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  if (
    r.schema !== 1 ||
    typeof r.token !== "string" ||
    !r.token ||
    typeof r.pid !== "number" ||
    !Number.isInteger(r.pid) ||
    r.pid <= 0 ||
    typeof r.parentSessionId !== "string" ||
    !r.parentSessionId ||
    typeof r.ownerRunId !== "string" ||
    !r.ownerRunId ||
    typeof r.requestId !== "string" ||
    !r.requestId ||
    typeof r.worktreeIdentity !== "string" ||
    !r.worktreeIdentity ||
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
      worktreeIdentity: r.worktreeIdentity,
      createdAt: r.createdAt,
    },
  };
}

export function acquireWorktreeResolverLock(
  cwd: string,
  parent: { sessionId: string; runId: string; requestId: string },
  opts: { fs?: Partial<WorktreeLockFs>; gitDir?: (cwd: string) => string | null } = {},
): WorktreeResolverAcquisition {
  const identity = (opts.gitDir ?? worktreeGitDir)(cwd);
  if (identity === null) return { kind: "unavailable" };
  return acquireExclusiveFileClaim(
    join(identity, WORKTREE_RESOLVER_LOCK),
    {
      encode: (token) => ({
        schema: 1,
        token,
        pid: process.pid,
        parentSessionId: parent.sessionId,
        ownerRunId: parent.runId,
        requestId: parent.requestId,
        worktreeIdentity: identity,
        createdAt: new Date().toISOString(),
      }),
      decode,
    },
    opts.fs,
  );
}
