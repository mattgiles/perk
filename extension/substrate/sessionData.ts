// The session-data accessor seam (contracts.md §8.1).
//
// Every run-scoped session artifact lives under `.perk/workflow/scratch/runs/<run_id>/data/`, and
// ALL session-data paths flow through this module (interior) or `perk/state/cache.py` (exterior) — the
// guard tests (cacheGuard.test.ts / tests/test_cache_guard.py) forbid manual construction of the
// `scratch`/`runs` path segments anywhere else.
//
// Seam doctrine — degrade gracefully, never invent identity:
// - The current run_id resolves from the rebuilt `perk:workflow-state` and degrades to `null`
//   when the session has no identity. CONTRAST with `coldDoor.activeRunId`, which falls back to
//   a `cold-door-<ts>` stamp for stdin-staging debuggability: a stamp here would orphan data
//   dirs and break run_id-keyed provenance, so this seam never stamps.
// - Reads return `null` on absence (normal, branchable) and on I/O errors (with a loud stderr
//   warning); writes return the written path or `null` on failure (with a warning). Never
//   throws — a broken disk must not wedge a session.
//
// Provenance doctrine (contracts §8.1/§8.3) — the pointer makes it consumable:
// - A session artifact is *consumable* only via its `session_artifacts` pointer
//   ({run_id, name, path, digest, at}) in the rebuilt `perk:workflow-state`. A bare file on
//   disk is never trusted: `writeSessionArtifact` returns a path only once BOTH the file and
//   the pointer landed; `readSessionArtifact` validates the on-disk bytes against the rebuilt
//   pointer and fails open to `null` when validation refuses.
// - Validation always derives the path from `run_id` + `name` through the seam; the recorded
//   `pointer.path` is informational/debugging only and is never dereferenced (workflow-state
//   entries are reconstructable from untrusted session history).
// - The four lifecycle guarantees: REWIND ⇒ the rebuilt branch carries an older pointer while
//   disk holds newer bytes ⇒ digest mismatch ⇒ refusal. FORK ⇒ the child run_id no longer
//   matches the inherited pointer's ⇒ silent refusal (no inheritance; fresh dir).
//   RELOAD/COMPACTION ⇒ same run_id ⇒ pointer + dir persist. CONCURRENT SESSIONS ⇒ run_id
//   keying isolates dirs and pointers alike — validation never crosses run_ids.
//
// Imports only node builtins + cache.ts + workflowState.ts + report.ts so the module stays
// loadable under `node --test`; accepts a minimal structural ctx (`BranchSource & { cwd }`).

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import type { ReportTarget } from "../surfaces/report.ts";
import { atomicWriteFileSync, sessionDataDir } from "./cache.ts";
import {
  appendWorkflowState,
  type BranchSource,
  branchOf,
  type EntrySink,
  rebuildWorkflowState,
  type SessionArtifactPointer,
} from "./workflowState.ts";

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

/** Per-name pointer identity: same run_id + same digest (the custom-equals comparator). */
function artifactMapsEqual(
  rebuilt: Record<string, SessionArtifactPointer> | null | undefined,
  expected: Record<string, SessionArtifactPointer> | null | undefined,
): boolean {
  const a = rebuilt ?? {};
  const b = expected ?? {};
  const names = Object.keys(b);
  if (Object.keys(a).length !== names.length) return false;
  return names.every(
    (name) => a[name]?.run_id === b[name]?.run_id && a[name]?.digest === b[name]?.digest,
  );
}

/**
 * Write a session artifact AND record its provenance pointer in `perk:workflow-state`.
 * Returns the absolute written path only when the artifact is *fully recorded* (file written,
 * read back, digested, pointer strict-appended); `null` on any failure — the seam/module has
 * already warned, and an orphan file (pointer-append failure) is gitignored scratch for the
 * GC to prune. Never throws.
 */
export function writeSessionArtifact(
  sink: EntrySink,
  ctx: SessionDataCtx & ReportTarget,
  name: string,
  content: string,
): string | null {
  const written = writeSessionData(ctx, name, content);
  if (written === null) return null; // already warned; never point at an unwritten file

  // Digest the bytes as read back from disk — catches encoding/disk surprises.
  const readBack = readSessionData(ctx, name);
  if (readBack === null) {
    console.error(`perk: warning: session artifact ${written} unreadable after write`);
    return null;
  }

  const runId = activeSessionRunId(ctx);
  if (runId === null) return null; // unreachable after a successful write; belt-and-braces
  const pointer: SessionArtifactPointer = {
    run_id: runId,
    name,
    path: relative(ctx.cwd, written),
    digest: digestSessionData(readBack),
    at: new Date().toISOString(),
  };

  // Per-field LWW: each append must carry the WHOLE merged map so sibling artifacts survive.
  const merged: Record<string, SessionArtifactPointer> = {
    ...(rebuildWorkflowState(branchOf(ctx)).session_artifacts ?? {}),
    [name]: pointer,
  };
  const ok = appendWorkflowState(sink, ctx, {
    data: { session_artifacts: merged },
    field: "session_artifacts",
    expected: merged,
    scope: "session-data",
    failure: `session_artifacts pointer read-back failed for ${name}`,
    equals: artifactMapsEqual,
  });
  return ok ? written : null;
}

/**
 * Read a session artifact through its provenance pointer; fail-open `null` when validation
 * refuses. Tiering: no identity / no pointer / run_id mismatch (the designed fork-isolation
 * path) → silent `null`; pointer matches but the file is absent, unreadable, or its digest
 * differs (rewind, tamper) → stderr warning + `null`. The path is always DERIVED from
 * `run_id` + `name` via the seam — `pointer.path` is never dereferenced. Never throws.
 */
export function readSessionArtifact(
  ctx: SessionDataCtx,
  name: string,
): { path: string; content: string } | null {
  const runId = activeSessionRunId(ctx);
  if (runId === null) return null;
  let pointer: SessionArtifactPointer | undefined;
  try {
    pointer = rebuildWorkflowState(branchOf(ctx)).session_artifacts?.[name];
  } catch {
    return null;
  }
  if (pointer === undefined) return null;
  if (pointer.run_id !== runId) return null; // fork / concurrent isolation — by design, silent

  const path = join(sessionDataDir(ctx.cwd, runId), name);
  const content = readSessionData(ctx, name);
  if (content === null) {
    console.error(`perk: warning: session artifact ${name} has a pointer but no file at ${path}`);
    return null;
  }
  if (digestSessionData(content) !== pointer.digest) {
    console.error(
      `perk: warning: session artifact ${path} digest mismatch (rewound or modified) — refusing`,
    );
    return null;
  }
  return { path, content };
}
