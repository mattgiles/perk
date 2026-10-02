// The one warm-door Result seam — owns the canonical { content, details, terminate? } tool-result
// shape and the loud-but-soft failure idiom (report + "<label> failed: <message>"), so the nine
// cold-door-delegating doors share one discriminated union instead of ad-hoc *Result/*Details
// pairs (cf. report.ts, branchOf).
//
// It also owns the rule mapping that shape onto Pi's structured result contract
// (`structureResult`, applied once to every perk tool by the registration seam, contracts.md
// §8.40): `details` doubles as `structuredContent`, and a soft failure (`details.ok === false`)
// is flagged `isError` — so the `details.ok` discriminant every perk tool already follows is what
// the model, Pi's UI and programmatic callers (nested `ctx.executeTool`, codemode scripts) see.

import type { JsonValue } from "@earendil-works/pi-ai";
import { type ReportTarget, report } from "../surfaces/report.ts";

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
 * reports through the terminal-safe report seam (`alsoLog` mirrors complete diagnostics only in
 * headless/RPC contexts) and returns the canonical soft failure: content
 * `"<label> failed: <message>"`, details
 * `{ ok: false, error: message, error_type: errorType }`, no `terminate`. `X` is the
 * `FailDetails` extras hook: `failFor<X>(…)` lets a call attach module-specific fail details
 * (spread AFTER `error`/`error_type`) — e.g. the learn wave's attempt receipts. Extras stay
 * optional, so existing extras-free call sites are unchanged.
 */
export function failFor<X extends object = Record<never, never>>(
  target: ReportTarget,
  scope: string,
  label: string = scope,
): (message: string, errorType: string, extras?: X) => FailResult<X> {
  return (message, errorType, extras) => {
    report(target, scope, "error", message, { alsoLog: true });
    return {
      content: [{ type: "text", text: `${label} failed: ${message}` }],
      details: {
        ok: false,
        error: message,
        error_type: errorType,
        ...(extras ?? {}),
      } as FailDetails<X>,
    };
  };
}

/** The two result fields `structureResult` derives; everything else on a result passes through. */
export type StructuredFields = { structuredContent?: JsonValue; isError?: boolean };

/**
 * Derive Pi's structured result fields from a perk tool result:
 *  - `structuredContent` is `details` itself — the same reference, no clone — and is absent when
 *    `details` is undefined. The cast is sound by construction: perk details are JSON (Pi persists
 *    them via `JSON.stringify`), and a seam every tool passes through must gain no throw path
 *    (a JSON round-trip would throw on a BigInt or a cycle) and no copy;
 *  - an own `ok === false` on an object `details` forces `isError: true`; otherwise the incoming
 *    flag is preserved exactly (key absent stays absent, a tool-set `true` survives). `false` is
 *    never written.
 * Every other field (`content`, `details`, `terminate`, `usage`) is spread through untouched.
 * Pure and idempotent.
 */
export function structureResult<R extends { content: unknown; details?: unknown }>(
  result: R,
): R & StructuredFields {
  const { details } = result;
  const failed =
    typeof details === "object" &&
    details !== null &&
    Object.hasOwn(details, "ok") &&
    (details as { ok?: unknown }).ok === false;
  return {
    ...result,
    ...(details !== undefined ? { structuredContent: details as JsonValue } : {}),
    ...(failed ? { isError: true } : {}),
  };
}
