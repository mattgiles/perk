// The fixture-review rules, the operation pipeline and the six kernel properties
// (docs/design/pi-durable-v2-foundations.md §4 replay rule, §7 kernel properties, §9 refusals,
// §12 rules and their precisions). Expected action lists are literal records over ids built here
// by string templates, with the capability-set digest an independent hash of its literal
// canonical JSON. Every input is deep-frozen, so a kernel that mutates its input throws.
//
// Named states (all full, i.e. actions applied): S0 = after `start` on T1; S1 = S0 + accept a1;
// S2 = S1 + accept b1, so D(T1) is open; S3 = S2 + reply approve to D(T1), so the execution is
// completed.

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";
import type { CapabilitySet } from "./capability.ts";
import { type Coverage, coverage, type FixturePolicy } from "./fixture.ts";
import {
  type Action,
  applyActions,
  evaluateOperation,
  nextRecords,
  type Operation,
  type OperationResult,
  receiptFor,
  reconcile,
} from "./reconcile.ts";
import type { ExecutionManifest, KernelRecord, ObservationFacts } from "./records.ts";
import type { RefusalReason } from "./refusal.ts";

// ── builders ────────────────────────────────────────────────────────────────────────────────────

const E = "01HZY3V8Q2M5N7P9R1T3V5X7Z9";
const T1 = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
const T2 = "9b9a1c8e6a2b1c0d7e5f4a3b2c1d0e9f8a7b6c5d";
const C1 = "c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1";
const C1B = "c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3";
const C2 = "c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2";
const M1 = "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1";
const M2 = "a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2a2";
const REPO = "/repo/.git";
const REF = "refs/heads/main";

const CAPSET_JSON =
  '{"extensions":["perk.v2.report"],"instructionsDigest":"1111111111111111111111111111111111111111111111111111111111111111","model":{"modelId":"faux-1","provider":"faux"},"posture":"read-only","tools":["find","grep","ls","read"],"workspaceRoot":"subject-snapshot"}';
const CAPSET_DIGEST = createHash("sha256").update(CAPSET_JSON, "utf8").digest("hex");

/** The normalized capability set, as the assignment records carry it. */
const NORMALIZED: CapabilitySet = {
  model: { provider: "faux", modelId: "faux-1" },
  extensions: ["perk.v2.report"],
  tools: ["find", "grep", "ls", "read"],
  instructionsDigest: "1".repeat(64),
  posture: "read-only",
  workspaceRoot: "subject-snapshot",
};

/** The host policy: tools deliberately unsorted, so the kernel must normalize. */
const policy: FixturePolicy = {
  capabilitySet: { ...NORMALIZED, tools: ["read", "ls", "grep", "find"] },
};

function deepFreeze<T>(value: T): T {
  if (typeof value === "object" && value !== null && !Object.isFrozen(value)) {
    for (const member of Object.values(value)) deepFreeze(member);
    Object.freeze(value);
  }
  return value;
}

deepFreeze(policy);

type Role = "a" | "b";

const aid = (role: Role, tree: string) => `v2/${E}/fixture-report/${role}/${tree}/${CAPSET_DIGEST}`;
const att = (role: Role, tree: string) => `${aid(role, tree)}/1`;
const outcomeId = (role: Role, tree: string) => `${att(role, tree)}/accept-report`;
const did = (tree: string) => `v2/${E}/decision/${tree}/fixture-approval`;
const digestOf = (tree: string) => (tree === T1 ? M1 : M2);

function manifest(): ExecutionManifest {
  return {
    type: "manifest",
    recordVersion: 1,
    definitions: { "perk.v2.assignment": 1, "perk.v2.reply": 1 },
    policyVersion: 1,
    durableVersion: "1.4.0",
    chordVersion: "1.4.0",
    workspace: { repoIdentity: REPO, executionId: E },
    executionKind: "fixture-review",
    createdAt: 1_700_000_000_000,
  };
}

function facts(
  tree: string,
  commit: string,
  manifestDigest: string = digestOf(tree),
  observedAt = 1000,
): ObservationFacts {
  return { repo: REPO, ref: REF, commit, tree, manifestDigest, observedAt };
}

