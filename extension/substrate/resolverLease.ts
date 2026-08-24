// The conflict-resolver claim (contracts.md §8.51): a machine-local SESSION CLAIM on a retained
// sync-continuation operation, taken by the warm dispatcher right before it injects the resolver
// dispatch. It is honestly NOT a child-lifecycle-bound lock — `pi.sendUserMessage` is
// fire-and-forget and the extension never observes the dispatched child's start or finish — so
// there is deliberately NO explicit release on dispatch. The claim self-heals instead, via the
// reclaimability predicate: the holder pid is dead, the recorded operation was consumed (a fresh
// conflict minted a new operation id), or the lease is missing/corrupt and the lock dir has aged
// past `RECLAIM_GRACE_MS`. The accepted residual: a live session's claim on a still-pending SAME
// operation blocks other sessions' dispatch until that session exits or the operation is
// consumed — the busy reason names the holder pid, the lock path, and the remediation.
//
// Reclaim mechanics mirror `hunkFeedback/store.ts::acquireLease` (the interleaving-safe recipe):
// judge reclaimability → quarantine-RENAME the observed lock dir to a unique name (rename is
// atomic, so two reclaimers can never both delete a successor) → post-rename re-judgment on the
// MOVED state (a claim that changed since the judgment, or whose lease is missing/corrupt but
// still inside the grace window, is renamed back — a raced-in claim is NEVER stolen, whatever
// operation it names) → ONE fresh-acquire retry → best-effort quarantine removal; a lost retry
// is an honest busy. Deletion only ever targets our own quarantine dir or our own same-call
// acquisition, and the explicit withheld-dispatch release is token-fenced through its own
// quarantine-verify (`releaseResolverClaim`).
//
// Error posture: a MISSING or MALFORMED lease is DATA (it routes to the reclaim rules), and the
// expected race disappearances (ENOENT on read/stat/rename, EEXIST on mkdir) are contention —
// every OTHER filesystem failure propagates to the typed `io_error` arm, never a fabricated
// busy/reclaim judgment.

import { randomBytes } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, rmSync, statSync } from "node:fs";
import { join } from "node:path";
import { atomicWriteFileSync } from "./cache.ts";

/**
 * A corrupt/missing `lease.json` is reclaimable only once the lock dir is older than this —
 * closes the winner's mkdir↔first-write window (implementation constant, not config).
 */
export const RECLAIM_GRACE_MS = 60_000;

/** The claim lock dir sits beside the continuation manifest it guards. */
export function resolverLockDir(manifestPath: string): string {
  return `${manifestPath}.resolver-lock`;
}

export type LeaseAcquisition =
  | { acquired: true; token: string }
  | { acquired: false; kind: "busy" | "io_error"; reason: string };

/** Deterministic-interleave seams for the reclaim-race tests — never set in production. */
export interface AcquireRaceHooks {
  /** Runs after the reclaimability judgment, before the quarantine rename. */
  beforeQuarantine?(): void;
  /** Runs after the quarantine rename attempt, before the fresh-acquire retry. */
  afterQuarantine?(): void;
}

/** The raw fs operations the claim touches — injectable ONLY for deterministic fault tests. */
export interface LeaseFsOps {
  /** Non-recursive mkdir: EEXIST is the contention signal. */
  mkdir(path: string): void;
  /** utf8 read. */
  readFile(path: string): string;
  /** Atomic lease write (temp + rename — the atomicWriteFileSync discipline). */
  writeLease(path: string, content: string): void;
  rename(from: string, to: string): void;
  /** Recursive, force. */
  rm(path: string): void;
  statMtimeMs(path: string): number;
}

const REAL_FS: LeaseFsOps = {
  mkdir: (path) => mkdirSync(path),
  readFile: (path) => readFileSync(path, "utf8"),
  writeLease: (path, content) => atomicWriteFileSync(path, content),
  rename: (from, to) => renameSync(from, to),
  rm: (path) => rmSync(path, { recursive: true, force: true }),
  statMtimeMs: (path) => statSync(path).mtimeMs,
};

