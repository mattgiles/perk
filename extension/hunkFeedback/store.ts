// The receiver-plane file contract behind the hunk watch feedback bridge (contracts.md §8.58):
// lenient NDJSON reads over the outbox/delivered streams, the append-only ack writer, and the
// single-consumer lease operations. Pure file mechanics — no timers, no session effects; the
// delivery machine lives in inbox.ts. Paths reach here from the cache-seam helpers
// (substrate/cache.ts) — this module never constructs `.perk/workflow` segments itself.
//
// Read posture (§8.58): reads are TOTAL and lenient — a missing file is no feedback; a trailing
// partial line is HELD (a concurrent append in flight); a malformed complete line warns and is
// skipped; an unknown `schema` is held with a loud version warning (never acked); duplicate
// `feedback_id`s collapse to the first valid record and conflicting later bytes for the same id
// are reported as corruption. Full-file reads with ID indexing — no cursors/compaction in v1.

import { randomBytes } from "node:crypto";
import {
  appendFileSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  statSync,
} from "node:fs";
import { basename, dirname, join } from "node:path";
import { atomicWriteFileSync } from "../substrate/cache.ts";

/** Heartbeat renewal cadence — an implementation constant (§8.58), not config. */
export const HEARTBEAT_MS = 5_000;
/** A lease whose heartbeat is older than this is reclaimable — implementation constant. */
export const STALE_LEASE_MS = 60_000;

// --- record shapes (feedback record v1 / acknowledgement v1 / lease, §8.58) ----------------

export interface FeedbackAnchor {
  file_path: string;
  /** Zero-based hunk position within the file (Hunk's own index). */
  hunk_index: number;
  side: "old" | "new";
  /** Positive one-based line number on `side`. */
  line: number;
}

export interface FeedbackRecord {
  schema: 1;
  /** `<watch_instance_id>:<hunk-note-id>` — the stable at-least-once identity. */
  feedback_id: string;
  watch_instance_id: string;
  plan_id: string;
  /** Publisher-assigned ISO-8601. */
  created_at: string;
  changeset_id: string | null;
  anchor: FeedbackAnchor;
  body: string;
}

export interface DeliveryAck {
  schema: 1;
  feedback_id: string;
  delivered_at: string;
  run_id: string;
  pi_session_id: string;
}

export interface OutboxRead {
  records: FeedbackRecord[];
  /** Lines held for a later read: the trailing partial line + unknown-schema lines. */
  held: number;
  warnings: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isAnchor(value: unknown): value is FeedbackAnchor {
  if (!isRecord(value)) return false;
  return (
    typeof value.file_path === "string" &&
    typeof value.hunk_index === "number" &&
    Number.isInteger(value.hunk_index) &&
    value.hunk_index >= 0 &&
    (value.side === "old" || value.side === "new") &&
    typeof value.line === "number" &&
    Number.isInteger(value.line) &&
    value.line >= 1
  );
}

function isFeedbackRecord(
  value: Record<string, unknown>,
): value is FeedbackRecord & Record<string, unknown> {
  return (
    typeof value.feedback_id === "string" &&
    value.feedback_id !== "" &&
    typeof value.watch_instance_id === "string" &&
    typeof value.plan_id === "string" &&
    typeof value.created_at === "string" &&
    (value.changeset_id === null || typeof value.changeset_id === "string") &&
    isAnchor(value.anchor) &&
    typeof value.body === "string" &&
    value.body !== ""
  );
}

/**
 * Split NDJSON content into complete lines + the held trailing partial (no trailing LF means a
 * concurrent appender may still be mid-write — hold it for the next read, never parse it).
 */
function completeLines(content: string): { lines: string[]; heldPartial: boolean } {
  const heldPartial = content !== "" && !content.endsWith("\n");
  const lines = content.split("\n");
  // The final split element is either "" (trailing LF) or the held partial — drop it either way.
  lines.pop();
  return { lines: lines.filter((line) => line.trim() !== ""), heldPartial };
}

/** The lenient §8.58 outbox read. A missing file is the normal no-feedback state. */
export function readOutbox(path: string): OutboxRead {
  let content: string;
  try {
    content = readFileSync(path, "utf8");
  } catch {
    return { records: [], held: 0, warnings: [] };
  }
  const { lines, heldPartial } = completeLines(content);
  const records: FeedbackRecord[] = [];
  const warnings: string[] = [];
  let held = heldPartial ? 1 : 0;
  const firstLineById = new Map<string, string>();
  for (const line of lines) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      warnings.push(`skipping a malformed outbox line (not JSON): ${line.slice(0, 80)}`);
      continue;
    }
    if (!isRecord(parsed)) {
      warnings.push(`skipping a malformed outbox line (not an object): ${line.slice(0, 80)}`);
      continue;
    }
    if (parsed.schema !== 1) {
      // An unknown version is HELD, never skipped/acked: a newer writer may be talking to an
      // older receiver — pausing keeps at-least-once intact for a receiver that understands it.
      warnings.push(
        `holding an outbox record with unknown schema ${JSON.stringify(parsed.schema)} — ` +
          "a newer perk may be required to deliver it",
      );
      held += 1;
      continue;
    }
    if (!isFeedbackRecord(parsed)) {
      warnings.push(`skipping a structurally invalid outbox record: ${line.slice(0, 80)}`);
      continue;
    }
    const prior = firstLineById.get(parsed.feedback_id);
    if (prior !== undefined) {
      if (prior !== line) {
        warnings.push(
          `conflicting bytes for feedback_id ${parsed.feedback_id} — keeping the first record ` +
            "(outbox corruption)",
        );
      }
      continue; // duplicates collapse to the first valid record
    }
    firstLineById.set(parsed.feedback_id, line);
    records.push(parsed);
  }
  return { records, held, warnings };
}

