// G6 (design §16) — the capstone's teardown proof, the early-failure cleanup path: a case that ends
// while its door's host is held mid-flight, before the test learned anything, still ends with the
// host proven dead, the execution the door then names discarded from the main checkout, and the
// run's temp root removed; `close()` is idempotent, as the deferred call relies on. On procfs the
// held host is SIGKILLed by identity; elsewhere it is never signalled by a bare pid, so close()
// releases its holds and the door completes, naming its execution in its envelope instead.

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { holdFile } from "../door/testGate.ts";
import { REF } from "../testing/binding.ts";
import {
  capstone,
  envelopeOf,
  executionsDir,
  failureOf,
  readGate,
  waitForGate,
} from "../testing/capstone.ts";
import { isDead, procAvailable } from "../testing/containment/procfs.ts";

const CASE_MS = 120_000;

test("G6: close() kills a held door host, proves it dead, then discards its store and the run root", {
  timeout: CASE_MS,
}, async (t) => {
  const run = capstone(t);
  const { repo } = run.subject();
  const start = run.spawnDoor("start", ["start", "--repo", repo, "--ref", REF, "--json"], {
    holds: [holdFile("acceptance", 1)],
  });
  await waitForGate(
    start,
    (gate) => gate.hosts.length === 1 && gate.verifies.some((v) => v.point === "acceptance"),
  );
  // The gate directory lives under the root, which close() removes: read the hosts first.
  const { hosts } = readGate(start.gate);
  assert.equal(start.result(), undefined, "the held door is still running");

  const closed = await run.close();

  assert.ok(start.result() !== undefined, "close() awaited the door's exit");
  if (procAvailable()) {
    for (const host of hosts) {
      assert.ok(host.startTime !== null, "procfs names the host's start time");
      assert.ok(isDead({ pid: host.pid, startTime: host.startTime }), `host ${host.pid} is dead`);
    }
  }
  const exited = await start.exited;
  const id = procAvailable() ? failureOf(exited).execution_id : envelopeOf(exited).executionId;
  assert.ok(id !== undefined, "the ended door names its execution");
  const store = join(executionsDir(), id);
  assert.ok(closed.discarded.includes(store), "the named execution was discarded");
  assert.equal(existsSync(store), false);
  assert.equal(existsSync(run.root), false, "the run root is removed");
  assert.equal(await run.close(), closed, "close() is idempotent");
});