interface ResolverLease {
  schema: 1;
  pid: number;
  operation_id: string;
  /** The per-acquisition ownership fence: rotated on every (re)acquire; release verifies it. */
  token: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorCode(error: unknown): string | undefined {
  return (error as NodeJS.ErrnoException).code;
}

/**
 * Read the lease as DATA: a missing file or malformed/mis-shaped content is `null` (the
 * corrupt/missing reclaim rules own it). Any OTHER read failure (EACCES, EIO, EISDIR, …) is a
 * genuine I/O failure and THROWS so the caller's typed `io_error` arm reports it honestly.
 */
function readLease(fs: LeaseFsOps, lockDir: string): ResolverLease | null {
  let raw: string;
  try {
    raw = fs.readFile(join(lockDir, "lease.json"));
  } catch (error) {
    if (errorCode(error) === "ENOENT") return null;
    throw error;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (
    isRecord(parsed) &&
    parsed.schema === 1 &&
    typeof parsed.pid === "number" &&
    Number.isInteger(parsed.pid) &&
    typeof parsed.operation_id === "string" &&
    typeof parsed.token === "string"
  ) {
    return parsed as unknown as ResolverLease;
  }
  return null;
}

/** The lock dir's mtime, or -Infinity when it vanished (ENOENT — a racing reclaim finished);
 * any other stat failure throws to the typed `io_error` arm. */
function lockDirBasisMs(fs: LeaseFsOps, path: string): number {
  try {
    return fs.statMtimeMs(path);
  } catch (error) {
    if (errorCode(error) === "ENOENT") return Number.NEGATIVE_INFINITY;
    throw error;
  }
}

function leaseBytes(lease: ResolverLease): string {
  return `${JSON.stringify(lease)}\n`;
}

function mintToken(): string {
  return randomBytes(8).toString("hex");
}

/** Liveness probe: ESRCH = dead; EPERM (a foreign-uid process) and success both count alive. */
function defaultIsAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return errorCode(error) !== "ESRCH";
  }
}

/**
 * Atomic non-recursive `mkdir` (EEXIST = contention) + the first lease write. Returns the fresh
 * token on acquisition, null on contention; throws on any other fs failure — after best-effort
 * removing the dir THIS call created (we own it; any surviving residue self-heals via the
 * aged-corrupt reclaim rule).
 */
function tryFreshAcquire(
  fs: LeaseFsOps,
  lockDir: string,
  pid: number,
  operationId: string,
): string | null {
  try {
    fs.mkdir(lockDir);
  } catch (error) {
    if (errorCode(error) === "EEXIST") return null;
    throw error;
  }
  const token = mintToken();
  try {
    fs.writeLease(
      join(lockDir, "lease.json"),
      leaseBytes({ schema: 1, pid, operation_id: operationId, token }),
    );
  } catch (error) {
    try {
      fs.rm(lockDir);
    } catch {
      // best-effort — the corrupt-lease reclaim rule collects it once it ages
    }
    throw error;
  }
  return token;
}

function busyHolder(pid: number, lockDir: string): string {
  return (
    `another live session (pid ${pid}) holds the resolver claim at ${lockDir} — ` +
    "dispatch from that session, or remove the lock dir if it is provably stale"
  );
}

function busyUnidentified(lockDir: string): string {
  return (
    `an unidentified holder claims the resolver lock at ${lockDir} (lease unreadable, ` +
    "created recently) — retry shortly, or remove the lock dir if it is provably stale"
  );
}

function sameLease(a: ResolverLease, b: ResolverLease | null): boolean {
  return b !== null && a.pid === b.pid && a.operation_id === b.operation_id && a.token === b.token;
}

/**
 * Acquire the resolver claim for `operationId` on the continuation at `manifestPath`. Never
 * throws: every genuine filesystem failure is caught and returned as `kind: "io_error"` (the
 * expected race disappearances are classified inline — see the module doc). Same-pid contention
 * is an idempotent REACQUIRE that rewrites `lease.json` with the CURRENT operation id and a
 * fresh token (a continue-time NEW conflict reuses the same operation id — the original
 * dispatching session re-claims; it never routes through reclaim). On success the returned
 * `token` is the ownership fence a withheld dispatch passes to `releaseResolverClaim`.
 * `pid`/`isAlive`/`now`/`hooks`/`fs` are injectable for deterministic tests.
 */