/** The delivered-id set (same leniency; any line carrying a string feedback_id counts). */
export function readDeliveredIds(path: string): Set<string> {
  let content: string;
  try {
    content = readFileSync(path, "utf8");
  } catch {
    return new Set();
  }
  const ids = new Set<string>();
  for (const line of completeLines(content).lines) {
    try {
      const parsed: unknown = JSON.parse(line);
      // Deliberately schema-lenient: taking the id from ANY parseable ack line can only
      // suppress a duplicate redelivery, never cause loss.
      if (isRecord(parsed) && typeof parsed.feedback_id === "string" && parsed.feedback_id !== "") {
        ids.add(parsed.feedback_id);
      }
    } catch {
      // malformed ack lines are ignored — at-least-once tolerates the resulting duplicate
    }
  }
  return ids;
}

/** Append acknowledgements — one complete line + LF per ack (the O_APPEND discipline). */
export function appendAcks(path: string, acks: readonly DeliveryAck[]): void {
  mkdirSync(dirname(path), { recursive: true });
  for (const ack of acks) {
    appendFileSync(path, `${JSON.stringify(ack)}\n`, "utf8");
  }
}

// --- the consumer lease (§8.58) ------------------------------------------------------------

export interface LeaseIdentity {
  runId: string;
  piSessionId: string;
}

export type LeaseAcquisition = { owned: true; token: string } | { owned: false; reason: string };

interface LeaseFile {
  schema: 1;
  token: string;
  run_id: string;
  pi_session_id: string;
  claimed_at: string;
  heartbeat_at: string;
}

function leasePath(lockDir: string): string {
  return join(lockDir, "lease.json");
}

function readLease(lockDir: string): LeaseFile | null {
  try {
    const parsed: unknown = JSON.parse(readFileSync(leasePath(lockDir), "utf8"));
    if (
      isRecord(parsed) &&
      parsed.schema === 1 &&
      typeof parsed.token === "string" &&
      typeof parsed.run_id === "string" &&
      typeof parsed.pi_session_id === "string" &&
      typeof parsed.claimed_at === "string" &&
      typeof parsed.heartbeat_at === "string"
    ) {
      return parsed as unknown as LeaseFile;
    }
    return null;
  } catch {
    return null;
  }
}

/** Temp-file + rename within the lock dir (atomicWriteFileSync's own discipline). */
function writeLease(lockDir: string, lease: LeaseFile): void {
  atomicWriteFileSync(leasePath(lockDir), `${JSON.stringify(lease)}\n`);
}

function freshLease(identity: LeaseIdentity, nowMs: number, claimedAt?: string): LeaseFile {
  const at = new Date(nowMs).toISOString();
  return {
    schema: 1,
    token: randomBytes(8).toString("hex"),
    run_id: identity.runId,
    pi_session_id: identity.piSessionId,
    claimed_at: claimedAt ?? at,
    heartbeat_at: at,
  };
}

/** Atomic `mkdir` (non-recursive, so EEXIST is the contention signal) + first lease write. */
function tryFreshAcquire(lockDir: string, identity: LeaseIdentity, nowMs: number): string | null {
  try {
    mkdirSync(lockDir);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") return null;
    throw error;
  }
  const lease = freshLease(identity, nowMs);
  writeLease(lockDir, lease);
  return lease.token;
}

