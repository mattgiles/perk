// The curated-submission policy matrix — Pi-free feature tests over deterministic fakes
// (submitter/gate) plus the production in-memory WorkflowSession double. Every enumerated
// `SubmitCuratedOutcome` arm is reached: the gate ladder (dry-run bypass, already_posted /
// allowRepost, headless refusal, user_declined, comment-no-confirm), bad_anchors table data,
// submit_failed passthrough, and the session-change ordering (record-review →
// append-review-post, BOTH always attempted, classifications ignored).

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type MemoryWorkflowSession,
  openMemoryWorkflowSession,
} from "../testing/memoryWorkflowSession.ts";
import {
  type CuratedSubmission,
  type FormalEventGate,
  type ReviewSubmitOutcome,
  type ReviewSubmitter,
  type SubmitBatch,
  submitCuratedReview,
} from "./submission.ts";

const OK_DATA = { pr: 42, event: "comment", mode: "review", comment_count: 2 };

function fakeSubmitter(outcome?: ReviewSubmitOutcome): {
  submitter: ReviewSubmitter;
  batches: SubmitBatch[];
} {
  const batches: SubmitBatch[] = [];
  return {
    batches,
    submitter: {
      submit(batch) {
        batches.push(batch);
        return Promise.resolve(outcome ?? { ok: true, data: { ...OK_DATA } });
      },
    },
  };
}

function interactiveGate(answer: boolean): {
  gate: FormalEventGate;
  confirms: { question: string; summary: string }[];
} {
  const confirms: { question: string; summary: string }[] = [];
  return {
    confirms,
    gate: {
      kind: "interactive",
      confirm(question, summary) {
        confirms.push({ question, summary });
        return Promise.resolve(answer);
      },
    },
  };
}

function input(overrides: Partial<CuratedSubmission> = {}): CuratedSubmission {
  return {
    pr: 42,
    event: "comment",
    body: "overall",
    dryRun: false,
    allowRepost: false,
    ...overrides,
  };
}

function session(): MemoryWorkflowSession {
  return openMemoryWorkflowSession({ runId: "RID" });
}

/** Silence the strict-append seam's loud stderr report for a deliberately induced failure. */
async function quietly<T>(fn: () => Promise<T>): Promise<T> {
  const original = console.error;
  console.error = () => {};
  try {
    return await fn();
  } finally {
    console.error = original;
  }
}

test("a formal event raises the confirm (wire event + count + first body line); declined → nothing submitted", async () => {
  const { submitter, batches } = fakeSubmitter();
  const { gate, confirms } = interactiveGate(false);
  const s = session();
  const outcome = await submitCuratedReview(
    input({
      event: "request-changes",
      body: "needs work\nsecond line",
      comments: [{ path: "a.ts", line: 12, body: "fix" }],
    }),
    { submitter, gate, session: s },
  );
  assert.equal(outcome.kind, "user_declined");
  assert.ok(
    outcome.kind === "user_declined" &&
      outcome.message === "user declined the request-changes review — nothing was submitted",
  );
  assert.equal(confirms.length, 1);
  assert.equal(confirms[0]?.question, "Post REQUEST_CHANGES review to PR #42?");
  assert.match(confirms[0]?.summary ?? "", /1 inline comment\(s\)/);
  assert.match(confirms[0]?.summary ?? "", /needs work/);
  assert.doesNotMatch(confirms[0]?.summary ?? "", /second line/);
  assert.equal(batches.length, 0, "nothing submitted on decline");
  assert.deepEqual(s.reviewPosts(), [], "no ledger row on decline");
});

test("an accepted confirm proceeds to the submitter", async () => {
  const { submitter, batches } = fakeSubmitter();
  const { gate, confirms } = interactiveGate(true);
  const outcome = await submitCuratedReview(input({ event: "approve", body: "" }), {
    submitter,
    gate,
    session: session(),
  });
  assert.equal(confirms.length, 1);
  assert.equal(batches.length, 1);
  assert.equal(outcome.kind, "posted");
});

test("a comment event never confirms", async () => {
  const { submitter, batches } = fakeSubmitter();
  const { gate, confirms } = interactiveGate(true);
  await submitCuratedReview(input(), { submitter, gate, session: session() });
  assert.equal(confirms.length, 0);
  assert.equal(batches.length, 1);
});