function report(subject: string, summary = "looks fine") {
  return { subjectDigest: subject, summary, findings: [{ path: "src/a.ts", note: "nit" }] };
}

type OperationOf<K extends Operation["type"]> = Extract<Operation, { type: K }>;

const START: OperationOf<"start"> = {
  type: "start",
  manifest: manifest(),
  observation: facts(T1, C1),
};
const STEP: Operation = { type: "step" };

function run(tree: string, commit: string): Operation {
  return { type: "run", observation: facts(tree, commit) };
}

function accept(
  role: Role,
  tree: string,
  overrides: Partial<{ report: unknown; verifiedDigest: string }> = {},
): OperationOf<"accept-report"> {
  return {
    type: "accept-report",
    attemptId: att(role, tree),
    report: report(tree),
    verifiedDigest: digestOf(tree),
    ...overrides,
  };
}

function reply(
  tree: string,
  overrides: Partial<{ action: string; actor: string; observation: ObservationFacts }> = {},
): OperationOf<"reply"> {
  return {
    type: "reply",
    decisionId: did(tree),
    action: "approve",
    actor: "human:cli",
    observation: facts(tree, tree === T1 ? C1 : C2),
    ...overrides,
  };
}

function cancel(reason = "operator stop"): Operation {
  return { type: "cancel", reason };
}

/** One kernel call over frozen inputs, and the record set after it. */
function play(records: readonly KernelRecord[], op: Operation) {
  const result = evaluateOperation(deepFreeze(records), deepFreeze(op), policy);
  return { result, records: nextRecords(records, result) };
}

/** `play`, asserting the operation was applied. */
function ok(records: readonly KernelRecord[], op: Operation) {
  const step = play(records, op);
  if (step.result.kind !== "applied")
    assert.fail(`expected applied: ${JSON.stringify(step.result)}`);
  return { result: step.result, records: step.records };
}

/** Assert `op` is refused with `reason` and records nothing; return the detail. */
function refusedWith(
  records: readonly KernelRecord[],
  op: Operation,
  reason: RefusalReason,
): string {
  const step = play(records, op);
  if (step.result.kind !== "refused")
    assert.fail(`expected refused: ${JSON.stringify(step.result)}`);
  assert.equal(step.result.refusal.reason, reason, step.result.refusal.detail);
  assert.equal(step.records, records, "nothing recorded");
  return step.result.refusal.detail;
}

/** Assert `op` replays with `receipt` and records nothing. */
function replays(records: readonly KernelRecord[], op: Operation, receipt: unknown): void {
  const step = play(records, op);
  if (step.result.kind !== "replayed")
    assert.fail(`expected replayed: ${JSON.stringify(step.result)}`);
  assert.deepEqual(step.result.receipt, receipt);
  assert.equal(step.records, records, "nothing recorded");
}

function reconcileOf(records: readonly KernelRecord[]): Action[] {
  return reconcile(deepFreeze(records), policy);
}

function coverageOfRecords(records: readonly KernelRecord[]): Coverage {
  return coverage(deepFreeze(records), policy);
}

type Step = {
  readonly before: readonly KernelRecord[];
  readonly op: Operation;
  readonly result: OperationResult;
  readonly after: readonly KernelRecord[];
};

function walk(ops: readonly Operation[], from: readonly KernelRecord[] = []): Step[] {
  const steps: Step[] = [];
  let records = from;
  for (const op of ops) {
    const { result, records: after } = play(records, op);
    steps.push({ before: records, op, result, after });
    records = after;
  }
  return steps;
}

function stepAt(steps: readonly Step[], i: number): Step {
  const step = steps[i];
  assert.ok(step !== undefined, `step ${i}`);
  return step;
}

function inputsOnly(step: Step): readonly KernelRecord[] {
  if (step.result.kind !== "applied") assert.fail("inputs-only states come from applied steps");
  return [...step.before, ...step.result.recorded];
}

// ── expected literal actions ────────────────────────────────────────────────────────────────────