/**
 * Acquire the single-consumer lease (§8.58). Atomic directory creation is the primitive; on
 * contention: same-identity → idempotent reacquire with a FRESH token (the fencing that retires
 * a `/reload` predecessor instance); stale (heartbeat older than `STALE_LEASE_MS`, lock-dir
 * mtime when `lease.json` is corrupt) → quarantine-rename then ONE fresh-acquire retry
 * (competing reclaimers converge on one winner; the winner best-effort-removes its quarantine
 * dir); fresh foreign → passive. `now()` is injected for deterministic tests.
 */
export function acquireLease(
  lockDir: string,
  identity: LeaseIdentity,
  now: () => number,
): LeaseAcquisition {
  mkdirSync(dirname(lockDir), { recursive: true });
  const nowMs = now();
  const fresh = tryFreshAcquire(lockDir, identity, nowMs);
  if (fresh !== null) return { owned: true, token: fresh };

  const lease = readLease(lockDir);
  if (
    lease !== null &&
    lease.run_id === identity.runId &&
    lease.pi_session_id === identity.piSessionId
  ) {
    const reacquired = freshLease(identity, nowMs, lease.claimed_at);
    writeLease(lockDir, reacquired);
    return { owned: true, token: reacquired.token };
  }

  // Staleness basis: the recorded heartbeat, else (corrupt lease.json) the lock-dir mtime.
  let basisMs = lease !== null ? Date.parse(lease.heartbeat_at) : Number.NaN;
  if (Number.isNaN(basisMs)) {
    try {
      basisMs = statSync(lockDir).mtimeMs;
    } catch {
      // The dir vanished between mkdir-EEXIST and stat (a racing release) — retry fresh below.
      basisMs = Number.NEGATIVE_INFINITY;
    }
  }
  if (nowMs - basisMs < STALE_LEASE_MS) {
    const holder =
      lease !== null
        ? `run ${lease.run_id} (session ${lease.pi_session_id})`
        : "an unidentified session";
    return {
      owned: false,
      reason: `another live implement session holds the feedback lease: ${holder}`,
    };
  }

  // Stale: quarantine the dead lock dir under a unique name, then ONE fresh-acquire retry.
  // A failed rename means a competing reclaimer already moved it — still take the retry.
  const quarantine = `${lockDir}.stale-${process.pid.toString(36)}-${randomBytes(4).toString("hex")}`;
  let renamed = false;
  try {
    renameSync(lockDir, quarantine);
    renamed = true;
  } catch {
    renamed = false;
  }
  const retried = tryFreshAcquire(lockDir, identity, nowMs);
  if (renamed) {
    try {
      rmSync(quarantine, { recursive: true, force: true });
    } catch {
      // best-effort — a leftover quarantine dir is harmless and swept on the next open
    }
  }
  if (retried !== null) return { owned: true, token: retried };
  return { owned: false, reason: "another session reclaimed the stale feedback lease first" };
}

/**
 * Best-effort removal of leftover `consumer.lock.stale-*` quarantine dirs beside `lockDir`.
 * Returns warnings for anything it could not remove (warn-and-leave — the tier is disposable).
 */
export function sweepQuarantine(lockDir: string): string[] {
  const parent = dirname(lockDir);
  const prefix = `${basename(lockDir)}.stale-`;
  const warnings: string[] = [];
  let entries: string[];
  try {
    entries = readdirSync(parent);
  } catch {
    return warnings;
  }
  for (const entry of entries) {
    if (!entry.startsWith(prefix)) continue;
    try {
      rmSync(join(parent, entry), { recursive: true, force: true });
    } catch (error) {
      warnings.push(`could not sweep the stale lease quarantine ${entry}: ${error}`);
    }
  }
  return warnings;
}

/** Renew `heartbeat_at` — throws on a lost/foreign lease (the caller reports, never renews). */
export function renewHeartbeat(lockDir: string, token: string, now: () => number): void {
  const lease = readLease(lockDir);
  if (lease === null || lease.token !== token) {
    throw new Error("feedback lease lost — heartbeat not renewed");
  }
  writeLease(lockDir, { ...lease, heartbeat_at: new Date(now()).toISOString() });
}

/** True iff the on-disk lease still carries `token`. Any read failure is false (fail-closed). */
export function verifyLease(lockDir: string, token: string): boolean {
  const lease = readLease(lockDir);
  return lease !== null && lease.token === token;
}

/** Release the lease — removes the lock dir only on token match; best-effort, never throws. */
export function releaseLease(lockDir: string, token: string): void {
  try {
    if (!verifyLease(lockDir, token)) return;
    rmSync(lockDir, { recursive: true, force: true });
  } catch {
    // best-effort — a leftover lock dir goes stale and is reclaimed by the next open
  }
}