test("the headless gate arm refuses a formal event with today's message; comment passes", async () => {
  const { submitter, batches } = fakeSubmitter();
  const gate: FormalEventGate = { kind: "headless" };
  const refused = await submitCuratedReview(input({ event: "approve", body: "" }), {
    submitter,
    gate,
    session: session(),
  });
  assert.equal(refused.kind, "headless_formal_event");
  assert.ok(
    refused.kind === "headless_formal_event" &&
      refused.message ===
        "headless sessions cannot post formal review verdicts — re-run interactively or use " +
          "event: comment",
  );
  assert.equal(batches.length, 0, "nothing submitted on the headless refusal");

  const posted = await submitCuratedReview(input(), { submitter, gate, session: session() });
  assert.equal(posted.kind, "posted");
});

test("dryRun bypasses the resume guard AND both gate arms; the batch carries dryRun", async () => {
  const { submitter, batches } = fakeSubmitter({ ok: true, data: { dry_run: true, pr: 42 } });
  const s = openMemoryWorkflowSession({
    runId: "RID",
    reviewPosts: [{ pr: 42, event: "comment", at: "t0" }],
  });
  const outcome = await submitCuratedReview(input({ event: "approve", body: "", dryRun: true }), {
    submitter,
    gate: { kind: "headless" },
    session: s,
  });
  assert.equal(outcome.kind, "dry_run_ok");
  assert.equal(batches.length, 1);
  assert.equal(batches[0]?.dryRun, true);
  assert.deepEqual(s.reviewPosts(), [{ pr: 42, event: "comment", at: "t0" }], "no new row");
  assert.equal(s.lastReviewRecord(), null, "no record on dry-run");
});

test("the resume guard refuses a repeat real post BEFORE the confirm and the submitter", async () => {
  // The envelope carries no `pr`, so each record falls back to its own call's param.
  const { submitter, batches } = fakeSubmitter({ ok: true, data: { mode: "review" } });
  const { gate, confirms } = interactiveGate(true);
  const s = openMemoryWorkflowSession({
    runId: "RID",
    reviewPosts: [{ pr: 41, event: "comment", at: "2026-01-01T00:00:00Z" }],
  });
  const outcome = await submitCuratedReview(input({ pr: 41, event: "approve", body: "again" }), {
    submitter,
    gate,
    session: s,
  });
  assert.equal(outcome.kind, "already_posted");
  assert.ok(outcome.kind === "already_posted");
  // The prior row's identity is user-visible evidence IN the message (no structural payload).
  assert.equal(
    outcome.message,
    "a comment review was already posted to PR #41 in this session " +
      "(review_posts row at 2026-01-01T00:00:00Z) — on a stack resume skip this member; pass " +
      "allow_repost: true only for a deliberate second review of the same PR",
  );
  assert.equal(batches.length, 0, "the guard refuses BEFORE the submitter");
  assert.equal(confirms.length, 0, "the guard refuses BEFORE the confirm dialog");

  // The deliberate escape hatch: allowRepost posts a second review to the same PR.
  const deliberate = await submitCuratedReview(input({ pr: 41, allowRepost: true }), {
    submitter,
    gate,
    session: s,
  });
  assert.equal(deliberate.kind, "posted");
  // Another PR was never blocked.
  const other = await submitCuratedReview(input({ pr: 42 }), { submitter, gate, session: s });
  assert.equal(other.kind, "posted");
});

test("the guard refuses on the LAST matching ledger row (absence stays silent)", async () => {
  const { submitter } = fakeSubmitter();
  const s = openMemoryWorkflowSession({
    runId: "RID",
    reviewPosts: [
      { pr: 41, event: "comment", at: "t1" },
      { pr: 41, event: "request-changes", at: "t2" },
    ],
  });
  const outcome = await submitCuratedReview(input({ pr: 41 }), {
    submitter,
    gate: { kind: "headless" },
    session: s,
  });
  assert.equal(outcome.kind, "already_posted");
  assert.ok(outcome.kind === "already_posted" && /review_posts row at t2/.test(outcome.message));
});

