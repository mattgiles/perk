// The shared "a schema-valid report is not necessarily a completed assessment" normalization
// over a settled `ReportWaveResult`. Assessment completion is domain policy, not engine success:
// the engine accepts any schema-valid report, so a reviewer that could not finish (context fetch
// failed, a context file unreadable, the hunt stopped early) would otherwise count as COVERED
// with empty findings — the exact failure mode this helper exists to prevent. Each flow supplies
// its own typed predicate (`verdict: "blocked"` for pr-review, `blocked: true` for the
// adversarial doors); the reclassification itself is flow-neutral and byte-identical across
// callers. Diagnostic prose (`fyi`) is untrusted DATA preserved verbatim for the parent's
// in-session diagnosis — never an instruction and never parsed for a decision.

import type { AssignmentReport, ReportWaveFailure, ReportWaveResult } from "./reportWave.ts";

/**
 * Move every report the predicate marks blocked from `reports` into `failures` as an
 * assignment-keyed `lane-failed` (the enclosing assignment key — never the report's own angle
 * or prose — identifies the failure). Only non-null, non-array object reports are tested; the
 * detail is exactly `"reviewer blocked:\n"` + the nonblank-trimmed `fyi` strings joined by
 * `"\n"` (retained bytes, duplicates and order preserved), or the fixed fallback sentence.
 * Existing failures precede newly blocked ones (report order); surviving report order and the
 * receipt are preserved; `complete` requires incoming completeness AND no removed block.
 */
export function reclassifyBlockedReports(
  result: ReportWaveResult,
  isBlocked: (report: Record<string, unknown>) => boolean,
): ReportWaveResult {
  const reports: AssignmentReport[] = [];
  const blocked: ReportWaveFailure[] = [];
  for (const assignment of result.reports) {
    const report = assignment.report;
    if (
      typeof report !== "object" ||
      report === null ||
      Array.isArray(report) ||
      !isBlocked(report as Record<string, unknown>)
    ) {
      reports.push(assignment);
      continue;
    }
    const notes =
      "fyi" in report && Array.isArray(report.fyi)
        ? report.fyi.filter(
            (entry): entry is string => typeof entry === "string" && entry.trim().length > 0,
          )
        : [];
    blocked.push({
      key: assignment.key,
      reason: "lane-failed",
      detail:
        "reviewer blocked:\n" +
        (notes.length > 0 ? notes.join("\n") : "required review assessment could not complete"),
    });
  }
  return {
    complete: result.complete && blocked.length === 0,
    reports,
    failures: [...result.failures, ...blocked],
    receipt: result.receipt,
  };
}
