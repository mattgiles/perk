// The shared approval-gate matrix — owned ONCE here, for every `saveThroughApprovalGate` caller
// (gistApprovalSave / planApprovalSave / objectiveApprovalSave): the snapshot-before-save
// ordering, the success-only exit, and the untouched-gate failure arms. Feature policy (draft
// resolution, save unions, outcome mapping) stays pinned in each feature's own suite.

import assert from "node:assert/strict";
import { test } from "node:test";
import { type ApprovalGate, saveThroughApprovalGate } from "./approvalGate.ts";

function fakeGate(active: boolean): ApprovalGate & { exits: number } {
  return {
    exits: 0,
    isActive() {
      return active;
    },
    exit() {
      this.exits += 1;
      active = false;
    },
  };
}

const SAVED = { status: "saved", id: "7" } as const;
const FAILED = { status: "failed", message: "backend exploded" } as const;

test("a successful save while read-only exits the gate once and reports gateExited", async () => {
  const gate = fakeGate(true);
  const result = await saveThroughApprovalGate(gate, async () => SAVED);
  assert.deepEqual(result, { outcome: SAVED, gateExited: true });
  assert.equal(gate.exits, 1, "exactly one exit");
});

test("a successful save while already read-write never exits the gate", async () => {
  const gate = fakeGate(false);
  const result = await saveThroughApprovalGate(gate, async () => SAVED);
  assert.deepEqual(result, { outcome: SAVED, gateExited: false });
  assert.equal(gate.exits, 0);
});

test("a failed save leaves the gate untouched", async () => {
  const gate = fakeGate(true);
  const result = await saveThroughApprovalGate(gate, async () => FAILED);
  assert.deepEqual(result, { outcome: FAILED, gateExited: false });
  assert.equal(gate.exits, 0, "the gate stays ON for the retry");
});

test("the snapshot governs: isActive flipping false DURING the save still exits", async () => {
  // The invariant is snapshot-BEFORE-save — a concurrent gate transition during the backend
  // write must not swallow the read-only → read-write boundary the save marks.
  let active = true;
  const gate = {
    exits: 0,
    isActive: () => active,
    exit() {
      this.exits += 1;
    },
  };
  const result = await saveThroughApprovalGate(gate, async () => {
    active = false;
    return SAVED;
  });
  assert.equal(result.gateExited, true, "the pre-save snapshot wins");
  assert.equal(gate.exits, 1);
});

test("a throwing save propagates with zero exit() calls", async () => {
  const gate = fakeGate(true);
  await assert.rejects(
    saveThroughApprovalGate(gate, async (): Promise<typeof SAVED> => {
      throw new Error("backend threw");
    }),
    /backend threw/,
  );
  assert.equal(gate.exits, 0, "a thrown save leaves the gate untouched");
});
