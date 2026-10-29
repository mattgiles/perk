// The identity grammar (docs/design/pi-durable-v2-foundations.md §4): every derivation and op-id
// helper against a fully literal expected string, the closed op-kind and reserved-kind lists, and
// the RangeError on every malformed part.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  acceptReportOpId,
  admitOpId,
  aggregateOpId,
  cancelOpId,
  continuationOpId,
  deriveAssignmentId,
  deriveAttemptId,
  deriveDecisionId,
  executionScopeId,
  isAssignmentId,
  isExecutionId,
  isGitOid,
  isSha256Hex,
  isSlug,
  launchOpId,
  OP_KINDS,
  observeOpId,
  openDecisionOpId,
  RESERVED_ASSIGNMENT_KINDS,
  replyOpId,
  submitOpId,
} from "./identity.ts";

const E = "01HZY3V8Q2M5N7P9R1T3V5X7Z9";
const TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
const TREE64 = "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321";
const CAPSET = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0";

const ASSIGNMENT =
  "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/fixture-report/a/4b825dc642cb6eb9a060e54bf8d69288fbee4904/0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0";

test("the op kinds and the reserved assignment kinds are the §4 lists", () => {
  assert.deepEqual(OP_KINDS, [
    "observe",
    "admit",
    "submit",
    "launch",
    "accept-report",
    "aggregate",
    "open-decision",
    "reply",
    "continuation",
    "cancel",
  ]);
  assert.deepEqual(RESERVED_ASSIGNMENT_KINDS, ["decision", "observe", "aggregate", "cancel"]);
  // An op kind starts with a letter, so it never collides with an attempt ordinal (all digits).
  for (const kind of OP_KINDS) assert.match(kind, /^[a-z]/, kind);
});

test("every derivation renders the pinned grammar", () => {
  assert.equal(executionScopeId(E), "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9");
  assert.equal(
    deriveAssignmentId({
      executionId: E,
      kind: "fixture-report",
      role: "a",
      subjectDigest: TREE,
      capabilitySetDigest: CAPSET,
    }),
    ASSIGNMENT,
  );
  assert.equal(
    deriveAssignmentId({
      executionId: E,
      kind: "k2",
      role: "role-b",
      subjectDigest: TREE64,
      capabilitySetDigest: CAPSET,
    }),
    "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/k2/role-b/6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321/0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0",
  );
  assert.equal(
    deriveAttemptId(ASSIGNMENT, 1),
    "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/fixture-report/a/4b825dc642cb6eb9a060e54bf8d69288fbee4904/0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0/1",
  );
  assert.equal(deriveAttemptId(ASSIGNMENT, 12).endsWith("e1f0/12"), true);
  assert.equal(
    deriveDecisionId({ executionId: E, subjectDigest: TREE, decisionKind: "fixture-approval" }),
    "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/decision/4b825dc642cb6eb9a060e54bf8d69288fbee4904/fixture-approval",
  );
});

test("every op-id helper renders its scope and kind", () => {
  const attempt = `${ASSIGNMENT}/1`;
  const decision =
    "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/decision/4b825dc642cb6eb9a060e54bf8d69288fbee4904/fixture-approval";
  assert.equal(observeOpId(E, 3), "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/observe/3");
  assert.equal(
    admitOpId(ASSIGNMENT),
    "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/fixture-report/a/4b825dc642cb6eb9a060e54bf8d69288fbee4904/0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0/admit",
  );
  assert.equal(
    submitOpId(attempt),
    "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/fixture-report/a/4b825dc642cb6eb9a060e54bf8d69288fbee4904/0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0/1/submit",
  );
  assert.equal(
    launchOpId(attempt),
    "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/fixture-report/a/4b825dc642cb6eb9a060e54bf8d69288fbee4904/0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0/1/launch",
  );
  assert.equal(
    acceptReportOpId(attempt),
    "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/fixture-report/a/4b825dc642cb6eb9a060e54bf8d69288fbee4904/0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0/1/accept-report",
  );
  assert.equal(
    aggregateOpId(E, TREE),
    "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/aggregate/4b825dc642cb6eb9a060e54bf8d69288fbee4904",
  );
  assert.equal(
    openDecisionOpId(decision),
    "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/decision/4b825dc642cb6eb9a060e54bf8d69288fbee4904/fixture-approval/open-decision",
  );
  assert.equal(
    replyOpId(decision),
    "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/decision/4b825dc642cb6eb9a060e54bf8d69288fbee4904/fixture-approval/reply",
  );
  assert.equal(
    continuationOpId(decision),
    "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/decision/4b825dc642cb6eb9a060e54bf8d69288fbee4904/fixture-approval/continuation",
  );
  assert.equal(cancelOpId(E), "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/cancel");
});

