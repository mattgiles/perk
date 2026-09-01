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
// One artifact-discipline implementation: the classified cores (`writeSessionArtifactClassified`
// / `readSessionArtifactClassified`) own the full write→read-back→digest→pointer-append and
// pointer-validated-read algorithms; `writeSessionArtifact`/`readSessionArtifact` are thin
// null-collapsing wrappers for the callers that predate the `session/` WorkflowSession seam
// (which delegates to the same cores) — the wrappers die when their last caller migrates.
//
// Imports only node builtins + cache.ts + workflowState.ts + report.ts so the module stays
// loadable under `node --test`; accepts a minimal structural ctx (`BranchSource & { cwd }`).

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import type { ReportTarget } from "../surfaces/report.ts";
import { atomicWriteFileSync, ensureRunScratch, sessionDataDir } from "./cache.ts";
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
 * The composed context the artifact WRITE core needs (`SessionDataCtx` for paths/branch +
 * `ReportTarget` for the strict-append seam's loud failure reporting). Exported so `session/`
 * consumes the reporting slice THROUGH this seam without importing `surfaces/` directly.
 */
export type SessionArtifactCtx = SessionDataCtx & ReportTarget;

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

/** Ensure the validated run root, then its data dir; `null` + a warning on failure. */
export function ensureSessionDataDir(ctx: SessionDataCtx): string | null {
  const runId = activeSessionRunId(ctx);
  if (runId === null) return null;
  const dir = sessionDataDir(ctx.cwd, runId);
  try {
    ensureRunScratch(ctx.cwd, runId);
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
 * The classified write outcome. `applied`/`unchanged` are the consumable arms (file + pointer
 * agree); `rejected` means the write was refused BEFORE any effect landed; `unverified` means an
 * effect may have landed (an orphan file, an unproven pointer) but the read-back proof failed —
 * the artifact is NOT consumable (gitignored scratch for the GC to prune).
 */
export type SessionArtifactWriteResult =
  | { status: "applied"; path: string; pointer: SessionArtifactPointer }
  | { status: "unchanged"; path: string; pointer: SessionArtifactPointer }
  | { status: "unverified"; problem: string }
  | { status: "rejected"; problem: string };

/**
 * The classified read outcome. `absent` is the silent, branchable tier (no identity / no
 * pointer / a cross-run fork pointer — designed isolation); `invalid` is the loud tier (a
 * pointer whose file is missing, unreadable, or digest-mismatched — rewind/tamper; the core has
 * already warned on stderr).
 */
export type SessionArtifactReadResult =
  | { status: "found"; path: string; content: string }
  | { status: "absent" }
  | { status: "invalid"; problem: string };

/**
 * Validate a session-artifact name at the seam: non-empty, no path separators (the artifact
 * name keys the pointer map and joins under the run's data dir — a separator would escape it).
 * Returns the problem string, or `null` when the name is safe. Shared with the in-memory
 * WorkflowSession backing so both backings refuse identically.
 */
export function sessionArtifactNameProblem(name: string): string | null {
  if (name.trim() === "") return "session artifact name is empty";
  if (name.includes("/") || name.includes("\\")) {
    return `session artifact name ${JSON.stringify(name)} carries a path separator`;
  }
  return null;
}

/**
 * Accept a persisted pointer only when it is SHAPE-SOUND: branch data is cast, never validated
 * (`rebuildWorkflowState` trusts entry data), so a malformed session entry can put `null` — or
 * anything else — where a pointer belongs. The cores dereference only `run_id` + `digest`
 * (`path` is always derived, `name` is the map key), so those are the fields the shape check
 * demands; anything unsound reads as "no pointer" and never throws.
 */
function soundPointer(candidate: unknown): SessionArtifactPointer | null {
  if (typeof candidate !== "object" || candidate === null) return null;
  const pointer = candidate as Partial<SessionArtifactPointer>;
  if (typeof pointer.run_id !== "string" || typeof pointer.digest !== "string") return null;
  return pointer as SessionArtifactPointer;
}

/**
 * The currently-recorded pointer for `name` when it is VALID for this run and matches the
 * on-disk bytes (quiet: the unchanged-short-circuit probe must never emit the read tier's
 * rewind warnings — a stale/broken/malformed state simply fails the probe and the write
 * proceeds).
 */
function currentValidPointer(
  ctx: SessionDataCtx,
  runId: string,
  name: string,
): { path: string; pointer: SessionArtifactPointer; diskDigest: string } | null {
  let pointer: SessionArtifactPointer | null;
  try {
    pointer = soundPointer(rebuildWorkflowState(branchOf(ctx)).session_artifacts?.[name]);
  } catch {
    return null;
  }
  if (pointer === null || pointer.run_id !== runId) return null;
  const path = join(sessionDataDir(ctx.cwd, runId), name);
  let disk: string;
  try {
    disk = readFileSync(path, "utf8");
  } catch {
    return null;
  }
  const diskDigest = digestSessionData(disk);
  if (diskDigest !== pointer.digest) return null;
  return { path, pointer, diskDigest };
}

/**
 * The classified artifact-write core: validate the name → the unchanged short-circuit (a valid
 * current pointer whose on-disk digest equals the new content's → no write, no append) → atomic
 * file write → read-back + digest → merged-map strict-append. Every failure tier keeps its
 * existing stderr warning; never throws.
 */
export function writeSessionArtifactClassified(
  sink: EntrySink,
  ctx: SessionArtifactCtx,
  name: string,
  content: string,
): SessionArtifactWriteResult {
  const nameProblem = sessionArtifactNameProblem(name);
  if (nameProblem !== null) return { status: "rejected", problem: nameProblem };

  const runId = activeSessionRunId(ctx);
  if (runId === null) {
    return {
      status: "rejected",
      problem: "session has no run_id — session artifacts need identity",
    };
  }

  // The unchanged short-circuit: a byte-identical rewrite is a no-op (no write, no fresh
  // pointer entry) — the recorded pointer already proves exactly these bytes.
  const current = currentValidPointer(ctx, runId, name);
  if (current !== null && current.diskDigest === digestSessionData(content)) {
    return { status: "unchanged", path: current.path, pointer: current.pointer };
  }

  const written = writeSessionData(ctx, name, content);
  if (written === null) {
    // already warned; never point at an unwritten file
    return { status: "rejected", problem: `could not write session data ${name} (see warnings)` };
  }

  // Digest the bytes as read back from disk — catches encoding/disk surprises.
  const readBack = readSessionData(ctx, name);
  if (readBack === null) {
    const problem = `session artifact ${written} unreadable after write`;
    console.error(`perk: warning: ${problem}`);
    return { status: "unverified", problem };
  }

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
  if (!ok) {
    // already reported through the strict-append seam
    return {
      status: "unverified",
      problem: `session_artifacts pointer read-back failed for ${name}`,
    };
  }
  return { status: "applied", path: written, pointer };
}

/**
 * The classified artifact-read core: no identity / no pointer / a cross-run pointer (fork
 * isolation) → `absent` (silent by design); a pointer whose file is missing, unreadable, or
 * digest-mismatched (rewind, tamper) → `invalid` with the stderr warning. The path is always
 * DERIVED from `run_id` + `name` via the seam — `pointer.path` is never dereferenced. Never
 * throws.
 */
export function readSessionArtifactClassified(
  ctx: SessionDataCtx,
  name: string,
): SessionArtifactReadResult {
  const runId = activeSessionRunId(ctx);
  if (runId === null) return { status: "absent" };
  let pointer: SessionArtifactPointer | null;
  try {
    pointer = soundPointer(rebuildWorkflowState(branchOf(ctx)).session_artifacts?.[name]);
  } catch {
    return { status: "absent" };
  }
  if (pointer === null) return { status: "absent" }; // no pointer — or a malformed one (no provenance)
  if (pointer.run_id !== runId) return { status: "absent" }; // fork isolation — by design, silent

  const path = join(sessionDataDir(ctx.cwd, runId), name);
  const content = readSessionData(ctx, name);
  if (content === null) {
    console.error(`perk: warning: session artifact ${name} has a pointer but no file at ${path}`);
    return { status: "invalid", problem: `session artifact ${name} has a pointer but no file` };
  }
  if (digestSessionData(content) !== pointer.digest) {
    console.error(
      `perk: warning: session artifact ${path} digest mismatch (rewound or modified) — refusing`,
    );
    return {
      status: "invalid",
      problem: `session artifact ${name} digest mismatch (rewound or modified)`,
    };
  }
  return { status: "found", path, content };
}

/**
 * Write a session artifact AND record its provenance pointer in `perk:workflow-state` — the
 * null-collapsing wrapper over `writeSessionArtifactClassified` for callers that predate the
 * WorkflowSession seam (it dies when its last caller migrates). Returns the absolute path when
 * the artifact is *fully recorded* (`applied`, or the byte-identical `unchanged` short-circuit);
 * `null` on any failure — the core has already warned. Never throws.
 */
export function writeSessionArtifact(
  sink: EntrySink,
  ctx: SessionArtifactCtx,
  name: string,
  content: string,
): string | null {
  const result = writeSessionArtifactClassified(sink, ctx, name, content);
  return result.status === "applied" || result.status === "unchanged" ? result.path : null;
}

/**
 * Read a session artifact through its provenance pointer — the null-collapsing wrapper over
 * `readSessionArtifactClassified` for callers that predate the WorkflowSession seam (it dies
 * when its last caller migrates): `absent` and `invalid` both collapse to `null` (the core has
 * already warned on the loud tier). Never throws.
 */
export function readSessionArtifact(
  ctx: SessionDataCtx,
  name: string,
): { path: string; content: string } | null {
  const result = readSessionArtifactClassified(ctx, name);
  return result.status === "found" ? { path: result.path, content: result.content } : null;
}
