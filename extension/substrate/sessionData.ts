// The session-data accessor seam (contracts.md §8.1) — RAW PRIMITIVES ONLY.
//
// Every run-scoped session artifact lives under `.perk/workflow/scratch/runs/<run_id>/data/`, and
// ALL session-data paths flow through this module (interior) or `perk/state/cache.py` (exterior) — the
// guard tests (cacheGuard.test.ts / tests/test_cache_guard.py) forbid manual construction of the
// `scratch`/`runs` path segments anywhere else.
//
// Seam doctrine — degrade gracefully, never invent identity:
// - The current run_id resolves from the rebuilt `perk:workflow-state`, narrowed non-empty AND
//   safe as a path component (`isSafeRunId` — a hostile rebuilt id degrades to no-identity
//   before any path derivation), and degrades to `null` when the session has no identity.
//   CONTRAST with `coldDoor.activeRunId`, which falls back to a `cold-door-<ts>` stamp for
//   stdin-staging debuggability: a stamp here would orphan data dirs and break run_id-keyed
//   provenance, so this seam never stamps.
// - Reads return `null` on absence (normal, branchable) and on I/O errors (with a loud stderr
//   warning); writes return the written path or `null` on failure (with a warning). Never
//   throws — a broken disk must not wedge a session.
// - The file primitives (`readSessionData`/`writeSessionData`/`ensureSessionDataDir`) take an
//   EXPLICIT run id — identity is resolved ONCE (by the session engine, or here via
//   `activeSessionRunId`) and passed down, so two independent identity reads can never
//   disagree about which run's storage an operation touches.
//
// The ARTIFACT DISCIPLINE (provenance pointers, digest validation, the classified write/read
// tiers — contracts §8.1/§8.3) lives in the session engine, `session/workflowSession.ts`: this
// module supplies only the file mechanics its production binding
// (`session/branchWorkflowSession.ts`) builds its content port from. A bare file on disk is
// never trusted — consumers go through the `WorkflowSession` seam.
//
// Imports only node builtins + cache.ts + workflowState.ts + report.ts so the module stays
// loadable under `node --test`; accepts a minimal structural ctx (`BranchSource & { cwd }`).

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { ReportTarget } from "../surfaces/report.ts";
import { atomicWriteFileSync, ensureRunScratch, isSafeRunId, sessionDataDir } from "./cache.ts";
import { type BranchSource, branchOf, rebuildWorkflowState } from "./workflowState.ts";

/** Minimal context slice — `ExtensionContext` satisfies it (the `BranchSource` precedent). */
export interface SessionDataCtx extends BranchSource {
  cwd: string;
}

/**
 * The composed context the session engine's production binding needs (`SessionDataCtx` for
 * paths/branch + `ReportTarget` for the strict-append seam's loud failure reporting). Exported
 * so `session/` consumes the reporting slice THROUGH this seam without importing `surfaces/`
 * directly.
 */
export type SessionArtifactCtx = SessionDataCtx & ReportTarget;

/**
 * The current session's run_id from the rebuilt workflow-state; `null` when the session has no
 * identity (no stamp fallback — see the header) OR when the rebuilt id is unsafe as a path
 * component (the read-path trust boundary: `isSafeRunId` — an unsafe persisted id must never
 * reach a path derivation or a receipt).
 */
export function activeSessionRunId(ctx: SessionDataCtx): string | null {
  try {
    const runId = rebuildWorkflowState(branchOf(ctx)).run_id;
    if (typeof runId === "string" && isSafeRunId(runId)) return runId;
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

/**
 * Ensure the validated run root, then its data dir, for an EXPLICIT run id; `null` + a warning
 * on failure (an unsafe id is refused loudly by the write path's `ensureRunScratch`). The run
 * identity is the CALLER's: the session engine passes its one validated id so storage, pointer,
 * and receipt can never disagree.
 */
export function ensureSessionDataDir(cwd: string, runId: string): string | null {
  const dir = sessionDataDir(cwd, runId);
  try {
    ensureRunScratch(cwd, runId);
    mkdirSync(dir, { recursive: true });
  } catch (error) {
    console.error(`perk: warning: could not create session data dir ${dir}: ${error}`);
    return null;
  }
  return dir;
}

/**
 * Read a run's session-data file; `null` on an absent file (normal, branchable) and on read
 * errors (with a stderr warning). Never throws.
 */
export function readSessionData(cwd: string, runId: string, name: string): string | null {
  const path = join(sessionDataDir(cwd, runId), name);
  if (!existsSync(path)) return null;
  try {
    return readFileSync(path, "utf8");
  } catch (error) {
    console.error(`perk: warning: could not read session data ${path}: ${error}`);
    return null;
  }
}

/**
 * Write a run's session-data file (creating the data dir lazily); returns the absolute path,
 * or `null` + a stderr warning on any failure. Never throws.
 */
export function writeSessionData(
  cwd: string,
  runId: string,
  name: string,
  content: string,
): string | null {
  const dir = ensureSessionDataDir(cwd, runId);
  if (dir === null) return null;
  const path = join(dir, name);
  try {
    atomicWriteFileSync(path, content);
  } catch (error) {
    console.error(`perk: warning: could not write session data ${path}: ${error}`);
    return null;
  }
  return path;
}

/** The session-artifact digest convention: `sha256:` + lowercase hex of the UTF-8 bytes. */
export function digestSessionData(content: string): string {
  return `sha256:${createHash("sha256").update(content, "utf8").digest("hex")}`;
}
