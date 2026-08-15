// The typed fetch boundary for /api/source: a local mirror of the UnitSourceOut wire
// shape plus a structural runtime check (the summary.ts posture). The kind must
// satisfy the wire.ts guard, so a successful parse is sound for its declared type.

import { isProseKind, type ProseKind } from "./wire.ts";

export type UnitSource = {
  unit: string;
  path: string;
  kind: ProseKind;
  content: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Structurally validate an unknown JSON payload as a UnitSource (null on any defect). */
export function parseUnitSource(value: unknown): UnitSource | null {
  if (
    !isRecord(value) ||
    typeof value.unit !== "string" ||
    typeof value.path !== "string" ||
    !isProseKind(value.kind) ||
    typeof value.content !== "string"
  ) {
    return null;
  }
  return { unit: value.unit, path: value.path, kind: value.kind, content: value.content };
}