test("the predicates accept the grammar and reject near misses", () => {
  assert.equal(isSlug("fixture-report"), true);
  assert.equal(isSlug("a1"), true);
  for (const bad of ["", "1a", "A", "-a", "a_b", "a b"]) assert.equal(isSlug(bad), false, bad);
  assert.equal(isExecutionId(E), true);
  assert.equal(isGitOid(TREE), true);
  assert.equal(isGitOid(TREE64), true);
  assert.equal(isGitOid(TREE.toUpperCase()), false);
  assert.equal(isGitOid(TREE.slice(1)), false);
  assert.equal(isSha256Hex(CAPSET), true);
  assert.equal(isSha256Hex(TREE), false);
  assert.equal(isAssignmentId(ASSIGNMENT), true);
  assert.equal(isAssignmentId(`${ASSIGNMENT}/1`), false);
  assert.equal(isAssignmentId(ASSIGNMENT.replace("fixture-report", "decision")), false);
});

test("a malformed part throws RangeError", () => {
  const assignment = (overrides: Partial<Parameters<typeof deriveAssignmentId>[0]>) =>
    deriveAssignmentId({
      executionId: E,
      kind: "fixture-report",
      role: "a",
      subjectDigest: TREE,
      capabilitySetDigest: CAPSET,
      ...overrides,
    });
  const badIds = [
    E.toLowerCase(),
    E.slice(1),
    `${E.slice(0, 25)}I`,
    `${E.slice(0, 25)}L`,
    `${E.slice(0, 25)}O`,
    `${E.slice(0, 25)}U`,
  ];
  for (const id of badIds) {
    assert.throws(() => executionScopeId(id), RangeError, id);
    assert.throws(() => assignment({ executionId: id }), RangeError, id);
    assert.throws(() => cancelOpId(id), RangeError, id);
    assert.throws(() => observeOpId(id, 1), RangeError, id);
  }
  for (const digest of [TREE.toUpperCase(), TREE.slice(2)]) {
    assert.throws(() => assignment({ subjectDigest: digest }), RangeError, digest);
    assert.throws(
      () => deriveDecisionId({ executionId: E, subjectDigest: digest, decisionKind: "k" }),
      RangeError,
    );
    assert.throws(() => aggregateOpId(E, digest), RangeError);
  }
  assert.throws(() => assignment({ capabilitySetDigest: CAPSET.toUpperCase() }), RangeError);
  assert.throws(() => assignment({ capabilitySetDigest: TREE }), RangeError);
  assert.throws(() => assignment({ kind: "Fixture" }), RangeError);
  assert.throws(() => assignment({ role: "a/b" }), RangeError);
  for (const kind of RESERVED_ASSIGNMENT_KINDS) {
    assert.throws(() => assignment({ kind }), RangeError, kind);
  }
  assert.throws(
    () => deriveDecisionId({ executionId: E, subjectDigest: TREE, decisionKind: "Approval" }),
    RangeError,
  );
  for (const ordinal of [0, -1, 1.5, Number.NaN]) {
    assert.throws(() => deriveAttemptId(ASSIGNMENT, ordinal), RangeError, String(ordinal));
    assert.throws(() => observeOpId(E, ordinal), RangeError, String(ordinal));
  }
  assert.throws(() => deriveAttemptId(`${ASSIGNMENT}/x`, 1), RangeError);
});
