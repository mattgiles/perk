// G2–G4 (design §16; P1, P2, P3) — the capstone's variants through the real door, each over its own
// temp git subject changed with plain git only:
//   G2: live edits during running assignments — a commit, an uncommitted edit and an untracked file
//       land while both reports are held at acceptance — leave both verified digests on the
//       originally observed snapshot, and materialize nothing for the live tree.
//   G3: a tree-changing commit makes `reply` stale (refused, nothing recorded), and a revert to the
//       subject's tree — a different commit with the same tree — is not stale.
//   G4: after `cancel`, nothing further is admitted: a reply is refused `cancelled`, and a `run`
//       over a changed tree records the observation and admits no assignment.

import assert from "node:assert/strict";
import { existsSync, readdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { holdFile } from "../door/testGate.ts";
import { FIXTURE_REPORT_TASK_NAME } from "../durable/assignment.ts";
import { CONTINUATION_TASK_NAME } from "../durable/continuation.ts";
import {
  MANIFEST_SUFFIX,
  SUBJECTS_DIR,
  snapshotDir,
  snapshotManifestPath,
} from "../subject/snapshot.ts";
import { ofType, REF } from "../testing/binding.ts";
import {
  capstone,
  capstoneHostOptions,
  countAt,
  envelopeOf,
  executionOfOwner,
  executionsDir,
  row,
  viewOf,
  waitForGate,
} from "../testing/capstone.ts";
import { recordsOf, storeTasks } from "../testing/decision.ts";
import { commitAll, fixtureGit, readTree, treeOf, writeFiles } from "../testing/subject.ts";
import { SUBJECT_FILES } from "../testing/worker.ts";

const CASE_MS = 180_000;

/** The snapshot trees materialized in a store (temp directories and manifests excluded). */
function snapshotTrees(store: string): string[] {
  return readdirSync(join(store, SUBJECTS_DIR))
    .filter((name) => !name.startsWith(".") && !name.endsWith(MANIFEST_SUFFIX))
    .sort();
}

test("G2: live edits during running assignments leave both verified digests on the observed snapshot", {
  timeout: CASE_MS,
}, async (t) => {
  const run = capstone(t);
  const { repo, commit: C1, tree: T1 } = run.subject();
  const holds = [holdFile("acceptance", 1), holdFile("acceptance", 2)];
  const start = run.spawnDoor("start", ["start", "--repo", repo, "--ref", REF, "--json"], {
    holds,
  });
  const held = await waitForGate(
    start,
    (gate) => gate.hosts.length === 1 && countAt(gate, "acceptance") === 2,
  );
  const [host] = held.hosts;
  assert.ok(host !== undefined);
  const id = executionOfOwner(host.pid);
  run.learn(id);
  const store = join(executionsDir(), id);

  // Both reports are in flight: the live checkout moves on underneath them.
  writeFiles(repo, { "a.txt": "edited and committed\n" });
  const C2 = commitAll(repo, "c2");
  const T2 = treeOf(repo, C2);
  assert.notEqual(T2, T1);
  writeFiles(repo, { "dir/b.ts": "edited, uncommitted\n", "new.txt": "untracked\n" });
  for (const hold of holds) rmSync(join(start.gate, hold));

  const started = await start.exited;
  assert.equal(started.code, 0, started.stderr);
  const envelope = envelopeOf(started);
  assert.equal(envelope.outcome, "pending_decision");
  const view = viewOf(envelope);
  const observation = view.observation;
  assert.ok(observation !== null);
  assert.deepEqual(
    { seq: observation.seq, commit: observation.commit, tree: observation.tree },
    { seq: 1, commit: C1, tree: T1 },
  );
  const D1 = observation.manifestDigest;
  assert.equal(view.assignments.length, 2);
  for (const assignment of view.assignments) {
    assert.equal(assignment.subjectDigest, T1);
    assert.ok(assignment.acceptedOutcomeId !== null, `${assignment.role} is accepted`);
  }

  const outcomes = ofType(
    (await recordsOf(capstoneHostOptions(store, id))).records,
    "report-outcome",
  );
  assert.equal(outcomes.length, 2);
  for (const outcome of outcomes) {
    assert.equal(outcome.verifiedDigest, D1, "verified against the observed snapshot");
    assert.equal(outcome.report.subjectDigest, T1);
  }

  const files = readTree(snapshotDir(store, T1))
    .filter((node) => node.kind !== "dir")
    .map((node) => [node.path, node.kind, node.bytes?.toString("utf8")]);
  assert.deepEqual(
    files,
    Object.entries(SUBJECT_FILES)
      .sort(([a], [b]) => Buffer.compare(Buffer.from(a), Buffer.from(b)))
      .map(([path, content]) => [path, "file", content]),
    "the snapshot holds exactly the committed subject",
  );
  assert.equal(existsSync(snapshotDir(store, T2)), false, "no snapshot of the live tree");
  assert.equal(existsSync(snapshotManifestPath(store, T2)), false, "no manifest of the live tree");
  const trees = snapshotTrees(store);
  assert.deepEqual(trees, [T1]);
  row(t, "G2", "digests", {
    observed: D1,
    verified: outcomes.map((outcome) => outcome.verifiedDigest),
    liveTree: T2,
    snapshotTrees: trees,
  });
});

test("G3: a tree-changing commit makes reply stale; a revert to the subject's tree does not", {
  timeout: CASE_MS,
}, async (t) => {
  const run = capstone(t);
  const { repo, commit: C1, tree: T1 } = run.subject();
  const started = envelopeOf(
    await run.door("start", ["start", "--repo", repo, "--ref", REF, "--json"]),
  );
  assert.equal(started.outcome, "pending_decision");
  const id = started.executionId;
  const decision = viewOf(started).decision;
  assert.ok(decision !== null);
  const replyArgs = ["reply", id, decision.decisionId, "approve", "--json"];

  writeFiles(repo, { "a.txt": "changed\n" });
  const C2 = commitAll(repo, "c2");
  assert.notEqual(treeOf(repo, C2), T1);

  const staleResult = await run.door("reply-stale", replyArgs);
  assert.equal(staleResult.code, 1);
  const stale = envelopeOf(staleResult);
  assert.equal(stale.outcome, "refused");
  assert.equal(stale.refusal?.reason, "stale_subject");
  assert.equal(stale.status, null);

  const status = envelopeOf(await run.door("status", ["status", id, "--json"]));
  assert.equal(status.outcome, "ok");
  const waiting = viewOf(status);
  assert.equal(waiting.state, "waiting");
  assert.equal(waiting.waitReason, "pending_decision");
  assert.equal(waiting.observation?.seq, 1, "the refused reply recorded nothing");
  assert.equal(waiting.observation?.commit, C1);
  assert.deepEqual(waiting.decision, decision);

  fixtureGit(repo, ["revert", "--no-edit", "HEAD"]);
  const C3 = fixtureGit(repo, ["rev-parse", "HEAD"]).toString("utf8").trim();
  assert.equal(treeOf(repo, C3), T1);
  assert.notEqual(C3, C1);

  const repliedResult = await run.door("reply", replyArgs);
  assert.equal(repliedResult.code, 0, repliedResult.stderr);
  const replied = envelopeOf(repliedResult);
  assert.equal(replied.outcome, "ok");
  const completed = viewOf(replied);
  assert.equal(completed.state, "completed");
  assert.deepEqual(
    {
      seq: completed.observation?.seq,
      commit: completed.observation?.commit,
      tree: completed.observation?.tree,
    },
    { seq: 2, commit: C3, tree: T1 },
  );
  assert.ok(replied.receipt?.continuation, "the receipt names its continuation");
  row(t, "G3", "stale", {
    refusal: stale.refusal?.reason,
    observationSeqAfterRefusal: waiting.observation?.seq,
    revertTreeEqualsSubject: treeOf(repo, C3) === T1,
    replyAfterRevert: replied.outcome,
    state: completed.state,
  });
});

test("G4: after cancel, nothing further is admitted", {
  timeout: CASE_MS,
}, async (t) => {
  const run = capstone(t);
  const { repo, tree: T1 } = run.subject();
  const started = envelopeOf(
    await run.door("start", ["start", "--repo", repo, "--ref", REF, "--json"]),
  );
  assert.equal(started.outcome, "pending_decision");
  const id = started.executionId;
  const decision = viewOf(started).decision;
  assert.ok(decision !== null);
  const originals = viewOf(started).assignments.map((assignment) => assignment.assignmentId);
  const store = join(executionsDir(), id);

  const cancelResult = await run.door("cancel", ["cancel", id, "--json"]);
  assert.equal(cancelResult.code, 0, cancelResult.stderr);
  const cancelled = envelopeOf(cancelResult);
  assert.equal(cancelled.outcome, "ok");
  assert.equal(viewOf(cancelled).state, "cancelled");
  assert.equal(cancelled.receipt?.kind, "cancellation");
  assert.equal(cancelled.receipt?.continuation, null);
  assert.equal(viewOf(cancelled).decision, null);
  assert.deepEqual(viewOf(cancelled).cancellation, { reason: "cancelled via perk v2 cancel" });

  const replyResult = await run.door("reply", [
    "reply",
    id,
    decision.decisionId,
    "approve",
    "--json",
  ]);
  assert.equal(replyResult.code, 1);
  const refused = envelopeOf(replyResult);
  assert.equal(refused.outcome, "refused");
  assert.equal(refused.refusal?.reason, "cancelled");

  writeFiles(repo, { "a.txt": "changed\n" });
  const C2 = commitAll(repo, "c2");
  const T2 = treeOf(repo, C2);
  assert.notEqual(T2, T1);

  const ranResult = await run.door("run", ["run", id, "--json"]);
  assert.equal(ranResult.code, 0, ranResult.stderr);
  const ran = envelopeOf(ranResult);
  assert.equal(ran.outcome, "ok");
  const view = viewOf(ran);
  assert.equal(view.state, "cancelled");
  assert.deepEqual(
    { seq: view.observation?.seq, tree: view.observation?.tree, commit: view.observation?.commit },
    { seq: 2, tree: T2, commit: C2 },
  );
  assert.deepEqual(
    view.assignments.map((assignment) => assignment.assignmentId),
    originals,
    "exactly the two original assignments",
  );
  for (const assignment of view.assignments) {
    assert.equal(assignment.subjectDigest, T1);
    assert.equal(assignment.current, false);
    assert.equal(assignment.attempts.length, 1);
  }
  assert.equal(view.decision, null);
  assert.equal(view.diagnostics.runnable, false);

  const reportTasks = await storeTasks(store, FIXTURE_REPORT_TASK_NAME);
  const continuationTasks = await storeTasks(store, CONTINUATION_TASK_NAME);
  assert.equal(reportTasks.length, 2);
  assert.equal(continuationTasks.length, 0);
  row(t, "G4", "cancel", {
    replyRefusal: refused.refusal?.reason,
    observationSeqAfterRun: view.observation?.seq,
    assignments: view.assignments.length,
    currentAssignments: view.assignments.filter((assignment) => assignment.current).length,
    fixtureReportTasks: reportTasks.length,
    continuationTasks: continuationTasks.length,
  });
});