function admitAction(role: Role, tree: string): Action {
  return {
    type: "admit",
    record: {
      type: "assignment",
      opId: `${aid(role, tree)}/admit`,
      assignmentId: aid(role, tree),
      kind: "fixture-report",
      role,
      subject: { kind: "git-tree", digest: tree },
      capabilitySet: NORMALIZED,
    },
  };
}

function startAction(role: Role, tree: string): Action {
  return {
    type: "start-attempt",
    record: {
      type: "attempt",
      opId: `${att(role, tree)}/submit`,
      attemptId: att(role, tree),
      assignmentId: aid(role, tree),
      ordinal: 1,
    },
  };
}

function aggregateAction(tree: string): Action {
  return {
    type: "aggregate",
    record: {
      type: "aggregate-outcome",
      opId: `v2/${E}/aggregate/${tree}`,
      subjectDigest: tree,
      outcomeIds: [outcomeId("a", tree), outcomeId("b", tree)],
    },
  };
}

function openDecisionAction(tree: string): Action {
  return {
    type: "open-decision",
    record: {
      type: "decision",
      opId: `${did(tree)}/open-decision`,
      decisionId: did(tree),
      subjectDigest: tree,
      decisionKind: "fixture-approval",
      aggregateId: `v2/${E}/aggregate/${tree}`,
      allowedActions: ["approve", "reject"],
      actor: "human:cli",
    },
  };
}

function continueAction(tree: string): Action {
  return {
    type: "continue",
    record: { type: "continuation", opId: `${did(tree)}/continuation`, decisionId: did(tree) },
  };
}

function roundOf(tree: string): Action[] {
  return [
    admitAction("a", tree),
    admitAction("b", tree),
    startAction("a", tree),
    startAction("b", tree),
  ];
}

function outcomeRecord(role: Role, tree: string, summary = "looks fine") {
  return {
    type: "report-outcome",
    opId: outcomeId(role, tree),
    attemptId: att(role, tree),
    assignmentId: aid(role, tree),
    subjectDigest: tree,
    verifiedDigest: digestOf(tree),
    report: report(tree, summary),
  };
}

// ── named states and paths ──────────────────────────────────────────────────────────────────────

const HAPPY = walk([START, accept("a", T1), accept("b", T1), reply(T1)]);
const S0 = stepAt(HAPPY, 0).after;
const S1 = stepAt(HAPPY, 1).after;
const S2 = stepAt(HAPPY, 2).after;
const S3 = stepAt(HAPPY, 3).after;

/** The fresh-round path: S2 → run T2 → accept a2 → accept b2. */
const FRESH = walk([run(T2, C2), accept("a", T2), accept("b", T2)], S2);

/** S1 → run T2 → accept a2/b2 → reply D(T2) (completed) → run T1 → accept b1. */
const SUPERSEDED_ACCEPT_OPS = [
  run(T2, C2),
  accept("a", T2),
  accept("b", T2),
  reply(T2),
  run(T1, C1B),
];
const SUPERSEDED_ACCEPT = walk(SUPERSEDED_ACCEPT_OPS, S1);
const SUPERSEDED_ACCEPT_END = stepAt(SUPERSEDED_ACCEPT, SUPERSEDED_ACCEPT.length - 1).after;

/** S2 → run T2 → accept a2/b2 → reply D(T2) (completed); then a reply to D(T1). */
const SUPERSEDED_REPLY_OPS = [run(T2, C2), accept("a", T2), accept("b", T2), reply(T2)];
const SUPERSEDED_REPLY = walk(SUPERSEDED_REPLY_OPS, S2);
const SUPERSEDED_REPLY_END = stepAt(SUPERSEDED_REPLY, SUPERSEDED_REPLY.length - 1).after;

// ── rules and pipeline ──────────────────────────────────────────────────────────────────────────

