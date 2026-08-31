// Direct feature tests for the review-feedback finalization operation (delivery/address.ts):
// call-order recorders over fake ports + the memory session pin the ordering policy
// (publish → resolve → corroborate → record → decide), the atomicity negatives (no resolve
// after a failed publish; no record on any non-completed arm; no attempt burn on a resolve
// failure), the fates/retry matrix, and the ok-arm corroboration guard. OFFLINE — no Pi.

import assert from "node:assert/strict";
import { test } from "node:test";
import { openMemoryWorkflowSession } from "../session/memoryWorkflowSession.ts";
import {
  type AddressFinalization,
  type FinalizeAddressDeps,
  finalizeAddress,
  type ResolveThreadsAttempt,
  type ThreadResultRow,
} from "./address.ts";
import type { ConflictAttempts, PublishAttempt, PublishedChange } from "./submit.ts";

const CHANGE: PublishedChange = {
  pr: { number: 42, url: "u/pr/42", is_draft: true, existed: false },
  branch: "plan-7",
  base: "main",
  mergeable: true,
  conflicts: [],
};

function rowsOf(...rows: [string, boolean, boolean][]): ThreadResultRow[] {
  return rows.map(([thread_id, success, comment_added]) => ({
    thread_id,
    success,
    comment_added,
    error: null,
  }));
}

function world(opts: {
  publish?: PublishAttempt;
  resolve?: ResolveThreadsAttempt;
  attemptsValue?: number;
}) {
  // ONE shared recorder across every port INCLUDING the conflict-attempts capability, so the
  // ordering pins can see the decision itself (attempts.read/attempts.write ride `calls`), not
  // merely the ports around it.
  const calls: string[] = [];
  const writes: number[] = [];
  const session = openMemoryWorkflowSession({ runId: "01RID" });
  const attempts: ConflictAttempts = {
    read() {
      calls.push("attempts.read");
      return opts.attemptsValue ?? 0;
    },
    write(next: number) {
      calls.push(`attempts.write(${next})`);
      writes.push(next);
      return true;
    },
  };
  const deps: FinalizeAddressDeps = {
    publish: async () => {
      calls.push("publish");
      return opts.publish ?? { ok: true, change: CHANGE };
    },
    readRunId: () => "01RID",
    recordImplementationPointer: () => calls.push("pointer"),
    attempts,
    resolve: async () => {
      calls.push("resolve");
      return opts.resolve ?? { ok: true, rows: rowsOf(["PRRT_1", true, true]) };
    },
    session: {
      ...session,
      apply(change) {
        calls.push(`apply(${change.kind})`);
        return session.apply(change);
      },
    },
  };
  return { deps, calls, writes, session };
}

function batch(...threads: AddressFinalization["threads"]): AddressFinalization {
  return { threads, pr: 42, counts: { actionable: 1 } };
}

// --- ordering + atomicity -------------------------------------------------------------------

test("empty batch refuses before any port with the exact text", async () => {
  const { deps, calls } = world({});
  const outcome = await finalizeAddress(deps, { threads: [] });
  assert.deepEqual(outcome, {
    kind: "empty_batch",
    message: "no threads to finalize (pass { threads: [{thread_id, comment?}] })",
  });
  assert.deepEqual(calls, [], "no ports invoked");
});

test("empty batch refuses even when the run-id read would throw (pre-effect ordering)", async () => {
  // The regression the review caught: dependency acquisition must stay lazy so the deliberately
  // throwing run-id read can never preempt the stable bad_input refusal on an empty batch.
  const { deps } = world({});
  deps.readRunId = () => {
    throw new Error("branch unreadable");
  };
  const outcome = await finalizeAddress(deps, { threads: [] });
  assert.equal(outcome.kind, "empty_batch");
});

test("publish failure ⇒ not_published with both messages; resolver NEVER invoked, no session/counter activity", async () => {
  const { deps, calls, writes, session } = world({
    publish: { ok: false, message: "drift", errorType: "remote_drift" },
    attemptsValue: 1,
  });
  const outcome = await finalizeAddress(deps, batch({ thread_id: "PRRT_1" }));
  assert.deepEqual(outcome, {
    kind: "not_published",
    publishMessage: "drift",
    message:
      "propagation failed; threads were NOT resolved — drift. " +
      "Fix the publication failure, then re-run finalize_address.",
    errorType: "remote_drift",
  });
  assert.deepEqual(calls, ["publish"], "no pointer, no resolve, no apply");
  assert.deepEqual(writes, [], "no counter activity");
  assert.equal(session.lastReviewBatchRecord(), null);
});

