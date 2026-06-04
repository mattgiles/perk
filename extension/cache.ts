// `.pi/workflow/` cache-tier I/O — the TS twin of perk/cache.py (contracts.md §8.1).
//
// Both planes read and write the SAME files; the cross-plane contract is the *files*, not a
// shared module. State-tiering primitives only — no workflow semantics. Imports use no
// relative paths (only node builtins), so this module loads cleanly under `node --test`.

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
  return join(cwd, ".pi", "workflow");
}

// --- handoff -----------------------------------------------------------------------------

export function handoffPath(cwd: string, runId: string): string {
  return join(workflowDir(cwd), "handoff", `${runId}.json`);
}

export function readHandoff(cwd: string, runId: string): Handoff | null {
  const path = handoffPath(cwd, runId);
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf8")) as Handoff;
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

export function runScratchDir(cwd: string, runId: string): string {
  return join(workflowDir(cwd), "scratch", "runs", runId);
}

export function ensureRunScratch(cwd: string, runId: string): string {
  const dir = runScratchDir(cwd, runId);
  mkdirSync(dir, { recursive: true });
  return dir;
}

/** Names of all run scratch dirs (used to enumerate fork siblings). */
export function listRunIds(cwd: string): string[] {
  const dir = join(workflowDir(cwd), "scratch", "runs");
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
}

export function planRefPath(cwd: string): string {
  return join(workflowDir(cwd), "plan-ref.json");
}

export function readPlanRef(cwd: string): PlanRef | null {
  const path = planRefPath(cwd);
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf8")) as PlanRef;
}

export function writePlanRef(cwd: string, ref: PlanRef): void {
  mkdirSync(workflowDir(cwd), { recursive: true });
  writeFileSync(planRefPath(cwd), `${JSON.stringify(ref, null, 2)}\n`, "utf8");
}

// --- plan body cache (`cache.plan`) ------------------------------------------------------

/**
 * The materialized plan-body cache (`cache.plan`, contracts §8.1). Written by the Python cold door
 * (`perk implement` → `launch._materialize_plan_body`) when it positions the worktree; read here so
 * in-session checkpoints (P2.T2c) seed from its `## Steps` list (inert when absent).
 */
export function planBodyPath(cwd: string): string {
  return join(workflowDir(cwd), "plan.md");
}

export function readPlanBody(cwd: string): string | null {
  const path = planBodyPath(cwd);
  if (!existsSync(path)) return null;
  return readFileSync(path, "utf8");
}

// --- markers (existence-only) ------------------------------------------------------------

/** The land->learn semaphore (Q2/Q5); the TS twin of perk.cache.PENDING_LEARN. */
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