test("start records the manifest and observation 1, admits both roles and starts attempt 1 of each", () => {
  const { result } = ok([], START);
  assert.deepEqual(result.recorded, [
    manifest(),
    {
      type: "observation",
      opId: `v2/${E}/observe/1`,
      seq: 1,
      repo: REPO,
      ref: REF,
      commit: C1,
      tree: T1,
      manifestDigest: M1,
      observedAt: 1000,
    },
  ]);
  assert.deepEqual(result.actions, roundOf(T1));
  assert.equal(result.receipt, null);
});

test("accepting a emits nothing; accepting b aggregates and opens the decision", () => {
  const a = ok(S0, accept("a", T1));
  assert.deepEqual(a.result.recorded, [outcomeRecord("a", T1)]);
  assert.deepEqual(a.result.actions, []);
  assert.deepEqual(a.result.receipt, {
    opId: outcomeId("a", T1),
    record: outcomeRecord("a", T1),
    continuation: null,
  });
  const b = ok(S1, accept("b", T1));
  assert.deepEqual(b.result.actions, [aggregateAction(T1), openDecisionAction(T1)]);
});

test("a reply emits exactly one continuation, and the execution is then terminal", () => {
  const { result, records } = ok(S2, reply(T1));
  assert.deepEqual(result.actions, [continueAction(T1)]);
  assert.deepEqual(reconcileOf(records), []);
  assert.deepEqual(ok(records, run(T2, C2)).result.actions, [], "a new tree after completion");
});

test("run with the same tree and a new commit records the observation and emits nothing", () => {
  const { result } = ok(S2, run(T1, C1B));
  assert.deepEqual(result.recorded, [
    {
      type: "observation",
      opId: `v2/${E}/observe/2`,
      seq: 2,
      repo: REPO,
      ref: REF,
      commit: C1B,
      tree: T1,
      manifestDigest: M1,
      observedAt: 1000,
    },
  ]);
  assert.deepEqual(result.actions, []);
});

test("run with a new tree starts a fresh round over it", () => {
  assert.deepEqual(ok(S2, run(T2, C2)).result.actions, roundOf(T2));
});

test("start on a started execution is refused already_started", () => {
  refusedWith(S0, START, "already_started");
  refusedWith(S3, START, "already_started");
});

test("every non-start operation on an empty record set is refused invalid_input", () => {
  for (const op of [run(T1, C1), STEP, accept("a", T1), reply(T1), cancel()]) {
    refusedWith([], op, "invalid_input");
  }
});

test("an invalid observation, or one on another ref, is refused invalid_input", () => {
  refusedWith([], { ...START, observation: { ...facts(T1, C1), tree: "nope" } }, "invalid_input");
  refusedWith(
    S0,
    { type: "run", observation: { ...facts(T2, C2), commit: C2.toUpperCase() } },
    "invalid_input",
  );
  refusedWith(
    S0,
    { type: "run", observation: { ...facts(T2, C2), ref: "refs/heads/other" } },
    "invalid_input",
  );
  refusedWith(
    S0,
    { type: "run", observation: { ...facts(T2, C2), repo: "/other/.git" } },
    "invalid_input",
  );
  refusedWith(
    S2,
    reply(T1, { observation: { ...facts(T1, C1), ref: "refs/heads/other" } }),
    "invalid_input",
  );
});

test("an unknown attempt is refused invalid_input", () => {
  const detail = refusedWith(
    S0,
    { ...accept("a", T1), attemptId: `${aid("a", T1)}/2` },
    "invalid_input",
  );
  assert.ok(detail.includes(`${aid("a", T1)}/2`), detail);
  refusedWith(S0, accept("a", T2), "invalid_input");
});

test("an equal resubmission replays its receipt; a different payload is duplicate_conflict", () => {
  const accepted = ok(S0, accept("a", T1));
  replays(accepted.records, accept("a", T1), accepted.result.receipt);
  refusedWith(
    accepted.records,
    accept("a", T1, { report: report(T1, "different") }),
    "duplicate_conflict",
  );
  refusedWith(accepted.records, accept("a", T1, { verifiedDigest: M2 }), "duplicate_conflict");

  const replied = ok(S2, reply(T1));
  replays(replied.records, reply(T1), replied.result.receipt);
  refusedWith(replied.records, reply(T1, { action: "reject" }), "duplicate_conflict");

  const cancelled = ok(S0, cancel("stop"));
  replays(cancelled.records, cancel("stop"), cancelled.result.receipt);
  refusedWith(cancelled.records, cancel("another reason"), "duplicate_conflict");
});

