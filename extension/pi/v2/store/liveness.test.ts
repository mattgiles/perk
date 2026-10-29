// The liveness seam (docs/design/pi-durable-v2-foundations.md §10 store owner lock protocol,
// "Liveness"): `/proc/<pid>/stat` parsing robust to a hostile command name, the procfs seam over a
// fake proc tree (fails closed: no `self`, or an unparseable stat, is unsupported; a missing pid or
// a zombie is no live process), and — where `/proc` exists — the real seam against this process
// and a child read alive, then killed.

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { test } from "node:test";
import { CASE_TIMEOUT_MS, defer, tempDir } from "../testing/durable.ts";
import { parseProcStat, procfsLiveness, selfIdentity } from "./liveness.ts";

/** A stat line for `comm` in `state`, with start time `start` at field 22. */
function statLine(pid: number, comm: string, state: string, start: string): string {
  // Fields 4–21 (18 fields), then field 22.
  const middle = Array.from({ length: 18 }, (_, i) => String(i + 1)).join(" ");
  return `${pid} (${comm}) ${state} ${middle} ${start} 0 0\n`;
}

test("parseProcStat counts fields after the last `)`", { timeout: CASE_TIMEOUT_MS }, () => {
  assert.deepEqual(parseProcStat(statLine(42, "a b) (c", "S", "123456")), {
    state: "S",
    startTime: "123456",
  });
  assert.deepEqual(parseProcStat(statLine(42, "x", "Z", "7")), { state: "Z", startTime: "7" });
  assert.equal(parseProcStat("42 (x) S 1 2 3"), null, "truncated before field 22");
  assert.equal(parseProcStat("42 x S"), null, "no command name");
  assert.equal(parseProcStat(statLine(42, "x", "S", "12a")), null, "a non-digit start time");
});

test("procfsLiveness over a fake proc tree fails closed", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const bare = await tempDir(t, "perk-v2-proc-");
  assert.equal(procfsLiveness(bare).startTimeOf(7), "unsupported", "no self/stat");

  const root = await tempDir(t, "perk-v2-proc-");
  const entry = async (name: string, text: string): Promise<void> => {
    await mkdir(join(root, name));
    await writeFile(join(root, name, "stat"), text);
  };
  await entry("self", statLine(1, "self", "R", "1"));
  await entry("10", statLine(10, "zombie", "Z", "500"));
  await entry("11", "garbage");
  await entry("12", statLine(12, "sleep (1)", "S", "777"));
  const liveness = procfsLiveness(root);
  assert.equal(liveness.startTimeOf(9), null, "a missing pid");
  assert.equal(liveness.startTimeOf(10), null, "a zombie");
  assert.equal(liveness.startTimeOf(11), "unsupported", "an unparseable stat");
  assert.equal(liveness.startTimeOf(12), "777", "a live process's start time");
});

test("the real seam: this process, and a child read alive then killed", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const liveness = procfsLiveness();
  if (!existsSync("/proc/self/stat")) {
    assert.equal(liveness.startTimeOf(process.pid), "unsupported");
    assert.equal(selfIdentity(liveness).startedAt, null);
    return;
  }
  const own = liveness.startTimeOf(process.pid);
  assert.ok(typeof own === "string" && /^[0-9]+$/.test(own), `a digit string: ${String(own)}`);
  assert.equal(selfIdentity(liveness).startedAt, own);
  assert.equal(selfIdentity(liveness).pid, process.pid);

  const child = spawn("sleep", ["30"], { stdio: "ignore" });
  const exited = new Promise<void>((resolve) => child.once("exit", () => resolve()));
  defer(t, async () => {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    await exited;
  });
  const pid = child.pid;
  assert.ok(pid !== undefined, "the child spawned");
  const started = liveness.startTimeOf(pid);
  assert.ok(typeof started === "string", `the live child has a start time: ${String(started)}`);
  child.kill("SIGKILL");
  await exited;
  assert.notEqual(liveness.startTimeOf(pid), started, "the killed child is no longer that process");
});
