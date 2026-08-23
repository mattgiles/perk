// The conflict-resolver claim (contracts.md §8.51): a machine-local SESSION CLAIM on a retained
// sync-continuation operation, taken by the warm dispatcher right before it injects the resolver
// dispatch. It is honestly NOT a child-lifecycle-bound lock — `pi.sendUserMessage` is
// fire-and-forget and the extension never observes the dispatched child's start or finish — so
// there is deliberately NO explicit release. The claim self-heals instead, via the
// reclaimability predicate: the holder pid is dead, the recorded operation was consumed (a fresh
// conflict minted a new operation id), or the lease is missing/corrupt and the lock dir has aged
// past `RECLAIM_GRACE_MS`. The accepted residual: a live session's claim on a still-pending SAME
// operation blocks other sessions' dispatch until that session exits or the operation is
// consumed — the busy reason names the holder pid, the lock path, and the remediation.
//
// Reclaim mechanics mirror `hunkFeedback/store.ts::acquireLease` (the interleaving-safe recipe):
// judge reclaimability → quarantine-RENAME the observed lock dir to a unique name (rename is
// atomic, so two reclaimers can never both delete a successor) → post-rename re-check (a moved
// claim that proves fresh is renamed back — a fresh foreign claim is NEVER stolen) → ONE
// fresh-acquire retry → best-effort quarantine removal; a lost retry is an honest busy. Deletion
// only ever targets our own quarantine dir or our own same-call acquisition.

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
  | { acquired: true }
  | { acquired: false; kind: "busy" | "io_error"; reason: string };

/** Deterministic-interleave seams for the reclaim-race tests — never set in production. */
export interface AcquireRaceHooks {
  /** Runs after the reclaimability judgment, before the quarantine rename. */
  beforeQuarantine?(): void;
  /** Runs after the quarantine rename attempt, before the fresh-acquire retry. */
  afterQuarantine?(): void;
}

interface ResolverLease {
  schema: 1;
  pid: number;
  operation_id: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readLease(lockDir: string): ResolverLease | null {
  try {
    const parsed: unknown = JSON.parse(readFileSync(join(lockDir, "lease.json"), "utf8"));
    if (
      isRecord(parsed) &&
      parsed.schema === 1 &&
      typeof parsed.pid === "number" &&
      Number.isInteger(parsed.pid) &&
      typeof parsed.operation_id === "string"
    ) {
      return parsed as unknown as ResolverLease;
    }
    return null;
  } catch {
    return null;
  }
}

function leaseBytes(pid: number, operationId: string): string {
  const lease: ResolverLease = { schema: 1, pid, operation_id: operationId };
  return `${JSON.stringify(lease)}\n`;
}

/** Liveness probe: ESRCH = dead; EPERM (a foreign-uid process) and success both count alive. */
function defaultIsAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== "ESRCH";
  }
}

/**
 * Atomic non-recursive `mkdir` (EEXIST = contention) + the first lease write. Returns true on
 * acquisition, false on contention; throws on any other fs failure — after best-effort removing
 * the dir THIS call created (we own it; any surviving residue self-heals via the aged-corrupt
 * reclaim rule).
 */
function tryFreshAcquire(lockDir: string, pid: number, operationId: string): boolean {
  try {
    mkdirSync(lockDir);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") return false;
    throw error;
  }
  try {
    atomicWriteFileSync(join(lockDir, "lease.json"), leaseBytes(pid, operationId));
  } catch (error) {
    try {
      rmSync(lockDir, { recursive: true, force: true });
    } catch {
      // best-effort — the corrupt-lease reclaim rule collects it once it ages
    }
    throw error;
  }
  return true;
}

function busyHolder(pid: number, lockDir: string): string {
  return (
    `another live session (pid ${pid}) holds the resolver claim at ${lockDir} — ` +
    "dispatch from that session, or remove the lock dir if it is provably stale"
  );
}