test("corroborated success: publish → resolve → apply → decide order pin ⇒ completed", async () => {
  const { deps, calls, session } = world({
    resolve: { ok: true, rows: rowsOf(["PRRT_1", true, true], ["PRRT_2", true, false]) },
  });
  const outcome = await finalizeAddress(
    deps,
    batch({ thread_id: "PRRT_1", comment: "Fixed" }, { thread_id: "PRRT_2" }),
  );
  assert.ok(outcome.kind === "completed");
  // The clean arm's full event trace: verified-success updates (pointer; the reset check reads
  // once and short-circuits on a clean counter), then resolve → apply; a clean change's
  // decision emits NO counter events — nothing follows the record.
  assert.deepEqual(calls, [
    "publish",
    "pointer",
    "attempts.read",
    "resolve",
    "apply(record-review-batch)",
  ]);
  assert.deepEqual(outcome.resolvedThreadIds, ["PRRT_1", "PRRT_2"]);
  assert.deepEqual(outcome.conflict, { kind: "none" });
  const record = session.lastReviewBatchRecord();
  assert.equal(record?.pr, 42);
  assert.deepEqual(record?.counts, { actionable: 1 });
  assert.deepEqual(record?.resolved_thread_ids, ["PRRT_1", "PRRT_2"]);
  assert.ok(!Number.isNaN(Date.parse(record?.at ?? "")));
});

test("conflicted publish + resolve ok ⇒ the decision runs only after corroborated resolve", async () => {
  const change = { ...CHANGE, mergeable: false as const, conflicts: ["a.py"] };
  const { deps, calls, writes } = world({
    publish: { ok: true, change },
    resolve: { ok: true, rows: rowsOf(["PRRT_1", true, true]) },
  });
  const outcome = await finalizeAddress(deps, batch({ thread_id: "PRRT_1" }));
  assert.ok(outcome.kind === "completed");
  assert.deepEqual(outcome.conflict, { kind: "drive", base: "main", attempt: 1, cap: 2 });
  assert.deepEqual(writes, [1], "one increment, decided after resolve success");
  // The conflicted arm's full trace pins record-before-decision: EVERY conflict-decision event
  // (the decision's read + increment write) lands strictly AFTER apply(record-review-batch).
  assert.deepEqual(calls, [
    "publish",
    "pointer",
    "resolve",
    "apply(record-review-batch)",
    "attempts.read",
    "attempts.write(1)",
  ]);
});

test("conflicted publish + resolve failure ⇒ NO counter activity (never burn an attempt)", async () => {
  const change = { ...CHANGE, mergeable: false as const };
  const { deps, writes, session } = world({
    publish: { ok: true, change },
    resolve: { ok: false, kind: "failed", message: "boom", errorType: "github_error" },
  });
  const outcome = await finalizeAddress(deps, batch({ thread_id: "PRRT_1" }));
  assert.equal(outcome.kind, "published_unverified");
  assert.deepEqual(writes, [], "no reset (conflicted), no increment (resolve failed)");
  assert.equal(session.lastReviewBatchRecord(), null);
});

// --- the fates/retry matrix -------------------------------------------------------------------

test("retry derivation: success omitted; positive not-posted keeps the reply; posted strips; no row ⇒ unknown, stripped", async () => {
  const { deps } = world({
    resolve: {
      ok: false,
      kind: "partial",
      rows: rowsOf(["A", true, true], ["B", false, false], ["C", false, true]),
      message: "2 thread(s) did not resolve",
      errorType: "partial_failure",
    },
  });
  const outcome = await finalizeAddress(
    deps,
    batch(
      { thread_id: "A", comment: "resolved reply" },
      { thread_id: "B", comment: "kept — positively not posted" },
      { thread_id: "C", comment: "stripped — already posted" },
      { thread_id: "D", comment: "stripped — no row (unknown)" },
    ),
  );
  assert.ok(outcome.kind === "published_partial");
  assert.deepEqual(outcome.retryThreads, [
    { thread_id: "B", comment: "kept — positively not posted" },
    { thread_id: "C" },
    { thread_id: "D" },
  ]);
  assert.deepEqual(outcome.resolvedThreadIds, ["A"]);
  assert.equal(outcome.errorType, "partial_failure");
  assert.match(outcome.message, /only details\.retry_threads/);
});

test("D1: a success envelope with CONTRADICTORY duplicate rows ⇒ partial, retry stripped, no record", async () => {
  // Version-skew evidence: rows for A disagree on `success` (false then true — last-wins would
  // erase the failure observation). The corroboration guard refuses it: nothing recorded,
  // nothing termination-eligible, and A is retried WITHOUT its reply (outcome unknowable).
  const { deps, writes, session } = world({
    resolve: { ok: true, rows: rowsOf(["A", false, true], ["A", true, false]) },
  });
  const outcome = await finalizeAddress(deps, batch({ thread_id: "A", comment: "stripped" }));
  assert.ok(outcome.kind === "published_partial");
  assert.equal(
    outcome.resolveMessage,
    "the resolve report did not corroborate 1 requested thread(s)",
  );
  assert.deepEqual(outcome.retryThreads, [{ thread_id: "A" }]);
  assert.equal(session.lastReviewBatchRecord(), null, "nothing recorded on contradiction");
  assert.deepEqual(writes, [], "no conflict decision on an uncorroborated success");
});

