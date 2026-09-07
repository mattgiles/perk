import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  type ConflictResolutionReceipt,
  classifyConflictResolution,
  conflictResolutionTask,
  decodeConflictResolution,
} from "./conflictResolution.ts";

const receipt: ConflictResolutionReceipt = {
  parentSessionId: "parent",
  ownerRunId: "run",
  requestId: "request",
  nodeId: "submit-conflict",
  cwd: "/wt",
  disposition: "terminal",
  termination: "confirmed",
  lock: { disposition: "released" },
};
const record = {
  mode: "pr-rebase",
  outcome: "completed",
  verification: "passed",
  push: "succeeded",
  summary: "Checks passed.",
};

test("strict terminal schema rejects missing, extra, wrong, blank and overlong fields", () => {
  assert.deepEqual(decodeConflictResolution(record), record);
  assert.ok(decodeConflictResolution({ ...record, summary: "x".repeat(2000) }));
  for (const value of [
    null,
    [],
    "completed",
    { ...record, extra: true },
    { ...record, mode: "retained-continuation" },
    ...["", " \n\t", "x".repeat(2001), 123].map((summary) => ({ ...record, summary })),
    ...Object.keys(record).map((key) =>
      Object.fromEntries(Object.entries(record).filter(([k]) => k !== key)),
    ),
    ...Object.keys(record).map((key) => ({ ...record, [key]: false })),
  ])
    assert.equal(decodeConflictResolution(value), null, JSON.stringify(value));
});

test("all outcome/verification/push combinations: only one authorizes re-submit", () => {
  for (const outcome of [
    "completed",
    "verification-failed",
    "stopped-before-mutation",
    "unresolvable-conflict",
    "aborted",
  ]) {
    for (const verification of ["passed", "failed", "not-run"]) {
      for (const push of ["succeeded", "failed", "not-attempted"]) {
        const r = classifyConflictResolution(
          "completed",
          { ...record, outcome, verification, push },
          receipt,
        );
        assert.equal(
          r.kind,
          outcome === "completed" && verification === "passed" && push === "succeeded"
            ? "resolved"
            : "withheld",
        );
        if (
          outcome === "verification-failed" ||
          (push === "succeeded" && outcome !== "completed")
        ) {
          assert.ok(r.kind === "withheld" && r.reason === "invalid-outcome");
        }
      }
    }
  }
});

test("native failure cannot salvage a valid report; lock failure cannot authorize re-submit", () => {
  for (const status of ["failed", "timed_out", "cancelled", "interrupted", "unknown"]) {
    const r = classifyConflictResolution(status, record, receipt);
    assert.equal(r.kind, "failed");
    assert.equal("report" in r, false);
  }
  for (const disposition of ["not-acquired", "busy", "retained", "ownership-error"] as const) {
    assert.equal(
      classifyConflictResolution("completed", record, { ...receipt, lock: { disposition } }).kind,
      "failed",
    );
  }
});

test("task quotes valid POSIX cwd, rejects controls and delegates authoritative base lookup", () => {
  const task = conflictResolutionTask(`/wt/space 'quote' "double" \\slash \`tick\` $HOME`);
  assert.ok(task?.includes("cd '/wt/space '\\''quote'\\'' \"double\" \\slash `tick` $HOME'"));
  assert.ok(task);
  assert.match(task, /perk pr review-context --json/);
  assert.match(task, /base_ref is the authoritative/);
  assert.match(task, /force-with-lease/);
  assert.doesNotMatch(task, /RETAINED-CONTINUATION|--pr|workflowScript/);
  for (const c of ["\0", "\r", "\n"]) assert.equal(conflictResolutionTask(`/wt${c}bad`), null);
});

test("agent supplies conditional structured completion without removing legacy report", () => {
  const source = readFileSync(
    new URL("../../agents/conflict-resolver.md", import.meta.url),
    "utf8",
  );
  for (const field of Object.keys(record)) assert.ok(source.includes(`\`${field}\``));
  assert.match(source, /Otherwise retain the first-line protocol/);
  assert.match(source, /2,000 characters/);
});
