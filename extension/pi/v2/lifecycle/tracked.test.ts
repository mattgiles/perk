// V4 — observation follows the tracked ref (docs/design/pi-durable-v2-foundations.md §8, §10 the
// host, contracts.md §8.77): `start`'s observer receives `null`, while `run`'s and `reply`'s receive
// exactly the `{repo, ref}` of the `seq` 1 observation, read from the records; the door's tracked
// observer, over a real fixture repo, records observations naming the original repo and ref, and
// fails to observe when no tracked ref is handed to it.

import assert from "node:assert/strict";
import { test } from "node:test";
import { trackedObserver } from "../door/cli.ts";
import { runHost } from "../host.ts";
import { gitObserver } from "../subject/observe.ts";
import { C1B, decisionIdOf, ofType, REF, REPO, T1 } from "../testing/binding.ts";
import { replyVerb } from "../testing/decision.ts";
import { CASE_TIMEOUT_MS } from "../testing/durable.ts";
import {
  expectQuiescent,
  HOST_NOW,
  hostOptions,
  observed,
  spyObserve,
  storeIn,
} from "../testing/host.ts";
import { commitAll, treeOf, writeFiles } from "../testing/subject.ts";
import { fixtureSubject } from "../testing/worker.ts";

test("V4: start observes with null; run and reply observe the seq 1 observation's repo and ref", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = hostOptions(store);
  const start = spyObserve(observed());
  expectQuiescent(await runHost(options, { type: "start", observe: start.observe }));
  assert.deepEqual(start.seen(), [null]);

  const tracked = { repo: REPO, ref: REF };
  const run = spyObserve(observed(T1, C1B));
  expectQuiescent(await runHost(options, { type: "run", observe: run.observe }));
  assert.deepEqual(run.seen(), [tracked]);

  const reply = spyObserve(observed());
  expectQuiescent(await runHost(options, replyVerb(reply.observe, decisionIdOf(T1))));
  assert.deepEqual(reply.seen(), [tracked]);
});

test("V4: the door's tracked observer records observations naming the original repo and ref", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { repo, store } = await fixtureSubject(t);
  const options = hostOptions(store);
  const now = () => HOST_NOW;
  const started = expectQuiescent(
    await runHost(options, {
      type: "start",
      observe: gitObserver({ storeDir: store, repo, ref: REF, now }),
    }),
  );
  const [first] = ofType(started.view.records.records, "observation");
  assert.ok(first !== undefined);

  writeFiles(repo, { "a.txt": "changed\n" });
  const tree = treeOf(repo, commitAll(repo, "c2"));
  const ran = expectQuiescent(
    await runHost(options, { type: "run", observe: trackedObserver(store, now) }),
  );
  const observations = ofType(ran.view.records.records, "observation");
  assert.equal(observations.length, 2);
  for (const observation of observations) {
    assert.equal(observation.repo, first.repo, "the original repo");
    assert.equal(observation.ref, REF, "the original ref");
  }
  assert.equal(observations[1]?.tree, tree, "the new tree at the tracked ref");
  assert.equal(observations[1]?.observedAt, HOST_NOW);
});

test("V4: the tracked observer handed no tracked ref fails to observe", async (t) => {
  const store = await storeIn(t);
  assert.deepEqual(await trackedObserver(store, () => HOST_NOW)(null), {
    kind: "observation_failed",
    detail: "the execution records no tracked ref",
  });
});
