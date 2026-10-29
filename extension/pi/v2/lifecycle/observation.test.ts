// The git observer behind the host's `Observe` seam (docs/design/pi-durable-v2-foundations.md §5,
// §8), over real temp repos and real SQLite stores: S5 an unresolvable ref or a missing repo is
// `observation_failed` and records nothing, and S6 a same-tree commit is a new observation of the
// same subject while a new tree is a new subject with its own assignments and decision.

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, realpathSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { readStatus, runHost } from "../host.ts";
import { gitObserver } from "../subject/observe.ts";
import { SUBJECTS_DIR, snapshotManifestPath } from "../subject/snapshot.ts";
import { assertSameRecords, assignmentIdOf, decisionIdOf, ofType } from "../testing/binding.ts";
import { CASE_TIMEOUT_MS, tempDir } from "../testing/durable.ts";
import { expectIncompatible, expectQuiescent, expectStatus, hostOptions } from "../testing/host.ts";
import {
  commitAll,
  commitIndex,
  fixtureGit,
  gitRepo,
  subjectStore,
  treeOf,
  writeFiles,
} from "../testing/subject.ts";

const REF = "refs/heads/main";

function snapshotNames(store: string): string[] {
  return readdirSync(join(store, SUBJECTS_DIR)).sort();
}

test("S5 (host): a start over a missing repo is observation_failed and creates no manifest or subject", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await subjectStore(t);
  const options = hostOptions(store);
  const missing = join(await tempDir(t, "perk-v2-subject-missing-"), "absent");
  const outcome = await runHost(options, {
    type: "start",
    observe: gitObserver({ storeDir: store, repo: missing, ref: REF }),
  });
  assert.equal(outcome.kind, "observation_failed");
  if (outcome.kind === "observation_failed") assert.match(outcome.detail, /is missing/);
  expectIncompatible(await readStatus(options), "manifest_missing");
  assert.equal(existsSync(join(store, SUBJECTS_DIR)), false);
});

test("S5 (host): a run after the tracked ref is deleted is observation_failed and records nothing", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const repo = await gitRepo(t);
  writeFiles(repo, { "a.txt": "a\n" });
  commitAll(repo, "c1");
  const store = await subjectStore(t);
  const options = hostOptions(store);
  const observe = gitObserver({ storeDir: store, repo, ref: REF });
  expectQuiescent(await runHost(options, { type: "start", observe }));
  const before = expectStatus(await readStatus(options)).view.records.records;

  fixtureGit(repo, ["update-ref", "-d", REF]);
  const outcome = await runHost(options, { type: "run", observe });
  assert.equal(outcome.kind, "observation_failed");
  if (outcome.kind === "observation_failed") {
    assert.match(outcome.detail, /does not resolve to a commit/);
  }
  const after = expectStatus(await readStatus(options)).view.records.records;
  assertSameRecords(after, before, "nothing recorded");
});

test("S6 (host): a same-tree commit is a new observation of the same subject; a new tree is a new subject", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const repo = await gitRepo(t);
  writeFiles(repo, { "a.txt": "one\n" });
  const c1 = commitAll(repo, "c1");
  const t1 = treeOf(repo, c1);
  const store = await subjectStore(t);
  const options = hostOptions(store);
  const observe = gitObserver({ storeDir: store, repo, ref: REF });

  const started = expectQuiescent(await runHost(options, { type: "start", observe }));
  assert.equal(started.view.waitReason, "pending_decision");
  const [first] = ofType(started.view.records.records, "observation");
  assert.ok(first !== undefined);
  const { opId: _opId, observedAt: _observedAt, ...firstFacts } = first;
  assert.deepEqual(firstFacts, {
    type: "observation",
    seq: 1,
    repo: realpathSync(repo),
    ref: REF,
    commit: c1,
    tree: t1,
    manifestDigest: createHash("sha256")
      .update(readFileSync(snapshotManifestPath(store, t1)))
      .digest("hex"),
  });
  const t1Assignments = [assignmentIdOf("a", t1), assignmentIdOf("b", t1)].sort();
  const assignmentIds = (records: typeof started.view.records.records) =>
    ofType(records, "assignment")
      .map((record) => record.assignmentId)
      .sort();
  assert.deepEqual(assignmentIds(started.view.records.records), t1Assignments);
  for (const outcome of ofType(started.view.records.records, "report-outcome")) {
    assert.equal(outcome.verifiedDigest, first.manifestDigest, "accepted with the real digest");
  }

  const c2 = commitIndex(repo, "c2, same tree");
  const ran = expectQuiescent(await runHost(options, { type: "run", observe }));
  const observations = ofType(ran.view.records.records, "observation").sort(
    (a, b) => a.seq - b.seq,
  );
  assert.deepEqual(
    observations.map((record) => [record.seq, record.commit, record.tree, record.manifestDigest]),
    [
      [1, c1, t1, first.manifestDigest],
      [2, c2, t1, first.manifestDigest],
    ],
  );
  assert.deepEqual(assignmentIds(ran.view.records.records), t1Assignments, "no new admission");
  assert.deepEqual(snapshotNames(store), [t1, `${t1}.manifest`]);

  writeFiles(repo, { "a.txt": "two\n" });
  const c3 = commitAll(repo, "c3");
  const t3 = treeOf(repo, c3);
  const changed = expectQuiescent(await runHost(options, { type: "run", observe }));
  const latest = ofType(changed.view.records.records, "observation").find(
    (record) => record.seq === 3,
  );
  assert.ok(latest !== undefined);
  assert.deepEqual([latest.commit, latest.tree], [c3, t3]);
  assert.notEqual(latest.manifestDigest, first.manifestDigest);
  assert.deepEqual(
    assignmentIds(changed.view.records.records),
    [...t1Assignments, assignmentIdOf("a", t3), assignmentIdOf("b", t3)].sort(),
  );
  assert.equal(changed.view.waitReason, "pending_decision");
  assert.ok(
    ofType(changed.view.records.records, "decision").some(
      (record) => record.decisionId === decisionIdOf(t3) && record.subjectDigest === t3,
    ),
    "the pending decision is over the new tree",
  );
  assert.deepEqual(snapshotNames(store), [t1, `${t1}.manifest`, t3, `${t3}.manifest`].sort());
});
