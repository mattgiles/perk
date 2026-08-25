// `.perk/workflow/` cache-tier I/O — the TS twin of perk/state/cache.py (contracts.md §8.1).
//
// Both planes read and write the SAME files; the cross-plane contract is the *files*, not a
// shared module. State-tiering primitives only — no workflow semantics. Imports use no
// relative paths (only node builtins), so this module loads cleanly under `node --test`.
//
// Readers are TOTAL: a corrupt/unreadable file is reported loudly on stderr (`console.error` —
// the report() seam is intentionally unavailable here, and stderr is headless-safe) and treated
// as absent (`null`), so a bad cache blob can never crash a caller mid-`session_start` before
// the read-only gate engages. The Python twins (src/perk/state/cache.py) deliberately keep
// RAISING `CacheError` (exterior plane, launch-time fail-loud) — the cross-plane contract is
// the *files*, not error semantics.
//
// Write discipline (contracts.md §8.1): every `.perk/workflow/` write goes through
// `atomicWriteFileSync` (temp file in the same directory + atomic rename) so a concurrent
// writer can never tear a file — a reader sees either the old bytes or the new bytes, never a
// mix (guard-tested by writeGuard.test.ts). The exemptions are the append-only NDJSON streams
// — the worker's `events.ndjson` (worker/stageExecution.ts) and the §8.58 hunk-watch `outbox.ndjson` /
// `delivered.ndjson` (hunkFeedback/perkFeedback.ts / hunkFeedback/store.ts) — where O_APPEND
// appends cannot truncate-tear and whole-file replace would introduce a read-modify-write race
// between independent processes. Atomicity is not mutual exclusion — whole-file
// last-writer-wins between concurrent writers is the accepted residual.

import { randomBytes } from "node:crypto";
import {
  chmodSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join, relative } from "node:path";

/**
 * Atomically replace `path` with `content` (the interior atomic-write seam).
 *
 * Writes a temp file in the same directory (so the rename never crosses filesystems) then swaps
 * it into place; a concurrent reader sees either the old bytes or the new bytes, never a torn
 * mix. On failure the temp file is best-effort removed and the error re-thrown. Precondition:
 * the parent directory exists (same contract as `writeFileSync`; call sites mkdir first).
 * Deliberately no fsync — crash durability is out of scope; the target is inter-process tearing
 * of regenerable, gitignored workflow state.
 */
export function atomicWriteFileSync(path: string, content: string): void {
  const tmp = `${path}.${process.pid}.${randomBytes(4).toString("hex")}.tmp`;
  try {
    writeFileSync(tmp, content, "utf8");
    renameSync(tmp, path);
  } catch (error) {
    try {
      rmSync(tmp, { force: true });
    } catch {
      // best-effort cleanup — a cleanup failure must never mask the original write/rename error
    }
    throw error;
  }
}

export interface Handoff {
  run_id: string;
  consumed: boolean;
  mode?: string;
  /** The registry stage id the cold launch primed (e.g. `objective-author`). */
  stage?: string;
  pi_session_id?: string;
  [key: string]: unknown;
}

export function workflowDir(cwd: string): string {
  return join(cwd, ".perk", "workflow");
}

/**
 * Read + parse a JSON cache blob, totally: a missing file is a silent `null` (absence is the
 * normal state); an unreadable/corrupt/wrong-shape file is a LOUD `null` (one stderr line naming
 * the file kind + path + error) — treated as absent by every caller.
 */
function readJsonOrNull<T>(path: string, what: string): T | null {
  if (!existsSync(path)) return null;
  try {
    const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error(`expected a JSON object, got ${JSON.stringify(parsed)}`);
    }
    return parsed as T;
  } catch (error) {
    console.error(`perk: unreadable ${what} at ${path} — treating as absent (${error})`);
    return null;
  }
}

// --- handoff -----------------------------------------------------------------------------

export function handoffPath(cwd: string, runId: string): string {
  return join(workflowDir(cwd), "handoff", `${runId}.json`);
}

export function readHandoff(cwd: string, runId: string): Handoff | null {
  return readJsonOrNull<Handoff>(handoffPath(cwd, runId), "handoff");
}