/**
 * Acquire the resolver claim for `operationId` on the continuation at `manifestPath`. Never
 * throws: every filesystem failure is caught and returned as `kind: "io_error"`. Same-pid
 * contention is an idempotent REACQUIRE that rewrites `lease.json` with the CURRENT operation id
 * (a continue-time NEW conflict reuses the same operation id — the original dispatching session
 * re-claims; it never routes through reclaim). `pid`/`isAlive`/`now`/`hooks` are injectable for
 * deterministic tests.
 */
export function acquireResolverLease(
  manifestPath: string,
  operationId: string,
  opts?: {
    pid?: number;
    isAlive?: (pid: number) => boolean;
    now?: () => number;
    hooks?: AcquireRaceHooks;
  },
): LeaseAcquisition {
  const pid = opts?.pid ?? process.pid;
  const isAlive = opts?.isAlive ?? defaultIsAlive;
  const now = opts?.now ?? Date.now;
  const hooks = opts?.hooks ?? {};
  const lockDir = resolverLockDir(manifestPath);
  try {
    if (tryFreshAcquire(lockDir, pid, operationId)) return { acquired: true };

    const lease = readLease(lockDir);
    if (lease !== null && lease.pid === pid) {
      // Same pid: reacquire, not reclaim — rewrite with the current operation id.
      atomicWriteFileSync(join(lockDir, "lease.json"), leaseBytes(pid, operationId));
      return { acquired: true };
    }

    // Reclaimability: dead holder / consumed operation / aged corrupt-or-missing lease.
    if (lease !== null) {
      if (isAlive(lease.pid) && lease.operation_id === operationId) {
        return { acquired: false, kind: "busy", reason: busyHolder(lease.pid, lockDir) };
      }
    } else {
      // Corrupt/missing lease.json: age on the lock dir's mtime. A vanished dir (a racing
      // reclaim finished between EEXIST and stat) counts old — the retry below settles it.
      let basisMs = Number.NEGATIVE_INFINITY;
      try {
        basisMs = statSync(lockDir).mtimeMs;
      } catch {
        // keep the -Infinity basis
      }
      if (now() - basisMs < RECLAIM_GRACE_MS) {
        return {
          acquired: false,
          kind: "busy",
          reason:
            `an unidentified holder claims the resolver lock at ${lockDir} (lease unreadable, ` +
            "created recently) — retry shortly, or remove the lock dir if it is provably stale",
        };
      }
    }

    // Reclaim: quarantine-rename → post-rename re-check → ONE fresh-acquire retry.
    hooks.beforeQuarantine?.();
    const quarantine = `${lockDir}.stale-${pid.toString(36)}-${randomBytes(4).toString("hex")}`;
    let renamed = false;
    try {
      renameSync(lockDir, quarantine);
      renamed = true;
    } catch {
      renamed = false; // a competing reclaimer moved it first — still take the one retry
    }
    if (renamed) {
      // Between our judgment and the rename a competitor may have COMPLETED a full
      // reclaim+reacquire — the dir we moved would then hold a FRESH foreign live claim on
      // THIS operation, not the stale state we judged. Restore it and report busy: a fresh
      // foreign claim is never stolen.
      const moved = readLease(quarantine);
      const movedFresh =
        moved !== null &&
        moved.pid !== pid &&
        isAlive(moved.pid) &&
        moved.operation_id === operationId;
      if (movedFresh) {
        try {
          renameSync(quarantine, lockDir);
        } catch {
          // the name was retaken meanwhile — leave the quarantine; it self-heals as residue
        }
        return { acquired: false, kind: "busy", reason: busyHolder(moved.pid, lockDir) };
      }
    }
    hooks.afterQuarantine?.();
    const retried = tryFreshAcquire(lockDir, pid, operationId);
    if (renamed) {
      try {
        rmSync(quarantine, { recursive: true, force: true });
      } catch {
        // best-effort — a leftover quarantine dir is inert
      }
    }
    if (retried) return { acquired: true };
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