test("text boundary: ill-formed caller text is a typed refusal, never a throw", () => {
  refusedWith(S0, accept("a", T1, { report: report(T1, "bad \uD800") }), "invalid_report");
  refusedWith(
    S0,
    accept("a", T1, { report: { ...report(T1), findings: [{ path: "a.ts", note: "\uDC00" }] } }),
    "invalid_report",
  );
  refusedWith(S0, cancel("stop \uD800"), "invalid_input");
  refusedWith(
    S0,
    { type: "run", observation: { ...facts(T2, C2), ref: "refs/heads/\uD800" } },
    "invalid_input",
  );
  refusedWith(
    [],
    { ...START, manifest: { ...manifest(), durableVersion: "1.4\uD800" } },
    "invalid_input",
  );
});

test("text boundary: replays across it — astral text replays; ill-formed text against a receipt conflicts", () => {
  const astral = ok(S0, accept("a", T1, { report: report(T1, "astral \u{1F600}") }));
  replays(
    astral.records,
    accept("a", T1, { report: report(T1, "astral \u{1F600}") }),
    astral.result.receipt,
  );
  assert.doesNotThrow(() =>
    refusedWith(S1, accept("a", T1, { report: report(T1, "bad \uD800") }), "duplicate_conflict"),
  );
  const cancelled = ok(S0, cancel()).records;
  assert.doesNotThrow(() => refusedWith(cancelled, cancel("\uD800"), "duplicate_conflict"));
});

/** A reply operation whose payload fields carry runtime values outside the declared types. */
function malformedReply(tree: string, fields: Record<string, unknown>): Operation {
  return { ...reply(tree), ...fields } as unknown as Operation;
}

test("an ill-typed reply payload is compared by the lookup first: duplicate_conflict against a receipt", () => {
  const ill = [
    { action: undefined },
    { action: 1 },
    { actor: 42 },
    { actor: 1n },
    { action: null },
  ];
  for (const fields of ill) {
    assert.doesNotThrow(() => refusedWith(S3, malformedReply(T1, fields), "duplicate_conflict"));
    // Without a receipt the same payload is an identity refusal, after the decision lookup.
    refusedWith(S2, malformedReply(T1, fields), "invalid_input");
    refusedWith(S2, malformedReply(T2, fields), "unknown_decision");
  }
  // The decision id names the operation, so an ill-typed one is refused before any lookup.
  refusedWith(S3, malformedReply(T1, { decisionId: 7 }), "invalid_input");
});

test("superseded is reachable: an accept after the execution consumed a decision", () => {
  assert.ok(SUPERSEDED_ACCEPT.every((step) => step.result.kind === "applied"));
  assert.deepEqual(stepAt(SUPERSEDED_ACCEPT, 4).result, {
    kind: "applied",
    recorded: [
      {
        type: "observation",
        opId: `v2/${E}/observe/4`,
        seq: 4,
        repo: REPO,
        ref: REF,
        commit: C1B,
        tree: T1,
        manifestDigest: M1,
        observedAt: 1000,
      },
    ],
    actions: [],
    receipt: null,
  });
  refusedWith(SUPERSEDED_ACCEPT_END, accept("b", T1), "superseded");
});

test("superseded is reachable: a reply to an earlier decision after another was consumed", () => {
  assert.ok(SUPERSEDED_REPLY.every((step) => step.result.kind === "applied"));
  refusedWith(SUPERSEDED_REPLY_END, reply(T1), "superseded");
});

test("precedence: unknown_decision beats cancelled; a bad action beats stale_subject", () => {
  refusedWith(ok(S0, cancel()).records, reply(T1), "unknown_decision");
  refusedWith(S2, reply(T1, { action: "maybe", observation: facts(T2, C2) }), "invalid_input");
  refusedWith(S2, reply(T1, { actor: "human:web", observation: facts(T2, C2) }), "invalid_input");
});

