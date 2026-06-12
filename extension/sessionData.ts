// The session-data accessor seam (Objective #339 Node 1.2, contracts.md §8.1).
//
// Every run-scoped session artifact lives under `.pi/workflow/scratch/runs/<run_id>/data/`, and
// ALL session-data paths flow through this module (interior) or `perk/cache.py` (exterior) — the
// guard tests (cacheGuard.test.ts / tests/test_cache_guard.py) forbid manual construction of the
// `scratch`/`runs` path segments anywhere else.
//
// Seam doctrine — degrade gracefully, never invent identity:
// - The current run_id resolves from the rebuilt `perk:workflow-state` and degrades to `null`
//   when the session has no identity. CONTRAST with `coldDoor.activeRunId`, which falls back to
//   a `cold-door-<ts>` stamp for stdin-staging debuggability: a stamp here would orphan data
//   dirs and break run_id-keyed provenance (node 1.3), so this seam never stamps.
// - Reads return `null` on absence (normal, branchable) and on I/O errors (with a loud stderr
//   warning); writes return the written path or `null` on failure (with a warning). Never
//   throws — a broken disk must not wedge a session.
//
// Imports only node builtins + cache.ts + workflowState.ts so the module stays loadable under
// `node --test`. Accepts a minimal structural ctx (`BranchSource & { cwd }`) like other seams.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { sessionDataDir } from "./cache.ts";
import { type BranchSource, branchOf, rebuildWorkflowState } from "./workflowState.ts";

/** Minimal context slice — `ExtensionContext` satisfies it (the `BranchSource` precedent). */
export interface SessionDataCtx extends BranchSource {
  cwd: string;
}

/**
 * The current session's run_id from the rebuilt workflow-state; `null` when the session has no
 * identity (no stamp fallback — see the header).
 */
export function activeSessionRunId(ctx: SessionDataCtx): string | null {
  try {
    const runId = rebuildWorkflowState(branchOf(ctx)).run_id;
    if (typeof runId === "string" && runId.length > 0) return runId;
  } catch {
    // a throwing getBranch means no resolvable identity — degrade to null
  }
  return null;
}

/** The current session's data dir as a pure path (no mkdir); `null` without a run_id. */
export function activeSessionDataDir(ctx: SessionDataCtx): string | null {
  const runId = activeSessionRunId(ctx);
  if (runId === null) return null;
  return sessionDataDir(ctx.cwd, runId);
}

/** Ensure (mkdir -p) the current session's data dir; `null` + a warning on failure. */
export function ensureSessionDataDir(ctx: SessionDataCtx): string | null {
  const dir = activeSessionDataDir(ctx);
  if (dir === null) return null;
  try {
    mkdirSync(dir, { recursive: true });
  } catch (error) {
    console.error(`perk: warning: could not create session data dir ${dir}: ${error}`);
    return null;
  }
  return dir;
}

/**
 * Read a session-data file; `null` on no run_id or an absent file (normal, branchable), and on
 * read errors (with a stderr warning). Never throws.
 */
export function readSessionData(ctx: SessionDataCtx, name: string): string | null {
  const dir = activeSessionDataDir(ctx);
  if (dir === null) return null;
  const path = join(dir, name);
  if (!existsSync(path)) return null;
  try {
    return readFileSync(path, "utf8");
  } catch (error) {
    console.error(`perk: warning: could not read session data ${path}: ${error}`);
    return null;
  }
}

/**
 * Write a session-data file (creating the data dir lazily); returns the absolute path, or
 * `null` + a stderr warning on any failure. Never throws.
 */
export function writeSessionData(
  ctx: SessionDataCtx,
  name: string,
  content: string,
): string | null {
  const dir = ensureSessionDataDir(ctx);
  if (dir === null) return null;
  const path = join(dir, name);
  try {
    writeFileSync(path, content, "utf8");
  } catch (error) {
    console.error(`perk: warning: could not write session data ${path}: ${error}`);
    return null;
  }
  return path;
}