/** Mark a handoff consumed (idempotent); a no-op when absent. Keeps the file (audit + GC). */
export function markHandoffConsumed(
  cwd: string,
  runId: string,
  opts: { piSessionId?: string } = {},
): void {
  const data = readHandoff(cwd, runId);
  if (data === null) return;
  data.consumed = true;
  if (opts.piSessionId !== undefined) data.pi_session_id = opts.piSessionId;
  atomicWriteFileSync(handoffPath(cwd, runId), `${JSON.stringify(data, null, 2)}\n`);
}

// --- scratch -----------------------------------------------------------------------------
//
// This module is the INTERIOR path-primitive seam for scratch/session-data (contracts.md §8.1):
// production code never hand-builds the `scratch`/`runs` path segments
// outside this module (guard-tested by cacheGuard.test.ts; the ctx-level current-run seam is
// sessionData.ts and the exterior twin is perk/state/cache.py).

export function scratchDir(cwd: string): string {
  return join(workflowDir(cwd), "scratch");
}

export function runScratchDir(cwd: string, runId: string): string {
  return join(scratchDir(cwd), "runs", runId);
}

/** The run-owned directory for disposable, non-authoritative model intermediates. */
export function agentScratchDir(cwd: string, runId: string): string {
  return join(runScratchDir(cwd, runId), "agent");
}

/**
 * The session data dir for a run — a dedicated `data/` subdir so
 * run-scoped session artifacts never overlap perk machine records (dispatch.json,
 * events.ndjson, ci-*.md) living directly in the run dir. Pure path — created lazily by the
 * sessionData.ts write helpers.
 */
export function sessionDataDir(cwd: string, runId: string): string {
  return join(runScratchDir(cwd, runId), "data");
}

/** Reject run ids that could select anything except one child of the shared runs directory. */
function assertSafeRunId(runId: string): void {
  if (
    runId.length === 0 ||
    runId === "." ||
    runId === ".." ||
    runId.includes("/") ||
    runId.includes("\\") ||
    runId.includes("\0")
  ) {
    throw new Error(`refusing unsafe run id ${JSON.stringify(runId)}`);
  }
}

/**
 * Ensure one checkout-owned path component is a real directory, never a static redirect.
 * Check-before-create races against a same-UID process are intentionally out of scope.
 */
function ensureUnredirectedDirectory(
  path: string,
  opts: { createMode: number; rejectGroupWorldWrite: boolean },
): void {
  let stat: ReturnType<typeof lstatSync>;
  try {
    stat = lstatSync(path);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    mkdirSync(path, { mode: opts.createMode });
    stat = lstatSync(path);
  }
  if (stat.isSymbolicLink()) throw new Error(`refusing a symlinked run-scratch path: ${path}`);
  if (!stat.isDirectory()) throw new Error(`refusing a non-directory run-scratch path: ${path}`);
  if (opts.rejectGroupWorldWrite && (stat.mode & 0o022) !== 0) {
    throw new Error(`refusing a group/world-writable run-scratch path: ${path}`);
  }
}

/**
 * Establish a run root beneath this checkout without following redirected checkout content.
 * Symlinks above `cwd` remain legal; every existing component from `.perk` through the run root
 * must be a real directory without group/world write permission, and missing components are
 * created no broader than 0755 even under a permissive umask. Run-id validation happens before
 * the first filesystem write.
 */
export function ensureRunScratch(cwd: string, runId: string): string {
  assertSafeRunId(runId);
  const dir = runScratchDir(cwd, runId);
  const components = [
    join(cwd, ".perk"),
    join(cwd, ".perk", "workflow"),
    scratchDir(cwd),
    join(scratchDir(cwd), "runs"),
    dir,
  ];
  for (const component of components) {
    ensureUnredirectedDirectory(component, {
      createMode: 0o755,
      rejectGroupWorldWrite: true,
    });
  }

  const expected = join(realpathSync(cwd), relative(cwd, dir));
  if (realpathSync(dir) !== expected) {
    throw new Error(`refusing a redirected run-scratch dir: ${dir}`);
  }
  return dir;
}

/**
 * Create the private run-owned agent directory as 0700 from the outset, then re-apply that mode on
 * reuse. The mode protects against other OS users; it is not a sandbox from another process running
 * as the same user.
 */