test("precedence: stale_subject beats cancelled, for accept and reply", () => {
  const ranT2 = ok(S1, run(T2, C2)).records;
  refusedWith(ok(ranT2, cancel()).records, accept("b", T1), "stale_subject");
  refusedWith(ok(S2, cancel()).records, reply(T1, { observation: facts(T2, C2) }), "stale_subject");
});

test("precedence: cancelled beats superseded, for accept and reply", () => {
  refusedWith(ok(SUPERSEDED_ACCEPT_END, cancel()).records, accept("b", T1), "cancelled");
  refusedWith(ok(SUPERSEDED_REPLY_END, cancel()).records, reply(T1), "cancelled");
});

test("precedence: superseded beats invalid_report", () => {
  refusedWith(SUPERSEDED_ACCEPT_END, accept("b", T1, { report: { summary: "" } }), "superseded");
});

test("precedence: the receipt beats every check — after cancel, a tree change and completion", () => {
  const acceptReceipt = ok(S0, accept("a", T1)).result.receipt;
  replays(ok(S1, cancel()).records, accept("a", T1), acceptReceipt);
  replays(ok(S1, run(T2, C2)).records, accept("a", T1), acceptReceipt);
  replays(S3, accept("a", T1), acceptReceipt);
  replays(SUPERSEDED_ACCEPT_END, accept("a", T1), acceptReceipt);

  const replyReceipt = ok(S2, reply(T1)).result.receipt;
  replays(S3, reply(T1), replyReceipt);
  replays(ok(S3, cancel()).records, reply(T1), replyReceipt);
  replays(ok(S3, run(T2, C2)).records, reply(T1, { observation: facts(T2, C2) }), replyReceipt);
});

// ── consistency and replayability ───────────────────────────────────────────────────────────────

const CANCEL_PATHS = [walk([cancel()], S0), walk([cancel()], S2), walk([cancel()], S3)];

const SWEEP: readonly Step[] = [
  ...HAPPY,
  ...FRESH,
  ...SUPERSEDED_ACCEPT,
  ...SUPERSEDED_REPLY,
  ...walk([run(T1, C1B)], S2),
  ...CANCEL_PATHS.flat(),
];

test("every applied result's actions are reconcile over its inputs, and its receipt replays", () => {
  let applied = 0;
  let replayed = 0;
  for (const step of SWEEP) {
    if (step.result.kind !== "applied") continue;
    applied++;
    assert.deepEqual(step.result.actions, reconcileOf([...step.before, ...step.result.recorded]));
    assert.deepEqual(step.after, nextRecords(step.before, step.result));
    if (step.op.type === "accept-report" || step.op.type === "reply" || step.op.type === "cancel") {
      replays(step.after, step.op, step.result.receipt);
      replayed++;
    } else {
      assert.equal(step.result.receipt, null);
    }
  }
  assert.ok(applied >= 20 && replayed >= 10, `swept ${applied} applied, ${replayed} replayed`);
});

// ── the six kernel properties (§7) ──────────────────────────────────────────────────────────────

type SweptState = {
  readonly label: string;
  readonly records: readonly KernelRecord[];
  readonly next: Operation;
};

function sweptStates(steps: readonly Step[], label: string): SweptState[] {
  const states: SweptState[] = [];
  steps.forEach((step, i) => {
    const next = steps[i + 1]?.op ?? STEP;
    states.push({ label: `${label} full ${i}`, records: step.after, next });
    if (step.result.kind === "applied") {
      states.push({ label: `${label} inputs-only ${i}`, records: inputsOnly(step), next });
    }
  });
  return states;
}

const K_STATES: readonly SweptState[] = [
  ...sweptStates(HAPPY, "happy"),
  ...sweptStates(FRESH, "fresh"),
];

function permutations(records: readonly KernelRecord[]): (readonly KernelRecord[])[] {
  const reversed = records.toReversed();
  return [
    records,
    reversed,
    [...records.slice(1), ...records.slice(0, 1)],
    JSON.parse(JSON.stringify(reversed)),
  ];
}

