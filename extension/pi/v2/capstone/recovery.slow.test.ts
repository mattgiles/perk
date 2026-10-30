// G1 (design §16; P1, P3, P6, P8, P9) — the capstone's SIGKILL-recovery flow through the real door:
// `uv run --no-sync perk v2 start` runs the fixture over a temp git subject while the test gate
// holds the second report to reach acceptance inside its replay-safe report tool; the test SIGKILLs
// that host by identity. The door fails with `v2_host_failed` naming the execution; `status` frees
// the dead holder's epoch and shows the first report's outcome retained; one `perk v2 run` replays
// only the second report's tool (re-verifying its snapshot) and reaches the decision; `status`
// explains the wait; a tree-unchanged commit is not stale, so `reply` completes the execution with
// exactly one continuation, and a repeated reply replays its receipt. Every count the exit
// assessment reads is emitted as a `perk-v2-capstone G1 …` row.

import assert from "node:assert/strict";
import { realpathSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { AssignmentView } from "../door/snapshot.ts";
import { holdFile } from "../door/testGate.ts";
import { FIXTURE_REPORT_TASK_NAME } from "../durable/assignment.ts";
import { CONTINUATION_TASK_NAME } from "../durable/continuation.ts";
import type { KernelRecord } from "../kernel/records.ts";
import { procfsLiveness } from "../store/liveness.ts";
import { REF } from "../testing/binding.ts";
import {
  capstone,
  capstoneHostOptions,
  countAt,
  envelopeOf,
  executionOfOwner,
  executionsDir,
  failureOf,
  perPoint,
  readGate,
  row,
  viewOf,
  waitForGate,
  workerCensus,
} from "../testing/capstone.ts";
import { type Identity, isDead, killIdentity } from "../testing/containment/procfs.ts";
import { assertCompleted, recordsOf, storeTasks } from "../testing/decision.ts";
import { ownerEpochs } from "../testing/host.ts";
import { fixtureGit, treeOf } from "../testing/subject.ts";

const CASE_MS = 240_000;

const COUNTED_TYPES = [
  "assignment",
  "attempt",
  "report-outcome",
  "aggregate-outcome",
  "decision",
  "reply",
  "continuation",
  "cancellation",
  "observation",
] as const;

function countByType(records: readonly KernelRecord[]): Record<string, number> {
  return Object.fromEntries(
    COUNTED_TYPES.map((type) => [type, records.filter((record) => record.type === type).length]),
  );
}

function onlyAttempt(assignment: AssignmentView) {
  assert.equal(assignment.attempts.length, 1, `${assignment.role}: exactly one attempt`);
  const [attempt] = assignment.attempts;
  assert.ok(attempt !== undefined);
  assert.equal(attempt.ordinal, 1, `${assignment.role}: attempt 1`);
  return attempt;
}

test("G1: a SIGKILLed door host's accepted work survives, one `perk v2 run` recovers the rest, and reply completes", {
  timeout: CASE_MS,
}, async (t) => {
  // 1. Liveness is a precondition: Linux must never pass by skipping recovery.
  const supported = procfsLiveness().startTimeOf(process.pid) !== "unsupported";
  if (process.platform === "linux") {
    assert.ok(
      supported,
      "procfs liveness must be supported on Linux: the capstone cannot pass by skipping recovery",
    );
  }

  // 2–3. Start, holding the second report at acceptance; the host announces itself first.
  const run = capstone(t);
  const { repo, commit: C1, tree: T1 } = run.subject();
  const start = run.spawnDoor("start", ["start", "--repo", repo, "--ref", REF, "--json"], {
    holds: [holdFile("acceptance", 2)],
  });
  const announced = await waitForGate(start, (gate) => gate.hosts.length === 1);
  const [host] = announced.hosts;
  assert.ok(host !== undefined);

  // 4. Without a liveness seam the dead holder can never be proved dead: fail closed, visibly.
  if (!supported) {
    await waitForGate(start, (gate) => countAt(gate, "acceptance") >= 2);
    // The hold keeps this host from finishing, so while its door runs the pid is still its own.
    assert.equal(start.result(), undefined, "the held door is still running");
    process.kill(host.pid, "SIGKILL");
    const killed = await start.exited;
    const id = failureOf(killed).execution_id;
    assert.ok(id !== undefined, "the door names the execution");
    const busy = envelopeOf(await run.door("status", ["status", id, "--json"]));
    assert.equal(busy.outcome, "owner_busy");
    assert.equal(busy.epoch, 1);
    row(t, "G1", "liveness", "unsupported");
    t.skip(
      "procfs liveness unsupported: recovery not exercised (design §16 requires a supported host for PASS)",
    );
    return;
  }

  // 5. Both reports reached acceptance, the first was accepted and settling, all in this host.
  const held = await waitForGate(
    start,
    (gate) => countAt(gate, "acceptance") >= 2 && countAt(gate, "settle") >= 1,
  );
  assert.ok(host.startTime !== null, "procfs names the host's start time");
  const identity: Identity = { pid: host.pid, startTime: host.startTime };
  for (const verify of held.verifies) {
    assert.equal(verify.pid, host.pid, "every verification ran in the announced host");
    assert.equal(verify.tree, T1, "every verification is over the subject");
  }
  assert.equal(countAt(held, "attempt-start"), 2);

  // 6. The held host owns epoch 1 of exactly one execution.
  const id = executionOfOwner(host.pid);
  run.learn(id);
  const store = join(executionsDir(), id);
  const busyResult = await run.door("status-busy", ["status", id, "--json"]);
  assert.equal(busyResult.code, 1);
  const busy = envelopeOf(busyResult);
  assert.equal(busy.outcome, "owner_busy");
  assert.equal(busy.epoch, 1);
  assert.equal(busy.status, null);

  // 7. The kill: the door reports the dead host and names the execution and its recovery.
  assert.ok(killIdentity(identity), "the held host is signalled by identity");
  const killed = await start.exited;
  assert.equal(killed.code, 1);
  const failure = failureOf(killed);
  assert.equal(failure.error_type, "v2_host_failed");
  assert.equal(failure.execution_id, id);
  for (const fragment of ["exited -9", `perk v2 status ${id}`, `perk v2 run ${id}`]) {
    assert.ok(failure.message.includes(fragment), `the failure names ${fragment}`);
  }
  assert.ok(isDead(identity), "the killed host is dead");

  // 8. The dead holder's epoch stays unreleased as its record.
  assert.deepEqual(
    (await ownerEpochs(store)).map((epoch) => [epoch.epoch, epoch.released, epoch.meta.pid]),
    [[1, false, host.pid]],
  );

  // 9. After the kill: the epoch is free, the first report's outcome survived, the second is open.
  const afterKillResult = await run.door("status-after-kill", ["status", id, "--json"]);
  assert.equal(afterKillResult.code, 0);
  const afterKill = envelopeOf(afterKillResult);
  assert.equal(afterKill.outcome, "ok");
  assert.equal(afterKill.epoch, 2);
  const retainedView = viewOf(afterKill);
  assert.equal(retainedView.state, "running");
  assert.equal(retainedView.waitReason, null);
  assert.equal(retainedView.diagnostics.runnable, true);
  assert.deepEqual(
    {
      seq: retainedView.observation?.seq,
      repo: retainedView.observation?.repo,
      ref: retainedView.observation?.ref,
      commit: retainedView.observation?.commit,
      tree: retainedView.observation?.tree,
    },
    { seq: 1, repo: realpathSync(repo), ref: REF, commit: C1, tree: T1 },
  );
  assert.equal(retainedView.assignments.length, 2);
  for (const assignment of retainedView.assignments) {
    assert.equal(assignment.current, true);
    assert.equal(assignment.subjectDigest, T1);
    onlyAttempt(assignment);
  }
  const acceptedAtKill = retainedView.assignments.filter((a) => a.acceptedOutcomeId !== null);
  assert.equal(acceptedAtKill.length, 1, "exactly the first report was accepted");
  const [first] = acceptedAtKill;
  const second = retainedView.assignments.find((a) => a.acceptedOutcomeId === null);
  assert.ok(first !== undefined && second !== undefined);
  assert.equal(onlyAttempt(second).ending, null, "the second attempt has no ending");
  const firstEndingAtKill = onlyAttempt(first).ending?.end ?? null;
  assert.ok(
    firstEndingAtKill === "accepted" || firstEndingAtKill === null,
    `the first ending is accepted or not landed: ${String(firstEndingAtKill)}`,
  );
  const firstOutcomeId = first.acceptedOutcomeId;
  const epochsAtKill = await ownerEpochs(store);
  const epochOne = epochsAtKill.find((epoch) => epoch.epoch === 1);
  row(t, "G1", "roles", { first: first.role, second: second.role });
  row(t, "G1", "retained", {
    epoch: afterKill.epoch,
    state: retainedView.state,
    acceptedOutcomes: acceptedAtKill.length,
    firstOutcomeId,
    attempts: retainedView.assignments.reduce((sum, a) => sum + a.attempts.length, 0),
    observationSeq: retainedView.observation?.seq,
    firstEndingAtKill,
    epoch1: { released: epochOne?.released, pidIsKilledHost: epochOne?.meta.pid === host.pid },
  });

  // 10. Recovery: one `run` passes the gate, recovers the second report and opens the decision.
  const rec = await run.door("run", ["run", id, "--json"]);
  assert.equal(rec.code, 0, rec.stderr);
  const recovered = envelopeOf(rec);
  assert.equal(recovered.outcome, "pending_decision");
  assert.equal(recovered.epoch, 3);
  const recoveredView = viewOf(recovered);
  assert.equal(recoveredView.observation?.seq, 2);
  assert.equal(recoveredView.observation?.commit, C1);
  assert.equal(recoveredView.observation?.tree, T1);
  assert.equal(recoveredView.assignments.length, 2);
  for (const assignment of recoveredView.assignments) {
    assert.ok(assignment.acceptedOutcomeId !== null, `${assignment.role} is accepted`);
    assert.equal(onlyAttempt(assignment).ending?.end, "accepted");
  }
  assert.equal(
    recoveredView.assignments.find((a) => a.role === first.role)?.acceptedOutcomeId,
    firstOutcomeId,
    "the first report's outcome is unchanged",
  );
  const decision = recoveredView.decision;
  assert.ok(decision !== null, "a decision opened");
  assert.deepEqual(
    {
      subjectDigest: decision.subjectDigest,
      allowedActions: decision.allowedActions,
      actor: decision.actor,
    },
    { subjectDigest: T1, allowedActions: ["approve", "reject"], actor: "human:cli" },
  );

  // 11. Work repeated, from the gate logs: the recovery host replayed only the second report.
  const startGate = readGate(start.gate);
  const recGate = readGate(rec.gate);
  assert.equal(recGate.hosts.length, 1);
  const [recHost] = recGate.hosts;
  assert.ok(recHost !== undefined);
  assert.notEqual(recHost.pid, host.pid, "recovery ran in a new host");
  for (const verify of recGate.verifies) assert.equal(verify.pid, recHost.pid);
  assert.equal(countAt(recGate, "attempt-start"), 0, "no attempt restarted");
  assert.equal(countAt(recGate, "acceptance"), 1, "only the second report's tool replayed");
  assert.equal(countAt(recGate, "settle"), firstEndingAtKill === null ? 2 : 1);
  assert.equal(countAt(startGate, "attempt-start"), 2, "the instrument saw both attempt starts");
  assert.equal(countAt(startGate, "acceptance"), 2, "the instrument saw both acceptances");
  assert.ok(countAt(startGate, "settle") >= 1, "the instrument saw the first settle");

  // 12. The wait, explained.
  const waiting = envelopeOf(await run.door("status-waiting", ["status", id, "--json"]));
  assert.equal(waiting.outcome, "ok");
  assert.equal(viewOf(waiting).state, "waiting");
  assert.equal(viewOf(waiting).waitReason, "pending_decision");
  assert.deepEqual(viewOf(waiting).decision, decision);
  const human = await run.door("status-human", ["status", id]);
  assert.equal(human.code, 0, human.stderr);
  for (const line of [
    "state: waiting (pending_decision)",
    `decision ${decision.decisionId}: reply with \`perk v2 reply ${id} ${decision.decisionId} <action>\` (actions: approve|reject)`,
  ]) {
    assert.ok(human.stderr.includes(line), `status explains the wait: ${line}`);
  }

  // 13. A tree-unchanged commit is a new observation of the same subject, not a stale one.
  fixtureGit(repo, ["commit", "-q", "--allow-empty", "-m", "c2"]);
  const C2 = fixtureGit(repo, ["rev-parse", "HEAD"]).toString("utf8").trim();
  assert.notEqual(C2, C1);
  assert.equal(treeOf(repo, C2), T1);

  // 14. Reply completes the execution with one continuation; a repeat replays the receipt.
  const replyArgs = ["reply", id, decision.decisionId, "approve", "--json"];
  const repliedResult = await run.door("reply", replyArgs);
  assert.equal(repliedResult.code, 0, repliedResult.stderr);
  const replied = envelopeOf(repliedResult);
  assert.equal(replied.outcome, "ok");
  assert.equal(viewOf(replied).state, "completed");
  assert.equal(viewOf(replied).observation?.commit, C2);
  assert.equal(viewOf(replied).observation?.tree, T1);
  const receipt = replied.receipt;
  assert.ok(receipt !== null && receipt.kind === "reply", "a reply receipt");
  const continuation = receipt.continuation;
  assert.ok(continuation !== null, "the receipt names its continuation");
  assert.equal(typeof continuation.opId, "string");
  assert.equal(typeof continuation.taskId, "number");
  const again = envelopeOf(await run.door("reply-again", replyArgs));
  assert.equal(again.outcome, "ok");
  assert.deepEqual(again.receipt, receipt, "a repeated reply replays the same receipt");
  assert.equal(viewOf(again).state, "completed");
  const done = envelopeOf(await run.door("status-done", ["status", id, "--json"]));
  assert.equal(done.outcome, "ok");
  assert.equal(viewOf(done).state, "completed");
  assert.equal(viewOf(done).decision, null);

  // 15. Epochs: the dead holder's stays unreleased; every later lock-taking call released its own.
  const epochs = await ownerEpochs(store);
  assert.deepEqual(
    epochs.map((epoch) => epoch.epoch),
    [1, 2, 3, 4, 5, 6, 7, 8],
    "status, run, status, status, reply, reply, status after the kill",
  );
  const [dead, ...later] = epochs;
  assert.ok(dead !== undefined);
  assert.equal(dead.released, false);
  assert.equal(dead.meta.pid, host.pid);
  for (const epoch of later) assert.equal(epoch.released, true, `epoch ${epoch.epoch} released`);
  row(
    t,
    "G1",
    "epochs",
    epochs.map((epoch) => [epoch.epoch, epoch.released]),
  );

  // 16. The store census (after the epoch census: a records read takes an epoch of its own).
  const records = (await recordsOf(capstoneHostOptions(store, id))).records;
  const counts = countByType(records);
  const { observation, ...pinned } = counts;
  assert.deepEqual(pinned, {
    assignment: 2,
    attempt: 2,
    "report-outcome": 2,
    "aggregate-outcome": 1,
    decision: 1,
    reply: 1,
    continuation: 1,
    cancellation: 0,
  });
  const continuationTasks = await storeTasks(store, CONTINUATION_TASK_NAME);
  assert.equal(continuationTasks.length, 1, "exactly one continuation task");
  assert.equal(continuationTasks[0]?.id, continuation.taskId);
  assertCompleted(continuationTasks[0], "the continuation");
  const reportTasks = await storeTasks(store, FIXTURE_REPORT_TASK_NAME);
  assert.equal(reportTasks.length, 2, "two fixture-report tasks: no attempt was relaunched");
  for (const task of reportTasks) assertCompleted(task, `fixture-report task ${task.id}`);
  const perWorker = await workerCensus(store);
  assert.deepEqual(perWorker, [
    { submissions: 1, assistantTurns: 1, reportResults: 1 },
    { submissions: 1, assistantTurns: 1, reportResults: 1 },
  ]);
  row(t, "G1", "repeated", {
    verify: { killed: perPoint(startGate), recovery: perPoint(recGate) },
    perWorker,
    fixtureReportTasks: reportTasks.length,
    attemptsPerAssignment: recoveredView.assignments.map((a) => a.attempts.length),
  });
  row(t, "G1", "records", { ...pinned, observation, continuationTasks: continuationTasks.length });
  row(t, "G1", "recovery", {
    doorFailure: failure.error_type,
    hintNamesStatusAndRun: true,
    recoveryCommands: ["run"],
    inspectionCommands: ["status"],
    storeEdits: 0,
  });
  row(t, "G1", "timing", run.timings());
});
