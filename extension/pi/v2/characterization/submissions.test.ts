// Durable characterization — P4 (Perk mints identity, deterministically),
// docs/design/pi-durable-v2-foundations.md §3 P4 and §4 (the identity model). A submission's
// `requestId` is its deduplication key per conversation: a repeat with the same key and type
// returns the original submission without a write or a second run — before and after a reopen —
// and the type is the only payload Durable compares.
//
// Upstream evidence (packages/durable at the mirrored 1.4.0 pin):
// src/harness/submissions.ts::admitSubmission (`tx.submissionByRequest`);
// test/harness-submissions.test.ts::"deduplicates request IDs per conversation before any write"
// and ::"reacquires a submission after reopen and settles it durably".

import assert from "node:assert/strict";
import { test } from "node:test";
import { fauxAssistantMessage } from "@earendil-works/pi-ai/providers/faux";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import {
  CASE_TIMEOUT_MS,
  context,
  counting,
  fauxSetup,
  flush,
  open,
  sqlitePath,
} from "../testing/durable.ts";

test("D6 (P4): submissions are deduplicated by requestId", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const path = await sqlitePath(t);
  const setup = fauxSetup();
  setup.faux.setResponses([fauxAssistantMessage("answer one")]);
  const { storage, commits } = counting(await openNodeSqliteStorage(path));
  const first = await open(t, storage, setup);
  first.harness.resume();

  const original = await first.root.submit(
    { type: "input", content: "op", requestId: "perk:op-1" },
    context,
  );
  assert.equal((await original.wait(context)).status, "done");
  const committed = commits();
  assert.equal(setup.faux.state.callCount, 1);

  // The same key with another payload is the same submission: no write, no run.
  const again = await first.root.submit(
    { type: "input", content: "DIFFERENT", requestId: "perk:op-1" },
    context,
  );
  assert.equal(again.id, original.id);
  for (let turn = 0; turn < 3; turn++) await flush();
  assert.equal(commits(), committed, "the duplicate wrote nothing");
  assert.equal(setup.faux.state.callCount, 1, "the duplicate started no run");
  assert.equal(setup.faux.getPendingResponseCount(), 0);
  // The type is the one field Durable compares.
  await assert.rejects(
    first.root.submit({ type: "write", entry: { kind: "note" }, requestId: "perk:op-1" }, context),
    /already identifies a submission of type input/,
  );
  await first.dispose();

  // After a reopen the key still resolves to the settled original.
  const second = await open(t, await openNodeSqliteStorage(path), setup);
  const reacquired = await second.root.submit(
    { type: "input", content: "op", requestId: "perk:op-1" },
    context,
  );
  assert.equal(reacquired.id, original.id);
  const stored = await second.harness.submission(original.id, context);
  assert.ok(stored, "the original is reacquirable after reopen");
  assert.equal((await stored.status(context)).status, "done");
  assert.equal(setup.faux.state.callCount, 1, "the reopened duplicate started no run");

  // A different key is a new submission.
  setup.faux.setResponses([fauxAssistantMessage("answer two")]);
  second.harness.resume();
  const other = await second.root.submit(
    { type: "input", content: "op", requestId: "perk:op-2" },
    context,
  );
  assert.notEqual(other.id, original.id);
  assert.equal((await other.wait(context)).status, "done");
  assert.equal(setup.faux.state.callCount, 2);
});
