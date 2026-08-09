import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  atomicWriteFileSync,
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

/** Run `fn` with `console.error` stubbed, returning the captured lines. */
function withStderrCapture<T>(fn: () => T): { result: T; lines: string[] } {
  const lines: string[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => lines.push(args.map(String).join(" "));
  try {
    return { result: fn(), lines };
  } finally {
    console.error = original;
  }
}

test("readHandoff: missing returns null; consume is a no-op", () => {
  const dir = tmp();
  assert.equal(readHandoff(dir, "RID"), null);
  markHandoffConsumed(dir, "RID"); // no throw on absent handoff
});

test("handoff: read + consume round-trip in the shape cache.py writes", () => {
  const dir = tmp();
  mkdirSync(join(dir, ".perk", "workflow", "handoff"), { recursive: true });
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

test("total readers: a corrupt handoff reads as absent (loud) and consume is a no-op", () => {
  const dir = tmp();
  mkdirSync(join(dir, ".perk", "workflow", "handoff"), { recursive: true });
  const truncated = '{"run_id": "RID", "consum'; // torn write
  writeFileSync(handoffPath(dir, "RID"), truncated, "utf8");

  const read = withStderrCapture(() => readHandoff(dir, "RID"));
  assert.equal(read.result, null);
  assert.equal(read.lines.length, 1);
  assert.match(read.lines[0] as string, /unreadable handoff at .*RID\.json/);

  // Consuming a corrupt handoff degrades to the absent no-op: no throw, file bytes kept (GC's
  // degrade-graceful rule collects it by age).
  const consume = withStderrCapture(() => markHandoffConsumed(dir, "RID"));
  assert.equal(consume.lines.length, 1);
  assert.equal(readFileSync(handoffPath(dir, "RID"), "utf8"), truncated);
});

test("total readers: a corrupt plan-ref reads as absent (loud)", () => {
  const dir = tmp();
  mkdirSync(workflowDir(dir), { recursive: true });
  writeFileSync(planRefPath(dir), '{"provider": "github", "pr_id', "utf8");
  const { result, lines } = withStderrCapture(() => readPlanRef(dir));
  assert.equal(result, null);
  assert.equal(lines.length, 1);
  assert.match(lines[0] as string, /unreadable plan-ref at .*plan-ref\.json/);
});

test("total readers: valid JSON of the wrong shape (a scalar, an array) reads as absent (loud)", () => {
  const dir = tmp();
  mkdirSync(workflowDir(dir), { recursive: true });
  for (const wrongShape of ["42\n", "[]\n"]) {
    writeFileSync(planRefPath(dir), wrongShape, "utf8");
    const { result, lines } = withStderrCapture(() => readPlanRef(dir));
    assert.equal(result, null, `expected null for ${JSON.stringify(wrongShape)}`);
    assert.equal(lines.length, 1);
  }
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

test("atomicWriteFileSync: content lands byte-exact", () => {
  const dir = tmp();
  const path = join(dir, "out.json");
  atomicWriteFileSync(path, '{"a": 1}\n');
  assert.equal(readFileSync(path, "utf8"), '{"a": 1}\n');
});

test("atomicWriteFileSync: a shorter write fully replaces longer prior content", () => {
  // The production tear shape: a bare truncate-write interrupted mid-way leaves trailing
  // stray bytes of the longer prior payload; the atomic replace never can.
  const dir = tmp();
  const path = join(dir, "out.json");
  atomicWriteFileSync(path, `${JSON.stringify({ key: "a much longer payload value here" })}\n`);
  atomicWriteFileSync(path, '{"k": 1}\n');
  assert.equal(readFileSync(path, "utf8"), '{"k": 1}\n');
});

test("atomicWriteFileSync: leaves no .tmp residue", () => {
  const dir = tmp();
  atomicWriteFileSync(join(dir, "out.json"), "content\n");
  assert.deepEqual(readdirSync(dir), ["out.json"]);
});