test("bad_anchors renders the per-comment repair table into the policy message", async () => {
  const invalid = [
    { index: 0, path: "a.ts", line: 999, side: "RIGHT", reason: "line not in diff" },
  ];
  const { submitter } = fakeSubmitter({
    ok: false,
    kind: "bad_anchors",
    invalid,
    message: "1 of 2 comment anchor(s) not in the PR diff — repair and retry",
  });
  const s = session();
  const outcome = await submitCuratedReview(input({ dryRun: true }), {
    submitter,
    gate: { kind: "headless" },
    session: s,
  });
  assert.equal(outcome.kind, "bad_anchors");
  assert.ok(outcome.kind === "bad_anchors");
  // The repair detail is user-visible IN the rendered table (no structural payload).
  assert.equal(
    outcome.message,
    "1 of 2 comment anchor(s) not in the PR diff — repair and retry\n" +
      "  comment[0] a.ts:999 (RIGHT) — line not in diff\n" +
      "repair these anchors and re-run with dry_run: true",
  );
  assert.deepEqual(s.reviewPosts(), [], "a failed submission never touches the ledger");
});

test("a failed submission passes message + errorType through verbatim, no session writes", async () => {
  const { submitter } = fakeSubmitter({
    ok: false,
    kind: "failed",
    message: "gh is not authenticated",
    errorType: "github_unauthed",
  });
  const s = session();
  const outcome = await submitCuratedReview(input(), {
    submitter,
    gate: { kind: "headless" },
    session: s,
  });
  assert.deepEqual(outcome, {
    kind: "submit_failed",
    message: "gh is not authenticated",
    errorType: "github_unauthed",
  });
  assert.equal(s.lastReviewRecord(), null);
  assert.deepEqual(s.reviewPosts(), []);
});

test("a real success applies record-review then append-review-post, in order", async () => {
  const { submitter } = fakeSubmitter();
  const s = session();
  const applied: string[] = [];
  const spied = {
    ...s,
    apply(change: Parameters<MemoryWorkflowSession["apply"]>[0]) {
      applied.push(change.kind);
      return s.apply(change);
    },
  };
  const outcome = await submitCuratedReview(input(), {
    submitter,
    gate: { kind: "headless" },
    session: spied,
  });
  assert.equal(outcome.kind, "posted");
  assert.deepEqual(applied, ["record-review", "append-review-post"]);
  assert.ok(outcome.kind === "posted");
  // The record's shape: envelope fields win; the row mirrors the record's pr/at.
  assert.equal(outcome.record.pr, 42);
  assert.equal(outcome.record.event, "comment");
  assert.equal(outcome.record.comment_count, 2);
  assert.equal(outcome.record.mode, "review");
  assert.ok(!Number.isNaN(Date.parse(outcome.record.at)));
  assert.deepEqual(s.lastReviewRecord(), outcome.record);
  // The ledger-row session effect mirrors the record's pr/at (the row is not a return payload).
  assert.deepEqual(s.reviewPosts(), [{ pr: 42, event: "comment", at: outcome.record.at }]);
});

test("the record falls back to the input pr and nulls when the envelope omits fields", async () => {
  const { submitter } = fakeSubmitter({ ok: true, data: {} });
  const s = session();
  const outcome = await submitCuratedReview(input({ pr: 7 }), {
    submitter,
    gate: { kind: "headless" },
    session: s,
  });
  assert.ok(outcome.kind === "posted");
  assert.equal(outcome.record.pr, 7);
  assert.equal(outcome.record.comment_count, null);
  assert.equal(outcome.record.mode, null);
});

test("BOTH session changes are always attempted — a rejected record never skips the ledger row", async () => {
  const { submitter } = fakeSubmitter();
  const s = session();
  s.failNextApply(); // record-review rejects; append-review-post must still be attempted
  const outcome = await quietly(() =>
    submitCuratedReview(input(), {
      submitter,
      gate: { kind: "headless" },
      session: s,
    }),
  );
  assert.equal(outcome.kind, "posted", "the classifications are ignored — the post succeeded");
  assert.equal(s.lastReviewRecord(), null, "the rejected record landed nothing");
  assert.equal(s.reviewPosts().length, 1, "the ledger row was still attempted and landed");
});

test("the port batch never carries allowRepost (feature ledger policy stays behind the boundary)", async () => {
  const { submitter, batches } = fakeSubmitter();
  await submitCuratedReview(input({ allowRepost: true }), {
    submitter,
    gate: { kind: "headless" },
    session: session(),
  });
  assert.equal(batches.length, 1);
  assert.deepEqual(Object.keys(batches[0] ?? {}).sort(), ["body", "dryRun", "event", "pr"]);
});
