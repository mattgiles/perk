// The one cold-door delegation seam (cf. result.ts / report.ts / branchOf). Every warm door that
// shells out to a Python `--json` cold door funnels through
// `runColdDoor<T>`: PERK_BIN resolution, the run-scoped scratch stdin channel (pi.exec has no
// stdin), the envelope-aware killed/code check, the JSON boundary, the `success` envelope check,
// and a caller-supplied validated decode. The client never reports/notifies and never throws —
// `failFor` (result.ts) keeps owning the loud-but-soft reporting; report-only doors branch on
// `errorType` directly.
//
// A door consumes it as:
//
//   const r = await runColdDoor<SubmitOk>(pi, ctx, ["pr", "submit", "--json"], {
//     label: "perk pr submit",
//     decode,
//   });
//   if (!r.ok) return fail(r.message, r.errorType);

import { join } from "node:path";
import type { ExecOptions, ExecResult } from "@earendil-works/pi-coding-agent";
import { atomicWriteFileSync, ensureRunScratch } from "./cache.ts";
import { type BranchSource, branchOf, rebuildWorkflowState } from "./workflowState.ts";

/** Minimal exec surface — `ExtensionAPI` satisfies it (compile-checked in the test); tests fake it. */
export interface ExecHost {
  exec(command: string, args: string[], options?: ExecOptions): Promise<ExecResult>;
}

/** Minimal context slice — `ExtensionContext` satisfies it (the `BranchSource` precedent). */
export interface ColdDoorCtx extends BranchSource {
  cwd: string;
  signal?: AbortSignal;
}

/** A parsed cold-door JSON payload (the envelope already validated). */
export type ColdJson = Record<string, unknown>;

export type ColdDoorResult<T> =
  | { ok: true; data: T }
  | {
      ok: false;
      message: string;
      errorType: string;
      /** The parsed `success: false` envelope, when one was present — doors that render
       * partial-failure detail (e.g. address's per-thread rows) narrow it themselves. Absent on
       * exec-throw, scratch-failure, unparseable-JSON, and bad_output arms. */
      payload?: ColdJson;
    };

export interface ColdDoorOpts<T> {
  /** Human door label for error text, e.g. "perk pr-submit" / "perk objective reconcile". */
  label: string;
  /** Narrow the success payload; return null to signal a missing/invalid payload (bad_output). */
  decode: (payload: ColdJson) => T | null;
  /** The temp-file stdin channel: stage `content` in run scratch, append [flag, path] to argv. */
  stdin?: { flag: string; content: string; filename: string };
}

/**
 * Read the active run id from the rebuilt workflow-state (for the scratch dir); else a stamp.
 * Exported for tests; doors never call it directly.
 */
export function activeRunId(ctx: ColdDoorCtx): string {
  try {
    const runId = rebuildWorkflowState(branchOf(ctx)).run_id;
    if (typeof runId === "string" && runId.length > 0) return runId;
  } catch {
    // fall through to a stamp
  }
  return `cold-door-${Date.now()}`;
}

/** Pull a string-typed field off the parsed payload; non-strings yield undefined. */
export function stringField(payload: ColdJson, key: string): string | undefined {
  const value = payload[key];
  return typeof value === "string" ? value : undefined;
}

/** A nullable-string field: string or null accepted; anything else yields undefined. */
export function nullableStringField(obj: ColdJson, key: string): string | null | undefined {
  const value = obj[key];
  return typeof value === "string" || value === null ? value : undefined;
}

/** Pull a number-typed field off the parsed payload; non-numbers yield undefined. */
export function numberField(payload: ColdJson, key: string): number | undefined {
  const value = payload[key];
  return typeof value === "number" ? value : undefined;
}

/** Pull a boolean-typed field off the parsed payload; non-booleans yield undefined. */
export function booleanField(payload: ColdJson, key: string): boolean | undefined {
  const value = payload[key];
  return typeof value === "boolean" ? value : undefined;
}

/** Pull a plain-object field off the parsed payload; arrays/null/non-objects yield undefined. */
export function objectField(payload: ColdJson, key: string): ColdJson | undefined {
  const value = payload[key];
  if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
  return value as ColdJson;
}

