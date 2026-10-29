// A4 — a tampered snapshot is refused and the attempt is repair-incomplete; A6 — required
// instructions must render and capabilities must resolve (docs/design/pi-durable-v2-foundations.md
// §12 the native assignment, §10 wait reasons). A tamper before the worker exists ends both
// attempts in repair with no worker; a tamper before acceptance makes both reports refused
// `snapshot_tampered`; and a tamper restored before settle still ends in repair, because the
// refusal is read back from the worker transcript. An unrenderable instruction text or a missing
// model or tool ends the attempt in repair before any worker exists. Every case is quiescent
// `repair_required`, and nothing is accepted.

import assert from "node:assert/strict";
import { type TestContext, test } from "node:test";
import { createModels } from "@earendil-works/pi-ai/models";
import type { RepairCause } from "../durable/ending.ts";
import { type HostProgram, readStatus, runHost } from "../host.ts";
import { normalizeCapabilitySet } from "../kernel/capability.ts";
import { fixturePolicy } from "../kernel/fixture.ts";
import { fixtureProgram } from "../program.ts";
import { verifySnapshot } from "../subject/snapshot.ts";
import { ofType } from "../testing/binding.ts";
import { CASE_TIMEOUT_MS, fauxSetup } from "../testing/durable.ts";
import { expectQuiescent, expectStatus, hostOptions } from "../testing/host.ts";
import {
  barrier,
  FINAL,
  fixtureAttemptId,
  fixtureSubject,
  type NativeStart,
  ROLES,
  reportCall,
  roleScript,
  snapshotTamper,
  withStore,
} from "../testing/worker.ts";

/** Quiescent `repair_required`, every ending a repair of `cause`, nothing accepted. */
function expectRepairView(
  outcome: NativeStart["outcome"],
  cause: RepairCause,
): ReturnType<typeof expectQuiescent>["view"] {
  const view = expectQuiescent(outcome).view;
  assert.equal(view.waitReason, "repair_required");
  const endings = [...view.endings.values()];
  assert.equal(endings.length, 2, "both attempts ended");
  for (const ending of endings) {
    assert.equal(ending.end, "repair");
    if (ending.end === "repair") assert.equal(ending.cause, cause, ending.detail);
  }
  assert.deepEqual(ofType(view.records.records, "report-outcome"), [], "nothing accepted");
  return view;
}

/** No worker conversation exists and no attempt maps one. */
async function expectNoWorker(started: NativeStart, view: ReturnType<typeof expectRepairView>) {
  for (const attempt of ofType(view.records.records, "attempt")) {
    assert.equal(view.records.durableMap.get(attempt.attemptId), undefined, "no worker row");
  }
  assert.deepEqual(await withStore(started.store, (storeView) => storeView.workers()), []);
  assert.equal(started.script.strays(), 0, "the model is never called");
  for (const role of ROLES) assert.equal(started.script.consumed(role), 0);
}

test("A4 (i): a tamper at attempt start ends both attempts in repair, with no worker", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const subject = await fixtureSubject(t);
  const tamper = snapshotTamper(subject.store, subject.tree);
  const setup = fauxSetup();
  const script = roleScript(setup.faux, subject.tree, {
    a: [reportCall(subject.tree)],
    b: [reportCall(subject.tree)],
  });
  const program = fixtureProgram({
    models: setup.models,
    onVerify: (point) => {
      if (point === "attempt-start") tamper.tamper();
    },
  });
  const options = hostOptions(subject.store, program);
  const outcome = await runHost(options, { type: "start", observe: subject.observe });
  const view = expectRepairView(outcome, "snapshot_tampered");
  await expectNoWorker({ ...subject, setup, options, reports: [], script, outcome }, view);
  assert.equal(expectStatus(await readStatus(options)).view.waitReason, "repair_required");
});