test("K1 determinism: reconcile, coverage and the next operation ignore record order", () => {
  const twoAssignments = K_STATES.filter(
    (state) => state.records.filter((record) => record.type === "assignment").length >= 2,
  );
  assert.ok(twoAssignments.length >= K_STATES.length - 1, "the permutations discriminate");
  for (const state of K_STATES) {
    const expected = {
      actions: reconcileOf(state.records),
      coverage: coverageOfRecords(state.records),
      result: evaluateOperation(state.records, state.next, policy),
    };
    for (const records of permutations(state.records)) {
      const frozen = deepFreeze(records);
      assert.deepEqual(
        {
          actions: reconcileOf(frozen),
          coverage: coverageOfRecords(frozen),
          result: evaluateOperation(frozen, state.next, policy),
        },
        expected,
        state.label,
      );
    }
    assert.deepEqual(reconcileOf(state.records), expected.actions, `${state.label}: a second call`);
    assert.deepEqual(
      evaluateOperation(state.records, state.next, policy),
      expected.result,
      `${state.label}: a second call`,
    );
    for (const value of [...state.records, ...expected.actions]) {
      assert.deepEqual(JSON.parse(JSON.stringify(value)), value, `${state.label}: JSON round trip`);
    }
  }
});

test("K2 idempotence: full states reconcile to nothing; applying an inputs-only state's actions converges", () => {
  const full = [S0, S1, S2, S3, ...FRESH.map((step) => step.after)];
  for (const records of full) {
    assert.deepEqual(reconcileOf(records), []);
    assert.deepEqual(play(records, STEP).result, {
      kind: "applied",
      recorded: [],
      actions: [],
      receipt: null,
    });
  }
  for (const step of [...HAPPY, ...FRESH]) {
    if (step.result.kind !== "applied") continue;
    const inputs = inputsOnly(step);
    const actions = reconcileOf(inputs);
    assert.deepEqual(actions, step.result.actions);
    assert.deepEqual(reconcileOf(applyActions(inputs, actions)), []);
  }
  // Non-vacuity: these inputs-only states have pending actions.
  for (const step of [
    stepAt(HAPPY, 0),
    stepAt(HAPPY, 2),
    stepAt(HAPPY, 3),
    stepAt(FRESH, 0),
    stepAt(FRESH, 2),
  ]) {
    assert.ok(reconcileOf(inputsOnly(step)).length > 0, `pending actions after ${step.op.type}`);
  }
});

test("K3 cancellation dominance: reconcile is silenced, admission refused, coverage unchanged", () => {
  const pendingInputs = [inputsOnly(stepAt(HAPPY, 0)), inputsOnly(stepAt(HAPPY, 2))];
  for (const records of [S0, S1, S2, ...pendingInputs]) {
    const cancelled = ok(records, cancel());
    assert.deepEqual(cancelled.result.actions, []);
    assert.deepEqual(reconcileOf(cancelled.records), []);
    const ran = ok(cancelled.records, run(T2, C2));
    assert.equal(ran.result.recorded.length, 1);
    assert.equal(ran.result.recorded[0]?.type, "observation");
    assert.deepEqual(ran.result.actions, []);
  }
  refusedWith(ok(S0, cancel()).records, accept("a", T1), "cancelled");
  refusedWith(ok(S1, cancel()).records, accept("b", T1), "cancelled");
  refusedWith(ok(S2, cancel()).records, reply(T1), "cancelled");
  for (const records of [S0, S1, S2]) {
    assert.deepEqual(coverageOfRecords(ok(records, cancel()).records), coverageOfRecords(records));
  }
  // Controls: without the cancel, the same states act and the same admissions succeed.
  for (const records of pendingInputs) assert.ok(reconcileOf(records).length > 0);
  for (const records of [S0, S1, S2]) {
    assert.deepEqual(ok(records, run(T2, C2)).result.actions, roundOf(T2));
  }
  ok(S0, accept("a", T1));
  ok(S1, accept("b", T1));
  ok(S2, reply(T1));
});

