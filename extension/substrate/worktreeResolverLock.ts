// Participating submit/address writers exclude each other by canonical worktree Git identity.
// There is NO reclamation policy. Death, age, reload and cancellation cannot prove quiescence.
import { randomUUID } from "node:crypto";
import {
  closeSync,
  constants,
  fstatSync,
  fsyncSync,
  lstatSync,
  openSync,
  readSync,
  type Stats,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { worktreeGitDir } from "./git.ts";

const OWNER_LIMIT = 16 * 1024;
export const WORKTREE_RESOLVER_LOCK = "perk-submit-conflict.lock";

interface LockRecord {
  schema: 1;
  token: string;
  pid: number;
  parentSessionId: string;
  ownerRunId: string;
  requestId: string;
  worktreeIdentity: string;
  createdAt: string;
}
export type LockOwner = Omit<LockRecord, "token" | "schema">;
export type LockFinish = {
  kind: "released" | "retained" | "ownership-error" | "io-error";
  path: string;
};
export interface WorktreeResolverClaim {
  readonly path: string;
  check(): "owned" | "ownership-error" | "io-error";
  /** First choice wins, locally idempotent. Retain closes resources but never removes metadata. */
  finish(disposition: "release" | "retain"): LockFinish;
}
export type WorktreeResolverAcquisition =
  | { kind: "acquired"; claim: WorktreeResolverClaim }
  | { kind: "unavailable" }
  | { kind: "busy"; path: string; owner?: LockOwner }
  | { kind: "io-error"; path: string; residue: boolean };

/** Only deterministic filesystem fault tests substitute these operations. */
export interface WorktreeLockFs {
  open: typeof openSync;
  close: typeof closeSync;
  fstat: (fd: number) => Stats;
  lstat: (path: string) => Stats;
  read: (fd: number, buffer: Buffer, offset: number, length: number, position: number) => number;
  write: (fd: number, data: string) => void;
  sync: (fd: number) => void;
  unlink: (path: string) => void;
}
const realFs: WorktreeLockFs = {
  open: openSync,
  close: closeSync,
  fstat: fstatSync,
  lstat: lstatSync,
  read: readSync,
  write: (fd, data) => writeFileSync(fd, data, "utf8"),
  sync: fsyncSync,
  unlink: unlinkSync,
};
function code(error: unknown): unknown {
  return typeof error === "object" && error !== null && "code" in error ? error.code : undefined;
}
function sameFile(a: Stats, b: Stats): boolean {
  return a.isFile() && b.isFile() && a.dev === b.dev && a.ino === b.ino;
}
function readRecord(fs: WorktreeLockFs, fd: number): LockRecord | null {
  const size = fs.fstat(fd).size;
  if (size <= 0 || size > OWNER_LIMIT) return null;
  const bytes = Buffer.alloc(size);
  let read = 0;
  while (read < size) {
    const n = fs.read(fd, bytes, read, size - read, read);
    if (n === 0) return null;
    read += n;
  }
  let raw: unknown;
  try {
    raw = JSON.parse(bytes.toString("utf8"));
  } catch {
    return null;
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  if (
    r.schema !== 1 ||
    typeof r.token !== "string" ||
    !r.token ||
    typeof r.pid !== "number" ||
    !Number.isInteger(r.pid) ||
    r.pid <= 0
  )
    return null;
  for (const field of [
    "parentSessionId",
    "ownerRunId",
    "requestId",
    "worktreeIdentity",
    "createdAt",
  ] as const) {
    if (typeof r[field] !== "string" || !r[field]) return null;
  }
  return r as unknown as LockRecord;
}
function ownerOf(r: LockRecord): LockOwner {
  return {
    pid: r.pid,
    parentSessionId: r.parentSessionId,
    ownerRunId: r.ownerRunId,
    requestId: r.requestId,
    worktreeIdentity: r.worktreeIdentity,
    createdAt: r.createdAt,
  };
}

function incumbent(fs: WorktreeLockFs, path: string): WorktreeResolverAcquisition {
  let fd: number | undefined;
  try {
    const stat = fs.lstat(path);
    if (!stat.isFile() || stat.size > OWNER_LIMIT) return { kind: "busy", path };
    fd = fs.open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    if (!sameFile(stat, fs.fstat(fd))) return { kind: "busy", path };
    const record = readRecord(fs, fd);
    return { kind: "busy", path, ...(record ? { owner: ownerOf(record) } : {}) };
  } catch (error) {
    // Even a disappearing incumbent doesn't invite a retry. A racing external replacement is
    // outside the protocol; ELOOP never follows the new symlink for diagnostic reads.
    if (code(error) === "ENOENT" || code(error) === "ELOOP") return { kind: "busy", path };
    return { kind: "io-error", path, residue: true };
  } finally {
    if (fd !== undefined) fs.close(fd);
  }
}

export function acquireWorktreeResolverLock(
  cwd: string,
  parent: { sessionId: string; runId: string; requestId: string },
  opts: { fs?: Partial<WorktreeLockFs>; gitDir?: (cwd: string) => string | null } = {},
): WorktreeResolverAcquisition {
  const identity = (opts.gitDir ?? worktreeGitDir)(cwd);
  if (identity === null) return { kind: "unavailable" };
  const path = join(identity, WORKTREE_RESOLVER_LOCK);
  const fs = { ...realFs, ...opts.fs };
  let fd: number;
  try {
    fd = fs.open(path, "wx", 0o600);
  } catch (error) {
    if (code(error) === "EEXIST") {
      try {
        return incumbent(fs, path);
      } catch {
        return { kind: "io-error", path, residue: true };
      }
    }
    return { kind: "io-error", path, residue: false };
  }
  let stat: Stats | undefined;
  const record: LockRecord = {
    schema: 1,
    token: randomUUID(),
    pid: process.pid,
    parentSessionId: parent.sessionId,
    ownerRunId: parent.runId,
    requestId: parent.requestId,
    worktreeIdentity: identity,
    createdAt: new Date().toISOString(),
  };
  try {
    stat = fs.fstat(fd);
    if (!stat.isFile()) throw new Error("not a regular file");
    fs.write(fd, `${JSON.stringify(record)}\n`);
    fs.sync(fd);
  } catch {
    let residue = true;
    try {
      if (stat && sameFile(stat, fs.lstat(path))) {
        fs.unlink(path);
        residue = false;
      }
    } catch {
      /* Report residue; never remove an unidentified or successor file. */
    }
    try {
      fs.close(fd);
    } catch {
      residue = true;
    }
    return { kind: "io-error", path, residue };
  }
  const acquiredStat = stat;
  let finished: LockFinish | undefined;
  function check(): "owned" | "ownership-error" | "io-error" {
    if (finished) return "ownership-error";
    try {
      if (!sameFile(acquiredStat, fs.lstat(path)) || !sameFile(acquiredStat, fs.fstat(fd)))
        return "ownership-error";
      const reader = fs.open(
        path,
        constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK,
      );
      try {
        if (!sameFile(acquiredStat, fs.fstat(reader))) return "ownership-error";
        return readRecord(fs, reader)?.token === record.token ? "owned" : "ownership-error";
      } finally {
        fs.close(reader);
      }
    } catch (error) {
      return code(error) === "ENOENT" ? "ownership-error" : "io-error";
    }
  }
  return {
    kind: "acquired",
    claim: {
      path,
      check,
      finish(disposition) {
        if (finished) return finished;
        let kind: LockFinish["kind"] = "retained";
        try {
          if (disposition === "release") {
            const ownership = check();
            if (ownership === "owned") {
              fs.unlink(path);
              kind = "released";
            } else kind = ownership;
          }
        } catch {
          kind = "io-error";
        } finally {
          try {
            fs.close(fd);
          } catch {
            kind = "io-error";
          }
        }
        finished = { kind, path };
        return finished;
      },
    },
  };
}