export function ensureAgentScratch(cwd: string, runId: string): string {
  const runDir = ensureRunScratch(cwd, runId);
  const dir = agentScratchDir(cwd, runId);
  ensureUnredirectedDirectory(dir, {
    createMode: 0o700,
    rejectGroupWorldWrite: false,
  });
  const expected = join(realpathSync(runDir), "agent");
  if (realpathSync(dir) !== expected) {
    throw new Error(`refusing a redirected agent scratch dir: ${dir}`);
  }
  chmodSync(dir, 0o700);
  return dir;
}

/**
 * The run-scoped structured run-event stream (contracts §8.12) — an NDJSON file under the
 * gitignored run scratch dir. Co-located with the run's read-only-child scratch so a runner/reader
 * finds all run artifacts under one dir.
 */
export function runEventsPath(cwd: string, runId: string): string {
  return join(runScratchDir(cwd, runId), "events.ndjson");
}

/** Names of all run scratch dirs (used to enumerate fork siblings). */
export function listRunIds(cwd: string): string[] {
  const dir = join(scratchDir(cwd), "runs");
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name);
}

// --- plan-ref: the active plan->branch ref pointer (plan-ref.json) -----------------------

/** The provider-agnostic plan ref (contracts.md §8.4); the TS twin of perk.plan.PlanRef. */
export interface PlanRef {
  provider: string;
  pr_id: string;
  url: string;
  labels: string[];
  objective_id: string | null;
  // The pinned target branch; Python-owned, parity-only on the warm plane.
  base?: string | null;
}

export function planRefPath(cwd: string): string {
  return join(workflowDir(cwd), "plan-ref.json");
}

export function readPlanRef(cwd: string): PlanRef | null {
  return readJsonOrNull<PlanRef>(planRefPath(cwd), "plan-ref");
}

export function writePlanRef(cwd: string, ref: PlanRef): void {
  mkdirSync(workflowDir(cwd), { recursive: true });
  atomicWriteFileSync(planRefPath(cwd), `${JSON.stringify(ref, null, 2)}\n`);
}

// --- hunk-watch: the watch-feedback bridge family (contracts.md §8.58) ---------------------
//
// Worktree-local, disposable: append-only NDJSON streams plus the single-consumer lease dir.
// This module is the INTERIOR construction site for the family; the hunk-plane twin is the
// self-contained bundled publisher (extension/hunkFeedback/perkFeedback.ts), pinned to these
// helpers by a path-parity test.

export function hunkWatchDir(cwd: string): string {
  return join(workflowDir(cwd), "hunk-watch");
}

/** Append-only feedback records (the Hunk publisher writes; the Pi receiver reads). */
export function hunkOutboxPath(cwd: string): string {
  return join(hunkWatchDir(cwd), "outbox.ndjson");
}

/** Append-only delivery acknowledgements (the Pi receiver writes). */
export function hunkDeliveredPath(cwd: string): string {
  return join(hunkWatchDir(cwd), "delivered.ndjson");
}

/** The single-consumer lease dir (atomic mkdir is the acquisition primitive). */
export function hunkConsumerLockDir(cwd: string): string {
  return join(hunkWatchDir(cwd), "consumer.lock");
}

export function hunkLeasePath(cwd: string): string {
  return join(hunkConsumerLockDir(cwd), "lease.json");
}

// --- markers (existence-only) ------------------------------------------------------------

/** The land->learn semaphore; the TS twin of perk.state.cache.PENDING_LEARN. */
export const PENDING_LEARN = "pending-learn";

export function markerPath(cwd: string, name: string): string {
  return join(workflowDir(cwd), "markers", name);
}

export function setMarker(cwd: string, name: string): void {
  mkdirSync(join(workflowDir(cwd), "markers"), { recursive: true });
  // Routed through the atomic seam for uniformity (empty content is trivially safe either way).
  atomicWriteFileSync(markerPath(cwd, name), "");
}

export function hasMarker(cwd: string, name: string): boolean {
  return existsSync(markerPath(cwd, name));
}

export function clearMarker(cwd: string, name: string): void {
  rmSync(markerPath(cwd, name), { force: true });
}
