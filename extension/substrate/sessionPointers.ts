// The run-cache session-pointer carrier (contracts.md §8.35) — the capture side of the cross-run
// session-pointer record. The TS twin of perk/state/session_pointers.py; both planes read/write the
// same `session-pointers.json` (the cross-plane contract is the file).
//
// Each run writes only its OWN record, keyed by `run_id`, under the SHARED MAIN CHECKOUT
// (`mainCheckoutRoot(cwd)`) so a linked-worktree run and a later resolver agree on one location. A
// run fills only the slots it owns (planning runs → `planning.*`; implement runs →
// `implementation.*`); the four class/site slots are always present (null when unset) so this
// read-modify-write merges trivially and never clobbers a sibling write.
//
// Beside the four class/site evidence slots the record carries `sessions` — the run's
// resumable-conversation index (one-to-many: a replan reuses the run id), written by
// `recordRunSession` at `session_start` for every identified arm and read by `perk resume RUN_ID`.
//
// Seam doctrine — best-effort + loud-but-non-fatal: every write is wrapped so a failure (unwritable
// root, bad disk) warns to stderr and returns false, NEVER throws. A capture failure must never
// wedge the save/launch/drive it rides on. Node builtins + cache.ts + git.ts + runId.ts only
// (loads under `node --test`).

import { existsSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";
import { atomicWriteFileSync, ensureRunScratch, runScratchDir } from "./cache.ts";
import { mainCheckoutRoot } from "./git.ts";
import { isCanonicalRunId } from "./runId.ts";

export const SESSION_POINTERS_FILE = "session-pointers.json";

/** One captured session pointer (a `main` or `worker` slot of a class). */
export interface SessionPointer {
  /** The session-file basename (matches the `perk:workflow-state` stamp). */
  pi_session_id: string;
  /** The absolute path known at capture (informational). */
  session_file: string;
  /** The inherited parent session (fork/replacement provenance), else null. */
  parent_pi_session_id: string | null;
  /** ISO-8601 capture time. */
  at: string;
}

/** The two capture sites of one session class (`main` = interior, `worker` = headless). */
export interface SessionClassPointers {
  main: SessionPointer | null;
  worker: SessionPointer | null;
}

/**
 * One resumable conversation of a run (an entry of the record's `sessions` list): the session
 * file's basename, its absolute path, the session's cwd at start, and the FIRST-capture time as
 * `new Date().toISOString()` (`YYYY-MM-DDTHH:mm:ss.sssZ` — fixed width, so lexical order is
 * chronological). `at` is provenance: an in-place update never refreshes it.
 */
export interface RunSessionEntry {
  pi_session_id: string;
  session_file: string;
  cwd: string;
  at: string;
}

/** A run's full session-pointer record (`session-pointers.json`). */
export interface SessionPointers {
  run_id: string;
  planning: SessionClassPointers;
  implementation: SessionClassPointers;
  /** The run's resumable conversations (a legacy record without the key reads as `[]`). */
  sessions: RunSessionEntry[];
}

export type SessionClass = "planning" | "implementation";
export type SessionSite = "main" | "worker";

/** The outcome of one `recordRunSession` call (`unchanged` writes nothing). */
export type RunSessionRecordOutcome = "appended" | "updated" | "unchanged" | "failed";

/** The empty record for a run (all four slots null, no sessions, until a capture fills one). */
function emptyRecord(runId: string): SessionPointers {
  return {
    run_id: runId,
    planning: { main: null, worker: null },
    implementation: { main: null, worker: null },
    sessions: [],
  };
}

function sessionPointersPath(root: string, runId: string): string {
  return join(runScratchDir(root, runId), SESSION_POINTERS_FILE);
}

/**
 * Read a run's session-pointers record from the shared main checkout; `null` when absent or
 * unparseable (best-effort — a corrupt record is treated as absent, never thrown). `root` is the
 * MAIN checkout (resolve via `mainCheckoutRoot(cwd)` at the call site).
 */
export function readSessionPointers(root: string, runId: string): SessionPointers | null {
  const path = sessionPointersPath(root, runId);
  if (!existsSync(path)) return null;
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8")) as SessionPointers;
    // A legacy record predates the `sessions` key: normalize so every reader sees a list.
    return { ...parsed, sessions: Array.isArray(parsed.sessions) ? parsed.sessions : [] };
  } catch {
    return null;
  }
}

/**
 * Record one resumable conversation into the run's `sessions` list under the shared main
 * checkout. `root` IS the main checkout (the caller passes `mainCheckoutRoot(cwd)`) — deliberately
 * asymmetric with `recordSessionPointer(cwd, …)`, which resolves the root itself.
 *
 * The grammar gate runs BEFORE any path derivation: a non-canonical `runId` is refused without
 * `readSessionPointers` or `sessionPointersPath` ever being called (nothing is created). Keyed by
 * `pi_session_id`: an absent id is appended; a present one with a different `session_file`/`cwd`
 * is updated in place (`at` untouched — it is first-capture provenance); an identical one is
 * `unchanged` and writes NOTHING. The four class/site slots ride through the read-modify-write
 * untouched. Best-effort: any failure warns to stderr and returns `failed`; never throws.
 */
