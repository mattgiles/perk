// Report acceptance content checks (docs/design/pi-durable-v2-foundations.md §12 report schema,
// P6 acceptance is semantic).
//
// Invariants:
// - `parseFixtureReport` is the acceptance authority for the fixture schema: strict (exactly the
//   schema's keys, at every level), non-empty well-formed `summary` and notes, snapshot-relative
//   finding paths. A degenerate report can never read as a clean result. Every report it returns
//   is a fresh JSON value.
// - `validateReport` checks content only — schema, subject and verified digest; freshness,
//   cancellation and supersession belong to the operation pipeline. Every failure is
//   `invalid_report`. Capability binding is checked by identity: the attempt id derives from the
//   assignment id, which embeds the capability-set digest.

import { isWellFormedText } from "./canonical.ts";
import { isGitOid, isSha256Hex } from "./identity.ts";
import type { AssignmentRecord, FixtureReport, ObservationRecord } from "./records.ts";
import type { Refusal } from "./refusal.ts";
import { isSnapshotPath } from "./subject.ts";

function isPlainObject(value: unknown): value is object {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const prototype: unknown = Object.getPrototypeOf(value);
  return (
    (prototype === Object.prototype || prototype === null) &&
    Object.getOwnPropertySymbols(value).length === 0
  );
}

function hasExactKeys(value: object, keys: readonly string[]): boolean {
  const own = Object.keys(value).sort();
  return own.length === keys.length && own.every((key, i) => key === keys[i]);
}

function isNote(value: unknown): value is string {
  return typeof value === "string" && value !== "" && isWellFormedText(value);
}

/** The report as a fresh fixture-report value, or `null` when it does not match the schema. */
export function parseFixtureReport(value: unknown): FixtureReport | null {
  if (!isPlainObject(value) || !hasExactKeys(value, ["findings", "subjectDigest", "summary"])) {
    return null;
  }
  const subjectDigest: unknown = Reflect.get(value, "subjectDigest");
  const summary: unknown = Reflect.get(value, "summary");
  const findings: unknown = Reflect.get(value, "findings");
  if (typeof subjectDigest !== "string" || !isGitOid(subjectDigest)) return null;
  if (!isNote(summary)) return null;
  if (!Array.isArray(findings)) return null;
  const parsed: { path: string; note: string }[] = [];
  for (let i = 0; i < findings.length; i++) {
    const finding: unknown = findings[i];
    if (!isPlainObject(finding) || !hasExactKeys(finding, ["note", "path"])) return null;
    const path: unknown = Reflect.get(finding, "path");
    const note: unknown = Reflect.get(finding, "note");
    if (typeof path !== "string" || !isSnapshotPath(path) || !isNote(note)) return null;
    parsed.push({ path, note });
  }
  return { subjectDigest, summary, findings: parsed };
}

export type ReportValidation =
  | { readonly ok: true; readonly report: FixtureReport }
  | { readonly ok: false; readonly refusal: Refusal };

function invalid(detail: string): ReportValidation {
  return { ok: false, refusal: { reason: "invalid_report", detail } };
}

/** The content checks for a report submitted against `assignment` as of the `latest` observation. */
export function validateReport(input: {
  readonly assignment: AssignmentRecord;
  readonly latest: ObservationRecord;
  readonly report: unknown;
  readonly verifiedDigest: string;
}): ReportValidation {
  const report = parseFixtureReport(input.report);
  if (report === null) return invalid("report does not match the fixture-report schema");
  if (report.subjectDigest !== input.assignment.subject.digest) {
    return invalid(
      `report subjectDigest ${report.subjectDigest} is not the subject ${input.assignment.subject.digest} of ${input.assignment.assignmentId}`,
    );
  }
  if (typeof input.verifiedDigest !== "string" || !isSha256Hex(input.verifiedDigest)) {
    return invalid("verifiedDigest is not 64 lowercase hex");
  }
  if (input.verifiedDigest !== input.latest.manifestDigest) {
    return invalid(
      `verifiedDigest ${input.verifiedDigest} is not the manifest digest ${input.latest.manifestDigest} of ${input.latest.opId}`,
    );
  }
  return { ok: true, report };
}
