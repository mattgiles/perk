// The closed vocabularies (docs/design/pi-durable-v2-foundations.md §9 refusal reasons, §10 step 8
// wait reasons) and the throwable refusal the binding raises inside a commit callback.

import assert from "node:assert/strict";
import { test } from "node:test";
import { isRefusalReason, KernelRefusal, REFUSAL_REASONS } from "./refusal.ts";
import { isWaitReason, WAIT_REASONS } from "./waitReason.ts";

test("the refusal reasons are the §9 list, in order", () => {
  assert.deepEqual(REFUSAL_REASONS, [
    "invalid_input",
    "unknown_decision",
    "stale_subject",
    "superseded",
    "cancelled",
    "duplicate_conflict",
    "invalid_report",
    "snapshot_tampered",
    "already_started",
  ]);
});

test("the wait reasons are the §10 list, in order", () => {
  assert.deepEqual(WAIT_REASONS, [
    "pending_decision",
    "unmet_prerequisite",
    "assignment_incomplete",
    "repair_required",
    "parked",
    "blocked",
    "sleeping",
    "cancelled",
    "completed",
  ]);
});

test("each predicate accepts every member and rejects a near miss", () => {
  for (const reason of REFUSAL_REASONS) assert.equal(isRefusalReason(reason), true, reason);
  for (const reason of WAIT_REASONS) assert.equal(isWaitReason(reason), true, reason);
  for (const nearMiss of ["stale", "waiting", "", "Cancelled", "invalid-input"]) {
    assert.equal(isRefusalReason(nearMiss), false, nearMiss);
    assert.equal(isWaitReason(nearMiss), false, nearMiss);
  }
});

test("KernelRefusal is an Error carrying its reason and detail", () => {
  const refusal = new KernelRefusal({ reason: "stale_subject", detail: "decision D is over T1" });
  assert.ok(refusal instanceof Error);
  assert.equal(refusal.name, "KernelRefusal");
  assert.equal(refusal.reason, "stale_subject");
  assert.equal(refusal.detail, "decision D is over T1");
  assert.equal(refusal.message, "stale_subject: decision D is over T1");
});
