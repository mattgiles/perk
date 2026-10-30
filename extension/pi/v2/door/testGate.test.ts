// G5 — the test gate (docs/design/pi-durable-v2-foundations.md §11 and §16, contracts.md §8.77): the
// environment parse fails closed, the host line is written on creation, verify lines are logged in
// call order before any hold, a hold blocks exactly the n-th verification of its point until its
// file is removed, and the host CLI's deps reach the fixture program's verifications.

import assert from "node:assert/strict";
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { setTimeout as sleep } from "node:timers/promises";
import type { VerifyPoint } from "../durable/assignment.ts";
import { doorTarget } from "../testing/door.ts";
import { CASE_TIMEOUT_MS, tempDir } from "../testing/durable.ts";
import { GATE_LOG, holdFile, TEST_GATE_ENV, testGate, testGateFromEnv } from "./testGate.ts";

const TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
const POLL_MS = 5;

function logOf(dir: string): string {
  return readFileSync(join(dir, GATE_LOG), "utf8");
}

/** Whether `promise` is still pending after `ms`. */
async function pendingAfter(promise: Promise<unknown>, ms: number): Promise<boolean> {
  const marker = Symbol("pending");
  const winner = await Promise.race([promise, sleep(ms).then(() => marker)]);
  return winner === marker;
}

test("G5 (env): unset or empty is no gate; anything but an existing absolute directory throws", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  assert.equal(testGateFromEnv({}), undefined);
  assert.equal(testGateFromEnv({ [TEST_GATE_ENV]: "" }), undefined);
  const dir = await tempDir(t, "perk-v2-gate-");
  const file = join(dir, "file");
  writeFileSync(file, "");
  for (const value of ["relative/gate", join(dir, "missing"), file]) {
    assert.throws(
      () => testGateFromEnv({ [TEST_GATE_ENV]: value }),
      (error: unknown) => error instanceof Error && error.message.includes(TEST_GATE_ENV),
      value,
    );
  }
  const gate = testGateFromEnv({ [TEST_GATE_ENV]: dir });
  assert.equal(typeof gate, "function");
  const [first] = logOf(dir).split("\n");
  assert.match(first ?? "", new RegExp(`^host ${process.pid} (?:[0-9]+|-)$`));
});

test("G5 (host line): the gate announces its host on creation, before any call", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const known = await tempDir(t, "perk-v2-gate-");
  testGate(known, { pid: 4242, startTime: "777" });
  assert.equal(logOf(known), "host 4242 777\n");
  const unknown = await tempDir(t, "perk-v2-gate-");
  testGate(unknown, { pid: 4242, startTime: null });
  assert.equal(logOf(unknown), "host 4242 -\n");
});

test("G5 (log and hold): verify lines in call order, and a hold blocks only its point's n-th call", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const dir = await tempDir(t, "perk-v2-gate-");
  const gate = testGate(dir, { pid: 4242, startTime: "1", pollMs: POLL_MS });
  const hold = join(dir, holdFile("acceptance", 2));
  writeFileSync(hold, "");
  await gate("attempt-start", "t1");
  await gate("acceptance", "t2");
  const second = gate("acceptance", "t3");
  assert.ok(await pendingAfter(second, POLL_MS * 20), "the second acceptance is held");
  assert.equal(
    logOf(dir),
    "host 4242 1\nattempt-start 4242 t1\nacceptance 4242 t2\nacceptance 4242 t3\n",
    "the held call's line is already logged",
  );
  rmSync(hold);
  await second;
  await gate("settle", TREE);
  assert.ok(logOf(dir).endsWith(`settle 4242 ${TREE}\n`));

  // Ordinals count per point: two attempt-start calls leave the first acceptance the first.
  const other = await tempDir(t, "perk-v2-gate-");
  const ordinal = testGate(other, { pid: 4242, startTime: "1", pollMs: POLL_MS });
  const first = join(other, holdFile("acceptance", 1));
  writeFileSync(first, "");
  await ordinal("attempt-start", "t1");
  await ordinal("attempt-start", "t1");
  const held = ordinal("acceptance", "t1");
  assert.ok(await pendingAfter(held, POLL_MS * 20), "the first acceptance is held");
  rmSync(first);
  await held;
  assert.equal(
    logOf(other),
    "host 4242 1\nattempt-start 4242 t1\nattempt-start 4242 t1\nacceptance 4242 t1\n",
  );
});

test("G5 (composition): the host CLI's onVerify reaches every verification of a start", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const seen: [VerifyPoint, string][] = [];
  const target = await doorTarget(t, {
    onVerify: (point, tree) => {
      seen.push([point, tree]);
    },
  });
  const started = await target.envelope("start", target.startOptions);
  assert.equal(started.outcome, "pending_decision", JSON.stringify(started));
  assert.ok(
    seen.every(([, tree]) => tree === target.tree),
    "every verification is over the fixture tree",
  );
  const count = (point: VerifyPoint): number => seen.filter(([p]) => p === point).length;
  assert.deepEqual(
    {
      "attempt-start": count("attempt-start"),
      acceptance: count("acceptance"),
      settle: count("settle"),
    },
    { "attempt-start": 2, acceptance: 2, settle: 2 },
  );
  assert.equal(seen.length, 6);
});
