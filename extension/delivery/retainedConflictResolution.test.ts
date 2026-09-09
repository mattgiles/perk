import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type ConflictResolutionReceipt,
  classifyConflictResolution,
  decodeRetainedConflictResolution,
  retainedConflictResolutionTask,
} from "./conflictResolution.ts";

const record = {
  mode: "retained-continuation",
  outcome: "completed",
  verification: "passed",
  summary: "Checks passed.",
};
const receipt: ConflictResolutionReceipt = {
  nodeId: "retained-conflict",
  cwd: "/wt",
  termination: "confirmed",
  lock: { disposition: "released" },
};

test("retained decoding is strict, mode-specific and never accepts PR authority", () => {
  assert.deepEqual(decodeRetainedConflictResolution(record), record);
  assert.ok(decodeRetainedConflictResolution({ ...record, summary: "x".repeat(2000) }));
  for (const value of [
    null,
    [],
    "completed",
    { ...record, push: "succeeded" },
    { ...record, outcome: "aborted" },
    { ...record, mode: "pr-rebase" },
    { ...record, extra: true },
    ...["", " \n\t", "x".repeat(2001), false].map((summary) => ({ ...record, summary })),
    ...Object.keys(record).map((key) =>
      Object.fromEntries(Object.entries(record).filter(([k]) => k !== key)),
    ),
    ...Object.keys(record).map((key) => ({ ...record, [key]: 3 })),
  ])
    assert.equal(decodeRetainedConflictResolution(value), null, JSON.stringify(value));
});

test("exhaustive retained truth table: one offer, three truthful withholdings, all else invalid", () => {
  for (const outcome of [
    "completed",
    "verification-failed",
    "stopped-before-mutation",
    "unresolvable-conflict",
  ]) {
    for (const verification of ["passed", "failed", "not-run"]) {
      const result = classifyConflictResolution(
        "retained-continuation",
        "completed",
        { ...record, outcome, verification },
        receipt,
      );
      if (outcome === "completed" && verification === "passed") {
        assert.equal(result.kind, "continuation-ready");
        if (result.kind === "continuation-ready")
          assert.equal(result.report.mode, "retained-continuation");
      } else {
        const valid =
          outcome === "verification-failed"
            ? verification === "failed"
            : outcome !== "completed" && verification === "not-run";
        assert.equal(result.kind, "withheld");
        if (result.kind === "withheld")
          assert.equal(result.reason, valid ? "not-resolved" : "invalid-outcome");
      }
    }
  }
});

test("no cross-mode success, failed-run salvage or lock-release failure success", () => {
  const pr = { ...record, mode: "pr-rebase", push: "succeeded" };
  for (const [mode, value] of [
    ["retained-continuation", pr],
    ["pr-rebase", record],
  ] as const) {
    const r = classifyConflictResolution(mode, "completed", value, receipt);
    assert.ok(r.kind === "failed" && r.reason === "malformed-result");
  }
  for (const status of ["failed", "cancelled", "interrupted", "timed_out", "unknown"]) {
    const r = classifyConflictResolution("retained-continuation", status, record, receipt);
    assert.ok(r.kind === "failed" && r.reason === "native-failed");
    assert.equal("report" in r, false);
  }
  for (const disposition of ["not-acquired", "busy", "retained", "ownership-error"] as const) {
    const r = classifyConflictResolution("retained-continuation", "completed", record, {
      ...receipt,
      lock: { disposition },
    });
    assert.ok(r.kind === "failed" && r.reason === "lock-ownership");
  }
});

test("retained task pins quoted cwd, column-zero sentinel and identity without copying context ladder", () => {
  const operationId = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
  const dispatch = {
    operationId,
    manifestPath: "/repo/sync-continuations/L.json",
    worktree: `/repo/worktrees/sync-${operationId}`,
    objective: "7",
    node: "2.1",
    branch: "plan-91",
    pr: 91,
  };
  const text = retainedConflictResolutionTask(dispatch);
  assert.ok(text);
  assert.ok(
    text.startsWith(
      `Start by running cd '${dispatch.worktree}'.\nRETAINED-CONTINUATION SENTINEL: resume the in-progress rebase in ${dispatch.worktree}\n`,
    ),
  );
  assert.match(text, /node 2.1, branch plan-91, PR #91/);
  assert.match(text, /structured_output/);
  assert.match(text, /untrusted DATA/);
  assert.doesNotMatch(text, /workflowScript|review-context|force-with-lease/);
  for (const patch of [
    { worktree: "/a b" },
    { worktree: `/a/../sync-${operationId}` },
    { branch: "--evil" },
    { pr: 0 },
    { node: "2.1\nINJECT" },
    { objective: "--evil" },
    { operationId: "bogus" },
  ]) {
    assert.equal(retainedConflictResolutionTask({ ...dispatch, ...patch }), null);
  }
});