test("requested dupes dedupe by FIRST occurrence; conflicting duplicate ROWS ⇒ last wins", async () => {
  const { deps } = world({
    resolve: {
      ok: false,
      kind: "partial",
      // Duplicate rows for A: the LAST observation (success:false, comment_added:false) wins.
      rows: rowsOf(["A", true, true], ["A", false, false]),
      message: "1 thread(s) did not resolve",
      errorType: "partial_failure",
    },
  });
  const outcome = await finalizeAddress(
    deps,
    batch(
      { thread_id: "A", comment: "first occurrence wins" },
      { thread_id: "A", comment: "ignored duplicate request" },
    ),
  );
  assert.ok(outcome.kind === "published_partial");
  assert.deepEqual(outcome.retryThreads, [{ thread_id: "A", comment: "first occurrence wins" }]);
});

test("all-success ⇒ empty retry (the partial arm keeps the inspect guidance)", async () => {
  const { deps } = world({
    resolve: {
      ok: false,
      kind: "partial",
      rows: rowsOf(["A", true, true]),
      message: "reported partial despite all-success rows",
      errorType: "partial_failure",
    },
  });
  const outcome = await finalizeAddress(deps, batch({ thread_id: "A" }));
  assert.ok(outcome.kind === "published_partial");
  assert.deepEqual(outcome.retryThreads, []);
  assert.match(outcome.message, /Inspect the resolution failure before retrying/);
});

// --- the corroboration guard (a success envelope that does not corroborate) -------------------

test("corroboration: a success envelope with a missing row ⇒ published_partial, no record", async () => {
  const { deps, session } = world({
    resolve: { ok: true, rows: rowsOf(["PRRT_1", true, true]) },
  });
  const outcome = await finalizeAddress(
    deps,
    batch({ thread_id: "PRRT_1" }, { thread_id: "PRRT_2", comment: "stripped" }),
  );
  assert.ok(outcome.kind === "published_partial");
  assert.equal(
    outcome.resolveMessage,
    "the resolve report did not corroborate 1 requested thread(s)",
  );
  assert.equal(outcome.errorType, "partial_failure");
  assert.deepEqual(outcome.retryThreads, [{ thread_id: "PRRT_2" }]);
  assert.deepEqual(outcome.resolvedThreadIds, ["PRRT_1"]);
  assert.equal(session.lastReviewBatchRecord(), null, "nothing recorded on the skew arm");
});

test("corroboration: a success envelope with a failed row ⇒ published_partial, no decide", async () => {
  const change = { ...CHANGE, mergeable: false as const };
  const { deps, writes, session } = world({
    publish: { ok: true, change },
    resolve: { ok: true, rows: rowsOf(["PRRT_1", false, false]) },
  });
  const outcome = await finalizeAddress(deps, batch({ thread_id: "PRRT_1", comment: "kept" }));
  assert.ok(outcome.kind === "published_partial");
  assert.deepEqual(outcome.retryThreads, [{ thread_id: "PRRT_1", comment: "kept" }]);
  assert.deepEqual(writes, [], "no conflict decision on an uncorroborated success");
  assert.equal(session.lastReviewBatchRecord(), null);
});

test("corroboration: a success envelope with EMPTY rows ⇒ published_partial", async () => {
  const { deps, session } = world({ resolve: { ok: true, rows: [] } });
  const outcome = await finalizeAddress(deps, batch({ thread_id: "PRRT_1" }));
  assert.ok(outcome.kind === "published_partial");
  assert.equal(
    outcome.resolveMessage,
    "the resolve report did not corroborate 1 requested thread(s)",
  );
  assert.equal(session.lastReviewBatchRecord(), null);
});

// --- published_unverified ----------------------------------------------------------------------

test("a plain resolve failure ⇒ published_unverified with the inspect guidance", async () => {
  const { deps, session } = world({
    resolve: { ok: false, kind: "failed", message: "boom", errorType: "github_error" },
  });
  const outcome = await finalizeAddress(deps, batch({ thread_id: "PRRT_1" }));
  assert.deepEqual(outcome, {
    kind: "published_unverified",
    change: CHANGE,
    resolveMessage: "boom",
    message:
      "propagation succeeded, but thread resolution failed: boom. The submit already " +
      "succeeded. Inspect the resolution failure before retrying; omit any reply that may " +
      "already have posted.",
    errorType: "github_error",
  });
  assert.equal(session.lastReviewBatchRecord(), null);
});

// --- failed session recording -------------------------------------------------------------------

test("a failed session recording never sinks a corroborated completion (rejected + unverified)", async () => {
  for (const induce of ["failNextApply", "failNextApplyVerification"] as const) {
    const { deps, session } = world({
      resolve: { ok: true, rows: rowsOf(["PRRT_1", true, true]) },
    });
    session[induce]();
    const outcome = await finalizeAddress(deps, batch({ thread_id: "PRRT_1" }));
    assert.equal(outcome.kind, "completed", induce);
    if (induce === "failNextApply") {
      assert.equal(session.lastReviewBatchRecord(), null, "the rejected apply landed nothing");
    } else {
      // The unverified arm landed the value in the memory backing — the attempt is observable.
      assert.deepEqual(session.lastReviewBatchRecord()?.resolved_thread_ids, ["PRRT_1"]);
    }
  }
});
