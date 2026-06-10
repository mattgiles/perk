// The one warm-door Result seam — owns the canonical { content, details, terminate? } tool-result
// shape and the loud-but-soft failure idiom (report + "<label> failed: <message>"), so the nine
// cold-door-delegating doors share one discriminated union instead of ad-hoc *Result/*Details
// pairs (cf. report.ts, branchOf — the node 1.1/1.2 seams).

import { type ReportTarget, report } from "./report.ts";

/** The single text block every warm-door result renders ("one text field, two doors"). */
export interface TextBlock {
  type: "text";
  text: string;
}

/** The canonical failure details. `X` adds module-specific fail extras (address's batch results). */
export type FailDetails<X extends object = Record<never, never>> = {
  ok: false;
  error: string;
  error_type: string;
} & X;

export type OkDetails<D extends object> = { ok: true } & D;

export interface OkResult<D extends object> {
  content: TextBlock[];
  details: OkDetails<D>;
  terminate?: boolean;
}

export interface FailResult<X extends object = Record<never, never>> {
  content: TextBlock[];
  details: FailDetails<X>;
  terminate?: boolean;
}

/** The discriminated-union warm-door result (discriminant: `details.ok`). */
export type Result<D extends object, X extends object = Record<never, never>> =
  | OkResult<D>
  | FailResult<X>;

/** Build a success result. `terminate: true` is included ONLY when requested (key-absent otherwise). */
export function ok<D extends object>(
  text: string,
  details: D,
  opts?: { terminate?: boolean },
): OkResult<D> {
  return {
    content: [{ type: "text", text }],
    details: { ok: true, ...details },
    ...(opts?.terminate ? { terminate: true } : {}),
  };
}

/**
 * Bind the module's fail constructor once: `const fail = failFor(ctx, scope)` (or
 * `failFor(ctx, scope, label)` when the content label differs from the report scope). Each call
 * reports loudly (`report(ctx, scope, "error", message, { alsoLog: true })`) and returns the
 * canonical soft failure: content `"<label> failed: <message>"`, details
 * `{ ok: false, error: message, error_type: errorType }`, no `terminate`.
 */
export function failFor(
  target: ReportTarget,
  scope: string,
  label: string = scope,
): (message: string, errorType: string) => FailResult {
  return (message, errorType) => {
    report(target, scope, "error", message, { alsoLog: true });
    return {
      content: [{ type: "text", text: `${label} failed: ${message}` }],
      details: { ok: false, error: message, error_type: errorType },
    };
  };
}
