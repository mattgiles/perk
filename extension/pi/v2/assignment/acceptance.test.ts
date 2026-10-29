// A1 — a valid report is accepted once, with no recap (docs/design/pi-durable-v2-foundations.md §12
// the native assignment): each role's worker reports through the report tool, which accepts in the
// reconcile commit and terminates the run, so the scripted recap is never requested; the worker
// conversation is task-owned, explicitly configured and mapped with its submission; a second run
// requests nothing. The mixed-round variant proves acceptance never depends on termination: a
// report beside another call still commits once, the run continues, and a later report replays.

import assert from "node:assert/strict";
import { join } from "node:path";
import { test } from "node:test";
import { lookupReceipt } from "../durable/operate.ts";
import { composeProgram, runHost, STORE_DATABASE } from "../host.ts";
import {
  FIXTURE_WORKER_EXTENSION,
  FIXTURE_WORKER_TOOLS,
  renderFixtureInstructions,
} from "../kernel/fixture.ts";
import { launchOpId, submitOpId } from "../kernel/identity.ts";
import { nonSessionV2Documents, ofType } from "../testing/binding.ts";
import { CASE_TIMEOUT_MS } from "../testing/durable.ts";
import { expectQuiescent } from "../testing/host.ts";
import {
  assertScript,
  call,
  FINAL,
  fixtureAttemptId,
  openStoreHarness,
  ROLES,
  reportArgs,
  reportCall,
  reportTypes,
  round,
  startNative,
  withStore,
} from "../testing/worker.ts";

test("A1: a valid report is accepted once, with no recap", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const started = await startNative(t, (tree) => ({
    a: [reportCall(tree), FINAL],
    b: [reportCall(tree), FINAL],
  }));
  const { tree, store, script, reports } = started;
  const view = expectQuiescent(started.outcome).view;
  assert.equal(view.waitReason, "pending_decision");
  assertScript(script, { a: { consumed: 1, leftover: 1 }, b: { consumed: 1, leftover: 1 } });
  assert.deepEqual(reportTypes(reports), [], "no report — no extension_error");

  const [observation] = ofType(view.records.records, "observation");
  assert.ok(observation !== undefined);
  const outcomes = ofType(view.records.records, "report-outcome");
  assert.equal(outcomes.length, 2);
  const durableMap = view.records.durableMap;
  const workers = await withStore(store, async (storeView) => {
    const found = [];
    for (const role of ROLES) {
      const attemptId = fixtureAttemptId(role, tree);
      const mine = outcomes.filter((outcome) => outcome.attemptId === attemptId);
      assert.equal(mine.length, 1, `role ${role}: one outcome`);
      assert.equal(mine[0]?.verifiedDigest, observation.manifestDigest);
      assert.deepEqual(view.endings.get(attemptId), { end: "accepted", outcomeId: mine[0]?.opId });

      const worker = durableMap.get(attemptId);
      const submission = durableMap.get(submitOpId(attemptId));
      const launch = durableMap.get(launchOpId(attemptId));
      assert.equal(worker?.durableKind, "conversation", `role ${role}: worker row`);
      assert.equal(submission?.durableKind, "submission", `role ${role}: submission row`);
      assert.equal(launch?.durableKind, "task", `role ${role}: launch row`);
      if (worker === undefined || submission === undefined || launch === undefined) continue;

      const conversation = (await storeView.conversations()).find(
        (candidate) => candidate.id === worker.durableId,
      );
      assert.equal(conversation?.owner?.taskId, launch.durableId, "owned by the launched task");
      assert.deepEqual(await storeView.agent(worker.durableId), {
        model: { provider: "faux", modelId: "faux-1" },
        extensions: [FIXTURE_WORKER_EXTENSION],
        tools: [...FIXTURE_WORKER_TOOLS],
        modelTools: [...FIXTURE_WORKER_TOOLS],
        instructions: renderFixtureInstructions(),
        cwd: "subject-snapshot",
      });
      const submissions = await storeView.submissions(worker.durableId);
      assert.deepEqual(
        submissions.map((record) => [record.id, record.requestId, record.status]),
        [[submission.durableId, submitOpId(attemptId), "done"]],
        `role ${role}: exactly the mapped submission`,
      );
      found.push({ role, attemptId, launch, submission });
    }
    return found;
  });
  assert.equal(workers.length, 2);

  // The submit receipt carries the launch and the submission rows.
  const opened = await openStoreHarness(t, store, composeProgram(started.options));
  for (const { attemptId, launch, submission } of workers) {
    const receipt = await lookupReceipt(opened.harness, submitOpId(attemptId));
    assert.deepEqual(receipt?.durable, [
      { perkId: launchOpId(attemptId), ...launch },
      { perkId: submitOpId(attemptId), ...submission },
    ]);
  }
  await opened.dispose();

  // A second run over the same tree requests nothing and accepts nothing.
  const again = expectQuiescent(
    await runHost(started.options, { type: "run", observe: started.observe }),
  );
  assert.equal(again.view.waitReason, "pending_decision");
  assertScript(script, { a: { consumed: 1, leftover: 1 }, b: { consumed: 1, leftover: 1 } });
  assert.equal(ofType(again.view.records.records, "report-outcome").length, 2);
  assert.deepEqual(await nonSessionV2Documents(join(store, STORE_DATABASE)), []);
});

test("A1 (mixed round): a report beside another call commits once; later reports replay", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const started = await startNative(t, (tree) => ({
    a: [
      round(call("report", reportArgs(tree), "r1"), call("read", { path: "a.txt" }, "x1")),
      round(call("report", reportArgs(tree), "r2"), call("bash", { command: "ls" }, "x2")),
      FINAL,
    ],
    b: [
      round(call("report", reportArgs(tree), "r1"), call("bash", { command: "ls" }, "x1")),
      FINAL,
    ],
  }));
  const { tree, store, script } = started;
  const view = expectQuiescent(started.outcome).view;
  assert.equal(view.waitReason, "pending_decision");
  assertScript(script, { a: { consumed: 3, leftover: 0 }, b: { consumed: 2, leftover: 0 } });
  const outcomes = ofType(view.records.records, "report-outcome");
  for (const role of ROLES) {
    const attemptId = fixtureAttemptId(role, tree);
    const mine = outcomes.filter((outcome) => outcome.attemptId === attemptId);
    assert.equal(mine.length, 1, `role ${role}: exactly one outcome`);
    assert.deepEqual(view.endings.get(attemptId), { end: "accepted", outcomeId: mine[0]?.opId });
  }
  const resultsOfA = await withStore(store, async (storeView) => {
    const worker = view.records.durableMap.get(fixtureAttemptId("a", tree));
    assert.ok(worker !== undefined);
    return storeView.toolResults(worker.durableId);
  });
  const reportResults = resultsOfA.filter((result) => result.message.toolName === "report");
  assert.equal(reportResults.length, 2, "two report calls, one acceptance");
  for (const result of reportResults) {
    assert.equal(result.message.isError, false);
    assert.match(result.text, /^accepted .*\/accept-report$/);
  }
  const read = resultsOfA.find((result) => result.message.toolName === "read");
  assert.equal(read?.text, "alpha\n", "the sibling read ran");
  const bash = resultsOfA.find((result) => result.message.toolName === "bash");
  assert.equal(bash?.message.isError, true, "bash is not a worker tool");
});
