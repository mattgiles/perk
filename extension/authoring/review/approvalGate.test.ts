// The shared approval-gate matrix — owned ONCE here, for every `saveThroughApprovalGate` caller
// (gistApprovalSave / planApprovalSave / objectiveApprovalSave): the snapshot-before-save
// ordering, the success-only exit, and the untouched-gate failure arms. Feature policy (draft
// resolution, save unions, outcome mapping) stays pinned in each feature's own suite.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { GateTransition } from "../../substrate/toolPolicy.ts";
import { type ApprovalGate, saveThroughApprovalGate } from "./approvalGate.ts";

const APPLIED_RELEASE: GateTransition = {
  status: "applied",
  requested: "read-write",
  access: "read-write",
};

function fakeGate(
  active: boolean,
  release: GateTransition = APPLIED_RELEASE,
): ApprovalGate & { exits: number } {
  return {
    exits: 0,
    isActive() {
      return active;
    },
    exit() {
      this.exits += 1;
      active = release.access === "read-only";
      return release;
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
    exit(): GateTransition {
      this.exits += 1;
      return APPLIED_RELEASE;
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

// gateExited is earned: only an applied read-write release reports it; every held release leaves
// it false while the saved outcome still returns, with exactly one exit() call either way.
const HELD_RELEASES: readonly [string, GateTransition][] = [
  [
    "restricted (the runner floor)",
    { status: "restricted", requested: "read-write", access: "read-only" },
  ],
  [
    "failed persist",
    {
      status: "failed",
      requested: "read-write",
      access: "read-only",
      step: "persist",
      error: "disk full",
    },
  ],
  [
    "failed install",
    {
      status: "failed",
      requested: "read-write",
      access: "read-only",
      step: "install",
      error: "toolset",
    },
  ],
  [
    "a lying applied that left read-only",
    { status: "applied", requested: "read-write", access: "read-only" },
  ],
];

for (const [label, release] of HELD_RELEASES) {
  test(`a successful save whose release is held (${label}) reports gateExited false`, async () => {
    const gate = fakeGate(true, release);
    const result = await saveThroughApprovalGate(gate, async () => SAVED);
    assert.deepEqual(result, { outcome: SAVED, gateExited: false });
    assert.equal(gate.exits, 1, "exactly one exit");
  });
}
