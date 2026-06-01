import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  clearMarker,
  handoffPath,
  hasMarker,
  markHandoffConsumed,
  type PlanRef,
  planRefPath,
  readHandoff,
  readPlanRef,
  setMarker,
  workflowDir,
  writePlanRef,
} from "./cache.ts";

function tmp(): string {
  return mkdtempSync(join(tmpdir(), "perk-cache-"));
}

test("readHandoff: missing returns null; consume is a no-op", () => {
  const dir = tmp();
  assert.equal(readHandoff(dir, "RID"), null);
  markHandoffConsumed(dir, "RID"); // no throw on absent handoff
});

test("handoff: read + consume round-trip in the shape cache.py writes", () => {
  const dir = tmp();
  mkdirSync(join(dir, ".pi", "workflow", "handoff"), { recursive: true });
  writeFileSync(
    handoffPath(dir, "RID"),
    JSON.stringify({ mode: "read-only", run_id: "RID", consumed: false }),
    "utf8",
  );
  const data = readHandoff(dir, "RID");
  assert.equal(data?.run_id, "RID");
  assert.equal(data?.consumed, false);

  markHandoffConsumed(dir, "RID", { piSessionId: "sess1" });
  const after = readHandoff(dir, "RID");
  assert.equal(after?.consumed, true);
  assert.equal(after?.pi_session_id, "sess1");
});

test("plan-ref: missing returns null; write + read round-trip in the shape cache.py writes", () => {
  const dir = tmp();
  assert.equal(readPlanRef(dir), null);
  const ref: PlanRef = {
    provider: "github",
    pr_id: "42",
    url: "https://github.com/o/r/issues/42",
    labels: ["perk:plan"],
    objective_id: null,
  };
  writePlanRef(dir, ref);
  assert.equal(planRefPath(dir), join(workflowDir(dir), "plan-ref.json"));
  assert.deepEqual(readPlanRef(dir), ref);
});

test("markers: set / has / clear (idempotent)", () => {
  const dir = tmp();
  assert.equal(hasMarker(dir, "m"), false);
  setMarker(dir, "m");
  assert.equal(hasMarker(dir, "m"), true);
  clearMarker(dir, "m");
  assert.equal(hasMarker(dir, "m"), false);
  clearMarker(dir, "m"); // idempotent
});