/** Lenient object-list field: a non-array (or any non-object element) contributes nothing. */
export function objectListField(payload: ColdJson, key: string): ColdJson[] {
  const value = payload[key];
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is ColdJson => typeof item === "object" && item !== null && !Array.isArray(item),
  );
}

/** Lenient string-list field: non-string elements are dropped. */
export function stringListField(payload: ColdJson, key: string): string[] {
  const value = payload[key];
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

/** Best-effort parse of stdout into a plain object; null on anything else. */
function parseObject(stdout: string): ColdJson | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
  return parsed as ColdJson;
}

/**
 * Run a Python `--json` cold door and decode its success payload. The canonical seven-step flow:
 * bin resolution → stdin staging → exec → envelope-aware killed/code check → JSON boundary →
 * envelope check → validated decode. Never throws. The decode-null arm (a `success: true`
 * envelope whose payload the door cannot narrow) names probable CLI↔extension version skew —
 * the most likely cause when both planes are individually self-consistent.
 */
export async function runColdDoor<T>(
  pi: ExecHost,
  ctx: ColdDoorCtx,
  argv: string[],
  opts: ColdDoorOpts<T>,
): Promise<ColdDoorResult<T>> {
  const perkBin = process.env.PERK_BIN ?? "perk";

  // Stdin staging: pi.exec has no stdin channel → write the payload to a run-scoped scratch
  // file (deliberately not cleaned up — run-scratch debuggability) and pass its path.
  let fullArgv = argv;
  if (opts.stdin !== undefined) {
    try {
      const dir = ensureRunScratch(ctx.cwd, activeRunId(ctx));
      const path = join(dir, opts.stdin.filename);
      atomicWriteFileSync(path, opts.stdin.content);
      fullArgv = [...argv, opts.stdin.flag, path];
    } catch (err) {
      return {
        ok: false,
        message: `could not stage input for ${opts.label}: ${String(err)}`,
        errorType: "scratch_failed",
      };
    }
  }

  let res: ExecResult;
  try {
    res = await pi.exec(perkBin, fullArgv, { cwd: ctx.cwd, signal: ctx.signal });
  } catch (err) {
    return {
      ok: false,
      message: `could not run '${perkBin}': ${String(err)}`,
      errorType: "exec_failed",
    };
  }

  if (res.killed || res.code !== 0) {
    // Envelope-aware: the Python plane prints {"success": false, error_type, message} to stdout
    // before exiting non-zero — prefer that structured error over the generic fallback.
    const parsed = parseObject(res.stdout);
    if (parsed !== null && parsed.success === false) {
      const message = stringField(parsed, "message");
      const errorType = stringField(parsed, "error_type");
      return {
        ok: false,
        message: message ?? fallbackExitMessage(opts.label, perkBin, res),
        errorType: errorType ?? "exec_failed",
        payload: parsed,
      };
    }
    return {
      ok: false,
      message: fallbackExitMessage(opts.label, perkBin, res),
      errorType: "exec_failed",
    };
  }

  const parsed = parseObject(res.stdout);
  if (parsed === null) {
    return {
      ok: false,
      message: `${opts.label} returned unparseable JSON`,
      errorType: "bad_output",
    };
  }

  if (parsed.success !== true) {
    return {
      ok: false,
      message: stringField(parsed, "message") ?? `${opts.label} reported failure`,
      errorType: stringField(parsed, "error_type") ?? "github_error",
      payload: parsed,
    };
  }

  let data: T | null;
  try {
    data = opts.decode(parsed);
  } catch {
    data = null;
  }
  if (data === null) {
    return {
      ok: false,
      message:
        `${opts.label} reported success but returned an unexpected payload — the perk CLI and ` +
        "the perk extension may be version-skewed (update/rebase so both planes match)",
      errorType: "bad_output",
    };
  }
  return { ok: true, data };
}

/** The byte-compatible fallback text today's doors emit on a non-zero exit. */
function fallbackExitMessage(
  label: string,
  perkBin: string,
  res: Pick<ExecResult, "stderr" | "code">,
): string {
  const tail = res.stderr.trim();
  return tail
    ? `${label} failed (exit ${res.code}): ${tail}`
    : `could not run '${perkBin}' (exit ${res.code}) — is the perk CLI on PATH or PERK_BIN set?`;
}