test("K4 stale-subject refusal: a reply or accept over an earlier tree is refused, a same-tree commit is not", () => {
  refusedWith(S2, reply(T1, { observation: facts(T2, C2) }), "stale_subject");
  const observed = S2.filter((record) => record.type === "observation").length;
  assert.deepEqual(ok(S2, run(T1, C1B)).result.recorded[0], {
    type: "observation",
    opId: `v2/${E}/observe/${observed + 1}`,
    seq: observed + 1,
    repo: REPO,
    ref: REF,
    commit: C1B,
    tree: T1,
    manifestDigest: M1,
    observedAt: 1000,
  });

  const ranT2 = ok(S1, run(T2, C2)).records;
  refusedWith(ranT2, accept("b", T1, { verifiedDigest: M2 }), "stale_subject");
  refusedWith(ranT2, accept("b", T1), "stale_subject");
  const t2 = coverageOfRecords(ranT2);
  assert.equal(t2.subjectDigest, T2);
  assert.deepEqual(
    t2.roles.map((role) => [
      role.role,
      role.assignmentId,
      role.admitted,
      role.attempts,
      role.acceptedOutcomeId,
    ]),
    [
      ["a", aid("a", T2), true, 1, null],
      ["b", aid("b", T2), true, 1, null],
    ],
  );

  // Controls: a same-tree, new-commit reply succeeds; accepting b1 without the T2 run succeeds.
  assert.deepEqual(ok(S2, reply(T1, { observation: facts(T1, C1B) })).result.actions, [
    continueAction(T1),
  ]);
  ok(S1, accept("b", T1));
});

test("K5 incomplete coverage stays visible", () => {
  const expected: Coverage = {
    subjectDigest: T1,
    roles: [
      {
        role: "a",
        assignmentId: aid("a", T1),
        admitted: true,
        attempts: 1,
        acceptedOutcomeId: outcomeId("a", T1),
      },
      {
        role: "b",
        assignmentId: aid("b", T1),
        admitted: true,
        attempts: 1,
        acceptedOutcomeId: null,
      },
    ],
    complete: false,
  };
  assert.deepEqual(coverageOfRecords(S1), expected);
  assert.deepEqual(reconcileOf(S1), []);
  for (const op of [
    accept("b", T1, { report: { ...report(T1), extra: true } }),
    accept("b", T1, { report: report(T2) }),
    accept("b", T1, { verifiedDigest: M2 }),
  ]) {
    refusedWith(S1, op, "invalid_report");
    assert.deepEqual(coverageOfRecords(S1), expected);
  }
  assert.deepEqual(ok(S1, accept("b", T1)).result.actions, [
    aggregateAction(T1),
    openDecisionAction(T1),
  ]);
  assert.equal(coverageOfRecords(S2).complete, true);
});

test("K6 one reply → exactly one continuation", () => {
  const { result, records } = ok(S2, reply(T1));
  const observed = S2.filter((record) => record.type === "observation").length;
  assert.deepEqual(result.recorded, [
    {
      type: "observation",
      opId: `v2/${E}/observe/${observed + 1}`,
      seq: observed + 1,
      repo: REPO,
      ref: REF,
      commit: C1,
      tree: T1,
      manifestDigest: M1,
      observedAt: 1000,
    },
    {
      type: "reply",
      opId: `${did(T1)}/reply`,
      decisionId: did(T1),
      action: "approve",
      actor: "human:cli",
    },
  ]);
  assert.deepEqual(result.actions, [continueAction(T1)]);
  assert.deepEqual(result.receipt?.continuation, continueAction(T1).record);
  assert.deepEqual(reconcileOf(records), []);
  replays(records, reply(T1), result.receipt);
  replays(ok(records, cancel()).records, reply(T1), result.receipt);
  replays(
    ok(records, run(T2, C2)).records,
    reply(T1, { observation: facts(T2, C2) }),
    result.receipt,
  );
  refusedWith(records, reply(T1, { action: "reject" }), "duplicate_conflict");
  assert.deepEqual(receiptFor(records, `${did(T1)}/reply`), result.receipt);
});
