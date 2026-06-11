// The tool-boundary decode seam — the sibling of coldDoor.ts's JSON-boundary decode (Objective
// #224 Node 3.2). Registered tools receive their LLM-supplied `params` as `unknown` (the SDK's
// `Static<TSchema>` default); each handler NARROWS that unknown here instead of asserting a shape
// with `params as {…}`. The live LLM path is already schema-validated by pi's agent loop before
// `execute`, so these helpers are type-honesty plus defense-in-depth for the unvalidated direct
// paths (the test harness's `invokeTool`; any future programmatic caller).
//
// Tri-state by design: the uniform strict-fail policy needs ABSENT (decode to undefined — current
// optional-field behavior) distinguished from PRESENT-BUT-MISTYPED (the `null` invalid sentinel —
// fail the call with `bad_input`). That is exactly why coldDoor.ts's lenient two-state field
// helpers (absent OR mistyped → undefined) are not reused here — different boundary, different
// semantics.

/** A narrowed tool-call params object. */
export type ToolParams = Record<string, unknown>;

/** Narrow unknown tool-call params to a plain object; null when not one. */
export function paramsOf(params: unknown): ToolParams | null {
  if (typeof params !== "object" || params === null || Array.isArray(params)) return null;
  return params as ToolParams;
}

/** Tri-state string field: undefined = absent; null = present-but-mistyped. */
export function stringParam(p: ToolParams, key: string): string | undefined | null {
  const value = p[key];
  if (value === undefined) return undefined;
  return typeof value === "string" ? value : null;
}

/** Tri-state number field: undefined = absent; null = present-but-mistyped. */
export function numberParam(p: ToolParams, key: string): number | undefined | null {
  const value = p[key];
  if (value === undefined) return undefined;
  return typeof value === "number" ? value : null;
}

/** Tri-state string-array field: every element must be a string; null on any mismatch. */
export function stringArrayParam(p: ToolParams, key: string): string[] | undefined | null {
  const value = p[key];
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) return null;
  const out: string[] = [];
  for (const item of value) {
    if (typeof item !== "string") return null;
    out.push(item);
  }
  return out;
}

/** Tri-state number-array field: every element must be a number; null on any mismatch. */
export function numberArrayParam(p: ToolParams, key: string): number[] | undefined | null {
  const value = p[key];
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) return null;
  const out: number[] = [];
  for (const item of value) {
    if (typeof item !== "number") return null;
    out.push(item);
  }
  return out;
}

/** Tri-state array field: any array passes (elements stay unknown); null on a non-array. */
export function arrayParam(p: ToolParams, key: string): unknown[] | undefined | null {
  const value = p[key];
  if (value === undefined) return undefined;
  return Array.isArray(value) ? [...value] : null;
}

/** Tri-state plain-object field: arrays/null/non-objects are invalid. */
export function objectParam(p: ToolParams, key: string): ToolParams | undefined | null {
  const value = p[key];
  if (value === undefined) return undefined;
  return paramsOf(value) ?? null;
}
