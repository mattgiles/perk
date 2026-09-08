// The flow-neutral blocked-report normalization: the predicate is applied only to object reports,
// the exact contracts-pinned detail string, failure ordering, completeness arithmetic, and the
// preserved receipt. `prReviewWave.test.ts` remains the parity evidence for the pr-review caller;
// this suite pins the helper's own semantics so a second caller (the adversarial doors) cannot
// drift them.

import assert from "node:assert/strict";
import { test } from "node:test";
import { reclassifyBlockedReports } from "./blockedReports.ts";
import type { ReportWaveResult } from "./reportWave.ts";

const RECEIPT: ReportWaveResult["receipt"] = {
  state: "complete",
  children: [{ key: "a", runId: "r-a", success: true }],
};

function settled(
  reports: ReportWaveResult["reports"],
  failures: ReportWaveResult["failures"] = [],
) {
  return { complete: failures.length === 0, reports, failures, receipt: RECEIPT };
}

const isBlockedFlag = (report: Record<string, unknown>) => report.blocked === true;

test("reclassifyBlockedReports: a blocked object report becomes an assignment-keyed lane-failed with the fyi detail", () => {
  const result = reclassifyBlockedReports(
    settled([
      { key: "a", report: { angle: "a", blocked: false, findings: [], fyi: [] } },
      {
        key: "b",
        report: {
          angle: "not-b",
          blocked: true,
          findings: [],
          fyi: ["  context fetch failed: exit 1  ", "", "   ", "partial note", "partial note"],
        },
      },
    ]),
    isBlockedFlag,
  );
  assert.equal(result.complete, false);
  assert.deepEqual(
    result.reports.map((r) => r.key),
    ["a"],
  );
  // The ENCLOSING assignment key names the failure, never the report's angle; retained fyi bytes,
  // duplicates and order are preserved (only blank entries are dropped, retained ones untrimmed).
  assert.deepEqual(result.failures, [
    {
      key: "b",
      reason: "lane-failed",
      detail: "reviewer blocked:\n  context fetch failed: exit 1  \npartial note\npartial note",
    },
  ]);
  assert.equal(result.receipt, RECEIPT);
});

test("reclassifyBlockedReports: no usable fyi falls back to the fixed sentence", () => {
  for (const fyi of [undefined, [], ["", "   "], "not an array", [42, null]]) {
    const result = reclassifyBlockedReports(
      settled([{ key: "x", report: { blocked: true, ...(fyi === undefined ? {} : { fyi }) } }]),
      isBlockedFlag,
    );
    assert.deepEqual(result.failures, [
      {
        key: "x",
        reason: "lane-failed",
        detail: "reviewer blocked:\nrequired review assessment could not complete",
      },
    ]);
  }
});

test("reclassifyBlockedReports: the predicate sees only non-null non-array object reports", () => {
  const seen: unknown[] = [];
  const result = reclassifyBlockedReports(
    settled([
      { key: "null", report: null },
      { key: "array", report: [{ blocked: true }] },
      { key: "string", report: "blocked" },
      { key: "number", report: 1 },
      { key: "object", report: { blocked: false } },
    ]),
    (report) => {
      seen.push(report);
      return false;
    },
  );
  assert.deepEqual(seen, [{ blocked: false }]);
  assert.equal(result.complete, true);
  assert.equal(result.reports.length, 5);
  assert.deepEqual(result.failures, []);
});

test("reclassifyBlockedReports: existing failures precede newly blocked ones; surviving order is preserved", () => {
  const existing = { key: null, reason: "timeout", detail: "took too long" } as const;
  const result = reclassifyBlockedReports(
    settled(
      [
        { key: "c", report: { blocked: true, fyi: ["c blocked"] } },
        { key: "a", report: { blocked: false } },
        { key: "b", report: { blocked: true, fyi: ["b blocked"] } },
        { key: "d", report: { blocked: false } },
      ],
      [existing],
    ),
    isBlockedFlag,
  );
  assert.deepEqual(
    result.reports.map((r) => r.key),
    ["a", "d"],
  );
  assert.deepEqual(
    result.failures.map((f) => [f.key, f.reason]),
    [
      [null, "timeout"],
      ["c", "lane-failed"],
      ["b", "lane-failed"],
    ],
  );
  assert.equal(result.complete, false);
});

test("reclassifyBlockedReports: completeness needs incoming completeness AND no removed block", () => {
  const clean = reclassifyBlockedReports(
    settled([{ key: "a", report: { blocked: false } }]),
    isBlockedFlag,
  );
  assert.equal(clean.complete, true);
  const alreadyIncomplete = reclassifyBlockedReports(
    settled(
      [{ key: "a", report: { blocked: false } }],
      [{ key: "b", reason: "missing-lane", detail: "absent" }],
    ),
    isBlockedFlag,
  );
  assert.equal(alreadyIncomplete.complete, false);
  assert.deepEqual(alreadyIncomplete.reports, [{ key: "a", report: { blocked: false } }]);
});

test("reclassifyBlockedReports: the predicate is flow-supplied — a verdict-shaped predicate ignores the boolean flag", () => {
  const isBlockedVerdict = (report: Record<string, unknown>) => report.verdict === "blocked";
  const result = reclassifyBlockedReports(
    settled([
      { key: "flag", report: { blocked: true, fyi: ["flagged"] } },
      { key: "verdict", report: { verdict: "blocked", fyi: ["verdict"] } },
    ]),
    isBlockedVerdict,
  );
  assert.deepEqual(
    result.reports.map((r) => r.key),
    ["flag"],
  );
  assert.deepEqual(
    result.failures.map((f) => f.key),
    ["verdict"],
  );
});
