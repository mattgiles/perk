import assert from "node:assert/strict";
import test from "node:test";
import {
  CHECK_IDS,
  CHECK_NOTICE_DETAILS,
  CHECK_RUN_STATUSES,
  type CheckRun,
  parseCheckRun,
  parseLatestCheck,
} from "./src/checks.ts";

const RUN: CheckRun = {
  run: "abc123",
  check: "prose-map",
  label: "Prose map check",
  command: "uv run --no-sync perk-dev prose-map check",
  status: "running",
  exit_code: null,
  output: "line one\n",
  next_offset: 9,
  truncated: false,
};

test("the closed check vocabulary is pinned exactly", () => {
  // Backend/frontend wire drift (a dropped or renamed id/status in checks.ts) must
  // fail here — iterating over the live arrays alone would be self-referential.
  assert.deepEqual(
    [...CHECK_IDS],
    [
      "prose-map",
      "learned-docs",
      "prompt-parity",
      "worker-prompt-pins",
      "worker-test-pins",
      "ruff",
      "ty",
      "biome",
      "tsc",
    ],
  );
  assert.deepEqual(
    [...CHECK_RUN_STATUSES],
    ["running", "passed", "failed", "cancelled", "timeout", "spawn-failed"],
  );
});

test("parseCheckRun accepts every closed id and status", () => {
  assert.deepEqual(parseCheckRun(RUN), RUN);
  for (const check of CHECK_IDS) {
    assert.deepEqual(parseCheckRun({ ...RUN, check })?.check, check);
  }
  for (const status of CHECK_RUN_STATUSES) {
    assert.deepEqual(parseCheckRun({ ...RUN, status })?.status, status);
  }
  const terminal = parseCheckRun({ ...RUN, status: "failed", exit_code: 3, truncated: true });
  assert.deepEqual(terminal, { ...RUN, status: "failed", exit_code: 3, truncated: true });
});

test("parseCheckRun rejects unknown vocabulary and ill-shaped fields", () => {
  assert.equal(parseCheckRun(null), null);
  assert.equal(parseCheckRun("running"), null);
  assert.equal(parseCheckRun({ ...RUN, check: "rm -rf /" }), null);
  assert.equal(parseCheckRun({ ...RUN, status: "exploded" }), null);
  assert.equal(parseCheckRun({ ...RUN, run: 7 }), null);
  assert.equal(parseCheckRun({ ...RUN, label: null }), null);
  assert.equal(parseCheckRun({ ...RUN, command: 4 }), null);
  assert.equal(parseCheckRun({ ...RUN, exit_code: "0" }), null);
  assert.equal(parseCheckRun({ ...RUN, exit_code: 1.5 }), null);
  assert.equal(parseCheckRun({ ...RUN, output: null }), null);
  assert.equal(parseCheckRun({ ...RUN, next_offset: -1 }), null);
  assert.equal(parseCheckRun({ ...RUN, next_offset: "9" }), null);
  assert.equal(parseCheckRun({ ...RUN, truncated: "yes" }), null);
  const missing: Record<string, unknown> = { ...RUN };
  delete missing.status;
  assert.equal(parseCheckRun(missing), null);
});

test("parseLatestCheck accepts null and nested runs, rejects everything else", () => {
  assert.deepEqual(parseLatestCheck({ run: null }), { run: null });
  assert.deepEqual(parseLatestCheck({ run: RUN }), { run: RUN });
  assert.equal(parseLatestCheck(null), null);
  assert.equal(parseLatestCheck({}), null);
  assert.equal(parseLatestCheck({ run: { ...RUN, check: "unknown" } }), null);
});

test("every notice maps to one fixed non-empty copy string", () => {
  assert.deepEqual(Object.keys(CHECK_NOTICE_DETAILS).sort(), [
    "busy",
    "not-sent",
    "run-lost",
    "start-failed",
  ]);
  assert.equal(CHECK_NOTICE_DETAILS.busy, "A check is already running.");
  assert.equal(CHECK_NOTICE_DETAILS["run-lost"], "Run record no longer available.");
  for (const detail of Object.values(CHECK_NOTICE_DETAILS)) {
    assert.ok(detail.length > 0);
  }
});