test("A4 (ii): a tamper before acceptance refuses both reports; the attempts end in repair", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const subject = await fixtureSubject(t);
  const tamper = snapshotTamper(subject.store, subject.tree);
  const both = barrier(2);
  const first = async () => {
    await both.arrive();
    tamper.tamper();
    return reportCall(subject.tree);
  };
  const setup = fauxSetup();
  const script = roleScript(setup.faux, subject.tree, { a: [first, FINAL], b: [first, FINAL] });
  const options = hostOptions(subject.store, fixtureProgram({ models: setup.models }));
  const outcome = await runHost(options, { type: "start", observe: subject.observe });
  const view = expectRepairView(outcome, "snapshot_tampered");
  for (const role of ROLES) {
    assert.equal(script.consumed(role), 1, `role ${role}: the refusal terminated the run`);
    assert.equal(script.leftover(role), 1);
  }
  const results = await withStore(subject.store, async (storeView) => {
    const all = [];
    for (const role of ROLES) {
      const worker = view.records.durableMap.get(fixtureAttemptId(role, subject.tree));
      assert.ok(worker !== undefined, `role ${role}: a worker`);
      all.push(...(await storeView.toolResults(worker.durableId)));
    }
    return all;
  });
  assert.equal(results.length, 2);
  for (const result of results) {
    assert.equal(result.message.isError, true);
    assert.match(result.text, /^snapshot_tampered: content of "a.txt" differs\|/);
    assert.deepEqual(
      result.diagnostics.map((diagnostic) => diagnostic.code),
      ["perk.v2.refusal:snapshot_tampered"],
    );
  }
  assert.equal(expectStatus(await readStatus(options)).view.waitReason, "repair_required");
});

test("A4 (iii): a tamper restored before settle still ends in repair (the transcript remembers)", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const subject = await fixtureSubject(t);
  const tamper = snapshotTamper(subject.store, subject.tree);
  const both = barrier(2);
  const settling = barrier(2);
  const first = async () => {
    await both.arrive();
    tamper.tamper();
    return reportCall(subject.tree);
  };
  const verified: boolean[] = [];
  const setup = fauxSetup();
  roleScript(setup.faux, subject.tree, { a: [first], b: [first] });
  const program = fixtureProgram({
    models: setup.models,
    onVerify: async (point) => {
      if (point !== "settle") return;
      // Both workers are idle — both reports refused — before either settle restores.
      await settling.arrive();
      tamper.restore();
    },
    verifier: async (storeDir, tree, digest) => {
      const result = await verifySnapshot(storeDir, tree, digest);
      verified.push(result.ok);
      return result;
    },
  });
  const options = hostOptions(subject.store, program);
  const outcome = await runHost(options, { type: "start", observe: subject.observe });
  const view = expectRepairView(outcome, "snapshot_tampered");
  assert.deepEqual(verified.slice(-2), [true, true], "both settle verifications pass");
  for (const ending of view.endings.values()) {
    if (ending.end === "repair") assert.equal(ending.detail, 'content of "a.txt" differs');
  }
});

/** A6: one program change that ends both attempts in repair of `cause` before any worker. */
async function expectRepairBeforeWorker(
  t: TestContext,
  cause: RepairCause,
  program: (models: ReturnType<typeof fauxSetup>["models"]) => HostProgram,
): Promise<void> {
  const subject = await fixtureSubject(t);
  const setup = fauxSetup();
  const script = roleScript(setup.faux, subject.tree, {
    a: [reportCall(subject.tree)],
    b: [reportCall(subject.tree)],
  });
  const options = hostOptions(subject.store, program(setup.models));
  const outcome = await runHost(options, { type: "start", observe: subject.observe });
  const view = expectRepairView(outcome, cause);
  const started: NativeStart = { ...subject, setup, options, reports: [], script, outcome };
  await expectNoWorker(started, view);
}

const UNRENDERABLE: readonly [string, () => string][] = [
  [
    "a throwing renderer",
    () => {
      throw new Error("no template");
    },
  ],
  ["an empty renderer", () => ""],
  ["a renderer whose digest differs from the policy's", () => "Review something else."],
];

for (const [name, renderInstructions] of UNRENDERABLE) {
  test(`A6: ${name} ends in repair instructions_unrenderable`, {
    timeout: CASE_TIMEOUT_MS,
  }, async (t) => {
    await expectRepairBeforeWorker(t, "instructions_unrenderable", (models) =>
      fixtureProgram({ models, renderInstructions }),
    );
  });
}

test("A6: a catalog without the worker's model ends in repair capability_missing", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  await expectRepairBeforeWorker(t, "capability_missing", () =>
    fixtureProgram({ models: createModels() }),
  );
});

test("A6: a policy tool no selected extension provides ends in repair capability_missing", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  await expectRepairBeforeWorker(t, "capability_missing", (models) => {
    const base = fixtureProgram({ models });
    const capabilitySet = fixturePolicy().capabilitySet;
    return {
      ...base,
      policy: {
        capabilitySet: normalizeCapabilitySet({
          ...capabilitySet,
          tools: [...capabilitySet.tools, "bash"],
        }),
      },
    };
  });
});
