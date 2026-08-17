import assert from "node:assert/strict";
import {
  chmodSync,
  closeSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readdirSync,
  readFileSync,
  readSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  agentScratchDir,
  atomicWriteFileSync,
  clearMarker,
  ensureAgentScratch,
  ensureRunScratch,
  handoffPath,
  hasMarker,
  hunkConsumerLockDir,
  hunkDeliveredPath,
  hunkLeasePath,
  hunkOutboxPath,
  hunkWatchDir,
  markHandoffConsumed,
  type PlanRef,
  planRefPath,
  readHandoff,
  readPlanRef,
  runScratchDir,
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

test("hunk-watch: the §8.58 path family hangs off workflowDir", () => {
  const dir = tmp();
  assert.equal(hunkWatchDir(dir), join(workflowDir(dir), "hunk-watch"));
  assert.equal(hunkOutboxPath(dir), join(hunkWatchDir(dir), "outbox.ndjson"));
  assert.equal(hunkDeliveredPath(dir), join(hunkWatchDir(dir), "delivered.ndjson"));
  assert.equal(hunkConsumerLockDir(dir), join(hunkWatchDir(dir), "consumer.lock"));
  assert.equal(hunkLeasePath(dir), join(hunkConsumerLockDir(dir), "lease.json"));
});

test("ensureRunScratch accepts ordinary, legacy, and dotted-fork ids idempotently", () => {
  const cwd = tmp();
  for (const runId of ["01JABCDEF", "cold-door-1700000000000", "01JABCDEF.2"]) {
    const expected = runScratchDir(cwd, runId);
    assert.equal(ensureRunScratch(cwd, runId), expected);
    assert.equal(ensureRunScratch(cwd, runId), expected);
    assert.ok(statSync(expected).isDirectory());
  }
});

test("ensureRunScratch validates a single safe segment before any write", () => {
  for (const runId of ["", ".", "..", "../escape", "nested/run", "nested\\run", "nul\0id"]) {
    const cwd = tmp();
    assert.throws(() => ensureRunScratch(cwd, runId), /unsafe run id/);
    assert.deepEqual(readdirSync(cwd), [], `unsafe ${JSON.stringify(runId)} wrote to disk`);
  }
});

test("ensureRunScratch rejects symlinks and non-directories from .perk through the run root", () => {
  const components = [
    [".perk"],
    [".perk", "workflow"],
    [".perk", "workflow", "scratch"],
    [".perk", "workflow", "scratch", "runs"],
    [".perk", "workflow", "scratch", "runs", "RID"],
  ];
  for (const [index, segments] of components.entries()) {
    const symlinkCwd = tmp();
    const symlinkTarget = join(symlinkCwd, ...segments);
    mkdirSync(join(symlinkTarget, ".."), { recursive: true });
    const outside = tmp();
    symlinkSync(outside, symlinkTarget, "dir");
    assert.throws(() => ensureRunScratch(symlinkCwd, "RID"), /symlinked run-scratch path/);

    const fileCwd = tmp();
    const fileTarget = join(fileCwd, ...segments);
    mkdirSync(join(fileTarget, ".."), { recursive: true });
    writeFileSync(fileTarget, `blocker-${index}`);
    assert.throws(() => ensureRunScratch(fileCwd, "RID"), /non-directory run-scratch path/);
  }
});

test("ensureRunScratch permits a symlink above the checkout root", () => {
  const root = tmp();
  const checkout = join(root, "checkout");
  const alias = join(root, "checkout-link");
  mkdirSync(checkout);
  symlinkSync(checkout, alias, "dir");
  assert.equal(ensureRunScratch(alias, "RID"), runScratchDir(alias, "RID"));
  assert.ok(statSync(runScratchDir(checkout, "RID")).isDirectory());
});

test("ensureAgentScratch creates and reapplies 0700, refusing redirects and files", () => {
  const cwd = tmp();
  const expected = agentScratchDir(cwd, "RID");
  assert.equal(ensureAgentScratch(cwd, "RID"), expected);
  assert.equal(statSync(expected).mode & 0o777, 0o700);
  chmodSync(expected, 0o755);
  assert.equal(ensureAgentScratch(cwd, "RID"), expected);
  assert.equal(statSync(expected).mode & 0o777, 0o700);

  const symlinkCwd = tmp();
  ensureRunScratch(symlinkCwd, "RID");
  const outside = tmp();
  symlinkSync(outside, agentScratchDir(symlinkCwd, "RID"), "dir");
  assert.throws(() => ensureAgentScratch(symlinkCwd, "RID"), /symlinked run-scratch path/);

  const fileCwd = tmp();
  ensureRunScratch(fileCwd, "RID");
  writeFileSync(agentScratchDir(fileCwd, "RID"), "blocker");
  assert.throws(() => ensureAgentScratch(fileCwd, "RID"), /non-directory run-scratch path/);
  assert.equal(existsSync(agentScratchDir(fileCwd, "RID")), true);
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

test("atomicWriteFileSync: replaces the directory entry, never the open file (replace semantics)", () => {
  // The black-box discriminator between atomic replace and a direct in-place write: a reader
  // holding the file open across the write must keep seeing the OLD bytes intact (the rename
  // swaps the directory entry to a new file), while a fresh open sees the new bytes. A plain
  // truncate-write (`writeFileSync(path, ...)`) mutates the file the reader holds open — the
  // torn-read exposure this seam exists to prevent — and fails this test deterministically.
  const dir = tmp();
  const path = join(dir, "out.json");
  atomicWriteFileSync(path, "old content\n");
  const fd = openSync(path, "r");
  try {
    atomicWriteFileSync(path, "new\n");
    const buf = Buffer.alloc(64);
    const bytes = readSync(fd, buf, 0, 64, 0);
    assert.equal(buf.subarray(0, bytes).toString("utf8"), "old content\n");
    assert.equal(readFileSync(path, "utf8"), "new\n");
  } finally {
    closeSync(fd);
  }
});
