// Report acceptance content (docs/design/pi-durable-v2-foundations.md §12 report schema, P6): the
// strict fixture-report parser, and each `invalid_report` arm of `validateReport` — every failing
// fixture is otherwise valid, so it fails on exactly its own arm.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { AssignmentRecord, ObservationRecord } from "./records.ts";
import { parseFixtureReport, validateReport } from "./report.ts";

const T1 = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
const T2 = "2222222222222222222222222222222222222222";
const M1 = "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1";
const M2 = "a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2";

const VALID = {
  subjectDigest: T1,
  summary: "two findings \u{1F600}",
  findings: [
    { path: "src/a.ts", note: "unused import" },
    { path: "docs/\u{1F600}.md", note: "typo \u{1F600}" },
  ],
};

test("parseFixtureReport accepts a valid report as a fresh value", () => {
  const parsed = parseFixtureReport(VALID);
  assert.deepEqual(parsed, VALID);
  assert.notEqual(parsed, VALID, "a fresh value");
  assert.deepEqual(parseFixtureReport({ ...VALID, findings: [] }), { ...VALID, findings: [] });
  assert.deepEqual(
    parseFixtureReport({ ...VALID, subjectDigest: "a".repeat(64) })?.subjectDigest,
    "a".repeat(64),
  );
});

test("parseFixtureReport returns null for anything off the schema", () => {
  const finding = VALID.findings[0];
  const { subjectDigest: _s, ...noSubject } = VALID;
  const { summary: _m, ...noSummary } = VALID;
  const { findings: _f, ...noFindings } = VALID;
  const cases: [string, unknown][] = [
    ["null", null],
    ["an array", [VALID]],
    ["a string", "report"],
    ["missing subjectDigest", noSubject],
    ["missing summary", noSummary],
    ["missing findings", noFindings],
    ["an extra top-level key", { ...VALID, verdict: "clean" }],
    ["an extra finding key", { ...VALID, findings: [{ ...finding, line: 3 }] }],
    ["a missing finding key", { ...VALID, findings: [{ path: "a.ts" }] }],
    ["a numeric summary", { ...VALID, summary: 1 }],
    ["findings not an array", { ...VALID, findings: {} }],
    ["a finding not an object", { ...VALID, findings: ["a.ts"] }],
    ["a numeric note", { ...VALID, findings: [{ path: "a.ts", note: 1 }] }],
    ["an empty summary", { ...VALID, summary: "" }],
    ["an empty note", { ...VALID, findings: [{ path: "a.ts", note: "" }] }],
    ["a lone-surrogate summary", { ...VALID, summary: "bad \uD800" }],
    ["a lone-surrogate note", { ...VALID, findings: [{ path: "a.ts", note: "\uDC00" }] }],
    ["an absolute finding path", { ...VALID, findings: [{ path: "/etc/passwd", note: "x" }] }],
    ["a dot-dot finding path", { ...VALID, findings: [{ path: "../a.ts", note: "x" }] }],
    ["an uppercase subjectDigest", { ...VALID, subjectDigest: T1.toUpperCase() }],
    ["a short subjectDigest", { ...VALID, subjectDigest: T1.slice(2) }],
  ];
  for (const [label, value] of cases) assert.equal(parseFixtureReport(value), null, label);
});

const ASSIGNMENT: AssignmentRecord = {
  type: "assignment",
  opId: "assignment-op",
  assignmentId: "assignment-id",
  kind: "fixture-report",
  role: "a",
  subject: { kind: "git-tree", digest: T1 },
  capabilitySet: {
    model: { provider: "faux", modelId: "faux-1" },
    extensions: ["perk.v2.report"],
    tools: ["find", "grep", "ls", "read"],
    instructionsDigest: "1".repeat(64),
    posture: "read-only",
    workspaceRoot: "subject-snapshot",
  },
};

const LATEST: ObservationRecord = {
  type: "observation",
  opId: "observation-op",
  seq: 1,
  repo: "/repo/.git",
  ref: "refs/heads/main",
  commit: "c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1",
  tree: T1,
  manifestDigest: M1,
  observedAt: 0,
};

test("validateReport accepts a valid report bound to the subject and the verified digest", () => {
  assert.deepEqual(
    validateReport({ assignment: ASSIGNMENT, latest: LATEST, report: VALID, verifiedDigest: M1 }),
    { ok: true, report: VALID },
  );
});

test("validateReport refuses each arm as invalid_report", () => {
  const cases: [string, unknown, string, string][] = [
    ["schema", { ...VALID, summary: "" }, M1, "schema"],
    ["subject mismatch", { ...VALID, subjectDigest: T2 }, M1, "subjectDigest"],
    ["malformed verified digest", VALID, M1.toUpperCase(), "verifiedDigest is not"],
    ["verified digest is not the latest manifest digest", VALID, M2, "manifest digest"],
  ];
  for (const [label, report, verifiedDigest, needle] of cases) {
    const result = validateReport({
      assignment: ASSIGNMENT,
      latest: LATEST,
      report,
      verifiedDigest,
    });
    assert.equal(result.ok, false, label);
    if (!result.ok) {
      assert.equal(result.refusal.reason, "invalid_report", label);
      assert.ok(result.refusal.detail.includes(needle), `${label}: ${result.refusal.detail}`);
    }
  }
});