export function recordRunSession(
  root: string,
  runId: string,
  entry: RunSessionEntry,
): RunSessionRecordOutcome {
  try {
    if (!isCanonicalRunId(runId)) {
      throw new Error(`non-canonical run id ${JSON.stringify(runId)}`);
    }
    const record = readSessionPointers(root, runId) ?? emptyRecord(runId);
    const existing = record.sessions.find((s) => s.pi_session_id === entry.pi_session_id);
    let outcome: RunSessionRecordOutcome;
    if (existing === undefined) {
      record.sessions.push(entry);
      outcome = "appended";
    } else if (existing.session_file === entry.session_file && existing.cwd === entry.cwd) {
      return "unchanged";
    } else {
      existing.session_file = entry.session_file;
      existing.cwd = entry.cwd;
      outcome = "updated";
    }
    ensureRunScratch(root, runId);
    atomicWriteFileSync(sessionPointersPath(root, runId), serialize(record));
    return outcome;
  } catch (error) {
    console.error(`perk: warning: could not record run session for ${runId}: ${error}`);
    return "failed";
  }
}

/**
 * Record one session pointer into `<class>.<site>` of the run's record, under the shared main
 * checkout (`mainCheckoutRoot(cwd)`). Read-modify-write: an existing record is loaded (or a fresh
 * four-slot record minted), only the named slot is set, and the whole record is written back — so
 * a planning write and an implementation write to the SAME run record never clobber each other.
 * Best-effort: returns `true` on a successful write, `false` (with a stderr warning) on any
 * failure. Never throws. Serialized byte-compatibly with the Python writer (key order +
 * 2-space indent + trailing newline).
 *
 * `preserveForeign` makes the slot first-write-wins (defense in depth against pointer
 * shadowing): when set and the slot already holds a pointer whose `pi_session_id` differs from
 * the incoming one, the write is SKIPPED with a loud stderr warning naming both session ids
 * (returns `false`) — so any future shadow vector surfaces instead of silently corrupting
 * evidence. A same-session re-capture still refreshes the slot. Default `false` keeps today's
 * overwrite semantics (each default-caller slot has exactly one legitimate writer).
 */
export function recordSessionPointer(
  cwd: string,
  runId: string,
  klass: SessionClass,
  site: SessionSite,
  pointer: SessionPointer,
  opts: { preserveForeign?: boolean } = {},
): boolean {
  if (!runId) return false;
  const root = mainCheckoutRoot(cwd);
  try {
    const record = readSessionPointers(root, runId) ?? emptyRecord(runId);
    const existing = record[klass][site];
    if (
      opts.preserveForeign === true &&
      existing !== null &&
      existing.pi_session_id !== pointer.pi_session_id
    ) {
      console.error(
        `perk: warning: session pointer ${klass}.${site} for run ${runId} already held by ` +
          `${existing.pi_session_id} — skipping foreign overwrite by ${pointer.pi_session_id}`,
      );
      return false;
    }
    // The run id is authoritative — a record read from disk keeps its own; a fresh one is minted
    // with `runId`. (A mismatched on-disk run_id is left as-is; self-keying guarantees a match.)
    record[klass][site] = pointer;
    ensureRunScratch(root, runId);
    atomicWriteFileSync(sessionPointersPath(root, runId), serialize(record));
    return true;
  } catch (error) {
    console.error(`perk: warning: could not record session pointer (${klass}.${site}): ${error}`);
    return false;
  }
}

/**
 * Capture one session pointer into `<class>.<site>` from a session file path — the call-site
 * convenience over `recordSessionPointer`. Derives `pi_session_id` from the basename and stamps
 * `at`. A `null`/empty `sessionFile` or `runId` is a no-op (`false`) — best-effort, never throws.
 * `preserveForeign` threads through to `recordSessionPointer`'s first-write-wins guard.
 */
export function captureSessionPointer(args: {
  cwd: string;
  runId: string;
  klass: SessionClass;
  site: SessionSite;
  sessionFile: string | null | undefined;
  parentSessionId?: string | null;
  preserveForeign?: boolean;
}): boolean {
  const { cwd, runId, klass, site, sessionFile } = args;
  if (!sessionFile || !runId) return false;
  return recordSessionPointer(
    cwd,
    runId,
    klass,
    site,
    {
      pi_session_id: basename(sessionFile),
      session_file: sessionFile,
      parent_pi_session_id: args.parentSessionId ?? null,
      at: new Date().toISOString(),
    },
    { preserveForeign: args.preserveForeign },
  );
}

/** Serialize a record byte-compatibly with the Python writer (explicit key order, null slots). */
function serialize(record: SessionPointers): string {
  const slot = (p: SessionPointer | null): Record<string, unknown> | null =>
    p === null
      ? null
      : {
          pi_session_id: p.pi_session_id,
          session_file: p.session_file,
          parent_pi_session_id: p.parent_pi_session_id,
          at: p.at,
        };
  const payload = {
    run_id: record.run_id,
    planning: { main: slot(record.planning.main), worker: slot(record.planning.worker) },
    implementation: {
      main: slot(record.implementation.main),
      worker: slot(record.implementation.worker),
    },
    sessions: record.sessions.map((e) => ({
      pi_session_id: e.pi_session_id,
      session_file: e.session_file,
      cwd: e.cwd,
      at: e.at,
    })),
  };
  return `${JSON.stringify(payload, null, 2)}\n`;
}
