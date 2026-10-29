// The v2 document census and the key-shape lookups (docs/design/pi-durable-v2-foundations.md §6
// record tiers, record keys and record presentation; §10 the manifest's definitions). Every token
// is a session-scoped `perk.v2.*` definition at version 1 that checkpoints on every write; both
// family lookups are total over their closed domains; `opKindOf` round-trips every kernel op-id
// helper over really derived ids; and the catalog and the definitions name exactly the binding's.

import assert from "node:assert/strict";
import { test } from "node:test";
import { FIXTURE_DECISION_KIND, roleAssignmentId } from "../kernel/fixture.ts";
import {
  acceptReportOpId,
  admitOpId,
  aggregateOpId,
  cancelOpId,
  continuationOpId,
  deriveAttemptId,
  deriveDecisionId,
  launchOpId,
  OP_KINDS,
  type OpKind,
  observeOpId,
  openDecisionOpId,
  replyOpId,
  submitOpId,
} from "../kernel/identity.ts";
import {
  CatalogDoc,
  emptyCatalog,
  familyForOpKind,
  familyForRecordType,
  opKindOf,
  V2_DOCUMENTS,
} from "./documents.ts";
import { bindingDefinitions } from "./tasks.ts";

const E = "01HZY3V8Q2M5N7P9R1T3V5X7Z9";
const TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
const POLICY = {
  capabilitySet: {
    model: { provider: "faux", modelId: "faux-1" },
    extensions: ["perk.v2.report"],
    tools: ["read"],
    instructionsDigest: "1".repeat(64),
    posture: "read-only",
    workspaceRoot: "subject-snapshot",
  },
} as const;

const FAMILY_KINDS = [
  "perk.v2.observation",
  "perk.v2.assignment",
  "perk.v2.attempt",
  "perk.v2.outcome",
  "perk.v2.decision",
  "perk.v2.reply",
  "perk.v2.cancellation",
  "perk.v2.durable-map",
];

test("every v2 document is a session-scoped perk.v2.* definition at version 1 that checkpoints on every write", () => {
  assert.deepEqual(
    V2_DOCUMENTS.map((token) => token.definition.kind),
    ["perk.v2.manifest", "perk.v2.catalog", ...FAMILY_KINDS],
  );
  for (const token of V2_DOCUMENTS) {
    const { kind, scope, version } = token.definition;
    assert.ok(kind.startsWith("perk.v2."), kind);
    assert.equal(scope, "session", kind);
    assert.equal(version, 1, kind);
    assert.equal(
      token.definition.checkpointWhen(emptyCatalog(), [], { deltasSinceBase: 0 }),
      true,
      kind,
    );
    const family = Reflect.get(token.definition, "family");
    assert.equal(
      family,
      kind === "perk.v2.manifest" || kind === "perk.v2.catalog" ? undefined : true,
      kind,
    );
  }
});

test("the family lookups are total: every record type but continuation, and every op kind", () => {
  const byType = {
    observation: "perk.v2.observation",
    assignment: "perk.v2.assignment",
    attempt: "perk.v2.attempt",
    "report-outcome": "perk.v2.outcome",
    "aggregate-outcome": "perk.v2.outcome",
    decision: "perk.v2.decision",
    reply: "perk.v2.reply",
    cancellation: "perk.v2.cancellation",
  } as const;
  for (const [type, kind] of Object.entries(byType)) {
    assert.equal(familyForRecordType(type as keyof typeof byType).definition.kind, kind, type);
  }
  const byKind: Record<OpKind, string> = {
    observe: "perk.v2.observation",
    admit: "perk.v2.assignment",
    submit: "perk.v2.attempt",
    launch: "perk.v2.durable-map",
    "accept-report": "perk.v2.outcome",
    aggregate: "perk.v2.outcome",
    "open-decision": "perk.v2.decision",
    reply: "perk.v2.reply",
    continuation: "perk.v2.durable-map",
    cancel: "perk.v2.cancellation",
  };
  assert.deepEqual(
    Object.keys(byKind).sort(),
    [...OP_KINDS].sort(),
    "the table covers every op kind",
  );
  for (const kind of OP_KINDS)
    assert.equal(familyForOpKind(kind).definition.kind, byKind[kind], kind);
});

test("opKindOf round-trips every op-id helper over derived ids, and garbage misses", () => {
  const assignment = roleAssignmentId(E, "a", TREE, POLICY);
  const attempt = deriveAttemptId(assignment, 1);
  const decision = deriveDecisionId({
    executionId: E,
    subjectDigest: TREE,
    decisionKind: FIXTURE_DECISION_KIND,
  });
  const cases: [string, OpKind][] = [
    [observeOpId(E, 1), "observe"],
    [observeOpId(E, 12), "observe"],
    [admitOpId(assignment), "admit"],
    [submitOpId(attempt), "submit"],
    [launchOpId(attempt), "launch"],
    [acceptReportOpId(attempt), "accept-report"],
    [aggregateOpId(E, TREE), "aggregate"],
    [openDecisionOpId(decision), "open-decision"],
    [replyOpId(decision), "reply"],
    [continuationOpId(decision), "continuation"],
    [cancelOpId(E), "cancel"],
  ];
  assert.deepEqual(
    [...new Set(cases.map(([, kind]) => kind))].sort(),
    [...OP_KINDS].sort(),
    "every op kind has a case",
  );
  for (const [opId, kind] of cases) assert.equal(opKindOf(opId), kind, opId);
  for (const garbage of [
    "",
    "garbage",
    "v2",
    `v2/${E}`,
    assignment,
    attempt,
    decision,
    `${attempt}/admit-x`,
  ]) {
    assert.equal(opKindOf(garbage), null, garbage);
  }
});

test("an empty catalog lists exactly the eight family kinds, with no manifest", () => {
  const catalog = emptyCatalog();
  assert.deepEqual(catalog, {
    manifest: false,
    members: Object.fromEntries(FAMILY_KINDS.map((kind) => [kind, []])),
  });
  assert.deepEqual(CatalogDoc.definition.initial(), catalog, "the catalog token starts empty");
  assert.notEqual(emptyCatalog().members, catalog.members, "each catalog is a fresh value");
});

test("the binding's definitions are exactly the ten documents and the two tasks, at version 1", () => {
  assert.deepEqual(bindingDefinitions(), {
    "perk.v2.manifest": 1,
    "perk.v2.catalog": 1,
    "perk.v2.observation": 1,
    "perk.v2.assignment": 1,
    "perk.v2.attempt": 1,
    "perk.v2.outcome": 1,
    "perk.v2.decision": 1,
    "perk.v2.reply": 1,
    "perk.v2.cancellation": 1,
    "perk.v2.durable-map": 1,
    "perk.v2.step": 1,
    "perk.v2.continuation": 1,
  });
});
