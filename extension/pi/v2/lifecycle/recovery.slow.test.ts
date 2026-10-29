// H8 (docs/design/pi-durable-v2-foundations.md §10, P8, P9): a real host process running `start`
// is SIGKILLed after role a accepted and while role b's phase is mid-flight. Its accepted record
// survives; the next status open takes the following epoch (the dead holder's epoch is free, and
// stays unreleased as its record) and shows b's attempt still open; the next run recovers b alone —
// a's accepted work is never repeated — and reaches the pending decision.

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { test } from "node:test";
import { readStatus, runHost } from "../host.ts";
import { acceptReportOpId } from "../kernel/identity.ts";
import { procfsLiveness } from "../store/liveness.ts";
import { assertSameRecords, attemptIdOf, C1B, ofType, T1 } from "../testing/binding.ts";
import { CASE_TIMEOUT_MS, tempDir } from "../testing/durable.ts";
import {
  expectQuiescent,
  expectStatus,
  fakeProgram,
  filePhaseHooks,
  hostOptions,
  observed,
  ownerEpochs,
  startHostChild,
} from "../testing/host.ts";

/** The phase log's lines as `[role, pid]` pairs. */
async function phases(path: string): Promise<[string, number][]> {
  const text = await readFile(path, "utf8");
  return text
    .split("\n")
    .filter((line) => line !== "")
    .map((line) => {
      const [role, pid] = line.split(" ");
      return [String(role), Number(pid)];
    });
}

test("H8: a SIGKILLed owner's accepted work survives, and its interrupted task recovers without repeating accepted work", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const dir = await tempDir(t, "perk-v2-host-");
  const store = join(dir, "store");
  const phaseLog = join(dir, "phases.log");
  const child = startHostChild(t, { storeDir: store, phaseLog, blockRole: "b" });
  await child.line("a-accepted");
  await child.line("b-blocked");
  const exit = await child.kill();
  assert.equal(exit.signal, "SIGKILL");

  const options = hostOptions(store, fakeProgram({ hooks: filePhaseHooks(phaseLog) }));
  if (procfsLiveness().startTimeOf(process.pid) === "unsupported") {
    // Without a liveness seam the dead holder can never be proved dead: fail closed.
    assert.deepEqual(await readStatus(options), { kind: "owner_busy", epoch: 1 });
    return;
  }

  // The killed owner's accepted outcome survived; b's attempt is open and its task ready again.
  const status = expectStatus(await readStatus(options));
  assert.equal(status.epoch, 2);
  assert.equal(status.view.waitReason, null, "b is runnable: no wait reason yet");
  const accepted = ofType(status.view.records.records, "report-outcome");
  assert.deepEqual(
    accepted.map((record) => record.opId),
    [acceptReportOpId(attemptIdOf("a", T1))],
    "a's outcome, and nothing for b",
  );
  assert.ok(
    ofType(status.view.records.records, "attempt").some(
      (record) => record.attemptId === attemptIdOf("b", T1),
    ),
    "b's attempt is recorded",
  );

  const recovered = expectQuiescent(
    await runHost(options, { type: "run", observe: observed(T1, C1B) }),
  );
  assert.equal(recovered.epoch, 3);
  assert.equal(recovered.view.waitReason, "pending_decision");

  // a ran once (in the killed child); b ran twice: in the child, then here.
  const logged = await phases(phaseLog);
  const pidsOf = (role: string): number[] =>
    logged.filter(([logRole]) => logRole === role).map(([, pid]) => pid);
  assert.deepEqual(pidsOf("a"), [child.pid], "a's accepted work is never repeated");
  assert.deepEqual(pidsOf("b"), [child.pid, process.pid], "b recovered here");
  assert.equal(logged.length, 3);

  const records = recovered.view.records.records;
  const outcomes = ofType(records, "report-outcome");
  assert.equal(outcomes.length, 2);
  assertSameRecords(
    outcomes.filter((record) => record.attemptId === attemptIdOf("a", T1)),
    accepted,
    "a's outcome is exactly the record that survived the kill",
  );
  assert.equal(ofType(records, "aggregate-outcome").length, 1);
  assert.equal(ofType(records, "decision").length, 1);
  assert.deepEqual(
    (await ownerEpochs(store)).map((entry) => [entry.epoch, entry.released, entry.meta.pid]),
    [
      [1, false, child.pid],
      [2, true, process.pid],
      [3, true, process.pid],
    ],
  );
});