export function acquireResolverLease(
  manifestPath: string,
  operationId: string,
  opts?: {
    pid?: number;
    isAlive?: (pid: number) => boolean;
    now?: () => number;
    hooks?: AcquireRaceHooks;
    fs?: Partial<LeaseFsOps>;
  },
): LeaseAcquisition {
  const pid = opts?.pid ?? process.pid;
  const isAlive = opts?.isAlive ?? defaultIsAlive;
  const now = opts?.now ?? Date.now;
  const hooks = opts?.hooks ?? {};
  const fs: LeaseFsOps = { ...REAL_FS, ...(opts?.fs ?? {}) };
  const lockDir = resolverLockDir(manifestPath);
  try {
    const fresh = tryFreshAcquire(fs, lockDir, pid, operationId);
    if (fresh !== null) return { acquired: true, token: fresh };

    const observed = readLease(fs, lockDir);
    if (observed !== null && observed.pid === pid) {
      // Same pid: reacquire, not reclaim — rewrite with the current operation id + fresh token.
      const token = mintToken();
      fs.writeLease(
        join(lockDir, "lease.json"),
        leaseBytes({ schema: 1, pid, operation_id: operationId, token }),
      );
      return { acquired: true, token };
    }

    // Reclaimability: dead holder / consumed operation / aged corrupt-or-missing lease.
    if (observed !== null) {
      if (isAlive(observed.pid) && observed.operation_id === operationId) {
        return { acquired: false, kind: "busy", reason: busyHolder(observed.pid, lockDir) };
      }
    } else if (now() - lockDirBasisMs(fs, lockDir) < RECLAIM_GRACE_MS) {
      // Corrupt/missing lease.json inside the grace window (a winner may sit between its
      // mkdir and first write) — busy; a vanished dir counts old and the retry settles it.
      return { acquired: false, kind: "busy", reason: busyUnidentified(lockDir) };
    }

    // Reclaim: quarantine-rename → post-rename re-judgment → ONE fresh-acquire retry.
    hooks.beforeQuarantine?.();
    const quarantine = `${lockDir}.stale-${pid.toString(36)}-${randomBytes(4).toString("hex")}`;
    let renamed = false;
    try {
      fs.rename(lockDir, quarantine);
      renamed = true;
    } catch (error) {
      // ENOENT = a competing reclaimer moved it first — still take the one retry. Any other
      // rename failure is genuine I/O and must not masquerade as contention.
      if (errorCode(error) !== "ENOENT") throw error;
      renamed = false;
    }
    if (renamed) {
      // Post-rename re-judgment on the MOVED state: between our judgment and the rename a
      // competitor may have installed a successor claim (any operation id — never assume the
      // one we are acquiring), or a winner may sit inside its mkdir↔first-write window (a
      // young dir with no lease yet). Neither is ours to take: restore and report busy. Only
      // the unchanged judged-stale state, a dead raced-in holder, or an AGED lease-less dir
      // proceeds to the retry.
      const moved = readLease(fs, quarantine);
      let busyReason: string | null = null;
      if (moved !== null) {
        if (!sameLease(moved, observed) && isAlive(moved.pid)) {
          busyReason = busyHolder(moved.pid, lockDir);
        }
      } else if (now() - lockDirBasisMs(fs, quarantine) < RECLAIM_GRACE_MS) {
        // rename preserves mtime — the moved dir's age is the original dir's age.
        busyReason = busyUnidentified(lockDir);
      }
      if (busyReason !== null) {
        try {
          fs.rename(quarantine, lockDir);
        } catch {
          // the name was retaken meanwhile — leave the quarantine; it self-heals as residue
        }
        return { acquired: false, kind: "busy", reason: busyReason };
      }
    }
    hooks.afterQuarantine?.();
    const retried = tryFreshAcquire(fs, lockDir, pid, operationId);
    if (renamed) {
      try {
        fs.rm(quarantine);
      } catch {
        // best-effort — a leftover quarantine dir is inert
      }
    }
    if (retried !== null) return { acquired: true, token: retried };
    return {
      acquired: false,
      kind: "busy",
      reason:
        `another session claimed the resolver lock at ${lockDir} first — dispatch from that ` +
        "session, or retry once its claim clears",
    };
  } catch (error) {
    return {
      acquired: false,
      kind: "io_error",
      reason: `resolver-claim filesystem failure at ${lockDir}: ${String(error)}`,
    };
  }
}

/**
 * Release THIS call's claim — the withheld-dispatch cleanup (a verified-increment failure must
 * not leave a phantom holder). Token-fenced through a quarantine-verify: the claim is renamed
 * to a private name first (atomic — a successor installed at the canonical path is never
 * touched), verified against `token`, and deleted only when it proved ours; anything else is
 * renamed back. Best-effort and never throws: leftover residue self-heals via the reclaim
 * rules.
 */
export function releaseResolverClaim(
  manifestPath: string,
  token: string,
  opts?: { fs?: Partial<LeaseFsOps> },
): void {
  const fs: LeaseFsOps = { ...REAL_FS, ...(opts?.fs ?? {}) };
  const lockDir = resolverLockDir(manifestPath);
  const quarantine = `${lockDir}.release-${process.pid.toString(36)}-${randomBytes(4).toString("hex")}`;
  try {
    try {
      fs.rename(lockDir, quarantine);
    } catch (error) {
      if (errorCode(error) === "ENOENT") return; // nothing to release
      throw error;
    }
    const moved = readLease(fs, quarantine);
    if (moved !== null && moved.token === token) {
      fs.rm(quarantine);
      return;
    }
    // Not ours (a successor raced in) — put it back untouched.
    try {
      fs.rename(quarantine, lockDir);
    } catch {
      // the name was retaken meanwhile — leave the quarantine; it self-heals as residue
    }
  } catch {
    // best-effort — a leftover claim/quarantine goes stale and is reclaimed by the next acquire
  }
}
