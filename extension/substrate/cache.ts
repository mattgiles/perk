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

import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

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
  writeFileSync(handoffPath(cwd, runId), `${JSON.stringify(data, null, 2)}\n`, "utf8");
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

/**
 * The session data dir for a run — a dedicated `data/` subdir so
 * run-scoped session artifacts never overlap perk machine records (dispatch.json,
 * events.ndjson, ci-*.md) living directly in the run dir. Pure path — created lazily by the
 * sessionData.ts write helpers.
 */
export function sessionDataDir(cwd: string, runId: string): string {
  return join(runScratchDir(cwd, runId), "data");
}

export function ensureRunScratch(cwd: string, runId: string): string {
  const dir = runScratchDir(cwd, runId);
  mkdirSync(dir, { recursive: true });
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
  writeFileSync(planRefPath(cwd), `${JSON.stringify(ref, null, 2)}\n`, "utf8");
}

// --- markers (existence-only) ------------------------------------------------------------

/** The land->learn semaphore; the TS twin of perk.state.cache.PENDING_LEARN. */
export const PENDING_LEARN = "pending-learn";

export function markerPath(cwd: string, name: string): string {
  return join(workflowDir(cwd), "markers", name);
}

export function setMarker(cwd: string, name: string): void {
  mkdirSync(join(workflowDir(cwd), "markers"), { recursive: true });
  writeFileSync(markerPath(cwd, name), "", "utf8");
}

export function hasMarker(cwd: string, name: string): boolean {
  return existsSync(markerPath(cwd, name));
}

export function clearMarker(cwd: string, name: string): void {
  rmSync(markerPath(cwd, name), { force: true });
}
